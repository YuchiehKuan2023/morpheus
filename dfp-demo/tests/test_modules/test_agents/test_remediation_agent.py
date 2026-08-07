"""
Unit tests for RemediationRules and RemediationAgent (Step 19.2 + 19.3).

All LLM calls are mocked.  No DB or Qdrant dependencies.

Test classes:
    TestRemediationRules          — pure data rules lookup
    TestRemediationAgentActions   — action counts per root cause
    TestRemediationAgentCompliance — compliance flag propagation
    TestRemediationAgentEscalation — escalation logic
    TestRemediationAgentConfidence — confidence formula
    TestRemediationAgentLLM       — LLM rationale enrichment
"""

from __future__ import annotations

import sys
import uuid
from pathlib import Path
from unittest.mock import MagicMock

import pytest

# Ensure repository root is on sys.path so `modules.*` imports resolve reliably.
_ROOT = Path(__file__).parents[3]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from modules.ai.agents.base_agent import AgentTask  # noqa: E402
from modules.ai.agents.remediation_agent import RemediationAgent  # noqa: E402
from modules.ai.agents.remediation_rules import RULES, get_actions  # noqa: E402

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_task(
    root_cause: str = "Account Takeover",
    severity: str = "HIGH",
    risk_score: float = 75.0,
    user_id: str = "user@example.com",
    forensics_confidence: float | None = None,
    investigation_confidence: float | None = None,
    recurrence_detected: bool = False,
) -> AgentTask:
    context: dict = {}
    if forensics_confidence is not None:
        context["forensics_result"] = {
            "confidence": forensics_confidence,
            "entities_involved": ["10.0.1.5", "device-abc"],
        }
    if investigation_confidence is not None:
        context["investigation_result"] = {
            "confidence": investigation_confidence,
            "recurrence_detected": recurrence_detected,
        }
    elif recurrence_detected:
        context["investigation_result"] = {"recurrence_detected": recurrence_detected}

    return AgentTask(
        investigation_id=str(uuid.uuid4()),
        anomaly_id=str(uuid.uuid4()),
        anomaly_data={
            "user_id": user_id,
            "root_cause": root_cause,
            "severity": severity,
            "risk_score": risk_score,
        },
        context=context,
    )


def _make_agent(llm_lines: list[str] | None = None) -> RemediationAgent:
    llm_service = MagicMock()
    response_text = "\n".join(llm_lines) if llm_lines else "Generic rationale."
    llm_service.chat.return_value = (response_text, 50)
    return RemediationAgent(llm_service=llm_service)


# ---------------------------------------------------------------------------
# TestRemediationRules — pure data-layer tests
# ---------------------------------------------------------------------------


class TestRemediationRules:
    def test_account_takeover_rules(self):
        """Account Takeover returns 4 actions; second is auto-actionable."""
        actions, flags = get_actions("Account Takeover", "HIGH")
        assert len(actions) == 4
        assert actions[0].priority == 1
        assert actions[1].auto_actionable is True  # Revoke OAuth tokens

    def test_unknown_root_cause(self):
        """Unmapped root cause falls back to 'Unknown' ruleset (3 actions)."""
        actions, _ = get_actions("Alien Attack", "LOW")
        assert len(actions) == len(RULES["Unknown"])
        assert actions[0].action == "Escalate to SOC for manual investigation"

    def test_data_exfiltration_compliance(self):
        """Data Exfiltration triggers GDPR Art.33 flag."""
        _, flags = get_actions("Data Exfiltration", "HIGH")
        assert any("GDPR Art.33" in f for f in flags)

    def test_critical_severity_compliance(self):
        """CRITICAL severity triggers ISO 27001 A.16 flag regardless of root cause."""
        _, flags = get_actions("Brute Force", "CRITICAL")
        assert any("ISO 27001 A.16" in f for f in flags)


# ---------------------------------------------------------------------------
# TestRemediationAgentActions
# ---------------------------------------------------------------------------


