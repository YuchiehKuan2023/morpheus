"""
AgentOrchestrator — runtime coordinator for the Multi-Agent System.

Consumes anomaly task messages from the ``dfp-agent-tasks`` Kafka topic
(published by AIOrchestrator when severity/risk thresholds are met), decides
which agents to invoke per the invocation decision table, runs them in the
correct order, persists every finding to PostgreSQL via FindingsService, and
closes the investigation record.

Execution sequence per message
-------------------------------
Step 1:
    ForensicsAgent.run(task)      — attack chain, Neo4j entities, LLM narrative
Step 2:
    InvestigationAgent.run(task)  — KNN similarity search, recurrence detection

Agents run sequentially (never concurrently) to avoid exceeding LLM rate
limits on shared/free-tier API keys.  Investigations themselves are also
processed one at a time — the Kafka consumer loop blocks until each
_run_investigation() call returns before consuming the next message.

Step 3 — assemble context:
    task.context["forensics_result"]     = forensics_result.result
    task.context["investigation_result"] = investigation_result.result

Step 4:
    RemediationAgent.run(task_with_context) — rule lookup + LLM rationale

Step 5:
    FindingsService.complete_investigation() or .fail_investigation()

Invocation policy
-----------------
    ALL severities / ALL risk scores → forensics + investigation + remediation
    Every anomaly warrants a full investigation regardless of score.

Usage
-----
    orchestrator = AgentOrchestrator(db_url, neo4j_driver, qdrant_client, llm_service)
    orchestrator.start()   # blocks; KeyboardInterrupt → graceful shutdown
"""

from __future__ import annotations

import logging
from typing import Any

import psycopg2
import psycopg2.extras

from modules.ai.agents.base_agent import AgentResult, AgentTask
from modules.ai.agents.findings_service import FindingsService
from modules.ai.agents.forensics_agent import ForensicsAgent
from modules.ai.agents.investigation_agent import InvestigationAgent
from modules.ai.agents.remediation_agent import RemediationAgent
from modules.ai.llm.llm_service import LLMService
from modules.io.kafka_consumer import DFPKafkaConsumer

logger = logging.getLogger(__name__)

_KAFKA_TOPIC = "dfp-agent-tasks"
_CONSUMER_GROUP = "agent-orchestrator"


