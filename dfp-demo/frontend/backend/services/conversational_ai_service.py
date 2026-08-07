"""
DFP Conversational AI Service
==============================
Three-pass pipeline (no keyword routing, no rule-based intent classification):

  Pass 0  _analyse_intent()  — LLM (no tools) produces a structured intent analysis
  Pass 1  route_query()      — LLM reads intent analysis + tool schemas → calls ALL relevant tools
  Pass 2  _execute_tool()    — executes chosen _fetch_* methods against real data
  Pass 3  generate_answer()  — LLM synthesises a grounded natural-language answer

Tool descriptions contain ONLY data-schema information (what columns/fields are returned
and what parameters control the query). All reasoning about which tool to call lives
in the router system prompt and the intent analysis, not in tool wording.
"""

from __future__ import annotations

import json
import logging
import os
import pathlib
import re
import time
from typing import Any

import psycopg2.extras

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Database schema — loaded once at import time from config/db_schema.md.
# Edit that file to add columns/JSONB paths; restart backend to pick up changes.
# ---------------------------------------------------------------------------

_SCHEMA_FILE = pathlib.Path(__file__).parent.parent.parent.parent / "config" / "db_schema.md"

try:
    _DB_SCHEMA: str = _SCHEMA_FILE.read_text(encoding="utf-8")
    logger.info("Loaded DB schema from %s (%d bytes)", _SCHEMA_FILE, len(_DB_SCHEMA))
except FileNotFoundError:
    _DB_SCHEMA = "(schema file not found — query_database tool will have limited context)"
    logger.warning("DB schema file not found at %s", _SCHEMA_FILE)

# Compact schema for the router — only what's needed to pick tools and write simple SQL.
# The full _DB_SCHEMA is injected into query_database calls at execution time.
_ROUTER_SCHEMA = """\
TABLE enriched_anomalies:
  anomaly_id(uuid PK), user_id(email FK→monitored_users.username), timestamp, risk_score(float 0-100),
  severity(CRITICAL|HIGH|MEDIUM|LOW), root_cause(text), status(new|pending|resolved),
  assigned_to(integer FK→analyst_users.id), validated_by, created_at
  JSONB original_event:
    ->>'callerIpAddress'                       IP address
    ->'location'->>'city'                      Sign-in city
    ->'location'->>'countryOrRegion'           Sign-in country
    ->'properties'->>'appDisplayName'          Application name
    ->'properties'->'deviceDetail'->>'operatingSystem'   OS
    ->'properties'->'deviceDetail'->>'browser' Browser
    ->'properties'->'deviceDetail'->>'displayName'       Device name
  JSONB raw_detection: ->>'top_features'(text summary), ->'features'(array of {feature,value,z_score})

TABLE monitored_users:
  id(PK), username(email = ea.user_id), display_name, department, job_title, seniority, company,
  primary_location_city, primary_location_country, primary_os, primary_browser, primary_device,
  work_hours_start, work_hours_end, active_days(text[]), corp_vpn(bool),
  apps(jsonb array [{name,frequency}]), devices(jsonb), all_locations(jsonb)

TABLE llm_explanations:
  id(PK), detection_id(FK→anomaly_id), context_analysis(text), risk_assessment(text),
  recommendations(text), confidence_score(0-1), hallucination_risk(low|medium|high),
  anomaly_classification(jsonb {label,confidence}), severity_level, created_at

TABLE agent_investigations:
  investigation_id(uuid PK), anomaly_id(FK), triggered_at, completed_at,
  status(pending|running|completed|failed), confidence_score, overall_recommendation, raw_report(jsonb)

TABLE agent_findings:
  finding_id(uuid PK), investigation_id(FK), agent_type(forensics|investigation|remediation),
  status, result(jsonb {narrative,attack_chain[],entry_point,entities_involved[],lateral_movement_detected})

TABLE analyst_users:
  id(PK), username(email), display_name, analyst_role, level, is_active

JOINS:
  ea.user_id = mu.username
  ea.anomaly_id = le.detection_id
  ea.anomaly_id = ai.anomaly_id
  ai.investigation_id = af.investigation_id
  ea.assigned_to = au.id
"""


class _RateLimitError(Exception):
    """Raised when the Groq API returns HTTP 429 (daily token quota exhausted)."""

    def __init__(self, retry_after: str = "") -> None:
        self.retry_after = retry_after
        super().__init__(retry_after)


# ---------------------------------------------------------------------------
# Tool catalogue — OpenAI-compatible function-calling schema
# The LLM reads these descriptions to decide which tools to invoke.
# Wording is carefully chosen to guide reasoning, not to hard-code rules.
# ---------------------------------------------------------------------------

