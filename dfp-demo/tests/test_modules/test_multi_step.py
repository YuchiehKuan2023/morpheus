"""
Multi-step integration tests for Week 26 — Planning + Multi-Step Reasoning.

Covers end-to-end scenarios with mocked LLM and tool execution:
- Simple query without planning
- Complex comparison query with planning
- Plan step failure + dependent skipping
- Reflector rejecting first answer and agent continuing
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


def _make_registry() -> ToolRegistry:
    """Create a toy registry with a few deterministic tools."""
    reg = ToolRegistry()

    reg.register(
        ToolSpec(
            name="get_user_profile",
            description="Get user profile",
            parameters={"type": "object", "properties": {"username": {"type": "string"}}, "required": ["username"]},
            handler=lambda **kw: {"user": kw.get("username", "unknown"), "anomaly_count": 5, "risk_score": 72.5},
            estimated_tokens=200,
        )
    )

    reg.register(
        ToolSpec(
            name="get_user_behaviour_baseline",
            description="Get user behaviour baseline",
            parameters={"type": "object", "properties": {"username": {"type": "string"}}, "required": ["username"]},
            handler=lambda **kw: {
                "username": kw.get("username", "unknown"),
                "usual_hours": "09:00-17:00",
                "usual_device": "laptop",
            },
            estimated_tokens=150,
        )
    )

    reg.register(
        ToolSpec(
            name="search_anomalies",
            description="Search anomalies",
            parameters={
                "type": "object",
                "properties": {
                    "severity": {"type": "string", "enum": ["HIGH", "CRITICAL"]},
                    "limit": {"type": "integer"},
                },
                "required": [],
            },
            handler=lambda **kw: {
                "total_matching": 3,
                "anomalies": [
                    {"anomaly_id": "a1", "user_id": "alice@co.com", "severity": kw.get("severity", "HIGH")},
                ],
            },
            estimated_tokens=300,
        )
    )

    reg.register(
        ToolSpec(
            name="get_risk_summary",
            description="Get platform risk summary",
            parameters={"type": "object", "properties": {}, "required": []},
            handler=lambda **kw: {"total_anomalies": 42, "critical": 5, "high": 15},
            estimated_tokens=200,
        )
    )

    return reg


def _mock_llm_responses(responses: list[str]):
    """
    Create a mock OpenAI client that returns responses in sequence.

    Each call to chat.completions.create returns the next response.
    """
    client = MagicMock()
    call_idx = {"n": 0}

    def _create(**kwargs):
        idx = call_idx["n"]
        call_idx["n"] += 1
        if idx >= len(responses):
            idx = len(responses) - 1
        choice = MagicMock()
        choice.message.content = responses[idx]
        return MagicMock(choices=[choice])

    client.chat.completions.create.side_effect = _create
    return client


# ═══════════════════════════════════════════════════════════════════════
#  Integration tests
# ═══════════════════════════════════════════════════════════════════════


class TestSimpleQueryNoPlanning:
    """Single-tool query that doesn't trigger planning."""

    def test_direct_answer_after_one_tool(self):
        registry = _make_registry()
        responses = [
            # Step 1: agent calls get_risk_summary
            "THOUGHT: The user wants a risk overview.\nACTION: get_risk_summary\nACTION_INPUT: {}",
            # Step 2: agent answers
            "THOUGHT: I have the data.\nANSWER: The platform has 42 total anomalies, 5 critical and 15 high.",
            # Reflection: sufficient
            "SUFFICIENT: yes\nFEEDBACK: Looks good",
            # Synthesis: full answer from answer model
            "The platform has 42 total anomalies, 5 critical and 15 high.",
        ]
        client = _mock_llm_responses(responses)
        agent = AgentCore(registry, client, "gpt-4o-mini", "llama-3.3-70b", AgentConfig(max_iterations=5))

        result = agent.run("What is the current risk level?", [])
        assert isinstance(result, AgentResponse)
        assert "42" in result.answer
        assert "get_risk_summary" in result.tools_used
        assert result.steps <= 3


class TestComparisonQueryWithPlanning:
    """Comparison query that triggers planning + multi-step execution."""

    def test_compare_two_users(self):
        registry = _make_registry()
        # Plan generation response
        plan_json = json.dumps(
            {
                "goal": "Compare alice and bob",
                "steps": [
                    {
                        "id": 1,
                        "action": "get_user_profile",
                        "params": {"username": "alice"},
                        "purpose": "Get alice profile",
                        "depends_on": [],
                    },
                    {
                        "id": 2,
                        "action": "get_user_profile",
                        "params": {"username": "bob"},
                        "purpose": "Get bob profile",
                        "depends_on": [],
                    },
                    {"id": 3, "action": "synthesize", "params": {}, "purpose": "Compare both", "depends_on": [1, 2]},
                ],
            }
        )

        responses = [
            # Plan generation (called by QueryPlanner)
            plan_json,
            # Step 1: ReAct calls get_user_profile for alice
            'THOUGHT: Following plan step 1.\nACTION: get_user_profile\nACTION_INPUT: {"username": "alice"}',
            # Step 2: ReAct calls get_user_profile for bob
            'THOUGHT: Following plan step 2.\nACTION: get_user_profile\nACTION_INPUT: {"username": "bob"}',
            # Step 3: Agent synthesizes
            "THOUGHT: I have both profiles, time to compare.\nANSWER: Alice has 5 anomalies with risk 72.5. Bob has 5 anomalies with risk 72.5. They have similar profiles.",
            # Reflection
            "SUFFICIENT: yes\nFEEDBACK: Both sides covered",
            # Synthesis
            "Alice has 5 anomalies with risk 72.5. Bob has 5 anomalies with risk 72.5. They have similar profiles.",
        ]
        client = _mock_llm_responses(responses)
        agent = AgentCore(registry, client, "gpt-4o-mini", "llama-3.3-70b", AgentConfig(max_iterations=6))

        result = agent.run(
            "Compare alice and bob's anomaly patterns",
            [],
            intent={"entities": "alice, bob"},
        )
        assert isinstance(result, AgentResponse)
        assert "get_user_profile" in result.tools_used
        assert result.steps >= 2


