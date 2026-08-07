"""
Unit tests for AgentOrchestrator (Step 20.6).

All agent.run() calls, FindingsService methods, and DB helpers are mocked.
No Kafka, PostgreSQL, Neo4j, Qdrant, or LLM dependencies.

Test cases cover:
    TestDecideAgents             — invocation decision table
    TestRunInvestigation         — full lifecycle (happy path + failure paths)
"""

from __future__ import annotations

import sys
import uuid
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

# Ensure repository root is on sys.path so `modules.*` imports resolve reliably.
_ROOT = Path(__file__).parents[3]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from modules.ai.agents.agent_orchestrator import AgentOrchestrator  # noqa: E402
from modules.ai.agents.base_agent import AgentResult  # noqa: E402

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_DB_URL = "postgresql://user:pass@localhost:5432/dfp_ai"


def _make_orchestrator() -> Any:
    """Return an AgentOrchestrator with all heavy dependencies mocked out."""
    with (
        patch("modules.ai.agents.agent_orchestrator.FindingsService"),
        patch("modules.ai.agents.agent_orchestrator.ForensicsAgent"),
        patch("modules.ai.agents.agent_orchestrator.InvestigationAgent"),
        patch("modules.ai.agents.agent_orchestrator.RemediationAgent"),
        patch("modules.ai.agents.agent_orchestrator.psycopg2.connect"),
    ):
        orch = AgentOrchestrator(
            db_url=_DB_URL,
            neo4j_driver=MagicMock(),
            qdrant_client=MagicMock(),
            llm_service=MagicMock(),
        )
    # Re-assign as explicit MagicMock instances so tests can configure
    # return values and assert call counts against known fresh mocks.
    orch.findings_service = MagicMock()
    orch.forensics_agent = MagicMock()
    orch.investigation_agent = MagicMock()
    orch.remediation_agent = MagicMock()
    return orch


def _ok_result(agent_type: str, confidence: float = 0.8) -> AgentResult:
    return AgentResult(
        agent_type=agent_type,
        status="complete",
        result={"confidence": confidence},
        confidence=confidence,
    )


def _fail_result(agent_type: str) -> AgentResult:
    return AgentResult(
        agent_type=agent_type,
        status="failed",
        result={},
        confidence=0.0,
        error="boom",
    )


def _anomaly_data() -> dict:
    return {
        "anomaly_id": str(uuid.uuid4()),
        "user_id": "test@example.com",
        "severity": "HIGH",
        "risk_score": 80.0,
        "root_cause": "Account Takeover",
    }


# ---------------------------------------------------------------------------
# TestDecideAgents — invocation decision table
# ---------------------------------------------------------------------------


class TestDecideAgents:
    def setup_method(self):
        self.orch = _make_orchestrator()

    def test_invocation_critical(self):
        agents = self.orch._decide_agents("CRITICAL", 0.0)
        assert agents == ["forensics", "investigation", "remediation"]

    def test_invocation_high(self):
        agents = self.orch._decide_agents("HIGH", 0.0)
        assert agents == ["forensics", "investigation", "remediation"]

    def test_invocation_medium_high_risk(self):
        agents = self.orch._decide_agents("MEDIUM", 70.0)
        assert agents == ["forensics", "investigation", "remediation"]

    def test_invocation_medium_risk_exactly_60(self):
        agents = self.orch._decide_agents("MEDIUM", 60.0)
        assert agents == ["forensics", "investigation", "remediation"]

    def test_invocation_medium_low_risk(self):
        agents = self.orch._decide_agents("MEDIUM", 40.0)
        assert agents == ["forensics", "investigation", "remediation"]

    def test_invocation_low(self):
        agents = self.orch._decide_agents("LOW", 99.0)
        assert agents == ["forensics", "investigation", "remediation"]

    def test_severity_case_insensitive(self):
        assert self.orch._decide_agents("critical", 0.0) == ["forensics", "investigation", "remediation"]
        assert self.orch._decide_agents("high", 0.0) == ["forensics", "investigation", "remediation"]