class TestRemediationAgentActions:
    def test_account_takeover_actions_in_result(self):
        """Result contains exactly 4 actions for Account Takeover."""
        agent = _make_agent(llm_lines=["r1", "r2", "r3", "r4"])
        task = _make_task(root_cause="Account Takeover", severity="HIGH")
        result = agent.run(task)

        assert result.status == "complete"
        actions = result.result["recommended_actions"]
        assert len(actions) == 4
        assert actions[0]["priority"] == 1

    def test_unknown_root_cause_fallback(self):
        """Unmapped root cause falls back to Unknown ruleset (3 actions)."""
        agent = _make_agent(llm_lines=["r1", "r2", "r3"])
        task = _make_task(root_cause="Totally Unknown Threat", severity="MEDIUM")
        result = agent.run(task)

        assert result.status == "complete"
        assert len(result.result["recommended_actions"]) == len(RULES["Unknown"])


# ---------------------------------------------------------------------------
# TestRemediationAgentCompliance
# ---------------------------------------------------------------------------


class TestRemediationAgentCompliance:
    def test_data_exfiltration_compliance(self):
        """GDPR flag surfaces in result for Data Exfiltration root cause."""
        agent = _make_agent()
        task = _make_task(root_cause="Data Exfiltration", severity="HIGH")
        result = agent.run(task)

        flags = result.result["compliance_flags"]
        assert any("GDPR Art.33" in f for f in flags)

    def test_critical_severity_compliance(self):
        """ISO 27001 A.16 flag surfaces in result for CRITICAL severity."""
        agent = _make_agent()
        task = _make_task(root_cause="Brute Force", severity="CRITICAL")
        result = agent.run(task)

        flags = result.result["compliance_flags"]
        assert any("ISO 27001 A.16" in f for f in flags)


# ---------------------------------------------------------------------------
# TestRemediationAgentEscalation
# ---------------------------------------------------------------------------


class TestRemediationAgentEscalation:
    def test_escalation_required_on_critical(self):
        """CRITICAL severity alone triggers escalation."""
        agent = _make_agent()
        task = _make_task(root_cause="Anomalous Access", severity="CRITICAL")
        result = agent.run(task)

        assert result.result["escalation_required"] is True

    def test_escalation_required_on_recurrence(self):
        """recurrence_detected=True triggers escalation even at HIGH severity."""
        agent = _make_agent()
        task = _make_task(severity="HIGH", recurrence_detected=True)
        result = agent.run(task)

        assert result.result["escalation_required"] is True

    def test_no_escalation_medium_no_recurrence(self):
        """MEDIUM severity + no recurrence → escalation_required=False."""
        agent = _make_agent()
        task = _make_task(severity="MEDIUM", recurrence_detected=False)
        result = agent.run(task)

        assert result.result["escalation_required"] is False


# ---------------------------------------------------------------------------
# TestRemediationAgentConfidence
# ---------------------------------------------------------------------------


class TestRemediationAgentConfidence:
    def test_confidence_uses_upstream(self):
        """Confidence = average of forensics (0.8) and investigation (0.6) = 0.7."""
        agent = _make_agent()
        task = _make_task(forensics_confidence=0.8, investigation_confidence=0.6)
        result = agent.run(task)

        assert pytest.approx(result.confidence, abs=1e-6) == 0.7

    def test_confidence_default_no_upstream(self):
        """Without upstream context confidence defaults to 0.6."""
        agent = _make_agent()
        task = _make_task()  # no forensics/investigation context
        result = agent.run(task)

        assert pytest.approx(result.confidence, abs=1e-6) == 0.6


# ---------------------------------------------------------------------------
# TestRemediationAgentLLM
# ---------------------------------------------------------------------------


class TestRemediationAgentLLM:
    def test_llm_rationale_appended(self):
        """LLM-returned lines are stored as action.rationale in order."""
        rationale_lines = [
            "Disable the account to stop ongoing access.",
            "Revoke tokens to invalidate active sessions.",
            "Force MFA to prevent re-entry.",
            "Notify manager to initiate HR review.",
        ]
        agent = _make_agent(llm_lines=rationale_lines)
        task = _make_task(root_cause="Account Takeover", severity="HIGH")
        result = agent.run(task)

        actions = result.result["recommended_actions"]
        for i, line in enumerate(rationale_lines):
            assert actions[i]["rationale"] == line
