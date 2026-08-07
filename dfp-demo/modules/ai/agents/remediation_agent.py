"""
RemediationAgent — selects and enriches response actions with LLM rationale.

Given the forensics and investigation context from prior agents, the agent:
  1. Looks up static response actions from remediation_rules.py for the
     detected root cause and severity.
  2. Makes a single LLM call to generate one rationale sentence per action.
  3. Determines whether escalation is required (CRITICAL severity or
     recurrence detected by InvestigationAgent).
  4. Combines compliance flags from both category and severity lookups.
  5. Returns a structured AgentResult.

Constructor:
    RemediationAgent(llm_service)  — no DB or Qdrant dependencies.

Context consumed from task.context:
    task.context["forensics_result"]     → ForensicsAgent output dict
    task.context["investigation_result"] → InvestigationAgent output dict

Output shape (stored in agent_findings.result / AgentResult.result):
    {
        "recommended_actions": [
            {"priority": int, "action": str, "rationale": str, "auto_actionable": bool}
        ],
        "escalation_required": bool,
        "compliance_flags":    [str],
        "confidence":          float,
    }
"""

from __future__ import annotations

import logging
from typing import Any

from modules.ai.agents.base_agent import AgentResult, AgentTask, BaseAgent
from modules.ai.agents.prompts.remediation_prompt import SYSTEM_PROMPT, build_user_prompt
from modules.ai.agents.remediation_rules import RemediationAction, get_actions
from modules.ai.llm.llm_service import LLMService

logger = logging.getLogger(__name__)


class RemediationAgent(BaseAgent):
    """Remediation agent: static rule lookup enriched with LLM action rationale."""

    TIMEOUT_SECONDS = 60

    def __init__(self, llm_service: LLMService) -> None:
        self._llm_service = llm_service

    @property
    def agent_type(self) -> str:
        return "remediation"

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _load_rules(
        self,
        root_cause: str,
        severity: str,
    ) -> tuple[list[RemediationAction], list[str]]:
        """Delegate to remediation_rules.get_actions."""
        return get_actions(root_cause, severity)

    def _enrich_with_llm(
        self,
        actions: list[RemediationAction],
        root_cause: str,
        severity: str,
        risk_score: float,
        user_id: str,
        entities: list[str],
        recurrence_detected: bool,
    ) -> tuple[list[RemediationAction], int]:
        """Single LLM call to produce a rationale sentence for every action.

        The LLM is instructed to emit one line per action in the same order.
        Lines are matched back to actions by index; extras are ignored and
        missing lines leave the rationale empty.
        """
        action_texts = [a.action for a in actions]
        user_prompt = build_user_prompt(
            root_cause=root_cause,
            severity=severity,
            risk_score=risk_score,
            actions=action_texts,
            user_id=user_id,
            entities=entities,
            recurrence_detected=recurrence_detected,
        )
        rationale_text, tokens = self._llm_service.chat(SYSTEM_PROMPT, user_prompt)

        # Split into non-empty lines and match by position.
        lines = [ln.strip() for ln in rationale_text.strip().splitlines() if ln.strip()]
        for i, action in enumerate(actions):
            action.rationale = lines[i] if i < len(lines) else ""

        return actions, tokens

    def _compute_confidence(
        self,
        forensics_result: dict[str, Any],
        investigation_result: dict[str, Any],
    ) -> float:
        """Average upstream confidence scores; fall back to 0.6 if neither is available."""
        f_conf = forensics_result.get("confidence")
        i_conf = investigation_result.get("confidence")
        if f_conf is None and i_conf is None:
            return 0.6
        values = [v for v in (f_conf, i_conf) if v is not None]
        return sum(values) / len(values)

    # ------------------------------------------------------------------
    # Main execution
    # ------------------------------------------------------------------

    def _execute(self, task: AgentTask) -> AgentResult:
        anomaly = task.anomaly_data
        forensics_result: dict[str, Any] = task.context.get("forensics_result", {})
        investigation_result: dict[str, Any] = task.context.get("investigation_result", {})

        root_cause: str = str(anomaly.get("root_cause") or "Unknown")
        severity: str = str(anomaly.get("severity") or "LOW")
        risk_score: float = float(anomaly.get("risk_score") or 0.0)
        user_id: str = str(anomaly.get("user_id") or "")
        entities: list[str] = forensics_result.get("entities_involved", [])
        recurrence_detected: bool = bool(investigation_result.get("recurrence_detected", False))

        # 1. Static rule lookup.
        actions, compliance_flags = self._load_rules(root_cause, severity)

        # 2. LLM rationale enrichment (best-effort; failure is non-fatal).
        llm_tokens = 0
        try:
            actions, llm_tokens = self._enrich_with_llm(
                actions=actions,
                root_cause=root_cause,
                severity=severity,
                risk_score=risk_score,
                user_id=user_id,
                entities=entities,
                recurrence_detected=recurrence_detected,
            )
        except Exception:
            logger.exception("[remediation] LLM enrichment failed")

        # 3. Escalation: CRITICAL severity OR recurrence detected.
        escalation_required = severity == "CRITICAL" or recurrence_detected

        # 4. Confidence from upstream agents.
        confidence = self._compute_confidence(forensics_result, investigation_result)

        result: dict[str, Any] = {
            "recommended_actions": [
                {
                    "priority": a.priority,
                    "action": a.action,
                    "rationale": a.rationale,
                    "auto_actionable": a.auto_actionable,
                }
                for a in actions
            ],
            "escalation_required": escalation_required,
            "compliance_flags": compliance_flags,
            "confidence": confidence,
        }

        return AgentResult(
            agent_type="remediation",
            status="complete",
            result=result,
            confidence=confidence,
            llm_tokens_used=llm_tokens,
        )
