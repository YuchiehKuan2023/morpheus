"""
Unit tests for the agentic conversational AI modules (Week 25).

Covers:
- ToolSpec and ToolRegistry: registration, schema generation, execution,
  caching, validation, retry, and fallback
- WorkingMemory: thoughts, observations, entity extraction, scratchpad rendering
- GuardRails: iteration limits, tool-call budgets, blocked tools, duplicate detection
- AgentCore._parse_step: THOUGHT/ACTION/ANSWER parsing from raw LLM output
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[2]))

from modules.ai.conversational.guard_rails import AgentConfig, GuardRails
from modules.ai.conversational.memory import WorkingMemory
from modules.ai.conversational.tool_registry import ToolRegistry, ToolSpec

# ═══════════════════════════════════════════════════════════════════════
#  ToolRegistry
# ═══════════════════════════════════════════════════════════════════════


class TestToolRegistry:
    """ToolRegistry registration, schema generation, and execution."""

    @staticmethod
    def _dummy_handler(**kwargs):
        return {"result": "ok", **kwargs}

    @staticmethod
    def _failing_handler(**kwargs):
        raise RuntimeError("boom")

    def _make_spec(self, name: str = "test_tool", **overrides) -> ToolSpec:
        defaults = {
            "name": name,
            "description": "A test tool",
            "parameters": {"type": "object", "properties": {"x": {"type": "integer"}}, "required": ["x"]},
            "handler": self._dummy_handler,
            "estimated_tokens": 100,
        }
        defaults.update(overrides)
        return ToolSpec(**defaults)

    def test_register_and_has(self):
        reg = ToolRegistry()
        spec = self._make_spec()
        reg.register(spec)
        assert reg.has("test_tool")
        assert not reg.has("nonexistent")

    def test_get_returns_spec(self):
        reg = ToolRegistry()
        spec = self._make_spec()
        reg.register(spec)
        assert reg.get("test_tool") is spec

    def test_tool_names(self):
        reg = ToolRegistry()
        reg.register(self._make_spec("alpha"))
        reg.register(self._make_spec("beta"))
        assert reg.tool_names == ["alpha", "beta"]

    def test_execute_success(self):
        reg = ToolRegistry()
        reg.register(self._make_spec())
        result = reg.execute("test_tool", {"x": 42})
        assert result.success is True
        assert result.data == {"result": "ok", "x": 42}
        assert result.tokens_estimate > 0

    def test_execute_unknown_tool(self):
        reg = ToolRegistry()
        result = reg.execute("nonexistent", {})
        assert result.success is False
        assert result.error is not None and "Unknown tool" in result.error

    def test_execute_validation_required_missing(self):
        reg = ToolRegistry()
        reg.register(self._make_spec())
        result = reg.execute("test_tool", {})
        assert result.success is False
        assert result.error is not None and "required" in result.error.lower()

    def test_execute_validation_enum(self):
        reg = ToolRegistry()
        spec = self._make_spec(
            parameters={
                "type": "object",
                "properties": {
                    "severity": {"type": "string", "enum": ["HIGH", "LOW"]},
                },
                "required": [],
            },
        )
        reg.register(spec)
        result = reg.execute("test_tool", {"severity": "INVALID"})
        assert result.success is False
        assert result.error is not None
        assert "enum" in result.error.lower() or "must be one of" in result.error.lower()

    def test_execute_retry_then_succeed(self):
        call_count = 0

        def flaky(**kwargs):
            nonlocal call_count
            call_count += 1
            if call_count < 2:
                raise RuntimeError("transient")
            return {"ok": True}

        reg = ToolRegistry()
        reg.register(self._make_spec(handler=flaky, max_retries=2))
        result = reg.execute("test_tool", {"x": 1})
        assert result.success is True
        assert call_count == 2

    def test_execute_fallback(self):
        reg = ToolRegistry()
        reg.register(self._make_spec("primary", handler=self._failing_handler, fallback="backup", max_retries=0))
        reg.register(self._make_spec("backup"))
        result = reg.execute("primary", {"x": 1})
        assert result.success is True
        assert result.was_fallback is True

    def test_caching(self):
        call_count = 0

        def counting_handler(**kwargs):
            nonlocal call_count
            call_count += 1
            return {"count": call_count}

        reg = ToolRegistry()
        reg.register(self._make_spec(handler=counting_handler, cacheable=True, cache_ttl=60))
        r1 = reg.execute("test_tool", {"x": 1})
        r2 = reg.execute("test_tool", {"x": 1})
        assert r1.data == r2.data
        assert call_count == 1  # second call served from cache

    def test_schemas_text_contains_all_tools(self):
        reg = ToolRegistry()
        reg.register(self._make_spec("alpha"))
        reg.register(self._make_spec("beta"))
        text = reg.get_schemas_text()
        assert "alpha" in text
        assert "beta" in text

    def test_openai_schemas_format(self):
        reg = ToolRegistry()
        reg.register(self._make_spec())
        schemas = reg.get_openai_schemas()
        assert len(schemas) == 1
        assert schemas[0]["type"] == "function"
        assert schemas[0]["function"]["name"] == "test_tool"


# ═══════════════════════════════════════════════════════════════════════
#  WorkingMemory
# ═══════════════════════════════════════════════════════════════════════


class TestWorkingMemory:
    """WorkingMemory scratchpad, entity extraction, and token tracking."""

    def test_add_thought(self):
        mem = WorkingMemory()
        mem.add_thought("I need to find critical anomalies")
        assert len(mem.thoughts) == 1
        assert "critical" in mem.thoughts[0]

    def test_add_observation_tracks_tools(self):
        mem = WorkingMemory()
        mem.add_observation("search_anomalies", {"severity": "HIGH"}, {"total_matching": 5}, tokens=200)
        assert "search_anomalies" in mem.tools_used
        assert mem.tool_call_count == 1
        assert mem.tokens_used == 200

    def test_entity_extraction_users(self):
        mem = WorkingMemory()
        mem.add_observation(
            "get_user_profile",
            {"username": "alice@contoso.com"},
            {"user": {"user_id": "alice@contoso.com", "username": "alice@contoso.com"}},
            tokens=100,
        )
        assert "alice@contoso.com" in mem.entities["users"]

    def test_entity_extraction_anomaly_ids(self):
        mem = WorkingMemory()
        mem.add_observation(
            "search_anomalies",
            {},
            {"anomalies": [{"anomaly_id": "abc-123", "user_id": "bob@contoso.com"}]},
            tokens=100,
        )
        assert "abc-123" in mem.entities["anomaly_ids"]
        assert "bob@contoso.com" in mem.entities["users"]

    def test_entity_extraction_ips(self):
        mem = WorkingMemory()
        mem.add_observation(
            "search_anomalies",
            {},
            {"anomalies": [{"event_ip": "10.0.0.1"}]},
            tokens=50,
        )
        assert "10.0.0.1" in mem.entities["ips"]

    def test_scratchpad_format(self):
        mem = WorkingMemory()
        mem.add_thought("Looking for critical anomalies")
        mem.add_observation("search_anomalies", {"severity": "CRITICAL"}, {"total_matching": 3}, tokens=100)
        pad = mem.scratchpad
        assert "THOUGHT:" in pad
        assert "ACTION: search_anomalies" in pad
        assert "ACTION_INPUT:" in pad
        assert "OBSERVATION:" in pad

    def test_scratchpad_compressed(self):
        mem = WorkingMemory()
        mem.add_observation("tool_a", {}, {"total_matching": 10}, tokens=100, success=True)
        mem.add_observation("tool_b", {}, None, tokens=0, success=False, error="timeout")
        compressed = mem.scratchpad_compressed
        assert "tool_a" in compressed
        assert "FAILED" in compressed

    def test_reset(self):
        mem = WorkingMemory()
        mem.add_thought("test")
        mem.add_observation("tool", {}, {}, tokens=500)
        mem.reset()
        assert len(mem.thoughts) == 0
        assert len(mem.observations) == 0
        assert mem.tokens_used == 0
        assert len(mem.tools_used) == 0

    def test_tokens_remaining(self):
        mem = WorkingMemory(max_observation_tokens=1000)
        mem.add_observation("tool", {}, {}, tokens=600)
        assert mem.tokens_remaining == 400

    def test_duplicate_tool_names_not_repeated(self):
        mem = WorkingMemory()
        mem.add_observation("search_anomalies", {"severity": "HIGH"}, {}, tokens=100)
        mem.add_observation("search_anomalies", {"severity": "LOW"}, {}, tokens=100)
        assert mem.tools_used == ["search_anomalies"]  # not duplicated
        assert mem.tool_call_count == 2


# ═══════════════════════════════════════════════════════════════════════
#  GuardRails
# ═══════════════════════════════════════════════════════════════════════


class TestGuardRails:
    """GuardRails limits, blocked tools, and dedup."""

    def test_blocked_tool(self):
        guard = GuardRails(AgentConfig(blocked_tools=("query_database",)))
        allowed, reason = guard.allow_action("query_database", {})
        assert not allowed
        assert "blocked" in reason.lower()

    def test_tool_call_budget(self):
        guard = GuardRails(AgentConfig(max_tool_calls=2))
        guard.record_call("a", {}, 100)
        guard.record_call("b", {}, 100)
        allowed, reason = guard.allow_action("c", {})
        assert not allowed
        assert "budget" in reason.lower()

    def test_token_budget(self):
        guard = GuardRails(AgentConfig(max_observation_tokens=500))
        guard.record_call("a", {}, 500)
        allowed, reason = guard.allow_action("b", {})
        assert not allowed
        assert "token" in reason.lower()

    def test_duplicate_call_blocked(self):
        guard = GuardRails()
        params = {"severity": "HIGH"}
        guard.record_call("search_anomalies", params, 100)
        allowed, reason = guard.allow_action("search_anomalies", params)
        assert not allowed
        assert "duplicate" in reason.lower()

    def test_same_tool_different_params_allowed(self):
        guard = GuardRails()
        guard.record_call("search_anomalies", {"severity": "HIGH"}, 100)
        allowed, reason = guard.allow_action("search_anomalies", {"severity": "LOW"})
        assert allowed

    def test_iteration_check(self):
        guard = GuardRails(AgentConfig(max_iterations=3))
        assert guard.check_iteration(0)[0] is True
        assert guard.check_iteration(2)[0] is True
        assert guard.check_iteration(3)[0] is False

    def test_reset(self):
        guard = GuardRails(AgentConfig(max_tool_calls=2))
        guard.record_call("a", {}, 100)
        guard.record_call("b", {}, 100)
        guard.reset()
        assert guard.calls_remaining == 2

    def test_calls_remaining(self):
        guard = GuardRails(AgentConfig(max_tool_calls=5))
        guard.record_call("a", {}, 50)
        assert guard.calls_remaining == 4


# ═══════════════════════════════════════════════════════════════════════
#  AgentCore._parse_step
# ═══════════════════════════════════════════════════════════════════════


class TestParseStep:
    """AgentCore._parse_step: extracting THOUGHT/ACTION/ANSWER from free-form LLM text."""

    @staticmethod
    def _parse(raw: str):
        from modules.ai.conversational.agent_core import AgentCore

        return AgentCore._parse_step(raw)

    def test_action_with_thought(self):
        raw = (
            "THOUGHT: I need to search for critical anomalies.\n"
            "ACTION: search_anomalies\n"
            'ACTION_INPUT: {"severity": "CRITICAL", "limit": 5}'
        )
        p = self._parse(raw)
        assert p.type == "action"
        assert p.thought == "I need to search for critical anomalies."
        assert p.action == "search_anomalies"
        assert p.params == {"severity": "CRITICAL", "limit": 5}

    def test_answer_with_thought(self):
        raw = "THOUGHT: I now have all the data.\nANSWER: Here are the top 3 anomalies..."
        p = self._parse(raw)
        assert p.type == "answer"
        assert "all the data" in p.thought
        assert "top 3" in p.answer

    def test_answer_without_thought(self):
        raw = "ANSWER: No anomalies found for this user."
        p = self._parse(raw)
        assert p.type == "answer"
        assert p.thought == ""
        assert "No anomalies" in p.answer

    def test_fallback_to_answer_when_no_markers(self):
        raw = "The data shows that user alice has 5 critical anomalies."
        p = self._parse(raw)
        assert p.type == "answer"  # treated as answer since no markers
        assert "alice" in p.answer

    def test_action_with_empty_input(self):
        raw = "THOUGHT: Let me get the risk summary.\nACTION: get_risk_summary\nACTION_INPUT: {}"
        p = self._parse(raw)
        assert p.type == "action"
        assert p.action == "get_risk_summary"
        assert p.params == {}

    def test_malformed_json_in_action_input(self):
        raw = "THOUGHT: Searching.\nACTION: search_anomalies\nACTION_INPUT: {invalid json}"
        p = self._parse(raw)
        assert p.type == "action"
        assert p.action == "search_anomalies"
        assert p.params == {}  # fallback to empty dict

    def test_answer_takes_priority_over_action(self):
        """If both ACTION and ANSWER are present, ANSWER wins."""
        raw = (
            "THOUGHT: I have enough info.\n"
            "ANSWER: Here is the analysis.\n"
            "ACTION: search_anomalies\n"
            'ACTION_INPUT: {"days": 7}'
        )
        p = self._parse(raw)
        assert p.type == "answer"


# ═══════════════════════════════════════════════════════════════════════
#  Integration: ToolRegistry.get_schemas_text
# ═══════════════════════════════════════════════════════════════════════


class TestSchemasText:
    """Verify schema text generation produces prompt-worthy output."""

    def test_includes_required_annotation(self):
        reg = ToolRegistry()
        reg.register(
            ToolSpec(
                name="test",
                description="Test tool",
                parameters={
                    "type": "object",
                    "properties": {"id": {"type": "string", "description": "The ID"}},
                    "required": ["id"],
                },
                handler=lambda **_: {},
            )
        )
        text = reg.get_schemas_text()
        assert "(required)" in text

    def test_includes_enum_values(self):
        reg = ToolRegistry()
        reg.register(
            ToolSpec(
                name="test",
                description="Test tool",
                parameters={
                    "type": "object",
                    "properties": {
                        "severity": {
                            "type": "string",
                            "enum": ["HIGH", "LOW"],
                            "description": "Severity level",
                        }
                    },
                    "required": [],
                },
                handler=lambda **_: {},
            )
        )
        text = reg.get_schemas_text()
        assert "HIGH" in text
        assert "LOW" in text
