"""
End-to-end test suite for Week 30 — Hardening & Rollout.

20+ conversational scenarios covering all tool combinations, edge cases,
multi-turn context, error recovery, and output validation.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import MagicMock

sys.path.insert(0, str(Path(__file__).parents[2]))

from modules.ai.conversational.agent_core import AgentCore, AgentResponse
from modules.ai.conversational.guard_rails import AgentConfig
from modules.ai.conversational.tool_registry import ToolRegistry, ToolSpec

# ═══════════════════════════════════════════════════════════════════════
#  Shared helpers
# ═══════════════════════════════════════════════════════════════════════


_TOOL_DEFS: list[dict] = [
    {
        "name": "search_anomalies",
        "description": "Search anomalies by filters",
        "parameters": {
            "type": "object",
            "properties": {
                "severity": {"type": "string", "enum": ["HIGH", "CRITICAL"]},
                "limit": {"type": "integer"},
                "user_id": {"type": "string"},
            },
            "required": [],
        },
        "handler": lambda **kw: {
            "total_matching": 3,
            "anomalies": [
                {
                    "anomaly_id": "a1",
                    "user_id": kw.get("user_id", "alice@co.com"),
                    "severity": kw.get("severity", "HIGH"),
                    "risk_score": 85.2,
                },
                {"anomaly_id": "a2", "user_id": "bob@co.com", "severity": "CRITICAL", "risk_score": 92.1},
            ],
        },
        "estimated_tokens": 300,
    },
    {
        "name": "get_anomaly_detail",
        "description": "Get detailed anomaly info",
        "parameters": {
            "type": "object",
            "properties": {"anomaly_id": {"type": "string"}},
            "required": ["anomaly_id"],
        },
        "handler": lambda **kw: {
            "anomaly_id": kw.get("anomaly_id", "a1"),
            "user_id": "alice@co.com",
            "severity": "HIGH",
            "risk_score": 85.2,
            "root_cause": "Unusual login location",
            "timestamp": "2026-04-15T14:30:00Z",
        },
        "estimated_tokens": 200,
    },
    {
        "name": "get_user_profile",
        "description": "Get user profile and anomaly history",
        "parameters": {
            "type": "object",
            "properties": {"username": {"type": "string"}},
            "required": ["username"],
        },
        "handler": lambda **kw: {
            "user": kw.get("username", "alice@co.com"),
            "anomaly_count": 5,
            "risk_score": 72.5,
            "last_seen": "2026-04-14",
        },
        "estimated_tokens": 200,
    },
    {
        "name": "get_risk_summary",
        "description": "Platform-wide risk summary",
        "parameters": {"type": "object", "properties": {}, "required": []},
        "handler": lambda **kw: {"total_anomalies": 42, "critical": 5, "high": 15, "medium": 12, "low": 10},
        "estimated_tokens": 200,
    },
    {
        "name": "get_similar_anomalies",
        "description": "Find anomalies similar to a given one",
        "parameters": {
            "type": "object",
            "properties": {"anomaly_id": {"type": "string"}, "limit": {"type": "integer"}},
            "required": ["anomaly_id"],
        },
        "handler": lambda **kw: {
            "query_id": kw.get("anomaly_id", "a1"),
            "similar": [
                {"anomaly_id": "a3", "similarity": 0.92, "user_id": "carol@co.com"},
                {"anomaly_id": "a4", "similarity": 0.87, "user_id": "alice@co.com"},
            ],
        },
        "estimated_tokens": 250,
    },
    {
        "name": "get_top_anomalies",
        "description": "Get top anomalies by risk score",
        "parameters": {
            "type": "object",
            "properties": {"limit": {"type": "integer"}, "severity": {"type": "string"}},
            "required": [],
        },
        "handler": lambda **kw: {
            "anomalies": [
                {"anomaly_id": "a2", "risk_score": 92.1, "severity": "CRITICAL"},
                {"anomaly_id": "a1", "risk_score": 85.2, "severity": "HIGH"},
            ],
        },
        "estimated_tokens": 250,
    },
    {
        "name": "get_investigation",
        "description": "Get investigation findings for an anomaly",
        "parameters": {
            "type": "object",
            "properties": {"anomaly_id": {"type": "string"}},
            "required": ["anomaly_id"],
        },
        "handler": lambda **kw: {
            "anomaly_id": kw.get("anomaly_id", "a1"),
            "findings": "Unusual login from new IP in foreign country",
            "recommendation": "Verify with user",
        },
        "estimated_tokens": 300,
    },
    {
        "name": "get_user_behaviour_baseline",
        "description": "Get normal behaviour baseline for a user",
        "parameters": {
            "type": "object",
            "properties": {"username": {"type": "string"}},
            "required": ["username"],
        },
        "handler": lambda **kw: {
            "username": kw.get("username", "alice@co.com"),
            "usual_hours": "09:00-17:00",
            "usual_device": "laptop",
            "usual_location": "London",
        },
        "estimated_tokens": 200,
    },
    {
        "name": "get_neo4j_graph",
        "description": "Query the knowledge graph",
        "parameters": {
            "type": "object",
            "properties": {"entity": {"type": "string"}, "depth": {"type": "integer"}},
            "required": ["entity"],
        },
        "handler": lambda **kw: {
            "nodes": [
                {"id": kw.get("entity", "alice"), "type": "user"},
                {"id": "a1", "type": "anomaly"},
            ],
            "edges": [{"from": kw.get("entity", "alice"), "to": "a1", "type": "HAS_ANOMALY"}],
        },
        "estimated_tokens": 350,
    },
    {
        "name": "get_anomaly_timeline",
        "description": "Get timeline of anomalies for a user",
        "parameters": {
            "type": "object",
            "properties": {"user_id": {"type": "string"}, "days": {"type": "integer"}},
            "required": ["user_id"],
        },
        "handler": lambda **kw: {
            "user_id": kw.get("user_id", "alice@co.com"),
            "events": [
                {"date": "2026-04-15", "count": 2, "max_severity": "CRITICAL"},
                {"date": "2026-04-14", "count": 1, "max_severity": "HIGH"},
            ],
        },
        "estimated_tokens": 250,
    },
    {
        "name": "get_root_cause_summary",
        "description": "Summarise root causes across anomalies",
        "parameters": {
            "type": "object",
            "properties": {"severity": {"type": "string"}},
            "required": [],
        },
        "handler": lambda **kw: {
            "causes": [
                {"cause": "Unusual login location", "count": 12},
                {"cause": "Off-hours access", "count": 8},
                {"cause": "New device", "count": 5},
            ],
        },
        "estimated_tokens": 250,
    },
    {
        "name": "semantic_search_anomalies",
        "description": "Semantic search across anomaly descriptions",
        "parameters": {
            "type": "object",
            "properties": {"query": {"type": "string"}, "limit": {"type": "integer"}},
            "required": ["query"],
        },
        "handler": lambda **kw: {
            "results": [
                {"anomaly_id": "a5", "score": 0.95, "snippet": "VPN from unusual country"},
                {"anomaly_id": "a6", "score": 0.88, "snippet": "Login at 3am from mobile"},
            ],
        },
        "estimated_tokens": 300,
    },
    {
        "name": "get_dimension_ranking",
        "description": "Rank anomaly dimensions by contribution",
        "parameters": {
            "type": "object",
            "properties": {"anomaly_id": {"type": "string"}},
            "required": ["anomaly_id"],
        },
        "handler": lambda **kw: {
            "anomaly_id": kw.get("anomaly_id", "a1"),
            "dimensions": [
                {"name": "location", "z_score": 4.5, "contribution": 0.45},
                {"name": "time_of_day", "z_score": 3.2, "contribution": 0.32},
            ],
        },
        "estimated_tokens": 250,
    },
    {
        "name": "get_llm_explanations",
        "description": "Get LLM-generated explanations for anomalies",
        "parameters": {
            "type": "object",
            "properties": {"anomaly_id": {"type": "string"}},
            "required": ["anomaly_id"],
        },
        "handler": lambda **kw: {
            "anomaly_id": kw.get("anomaly_id", "a1"),
            "explanation": "This anomaly was flagged because the user logged in from a new location.",
        },
        "estimated_tokens": 200,
    },
]


def _make_full_registry() -> ToolRegistry:
    """Build a ToolRegistry with all 14 tools."""
    reg = ToolRegistry()
    for td in _TOOL_DEFS:
        reg.register(ToolSpec(**td))
    return reg


def _mock_llm(responses: list[str]):
    """Create a mock OpenAI client returning responses in sequence."""
    client = MagicMock()
    idx = {"n": 0}

    def _create(**kwargs):
        i = min(idx["n"], len(responses) - 1)
        idx["n"] += 1
        choice = MagicMock()
        choice.message.content = responses[i]
        return MagicMock(choices=[choice])

    client.chat.completions.create.side_effect = _create
    return client


def _run(
    query: str, responses: list[str], *, history: list | None = None, intent: dict | None = None, max_iter: int = 6
) -> AgentResponse:
    """Convenience: build agent, run query, return result."""
    registry = _make_full_registry()
    client = _mock_llm(responses)
    agent = AgentCore(registry, client, "gpt-4o-mini", "llama-3.3-70b", AgentConfig(max_iterations=max_iter))
    return agent.run(query, history or [], intent=intent)


# ═══════════════════════════════════════════════════════════════════════
#  E2E Scenario 1: Risk summary (single tool)
# ═══════════════════════════════════════════════════════════════════════


class TestE2ERiskSummary:
    """Simple risk overview uses get_risk_summary."""

    def test_risk_overview(self):
        result = _run(
            "What's the overall risk level?",
            [
                "THOUGHT: Need platform risk data.\nACTION: get_risk_summary\nACTION_INPUT: {}",
                "THOUGHT: Got it.\nANSWER: The platform has 42 anomalies: 5 critical, 15 high, 12 medium, 10 low.",
                "SUFFICIENT: yes\nFEEDBACK: Complete.",
                "The platform has 42 anomalies: 5 critical, 15 high, 12 medium, 10 low.",
            ],
        )
        assert "42" in result.answer
        assert "get_risk_summary" in result.tools_used


# ═══════════════════════════════════════════════════════════════════════
#  E2E Scenario 2: User profile lookup
# ═══════════════════════════════════════════════════════════════════════


class TestE2EUserProfile:
    """User-specific query uses get_user_profile."""

    def test_single_user(self):
        result = _run(
            "Tell me about alice@co.com",
            [
                'THOUGHT: Need user profile.\nACTION: get_user_profile\nACTION_INPUT: {"username": "alice@co.com"}',
                "THOUGHT: Got profile.\nANSWER: alice@co.com has 5 anomalies with risk score 72.5.",
                "SUFFICIENT: yes\nFEEDBACK: Good.",
                "alice@co.com has 5 anomalies with risk score 72.5.",
            ],
        )
        assert "72.5" in result.answer
        assert "get_user_profile" in result.tools_used


# ═══════════════════════════════════════════════════════════════════════
#  E2E Scenario 3: Anomaly detail
# ═══════════════════════════════════════════════════════════════════════


class TestE2EAnomalyDetail:
    """Anomaly detail query uses get_anomaly_detail."""

    def test_anomaly_lookup(self):
        result = _run(
            "What happened with anomaly a1?",
            [
                'THOUGHT: Look up anomaly.\nACTION: get_anomaly_detail\nACTION_INPUT: {"anomaly_id": "a1"}',
                "THOUGHT: Got details.\nANSWER: Anomaly a1 for alice@co.com: HIGH severity, risk 85.2, caused by unusual login location.",
                "SUFFICIENT: yes\nFEEDBACK: Complete.",
                "Anomaly a1 for alice@co.com: HIGH severity, risk 85.2, caused by unusual login location.",
            ],
        )
        assert "a1" in result.answer
        assert "get_anomaly_detail" in result.tools_used


# ═══════════════════════════════════════════════════════════════════════
#  E2E Scenario 4: Search + detail (two-tool chain)
# ═══════════════════════════════════════════════════════════════════════


class TestE2ESearchThenDetail:
    """Search anomalies then drill into one."""

    def test_search_then_drill(self):
        result = _run(
            "Find critical anomalies and explain the worst one",
            [
                'THOUGHT: Search for critical.\nACTION: search_anomalies\nACTION_INPUT: {"severity": "CRITICAL"}',
                'THOUGHT: a2 is the worst. Get detail.\nACTION: get_anomaly_detail\nACTION_INPUT: {"anomaly_id": "a2"}',
                "THOUGHT: Got both.\nANSWER: Found 3 anomalies. The worst is a2 (92.1 risk, CRITICAL).",
                "SUFFICIENT: yes\nFEEDBACK: Good drill-down.",
                "Found 3 anomalies. The worst is a2 (92.1 risk, CRITICAL).",
            ],
        )
        assert "a2" in result.answer
        assert "search_anomalies" in result.tools_used
        assert "get_anomaly_detail" in result.tools_used


# ═══════════════════════════════════════════════════════════════════════
#  E2E Scenario 5: User comparison (planned, multi-tool)
# ═══════════════════════════════════════════════════════════════════════


class TestE2EUserComparison:
    """Compare two users — triggers planning."""

    def test_compare_profiles(self):
        plan = json.dumps(
            {
                "goal": "Compare alice and bob profiles",
                "steps": [
                    {
                        "id": 1,
                        "action": "get_user_profile",
                        "params": {"username": "alice@co.com"},
                        "purpose": "Alice profile",
                        "depends_on": [],
                    },
                    {
                        "id": 2,
                        "action": "get_user_profile",
                        "params": {"username": "bob@co.com"},
                        "purpose": "Bob profile",
                        "depends_on": [],
                    },
                    {"id": 3, "action": "synthesize", "params": {}, "purpose": "Compare", "depends_on": [1, 2]},
                ],
            }
        )
        result = _run(
            "Compare alice@co.com and bob@co.com",
            [
                plan,
                'THOUGHT: Get alice.\nACTION: get_user_profile\nACTION_INPUT: {"username": "alice@co.com"}',
                'THOUGHT: Get bob.\nACTION: get_user_profile\nACTION_INPUT: {"username": "bob@co.com"}',
                "THOUGHT: Both profiles in hand.\nANSWER: Alice: 5 anomalies, risk 72.5. Bob: 5 anomalies, risk 72.5. Similar profiles.",
                "SUFFICIENT: yes\nFEEDBACK: Both covered.",
                "Alice: 5 anomalies, risk 72.5. Bob: 5 anomalies, risk 72.5. Similar profiles.",
            ],
            intent={"entities": "alice@co.com, bob@co.com"},
        )
        assert "get_user_profile" in result.tools_used
        assert result.steps >= 2


# ═══════════════════════════════════════════════════════════════════════
#  E2E Scenario 6: Investigation with explanation
# ═══════════════════════════════════════════════════════════════════════


class TestE2EInvestigation:
    """Investigate anomaly uses investigation + explanation tools."""

    def test_investigate_anomaly(self):
        result = _run(
            "Investigate anomaly a1",
            [
                'THOUGHT: Get investigation.\nACTION: get_investigation\nACTION_INPUT: {"anomaly_id": "a1"}',
                'THOUGHT: Also get explanation.\nACTION: get_llm_explanations\nACTION_INPUT: {"anomaly_id": "a1"}',
                "THOUGHT: Full picture.\nANSWER: Anomaly a1: unusual login from foreign country. Flagged due to new location.",
                "SUFFICIENT: yes\nFEEDBACK: Thorough.",
            ],
        )
        assert "get_investigation" in result.tools_used
        assert "get_llm_explanations" in result.tools_used


# ═══════════════════════════════════════════════════════════════════════
#  E2E Scenario 7: Similar anomalies
# ═══════════════════════════════════════════════════════════════════════


class TestE2ESimilarAnomalies:
    """Find similar anomalies to a given one (triggers planning via 'similar to')."""

    def test_similar_search(self):
        plan = json.dumps(
            {
                "goal": "Find similar anomalies",
                "steps": [
                    {
                        "id": 1,
                        "action": "get_similar_anomalies",
                        "params": {"anomaly_id": "a1"},
                        "purpose": "Find similar",
                        "depends_on": [],
                    },
                    {"id": 2, "action": "synthesize", "params": {}, "purpose": "Summarise", "depends_on": [1]},
                ],
            }
        )
        result = _run(
            "What anomalies are similar to a1?",
            [
                plan,
                'THOUGHT: Search similar.\nACTION: get_similar_anomalies\nACTION_INPUT: {"anomaly_id": "a1"}',
                "THOUGHT: Found matches.\nANSWER: a3 (92% similar, carol@co.com) and a4 (87% similar, alice@co.com).",
                "SUFFICIENT: yes\nFEEDBACK: Good.",
                "a3 (92% similar, carol@co.com) and a4 (87% similar, alice@co.com).",
            ],
        )
        assert "get_similar_anomalies" in result.tools_used
        assert "a3" in result.answer or "92" in result.answer


# ═══════════════════════════════════════════════════════════════════════
#  E2E Scenario 8: Top anomalies
# ═══════════════════════════════════════════════════════════════════════


class TestE2ETopAnomalies:
    """Get top anomalies by risk score."""

    def test_top_risks(self):
        result = _run(
            "Show me the top anomalies",
            [
                "THOUGHT: Get top anomalies.\nACTION: get_top_anomalies\nACTION_INPUT: {}",
                "THOUGHT: Got them.\nANSWER: Top anomalies: a2 (92.1 risk, CRITICAL), a1 (85.2 risk, HIGH).",
                "SUFFICIENT: yes\nFEEDBACK: Clear.",
                "Top anomalies: a2 (92.1 risk, CRITICAL), a1 (85.2 risk, HIGH).",
            ],
        )
        assert "get_top_anomalies" in result.tools_used
        assert "92.1" in result.answer or "a2" in result.answer


# ═══════════════════════════════════════════════════════════════════════
#  E2E Scenario 9: Timeline query
# ═══════════════════════════════════════════════════════════════════════


class TestE2ETimeline:
    """User anomaly timeline over time."""

    def test_user_timeline(self):
        result = _run(
            "Show alice's anomaly timeline",
            [
                'THOUGHT: Get timeline.\nACTION: get_anomaly_timeline\nACTION_INPUT: {"user_id": "alice@co.com"}',
                "THOUGHT: Got timeline.\nANSWER: Alice had 2 anomalies on Apr 15 (max CRITICAL) and 1 on Apr 14 (HIGH).",
                "SUFFICIENT: yes\nFEEDBACK: Good timeline.",
            ],
        )
        assert "get_anomaly_timeline" in result.tools_used


# ═══════════════════════════════════════════════════════════════════════
#  E2E Scenario 10: Root cause analysis
# ═══════════════════════════════════════════════════════════════════════


class TestE2ERootCause:
    """Root cause summary across anomalies."""

    def test_root_causes(self):
        result = _run(
            "What are the main root causes of anomalies?",
            [
                "THOUGHT: Get root causes.\nACTION: get_root_cause_summary\nACTION_INPUT: {}",
                "THOUGHT: Got causes.\nANSWER: Top causes: unusual login location (12), off-hours access (8), new device (5).",
                "SUFFICIENT: yes\nFEEDBACK: Complete.",
                "Top causes: unusual login location (12), off-hours access (8), new device (5).",
            ],
        )
        assert "get_root_cause_summary" in result.tools_used
        assert "12" in result.answer or "location" in result.answer.lower()


# ═══════════════════════════════════════════════════════════════════════
#  E2E Scenario 11: Semantic search
# ═══════════════════════════════════════════════════════════════════════


class TestE2ESemanticSearch:
    """Semantic search for anomaly descriptions."""

    def test_semantic_query(self):
        result = _run(
            "Find anomalies related to VPN usage",
            [
                'THOUGHT: Semantic search.\nACTION: semantic_search_anomalies\nACTION_INPUT: {"query": "VPN usage", "limit": 5}',
                "THOUGHT: Found results.\nANSWER: Found 2 VPN-related anomalies: a5 (VPN from unusual country) and a6 (login at 3am from mobile).",
                "SUFFICIENT: yes\nFEEDBACK: Relevant results.",
            ],
        )
        assert "semantic_search_anomalies" in result.tools_used


# ═══════════════════════════════════════════════════════════════════════
#  E2E Scenario 12: Dimension ranking
# ═══════════════════════════════════════════════════════════════════════


class TestE2EDimensionRanking:
    """Rank which dimensions contributed most to an anomaly."""

    def test_dimension_breakdown(self):
        result = _run(
            "What dimensions drove anomaly a1?",
            [
                'THOUGHT: Get dimensions.\nACTION: get_dimension_ranking\nACTION_INPUT: {"anomaly_id": "a1"}',
                "THOUGHT: Got ranking.\nANSWER: Location (z=4.5, 45%) and time_of_day (z=3.2, 32%) were the top contributors.",
                "SUFFICIENT: yes\nFEEDBACK: Clear breakdown.",
                "Location (z=4.5, 45%) and time_of_day (z=3.2, 32%) were the top contributors.",
            ],
        )
        assert "get_dimension_ranking" in result.tools_used
        assert "location" in result.answer.lower() or "4.5" in result.answer


# ═══════════════════════════════════════════════════════════════════════
#  E2E Scenario 13: Knowledge graph
# ═══════════════════════════════════════════════════════════════════════


class TestE2EKnowledgeGraph:
    """Query the knowledge graph for entity relationships."""

    def test_graph_query(self):
        result = _run(
            "Show me alice's connections in the graph",
            [
                'THOUGHT: Query graph.\nACTION: get_neo4j_graph\nACTION_INPUT: {"entity": "alice@co.com", "depth": 2}',
                "THOUGHT: Got graph.\nANSWER: Alice is connected to anomaly a1 via HAS_ANOMALY relationship.",
                "SUFFICIENT: yes\nFEEDBACK: Graph shown.",
            ],
        )
        assert "get_neo4j_graph" in result.tools_used


# ═══════════════════════════════════════════════════════════════════════
#  E2E Scenario 14: User baseline comparison
# ═══════════════════════════════════════════════════════════════════════


class TestE2EBaselineComparison:
    """Compare user behaviour to their baseline (triggers planning via 'compare')."""

    def test_baseline_vs_anomaly(self):
        plan = json.dumps(
            {
                "goal": "Compare alice's recent behaviour to baseline",
                "steps": [
                    {
                        "id": 1,
                        "action": "get_user_behaviour_baseline",
                        "params": {"username": "alice@co.com"},
                        "purpose": "Get baseline",
                        "depends_on": [],
                    },
                    {
                        "id": 2,
                        "action": "get_anomaly_timeline",
                        "params": {"user_id": "alice@co.com"},
                        "purpose": "Get recent",
                        "depends_on": [],
                    },
                    {"id": 3, "action": "synthesize", "params": {}, "purpose": "Compare", "depends_on": [1, 2]},
                ],
            }
        )
        result = _run(
            "How does alice's recent behaviour compare to her baseline?",
            [
                plan,
                'THOUGHT: Get baseline.\nACTION: get_user_behaviour_baseline\nACTION_INPUT: {"username": "alice@co.com"}',
                'THOUGHT: Get timeline.\nACTION: get_anomaly_timeline\nACTION_INPUT: {"user_id": "alice@co.com"}',
                "THOUGHT: Can compare.\nANSWER: Alice normally works 09:00-17:00 from London on laptop. Recent anomalies show activity outside these norms.",
                "SUFFICIENT: yes\nFEEDBACK: Good comparison.",
            ],
        )
        assert "get_user_behaviour_baseline" in result.tools_used
        assert "get_anomaly_timeline" in result.tools_used


# ═══════════════════════════════════════════════════════════════════════
#  E2E Scenario 15: Multi-turn context
# ═══════════════════════════════════════════════════════════════════════


class TestE2EMultiTurn:
    """Follow-up query using conversational history."""

    def test_followup_with_history(self):
        history = [
            {"role": "user", "content": "Tell me about alice@co.com"},
            {"role": "assistant", "content": "Alice has 5 anomalies with risk 72.5."},
        ]
        result = _run(
            "What are her top anomalies?",
            [
                'THOUGHT: User refers to alice from context.\nACTION: search_anomalies\nACTION_INPUT: {"user_id": "alice@co.com", "limit": 5}',
                "THOUGHT: Got anomalies.\nANSWER: Alice's top anomalies: a1 (85.2), a2 (92.1).",
                "SUFFICIENT: yes\nFEEDBACK: Good follow-up.",
            ],
            history=history,
        )
        assert "search_anomalies" in result.tools_used


# ═══════════════════════════════════════════════════════════════════════
#  E2E Scenario 16: Reflection rejection and retry
# ═══════════════════════════════════════════════════════════════════════


class TestE2EReflectionRejection:
    """Reflector rejects first answer, agent gathers more data."""

    def test_retry_after_rejection(self):
        result = _run(
            "Explain the top critical anomalies and their root causes",
            [
                'THOUGHT: Get top.\nACTION: get_top_anomalies\nACTION_INPUT: {"severity": "CRITICAL"}',
                "THOUGHT: Found them.\nANSWER: There are critical anomalies.",
                "SUFFICIENT: no\nFEEDBACK: Need root cause details",
                "THOUGHT: Get root causes.\nACTION: get_root_cause_summary\nACTION_INPUT: {}",
                "THOUGHT: Now complete.\nANSWER: Top critical anomalies: a2 (92.1). Main root causes: unusual login location (12 cases) and off-hours access (8 cases).",
                "SUFFICIENT: yes\nFEEDBACK: Full picture.",
            ],
        )
        assert result.steps >= 3
        assert "get_root_cause_summary" in result.tools_used


# ═══════════════════════════════════════════════════════════════════════
#  E2E Scenario 17: Tool failure recovery
# ═══════════════════════════════════════════════════════════════════════


class TestE2EToolFailureRecovery:
    """Agent recovers when a tool fails."""

    def test_fallback_on_failure(self):
        registry = _make_full_registry()
        # Replace get_investigation with a failing version
        registry._tools.pop("get_investigation")
        registry.register(
            ToolSpec(
                name="get_investigation",
                description="Get investigation findings",
                parameters={
                    "type": "object",
                    "properties": {"anomaly_id": {"type": "string"}},
                    "required": ["anomaly_id"],
                },
                handler=lambda **kw: (_ for _ in ()).throw(RuntimeError("Service unavailable")),
                estimated_tokens=300,
                max_retries=0,
            )
        )
        client = _mock_llm(
            [
                'THOUGHT: Investigate.\nACTION: get_investigation\nACTION_INPUT: {"anomaly_id": "a1"}',
                'THOUGHT: Failed. Try detail instead.\nACTION: get_anomaly_detail\nACTION_INPUT: {"anomaly_id": "a1"}',
                "THOUGHT: Got detail.\nANSWER: Could not get investigation findings, but anomaly a1 is HIGH severity for alice@co.com, caused by unusual login.",
                "SUFFICIENT: yes\nFEEDBACK: Handled failure.",
            ]
        )
        agent = AgentCore(registry, client, "gpt-4o-mini", "llama-3.3-70b", AgentConfig(max_iterations=6))
        result = agent.run("Investigate anomaly a1", [])
        assert isinstance(result, AgentResponse)
        assert len(result.answer) > 0


# ═══════════════════════════════════════════════════════════════════════
#  E2E Scenario 18: Budget exhaustion → forced answer
# ═══════════════════════════════════════════════════════════════════════


class TestE2EBudgetExhaustion:
    """Agent answers even when iteration budget runs out."""

    def test_force_answer(self):
        result = _run(
            "Full analysis of everything",
            [
                "THOUGHT: Start.\nACTION: get_risk_summary\nACTION_INPUT: {}",
                'THOUGHT: More.\nACTION: search_anomalies\nACTION_INPUT: {"severity": "CRITICAL"}',
                "Based on available data: 42 anomalies total, 5 critical. The platform risk level is moderate.",
            ],
            max_iter=2,
        )
        assert isinstance(result, AgentResponse)
        assert len(result.answer) > 0


# ═══════════════════════════════════════════════════════════════════════
#  E2E Scenario 19: Empty result handling
# ═══════════════════════════════════════════════════════════════════════


class TestE2EEmptyResults:
    """Agent handles tools that return empty/minimal results."""

    def test_no_anomalies_found(self):
        registry = _make_full_registry()
        registry._tools.pop("search_anomalies")
        registry.register(
            ToolSpec(
                name="search_anomalies",
                description="Search anomalies",
                parameters={"type": "object", "properties": {"user_id": {"type": "string"}}, "required": []},
                handler=lambda **kw: {"total_matching": 0, "anomalies": []},
                estimated_tokens=100,
            )
        )
        client = _mock_llm(
            [
                'THOUGHT: Search.\nACTION: search_anomalies\nACTION_INPUT: {"user_id": "unknown@co.com"}',
                "THOUGHT: No results.\nANSWER: No anomalies found for unknown@co.com.",
                "SUFFICIENT: yes\nFEEDBACK: Correctly handled empty.",
                "No anomalies found for unknown@co.com. The user has no recorded anomalies.",
            ]
        )
        agent = AgentCore(registry, client, "gpt-4o-mini", "llama-3.3-70b", AgentConfig(max_iterations=5))
        result = agent.run("Any anomalies for unknown@co.com?", [])
        assert "no" in result.answer.lower() or "0" in result.answer


# ═══════════════════════════════════════════════════════════════════════
#  E2E Scenario 20: Three-tool chain
# ═══════════════════════════════════════════════════════════════════════


class TestE2EThreeToolChain:
    """Three-tool pipeline: search → detail → similar."""

    def test_search_detail_similar(self):
        result = _run(
            "Find critical anomalies, explain the worst, and find similar ones",
            [
                'THOUGHT: Search critical.\nACTION: search_anomalies\nACTION_INPUT: {"severity": "CRITICAL"}',
                'THOUGHT: Worst is a2. Detail.\nACTION: get_anomaly_detail\nACTION_INPUT: {"anomaly_id": "a2"}',
                'THOUGHT: Now similar.\nACTION: get_similar_anomalies\nACTION_INPUT: {"anomaly_id": "a2"}',
                "THOUGHT: Complete.\nANSWER: Found 3 critical anomalies. Worst: a2 (92.1, bob@co.com). Similar: a3 (92%) and a4 (87%).",
                "SUFFICIENT: yes\nFEEDBACK: Full chain.",
            ],
        )
        assert "search_anomalies" in result.tools_used
        assert "get_anomaly_detail" in result.tools_used
        assert "get_similar_anomalies" in result.tools_used
        assert result.steps >= 3


# ═══════════════════════════════════════════════════════════════════════
#  E2E Scenario 21: Direct answer (no tool needed)
# ═══════════════════════════════════════════════════════════════════════


class TestE2EDirectAnswer:
    """Some queries can be answered without tools."""

    def test_greeting(self):
        result = _run(
            "Hello, what can you do?",
            [
                "THOUGHT: No tool needed.\nANSWER: I can help you analyze security anomalies, investigate user behaviour, search for threats, and more.",
                "SUFFICIENT: yes\nFEEDBACK: Appropriate non-tool response.",
            ],
        )
        assert len(result.tools_used) == 0
        assert len(result.answer) > 0


# ═══════════════════════════════════════════════════════════════════════
#  E2E Scenario 22: All responses have trace
# ═══════════════════════════════════════════════════════════════════════


class TestE2ETracePresent:
    """Every E2E response should carry a reasoning trace."""

    def test_simple_trace(self):
        result = _run(
            "Risk?",
            [
                "THOUGHT: Quick check.\nACTION: get_risk_summary\nACTION_INPUT: {}",
                "THOUGHT: Done.\nANSWER: 42 anomalies.",
                "SUFFICIENT: yes\nFEEDBACK: OK.",
            ],
        )
        assert result.reasoning_trace is not None
        assert len(result.reasoning_trace) > 0
        kinds = {s["kind"] for s in result.reasoning_trace}
        assert "thought" in kinds
        assert "answer" in kinds

    def test_multi_tool_trace(self):
        result = _run(
            "Profile and baseline for alice",
            [
                'THOUGHT: Get profile.\nACTION: get_user_profile\nACTION_INPUT: {"username": "alice@co.com"}',
                'THOUGHT: Get baseline.\nACTION: get_user_behaviour_baseline\nACTION_INPUT: {"username": "alice@co.com"}',
                "THOUGHT: Both done.\nANSWER: Alice has 5 anomalies, normally works 09:00-17:00 from London.",
                "SUFFICIENT: yes\nFEEDBACK: Complete.",
                "Alice has 5 anomalies, normally works 09:00-17:00 from London.",
            ],
        )
        assert result.reasoning_trace is not None
        actions = [s for s in result.reasoning_trace if s["kind"] == "action"]
        assert len(actions) >= 2


# ═══════════════════════════════════════════════════════════════════════
#  E2E Scenario 23: Response quality — answer is non-empty
# ═══════════════════════════════════════════════════════════════════════


class TestE2EResponseQuality:
    """Verify response quality invariants across scenarios."""

    def test_answer_always_non_empty(self):
        """No matter the scenario, the answer should never be empty."""
        scenarios = [
            (
                "Risk?",
                [
                    "THOUGHT: Get.\nACTION: get_risk_summary\nACTION_INPUT: {}",
                    "THOUGHT: Got.\nANSWER: 42 total anomalies.",
                    "SUFFICIENT: yes\nFEEDBACK: OK.",
                ],
            ),
            (
                "Hi",
                [
                    "THOUGHT: Greeting.\nANSWER: Hello! I'm your anomaly analysis assistant.",
                    "SUFFICIENT: yes\nFEEDBACK: OK.",
                ],
            ),
        ]
        for query, responses in scenarios:
            result = _run(query, responses)
            assert len(result.answer.strip()) > 0, f"Empty answer for: {query}"

    def test_tools_used_matches_actions(self):
        """tools_used should reflect the tools actually called."""
        result = _run(
            "Check risk and search anomalies",
            [
                "THOUGHT: Risk first.\nACTION: get_risk_summary\nACTION_INPUT: {}",
                'THOUGHT: Now search.\nACTION: search_anomalies\nACTION_INPUT: {"severity": "HIGH"}',
                "THOUGHT: Done.\nANSWER: 42 anomalies, 3 match HIGH severity.",
                "SUFFICIENT: yes\nFEEDBACK: OK.",
            ],
        )
        assert "get_risk_summary" in result.tools_used
        assert "search_anomalies" in result.tools_used
