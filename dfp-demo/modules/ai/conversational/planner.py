"""
Query Planner — decomposes complex analyst questions into ordered sub-tasks.

Triggered when the query involves comparison, multi-entity analysis,
cross-referencing, or causal reasoning.  Produces an advisory plan that
the :class:`AgentCore` follows (but may deviate from based on observations).
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from typing import Any

from modules.ai.shared.json_parser import parse_llm_json

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class PlanStep:
    """A single step in a query execution plan."""

    id: int
    action: str  # tool name or "synthesize"
    purpose: str  # why this step is needed
    params: dict[str, Any] = field(default_factory=dict)
    depends_on: list[int] = field(default_factory=list)
    completed: bool = False
    skipped: bool = False


@dataclass(slots=True)
class QueryPlan:
    """An ordered execution plan for a complex query."""

    goal: str
    steps: list[PlanStep]
    is_complex: bool = True

    @property
    def pending_steps(self) -> list[PlanStep]:
        return [s for s in self.steps if not s.completed and not s.skipped]

    @property
    def next_step(self) -> PlanStep | None:
        for s in self.steps:
            if not s.completed and not s.skipped:
                return s
        return None

    def mark_completed(self, step_id: int) -> None:
        for s in self.steps:
            if s.id == step_id:
                s.completed = True
                return

    def mark_skipped(self, step_id: int) -> None:
        for s in self.steps:
            if s.id == step_id:
                s.skipped = True
                return

    def skip_dependents(self, step_id: int) -> None:
        """Skip all steps that depend on *step_id*."""
        for s in self.steps:
            if step_id in s.depends_on:
                s.skipped = True
                # Recursively skip anything depending on this skipped step
                self.skip_dependents(s.id)

    def summary(self) -> str:
        lines: list[str] = [f"PLAN: {self.goal}"]
        for s in self.steps:
            status = "✓" if s.completed else ("⊘" if s.skipped else "○")
            deps = f" (after step {s.depends_on})" if s.depends_on else ""
            lines.append(f"  {status} Step {s.id}: {s.action} — {s.purpose}{deps}")
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Complexity detection
# ---------------------------------------------------------------------------

COMPLEXITY_INDICATORS: list[str] = [
    "compare",
    "versus",
    "vs",
    "difference between",
    "correlation",
    "relationship",
    "trend over",
    "changed over",
    "all users",
    "every user",
    "each user",
    "similar to",
    "like the",
    "and also",
    "additionally",
    "as well as",
    "why",
    "explain why",
    "root cause of",
    "which.*have no",
    "which.*without",
    "cross-reference",
    "correlate",
]

# Compiled for performance
_COMPLEXITY_RE = re.compile(
    "|".join(re.escape(p) if not any(c in p for c in ".*+?[]()") else p for p in COMPLEXITY_INDICATORS),
    re.IGNORECASE,
)


def needs_planning(query: str, intent: dict[str, Any] | None = None) -> bool:
    """
    Determine if a query is complex enough to benefit from up-front planning.

    Checks:
    - Keyword indicators (compare, vs, trend, etc.)
    - Multiple entities mentioned in intent analysis
    - Multiple data dimensions required
    """
    if _COMPLEXITY_RE.search(query):
        return True

    if intent:
        # Multiple named entities (users, anomaly IDs)
        entities = intent.get("entities", "")
        if isinstance(entities, str) and entities.lower() != "none":
            # Count comma-separated or "and"-separated entities
            parts = re.split(r"[,;]|\band\b", entities)
            if len([p for p in parts if p.strip()]) > 1:
                return True

        # Multiple dimensions
        dims = intent.get("dimensions", "")
        if isinstance(dims, str):
            parts = re.split(r"[,/;]", dims)
            if len([p for p in parts if p.strip()]) > 2:
                return True

    return False


# ---------------------------------------------------------------------------
# Planner prompt
# ---------------------------------------------------------------------------

PLANNER_PROMPT = """\
You are a query planner for a cybersecurity anomaly detection platform.

Given a user's question, decompose it into an ordered list of tool-call steps \
that will gather ALL the data needed to answer comprehensively.

