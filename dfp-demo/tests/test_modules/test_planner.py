"""
Unit tests for Week 26 — Planning + Multi-Step Reasoning.

Covers:
- QueryPlanner: needs_planning heuristics, plan parsing, PlanStep/QueryPlan
- Reflector: reflection parsing, budget tracking
- Meta-tools: summarize_results, refine_query, ask_clarification
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import MagicMock

sys.path.insert(0, str(Path(__file__).parents[2]))

from modules.ai.conversational.planner import (
    PlanStep,
    QueryPlan,
    QueryPlanner,
    needs_planning,
)
from modules.ai.conversational.reflector import Reflector

# ═══════════════════════════════════════════════════════════════════════
#  needs_planning heuristics
# ═══════════════════════════════════════════════════════════════════════


class TestNeedsPlanning:
    """Keyword- and intent-based complexity detection."""

    def test_simple_query_no_planning(self):
        assert needs_planning("Show me critical anomalies") is False

    def test_comparison_keyword(self):
        assert needs_planning("Compare alice and bob's anomaly patterns") is True

    def test_versus_keyword(self):
        assert needs_planning("alice vs bob") is True

    def test_trend_keyword(self):
        assert needs_planning("How have anomalies changed over time?") is True

    def test_root_cause_keyword(self):
        assert needs_planning("What is the root cause of this anomaly?") is True

    def test_correlation_keyword(self):
        assert needs_planning("Is there a correlation between login time and risk?") is True

    def test_all_users_keyword(self):
        assert needs_planning("Show all users with high risk") is True

    def test_multiple_entities_in_intent(self):
        intent = {"entities": "alice@contoso.com, bob@contoso.com"}
        assert needs_planning("Show their profiles", intent) is True

    def test_single_entity_no_planning(self):
        intent = {"entities": "alice@contoso.com"}
        assert needs_planning("Show profile", intent) is False

    def test_many_dimensions_triggers_planning(self):
        intent = {"dimensions": "severity/user/time/city"}
        assert needs_planning("Show breakdown", intent) is True

    def test_few_dimensions_no_planning(self):
        intent = {"dimensions": "severity, user"}
        assert needs_planning("Show breakdown", intent) is False

    def test_entities_none_string(self):
        intent = {"entities": "none"}
        assert needs_planning("Show data", intent) is False

    def test_and_separated_entities(self):
        intent = {"entities": "alice@contoso.com and bob@contoso.com"}
        assert needs_planning("Compare users", intent) is True


# ═══════════════════════════════════════════════════════════════════════
#  QueryPlan data structure
# ═══════════════════════════════════════════════════════════════════════


class TestQueryPlan:
    """QueryPlan step tracking and management."""

    def _make_plan(self) -> QueryPlan:
        return QueryPlan(
            goal="Compare two users",
            steps=[
                PlanStep(id=1, action="get_user_profile", purpose="Get alice", params={"username": "alice"}),
                PlanStep(id=2, action="get_user_profile", purpose="Get bob", params={"username": "bob"}),
                PlanStep(id=3, action="synthesize", purpose="Compare profiles", depends_on=[1, 2]),
            ],
        )

    def test_next_step(self):
        plan = self._make_plan()
        assert plan.next_step is not None
        assert plan.next_step.id == 1

    def test_mark_completed(self):
        plan = self._make_plan()
        plan.mark_completed(1)
        assert plan.steps[0].completed is True
        assert plan.next_step is not None
        assert plan.next_step.id == 2

    def test_pending_steps(self):
        plan = self._make_plan()
        assert len(plan.pending_steps) == 3
        plan.mark_completed(1)
        assert len(plan.pending_steps) == 2

    def test_mark_skipped(self):
        plan = self._make_plan()
        plan.mark_skipped(2)
        assert plan.steps[1].skipped is True
        pending = plan.pending_steps
        assert len(pending) == 2  # steps 1 and 3

    def test_skip_dependents(self):
        plan = self._make_plan()
        plan.skip_dependents(1)
        # Step 3 depends on step 1, so it should be skipped
        assert plan.steps[2].skipped is True

    def test_all_done(self):
        plan = self._make_plan()
        for s in plan.steps:
            plan.mark_completed(s.id)
        assert plan.next_step is None
        assert len(plan.pending_steps) == 0

    def test_summary_format(self):
        plan = self._make_plan()
        plan.mark_completed(1)
        summary = plan.summary()
        assert "PLAN:" in summary
        assert "✓" in summary
        assert "○" in summary


# ═══════════════════════════════════════════════════════════════════════
#  QueryPlanner._parse_plan
# ═══════════════════════════════════════════════════════════════════════


class TestParsePlan:
    """Plan JSON parsing from LLM output."""

    def test_valid_json(self):
        raw = json.dumps(
            {
                "goal": "Compare users",
                "steps": [
                    {
                        "id": 1,
                        "action": "get_user_profile",
                        "params": {"username": "alice"},
                        "purpose": "Get alice",
                        "depends_on": [],
                    },
                    {"id": 2, "action": "synthesize", "params": {}, "purpose": "Combine", "depends_on": [1]},
                ],
            }
        )
        plan = QueryPlanner._parse_plan(raw)
        assert plan is not None
        assert plan.goal == "Compare users"
        assert len(plan.steps) == 2
        assert plan.steps[1].depends_on == [1]

    def test_json_with_code_fences(self):
        raw = (
            "```json\n"
            + json.dumps(
                {
                    "goal": "Test",
                    "steps": [
                        {"id": 1, "action": "get_risk_summary", "params": {}, "purpose": "Overview", "depends_on": []}
                    ],
                }
            )
            + "\n```"
        )
        plan = QueryPlanner._parse_plan(raw)
        assert plan is not None
        assert len(plan.steps) == 1

    def test_json_embedded_in_text(self):
        raw = 'Sure! Here is the plan:\n{"goal": "Test", "steps": [{"id": 1, "action": "a", "params": {}, "purpose": "p", "depends_on": []}]}\nHope that helps!'
        plan = QueryPlanner._parse_plan(raw)
        assert plan is not None

    def test_invalid_json_returns_none(self):
        assert QueryPlanner._parse_plan("This is not JSON at all") is None

    def test_missing_steps_returns_none(self):
        assert QueryPlanner._parse_plan('{"goal": "no steps here"}') is None

    def test_empty_steps_allowed(self):
        raw = json.dumps({"goal": "Nothing needed", "steps": []})
        plan = QueryPlanner._parse_plan(raw)
        assert plan is not None
        assert len(plan.steps) == 0


# ═══════════════════════════════════════════════════════════════════════
#  QueryPlanner.generate_plan (with mocked LLM)
# ═══════════════════════════════════════════════════════════════════════


class TestQueryPlannerGenerate:
    """QueryPlanner.generate_plan with mocked OpenAI client."""

    def _make_planner(self, llm_response: str) -> QueryPlanner:
        mock_client = MagicMock()
        mock_choice = MagicMock()
        mock_choice.message.content = llm_response
        mock_client.chat.completions.create.return_value = MagicMock(choices=[mock_choice])
        return QueryPlanner(mock_client, "gpt-4o-mini")

    def test_successful_plan_generation(self):
        response = json.dumps(
            {
                "goal": "Analyse user risk",
                "steps": [
                    {
                        "id": 1,
                        "action": "get_user_profile",
                        "params": {"username": "alice"},
                        "purpose": "Get profile",
                        "depends_on": [],
                    },
                    {
                        "id": 2,
                        "action": "get_user_behaviour_baseline",
                        "params": {"username": "alice"},
                        "purpose": "Get baseline",
                        "depends_on": [],
                    },
                    {"id": 3, "action": "synthesize", "params": {}, "purpose": "Compare", "depends_on": [1, 2]},
                ],
            }
        )
        planner = self._make_planner(response)
        plan = planner.generate_plan("Compare alice's anomalies with her baseline")
        assert plan is not None
        assert len(plan.steps) == 3
        assert plan.goal == "Analyse user risk"

    def test_llm_failure_returns_none(self):
        mock_client = MagicMock()
        mock_client.chat.completions.create.side_effect = RuntimeError("API down")
        planner = QueryPlanner(mock_client, "gpt-4o-mini")
        assert planner.generate_plan("some query") is None

    def test_unparseable_response_returns_none(self):
        planner = self._make_planner("I don't understand the question")
        assert planner.generate_plan("some query") is None


# ═══════════════════════════════════════════════════════════════════════
#  Reflector
# ═══════════════════════════════════════════════════════════════════════


class TestReflector:
    """Reflector standalone module tests."""

    def _make_reflector(self, llm_response: str, max_reflections: int = 2) -> Reflector:
        mock_client = MagicMock()
        mock_choice = MagicMock()
        mock_choice.message.content = llm_response
        mock_client.chat.completions.create.return_value = MagicMock(choices=[mock_choice])
        return Reflector(mock_client, "gpt-4o-mini", max_reflections=max_reflections)

    def test_sufficient_answer(self):
        ref = self._make_reflector("SUFFICIENT: yes\nFEEDBACK: Looks good")
        result = ref.reflect("What is X?", "X is Y.", "tool_a: returned data")
        assert result.sufficient is True
        assert result.feedback == "Looks good"

    def test_insufficient_answer(self):
        ref = self._make_reflector("SUFFICIENT: no\nFEEDBACK: Missing user baseline data")
        result = ref.reflect("Compare users", "Only one user shown", "tool_a: data")
        assert result.sufficient is False
        assert "Missing" in result.feedback

    def test_reflection_budget_exhaustion(self):
        ref = self._make_reflector("SUFFICIENT: no\nFEEDBACK: Incomplete", max_reflections=1)
        r1 = ref.reflect("Q", "A", "scratchpad")
        assert r1.sufficient is False
        # Second call should be auto-accepted due to budget
        r2 = ref.reflect("Q", "A", "scratchpad")
        assert r2.sufficient is True
        assert "budget" in r2.feedback.lower()

    def test_reset_restores_budget(self):
        ref = self._make_reflector("SUFFICIENT: no\nFEEDBACK: Bad", max_reflections=1)
        ref.reflect("Q", "A", "s")
        assert ref.reflections_remaining == 0
        ref.reset()
        assert ref.reflections_remaining == 1

    def test_llm_failure_accepts_answer(self):
        mock_client = MagicMock()
        mock_client.chat.completions.create.side_effect = RuntimeError("API error")
        ref = Reflector(mock_client, "gpt-4o-mini")
        result = ref.reflect("Q", "A", "s")
        assert result.sufficient is True
        assert result.confidence < 0.5

    def test_confidence_heuristic(self):
        ref = self._make_reflector("SUFFICIENT: no\nFEEDBACK: Data is incomplete and partial")
        result = ref.reflect("Q", "A", "s")
        assert result.confidence <= 0.5

    def test_parse_without_feedback_marker(self):
        result = Reflector._parse("SUFFICIENT: yes\nThe answer is fine.")
        assert result.sufficient is True
        assert "fine" in result.feedback


# ═══════════════════════════════════════════════════════════════════════
#  Meta-tools (via register_meta_tools)
# ═══════════════════════════════════════════════════════════════════════


class TestMetaTools:
    """Meta-tool registration and execution."""

    def _setup_agent_with_meta_tools(self):
        from modules.ai.conversational.memory import WorkingMemory
        from modules.ai.conversational.tool_registry import ToolRegistry, register_meta_tools

        registry = ToolRegistry()
        agent = MagicMock()
        agent._memory = WorkingMemory()
        register_meta_tools(registry, agent)
        return registry, agent

    def test_meta_tools_registered(self):
        registry, _ = self._setup_agent_with_meta_tools()
        assert registry.has("summarize_results")
        assert registry.has("refine_query")
        assert registry.has("ask_clarification")

    def test_summarize_results_empty(self):
        registry, _ = self._setup_agent_with_meta_tools()
        result = registry.execute("summarize_results", {})
        assert result.success is True
        assert "No observations" in result.data["summary"]

    def test_summarize_results_with_observations(self):
        registry, agent = self._setup_agent_with_meta_tools()
        agent._memory.add_observation("search_anomalies", {"severity": "HIGH"}, {"total_matching": 5}, tokens=200)
        result = registry.execute("summarize_results", {})
        assert result.success is True
        assert "search_anomalies" in result.data["summary"]
        assert "search_anomalies" in result.data["tools_used"]

    def test_refine_query(self):
        registry, _ = self._setup_agent_with_meta_tools()
        result = registry.execute("refine_query", {"query": "unusual login"})
        assert result.success is True
        assert len(result.data["refined_queries"]) >= 2
        assert "unusual login" in result.data["original"]

    def test_refine_query_with_context(self):
        registry, _ = self._setup_agent_with_meta_tools()
        result = registry.execute("refine_query", {"query": "login", "context": "after midnight"})
        assert result.success is True
        assert any("midnight" in q for q in result.data["refined_queries"])

    def test_ask_clarification(self):
        registry, _ = self._setup_agent_with_meta_tools()
        result = registry.execute(
            "ask_clarification",
            {
                "question": "Which user do you mean?",
                "options": ["alice", "bob"],
            },
        )
        assert result.success is True
        assert result.data["clarification_needed"] is True
        assert len(result.data["options"]) == 2

    def test_meta_tools_source_label(self):
        registry, _ = self._setup_agent_with_meta_tools()
        for name in ("summarize_results", "refine_query", "ask_clarification"):
            spec = registry.get(name)
            assert spec is not None
            assert spec.source_label == "Agent"

    def test_meta_tools_in_schema_text(self):
        registry, _ = self._setup_agent_with_meta_tools()
        text = registry.get_schemas_text()
        assert "summarize_results" in text
        assert "refine_query" in text
        assert "ask_clarification" in text
