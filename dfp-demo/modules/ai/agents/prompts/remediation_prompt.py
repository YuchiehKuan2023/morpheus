"""
Prompt templates for RemediationAgent.

SYSTEM_PROMPT instructs the LLM to act as a security operations analyst.
build_user_prompt() assembles the user-turn message from triage context
and the pre-computed list of candidate remediation actions.
"""

from __future__ import annotations

SYSTEM_PROMPT = """You are a security operations analyst.
For each recommended action, write exactly one sentence of rationale that is specific to the
user, entities, and severity level provided. Be direct and actionable.

Output format rules (strictly enforced):
- Return exactly one line per action, in the same order as the input list.
- Each line must be a single sentence with no leading numbers, bullets, or labels.
- Do not add blank lines, preamble, or any other text outside the per-action sentences."""


def build_user_prompt(
    root_cause: str,
    severity: str,
    risk_score: float,
    actions: list[str],
    user_id: str,
    entities: list[str],
    recurrence_detected: bool,
) -> str:
    """Construct the user-turn prompt from triage data and candidate actions.

    Args:
        root_cause:          Root cause label for the triggering anomaly.
        severity:            Severity string (e.g. "CRITICAL", "HIGH").
        risk_score:          Numeric risk score 0–100.
        actions:             Ordered list of candidate remediation action strings.
        user_id:             The subject user identifier.
        entities:            Entity strings involved (IPs, devices, apps).
        recurrence_detected: True if InvestigationAgent found prior occurrences.

    Returns:
        Formatted prompt string ready to send as the ``user`` turn.
    """
    action_list = "\n".join(f"  {i + 1}. {a}" for i, a in enumerate(actions))
    recurrence_note = " This pattern has recurred — escalation priority is higher." if recurrence_detected else ""
    return (
        f"User: {user_id}\n"
        f"Root cause: {root_cause} | Severity: {severity} | "
        f"Risk score: {risk_score:.1f}/100{recurrence_note}\n"
        f"Connected entities: {', '.join(entities) if entities else 'none'}\n\n"
        f"Recommended actions:\n{action_list}\n\n"
        f"Write a one-sentence rationale for each action, referencing specific details above."
    )