class AgentOrchestrator:
    """
    Multi-agent orchestrator.

    Instantiated once at startup; ``start()`` blocks until KeyboardInterrupt.

    Args:
        db_url:          libpq connection string for PostgreSQL.
        neo4j_driver:    neo4j.GraphDatabase driver instance.
        qdrant_client:   qdrant_client.QdrantClient instance.
        llm_service:     Initialised LLMService for all agent LLM calls.
        kafka_bootstrap: Kafka broker address (host:port).
    """

    def __init__(
        self,
        db_url: str,
        neo4j_driver: Any,
        qdrant_client: Any,
        llm_service: LLMService,
        kafka_bootstrap: str = "127.0.0.1:29092",
    ) -> None:
        self.findings_service = FindingsService(db_url)
        self.forensics_agent = ForensicsAgent(db_url, neo4j_driver, llm_service)
        self.investigation_agent = InvestigationAgent(db_url, qdrant_client, llm_service)
        self.remediation_agent = RemediationAgent(llm_service)
        self.kafka_bootstrap = kafka_bootstrap

        # Separate connection for fetching anomaly row (not shared with agents)
        self._conn = psycopg2.connect(db_url)
        logger.info("AgentOrchestrator initialised")

    # ------------------------------------------------------------------
    # Public entry point
    # ------------------------------------------------------------------

    def start(self) -> None:
        """Blocking Kafka consumer loop on dfp-agent-tasks."""
        consumer = DFPKafkaConsumer(
            bootstrap_servers=self.kafka_bootstrap,
            topic=_KAFKA_TOPIC,
            group_id=_CONSUMER_GROUP,
            auto_offset_reset="earliest",
        )
        logger.info("=" * 70)
        logger.info("AGENT ORCHESTRATOR starting")
        logger.info(f"  Topic  : {_KAFKA_TOPIC}")
        logger.info(f"  Group  : {_CONSUMER_GROUP}")
        logger.info(f"  Broker : {self.kafka_bootstrap}")
        logger.info("=" * 70)

        try:
            while True:
                messages = consumer.consume_batch(batch_size=10, timeout=1.0)
                for msg in messages:
                    try:
                        self._run_investigation(msg)
                    except Exception as exc:
                        logger.exception("[orchestrator] Unhandled error processing message: %s", exc)
        except KeyboardInterrupt:
            logger.info("AgentOrchestrator stopped by KeyboardInterrupt")
        finally:
            consumer.close()
            self.close()

    def close(self) -> None:
        """Close the DB connection and findings service. Called on shutdown."""
        try:
            self._conn.close()
        except Exception:
            pass
        self.findings_service.close()
        logger.info("AgentOrchestrator closed")

    # ------------------------------------------------------------------
    # Invocation decision table
    # ------------------------------------------------------------------

    def _decide_agents(self, severity: str, risk_score: float) -> list[str]:
        """
        All anomalies trigger the full agent pipeline regardless of severity or
        risk score.  A low score for one user is not the same as a low score for
        another — if it has been flagged as an anomaly, it warrants investigation.
        """
        return ["forensics", "investigation", "remediation"]

    # ------------------------------------------------------------------
    # Investigation lifecycle
    # ------------------------------------------------------------------

    def _run_investigation(self, message: dict[str, Any]) -> None:
        """Full investigation lifecycle for one anomaly task message."""
        anomaly_id: str = str(message.get("anomaly_id") or "")
        severity: str = str(message.get("severity") or "LOW")
        try:
            risk_score: float = float(message.get("risk_score") or 0.0)
        except (TypeError, ValueError):
            logger.warning("[orchestrator] Invalid risk_score in message — defaulting to 0.0")
            risk_score = 0.0

        if not anomaly_id:
            logger.warning("[orchestrator] Message missing anomaly_id — skipping")
            return

        agents_to_invoke = self._decide_agents(severity, risk_score)
        if not agents_to_invoke:
            logger.info(
                "[orchestrator] No agents triggered: anomaly=%s severity=%s risk=%.1f",
                anomaly_id,
                severity,
                risk_score,
            )
            return

        anomaly_data = self._fetch_anomaly(anomaly_id)
        if anomaly_data is None:
            logger.warning(
                "[orchestrator] anomaly_id=%s not found in enriched_anomalies — skipping",
                anomaly_id,
            )
            return

        # Assign an analyst before kicking off the investigation so that the
        # assignment is visible in the UI as soon as the investigation row exists.
        self._assign_analyst(anomaly_id, severity)

        investigation_id = self.findings_service.create_investigation(anomaly_id, severity, agents_to_invoke)

        base_task = AgentTask(
            investigation_id=investigation_id,
            anomaly_id=anomaly_id,
            anomaly_data=anomaly_data,
        )

        all_results: list[AgentResult] = []
        context: dict[str, Any] = {}

        try:
            # Steps 1 + 2: sequential to stay within LLM rate limits
            forensics_result: AgentResult | None = None
            investigation_result: AgentResult | None = None

            if "forensics" in agents_to_invoke:
                forensics_result = self.forensics_agent.run(base_task)
            if "investigation" in agents_to_invoke:
                investigation_result = self.investigation_agent.run(base_task)

            # Persist findings + build context for remediation
            if forensics_result is not None:
                all_results.append(forensics_result)
                self.findings_service.record_finding(investigation_id, forensics_result)
                if forensics_result.status == "complete":
                    context["forensics_result"] = forensics_result.result

            if investigation_result is not None:
                all_results.append(investigation_result)
                self.findings_service.record_finding(investigation_id, investigation_result)
                if investigation_result.status == "complete":
                    context["investigation_result"] = investigation_result.result

            # Step 4: remediation (always after steps 1+2)
            if "remediation" in agents_to_invoke:
                remediation_task = AgentTask(
                    investigation_id=investigation_id,
                    anomaly_id=anomaly_id,
                    anomaly_data=anomaly_data,
                    context=context,
                )
                remediation_result = self.remediation_agent.run(remediation_task)
                all_results.append(remediation_result)
                self.findings_service.record_finding(investigation_id, remediation_result)

            # Step 5: close investigation
            # Mark as failed if ANY agent failed (not only when all agents failed).
            # Partial failures still indicate an incomplete investigation.
            any_failed = bool(all_results) and any(r.status == "failed" for r in all_results)
            if any_failed:
                self.findings_service.fail_investigation(investigation_id, reason="one or more agents failed")
            else:
                self.findings_service.complete_investigation(investigation_id, all_results)

        except Exception as exc:
            logger.exception(
                "[orchestrator] Investigation %s aborted: %s",
                investigation_id,
                exc,
            )
            self.findings_service.fail_investigation(investigation_id, reason=str(exc))

    # ------------------------------------------------------------------
    # DB helpers
    # ------------------------------------------------------------------

    def _assign_analyst(self, anomaly_id: str, severity: str) -> None:
        """SELECT a suitable analyst from analyst_users and UPDATE enriched_anomalies.assigned_to.

        Uses the permissions module to determine which analyst levels are
        allowed to handle each severity:
            LOW      → Level 1 (L1) or Level 4 (admin)
            MEDIUM   → Level 2 (L2) or Level 4 (admin)
            HIGH     → Level 3 (L3) or Level 4 (admin)
            CRITICAL → Level 3 (L3) or Level 4 (admin)

        Falls back to any active analyst when no one at the required level
        is available.  Silently skips if the analyst_users table is empty
        or any DB error occurs so that it never blocks the investigation.
        """
        from scripts.constants.permissions import ANALYST_LEVELS

        # Build list of levels allowed to handle this severity
        sev = severity.upper()
        allowed_levels = [level for level, entry in ANALYST_LEVELS.items() if sev in entry["allowed_severities"]]
        try:
            with self._conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(
                    """
                    SELECT id, username FROM analyst_users
                    WHERE is_active = TRUE AND level = ANY(%s)
                    ORDER BY RANDOM()
                    LIMIT 1
                    """,
                    (allowed_levels,),
                )
                row = cur.fetchone()
                if row is None:
                    # Fallback: any active analyst when no one at the required level
                    cur.execute(
                        "SELECT id, username FROM analyst_users WHERE is_active = TRUE ORDER BY RANDOM() LIMIT 1"
                    )
                    row = cur.fetchone()
                if row is None:
                    logger.warning(
                        "[orchestrator] No active analysts found — skipping assignment for %s",
                        anomaly_id,
                    )
                    self._conn.rollback()
                    return
                cur.execute(
                    "UPDATE enriched_anomalies SET assigned_to = %s WHERE anomaly_id = %s AND assigned_to IS NULL",
                    (row["id"], anomaly_id),
                )
                if cur.rowcount > 0:
                    # Fetch the monitored user_id for the notification message
                    cur.execute(
                        "SELECT user_id FROM enriched_anomalies WHERE anomaly_id = %s",
                        (anomaly_id,),
                    )
                    anomaly_row = cur.fetchone()
                    monitored_user = anomaly_row["user_id"] if anomaly_row else "unknown"
                    cur.execute(
                        """INSERT INTO analyst_notifications
                               (analyst_id, anomaly_id, type, title, message)
                           VALUES (%s, %s, %s, %s, %s)""",
                        (
                            row["id"],
                            anomaly_id,
                            "anomaly_assigned",
                            f"New {sev} anomaly assigned — {monitored_user}",
                            f"You have been auto-assigned anomaly {anomaly_id[:8]}... for user {monitored_user}.",
                        ),
                    )
                self._conn.commit()
                logger.debug(
                    "[orchestrator] Assigned analyst %s to anomaly %s (severity=%s)",
                    row["username"],
                    anomaly_id,
                    severity,
                )
        except Exception as exc:
            self._conn.rollback()
            logger.warning(
                "[orchestrator] Failed to assign analyst for %s: %s",
                anomaly_id,
                exc,
            )

    def _fetch_anomaly(self, anomaly_id: str) -> dict[str, Any] | None:
        """Return full enriched_anomalies row as a dict, or None if absent."""
        with self._conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                "SELECT * FROM enriched_anomalies WHERE anomaly_id = %s",
                (anomaly_id,),
            )
            row = cur.fetchone()
            # Explicitly end the transaction for this read-only operation to avoid
            # leaving the connection "idle in transaction" when autocommit is False.
            self._conn.rollback()
        return dict(row) if row else None