DFP_CHAT_TOOLS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "search_anomalies",
            "description": (
                "Filter and search anomaly records by severity, username, or date range. "
                "Returns matching records with risk scores, severities, timestamps, and root causes."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "severity": {
                        "type": "string",
                        "enum": ["CRITICAL", "HIGH", "MEDIUM", "LOW"],
                        "description": "Filter anomalies by this severity level only.",
                    },
                    "username": {
                        "type": "string",
                        "description": "Return anomalies for this specific user only.",
                    },
                    "days": {
                        "type": "integer",
                        "description": "Limit results to the last N days. 0 means all time.",
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Max records to return (default 5). For pagination pass offset.",
                    },
                    "offset": {
                        "type": "integer",
                        "description": "Skip this many records (default 0). Use to fetch the next page.",
                    },
                    "sort_by": {
                        "type": "string",
                        "enum": ["risk_score_desc", "timestamp_desc"],
                        "description": "Sort order. Use 'timestamp_desc' for most recent/latest/newest anomalies. Use 'risk_score_desc' (default) for highest-risk anomalies.",
                    },
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_anomaly_detail",
            "description": (
                "Get full details for a single anomaly by its UUID, including LLM explanation, "
                "forensic evidence, agent findings, and investigation summary."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "anomaly_id": {
                        "type": "string",
                        "description": "The anomaly UUID (e.g. '3fa85f64-5717-4562-b3fc-2c963f66afa6').",
                    }
                },
                "required": ["anomaly_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_user_profile",
            "description": (
                "Returns a specific monitored user's complete profile (job title, location, department), "
                "their full anomaly history statistics (total, critical/high/medium/low counts, avg risk score), "
                "and their five most recent anomaly records."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "username": {
                        "type": "string",
                        "description": "The username to look up (exact match).",
                    }
                },
                "required": ["username"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "semantic_search_anomalies",
            "description": (
                "Semantic vector search across all anomaly records using Qdrant (all-MiniLM-L6-v2, "
                "384-dim cosine similarity). Returns individual anomaly records with similarity_score "
                "(0.0\u20131.0) ranked by semantic closeness to the query. Also searches root cause, "
                "classification reasoning, and LLM analysis text. Falls back to SQL keyword search "
                "when Qdrant is unavailable."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Natural-language description of the threat, behaviour, or attack to search for.",
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Number of semantically similar anomalies to return (default 5, max 20).",
                    },
                    "min_similarity": {
                        "type": "number",
                        "description": "Minimum cosine similarity (0.0–1.0, default 0.3). Lower returns more results.",
                    },
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_risk_summary",
            "description": (
                "Returns aggregate platform-wide statistics: total anomaly counts broken down by severity band, "
                "unique user count, all monitored users ranked by their anomaly count with per-severity breakdown, "
                "and a 14-day daily trend. "
                "This tool returns statistical summaries only — it does not return individual anomaly records."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "days": {
                        "type": "integer",
                        "description": "Analysis window in days (default 0 = all time).",
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Number of users to return (default 5). For pagination pass offset.",
                    },
                    "offset": {
                        "type": "integer",
                        "description": "Skip this many users (default 0). Use to fetch the next page.",
                    },
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_top_anomalies",
            "description": (
                "Returns individual anomaly records sorted by risk score descending. "
                "Provides the highest-risk anomaly records with severity, timestamps, root causes, and status."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "limit": {
                        "type": "integer",
                        "description": "Number of top anomalies to return (default 5).",
                    },
                    "days": {
                        "type": "integer",
                        "description": "Restrict to anomalies detected in the last N days (0 = all time).",
                    },
                    "offset": {
                        "type": "integer",
                        "description": "Skip this many records (default 0). Use to fetch the next page.",
                    },
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_investigation",
            "description": (
                "Returns AI multi-agent investigation records for anomalies. Each record contains: "
                "forensic agent findings (attack chain, entry point, lateral movement), "
                "investigation agent findings (root cause analysis, behavioural patterns), "
                "remediation agent findings (recommended actions with priority, compliance flags, escalation status), "
                "overall recommendation, confidence score, and agents invoked. "
                "This tool returns what the AI agents discovered and recommended for investigated anomalies."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "username": {
                        "type": "string",
                        "description": "Filter investigations to anomalies for a specific user (optional).",
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Number of investigations to return (default 5).",
                    },
                    "offset": {
                        "type": "integer",
                        "description": "Skip this many records (default 0). Use to fetch the next page.",
                    },
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_neo4j_graph",
            "description": (
                "Returns network-topology relationship edges from the Neo4j knowledge graph: "
                "who-accessed-what connections between user accounts, IP addresses, devices, "
                "applications, and corporate resources. Each edge has relationship_type, "
                "source_labels, source_name, target_labels, target_name. "
                "This is graph connectivity data, not geographic or statistical data."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "entity": {
                        "type": "string",
                        "description": "Entity name (username, IP, or resource) to find graph relationships for.",
                    }
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_root_cause_summary",
            "description": (
                "Returns aggregate statistics grouped by root cause category: occurrence counts and average risk scores. "
                "Also returns sub-category distribution counts. "
                "This tool returns statistical summaries only — it does not return individual anomaly records."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "days": {
                        "type": "integer",
                        "description": "Analysis window in days (default 30, 0 = all time).",
                    }
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_llm_explanations",
            "description": (
                "Returns LLM-generated analytical explanation records. Each record contains: "
                "context_analysis (what happened), pattern_analysis (behavioural pattern identified), "
                "anomaly_classification (true_positive/false_positive/uncertain), risk_assessment, "
                "recommendations, reasoning_process, evidence_summary, similar_cases_cited, "
                "graph_insights_used, confidence_score, hallucination_risk, and cold_start flag. "
                "Filterable by specific anomaly_id, severity, or classification result."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "anomaly_id": {
                        "type": "string",
                        "description": "UUID of a specific anomaly to get the LLM explanation for.",
                    },
                    "severity": {
                        "type": "string",
                        "enum": ["CRITICAL", "HIGH", "MEDIUM", "LOW"],
                        "description": "Filter explanations by severity_level.",
                    },
                    "classification": {
                        "type": "string",
                        "enum": ["true_positive", "false_positive", "uncertain"],
                        "description": "Filter by anomaly classification result.",
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Number of explanation records to return (default 5, max 20).",
                    },
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_user_behaviour_baseline",
            "description": (
                "Returns the established normal behaviour baseline from monitored_users: "
                "work_hours_start/end, active_days, primary_os, primary_browser, primary_device, "
                "apps used with frequencies, all_locations, corp_vpn, total_events. "
                "Filterable by username or department. Statistics only — no anomaly records."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "username": {
                        "type": "string",
                        "description": "Username (email) of the specific user to get baseline for.",
                    },
                    "department": {
                        "type": "string",
                        "description": "Filter users by department (e.g. 'Engineering', 'Finance').",
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Number of users to return when browsing by department (default 10).",
                    },
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_anomaly_timeline",
            "description": (
                "Returns time-series anomaly data aggregated by day or week: anomaly_count, "
                "avg_risk_score, max_risk_score, critical/high/medium/low counts per period, "
                "unique_users_affected, and a computed trend field (increasing/decreasing/stable). "
                "Scopeable to a specific user or platform-wide."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "username": {
                        "type": "string",
                        "description": "Optional: scope the timeline to a specific user.",
                    },
                    "days": {
                        "type": "integer",
                        "description": "Time window in days (default 30, max 365).",
                    },
                    "granularity": {
                        "type": "string",
                        "enum": ["daily", "weekly"],
                        "description": "Aggregation granularity (default daily).",
                    },
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_dimension_ranking",
            "description": (
                "Aggregates all anomaly records by any specified event dimension and ranks entities "
                "within that dimension by anomaly severity. Returns each entity's anomaly_count, "
                "max_risk_score, avg_risk_score, critical_count, high_count, and top_users affected. "
                "Supported dimensions: city, country, location (city+country), ip_address, user, "
                "severity, root_cause, sub_category, app, device, browser, os, status. "
                "Use to answer 'which X is most anomalous' or 'rank by X' for any dimension."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "dimension": {
                        "type": "string",
                        "description": (
                            "The dimension to group and rank by. "
                            "Supported values: city, country, location, ip_address, user, "
                            "severity, root_cause, sub_category, app, device, browser, os, status."
                        ),
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Number of top entities to return (default 10, max 30).",
                    },
                    "days": {
                        "type": "integer",
                        "description": "Restrict to anomalies from the last N days (default 0 = all time).",
                    },
                },
                "required": ["dimension"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "query_database",
            "description": (
                "Execute a read-only SELECT query directly against the DFP PostgreSQL database. "
                "Use for any question a specific tool cannot answer: filtering on any column "
                "(assigned_to, validated_by, resolved_at, classification_reasoning, cost_usd, etc.), "
                "sorting by timestamp, JOINing tables, computing arbitrary aggregations, or accessing "
                "columns/JSONB paths not returned by other tools. "
                "Returns rows as a list of objects plus a row_count. "
                "Write correct SQL using the schema provided in the system prompt."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "sql": {
                        "type": "string",
                        "description": (
                            "A valid PostgreSQL SELECT statement. "
                            "Must start with SELECT (no INSERT/UPDATE/DELETE/DROP/TRUNCATE). "
                            "Must include LIMIT (max 100). "
                            "Use exact column names and JSONB paths from the schema in the system prompt."
                        ),
                    },
                },
                "required": ["sql"],
            },
        },
    },
]

# ---------------------------------------------------------------------------
# System prompt for Pass 0 (intent analysis — no tool calls)
# ---------------------------------------------------------------------------

_INTENT_ANALYSIS_SYSTEM = """\
You are an intent analyser for a security anomaly detection platform.
Given the user's question, produce a structured analysis in exactly this format:

LABEL: 2-5 word category — use EXACTLY "Off-Topic" for any question unrelated to cybersecurity,
  anomaly detection, user behaviour, or the DFP platform (e.g. cooking, sports, weather, coding help).
  Otherwise pick the BEST match from these — read the definitions carefully:
    Greeting            — salutation only, no data question
    Location Query      — asks which city/country/IP has the most anomalies or where something happened
    User Investigation  — asks about a named user's behaviour, history, or profile
    Threat Search       — asks to find, retrieve, or describe one or more specific anomaly records
                          (including "latest", "most recent", "last", "show me anomalies", "what happened")
    Timeline Query      — asks how anomaly counts or risk changed over time / trend analysis
    Risk Overview       — asks for AGGREGATE platform-wide statistics: totals, averages, top-user rankings,
                          severity distribution; NOT for retrieving individual anomaly records
    Operational Query   — asks about investigation status, analyst assignments, remediation actions,
                          compliance flags, or agent findings
    Conceptual Question — asks what something means or how the platform works
INTENT: What the user wants to know (one sentence, focus on answer shape not restatement)
DIMENSIONS: Data dimensions that matter (e.g. location/city, user, device, ip, time, severity, app, root_cause)
AGGREGATION: ranking / single-best / filtering / comparison / listing / count / drill-down
ENTITIES: Specific names, IDs, or dates mentioned — or 'none'
ANSWER SHAPE: ranked table / single value / narrative / distribution chart
CONFIDENCE: 0-100 integer — how completely answerable is this from the anomaly database

Be concise. LABEL and CONFIDENCE are required on every response.\
"""

# ---------------------------------------------------------------------------
# System prompt for Pass 1 (router)
# ---------------------------------------------------------------------------

_ROUTER_SYSTEM = f"""\
You are the tool-selection engine for a NVIDIA Morpheus Digital Fingerprinting (DFP) security platform.
You will receive a structured INTENT ANALYSIS followed by the user's raw question.

YOUR ONLY JOB: decide which tools to call (and with what parameters) so the answering LLM has
all the data it needs, in the right shape, to answer the question completely.

STRICT RULES:
1. Read the INTENT ANALYSIS first. It tells you the answer shape, dimensions, and aggregations needed.
2. Select EVERY tool whose data contributes to a complete answer — never just one if more are relevant.
3. Parameters must match the intent: if the user wants top-10, pass limit=10; if scoped to a user, pass username.
4. For 'most anomalous X' questions (location, device, IP, app, etc.), call get_dimension_ranking(dimension=X)
   PLUS get_top_anomalies so the answer has both the ranking AND representative record detail.
5. For questions about a named user, call BOTH get_user_profile AND get_user_behaviour_baseline.
6. Never call get_neo4j_graph for geographic or statistical questions — it returns graph connectivity edges only.
7. If the message is a greeting or entirely off-topic, call NO tools.

AVAILABLE DATA (what each tool fetches — read these to pick the right ones):
- search_anomalies          → individual anomaly records with structured filters (severity, username, date range, sort_by). Use sort_by=timestamp_desc for "most recent / latest / newest" queries; default sort is risk_score_desc.
- semantic_search_anomalies → anomaly records ranked by vector similarity to a text description; also covers text fields
- get_anomaly_detail        → single anomaly full record (only when user provides a UUID)
- get_user_profile          → one named user: profile, anomaly stats, last 5 anomaly records
- get_user_behaviour_baseline → normal behaviour baseline: work hours, active days, devices, apps, locations, VPN
- get_risk_summary          → platform-wide aggregate stats: severity counts, user rankings, 14-day trend
- get_top_anomalies         → individual anomaly records sorted by risk score desc; each record now includes event_city, event_country, event_ip
- get_investigation         → AI agent findings: forensics, attack chain, root cause, remediation actions, escalation
- get_llm_explanations      → LLM analytical explanation records per anomaly: classification, evidence, confidence, hallucination risk
- get_root_cause_summary    → aggregate stats grouped by root_cause category (counts, avg risk)
- get_anomaly_timeline      → time-series daily/weekly anomaly counts and risk scores; trend direction
- get_neo4j_graph           → network-topology graph edges (who accessed what): user→IP→resource connectivity
- get_dimension_ranking     → top-N entities ranked by max risk for ANY dimension: city, country, ip_address, user, device, app, browser, os, root_cause, severity, status
- query_database            → execute any read-only SELECT query; use when no specific tool covers the question

WHEN TO USE query_database:
- Use it for any question a specific tool cannot answer: sorting by timestamp instead of risk,
  filtering on columns not exposed by other tools (assigned_to, validated_by, resolution_notes,
  classification_reasoning, cost_usd, latency_ms, etc.), multi-table JOINs, ad-hoc aggregations.
- Combine it with specific tools when both contribute to the answer.
- Always use the complete schema below to write correct column names and JSONB paths.
- Write minimal, precise SQL — SELECT only the columns needed, always include LIMIT.

COMPACT SCHEMA (for query_database SQL — use full column/JSONB names below):
{_ROUTER_SCHEMA}\
"""

# ---------------------------------------------------------------------------
# System prompt for Pass 3 (answerer)
# ---------------------------------------------------------------------------

_ANSWER_SYSTEM = (
    "You are a senior security analyst AI for a Digital Fingerprinting Platform (DFP), "
    "helping SOC teams understand user behaviour anomalies and insider-threat investigations.\n\n"
    "RULES:\n"
    "1. NO PREAMBLE: When real data is provided in the prompt, go straight to the analysis. "
    "Never open with a greeting, self-introduction, or pleasantry when data is present.\n"
    "2. GREETINGS ONLY when no data is provided: Respond briefly, mention your purpose, invite a question.\n"
    "3. OFF-TOPIC: Politely decline and redirect to platform topics.\n"
    "4. DATA RELEVANCE: Before writing your response, check whether the data returned actually answers "
    "the user's question. If the data is present but does not address what was asked (e.g. aggregate statistics "
    "were returned when the user wanted specific anomaly records, or the records do not match the described "
    "threat type), say so clearly: explain what the data does show, state what it does not show, and suggest "
    "a more targeted question the user can ask to get the specific information they need. "
    "Never present data as answering the question when it does not.\n"
    "5. DATA COMPLETENESS: When data does answer the question, use every relevant record fully. "
    "Do not skip or omit records that are present.\n"
    "6. PAGINATION: If 'total_matching' or 'unique_users' in the data exceeds the number of items shown, "
    "tell the user the total count and that they can ask for the next page.\n"
    "7. USER IDENTITY: When a USER PROFILES section is present, always refer to users by "
    "full name and title, never raw email. "
    "Format: **Full Name** (Title, Seniority, Dept, Company \u00b7 City, Country).\n"
    "8. FIELD NAMES: Translate all snake_case keys to natural English prose.\n"
    "9. NUMBERS: Risk scores on the 0\u2013100 scale, rounded to 1 decimal place.\n"
    "10. FORMAT: Bold headers and bullet lists for multi-item results; easy-to-scan layout.\n"
    "11. INVESTIGATIONS: List each recommended action with its priority and rationale. "
    "Flag any escalation-required or compliance issues.\n"
    "12. COMMENTARY: Add a brief analyst paragraph after listing data.\n"
    "13. Never invent IDs, dates, usernames, or numeric values not present in the data.\n"
    "14. SOURCE ATTRIBUTION: Each data section is labelled with [source: tool_name]. "
    "Cite sources naturally in prose (e.g. 'The semantic vector search identified...', "
    "'Agent investigation findings show...', 'According to the LLM explanation...'). "
    "Do not repeat source labels mechanically — integrate them naturally.\n"
    "15. SIMILARITY SCORES: When results include similarity_score (from semantic vector search), "
    "interpret as semantic relevance: >0.7 = strongly relevant, 0.4\u20130.7 = moderately relevant, "
    "<0.4 = loosely related. Mention this when discussing search results.\n"
    "16. BASELINE CONTEXT: When behaviour baseline data is provided alongside anomaly data, explicitly "
    "compare the detected anomalous behaviour against the normal baseline. Highlight specific deviations "
    "(e.g. activity outside work hours, unrecognised device, unknown location)."
)

# ---------------------------------------------------------------------------
# Source category labels — maps tool names to the source badge shown in the UI
# ---------------------------------------------------------------------------

_TOOL_SOURCE_LABELS: dict[str, str] = {
    "search_anomalies": "PostgreSQL",
    "get_anomaly_detail": "PostgreSQL",
    "get_top_anomalies": "PostgreSQL",
    "get_user_profile": "PostgreSQL",
    "get_user_behaviour_baseline": "PostgreSQL",
    "get_risk_summary": "PostgreSQL",
    "get_investigation": "PostgreSQL",
    "get_llm_explanations": "PostgreSQL",
    "get_root_cause_summary": "Analytics",
    "get_anomaly_timeline": "Analytics",
    "get_dimension_ranking": "Analytics",
    "query_database": "PostgreSQL",
    "semantic_search_anomalies": "Qdrant",
    "get_similar_anomalies": "Qdrant",
    "get_neo4j_graph": "Knowledge Graph",
}

# ---------------------------------------------------------------------------
# Human-readable display names for each tool (used in answer source labels)
# ---------------------------------------------------------------------------

_TOOL_DISPLAY_NAMES: dict[str, str] = {
    "search_anomalies": "Filtered Anomaly Search",
    "semantic_search_anomalies": "Semantic Vector Search (Qdrant)",
    "get_similar_anomalies": "Semantic Vector Search (Qdrant)",  # legacy alias
    "get_anomaly_detail": "Anomaly Detail Record",
    "get_user_profile": "User Profile",
    "get_user_behaviour_baseline": "User Behaviour Baseline",
    "get_risk_summary": "Platform Risk Summary",
    "get_top_anomalies": "Top Anomalies by Risk Score",
    "get_investigation": "AI Agent Investigation Findings",
    "get_llm_explanations": "LLM Analytical Explanations",
    "get_root_cause_summary": "Root Cause Distribution",
    "get_anomaly_timeline": "Anomaly Timeline & Trend",
    "get_neo4j_graph": "Knowledge Graph Relationships",
    "get_dimension_ranking": "Anomaly Dimension Ranking",
    "query_database": "Ad-hoc Database Query",
}


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------


class DFPConversationalAIService:
    """
    Conversational AI service for the DFP platform.

    Uses a two-pass function-calling pipeline:
      Pass 1 — route_query(): LLM selects tools (no rule-based classification).
      Pass 2 — _execute_tool(): fetches real data from PostgreSQL / Neo4j.
      Pass 3 — generate_answer(): LLM synthesises a grounded natural-language answer.

    Backend: configured via LLM_PROVIDER ('github' | 'groq' | 'ollama') and LLM_API_KEY.
    """

    def __init__(self) -> None:
        try:
            from openai import OpenAI
        except ImportError as exc:
            raise RuntimeError("openai package not installed — run: pip install openai") from exc

        llm_provider = os.getenv("LLM_PROVIDER", "github").lower()
        llm_api_key = os.getenv("LLM_API_KEY", "")

        if llm_provider == "github":
            self._client = OpenAI(
                base_url="https://models.inference.ai.azure.com",
                api_key=llm_api_key,
            )
            logger.info("Using GitHub Models backend")
        elif llm_provider == "groq":
            self._client = OpenAI(
                base_url="https://api.groq.com/openai/v1",
                api_key=llm_api_key,
            )
            logger.info("Using Groq backend")
        else:
            ollama_base = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434/v1")
            self._client = OpenAI(
                base_url=ollama_base,
                api_key="ollama",  # Ollama ignores the key but OpenAI client requires it
            )
            logger.info("Using Ollama backend at %s", ollama_base)

        self._router_model = os.getenv("LLM_ROUTER_MODEL", "gpt-4o-mini")
        self._answer_model = os.getenv("LLM_MAIN_MODEL", "Llama-3.3-70B-Instruct")
        self._max_retries = 3

        # Chat mode: "pipeline" (legacy 3-pass) or "agentic" (ReAct loop)
        self._chat_mode = os.getenv("CHAT_MODE", "pipeline").lower()
        self._agent_core: Any = None  # Lazy-initialised on first agentic call

        # Lazy-initialised Qdrant + sentence-transformers (loaded on first semantic search call)
        self._qdrant_ready: bool | None = None  # None = not yet attempted; False = unavailable
        self._embedding_svc: Any = None
        self._vector_store: Any = None

    # ------------------------------------------------------------------
    # Public entry point
    # ------------------------------------------------------------------

    def process_query(self, session_id: int, query: str) -> dict[str, Any]:
        """
        Full pipeline: route → fetch → answer → persist.

        Returns:
            {
                "answer": str,
                "tools_used": list[str],
                "session_id": int,
            }
        """
        history = self.get_conversation_history(session_id)

        # Pass 0 — lightweight intent analysis (no tool calls, ~100 tokens)
        intent_analysis = self._analyse_intent(query, history)

        # Short-circuit: refuse off-topic questions immediately, no tools, no LLM round-trip
        _OFF_TOPIC_REFUSAL = (
            "I'm a security analyst AI for the DFP platform — I can help with anomaly detection, "
            "user behaviour analysis, threat investigations, and insider-threat queries. "
            "For general questions like that, try ChatGPT or a general-purpose assistant."
        )
        if intent_analysis.get("label", "").lower() == "off-topic":
            self._save_message(session_id, "user", query)
            self._save_message(
                session_id,
                "assistant",
                _OFF_TOPIC_REFUSAL,
                intent=intent_analysis.get("label"),
                confidence=intent_analysis.get("confidence", 0),
                sources=[],
            )
            self._maybe_set_title(session_id, query)
            return {
                "answer": _OFF_TOPIC_REFUSAL,
                "tools_used": [],
                "session_id": session_id,
                "suggested_followups": [],
                "intent": intent_analysis.get("label", "Off-Topic"),
                "confidence": intent_analysis.get("confidence", 0),
                "sources": [],
            }

        # ── Agentic mode: delegate to AgentCore ────────────────────
        if self._chat_mode == "agentic":
            return self._process_query_agentic(session_id, query, history, intent_analysis)

        # Pass 1 — LLM picks tools, guided by intent analysis
        try:
            tool_calls = self.route_query(query, history, intent_analysis["raw"])
        except _RateLimitError as exc:
            rate_msg = (
                f"The AI service has reached its daily token limit. {exc.retry_after}. "
                "This limit resets each day — you can continue using the platform then."
            )
            self._save_message(session_id, "user", query)
            self._save_message(session_id, "assistant", rate_msg)
            return {
                "answer": rate_msg,
                "tools_used": [],
                "session_id": session_id,
                "intent": intent_analysis.get("label", "Rate Limited"),
                "confidence": 0,
                "sources": [],
            }

        # Pass 2 — execute selected tools
        tool_results: dict[str, Any] = {}
        for tc in tool_calls:
            try:
                result = self._execute_tool(tc)
                if result is not None:
                    tool_results[tc["name"]] = result
                    logger.info("Tool %s succeeded", tc["name"])
                else:
                    logger.warning("Tool %s returned None", tc["name"])
            except Exception as exc:
                logger.error("Tool %s failed: %s", tc["name"], exc, exc_info=True)

        if not tool_results and tool_calls:
            logger.warning(
                "All %d tool(s) failed or returned None: %s",
                len(tool_calls),
                [t["name"] for t in tool_calls],
            )

        # Pass 3 — LLM synthesises answer
        answer = self.generate_answer(query, tool_results, history)

        # Contextual follow-up hints (pure-Python, no extra LLM call)
        followups = self._generate_contextual_hints(query, tool_results)

        # Deduplicated ordered source category labels for the UI
        sources = list(dict.fromkeys(_TOOL_SOURCE_LABELS.get(t, "PostgreSQL") for t in tool_results))

        # Persist both turns
        self._save_message(session_id, "user", query)
        self._save_message(
            session_id,
            "assistant",
            answer,
            tools_used=list(tool_results.keys()),
            data=dict(tool_results.items()),
            intent=intent_analysis.get("label"),
            confidence=intent_analysis.get("confidence"),
            sources=sources,
        )

        # Auto-title session on first user turn
        self._maybe_set_title(session_id, query)

        return {
            "answer": answer,
            "tools_used": list(tool_results.keys()),
            "session_id": session_id,
            "suggested_followups": followups,
            "intent": intent_analysis.get("label", "Query"),
            "confidence": intent_analysis.get("confidence", 80),
            "sources": sources,
        }

    # ------------------------------------------------------------------
    # Agentic mode helpers
    # ------------------------------------------------------------------

    def _get_agent_core(self) -> Any:
        """Lazy-initialise the AgentCore on first agentic call."""
        if self._agent_core is None:
            from modules.ai.conversational.agent_core import AgentCore
            from modules.ai.conversational.tool_registry import build_registry

            registry = build_registry(self)
            self._agent_core = AgentCore(
                tool_registry=registry,
                client=self._client,
                router_model=self._router_model,
                answer_model=self._answer_model,
            )
            logger.info("AgentCore initialised (agentic mode)")
        return self._agent_core

    def process_query_streaming(
        self,
        session_id: int,
        query: str,
        step_callback: Any,
    ) -> dict[str, Any]:
        """Like process_query but pushes each trace step to *step_callback* in real time."""
        history = self.get_conversation_history(session_id)
        intent_analysis = self._analyse_intent(query, history)

        if intent_analysis.get("label", "").lower() == "off-topic":
            return self.process_query(session_id, query)

        if self._chat_mode == "agentic":
            return self._process_query_agentic(
                session_id,
                query,
                history,
                intent_analysis,
                step_callback=step_callback,
            )

        # Non-agentic mode falls back to standard (no step streaming)
        return self.process_query(session_id, query)

    def _process_query_agentic(
        self,
        session_id: int,
        query: str,
        history: list[dict[str, Any]],
        intent_analysis: dict[str, Any],
        step_callback: Any = None,
    ) -> dict[str, Any]:
        """
        Run the ReAct agent loop instead of the 3-pass pipeline.

        Uses the same ``process_query`` return contract so the API
        endpoint and frontend stay completely unchanged.
        """
        agent = self._get_agent_core()
        agent_response = agent.run(query, history, session_id=session_id, step_callback=step_callback)

        # Contextual follow-up hints using actual observation data
        followups = self._generate_contextual_hints(query, agent_response.tool_results or {})

        # Persist both turns
        self._save_message(session_id, "user", query)
        self._save_message(
            session_id,
            "assistant",
            agent_response.answer,
            tools_used=agent_response.tools_used,
            intent=intent_analysis.get("label"),
            confidence=intent_analysis.get("confidence"),
            sources=agent_response.sources,
            data={
                "reasoning_trace": agent_response.reasoning_trace,
                "steps": agent_response.steps,
            }
            if agent_response.reasoning_trace
            else None,
        )
        self._maybe_set_title(session_id, query)

        return {
            "answer": agent_response.answer,
            "tools_used": agent_response.tools_used,
            "session_id": session_id,
            "suggested_followups": followups,
            "intent": intent_analysis.get("label", "Query"),
            "confidence": intent_analysis.get("confidence", 80),
            "sources": agent_response.sources,
            "reasoning_trace": agent_response.reasoning_trace,
            "steps": agent_response.steps,
        }

    # ------------------------------------------------------------------
    # Pass 0 — intent analyser (no tools, lightweight)
    # ------------------------------------------------------------------

    def _analyse_intent(self, query: str, history: list[dict[str, Any]]) -> dict[str, Any]:
        """
        Pass 0 — lightweight intent analysis (no tool calls, ~150 tokens).

        Parses the structured LLM output into a dict:
            label       — short display label for the UI (e.g. "Location Query")
            confidence  — 0-100 integer: how answerable from the DB
            raw         — full text block injected into the Pass 1 router prompt
        Falls back gracefully on any failure.
        """
        messages: list[dict[str, Any]] = [{"role": "system", "content": _INTENT_ANALYSIS_SYSTEM}]
        for msg in history[-4:]:
            messages.append({"role": msg["role"], "content": str(msg["content"])})
        messages.append({"role": "user", "content": query})

        try:
            response = self._client.chat.completions.create(
                model=self._router_model,
                messages=messages,  # type: ignore[arg-type]
                temperature=0.0,
                max_tokens=160,
            )
            raw = (response.choices[0].message.content or "").strip()
            logger.debug("Intent analysis: %s", raw)

            # Parse key: value lines — lenient, order-independent
            label = "Query"
            confidence = 80
            for line in raw.splitlines():
                if ":" not in line:
                    continue
                key, _, value = line.partition(":")
                key = key.strip().upper()
                value = value.strip()
                if key == "LABEL":
                    label = value or label
                elif key == "CONFIDENCE":
                    try:
                        confidence = max(0, min(100, int(value.rstrip("%"))))
                    except ValueError:
                        pass

            return {"label": label, "confidence": confidence, "raw": raw}

        except Exception as exc:
            logger.warning("Intent analysis failed (non-fatal): %s", exc)
            return {"label": "Query", "confidence": 80, "raw": ""}

    # ------------------------------------------------------------------
    # Pass 1 — router
    # ------------------------------------------------------------------

    def route_query(
        self,
        query: str,
        history: list[dict[str, Any]],
        intent_analysis: str = "",
    ) -> list[dict[str, Any]]:
        """
        Pass 1: Ask the LLM which tools to call for this query.
        intent_analysis (from Pass 0) is prepended to the user message so the router
        has explicit reasoning about dimensions, aggregations, and answer shape before
        making tool selections.

        Returns a list of {name, arguments} dicts.
        Returns [] when no tools are needed (e.g. greetings).
        """
        messages: list[dict[str, Any]] = [{"role": "system", "content": _ROUTER_SYSTEM}]
        # Keep only the last 4 messages (≈2 rounds) and truncate content to stay
        # well under gpt-4o-mini's 8 000-token hard limit.  The router only needs
        # enough conversational context to pick the right tools — it doesn't need
        # the full text of previous AI responses.
        _ROUTER_HISTORY_CHARS = 600  # max chars per message sent to router
        for msg in history[-4:]:
            content = str(msg["content"])
            if len(content) > _ROUTER_HISTORY_CHARS:
                content = content[:_ROUTER_HISTORY_CHARS] + "…"
            messages.append({"role": msg["role"], "content": content})

        # Augment the user message with the intent analysis so the router sees
        # explicit reasoning before deciding which tools to call.
        if intent_analysis:
            augmented_query = f"[INTENT ANALYSIS]\n{intent_analysis}\n\n[USER QUESTION]\n{query}"
        else:
            augmented_query = query
        messages.append({"role": "user", "content": augmented_query})

        for attempt in range(self._max_retries):
            try:
                response = self._client.chat.completions.create(
                    model=self._router_model,
                    messages=messages,  # type: ignore[arg-type]
                    tools=DFP_CHAT_TOOLS,  # type: ignore[arg-type]
                    tool_choice="auto",  # type: ignore[arg-type]
                    temperature=0.0,
                    max_tokens=512,
                )
                tool_calls = response.choices[0].message.tool_calls
                if not tool_calls:
                    return []

                result = []
                for tc in tool_calls:
                    fn = getattr(tc, "function", None)
                    if fn is None:
                        continue
                    try:
                        args = json.loads(getattr(fn, "arguments", None) or "{}") or {}
                    except json.JSONDecodeError:
                        args = {}
                    result.append({"name": getattr(fn, "name", None) or "", "arguments": args})

                logger.info(
                    "route_query selected %d tool(s): %s",
                    len(result),
                    [t["name"] for t in result],
                )
                return result

            except Exception as exc:
                exc_str = str(exc)
                if "rate_limit_exceeded" in exc_str or "429" in exc_str:
                    match = re.search(r"try again in ([\w.]+)", exc_str)
                    retry_after = f"Please try again in {match.group(1)}" if match else "Please try again later"
                    raise _RateLimitError(retry_after) from exc
                if attempt < self._max_retries - 1:
                    time.sleep(2**attempt)
                    logger.warning(
                        "route_query attempt %d/%d failed: %s",
                        attempt + 1,
                        self._max_retries,
                        exc,
                    )
                else:
                    logger.error("route_query failed after all retries: %s", exc)

        return []

    # ------------------------------------------------------------------
    # Pass 2 — tool executor
    # ------------------------------------------------------------------

    def _execute_tool(self, tool_call: dict[str, Any]) -> Any:
        name = tool_call["name"]
        args = tool_call.get("arguments") or {}
        dispatch = {
            "search_anomalies": self._fetch_search_anomalies,
            "semantic_search_anomalies": self._fetch_semantic_search_anomalies,
            "get_similar_anomalies": self._fetch_semantic_search_anomalies,  # legacy alias
            "get_anomaly_detail": self._fetch_get_anomaly_detail,
            "get_user_profile": self._fetch_get_user_profile,
            "get_user_behaviour_baseline": self._fetch_get_user_behaviour_baseline,
            "get_risk_summary": self._fetch_get_risk_summary,
            "get_top_anomalies": self._fetch_get_top_anomalies,
            "get_investigation": self._fetch_get_investigation,
            "get_llm_explanations": self._fetch_get_llm_explanations,
            "get_neo4j_graph": self._fetch_get_neo4j_graph,
            "get_root_cause_summary": self._fetch_get_root_cause_summary,
            "get_anomaly_timeline": self._fetch_get_anomaly_timeline,
            "get_dimension_ranking": self._fetch_get_dimension_ranking,
            "query_database": self._fetch_query_database,
        }
        fn = dispatch.get(name)
        if fn is None:
            logger.warning("Unknown tool requested: %s", name)
            return None
        return fn(**args)

    # ------------------------------------------------------------------
    # User profile enrichment helpers
    # ------------------------------------------------------------------

    def _extract_user_ids(self, data: Any, _seen: set[str] | None = None) -> set[str]:
        """Recursively collect every unique user email from nested dicts/lists.

        Handles two key patterns:
          - key "user_id"          → scalar email string (from most tools)
          - key "affected_users"   → list of email strings (from get_dimension_ranking)
        """
        if _seen is None:
            _seen = set()
        if isinstance(data, dict):
            for key, value in data.items():
                if key == "user_id" and isinstance(value, str) and value:
                    _seen.add(value)
                elif key == "affected_users" and isinstance(value, list):
                    for item in value:
                        if isinstance(item, str) and item:
                            _seen.add(item)
                else:
                    self._extract_user_ids(value, _seen)
        elif isinstance(data, list):
            for item in data:
                self._extract_user_ids(item, _seen)
        return _seen

    def _bulk_fetch_user_profiles(self, user_ids: set[str]) -> dict[str, dict[str, Any]]:
        """
        Fetch rich profile data for a set of user email addresses.
        Returns a dict keyed by username/email → profile dict.
        """
        if not user_ids:
            return {}
        from db import get_db

        sql = """
            SELECT
                username,
                display_name,
                first_name,
                last_name,
                job_title,
                seniority,
                department,
                company,
                primary_location_city,
                primary_location_country
            FROM monitored_users
            WHERE username = ANY(%s)
        """
        try:
            with get_db() as conn:
                with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                    cur.execute(sql, (list(user_ids),))
                    return {row["username"]: dict(row) for row in cur.fetchall()}
        except Exception as exc:
            logger.warning("Failed to fetch user profiles: %s", exc)
            return {}

    def _format_user_profiles_block(self, profiles: dict[str, dict[str, Any]]) -> str:
        """
        Render the user profile lookup table as a compact, LLM-readable block.
        Each line: email → Full Name | Job Title | Seniority | Department | Company | City, Country
        """
        lines: list[str] = []
        for email, p in profiles.items():
            full_name = p.get("display_name") or f"{p.get('first_name', '')} {p.get('last_name', '')}".strip()
            parts = [
                f"Full name: {full_name}",
                f"Job title: {p.get('job_title') or 'Unknown'}",
                f"Seniority: {p.get('seniority') or 'Unknown'}",
                f"Department: {p.get('department') or 'Unknown'}",
                f"Company: {p.get('company') or 'Unknown'}",
                f"Location: {p.get('primary_location_city') or ''}, {p.get('primary_location_country') or ''}".strip(
                    ", "
                ),
            ]
            lines.append(f"[{email}]\n  " + "\n  ".join(parts))
        return "\n\n".join(lines)

    # ------------------------------------------------------------------
    # Pass 3 — answer generator
    # ------------------------------------------------------------------

    def generate_answer(
        self,
        user_query: str,
        tool_results: dict[str, Any],
        history: list[dict[str, Any]],
    ) -> str:
        """Synthesise a natural-language answer grounded in tool_results."""
        sections: list[str] = []
        for name, data in tool_results.items():
            label = _TOOL_DISPLAY_NAMES.get(name, name.upper().replace("_", " "))
            serialised = json.dumps(data, indent=2, default=str)[:3000]
            sections.append(f"=== {label} [source: {name}] ===\n{serialised}")

        # Enrich with user profile data for every user_id found in results.
        user_ids = self._extract_user_ids(tool_results)
        profiles: dict[str, Any] = {}
        if user_ids:
            profiles = self._bulk_fetch_user_profiles(user_ids)

        if profiles:
            profile_block = self._format_user_profiles_block(profiles)
            sections.append(f"=== USER PROFILES [source: monitored_users] ===\n{profile_block}")

        has_data = bool(sections)
        results_block = "\n\n".join(sections)[:6000] if sections else ""

        has_profiles = bool(profiles)
        profile_instruction = (
            "IMPORTANT: A USER PROFILES section is included in the data above. "
            "When referring to any user, use their full name, job title, seniority, "
            "and location from that section — never use raw email addresses. "
            "Format as e.g. 'Deborah Moore (Operations Analyst, Senior, Operations, TechSolutions · Beijing, China)'. "
            if has_profiles
            else ""
        )

        if has_data:
            grounded_prompt = (
                f"DATA FROM PLATFORM:\n{results_block}\n\n"
                f"USER QUESTION: {user_query}\n\n"
                "INSTRUCTION: Start your response immediately with the analysis — no greeting, "
                "no self-introduction, no preamble. "
                "Reference specific figures, names, and scores from the data above. "
                "Present all items returned. "
                f"{profile_instruction}"
                "Translate all field names to natural English. "
                "CRITICAL: Do NOT add any statistics, percentages, frequencies, or context "
                "that are not explicitly present in the data above. Every number you write "
                "must come directly from the data. Do not invent any values."
            )
        else:
            # No tool data — do NOT answer data questions from world knowledge.
            # Only allow conversational/help responses.
            grounded_prompt = (
                f"USER QUESTION: {user_query}\n\n"
                "IMPORTANT: No database results are available for this question. "
                "If the question asks for specific platform data (anomalies, users, scores, locations, "
                "investigations, etc.), you MUST say that you could not retrieve the data and suggest "
                "rephrasing the question. Do NOT invent, estimate, or guess any values, names, scores, "
                "or statistics. Only answer from your own knowledge for general conceptual questions "
                "(e.g. what is insider threat?) or greetings."
            )

        messages: list[dict[str, Any]] = [
            {"role": "system", "content": _ANSWER_SYSTEM},
        ]
        for msg in history[-10:]:  # wider context window for better continuity
            messages.append({"role": msg["role"], "content": str(msg["content"])})
        messages.append({"role": "user", "content": grounded_prompt})

        for attempt in range(self._max_retries):
            try:
                response = self._client.chat.completions.create(
                    model=self._answer_model,
                    messages=messages,  # type: ignore[arg-type]
                    temperature=0.0,
                    max_tokens=3800,  # GitHub Models low-tier cap is 4000 out; leave headroom
                )
                return response.choices[0].message.content or ""
            except Exception as exc:
                exc_str = str(exc)
                if "rate_limit_exceeded" in exc_str or "429" in exc_str:
                    match = re.search(r"try again in ([\w.]+)", exc_str)
                    retry_after = f"Please try again in {match.group(1)}" if match else "Please try again later"
                    return (
                        f"The AI service has reached its daily token limit. {retry_after}. This limit resets each day."
                    )
                if attempt < self._max_retries - 1:
                    time.sleep(2**attempt)
                    logger.warning(
                        "generate_answer attempt %d/%d failed: %s",
                        attempt + 1,
                        self._max_retries,
                        exc,
                    )
                else:
                    logger.error("generate_answer failed after all retries: %s", exc)

        return "I'm sorry, I was unable to generate a response at this time. Please try again in a moment."

    # ------------------------------------------------------------------
    # _fetch_* methods — one per tool
    # ------------------------------------------------------------------

    def _fetch_search_anomalies(
        self,
        severity: str | None = None,
        username: str | None = None,
        days: int = 0,
        limit: int = 5,
        offset: int = 0,
        sort_by: str = "risk_score_desc",
    ) -> dict[str, Any]:
        limit = min(int(limit), 20)
        offset = max(int(offset), 0)
        days = max(int(days), 0)

        conditions: list[str] = []
        params: list[Any] = []

        if severity:
            conditions.append("severity = %s")
            params.append(severity.upper())
        if username:
            conditions.append("user_id ILIKE %s")
            params.append(f"%{username}%")
        if days:
            conditions.append("timestamp >= NOW() - make_interval(days => %s)")
            params.append(days)

        where = ("WHERE " + " AND ".join(conditions)) if conditions else ""
        params.append(offset)
        params.append(limit)

        sql = f"""
            SELECT
                anomaly_id::text,
                user_id,
                timestamp,
                severity,
                ROUND(risk_score::numeric, 2)                              AS risk_score,
                ROUND(anomaly_score::numeric, 4)                           AS anomaly_score,
                root_cause,
                status,
                original_event->'location'->>'city'                        AS event_city,
                original_event->'location'->>'countryOrRegion'             AS event_country,
                original_event->>'callerIpAddress'                         AS event_ip
            FROM enriched_anomalies
            {where}
            ORDER BY {"timestamp DESC" if sort_by == "timestamp_desc" else "risk_score DESC NULLS LAST, timestamp DESC"}
            OFFSET %s
            LIMIT %s
        """
        from db import get_db  # local import — avoids circular deps at module level

        with get_db() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(sql, params)
                rows = cur.fetchall()
                # total count with same filters (exclude both offset and limit params)
                count_sql = f"SELECT COUNT(*) FROM enriched_anomalies {where}"
                cur.execute(count_sql, params[:-2])
                total = cur.fetchone()["count"]

        records = []
        for r in rows:
            d = dict(r)
            if d.get("timestamp"):
                d["timestamp"] = d["timestamp"].isoformat()
            records.append(d)

        return {"total_matching": total, "returned": len(records), "offset": offset, "anomalies": records}

    def _fetch_get_anomaly_detail(self, anomaly_id: str) -> dict[str, Any] | None:
        from db import get_db

        sql = """
            SELECT
                ea.anomaly_id::text,
                ea.user_id,
                ea.timestamp,
                ea.severity,
                ROUND(ea.risk_score::numeric, 2)       AS risk_score,
                ROUND(ea.anomaly_score::numeric, 4)    AS anomaly_score,
                ea.root_cause,
                ea.sub_category,
                ea.status,
                ea.classification_reasoning,
                ea.validation_reasoning,
                ea.risk_factors,
                le.context_analysis,
                le.pattern_analysis                    AS llm_pattern_analysis,
                le.risk_assessment,
                le.recommendations                     AS llm_recommendations,
                le.confidence_score                    AS llm_confidence_score,
                le.severity_level                      AS llm_severity_level,
                ai.status                             AS investigation_status,
                ai.overall_recommendation,
                ai.confidence_score                   AS investigation_confidence,
                ai.agents_invoked
            FROM enriched_anomalies ea
            LEFT JOIN llm_explanations le
                ON le.detection_id = ea.anomaly_id
            LEFT JOIN agent_investigations ai
                ON ai.anomaly_id = ea.anomaly_id
            WHERE ea.anomaly_id = %s::uuid
            LIMIT 1
        """
        with get_db() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(sql, (anomaly_id,))
                row = cur.fetchone()

        if not row:
            return {"error": f"No anomaly found with ID {anomaly_id}"}

        d = dict(row)
        if d.get("timestamp"):
            d["timestamp"] = d["timestamp"].isoformat()
        return d

    def _fetch_get_user_profile(self, username: str) -> dict[str, Any] | None:
        from db import get_db

        with get_db() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                # User baseline info
                cur.execute(
                    """
                    SELECT *
                    FROM monitored_users
                    WHERE username ILIKE %s
                    LIMIT 1
                    """,
                    (username,),
                )
                user = cur.fetchone()

                if not user:
                    return {"error": f"No monitored user found matching '{username}'"}

                user = dict(user)
                for ts_col in ("created_at", "updated_at", "last_seen"):
                    if user.get(ts_col):
                        user[ts_col] = user[ts_col].isoformat()

                # Anomaly summary for this user
                cur.execute(
                    """
                    SELECT
                        COUNT(*)                                                  AS total_anomalies,
                        COUNT(*) FILTER (WHERE severity = 'CRITICAL')             AS critical_count,
                        COUNT(*) FILTER (WHERE severity = 'HIGH')                 AS high_count,
                        COUNT(*) FILTER (WHERE severity = 'MEDIUM')               AS medium_count,
                        COUNT(*) FILTER (WHERE severity = 'LOW')                  AS low_count,
                        ROUND(AVG(risk_score)::numeric, 2)                        AS avg_risk_score,
                        ROUND(MAX(risk_score)::numeric, 2)                        AS max_risk_score,
                        MAX(timestamp)                                            AS last_anomaly_at
                    FROM enriched_anomalies
                    WHERE user_id ILIKE %s
                    """,
                    (username,),
                )
                stats = dict(cur.fetchone())
                if stats.get("last_anomaly_at"):
                    stats["last_anomaly_at"] = stats["last_anomaly_at"].isoformat()

                # Recent anomalies
                cur.execute(
                    """
                    SELECT
                        anomaly_id::text,
                        timestamp,
                        severity,
                        ROUND(risk_score::numeric, 2) AS risk_score,
                        root_cause
                    FROM enriched_anomalies
                    WHERE user_id ILIKE %s
                    ORDER BY timestamp DESC
                    LIMIT 5
                    """,
                    (username,),
                )
                recent = [dict(r) for r in cur.fetchall()]
                for r in recent:
                    if r.get("timestamp"):
                        r["timestamp"] = r["timestamp"].isoformat()

        return {
            "user": user,
            "anomaly_stats": stats,
            "recent_anomalies": recent,
        }

    def _fetch_semantic_search_anomalies(
        self,
        query: str,
        limit: int = 5,
        min_similarity: float = 0.3,
    ) -> dict[str, Any]:
        """
        Semantic vector search via Qdrant (sentence-transformers all-MiniLM-L6-v2).
        Falls back to SQL keyword search when Qdrant is unavailable.
        """
        limit = min(int(limit), 20)
        min_similarity = max(0.0, min(1.0, float(min_similarity)))

        qdrant_result = self._try_qdrant_search(query, limit, min_similarity)
        if qdrant_result is not None:
            return qdrant_result

        return self._sql_text_search_anomalies(query, limit)

    def _try_qdrant_search(self, query: str, limit: int, min_score: float) -> dict[str, Any] | None:
        """
        Attempt Qdrant semantic search. Returns None when Qdrant is unavailable so the
        caller can fall back to SQL. Lazy-initialises the embedding model + vector store.
        """
        # Lazy init — only try once; mark False on failure to avoid repeated startup cost
        if self._qdrant_ready is None:
            try:
                import sys

                # Add project root to sys.path so modules/ is importable
                project_root = os.path.join(os.path.dirname(__file__), "..", "..", "..")
                if project_root not in sys.path:
                    sys.path.insert(0, project_root)

                from modules.ai.embeddings.embedding_service import EmbeddingService
                from modules.ai.embeddings.vector_store import VectorStore

                self._embedding_svc = EmbeddingService()
                self._vector_store = VectorStore()
                self._qdrant_ready = True
                logger.info("Qdrant semantic search initialised (all-MiniLM-L6-v2)")
            except Exception as exc:
                logger.warning("Qdrant/sentence-transformers unavailable — using SQL fallback: %s", exc)
                self._qdrant_ready = False

        if not self._qdrant_ready:
            return None

        try:
            query_embedding = self._embedding_svc.model.encode(
                query,
                convert_to_numpy=True,
                show_progress_bar=False,
            )
            qdrant_hits = self._vector_store.search_similar(
                embedding=query_embedding,
                top_k=limit,
                min_score=min_score,
            )
        except Exception as exc:
            logger.warning("Qdrant search failed: %s", exc)
            return None

        if not qdrant_hits:
            return {
                "search_type": "semantic_vector_search",
                "model": "all-MiniLM-L6-v2",
                "query": query,
                "returned": 0,
                "note": (
                    "No semantically similar anomalies found above the similarity threshold. "
                    "Try lowering min_similarity or rephrasing the query."
                ),
                "anomalies": [],
            }

        # Hydrate from PostgreSQL to get full anomaly records
        detection_ids = [r.detection_id for r in qdrant_hits]
        score_map = {r.detection_id: r.score for r in qdrant_hits}

        from db import get_db

        with get_db() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(
                    """
                    SELECT
                        ea.anomaly_id::text AS anomaly_id,
                        ea.user_id,
                        ea.timestamp,
                        ea.severity,
                        ROUND(ea.risk_score::numeric, 2)    AS risk_score,
                        ROUND(ea.anomaly_score::numeric, 4) AS anomaly_score,
                        ea.root_cause,
                        ea.sub_category,
                        ea.classification_reasoning,
                        ea.status
                    FROM enriched_anomalies ea
                    WHERE ea.anomaly_id::text = ANY(%s)
                    """,
                    (detection_ids,),
                )
                db_rows = {str(r["anomaly_id"]): dict(r) for r in cur.fetchall()}

        records: list[dict[str, Any]] = []
        for hit in qdrant_hits:
            row = db_rows.get(hit.detection_id)
            if row:
                if row.get("timestamp"):
                    row["timestamp"] = row["timestamp"].isoformat()
            else:
                # Use Qdrant payload metadata as fallback when not found in DB
                row = {
                    "anomaly_id": hit.detection_id,
                    "user_id": hit.user_id,
                    "timestamp": hit.timestamp.isoformat() if hit.timestamp else None,
                    "severity": hit.metadata.get("severity"),
                    "note": "DB record not found — Qdrant metadata only",
                }
            row["similarity_score"] = round(score_map.get(hit.detection_id, 0.0), 4)
            records.append(row)

        records.sort(key=lambda x: x.get("similarity_score", 0.0), reverse=True)

        return {
            "search_type": "semantic_vector_search",
            "model": "all-MiniLM-L6-v2",
            "query": query,
            "returned": len(records),
            "anomalies": records,
        }

    def _sql_text_search_anomalies(self, query: str, limit: int) -> dict[str, Any]:
        """SQL keyword-based fallback when Qdrant is unavailable."""
        from db import get_db

        terms = [w.strip(".,?!\"'") for w in query.lower().split() if len(w) > 3]
        if not terms:
            terms = [query.lower()[:50]]

        text_conditions: list[str] = []
        params: list[Any] = []
        for term in terms[:6]:
            ph = f"%{term}%"
            text_conditions.append(
                "(LOWER(COALESCE(ea.root_cause,'')) LIKE %s"
                " OR LOWER(COALESCE(ea.sub_category,'')) LIKE %s"
                " OR LOWER(COALESCE(ea.classification_reasoning,'')) LIKE %s"
                " OR LOWER(COALESCE(ea.validation_reasoning,'')) LIKE %s"
                " OR LOWER(COALESCE(le.context_analysis,'')) LIKE %s"
                " OR LOWER(COALESCE(le.pattern_analysis,'')) LIKE %s"
                " OR LOWER(COALESCE(le.risk_assessment,'')) LIKE %s)"
            )
            params.extend([ph, ph, ph, ph, ph, ph, ph])

        where = "WHERE " + " OR ".join(text_conditions) if text_conditions else ""
        params.append(limit)

        sql = f"""
            SELECT
                ea.anomaly_id::text,
                ea.user_id,
                ea.timestamp,
                ea.severity,
                ROUND(ea.risk_score::numeric, 2)  AS risk_score,
                ea.root_cause,
                ea.sub_category,
                ea.classification_reasoning
            FROM enriched_anomalies ea
            LEFT JOIN llm_explanations le ON le.detection_id = ea.anomaly_id
            {where}
            ORDER BY ea.risk_score DESC NULLS LAST, ea.timestamp DESC
            LIMIT %s
        """
        with get_db() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(sql, params)
                rows = cur.fetchall()

        records = []
        for r in rows:
            d = dict(r)
            if d.get("timestamp"):
                d["timestamp"] = d["timestamp"].isoformat()
            records.append(d)

        if not records:
            fallback = self._fetch_get_top_anomalies(limit=limit)
            return {
                "search_type": "sql_fallback_top_risk",
                "query": query,
                "returned": fallback["returned"],
                "note": "No text matches found — showing highest-risk anomalies as context.",
                "anomalies": fallback["anomalies"],
            }

        return {
            "search_type": "sql_keyword_search",
            "query": query,
            "returned": len(records),
            "anomalies": records,
        }

    def _fetch_get_risk_summary(self, days: int = 0, limit: int = 5, offset: int = 0) -> dict[str, Any]:
        from db import get_db

        days = max(int(days), 0)
        limit = min(int(limit), 20)
        offset = max(int(offset), 0)
        time_filter = f"AND timestamp >= NOW() - INTERVAL '{days} days'" if days else ""

        with get_db() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(
                    f"""
                    SELECT
                        COUNT(*) AS total_anomalies,
                        COUNT(*) FILTER (WHERE severity = 'CRITICAL') AS critical_count,
                        COUNT(*) FILTER (WHERE severity = 'HIGH')     AS high_count,
                        COUNT(*) FILTER (WHERE severity = 'MEDIUM')   AS medium_count,
                        COUNT(*) FILTER (WHERE severity = 'LOW')      AS low_count,
                        ROUND(AVG(risk_score)::numeric, 2)            AS avg_risk_score,
                        ROUND(MAX(risk_score)::numeric, 2)            AS max_risk_score,
                        COUNT(DISTINCT user_id)                       AS unique_users
                    FROM enriched_anomalies
                    WHERE 1=1 {time_filter}
                    """
                )
                totals = dict(cur.fetchone())

                # Return all users ranked by anomaly count (most anomalies first)
                cur.execute(
                    f"""
                    SELECT
                        user_id,
                        COUNT(*)                                                  AS anomaly_count,
                        ROUND(MAX(risk_score)::numeric, 2)                        AS max_risk_score,
                        ROUND(AVG(risk_score)::numeric, 2)                        AS avg_risk_score,
                        COUNT(*) FILTER (WHERE severity = 'CRITICAL')             AS critical_count,
                        COUNT(*) FILTER (WHERE severity = 'HIGH')                 AS high_count,
                        COUNT(*) FILTER (WHERE severity = 'MEDIUM')               AS medium_count,
                        COUNT(*) FILTER (WHERE severity = 'LOW')                  AS low_count
                    FROM enriched_anomalies
                    WHERE 1=1 {time_filter}
                    GROUP BY user_id
                    ORDER BY anomaly_count DESC, max_risk_score DESC NULLS LAST
                    LIMIT {limit} OFFSET {offset}
                    """
                )
                all_users = [dict(r) for r in cur.fetchall()]

                cur.execute(
                    f"""
                    SELECT
                        DATE(timestamp) AS day,
                        COUNT(*) AS anomaly_count,
                        ROUND(AVG(risk_score)::numeric, 2) AS avg_risk_score
                    FROM enriched_anomalies
                    WHERE 1=1 {time_filter}
                    GROUP BY DATE(timestamp)
                    ORDER BY day DESC
                    LIMIT 14
                    """
                )
                trend = [dict(r) for r in cur.fetchall()]
                for t in trend:
                    if t.get("day"):
                        t["day"] = t["day"].isoformat()

        return {
            "window_days": days or "all_time",
            "totals": totals,
            "offset": offset,
            "all_users_by_anomaly_count": all_users,
            "daily_trend": trend,
        }

    def _fetch_get_top_anomalies(self, limit: int = 5, days: int = 0, offset: int = 0) -> dict[str, Any]:
        from db import get_db

        limit = min(int(limit), 20)
        offset = max(int(offset), 0)
        days = max(int(days), 0)
        time_filter = f"AND timestamp >= NOW() - INTERVAL '{days} days'" if days else ""

        sql = f"""
            SELECT
                anomaly_id::text,
                user_id,
                timestamp,
                severity,
                ROUND(risk_score::numeric, 2)                              AS risk_score,
                ROUND(anomaly_score::numeric, 4)                           AS anomaly_score,
                root_cause,
                sub_category,
                status,
                original_event->'location'->>'city'                        AS event_city,
                original_event->'location'->>'countryOrRegion'             AS event_country,
                original_event->>'callerIpAddress'                         AS event_ip
            FROM enriched_anomalies
            WHERE 1=1 {time_filter}
            ORDER BY risk_score DESC NULLS LAST
            OFFSET %s
            LIMIT %s
        """
        with get_db() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(
                    sql,
                    (
                        offset,
                        limit,
                    ),
                )
                rows = cur.fetchall()

        records = []
        for r in rows:
            d = dict(r)
            if d.get("timestamp"):
                d["timestamp"] = d["timestamp"].isoformat()
            records.append(d)

        total = 0
        with get_db() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                count_sql = f"SELECT COUNT(*) FROM enriched_anomalies WHERE 1=1 {time_filter}"
                cur.execute(count_sql)
                total = cur.fetchone()["count"]

        return {"total_matching": total, "returned": len(records), "offset": offset, "anomalies": records}

    def _fetch_get_investigation(
        self,
        username: str | None = None,
        limit: int = 5,
        offset: int = 0,
    ) -> dict[str, Any]:
        from db import get_db

        limit = min(int(limit), 20)
        offset = max(int(offset), 0)
        filter_params: list[Any] = []

        if username:
            user_filter = "WHERE ea.user_id ILIKE %s"
            filter_params.append(f"%{username}%")
        else:
            user_filter = ""

        params = filter_params + [offset, limit]

        sql = f"""
            SELECT
                ai.investigation_id::text,
                ai.anomaly_id::text,
                ea.user_id,
                ea.severity,
                ROUND(ea.risk_score::numeric, 2) AS risk_score,
                ai.triggered_at,
                ai.completed_at,
                ai.status,
                ai.severity_at_trigger,
                ai.agents_invoked,
                ai.confidence_score,
                ai.overall_recommendation
            FROM agent_investigations ai
            JOIN enriched_anomalies ea ON ea.anomaly_id = ai.anomaly_id
            {user_filter}
            ORDER BY ai.triggered_at DESC
            OFFSET %s
            LIMIT %s
        """
        with get_db() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(sql, params)
                investigations = [dict(r) for r in cur.fetchall()]

                for inv in investigations:
                    for ts_col in ("triggered_at", "completed_at"):
                        if inv.get(ts_col):
                            inv[ts_col] = inv[ts_col].isoformat()

                    # Attach structured agent findings — extract key fields directly
                    cur.execute(
                        """
                        SELECT
                            agent_type,
                            status,
                            result
                        FROM agent_findings
                        WHERE investigation_id = %s::uuid
                        ORDER BY started_at
                        """,
                        (inv["investigation_id"],),
                    )
                    raw_findings = cur.fetchall()
                    structured_findings: list[dict[str, Any]] = []
                    for f in raw_findings:
                        agent_type = f["agent_type"]
                        result = f["result"] or {}
                        finding: dict[str, Any] = {
                            "agent_type": agent_type,
                            "status": f["status"],
                            "confidence": result.get("confidence"),
                        }
                        if agent_type == "forensics":
                            finding["narrative"] = result.get("narrative")
                            finding["entry_point"] = result.get("entry_point")
                            finding["attack_chain"] = result.get("attack_chain")
                            finding["entities_involved"] = result.get("entities_involved")
                            finding["lateral_movement_detected"] = result.get("lateral_movement_detected")
                        elif agent_type == "investigation":
                            finding["dominant_root_cause"] = result.get("dominant_root_cause")
                            finding["pattern_analysis"] = result.get("pattern_analysis")
                            finding["recurrence_detected"] = result.get("recurrence_detected")
                            finding["recurrence_count"] = result.get("recurrence_count")
                            finding["first_seen"] = result.get("first_seen")
                        elif agent_type == "remediation":
                            finding["recommended_actions"] = result.get("recommended_actions", [])
                            finding["compliance_flags"] = result.get("compliance_flags")
                            finding["escalation_required"] = result.get("escalation_required")
                        structured_findings.append(finding)

                    inv["findings"] = structured_findings

                # Total count for pagination hint
                count_sql = f"""
                    SELECT COUNT(*)
                    FROM agent_investigations ai
                    JOIN enriched_anomalies ea ON ea.anomaly_id = ai.anomaly_id
                    {user_filter}
                """
                cur.execute(count_sql, filter_params)
                total = cur.fetchone()["count"]

        return {
            "total_matching": total,
            "returned": len(investigations),
            "offset": offset,
            "investigations": investigations,
        }

    def _fetch_get_neo4j_graph(
        self,
        entity: str | None = None,
    ) -> dict[str, Any]:
        try:
            from neo4j import GraphDatabase
        except ImportError:
            return {"error": "Neo4j driver not installed"}

        uri = os.getenv("NEO4J_URI", "bolt://localhost:7687")
        user = os.getenv("NEO4J_USER", "neo4j")
        password = os.getenv("NEO4J_PASSWORD", "")
        database = os.getenv("NEO4J_DATABASE", "neo4j")

        try:
            driver = GraphDatabase.driver(uri, auth=(user, password))
            driver.verify_connectivity()
        except Exception as exc:
            logger.warning("Neo4j unavailable: %s", exc)
            return {"error": "Knowledge graph is currently unavailable"}

        try:
            with driver.session(database=database) as session:
                if entity:
                    result = session.run(
                        """
                        MATCH (n {name: $entity})-[r]-(m)
                        RETURN
                            type(r)   AS relationship,
                            labels(n) AS source_labels,
                            n.name    AS source,
                            labels(m) AS target_labels,
                            m.name    AS target
                        LIMIT 30
                        """,
                        entity=entity,
                    )
                else:
                    result = session.run(
                        """
                        MATCH (n)-[r]-(m)
                        RETURN
                            type(r)   AS relationship,
                            labels(n) AS source_labels,
                            n.name    AS source,
                            labels(m) AS target_labels,
                            m.name    AS target
                        LIMIT 30
                        """
                    )
                edges = [dict(record) for record in result]
        finally:
            driver.close()

        return {
            "entity": entity,
            "edge_count": len(edges),
            "edges": edges,
        }

    def _fetch_get_root_cause_summary(self, days: int = 30) -> dict[str, Any]:
        from db import get_db

        days = max(int(days), 0)
        time_filter = f"AND timestamp >= NOW() - INTERVAL '{days} days'" if days else ""

        sql = f"""
            SELECT
                COALESCE(root_cause, 'Unknown') AS root_cause,
                COUNT(*)                        AS count,
                ROUND(AVG(risk_score)::numeric, 2) AS avg_risk_score
            FROM enriched_anomalies
            WHERE root_cause IS NOT NULL {time_filter}
            GROUP BY root_cause
            ORDER BY count DESC
            LIMIT 15
        """
        sql_sub = f"""
            SELECT
                COALESCE(sub_category, 'Unknown') AS sub_category,
                COUNT(*) AS count
            FROM enriched_anomalies
            WHERE sub_category IS NOT NULL {time_filter}
            GROUP BY sub_category
            ORDER BY count DESC
            LIMIT 10
        """
        with get_db() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(sql)
                root_causes = [dict(r) for r in cur.fetchall()]
                cur.execute(sql_sub)
                sub_categories = [dict(r) for r in cur.fetchall()]

        return {
            "window_days": days or "all_time",
            "root_cause_distribution": root_causes,
            "sub_category_distribution": sub_categories,
        }

    def _fetch_get_llm_explanations(
        self,
        anomaly_id: str | None = None,
        severity: str | None = None,
        classification: str | None = None,
        limit: int = 5,
    ) -> dict[str, Any]:
        """
        Fetch LLM-generated analytical explanation records.
        Returns context analysis, pattern analysis, evidence, recommendations, and metadata.
        """
        from db import get_db

        limit = min(int(limit), 20)
        conditions: list[str] = []
        params: list[Any] = []

        if anomaly_id:
            conditions.append("le.detection_id = %s::uuid")
            params.append(anomaly_id)
        if severity:
            conditions.append("le.severity_level = %s")
            params.append(severity.upper())
        if classification:
            normalized_classification = classification.lower()
            if normalized_classification == "true_positive":
                conditions.append("(le.anomaly_classification->>'positive')::boolean = true")
            elif normalized_classification == "false_positive":
                conditions.append("(le.anomaly_classification->>'positive')::boolean = false")
            elif normalized_classification == "uncertain":
                conditions.append("le.anomaly_classification->>'positive' IS NULL")

        where = ("WHERE " + " AND ".join(conditions)) if conditions else ""
        params.append(limit)

        sql = f"""
            SELECT
                le.detection_id::text                             AS anomaly_id,
                le.explanation_type,
                le.context_analysis,
                le.pattern_analysis,
                le.anomaly_classification,
                le.risk_assessment,
                le.recommendations,
                le.reasoning_process,
                le.evidence_summary,
                le.similar_cases_cited,
                le.graph_insights_used,
                ROUND(le.confidence_score::numeric, 4)            AS confidence_score,
                le.severity_level,
                le.hallucination_risk,
                le.cold_start,
                le.human_feedback,
                le.validation_status,
                le.created_at,
                ea.user_id,
                ea.severity                                       AS anomaly_severity,
                ea.root_cause,
                ROUND(ea.risk_score::numeric, 2)                  AS risk_score
            FROM llm_explanations le
            JOIN enriched_anomalies ea ON ea.anomaly_id = le.detection_id
            {where}
            ORDER BY le.created_at DESC
            LIMIT %s
        """
        with get_db() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(sql, params)
                rows = cur.fetchall()

        records = []
        for r in rows:
            d = dict(r)
            if d.get("created_at"):
                d["created_at"] = d["created_at"].isoformat()
            records.append(d)

        return {"returned": len(records), "explanations": records}

    def _fetch_get_user_behaviour_baseline(
        self,
        username: str | None = None,
        department: str | None = None,
        limit: int = 10,
    ) -> dict[str, Any]:
        """
        Fetch normal behaviour baseline for one or more monitored users.
        Returns work hours, active days, devices, apps, locations, VPN usage.
        """
        from db import get_db

        conditions: list[str] = []
        params: list[Any] = []

        if username:
            conditions.append("username ILIKE %s")
            params.append(f"%{username}%")
        if department:
            conditions.append("department ILIKE %s")
            params.append(f"%{department}%")

        where = ("WHERE " + " AND ".join(conditions)) if conditions else ""
        limit = min(int(limit), 20)
        params.append(limit)

        sql = f"""
            SELECT
                username,
                display_name,
                job_title,
                seniority,
                department,
                company,
                primary_location_city,
                primary_location_country,
                all_locations,
                primary_os,
                primary_browser,
                primary_device,
                devices,
                apps,
                work_hours_start,
                work_hours_end,
                active_days,
                total_events,
                corp_vpn
            FROM monitored_users
            {where}
            ORDER BY username
            LIMIT %s
        """
        with get_db() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(sql, params)
                rows = cur.fetchall()

        if not rows:
            return {
                "returned": 0,
                "baselines": [],
                "note": "No users found matching the given criteria.",
            }

        return {"returned": len(rows), "baselines": [dict(r) for r in rows]}

    def _fetch_get_anomaly_timeline(
        self,
        username: str | None = None,
        days: int = 30,
        granularity: str = "daily",
    ) -> dict[str, Any]:
        """
        Returns time-series anomaly counts/risk aggregated by day or week.
        Includes user count per period and overall trend direction.
        """
        from db import get_db

        days = max(1, min(int(days), 365))
        granularity = (granularity or "daily").lower()
        if granularity not in ("daily", "weekly"):
            granularity = "daily"

        user_filter = ""
        params: list[Any] = []

        if username:
            user_filter = "AND user_id ILIKE %s"
            params.append(f"%{username}%")

        trunc = "day" if granularity == "daily" else "week"

        sql = f"""
            SELECT
                DATE_TRUNC('{trunc}', timestamp)::date            AS period,
                COUNT(*)                                          AS anomaly_count,
                ROUND(AVG(risk_score)::numeric, 2)                AS avg_risk_score,
                ROUND(MAX(risk_score)::numeric, 2)                AS max_risk_score,
                COUNT(*) FILTER (WHERE severity = 'CRITICAL')     AS critical_count,
                COUNT(*) FILTER (WHERE severity = 'HIGH')         AS high_count,
                COUNT(*) FILTER (WHERE severity = 'MEDIUM')       AS medium_count,
                COUNT(*) FILTER (WHERE severity = 'LOW')          AS low_count,
                COUNT(DISTINCT user_id)                           AS unique_users_affected
            FROM enriched_anomalies
            WHERE timestamp >= NOW() - INTERVAL '{days} days'
            {user_filter}
            GROUP BY DATE_TRUNC('{trunc}', timestamp)
            ORDER BY period DESC
            LIMIT 60
        """
        with get_db() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(sql, params)
                rows = cur.fetchall()

        periods = []
        for r in rows:
            d = dict(r)
            if d.get("period"):
                d["period"] = d["period"].isoformat()
            periods.append(d)

        # Compute trend from first half (recent) vs second half (older)
        trend = "stable"
        if len(periods) >= 4:
            half = len(periods) // 2
            recent_avg = sum(p["anomaly_count"] for p in periods[:half]) / half
            older_avg = sum(p["anomaly_count"] for p in periods[half:]) / max(1, len(periods) - half)
            if recent_avg > older_avg * 1.2:
                trend = "increasing"
            elif recent_avg < older_avg * 0.8:
                trend = "decreasing"

        return {
            "scope": username or "platform_wide",
            "window_days": days,
            "granularity": granularity,
            "trend": trend,
            "periods": periods,
        }

    # ------------------------------------------------------------------
    # Contextual follow-up hint generator
    # ------------------------------------------------------------------

    # ---------------------------------------------------------------------------
    # Dimension-based ranking (Pass 2 for get_dimension_ranking tool)
    # ---------------------------------------------------------------------------

    # Mapping of user-facing dimension names → SQL expressions against enriched_anomalies
    _DIMENSION_SQL: dict[str, str] = {
        "city": "original_event->'location'->>'city'",
        "country": "original_event->'location'->>'countryOrRegion'",
        "location": (
            "CONCAT(original_event->'location'->>'city', ', ', original_event->'location'->>'countryOrRegion')"
        ),
        "ip": "original_event->>'callerIpAddress'",
        "ip_address": "original_event->>'callerIpAddress'",
        "user": "user_id",
        "username": "user_id",
        "severity": "severity",
        "root_cause": "root_cause",
        "sub_category": "sub_category",
        "status": "status",
        "app": "COALESCE(NULLIF(original_event->'properties'->>'appDisplayName', ''), raw_detection->>'app')",
        "device": "COALESCE(NULLIF(raw_detection->>'device', ''), original_event->'properties'->'deviceDetail'->>'displayName')",
        "browser": "COALESCE(NULLIF(raw_detection->>'browser', ''), '')",
        "os": "COALESCE(NULLIF(raw_detection->>'os', ''), original_event->'properties'->'deviceDetail'->>'operatingSystem')",
    }

    def _fetch_get_dimension_ranking(
        self,
        dimension: str,
        limit: int = 10,
        days: int = 0,
    ) -> dict[str, Any]:
        """
        Aggregate anomaly data grouped by any supported dimension expression and
        rank entities by max risk score then anomaly count.  Returns the top-N
        entities with aggregated statistics so the LLM can identify the most
        anomalous city / country / IP / device / app / user / etc.
        """
        from db import get_db

        dim_key = dimension.lower().strip()
        expr = self._DIMENSION_SQL.get(dim_key)
        if not expr:
            supported = ", ".join(sorted(self._DIMENSION_SQL.keys()))
            return {
                "error": f"Unknown dimension '{dimension}'. Supported: {supported}",
                "dimension": dimension,
            }

        limit = min(int(limit), 30)
        days = max(int(days), 0)
        time_filter = f"AND timestamp >= NOW() - INTERVAL '{days} days'" if days else ""

        # Use the expression twice: once in GROUP BY and once in SELECT.
        # We pass it as an f-string (no user input reaches here — dim_key is
        # validated against a static dict before use).
        sql = f"""
            SELECT
                ({expr})                                              AS dimension_value,
                COUNT(*)                                              AS anomaly_count,
                ROUND(MAX(risk_score)::numeric, 2)                    AS max_risk_score,
                ROUND(AVG(risk_score)::numeric, 2)                    AS avg_risk_score,
                COUNT(*) FILTER (WHERE severity = 'CRITICAL')         AS critical_count,
                COUNT(*) FILTER (WHERE severity = 'HIGH')             AS high_count,
                COUNT(*) FILTER (WHERE severity = 'MEDIUM')           AS medium_count,
                COUNT(*) FILTER (WHERE severity = 'LOW')              AS low_count,
                array_agg(DISTINCT user_id ORDER BY user_id)
                    FILTER (WHERE user_id IS NOT NULL)                AS affected_users
            FROM enriched_anomalies
            WHERE ({expr}) IS NOT NULL
              AND TRIM(({expr})) <> '' {time_filter}
            GROUP BY ({expr})
            ORDER BY max_risk_score DESC NULLS LAST, anomaly_count DESC
            LIMIT %s
        """
        with get_db() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(sql, (limit,))
                rows = cur.fetchall()

        ranking = []
        for r in rows:
            entry = dict(r)
            # affected_users is a postgres array — convert to plain list
            users = entry.get("affected_users") or []
            entry["affected_users"] = list(users[:5])  # limit to first 5 for readability
            ranking.append(entry)

        return {
            "dimension": dimension,
            "window_days": days or "all_time",
            "returned": len(ranking),
            "ranking": ranking,
        }

    # ---------------------------------------------------------------------------
    # Ad-hoc read-only SQL execution (query_database tool)
    # ---------------------------------------------------------------------------

    # Patterns that must never appear in a query_database SQL string.
    # Defence-in-depth: the DB user should also have only SELECT grants.
    _SQL_DANGEROUS = re.compile(
        r"\b(INSERT|UPDATE|DELETE|DROP|TRUNCATE|ALTER|CREATE|GRANT|REVOKE|COPY|EXECUTE|"
        r"pg_read_file|pg_ls_dir|pg_sleep|pg_terminate_backend|lo_export|lo_import)\b",
        re.IGNORECASE,
    )
    # Block multiple statements (`;` followed by anything non-whitespace)
    _SQL_MULTI_STMT = re.compile(r";\s*\S", re.IGNORECASE)

    def _fetch_query_database(self, sql: str) -> dict[str, Any]:
        """
        Execute a caller-supplied SELECT statement with strict safety guards:
          1. Must start with SELECT (leading whitespace/comments stripped)
          2. Must not contain dangerous keywords (DML, DDL, system functions)
          3. Must not contain multiple statements
          4. LIMIT clamped to 100 if absent or above threshold
          5. Executed inside a READ ONLY transaction with 8s statement timeout
        Returns {rows: [...], row_count: int} on success or {error: str} on rejection.
        """
        from db import get_db

        if not isinstance(sql, str):
            return {"error": "sql must be a string"}

        sql = sql.strip()

        # 1. Must be a SELECT
        if not re.match(r"^(--[^\n]*\n\s*)*SELECT\b", sql, re.IGNORECASE):
            return {"error": "Only SELECT statements are permitted"}

        # 2. No dangerous keywords
        danger = self._SQL_DANGEROUS.search(sql)
        if danger:
            return {"error": f"Disallowed keyword: {danger.group().upper()}"}

        # 3. No multi-statement
        if self._SQL_MULTI_STMT.search(sql):
            return {"error": "Multiple statements are not permitted"}

        # 4. Enforce LIMIT ≤ 100
        limit_match = re.search(r"\bLIMIT\s+(\d+)", sql, re.IGNORECASE)
        if limit_match:
            if int(limit_match.group(1)) > 100:
                sql = re.sub(r"\bLIMIT\s+\d+", "LIMIT 100", sql, flags=re.IGNORECASE)
        else:
            sql = sql.rstrip(";") + "\nLIMIT 100"

        try:
            with get_db() as conn:
                with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                    cur.execute("SET LOCAL statement_timeout = '8s'")
                    cur.execute("SET TRANSACTION READ ONLY")
                    cur.execute(sql)
                    rows = cur.fetchall()

            serialisable: list[dict[str, Any]] = []
            for row in rows:
                entry: dict[str, Any] = {}
                for k, v in row.items():
                    entry[k] = v.isoformat() if hasattr(v, "isoformat") else v
                serialisable.append(entry)

            return {"row_count": len(serialisable), "rows": serialisable}

        except Exception as exc:
            logger.warning("query_database failed: %s | sql: %.200s", exc, sql)
            return {"error": str(exc)}

    def _generate_contextual_hints(
        self,
        query: str,
        tool_results: dict[str, Any],
    ) -> list[str]:
        """
        Generate up to 3 specific, contextually relevant follow-up questions
        based solely on what was retrieved — no LLM call required.
        """
        hints: list[str] = []

        def _add(hint: str) -> None:
            if hint not in hints and len(hints) < 3:
                hints.append(hint)

        # From investigation results
        if "get_investigation" in tool_results:
            investigations = tool_results["get_investigation"].get("investigations", [])
            if investigations:
                first = investigations[0]
                user = first.get("user_id", "")
                aid = first.get("anomaly_id", "")
                if user:
                    _add(f"What is the full behaviour baseline for {user}?")
                if aid:
                    _add(f"Get the LLM analytical explanation for anomaly {aid[:8]}…")

        # From risk summary
        if "get_risk_summary" in tool_results:
            rs = tool_results["get_risk_summary"]
            users = rs.get("all_users_by_anomaly_count", [])
            if users:
                top_user = users[0].get("user_id", "")
                if top_user:
                    _add(f"Show me the investigation findings for {top_user}")
            if rs.get("totals", {}).get("critical_count", 0) > 0:
                _add("Find the CRITICAL anomalies and show their investigation status")
            trend = rs.get("daily_trend", [])
            if len(trend) >= 2:
                _add("Show me the anomaly trend over the past 30 days broken down by severity")

        # From top anomalies
        if "get_top_anomalies" in tool_results:
            anomalies = tool_results["get_top_anomalies"].get("anomalies", [])
            if anomalies:
                first = anomalies[0]
                aid = first.get("anomaly_id", "")
                user = first.get("user_id", "")
                if aid:
                    _add(f"Get full investigation details for anomaly {aid[:8]}…")
                if user:
                    _add(f"Show the complete profile and behaviour baseline for {user}")

        # From search / semantic search results
        for search_key in ("semantic_search_anomalies", "search_anomalies", "get_similar_anomalies"):
            if search_key in tool_results:
                anomalies = tool_results[search_key].get("anomalies", [])
                if anomalies:
                    first = anomalies[0]
                    user = first.get("user_id", "")
                    aid = first.get("anomaly_id", "")
                    if user:
                        _add(f"What are the agent investigation findings for {user}?")
                    if aid:
                        _add(f"Get the LLM explanation and reasoning for anomaly {aid[:8]}…")
                break

        # From user profile
        if "get_user_profile" in tool_results:
            user_data = tool_results["get_user_profile"].get("user", {})
            username = user_data.get("username", "")
            if username:
                _add(f"Show the normal behaviour baseline for {username}")
                _add(f"What do the AI agents recommend for anomalies affecting {username}?")

        # From LLM explanations
        if "get_llm_explanations" in tool_results:
            explanations = tool_results["get_llm_explanations"].get("explanations", [])
            if explanations:
                first = explanations[0]
                aid = first.get("anomaly_id", "")
                user = first.get("user_id", "")
                if aid:
                    _add(f"Get the agent investigation findings for anomaly {aid[:8]}…")
                if user:
                    _add(f"Show me the behaviour baseline for {user}")

        # From user behaviour baseline
        if "get_user_behaviour_baseline" in tool_results:
            baselines = tool_results["get_user_behaviour_baseline"].get("baselines", [])
            if baselines:
                first = baselines[0]
                username = first.get("username", "")
                if username:
                    _add(f"Show recent anomalies for {username} and compare to their baseline")

        # From anomaly timeline
        if "get_anomaly_timeline" in tool_results:
            tl = tool_results["get_anomaly_timeline"]
            scope = tl.get("scope", "")
            trend = tl.get("trend", "stable")
            if trend == "increasing":
                _add("What are the most recent high-risk anomalies driving the increase?")
            if scope and scope != "platform_wide":
                _add(f"Show me the full investigation history for {scope}")

        # From Neo4j graph
        if "get_neo4j_graph" in tool_results:
            edges = tool_results["get_neo4j_graph"].get("edges", [])
            if edges:
                entities = {e.get("source") for e in edges if e.get("source")}
                if entities:
                    entity = next(iter(entities))
                    _add(f"Search for anomalies involving {entity}")

        # Generic fallbacks to fill remaining slots
        for fallback in [
            "What do the AI agents recommend for the most critical anomalies?",
            "Show me the users with the highest risk scores",
            "Find anomalies that are still pending investigation",
            "What are the most common root causes this month?",
            "Show me the platform-wide anomaly trend for the past 30 days",
        ]:
            _add(fallback)

        return hints

    # ------------------------------------------------------------------
    # Session management
    # ------------------------------------------------------------------

    def create_session(self, title: str = "New Conversation", user_id: int | None = None) -> dict[str, Any]:
        from db import get_db

        with get_db() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(
                    "INSERT INTO chat_sessions (title, user_id) VALUES (%s, %s) RETURNING *",
                    (title, user_id),
                )
                row = dict(cur.fetchone())
                conn.commit()

        for ts_col in ("created_at", "updated_at"):
            if row.get(ts_col):
                row[ts_col] = row[ts_col].isoformat()
        return row

    def get_sessions(self, status: str = "active", user_id: int | None = None) -> list[dict[str, Any]]:
        from db import get_db

        with get_db() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(
                    """
                    SELECT
                        cs.id,
                        cs.title,
                        cs.status,
                        cs.is_pinned,
                        cs.user_id,
                        cs.created_at,
                        cs.updated_at,
                        COUNT(cm.id) FILTER (WHERE cm.role = 'user') AS message_count
                    FROM chat_sessions cs
                    LEFT JOIN chat_messages cm ON cm.session_id = cs.id
                    WHERE cs.status = %s
                      AND (%s::int IS NULL OR cs.user_id = %s)
                    GROUP BY cs.id
                    ORDER BY cs.is_pinned DESC, cs.updated_at DESC
                    LIMIT 50
                    """,
                    (status, user_id, user_id),
                )
                rows = [dict(r) for r in cur.fetchall()]

        for r in rows:
            for ts_col in ("created_at", "updated_at"):
                if r.get(ts_col):
                    r[ts_col] = r[ts_col].isoformat()
        return rows

    def get_session(self, session_id: int, user_id: int | None = None) -> dict[str, Any] | None:
        from db import get_db

        with get_db() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                if user_id is not None:
                    cur.execute(
                        "SELECT * FROM chat_sessions WHERE id = %s AND user_id = %s",
                        (session_id, user_id),
                    )
                else:
                    cur.execute(
                        "SELECT * FROM chat_sessions WHERE id = %s",
                        (session_id,),
                    )
                row = cur.fetchone()
                if not row:
                    return None
                session = dict(row)
                for ts_col in ("created_at", "updated_at"):
                    if session.get(ts_col):
                        session[ts_col] = session[ts_col].isoformat()

                cur.execute(
                    """
                    SELECT id, session_id, role, content,
                           tools_used, intent, confidence, sources, data, created_at
                    FROM chat_messages
                    WHERE session_id = %s
                    ORDER BY created_at ASC
                    """,
                    (session_id,),
                )
                messages = []
                for m in cur.fetchall():
                    md = dict(m)
                    if md.get("created_at"):
                        md["created_at"] = md["created_at"].isoformat()
                    # Unpack reasoning trace from JSONB data column
                    if md.get("data") and isinstance(md["data"], dict):
                        if md["data"].get("reasoning_trace"):
                            md["reasoning_trace"] = md["data"]["reasoning_trace"]
                        if md["data"].get("steps"):
                            md["steps"] = md["data"]["steps"]
                        del md["data"]
                    else:
                        md.pop("data", None)
                    messages.append(md)

        session["messages"] = messages
        return session

    def delete_session(self, session_id: int, user_id: int | None = None) -> bool:
        from db import get_db

        with get_db() as conn:
            with conn.cursor() as cur:
                if user_id is not None:
                    cur.execute(
                        "DELETE FROM chat_sessions WHERE id = %s AND user_id = %s RETURNING id",
                        (session_id, user_id),
                    )
                else:
                    cur.execute(
                        "DELETE FROM chat_sessions WHERE id = %s RETURNING id",
                        (session_id,),
                    )
                deleted = cur.fetchone()
                conn.commit()
        return deleted is not None

    def archive_session(self, session_id: int, user_id: int | None = None) -> bool:
        from db import get_db

        with get_db() as conn:
            with conn.cursor() as cur:
                if user_id is not None:
                    cur.execute(
                        "UPDATE chat_sessions SET status = 'archived', updated_at = NOW() WHERE id = %s AND user_id = %s RETURNING id",
                        (session_id, user_id),
                    )
                else:
                    cur.execute(
                        "UPDATE chat_sessions SET status = 'archived', updated_at = NOW() WHERE id = %s RETURNING id",
                        (session_id,),
                    )
                updated = cur.fetchone()
                conn.commit()
        return updated is not None

    def unarchive_session(self, session_id: int, user_id: int | None = None) -> bool:
        from db import get_db

        with get_db() as conn:
            with conn.cursor() as cur:
                if user_id is not None:
                    cur.execute(
                        "UPDATE chat_sessions SET status = 'active', updated_at = NOW() WHERE id = %s AND user_id = %s RETURNING id",
                        (session_id, user_id),
                    )
                else:
                    cur.execute(
                        "UPDATE chat_sessions SET status = 'active', updated_at = NOW() WHERE id = %s RETURNING id",
                        (session_id,),
                    )
                updated = cur.fetchone()
                conn.commit()
        return updated is not None

    def rename_session(self, session_id: int, title: str, user_id: int | None = None) -> bool:
        from db import get_db

        with get_db() as conn:
            with conn.cursor() as cur:
                if user_id is not None:
                    cur.execute(
                        "UPDATE chat_sessions SET title = %s, updated_at = NOW() WHERE id = %s AND user_id = %s RETURNING id",
                        (title, session_id, user_id),
                    )
                else:
                    cur.execute(
                        "UPDATE chat_sessions SET title = %s, updated_at = NOW() WHERE id = %s RETURNING id",
                        (title, session_id),
                    )
                updated = cur.fetchone()
                conn.commit()
        return updated is not None

    def export_session(self, session_id: int, user_id: int | None = None) -> dict[str, Any] | None:
        """Return full session data formatted for export."""
        session = self.get_session(session_id, user_id=user_id)
        if not session:
            return None
        return {
            "title": session["title"],
            "created_at": session["created_at"],
            "updated_at": session["updated_at"],
            "messages": [
                {
                    "role": m["role"],
                    "content": m["content"],
                    "created_at": m["created_at"],
                    **(({"tools_used": m["tools_used"]}) if m.get("tools_used") else {}),
                    **(({"intent": m["intent"]}) if m.get("intent") else {}),
                    **(({"sources": m["sources"]}) if m.get("sources") else {}),
                }
                for m in session.get("messages", [])
            ],
        }

    def get_conversation_history(self, session_id: int, limit: int = 20) -> list[dict[str, Any]]:
        """Return the last `limit` messages as {role, content} dicts."""
        from db import get_db

        with get_db() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(
                    """
                    SELECT role, content
                    FROM chat_messages
                    WHERE session_id = %s
                    ORDER BY created_at DESC
                    LIMIT %s
                    """,
                    (session_id, limit),
                )
                rows = cur.fetchall()

        # Reverse so oldest is first (for message array ordering)
        return [{"role": r["role"], "content": r["content"]} for r in reversed(rows)]

    def _save_message(
        self,
        session_id: int,
        role: str,
        content: str,
        tools_used: list[str] | None = None,
        data: dict | None = None,
        intent: str | None = None,
        confidence: int | None = None,
        sources: list[str] | None = None,
    ) -> None:
        from db import get_db

        with get_db() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO chat_messages
                        (session_id, role, content, tools_used, data, intent, confidence, sources)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        session_id,
                        role,
                        content,
                        json.dumps(tools_used) if tools_used else None,
                        json.dumps(data, default=str) if data else None,
                        intent,
                        confidence,
                        json.dumps(sources),  # always persist, even for empty list
                    ),
                )
                cur.execute(
                    "UPDATE chat_sessions SET updated_at = NOW() WHERE id = %s",
                    (session_id,),
                )
                conn.commit()

    def _maybe_set_title(self, session_id: int, first_query: str) -> None:
        """Set a meaningful session title from the first user message if still default."""
        from db import get_db

        with get_db() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute("SELECT title FROM chat_sessions WHERE id = %s", (session_id,))
                row = cur.fetchone()
                if row and row["title"] == "New Conversation":
                    title = first_query[:60].strip()
                    if len(first_query) > 60:
                        title += "…"
                    cur.execute(
                        "UPDATE chat_sessions SET title = %s WHERE id = %s",
                        (title, session_id),
                    )
                    conn.commit()

    # ------------------------------------------------------------------
    # Suggested questions
    # ------------------------------------------------------------------

    def get_suggested_questions(self) -> list[str]:
        """
        Return dynamic suggested questions based on actual platform state.
        Falls back to static defaults if the DB query fails.
        """
        try:
            from db import get_db

            with get_db() as conn:
                with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                    cur.execute(
                        """
                        SELECT
                            COUNT(*) FILTER (WHERE severity = 'CRITICAL') AS critical_count,
                            COUNT(*) FILTER (WHERE severity = 'HIGH')     AS high_count,
                            COUNT(DISTINCT user_id)                       AS user_count
                        FROM enriched_anomalies
                        WHERE timestamp >= NOW() - INTERVAL '7 days'
                        """
                    )
                    stats = dict(cur.fetchone())

                    cur.execute(
                        """
                        SELECT root_cause
                        FROM enriched_anomalies
                        WHERE root_cause IS NOT NULL
                        GROUP BY root_cause
                        ORDER BY COUNT(*) DESC
                        LIMIT 1
                        """
                    )
                    top_cause_row = cur.fetchone()

            questions = [
                "What is the current risk posture across the platform?",
                "Show me the top anomalies by risk score",
            ]

            if stats.get("critical_count", 0) > 0:
                questions.append(f"What are the {int(stats['critical_count'])} CRITICAL anomalies detected this week?")
            if stats.get("high_count", 0) > 0:
                questions.append("Summarise the HIGH severity anomalies from the past 7 days")
            if top_cause_row:
                questions.append(f"Find anomalies related to {top_cause_row['root_cause']}")
            questions += [
                "What patterns of data exfiltration have been detected?",
                "Which users have the most anomalies and what is their risk level?",
                "What do the latest agent investigations recommend?",
            ]
            return questions[:8]

        except Exception as exc:
            logger.warning("Could not generate dynamic suggestions: %s", exc)
            return [
                "What is the overall risk posture across the platform?",
                "Show me the top anomalies by risk score",
                "Which users have been flagged most frequently?",
                "Find anomalies involving data exfiltration",
                "What patterns of after-hours access have been detected?",
                "What did the AI agents find in their investigations?",
                "Show risk severity breakdown for the past 30 days",
                "Are there any privilege escalation anomalies?",
            ]