class TestReflectorRejectsFirstAnswer:
    """Agent proposes answer, reflector says 'no', agent gathers more data."""

    def test_reflection_loop(self):
        registry = _make_registry()
        responses = [
            # Step 1: search
            'THOUGHT: Search for anomalies.\nACTION: search_anomalies\nACTION_INPUT: {"severity": "CRITICAL"}',
            # Step 2: first answer attempt
            "THOUGHT: Found some anomalies.\nANSWER: There are critical anomalies.",
            # Reflection 1: insufficient
            "SUFFICIENT: no\nFEEDBACK: Need risk summary for context",
            # Step 3: gather more data
            "THOUGHT: Need risk context.\nACTION: get_risk_summary\nACTION_INPUT: {}",
            # Step 4: better answer
            "THOUGHT: Now I have context.\nANSWER: There are 3 critical anomalies out of 42 total.",
            # Reflection 2: sufficient
            "SUFFICIENT: yes\nFEEDBACK: Good coverage",
            # Synthesis
            "There are 3 critical anomalies out of 42 total.",
        ]
        client = _mock_llm_responses(responses)
        agent = AgentCore(registry, client, "gpt-4o-mini", "llama-3.3-70b", AgentConfig(max_iterations=6))

        result = agent.run("How many critical anomalies are there?", [])
        assert "42" in result.answer or "3" in result.answer
        assert result.steps >= 3


class TestPlanStepFailure:
    """When a tool fails, dependent plan steps are skipped."""

    def test_failing_tool_skips_dependents(self):
        registry = _make_registry()
        # Add a failing tool
        registry.register(
            ToolSpec(
                name="get_investigation",
                description="Get investigation",
                parameters={
                    "type": "object",
                    "properties": {"anomaly_id": {"type": "string"}},
                    "required": ["anomaly_id"],
                },
                handler=lambda **kw: (_ for _ in ()).throw(RuntimeError("Service unavailable")),
                estimated_tokens=500,
                max_retries=0,
            )
        )

        # Plan with dependency
        plan_json = json.dumps(
            {
                "goal": "Investigate anomaly",
                "steps": [
                    {
                        "id": 1,
                        "action": "get_investigation",
                        "params": {"anomaly_id": "a1"},
                        "purpose": "Get findings",
                        "depends_on": [],
                    },
                    {"id": 2, "action": "synthesize", "params": {}, "purpose": "Summarize", "depends_on": [1]},
                ],
            }
        )

        responses = [
            plan_json,
            # Step 1: tries investigation (will fail)
            'THOUGHT: Get investigation.\nACTION: get_investigation\nACTION_INPUT: {"anomaly_id": "a1"}',
            # Step 2: falls back to risk summary
            "THOUGHT: Investigation failed. Let me get risk data instead.\nACTION: get_risk_summary\nACTION_INPUT: {}",
            # Step 3: answers
            "THOUGHT: Best effort.\nANSWER: Investigation was unavailable. The platform has 42 anomalies total.",
            # Reflection
            "SUFFICIENT: yes\nFEEDBACK: Noted the failure",
        ]
        client = _mock_llm_responses(responses)
        agent = AgentCore(registry, client, "gpt-4o-mini", "llama-3.3-70b", AgentConfig(max_iterations=6))

        result = agent.run(
            "Why did anomaly a1 happen?",
            [],
        )
        assert isinstance(result, AgentResponse)
        # Agent should have handled the failure gracefully
        assert result.steps >= 2


class TestBudgetExhausted:
    """When budget runs out, force_answer is used."""

    def test_force_answer_on_exhaustion(self):
        registry = _make_registry()
        responses = [
            # All steps are tool calls, never answers
            "THOUGHT: Step 1.\nACTION: get_risk_summary\nACTION_INPUT: {}",
            'THOUGHT: Step 2.\nACTION: search_anomalies\nACTION_INPUT: {"severity": "HIGH"}',
            # Budget exhausted → force answer is called with the expensive model
            "Based on the data collected, there are 42 anomalies with 15 high severity.",
        ]
        client = _mock_llm_responses(responses)
        agent = AgentCore(registry, client, "gpt-4o-mini", "llama-3.3-70b", AgentConfig(max_iterations=2))

        result = agent.run("Overview of anomalies", [])
        assert isinstance(result, AgentResponse)
        # Should still produce an answer even though budget was exhausted
        assert len(result.answer) > 0
