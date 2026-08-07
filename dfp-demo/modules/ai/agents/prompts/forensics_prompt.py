"""
Prompt templates for ForensicsAgent.

SYSTEM_PROMPT instructs the LLM to act as a forensic analyst.
build_user_prompt() assembles the user-turn message from structured pipeline data.
"""

from __future__ import annotations

SYSTEM_PROMPT = """You are a cybersecurity forensics analyst.
You will be given a sequence of anomalous events for a single user over the past 30 days,
along with a graph of the entities (IPs, devices, applications) they are connected to.
Your task is to reconstruct the likely attack sequence and produce a concise forensic narrative.
Be specific about which events indicate escalation or lateral movement.
Respond in plain English, 3-5 sentences."""


def build_user_prompt(
    user_id: str,
    event_chain: list[dict],
    entities: list[str],
    anomaly: dict,
) -> str:
    """Construct the user-turn prompt from structured data.

    Args:
        user_id:     The subject user identifier.
        event_chain: Chronological list of event dicts, each with keys
                     ``ts``, ``event_type``, and optionally ``significance``.
        entities:    Entity strings from Neo4j (e.g. "IP:10.0.0.1").
        anomaly:     Trigger anomaly metadata — expects keys
                     ``root_cause``, ``anomaly_score``, ``severity``.

    Returns:
        Formatted prompt string ready to send as the ``user`` turn.
    """
    chain_text = "\n".join(f"  [{e['ts']}] {e['event_type']} — {e.get('significance', '')}" for e in event_chain)
    entity_text = ", ".join(entities) if entities else "none identified"
    return (
        f"User: {user_id}\n"
        f"Trigger anomaly: {anomaly.get('root_cause', 'Unknown')} "
        f"(score={anomaly.get('anomaly_score', '?')}, severity={anomaly.get('severity', '?')})\n\n"
        f"Event chain (last 30 days, chronological):\n{chain_text}\n\n"
        f"Connected entities: {entity_text}\n\n"
        f"Reconstruct the attack sequence."
    )
