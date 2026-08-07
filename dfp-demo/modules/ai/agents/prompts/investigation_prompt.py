"""
Prompt templates for InvestigationAgent.

SYSTEM_PROMPT instructs the LLM to act as a threat intelligence analyst.
build_user_prompt() assembles the user-turn message from vector-similarity
search results and recurrence statistics.
"""

from __future__ import annotations

SYSTEM_PROMPT = """You are a threat intelligence analyst.
You will be given a list of similar past security incidents (anomaly detections)
retrieved by vector similarity from the incident database.
Summarise the pattern in 2-3 sentences: how many times has this type of incident occurred,
which users or IP ranges are involved, and whether it appears to be an isolated event or a campaign."""


def build_user_prompt(
    similar_detections: list[dict],
    dominant_root_cause: str,
    recurrence_count: int,
) -> str:
    """Construct the user-turn prompt from similarity search results.

    Args:
        similar_detections: List of incident dicts, each with keys
                            ``date``, ``user_id``, ``similarity``,
                            and optionally ``root_cause``.
        dominant_root_cause: Most common root-cause label across similar detections.
        recurrence_count:   Total number of times this pattern has been seen.

    Returns:
        Formatted prompt string ready to send as the ``user`` turn.
    """
    entries = "\n".join(
        f"  [{d['date']}] user={d['user_id']} similarity={d['similarity']:.2f} root_cause={d.get('root_cause', '?')}"
        for d in similar_detections
    )
    return (
        f"Dominant pattern: {dominant_root_cause} ({recurrence_count} occurrences)\n\n"
        f"Similar past detections:\n{entries}\n\n"
        f"Summarise the pattern and assess whether this is an isolated event or a campaign."
    )
