"""
Unit tests for modules/ai/agents/base_agent.py

Covers:
- AgentTask and AgentResult dataclass construction and defaults
- BaseAgent.run() delegates to _execute() and sets latency_ms
- BaseAgent.run() catches exceptions → returns AgentResult(status='failed')
- ABC enforcement: cannot instantiate BaseAgent directly

Author: Tomasz Zabek <tzabek@deloitte.co.uk>
Date: 2026-03-23
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parents[3]))

from modules.ai.agents.base_agent import AgentResult, AgentTask, BaseAgent

# ---------------------------------------------------------------------------
# Concrete test double
# ---------------------------------------------------------------------------


class _GoodAgent(BaseAgent):
    @property
    def agent_type(self) -> str:
        return "forensics"

    def __init__(self, result: AgentResult) -> None:
        self._result = result

    def _execute(self, task: AgentTask) -> AgentResult:
        return self._result


class _SlowAgent(BaseAgent):
    """Sleeps briefly so latency_ms is measurably > 0."""

    @property
    def agent_type(self) -> str:
        return "investigation"

    def _execute(self, task: AgentTask) -> AgentResult:
        time.sleep(0.02)
        return AgentResult(agent_type="investigation", status="complete", result={})


class _BrokenAgent(BaseAgent):
    @property
    def agent_type(self) -> str:
        return "remediation"

    def _execute(self, task: AgentTask) -> AgentResult:
        raise RuntimeError("downstream LLM unavailable")


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def sample_task() -> AgentTask:
    return AgentTask(
        investigation_id="inv-001",
        anomaly_id="ano-001",
        anomaly_data={"anomaly_score": 4.2, "user_id": "alice@example.com"},
    )


@pytest.fixture
def success_result() -> AgentResult:
    return AgentResult(
        agent_type="forensics",
        status="complete",
        result={"summary": "lateral movement detected"},
        confidence=0.88,
    )


# ---------------------------------------------------------------------------
# Dataclass tests
# ---------------------------------------------------------------------------


class TestAgentTaskDefaults:
    def test_required_fields(self):
        task = AgentTask(
            investigation_id="i1",
            anomaly_id="a1",
            anomaly_data={"score": 3.5},
        )
        assert task.investigation_id == "i1"
        assert task.anomaly_id == "a1"
        assert task.anomaly_data == {"score": 3.5}

    def test_context_defaults_to_empty_dict(self):
        task = AgentTask(
            investigation_id="i1",
            anomaly_id="a1",
            anomaly_data={},
        )
        assert task.context == {}

    def test_context_instances_are_independent(self):
        t1 = AgentTask(investigation_id="i1", anomaly_id="a1", anomaly_data={})
        t2 = AgentTask(investigation_id="i2", anomaly_id="a2", anomaly_data={})
        t1.context["key"] = "val"
        assert "key" not in t2.context


class TestAgentResultDefaults:
    def test_required_fields(self):
        r = AgentResult(agent_type="forensics", status="complete", result={"x": 1})
        assert r.agent_type == "forensics"
        assert r.status == "complete"
        assert r.result == {"x": 1}

    def test_optional_defaults(self):
        r = AgentResult(agent_type="forensics", status="complete", result={})
        assert r.confidence == 0.0
        assert r.latency_ms == 0
        assert r.llm_tokens_used == 0
        assert r.error is None

    def test_error_field(self):
        r = AgentResult(
            agent_type="remediation",
            status="failed",
            result={},
            error="timeout after 30s",
        )
        assert r.error == "timeout after 30s"


# ---------------------------------------------------------------------------
# ABC enforcement
# ---------------------------------------------------------------------------


class TestBaseAgentABC:
    def test_cannot_instantiate_abstract_class(self):
        with pytest.raises(TypeError):
            BaseAgent()  # type: ignore[abstract]

    def test_missing_execute_raises(self):
        class _Incomplete(BaseAgent):
            @property
            def agent_type(self) -> str:
                return "forensics"

            # no _execute

        with pytest.raises(TypeError):
            _Incomplete()  # type: ignore[abstract]


# ---------------------------------------------------------------------------
# run() delegation
# ---------------------------------------------------------------------------


class TestBaseAgentRun:
    def test_run_returns_execute_result(self, sample_task, success_result):
        agent = _GoodAgent(success_result)
        returned = agent.run(sample_task)
        assert returned is success_result

    def test_run_sets_latency_ms(self, sample_task):
        agent = _SlowAgent()
        result = agent.run(sample_task)
        assert result.latency_ms >= 10  # ≥ 10 ms (we slept 20 ms)

    def test_run_preserves_agent_type_from_execute(self, sample_task, success_result):
        agent = _GoodAgent(success_result)
        result = agent.run(sample_task)
        assert result.agent_type == "forensics"

    def test_run_passes_task_to_execute(self, sample_task):
        received: list[AgentTask] = []

        class _Capturing(BaseAgent):
            @property
            def agent_type(self) -> str:
                return "forensics"

            def _execute(self, task):
                received.append(task)
                return AgentResult(agent_type="forensics", status="complete", result={})

        _Capturing().run(sample_task)
        assert received[0] is sample_task


# ---------------------------------------------------------------------------
# Exception handling
# ---------------------------------------------------------------------------


class TestBaseAgentExceptionHandling:
    def test_exception_returns_failed_result(self, sample_task):
        result = _BrokenAgent().run(sample_task)
        assert result.status == "failed"

    def test_exception_sets_error_message(self, sample_task):
        result = _BrokenAgent().run(sample_task)
        assert "downstream LLM unavailable" in (result.error or "")

    def test_exception_result_has_agent_type(self, sample_task):
        result = _BrokenAgent().run(sample_task)
        assert result.agent_type == "remediation"

    def test_exception_result_latency_ms_set(self, sample_task):
        result = _BrokenAgent().run(sample_task)
        assert isinstance(result.latency_ms, int)
        assert result.latency_ms >= 0

    def test_exception_result_is_empty_dict(self, sample_task):
        result = _BrokenAgent().run(sample_task)
        assert result.result == {}