Available tools (with key capabilities):
- search_anomalies — filter anomaly records by severity, username, date range
- get_anomaly_detail — full detail for a single anomaly by UUID
- get_user_profile — user profile + anomaly stats + recent anomalies
- get_user_behaviour_baseline — normal behaviour: hours, devices, apps, locations
- semantic_search_anomalies — vector similarity search by description
- get_risk_summary — platform-wide aggregate stats, user rankings, daily trend
- get_top_anomalies — individual anomalies sorted by risk_score DESC
- get_investigation — AI agent investigation findings for anomalies
- get_llm_explanations — LLM-generated analytical explanations
- get_root_cause_summary — aggregate stats by root cause category
- get_anomaly_timeline — time-series daily/weekly counts and trend
- get_dimension_ranking — top-N entities for any dimension (city, user, device, etc.)
- get_neo4j_graph — network relationship edges from knowledge graph

Respond in exactly this JSON format (no markdown fences, no commentary):
{"goal": "one-sentence goal", "steps": [\
{"id": 1, "action": "tool_name", "params": {}, "purpose": "why", "depends_on": []}, \
...]}

Rules:
- Each step has a SINGLE tool call (except the final "synthesize" step which has no tool).
- Include a final step with action "synthesize" when you need to combine data from earlier steps.
- Use "depends_on" when a step needs results from a prior step (e.g. username from step 1).
- For ANY question involving a specific user, you MUST include BOTH get_user_profile AND get_user_behaviour_baseline for that user. Never omit the baseline step.
- For comparison questions, gather complete data for BOTH sides (profile + baseline each) before the synthesize step.
- Keep plans short: 2-6 steps max. Simple queries need 2 steps (1 tool + synthesize).
- Leave parameter values as placeholders like "<from_step_1>" when they depend on earlier results.
- Include get_llm_explanations when the user asks for explanations, analysis, or "why" something happened.
- Include get_investigation when the user asks about investigation findings or wants a deeper audit.
- For simple comparisons (e.g. "who is riskier"), profiles and baselines are sufficient — do not add explanations or investigation steps unless they are clearly relevant.
"""


# ---------------------------------------------------------------------------
# QueryPlanner class
# ---------------------------------------------------------------------------


class QueryPlanner:
    """
    Decomposes complex queries into ordered sub-tasks.

    Uses the cheap router model for plan generation.
    Plans are advisory — the agent can deviate based on observations.
    """

    def __init__(self, client: Any, model: str) -> None:
        self._client = client
        self._model = model

    def generate_plan(self, query: str, intent: dict[str, Any] | None = None) -> QueryPlan | None:
        """
        Generate an execution plan for a complex query.

        Returns ``None`` if the LLM response cannot be parsed.
        """
        user_prompt = f"Query: {query}"
        if intent:
            user_prompt += f"\nIntent analysis: {json.dumps(intent, default=str)}"

        try:
            response = self._client.chat.completions.create(
                model=self._model,
                messages=[
                    {"role": "system", "content": PLANNER_PROMPT},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=0.0,
                max_tokens=800,
            )
            raw = (response.choices[0].message.content or "").strip()
            plan = self._parse_plan(raw)
            if plan:
                return plan
            logger.warning("Plan parsing failed, raw response: %s", raw[:300])
            return None
        except Exception as exc:
            logger.warning("Plan generation failed: %s", exc)
            return None

    @staticmethod
    def _parse_plan(raw: str) -> QueryPlan | None:
        """Parse the LLM's JSON plan into a QueryPlan."""
        try:
            data = parse_llm_json(raw)
        except ValueError:
            logger.warning("Could not parse plan JSON from: %s", raw[:300])
            return None

        if not isinstance(data, dict) or "steps" not in data:
            logger.warning("Plan missing 'steps' key: %s", raw[:200])
            return None

        steps: list[PlanStep] = []
        for s in data["steps"]:
            steps.append(
                PlanStep(
                    id=s.get("id", len(steps) + 1),
                    action=s.get("action", ""),
                    purpose=s.get("purpose", ""),
                    params=s.get("params", {}),
                    depends_on=s.get("depends_on", []),
                )
            )

        return QueryPlan(
            goal=data.get("goal", "Answer the query"),
            steps=steps,
        )
