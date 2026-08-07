"""
Episodic Memory — cross-turn persistence for multi-turn investigations.

Records a compressed summary of each completed agent turn (query, answer,
tools used, entities referenced) into the ``chat_memory`` table.  At the
start of a new turn the agent retrieves the most relevant prior turns so
it can resolve follow-up questions like "tell me more about that user".

Database access is provided by ``modules.utils.db.get_db``.
"""

from __future__ import annotations

import logging
import re

from modules.utils.db import get_db

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Entity extraction helpers
# ---------------------------------------------------------------------------

_EMAIL_RE = re.compile(r"[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+")
_UUID_RE = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", re.I)
_IP_RE = re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")


def extract_entities(text: str) -> list[str]:
    """Pull user-ids / anomaly-ids / IPs out of free text."""
    entities: list[str] = []
    entities.extend(_EMAIL_RE.findall(text))
    entities.extend(_UUID_RE.findall(text))
    entities.extend(_IP_RE.findall(text))
    # Deduplicate while preserving order
    seen: set[str] = set()
    unique: list[str] = []
    for e in entities:
        el = e.lower()
        if el not in seen:
            seen.add(el)
            unique.append(e)
    return unique


# ---------------------------------------------------------------------------
# EpisodicMemory
# ---------------------------------------------------------------------------


class EpisodicMemory:
    """
    Cross-turn memory for multi-turn investigations.

    Each completed agent turn is recorded as a row in ``chat_memory``.
    Before the agent starts a new turn it calls :meth:`get_relevant_context`
    to retrieve the most useful prior turns (ranked by recency + entity
    overlap with the new query).
    """

    def __init__(self, session_id: int) -> None:
        self.session_id = session_id

    # ------------------------------------------------------------------
    # Write path — record a completed turn
    # ------------------------------------------------------------------

    def record_turn(
        self,
        query: str,
        answer: str,
        tools_used: list[str],
        entities: set[str] | list[str],
    ) -> None:
        """Persist a completed turn's key facts to the session."""
        turn_number = self._next_turn()
        answer_summary = self._summarise(answer, max_len=500)
        entity_list = sorted(set(entities)) if entities else []

        try:
            with get_db() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        INSERT INTO chat_memory
                            (session_id, turn_number, query_summary,
                             answer_summary, tools_used, entities_referenced)
                        VALUES (%s, %s, %s, %s, %s, %s)
                        ON CONFLICT (session_id, turn_number)
                        DO UPDATE SET
                            query_summary       = EXCLUDED.query_summary,
                            answer_summary      = EXCLUDED.answer_summary,
                            tools_used          = EXCLUDED.tools_used,
                            entities_referenced = EXCLUDED.entities_referenced
                        """,
                        (
                            self.session_id,
                            turn_number,
                            query,
                            answer_summary,
                            tools_used or [],
                            entity_list,
                        ),
                    )
                conn.commit()
        except Exception as exc:
            logger.warning("Failed to record turn %d: %s", turn_number, exc)

    # ------------------------------------------------------------------
    # Read path — retrieve relevant prior context
    # ------------------------------------------------------------------

    def get_relevant_context(
        self,
        query: str,
        max_turns: int = 5,
    ) -> str:
        """
        Retrieve the most relevant prior turns for context injection.

        Ranking: entity-overlap with the current query first, then recency.
        Returns a formatted text block suitable for prompt injection.
        """
        try:
            import psycopg2.extras
        except ImportError:
            return ""

        try:
            with get_db() as conn:
                with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                    cur.execute(
                        """
                        SELECT turn_number, query_summary, answer_summary,
                               tools_used, entities_referenced
                        FROM chat_memory
                        WHERE session_id = %s
                        ORDER BY turn_number DESC
                        LIMIT %s
                        """,
                        (self.session_id, max_turns * 2),
                    )
                    rows = cur.fetchall()
        except Exception as exc:
            logger.warning("Failed to fetch episodic context: %s", exc)
            return ""

        if not rows:
            return ""

        # Rank by entity overlap with the new query, then by recency
        query_entities = {e.lower() for e in extract_entities(query)}
        ranked = sorted(
            rows,
            key=lambda r: (
                _entity_overlap(r.get("entities_referenced") or [], query_entities),
                r["turn_number"],
            ),
            reverse=True,
        )

        return _format_turns(ranked[:max_turns])

    def get_all_entities(self) -> list[str]:
        """Return all entities referenced in this session (deduplicated)."""
        try:
            with get_db() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        SELECT DISTINCT unnest(entities_referenced) AS entity
                        FROM chat_memory
                        WHERE session_id = %s
                        ORDER BY entity
                        """,
                        (self.session_id,),
                    )
                    return [row[0] for row in cur.fetchall()]
        except Exception as exc:
            logger.warning("Failed to fetch session entities: %s", exc)
            return []

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _next_turn(self) -> int:
        """Get the next turn number for this session."""
        try:
            with get_db() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        "SELECT COALESCE(MAX(turn_number), 0) + 1 FROM chat_memory WHERE session_id = %s",
                        (self.session_id,),
                    )
                    return cur.fetchone()[0]
        except Exception:
            return 1

    @staticmethod
    def _summarise(text: str, max_len: int = 500) -> str:
        """Truncate answer text for storage, preserving sentence boundaries."""
        if len(text) <= max_len:
            return text
        # Try to cut at a sentence boundary
        truncated = text[:max_len]
        last_period = truncated.rfind(".")
        if last_period > max_len // 2:
            return truncated[: last_period + 1]
        return truncated + "..."


# ---------------------------------------------------------------------------
# Module-level helpers
# ---------------------------------------------------------------------------


def _entity_overlap(stored: list[str], query_entities: set[str]) -> int:
    """Count how many stored entities appear in the query's entity set."""
    return sum(1 for e in stored if e.lower() in query_entities)


def _format_turns(turns: list[dict]) -> str:
    """Format prior turns into a text block for prompt injection."""
    parts: list[str] = []
    for t in turns:
        tools = ", ".join(t.get("tools_used") or []) or "none"
        entities = ", ".join(t.get("entities_referenced") or []) or "none"
        parts.append(
            f"[Turn {t['turn_number']}] Q: {t['query_summary']}\n"
            f"  A: {t.get('answer_summary', '(no answer)')}\n"
            f"  Tools: {tools} | Entities: {entities}"
        )
    return "\n".join(parts)