# ---------------------------------------------------------------------------
# TestRunInvestigation — full lifecycle
# ---------------------------------------------------------------------------


class TestRunInvestigation:
    def _run(
        self,
        severity: str = "HIGH",
        risk_score: float = 80.0,
        forensics_ok: bool = True,
        investigation_ok: bool = True,
        remediation_ok: bool = True,
    ) -> Any:
        orch = _make_orchestrator()

        anomaly_id = str(uuid.uuid4())
        investigation_id = str(uuid.uuid4())

        # FindingsService stubs
        orch.findings_service.create_investigation.return_value = investigation_id
        orch.findings_service.record_finding = MagicMock()
        orch.findings_service.complete_investigation = MagicMock()
        orch.findings_service.fail_investigation = MagicMock()

        # _fetch_anomaly stub
        orch._fetch_anomaly = MagicMock(return_value=_anomaly_data())

        # Agent run() stubs
        orch.forensics_agent.run.return_value = _ok_result("forensics") if forensics_ok else _fail_result("forensics")
        orch.investigation_agent.run.return_value = (
            _ok_result("investigation") if investigation_ok else _fail_result("investigation")
        )
        orch.remediation_agent.run.return_value = (
            _ok_result("remediation") if remediation_ok else _fail_result("remediation")
        )

        msg = {"anomaly_id": anomaly_id, "severity": severity, "risk_score": risk_score}
        orch._run_investigation(msg)
        return orch

    # --- happy paths ----------------------------------------------------------

    def test_complete_investigation_written(self):
        orch = self._run(severity="HIGH")
        orch.findings_service.complete_investigation.assert_called_once()
        orch.findings_service.fail_investigation.assert_not_called()

    def test_all_three_agents_invoked_for_critical(self):
        orch = self._run(severity="CRITICAL")
        orch.forensics_agent.run.assert_called_once()
        orch.investigation_agent.run.assert_called_once()
        orch.remediation_agent.run.assert_called_once()

    def test_all_three_agents_invoked_for_high(self):
        orch = self._run(severity="HIGH")
        orch.forensics_agent.run.assert_called_once()
        orch.investigation_agent.run.assert_called_once()
        orch.remediation_agent.run.assert_called_once()

    def test_medium_high_risk_all_agents(self):
        orch = self._run(severity="MEDIUM", risk_score=70.0)
        orch.forensics_agent.run.assert_called_once()
        orch.investigation_agent.run.assert_called_once()
        orch.remediation_agent.run.assert_called_once()

    # --- remediation receives context -----------------------------------------

    def test_remediation_receives_context(self):
        orch = _make_orchestrator()
        investigation_id = str(uuid.uuid4())

        orch.findings_service.create_investigation.return_value = investigation_id
        orch.findings_service.record_finding = MagicMock()
        orch.findings_service.complete_investigation = MagicMock()
        orch.findings_service.fail_investigation = MagicMock()
        orch._fetch_anomaly = MagicMock(return_value=_anomaly_data())

        forensics_payload = {"narrative": "attack chain found", "confidence": 0.9}
        investigation_payload = {"recurrence_detected": True, "confidence": 0.7}

        orch.forensics_agent.run.return_value = AgentResult(
            agent_type="forensics",
            status="complete",
            result=forensics_payload,
            confidence=0.9,
        )
        orch.investigation_agent.run.return_value = AgentResult(
            agent_type="investigation",
            status="complete",
            result=investigation_payload,
            confidence=0.7,
        )
        orch.remediation_agent.run.return_value = _ok_result("remediation")

        msg = {"anomaly_id": str(uuid.uuid4()), "severity": "HIGH", "risk_score": 80.0}
        orch._run_investigation(msg)

        remediation_call_args = orch.remediation_agent.run.call_args[0][0]
        assert remediation_call_args.context["forensics_result"] == forensics_payload
        assert remediation_call_args.context["investigation_result"] == investigation_payload

    # --- partial failure paths -------------------------------------------------

    def test_forensics_failure_continues(self):
        """Forensics failure must not abort investigation or remediation,
        but the investigation is marked as failed (any agent failure → fail)."""
        orch = self._run(severity="HIGH", forensics_ok=False)
        orch.investigation_agent.run.assert_called_once()
        orch.remediation_agent.run.assert_called_once()
        orch.findings_service.fail_investigation.assert_called_once()
        orch.findings_service.complete_investigation.assert_not_called()

    def test_fail_investigation_on_all_fail(self):
        """All agents failed → fail_investigation called, not complete."""
        orch = self._run(severity="HIGH", forensics_ok=False, investigation_ok=False, remediation_ok=False)
        orch.findings_service.fail_investigation.assert_called_once()
        orch.findings_service.complete_investigation.assert_not_called()

    # --- skip conditions -------------------------------------------------------

    def test_low_severity_still_investigates(self):
        """All anomalies get full agent pipeline regardless of severity."""
        orch = _make_orchestrator()
        orch._fetch_anomaly = MagicMock(return_value=_anomaly_data())
        orch.findings_service.create_investigation.return_value = str(uuid.uuid4())
        orch.findings_service.record_finding = MagicMock()
        orch.findings_service.complete_investigation = MagicMock()
        orch.findings_service.fail_investigation = MagicMock()
        orch.forensics_agent.run.return_value = _ok_result("forensics")
        orch.investigation_agent.run.return_value = _ok_result("investigation")
        orch.remediation_agent.run.return_value = _ok_result("remediation")
        msg = {"anomaly_id": str(uuid.uuid4()), "severity": "LOW", "risk_score": 90.0}
        orch._run_investigation(msg)
        orch.findings_service.create_investigation.assert_called_once()
        orch.forensics_agent.run.assert_called_once()
        orch.investigation_agent.run.assert_called_once()
        orch.remediation_agent.run.assert_called_once()

    def test_missing_anomaly_id_skipped(self):
        orch = _make_orchestrator()
        orch._run_investigation({})
        orch.findings_service.create_investigation.assert_not_called()

    def test_none_anomaly_id_skipped(self):
        """anomaly_id=None must not escape the guard via str(None)='None'."""
        orch = _make_orchestrator()
        orch._run_investigation({"anomaly_id": None, "severity": "HIGH", "risk_score": 80.0})
        orch.findings_service.create_investigation.assert_not_called()

    def test_none_risk_score_defaults_to_zero(self):
        """risk_score=None must not raise TypeError; defaults to 0.0 and investigation proceeds."""
        orch = self._run(severity="MEDIUM", risk_score=0.0)
        orch.findings_service.create_investigation.assert_called_once()
        orch.forensics_agent.run.assert_called_once()

    def test_invalid_risk_score_string_defaults_to_zero(self):
        """Non-numeric risk_score must not raise ValueError; defaults to 0.0 and investigation proceeds."""
        orch = _make_orchestrator()
        orch._fetch_anomaly = MagicMock(return_value=_anomaly_data())
        orch.findings_service.create_investigation.return_value = str(uuid.uuid4())
        orch.forensics_agent.run.return_value = _ok_result("forensics")
        orch.investigation_agent.run.return_value = _ok_result("investigation")
        orch.remediation_agent.run.return_value = _ok_result("remediation")
        orch._run_investigation({"anomaly_id": str(uuid.uuid4()), "severity": "MEDIUM", "risk_score": "not-a-number"})
        orch.findings_service.create_investigation.assert_called_once()

    def test_anomaly_not_in_db_skipped(self):
        orch = _make_orchestrator()
        orch._fetch_anomaly = MagicMock(return_value=None)
        msg = {"anomaly_id": str(uuid.uuid4()), "severity": "HIGH", "risk_score": 80.0}
        orch._run_investigation(msg)
        orch.findings_service.create_investigation.assert_not_called()

    def test_three_findings_recorded_for_high(self):
        """record_finding called exactly once per agent (3 for HIGH)."""
        orch = self._run(severity="HIGH")
        assert orch.findings_service.record_finding.call_count == 3
