"""
FindingsService — persistence layer for the Multi-Agent System.

Handles all DB writes for agent investigations and findings.
Every agent writes through this service — never raw SQL in agent files.

Tables managed:
    agent_investigations  — one row per anomaly investigation
    agent_findings        — one row per agent per investigation

Usage:
    svc = FindingsService()
    inv_id = svc.create_investigation(anomaly_id, "HIGH", ["forensics", "investigation", "remediation"])
    svc.record_finding(inv_id, result)
    svc.complete_investigation(inv_id, [forensics_result, investigation_result, remediation_result])
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

import psycopg2
import psycopg2.extras

from modules.ai.agents.base_agent import AgentResult

logger = logging.getLogger(__name__)


def _build_dsn() -> dict[str, Any]:
    """Return psycopg2 connect kwargs from environment variables."""
    from modules.utils.db import get_db_params

    return get_db_params()


class FindingsService:
    """
    Persist agent investigation state to PostgreSQL.

    Accepts either a libpq connection string or falls back to
    individual POSTGRES_* environment variables (matching the rest of
    the codebase — see PersistenceService).

    Args:
        db_url: Optional libpq connection string
                (e.g. "postgresql://user:pass@host:5432/db").
                If omitted, reads POSTGRES_HOST/PORT/DB/USER/PASSWORD.
    """

    def __init__(self, db_url: str | None = None) -> None:
        if db_url:
            self._conn = psycopg2.connect(db_url)
        else:
            self._conn = psycopg2.connect(**_build_dsn())
        logger.info("FindingsService connected to PostgreSQL")

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def create_investigation(
        self,
        anomaly_id: str,
        severity: str,
        agents_to_invoke: list[str],
    ) -> str:
        """
        Open a new investigation record.

        Returns:
            investigation_id (UUID string)
        """
        with self._conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                """
                INSERT INTO agent_investigations
                    (anomaly_id, status, severity_at_trigger, agents_invoked, triggered_at)
                VALUES (%s, 'running', %s, %s, NOW())
                RETURNING investigation_id
                """,
                (anomaly_id, severity, agents_to_invoke),
            )
            row = cur.fetchone()
        self._conn.commit()
        if row is None:
            raise RuntimeError(f"INSERT into agent_investigations returned no row for anomaly_id={anomaly_id}")
        investigation_id = str(row["investigation_id"])
        logger.info(
            "Investigation created: %s  anomaly=%s  severity=%s  agents=%s",
            investigation_id,
            anomaly_id,
            severity,
            agents_to_invoke,
        )
        return investigation_id

    def record_finding(
        self,
        investigation_id: str,
        result: AgentResult,
    ) -> None:
        """
        Persist one agent's result into agent_findings.

        started_at is back-calculated from completed_at and latency_ms so
        the timeline is consistent even if the agent ran asynchronously.
        """
        completed_at = datetime.now(tz=timezone.utc)
        started_at = completed_at - timedelta(milliseconds=result.latency_ms)

        with self._conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO agent_findings
                    (investigation_id, agent_type, status, result,
                     llm_tokens_used, latency_ms, started_at, completed_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    investigation_id,
                    result.agent_type,
                    result.status,
                    psycopg2.extras.Json(result.result),
                    result.llm_tokens_used or None,
                    result.latency_ms or None,
                    started_at,
                    completed_at,
                ),
            )
        self._conn.commit()
        logger.info(
            "Finding recorded: investigation=%s  agent=%s  status=%s",
            investigation_id,
            result.agent_type,
            result.status,
        )

    def complete_investigation(
        self,
        investigation_id: str,
        agent_results: list[AgentResult],
    ) -> None:
        """
        Mark investigation complete and write aggregated report.

        confidence_score: mean confidence across successful agents
                          (only successful agents contribute).
        overall_recommendation: first non-empty action from the remediation
                                agent; falls back to a generic string.
        raw_report: full merged output from all agents.
        """
        successful = [r for r in agent_results if r.status == "complete"]

        # Confidence: mean of successful agent confidences
        if successful:
            confidence_score = sum(r.confidence for r in successful) / len(successful)
        else:
            confidence_score = 0.0

        # Overall recommendation: pull primary action from remediation result
        overall_recommendation = self._extract_recommendation(agent_results)

        # Raw report: keyed by agent_type
        raw_report = {r.agent_type: r.result for r in agent_results}

        with self._conn.cursor() as cur:
            cur.execute(
                """
                UPDATE agent_investigations
                SET status = 'complete',
                    completed_at = NOW(),
                    confidence_score = %s,
                    overall_recommendation = %s,
                    raw_report = %s
                WHERE investigation_id = %s
                """,
                (
                    round(confidence_score, 4),
                    overall_recommendation,
                    psycopg2.extras.Json(raw_report),
                    investigation_id,
                ),
            )
        self._conn.commit()
        logger.info(
            "Investigation complete: %s  confidence=%.2f  agents_succeeded=%d/%d",
            investigation_id,
            confidence_score,
            len(successful),
            len(agent_results),
        )

    def fail_investigation(
        self,
        investigation_id: str,
        reason: str = "",
    ) -> None:
        """Mark investigation as failed (all agents failed or unrecoverable error)."""
        with self._conn.cursor() as cur:
            cur.execute(
                """
                UPDATE agent_investigations
                SET status = 'failed',
                    completed_at = NOW()
                WHERE investigation_id = %s
                """,
                (investigation_id,),
            )
        self._conn.commit()
        logger.warning(
            "Investigation failed: %s  reason=%s",
            investigation_id,
            reason,
        )

    def get_investigation(self, anomaly_id: str) -> dict[str, Any] | None:
        """
        Return the most recent investigation for an anomaly, including
        all agent findings as a nested list.

        Returns None if no investigation exists yet.
        """
        with self._conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                """
                SELECT
                    ai.investigation_id,
                    ai.anomaly_id,
                    ai.triggered_at,
                    ai.completed_at,
                    ai.status,
                    ai.severity_at_trigger,
                    ai.agents_invoked,
                    ai.confidence_score,
                    ai.overall_recommendation,
                    ai.raw_report,
                    COALESCE(
                        json_agg(
                            json_build_object(
                                'finding_id',       af.finding_id,
                                'agent_type',       af.agent_type,
                                'status',           af.status,
                                'result',           af.result,
                                'llm_tokens_used',  af.llm_tokens_used,
                                'latency_ms',       af.latency_ms,
                                'started_at',       af.started_at,
                                'completed_at',     af.completed_at
                            ) ORDER BY af.started_at
                        ) FILTER (WHERE af.finding_id IS NOT NULL),
                        '[]'
                    ) AS findings
                FROM agent_investigations ai
                LEFT JOIN agent_findings af
                       ON af.investigation_id = ai.investigation_id
                WHERE ai.anomaly_id = %s
                GROUP BY ai.investigation_id
                ORDER BY ai.triggered_at DESC
                LIMIT 1
                """,
                (anomaly_id,),
            )
            row = cur.fetchone()

        if row is None:
            return None

        result = dict(row)
        # Coerce timestamps to ISO strings for JSON serialisation
        for col in ("triggered_at", "completed_at"):
            if result.get(col) and hasattr(result[col], "isoformat"):
                result[col] = result[col].isoformat()
        return result

    def close(self) -> None:
        """Close the PostgreSQL connection."""
        self._conn.close()
        logger.info("FindingsService connection closed")

    def __enter__(self) -> FindingsService:
        return self

    def __exit__(self, *_: Any) -> None:
        self.close()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _extract_recommendation(agent_results: list[AgentResult]) -> str:
        """Pull the top-priority action from the remediation agent result."""
        for result in agent_results:
            if result.agent_type == "remediation" and result.status == "complete":
                actions = result.result.get("recommended_actions", [])
                for action_entry in actions:
                    action = action_entry.get("action")
                    if action:
                        return action
        return "Manual SOC review required."
