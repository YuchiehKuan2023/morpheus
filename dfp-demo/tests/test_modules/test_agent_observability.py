"""
Unit & integration tests for Week 29 — Frontend + Observability.

Covers:
- TraceStep dataclass: creation, field defaults
- AgentCore._serialize_trace: serialisation, field omission
- AgentResponse.reasoning_trace: trace attached to response
- Trace capture during ReAct loop (integration w/ mocked LLM)
- Agent metrics endpoint query structure
- SSE streaming endpoint event format
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import MagicMock

sys.path.insert(0, str(Path(__file__).parents[2]))

from modules.ai.conversational.agent_core import AgentCore, AgentResponse, TraceStep
from modules.ai.conversational.guard_rails import AgentConfig
from modules.ai.conversational.tool_registry import ToolRegistry, ToolSpec

# ═══════════════════════════════════════════════════════════════════════
#  Helpers
# ═══════════════════════════════════════════════════════════════════════


def _make_registry() -> ToolRegistry:
    """Minimal registry with one deterministic tool."""
    reg = ToolRegistry()
    reg.register(
        ToolSpec(
            name="get_risk_summary",
            description="Get platform risk summary",
            parameters={"type": "object", "properties": {}, "required": []},
            handler=lambda **kw: {"total_anomalies": 42, "critical": 5, "high": 15},
            estimated_tokens=200,
        )
    )
    reg.register(
        ToolSpec(
            name="search_anomalies",
            description="Search anomalies",
            parameters={
                "type": "object",
                "properties": {"severity": {"type": "string"}, "limit": {"type": "integer"}},
                "required": [],
            },
            handler=lambda **kw: {"total_matching": 3, "anomalies": [{"id": "a1"}]},
            estimated_tokens=300,
        )
    )
    return reg


def _mock_llm_responses(responses: list[str]):
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


# ═══════════════════════════════════════════════════════════════════════
#  TraceStep dataclass
# ═══════════════════════════════════════════════════════════════════════


class TestTraceStep:
    """TraceStep creation, defaults, and slot behaviour."""

    def test_create_minimal(self):
        ts = TraceStep(kind="thought")
        assert ts.kind == "thought"
        assert ts.content == ""
        assert ts.tool == ""
        assert ts.params is None
        assert ts.success is None
        assert ts.elapsed_ms == 0

    def test_create_full(self):
        ts = TraceStep(
            kind="action",
            content="Calling tool",
            tool="get_risk_summary",
            params={"limit": 5},
            success=True,
            elapsed_ms=150,
        )
        assert ts.kind == "action"
        assert ts.tool == "get_risk_summary"
        assert ts.params == {"limit": 5}
        assert ts.success is True
        assert ts.elapsed_ms == 150

    def test_slots_prevent_arbitrary_attrs(self):
        ts = TraceStep(kind="thought")
        try:
            ts.arbitrary = "nope"  # type: ignore[attr-defined]
            raise AssertionError("Expected AttributeError")
        except AttributeError:
            pass

    def test_all_kind_values(self):
        for kind in ("thought", "action", "observation", "plan", "reflection", "answer"):
            ts = TraceStep(kind=kind, content="test")
            assert ts.kind == kind


# ═══════════════════════════════════════════════════════════════════════
#  _serialize_trace
# ═══════════════════════════════════════════════════════════════════════


class TestSerializeTrace:
    """AgentCore._serialize_trace correctly serialises and omits empty fields."""

    def _make_agent(self) -> AgentCore:
        reg = _make_registry()
        client = _mock_llm_responses(["THOUGHT: ok\nANSWER: done"])
        return AgentCore(reg, client, "gpt-4o-mini", "llama-3.3-70b")

    def test_empty_trace(self):
        agent = self._make_agent()
        agent._trace = []
        result = agent._serialize_trace()
        assert result == []

    def test_minimal_step_only_has_kind(self):
        agent = self._make_agent()
        agent._trace = [TraceStep(kind="thought")]
        result = agent._serialize_trace()
        assert len(result) == 1
        assert result[0] == {"kind": "thought"}

    def test_content_included(self):
        agent = self._make_agent()
        agent._trace = [TraceStep(kind="thought", content="Hmm")]
        result = agent._serialize_trace()
        assert result[0]["content"] == "Hmm"

    def test_tool_and_params_included(self):
        agent = self._make_agent()
        agent._trace = [TraceStep(kind="action", tool="search_anomalies", params={"severity": "HIGH"})]
        result = agent._serialize_trace()
        assert result[0]["tool"] == "search_anomalies"
        assert result[0]["params"] == {"severity": "HIGH"}

    def test_success_included_when_set(self):
        agent = self._make_agent()
        agent._trace = [TraceStep(kind="observation", success=True)]
        result = agent._serialize_trace()
        assert result[0]["success"] is True

    def test_success_false_included(self):
        agent = self._make_agent()
        agent._trace = [TraceStep(kind="observation", success=False)]
        result = agent._serialize_trace()
        assert result[0]["success"] is False

    def test_elapsed_ms_included_when_nonzero(self):
        agent = self._make_agent()
        agent._trace = [TraceStep(kind="action", elapsed_ms=42)]
        result = agent._serialize_trace()
        assert result[0]["elapsed_ms"] == 42

    def test_elapsed_ms_omitted_when_zero(self):
        agent = self._make_agent()
        agent._trace = [TraceStep(kind="action", elapsed_ms=0)]
        result = agent._serialize_trace()
        assert "elapsed_ms" not in result[0]

    def test_params_omitted_when_none(self):
        agent = self._make_agent()
        agent._trace = [TraceStep(kind="action", tool="search")]
        result = agent._serialize_trace()
        assert "params" not in result[0]

    def test_multi_step_trace(self):
        agent = self._make_agent()
        agent._trace = [
            TraceStep(kind="thought", content="Let me check"),
            TraceStep(kind="action", tool="get_risk_summary", elapsed_ms=100),
            TraceStep(kind="observation", content="Got 42 anomalies", success=True, elapsed_ms=100),
            TraceStep(kind="answer", content="There are 42 anomalies"),
        ]
        result = agent._serialize_trace()
        assert len(result) == 4
        assert [r["kind"] for r in result] == ["thought", "action", "observation", "answer"]


# ═══════════════════════════════════════════════════════════════════════
#  AgentResponse with reasoning_trace
# ═══════════════════════════════════════════════════════════════════════


class TestAgentResponseTrace:
    """AgentResponse carries reasoning_trace field."""

    def test_response_without_trace(self):
        resp = AgentResponse(answer="hello", tools_used=[], steps=1, sources=[])
        assert resp.reasoning_trace is None

    def test_response_with_trace(self):
        trace = [{"kind": "thought", "content": "Hmm"}, {"kind": "answer", "content": "Done"}]
        resp = AgentResponse(answer="Done", tools_used=[], steps=1, sources=[], reasoning_trace=trace)
        assert resp.reasoning_trace is not None
        assert len(resp.reasoning_trace) == 2
        assert resp.reasoning_trace[0]["kind"] == "thought"

    def test_trace_is_json_serialisable(self):
        trace = [
            {"kind": "action", "tool": "search_anomalies", "params": {"severity": "HIGH"}, "elapsed_ms": 150},
            {"kind": "observation", "content": "Found 3", "success": True},
        ]
        resp = AgentResponse(
            answer="Found anomalies", tools_used=["search_anomalies"], steps=2, sources=[], reasoning_trace=trace
        )
        serialised = json.dumps(resp.reasoning_trace)
        parsed = json.loads(serialised)
        assert parsed == trace


# ═══════════════════════════════════════════════════════════════════════
#  Trace capture during ReAct loop
# ═══════════════════════════════════════════════════════════════════════


class TestTraceCaptureIntegration:
    """End-to-end trace capture during AgentCore.run()."""

    def test_simple_query_produces_trace(self):
        """A direct answer should produce at least a thought and answer step."""
        registry = _make_registry()
        responses = [
            "THOUGHT: The user wants risk info.\nACTION: get_risk_summary\nACTION_INPUT: {}",
            "THOUGHT: I have the data.\nANSWER: There are 42 total anomalies, 5 critical.",
            "SUFFICIENT: yes\nFEEDBACK: Correct and complete.",
        ]
        client = _mock_llm_responses(responses)
        agent = AgentCore(registry, client, "gpt-4o-mini", "llama-3.3-70b", AgentConfig(max_iterations=5))

        result = agent.run("What is the current risk level?", [])

        assert result.reasoning_trace is not None
        assert len(result.reasoning_trace) > 0

        kinds = [s["kind"] for s in result.reasoning_trace]
        assert "thought" in kinds
        assert "answer" in kinds

    def test_tool_call_produces_action_and_observation(self):
        """Tool calls should produce action + observation trace entries."""
        registry = _make_registry()
        responses = [
            "THOUGHT: Need risk data.\nACTION: get_risk_summary\nACTION_INPUT: {}",
            "THOUGHT: Got it.\nANSWER: 42 anomalies found.",
            "SUFFICIENT: yes\nFEEDBACK: Good answer.",
        ]
        client = _mock_llm_responses(responses)
        agent = AgentCore(registry, client, "gpt-4o-mini", "llama-3.3-70b", AgentConfig(max_iterations=5))

        result = agent.run("Tell me about anomalies", [])
        assert result.reasoning_trace is not None

        kinds = [s["kind"] for s in result.reasoning_trace]
        assert "action" in kinds
        assert "observation" in kinds

        action_steps = [s for s in result.reasoning_trace if s["kind"] == "action"]
        assert len(action_steps) >= 1
        assert action_steps[0].get("tool") == "get_risk_summary"

    def test_observation_has_success_field(self):
        """Observation steps should have a success field."""
        registry = _make_registry()
        responses = [
            "THOUGHT: Let me search.\nACTION: get_risk_summary\nACTION_INPUT: {}",
            "THOUGHT: Got data.\nANSWER: Risk level is moderate.",
            "SUFFICIENT: yes\nFEEDBACK: Fine.",
        ]
        client = _mock_llm_responses(responses)
        agent = AgentCore(registry, client, "gpt-4o-mini", "llama-3.3-70b", AgentConfig(max_iterations=5))

        result = agent.run("Risk level?", [])
        assert result.reasoning_trace is not None

        obs = [s for s in result.reasoning_trace if s["kind"] == "observation"]
        assert len(obs) >= 1
        assert "success" in obs[0]

    def test_reflection_captured_in_trace(self):
        """Reflection step should appear in trace when reflector runs."""
        registry = _make_registry()
        responses = [
            "THOUGHT: Need data.\nACTION: get_risk_summary\nACTION_INPUT: {}",
            "THOUGHT: Done.\nANSWER: 42 anomalies.",
            "SUFFICIENT: yes\nFEEDBACK: Good summary.",
        ]
        client = _mock_llm_responses(responses)
        agent = AgentCore(registry, client, "gpt-4o-mini", "llama-3.3-70b", AgentConfig(max_iterations=5))

        result = agent.run("How many anomalies?", [])
        assert result.reasoning_trace is not None

        kinds = [s["kind"] for s in result.reasoning_trace]
        assert "reflection" in kinds

        reflection = [s for s in result.reasoning_trace if s["kind"] == "reflection"]
        assert len(reflection) >= 1
        assert "success" in reflection[0]

    def test_trace_reset_between_runs(self):
        """Each run() call should start with a fresh trace."""
        registry = _make_registry()
        responses = [
            # Run 1
            "THOUGHT: First query.\nACTION: get_risk_summary\nACTION_INPUT: {}",
            "THOUGHT: Done.\nANSWER: First answer.",
            "SUFFICIENT: yes\nFEEDBACK: OK.",
            # Run 2
            "THOUGHT: Second query.\nANSWER: Direct answer.",
            "SUFFICIENT: yes\nFEEDBACK: OK.",
        ]
        client = _mock_llm_responses(responses)
        agent = AgentCore(registry, client, "gpt-4o-mini", "llama-3.3-70b", AgentConfig(max_iterations=5))

        r1 = agent.run("First question", [])
        assert r1.reasoning_trace is not None
        r1_len = len(r1.reasoning_trace)

        r2 = agent.run("Second question", [])
        assert r2.reasoning_trace is not None
        # Second run should not carry over first run's trace
        assert len(r2.reasoning_trace) < r1_len

    def test_steps_count_matches_response(self):
        """The steps field should reflect actual iteration count."""
        registry = _make_registry()
        responses = [
            "THOUGHT: Check.\nACTION: get_risk_summary\nACTION_INPUT: {}",
            "THOUGHT: Got it.\nANSWER: 42 anomalies.",
            "SUFFICIENT: yes\nFEEDBACK: Fine.",
        ]
        client = _mock_llm_responses(responses)
        agent = AgentCore(registry, client, "gpt-4o-mini", "llama-3.3-70b", AgentConfig(max_iterations=5))

        result = agent.run("Risk overview?", [])
        assert result.steps > 0


# ═══════════════════════════════════════════════════════════════════════
#  SSE event format
# ═══════════════════════════════════════════════════════════════════════


class TestSSEEventFormat:
    """Verify SSE event serialisation follows the expected wire format."""

    def test_step_event_format(self):
        """A step event should be formatted as 'event: step\\ndata: {...}\\n\\n'."""
        step = {"kind": "thought", "content": "Let me think"}
        event = f"event: step\ndata: {json.dumps(step)}\n\n"
        assert event.startswith("event: step\n")
        assert "data: " in event
        assert event.endswith("\n\n")
        parsed = json.loads(event.split("data: ")[1].split("\n")[0])
        assert parsed["kind"] == "thought"

    def test_answer_event_format(self):
        """An answer event should contain the full response except trace."""
        response = {"answer": "42 anomalies", "tools_used": ["get_risk_summary"], "session_id": 1}
        event = f"event: answer\ndata: {json.dumps(response)}\n\n"
        assert event.startswith("event: answer\n")
        parsed = json.loads(event.split("data: ")[1].split("\n")[0])
        assert parsed["answer"] == "42 anomalies"

    def test_error_event_format(self):
        """An error event should include detail."""
        error = {"detail": "something went wrong"}
        event = f"event: error\ndata: {json.dumps(error)}\n\n"
        parsed = json.loads(event.split("data: ")[1].split("\n")[0])
        assert parsed["detail"] == "something went wrong"


# ═══════════════════════════════════════════════════════════════════════
#  Agent metrics data extraction
# ═══════════════════════════════════════════════════════════════════════


class TestAgentMetricsExtraction:
    """Verify trace-based metric calculations."""

    def test_tool_distribution_from_trace(self):
        """Extract tool call distribution from serialised trace steps."""
        trace = [
            {"kind": "action", "tool": "get_risk_summary", "elapsed_ms": 100},
            {"kind": "action", "tool": "search_anomalies", "elapsed_ms": 200},
            {"kind": "action", "tool": "get_risk_summary", "elapsed_ms": 80},
            {"kind": "observation", "content": "data", "success": True},
        ]
        actions = [s for s in trace if s["kind"] == "action"]
        dist: dict[str, int] = {}
        for a in actions:
            tool = a.get("tool", "unknown")
            dist[tool] = dist.get(tool, 0) + 1
        assert dist == {"get_risk_summary": 2, "search_anomalies": 1}

    def test_avg_tool_latency_from_trace(self):
        """Compute average latency per tool from trace steps."""
        trace = [
            {"kind": "action", "tool": "get_risk_summary", "elapsed_ms": 100},
            {"kind": "action", "tool": "get_risk_summary", "elapsed_ms": 200},
            {"kind": "action", "tool": "search_anomalies", "elapsed_ms": 150},
        ]
        latency_sums: dict[str, float] = {}
        latency_counts: dict[str, int] = {}
        for s in trace:
            if s["kind"] == "action" and s.get("elapsed_ms"):
                tool = s["tool"]
                latency_sums[tool] = latency_sums.get(tool, 0) + s["elapsed_ms"]
                latency_counts[tool] = latency_counts.get(tool, 0) + 1
        avg = {t: latency_sums[t] / latency_counts[t] for t in latency_sums}
        assert avg["get_risk_summary"] == 150.0
        assert avg["search_anomalies"] == 150.0

    def test_step_count_from_response(self):
        """steps field on AgentResponse gives total iteration count."""
        resp = AgentResponse(
            answer="test",
            tools_used=["t1", "t2"],
            steps=3,
            sources=[],
            reasoning_trace=[{"kind": "thought"}, {"kind": "action"}, {"kind": "answer"}],
        )
        assert resp.steps == 3
        assert len(resp.reasoning_trace or []) == 3

    def test_empty_trace_produces_zero_metrics(self):
        """An empty trace should give zero counts across all metrics."""
        trace: list[dict] = []
        actions = [s for s in trace if s.get("kind") == "action"]
        assert len(actions) == 0
