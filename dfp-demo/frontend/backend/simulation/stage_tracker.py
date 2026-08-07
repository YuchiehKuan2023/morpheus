"""
Stage tracker for a single simulation session.

Runs in its own thread (submitted to the SimulationManager thread pool).
Polls the DB every POLL_INTERVAL seconds and advances the session through
these stages by watching enriched_anomalies, agent_investigations, and
agent_findings:

  sent  ──► detected ──► enriched ──► classified ──► agent_running ──► complete
         └─► clean (no row within timeout)              └─► failed

  Score >= threshold → all stages run unconditionally.
  Score < threshold  → no row inserted → clean exit.

For each stage transition a SimProcessEntry is appended to stages_log and
the simulation_sessions row is updated atomically.

Process groups tracked:
  inference:          kafka_sent, dfp_scoring
  ai_orchestrator:    context_enrichment, llm_classification, risk_scoring
  agent_orchestrator: forensics_agent, investigation_agent, remediation_agent
"""

import json
import logging
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID

import psycopg2
import psycopg2.extras

# Make scripts/utils importable regardless of CWD — same pattern as event_generator.py.
_PROJECT_ROOT = Path(__file__).resolve().parents[3]  # dfp-demo/
for _p in (str(_PROJECT_ROOT / "scripts"), str(_PROJECT_ROOT)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from utils.shared.extract_severity import (  # type: ignore  # noqa: E402
    severity_from_score as _severity_from_score,  # noqa: E402  # pyright: ignore[reportMissingImports]
)

logger = logging.getLogger(__name__)


POLL_INTERVAL = 2  # seconds between DB polls
DETECTION_TIMEOUT = 35  # seconds to wait for enriched_anomalies row / AI orchestrator
# session signal.  The AI orchestrator now writes directly to
# simulation_sessions as soon as the anomaly row is persisted
# (clean events are signalled even faster), so this timeout is
# only a last-resort fallback for events that never reached the
# AI orchestrator at all (e.g. Kafka consumer lag at startup).
AI_ORCH_TIMEOUT = 300  # seconds to wait for each AI enrichment phase (generous for Groq 429 retries)
AGENT_ORCH_TIMEOUT = 180  # seconds to wait for agent investigation to complete

# Mirrors the decision table in AgentOrchestrator._decide_agents().
# Kept here so the stage tracker can skip the agent-wait phase without
# importing from the modules package.
# Mirrors AgentOrchestrator._decide_agents: severity alone is the gate;
# risk_score is no longer used to include/exclude agents.
_AGENT_ACTIVE_SEVERITIES = {"CRITICAL", "HIGH", "MEDIUM", "LOW"}


def _agents_will_run(severity: str, risk_score: float | None) -> bool:  # noqa: ARG001
    """Return True if the agent orchestrator will create an investigation."""
    sev = (severity or "").upper()
    return sev in _AGENT_ACTIVE_SEVERITIES


def recover_orphaned_sessions(db_params: dict | None = None) -> int:
    """Mark sessions that are stuck in in-progress stages as failed.

    Called once at application startup to clean up sessions whose tracker
    threads were killed by a service restart.  Any session that has been in
    an in-progress stage for longer than the maximum possible tracker
    lifetime is considered orphaned.

    Args:
        db_params: psycopg2 connection kwargs.  If None the standard env
            vars (POSTGRES_*) are used.

    Returns:
        Number of sessions recovered.
    """
    if db_params is None:
        from modules.utils.db import get_db_params

        db_params = get_db_params()

    # Maximum tracker lifetime: DETECTION_TIMEOUT + 3×AI_ORCH_TIMEOUT + AGENT_ORCH_TIMEOUT
    # = 300 + 900 + 180 = 1380 s ≈ 23 min.  Use 30 min to be safe.
    _ORPHAN_CUTOFF_MINUTES = 30

    _IN_PROGRESS_STAGES = "('sent','detected','enriched','classified','agent_running')"

    try:
        conn = psycopg2.connect(**db_params)
    except Exception as exc:
        logger.error("recover_orphaned_sessions: could not connect to DB: %s", exc)
        return 0

    recovered = 0
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                f"""
                SELECT session_id, stage, stages_log
                FROM simulation_sessions
                WHERE stage IN {_IN_PROGRESS_STAGES}
                  AND updated_at < NOW() - INTERVAL '{_ORPHAN_CUTOFF_MINUTES} minutes'
                """
            )
            rows = cur.fetchall()

        for row in rows:
            sid = str(row["session_id"])
            old_stage = row["stage"]
            try:
                stages_log = list(row["stages_log"]) if row["stages_log"] else []
            except Exception:
                stages_log = []

            # Append a sentinel entry so the UI shows a clear failure reason.
            stages_log = _upsert_process(
                stages_log,
                "agent_orchestrator",
                "forensics_agent",
                "error",
                f"Orphan recovery: tracker killed at stage='{old_stage}' (service restart)",
            )

            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE simulation_sessions
                    SET stage = 'failed',
                        stages_log = %s,
                        updated_at = NOW(),
                        completed_at = NOW()
                    WHERE session_id = %s
                    """,
                    (json.dumps(stages_log), sid),
                )
            conn.commit()
            recovered += 1
            logger.warning(
                "Orphan recovery: session %s was stuck at stage='%s', marked failed",
                sid,
                old_stage,
            )
    except Exception as exc:
        logger.error("recover_orphaned_sessions failed: %s", exc, exc_info=True)
    finally:
        conn.close()

    if recovered:
        logger.info("Orphan recovery: %d session(s) recovered", recovered)
    else:
        logger.info("Orphan recovery: no stuck sessions found")
    return recovered


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _build_initial_stages_log() -> list[dict]:
    """Return the full process skeleton with all entries set to 'pending'."""
    groups = [
        ("inference", ["kafka_sent", "dfp_scoring"]),
        (
            "ai_orchestrator",
            ["context_enrichment", "llm_classification", "risk_scoring", "shap_explanation", "lime_explanation"],
        ),
        ("agent_orchestrator", ["forensics_agent", "investigation_agent", "remediation_agent"]),
    ]
    entries = []
    for group, processes in groups:
        for process in processes:
            entries.append(
                {
                    "group": group,
                    "process": process,
                    "status": "pending",
                    "ts": None,
                    "detail": None,
                }
            )
    return entries


def _upsert_process(
    stages_log: list[dict],
    group: str,
    process: str,
    status: str,
    detail: str | None = None,
) -> list[dict]:
    """Return a new stages_log list with the given process entry updated."""
    updated = []
    for entry in stages_log:
        if entry["group"] == group and entry["process"] == process:
            updated.append(
                {
                    **entry,
                    "status": status,
                    "ts": _now_iso(),
                    "detail": detail,
                }
            )
        else:
            updated.append(entry)
    return updated


class StageTracker(threading.Thread):
    """
    Tracks one simulation session through the pipeline.

    Created by SimulationScheduler after an event is published.
    Reads / writes simulation_sessions via its own DB connection.
    Signals completion via the *done_event* threading.Event so the manager
    can remove it from the active set.
    """

    def __init__(
        self,
        session_id: UUID,
        user_id: str,
        sent_at: datetime,
        db_params: dict,
        *,
        skip_detection: bool = False,
        anomaly_id: str | None = None,
    ):
        super().__init__(daemon=True, name=f"tracker-{str(session_id)[:8]}")
        self.session_id = session_id
        self.user_id = user_id
        self.sent_at = sent_at
        self.db_params = db_params
        self.done_event = threading.Event()
        self._skip_detection = skip_detection
        self._known_anomaly_id = anomaly_id

    # ── DB helpers ─────────────────────────────────────────────────────────────

    def _connect(self):
        return psycopg2.connect(**self.db_params)

    def _load_session(self, conn) -> dict | None:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                "SELECT * FROM simulation_sessions WHERE session_id = %s",
                (str(self.session_id),),
            )
            row = cur.fetchone()
            return dict(row) if row else None

    def _save(self, conn, stage: str, stages_log: list[dict], extra: dict | None = None) -> None:
        fields = {
            "stage": stage,
            "stages_log": json.dumps(stages_log),
            "updated_at": datetime.now(timezone.utc),
        }
        if extra:
            fields.update(extra)

        set_clause = ", ".join(f"{k} = %s" for k in fields)
        values = list(fields.values()) + [str(self.session_id)]

        with conn.cursor() as cur:
            cur.execute(
                f"UPDATE simulation_sessions SET {set_clause} WHERE session_id = %s",
                values,
            )
        conn.commit()

    # ── Polling helpers ────────────────────────────────────────────────────────

    def _poll_enriched_anomaly(self, conn) -> dict | None:
        """Return the enriched_anomalies row for this session, or None.

        First tries to match by _simulation_session_id stored in original_event
        (available for events dispatched after this filtering was added).
        Falls back to user_id + created_at range for older events.
        """
        session_id_str = str(self.session_id)
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                """
                SELECT anomaly_id, anomaly_score, severity, root_cause,
                       risk_score, is_anomaly, classified_by, status, validation_confidence
                FROM enriched_anomalies
                WHERE original_event->>'_simulation_session_id' = %s
                ORDER BY created_at ASC
                LIMIT 1
                """,
                (session_id_str,),
            )
            row = cur.fetchone()
            if row:
                return dict(row)

        # Fallback: match by user + time window (events before session_id tagging)
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                """
                SELECT anomaly_id, anomaly_score, severity, root_cause,
                       risk_score, is_anomaly, classified_by, status, validation_confidence
                FROM enriched_anomalies
                WHERE user_id = %s AND created_at > %s
                  AND original_event->>'_simulation_session_id' IS NULL
                ORDER BY created_at ASC
                LIMIT 1
                """,
                (self.user_id, self.sent_at),
            )
            row = cur.fetchone()
            return dict(row) if row else None

    def _poll_agent_investigation(self, conn, anomaly_id: str) -> dict | None:
        """Return the agent_investigations row for this anomaly, or None."""
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                """
                SELECT investigation_id, status, agents_invoked,
                       triggered_at, completed_at, confidence_score
                FROM agent_investigations
                WHERE anomaly_id = %s
                ORDER BY triggered_at DESC
                LIMIT 1
                """,
                (anomaly_id,),
            )
            row = cur.fetchone()
            return dict(row) if row else None

    def _poll_enriched_anomaly_by_id(self, conn, anomaly_id: str) -> dict | None:
        """Return the enriched_anomalies row by anomaly_id directly."""
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                """
                SELECT anomaly_id, anomaly_score, severity, root_cause,
                       risk_score, is_anomaly, classified_by, status, validation_confidence
                FROM enriched_anomalies
                WHERE anomaly_id = %s
                """,
                (anomaly_id,),
            )
            row = cur.fetchone()
            return dict(row) if row else None

    def _mark_processed(self, conn, anomaly_id: str) -> None:
        """Mark the anomaly as fully processed."""
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE enriched_anomalies SET processed = TRUE WHERE anomaly_id = %s",
                (anomaly_id,),
            )
        conn.commit()

    def _poll_agent_findings(self, conn, investigation_id: str) -> list[dict]:
        """Return all agent_findings rows for this investigation."""
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                """
                SELECT agent_type, status, started_at, completed_at,
                       latency_ms, result
                FROM agent_findings
                WHERE investigation_id = %s
                ORDER BY started_at ASC
                """,
                (investigation_id,),
            )
            return [dict(r) for r in cur.fetchall()]

    def _poll_llm_explanation(self, conn, anomaly_id: str) -> bool:
        """Return True if an llm_explanations row exists for this anomaly."""
        with conn.cursor() as cur:
            cur.execute(
                "SELECT 1 FROM llm_explanations WHERE detection_id = %s LIMIT 1",
                (anomaly_id,),
            )
            return cur.fetchone() is not None

    # ── Main tracking loop ─────────────────────────────────────────────────────

    def run(self) -> None:
        try:
            self._track()
        except Exception as exc:
            logger.error("Tracker %s crashed: %s", self.session_id, exc, exc_info=True)
        finally:
            self.done_event.set()

    def _track(self) -> None:
        conn = self._connect()
        try:
            stages_log = _build_initial_stages_log()

            # ── skip_detection fast-path (re-orchestration of existing anomaly) ─
            if self._skip_detection and self._known_anomaly_id:
                anomaly_id = self._known_anomaly_id
                anomaly_row = self._poll_enriched_anomaly_by_id(conn, anomaly_id)
                score = anomaly_row.get("anomaly_score") if anomaly_row else None
                severity = _severity_from_score(float(score)) if score is not None else "UNKNOWN"
                stages_log = _upsert_process(
                    stages_log,
                    "inference",
                    "kafka_sent",
                    "completed",
                    "Existing anomaly — skipped",
                )
                stages_log = _upsert_process(
                    stages_log,
                    "inference",
                    "dfp_scoring",
                    "completed",
                    f"Score={score:.2f} — existing anomaly" if score is not None else "Existing anomaly",
                )
                stages_log = _upsert_process(
                    stages_log,
                    "ai_orchestrator",
                    "context_enrichment",
                    "running",
                    "AI Orchestrator enriching context…",
                )
                self._save(
                    conn,
                    "detected",
                    stages_log,
                    extra={"anomaly_id": anomaly_id, "anomaly_score": score, "severity": severity},
                )
            else:
                # ── Mark kafka_sent as completed immediately ────────────────────
                stages_log = _upsert_process(
                    stages_log, "inference", "kafka_sent", "completed", "Event published to Kafka dfp-events"
                )
                stages_log = _upsert_process(
                    stages_log,
                    "inference",
                    "dfp_scoring",
                    "running",
                    "Running DFP autoencoder scoring and AI enrichment pipeline…",
                )
                self._save(conn, "sent", stages_log)

                # ── Phase 1: wait for the AI orchestrator to signal the outcome ──
                detection_deadline = time.monotonic() + DETECTION_TIMEOUT
                anomaly_row = None
                while time.monotonic() < detection_deadline:
                    time.sleep(POLL_INTERVAL)

                    session_row = self._load_session(conn)
                    if session_row:
                        if session_row.get("stage") == "clean":
                            stages_log = _upsert_process(
                                stages_log,
                                "inference",
                                "dfp_scoring",
                                "completed",
                                "Score below threshold — clean event",
                            )
                            self._save(conn, "clean", stages_log, extra={"completed_at": datetime.now(timezone.utc)})
                            return
                        if session_row.get("stage") == "detected" and session_row.get("anomaly_id"):
                            anomaly_row = self._poll_enriched_anomaly(conn)
                            if anomaly_row:
                                break

                    anomaly_row = self._poll_enriched_anomaly(conn)
                    if anomaly_row:
                        break

                if not anomaly_row:
                    session_row = self._load_session(conn)
                    if session_row and session_row.get("stage") == "clean":
                        stages_log = _upsert_process(
                            stages_log, "inference", "dfp_scoring", "completed", "Score below threshold — clean event"
                        )
                        self._save(conn, "clean", stages_log, extra={"completed_at": datetime.now(timezone.utc)})
                        return
                    stages_log = _upsert_process(
                        stages_log, "inference", "dfp_scoring", "completed", "Score below threshold — clean event"
                    )
                    self._save(conn, "clean", stages_log, extra={"completed_at": datetime.now(timezone.utc)})
                    return

                anomaly_id = str(anomaly_row["anomaly_id"])
                score = anomaly_row.get("anomaly_score")
                severity = _severity_from_score(float(score)) if score is not None else "UNKNOWN"

                stages_log = _upsert_process(
                    stages_log,
                    "inference",
                    "dfp_scoring",
                    "completed",
                    f"Score={score:.2f} above threshold — severity={severity}",
                )
                stages_log = _upsert_process(
                    stages_log, "ai_orchestrator", "context_enrichment", "running", "AI Orchestrator enriching context…"
                )
                self._save(
                    conn,
                    "detected",
                    stages_log,
                    extra={
                        "anomaly_id": anomaly_id,
                        "anomaly_score": score,
                        "severity": severity,
                    },
                )

            # ── Phase 2: wait for LLM explanation (context_enrichment) ─────────
            # Polls llm_explanations so context_enrichment completes as soon as the
            # LLM narrative is generated — not waiting for the full AI pipeline.
            context_deadline = time.monotonic() + AI_ORCH_TIMEOUT
            llm_done = False
            while time.monotonic() < context_deadline:
                time.sleep(POLL_INTERVAL)
                if self._poll_llm_explanation(conn, anomaly_id):
                    llm_done = True
                    break

            stages_log = _upsert_process(
                stages_log,
                "ai_orchestrator",
                "context_enrichment",
                "completed" if llm_done else "error",
                "LLM explanation generated" if llm_done else "Timeout — LLM explanation not generated",
            )
            if not llm_done:
                self._save(conn, "failed", stages_log, extra={"completed_at": datetime.now(timezone.utc)})
                return

            stages_log = _upsert_process(
                stages_log, "ai_orchestrator", "llm_classification", "running", "Stage 1 validation running…"
            )
            self._save(conn, "enriched", stages_log)

            # ── Phase 3: wait for Stage 1 validation verdict (llm_classification) ─
            # label_single writes is_anomaly + validation_confidence atomically.
            # Use validation_confidence as the completion signal: it is always set
            # to a non-NULL float (including for UNCERTAIN where is_anomaly=NULL),
            # so NULL means the labeler hasn't written yet — a true timeout.
            validation_deadline = time.monotonic() + AI_ORCH_TIMEOUT
            while time.monotonic() < validation_deadline:
                time.sleep(POLL_INTERVAL)
                if self._known_anomaly_id:
                    anomaly_row = self._poll_enriched_anomaly_by_id(conn, anomaly_id)
                else:
                    anomaly_row = self._poll_enriched_anomaly(conn)
                if anomaly_row and anomaly_row.get("validation_confidence") is not None:
                    break

            is_anomaly = anomaly_row.get("is_anomaly") if anomaly_row else None
            confidence = anomaly_row.get("validation_confidence") if anomaly_row else None

            if confidence is None:
                # Stage 1 labeler didn't write within timeout (e.g. crashed).
                # Mark it as error but continue — Stage 2 and agents still run.
                stages_log = _upsert_process(
                    stages_log, "ai_orchestrator", "llm_classification", "error", "Validation timeout"
                )
            else:
                if is_anomaly is True:
                    is_anomaly_label = "TRUE ANOMALY"
                elif is_anomaly is False:
                    is_anomaly_label = "FALSE POSITIVE"
                else:
                    is_anomaly_label = "UNCERTAIN"
                stages_log = _upsert_process(
                    stages_log,
                    "ai_orchestrator",
                    "llm_classification",
                    "completed",
                    f"Verdict: {is_anomaly_label}"
                    + (f" (confidence={confidence:.2f})" if confidence is not None else ""),
                )

            # ── Phase 4: wait for Stage 2 root cause + risk score (risk_scoring) ─
            # Stage 2 runs for ALL above-threshold detections regardless of the
            # Stage 1 verdict — analysts need root cause, risk score and SHAP
            # even for events labelled false positive or uncertain.
            root_cause: str | None = None
            risk_score: float | None = None

            clf_deadline = time.monotonic() + AI_ORCH_TIMEOUT
            while time.monotonic() < clf_deadline:
                time.sleep(POLL_INTERVAL)
                if self._known_anomaly_id:
                    anomaly_row = self._poll_enriched_anomaly_by_id(conn, anomaly_id)
                else:
                    anomaly_row = self._poll_enriched_anomaly(conn)
                if anomaly_row and anomaly_row.get("root_cause"):
                    break

            root_cause = anomaly_row.get("root_cause") if anomaly_row else None
            risk_score = anomaly_row.get("risk_score") if anomaly_row else None
            stages_log = _upsert_process(
                stages_log,
                "ai_orchestrator",
                "risk_scoring",
                "completed" if root_cause else "error",
                (
                    f"Root cause: {root_cause}" + (f", risk={risk_score:.1f}" if risk_score is not None else "")
                    if root_cause
                    else "Timeout — Stage 2 classification did not complete"
                ),
            )
            explanation_status = "completed" if root_cause else "error"
            shap_message = (
                "SHAP feature attribution computed"
                if root_cause
                else "Stage 2 classification did not complete — SHAP explanation unavailable"
            )
            lime_message = (
                "LIME local explanation available on-demand"
                if root_cause
                else "Stage 2 classification did not complete — LIME explanation unavailable"
            )
            stages_log = _upsert_process(
                stages_log,
                "ai_orchestrator",
                "shap_explanation",
                explanation_status,
                shap_message,
            )
            stages_log = _upsert_process(
                stages_log,
                "ai_orchestrator",
                "lime_explanation",
                explanation_status,
                lime_message,
            )

            self._save(
                conn,
                "classified",
                stages_log,
                extra={
                    "root_cause": root_cause,
                    "risk_score": risk_score,
                },
            )

            # ── Phase 4: skip agent phase when orchestrator won't fire ──────────
            # The agent orchestrator only triggers investigations for CRITICAL/HIGH
            # severity or MEDIUM with risk_score >= 60.  For LOW severity or low-
            # risk MEDIUM events it silently discards the Kafka message — no
            # agent_investigations row is ever created.  Detect this deterministic
            # no-op up front so we can close the session as 'complete' immediately
            # rather than burning AGENT_ORCH_TIMEOUT seconds waiting for a row
            # that will never appear.
            if not _agents_will_run(severity, risk_score):
                skip_reason = f"Severity={severity} does not meet threshold for agent investigation" + (
                    f" (risk_score={risk_score:.1f})" if risk_score is not None else ""
                )
                for agent in ("forensics_agent", "investigation_agent", "remediation_agent"):
                    stages_log = _upsert_process(stages_log, "agent_orchestrator", agent, "completed", skip_reason)
                self._mark_processed(conn, anomaly_id)
                self._save(
                    conn,
                    "complete",
                    stages_log,
                    extra={"completed_at": datetime.now(timezone.utc)},
                )
                return

            # ── Phase 4: wait for agent orchestrator ───────────────────────────
            # agents_invoked is resolved once the investigation row exists;
            # pre-marking is skipped because all agents are already pending
            # from _build_initial_stages_log().
            all_agents = ("forensics_agent", "investigation_agent", "remediation_agent")

            agent_deadline = time.monotonic() + AGENT_ORCH_TIMEOUT
            investigation_row = None
            while time.monotonic() < agent_deadline:
                time.sleep(POLL_INTERVAL)
                investigation_row = self._poll_agent_investigation(conn, anomaly_id)
                if investigation_row:
                    break

            if not investigation_row:
                for agent in all_agents:
                    stages_log = _upsert_process(
                        stages_log,
                        "agent_orchestrator",
                        agent,
                        "error",
                        "Agent orchestrator timeout — no investigation created",
                    )
                self._save(conn, "failed", stages_log, extra={"completed_at": datetime.now(timezone.utc)})
                return

            investigation_id = str(investigation_row["investigation_id"])

            # Resolve which agents were actually invoked so non-invoked agents
            # are not left in a false 'pending' state.
            # agents_invoked in DB stores short names ("forensics", "investigation",
            # "remediation"); append "_agent" to match the stage process keys.
            agents_invoked_raw = investigation_row.get("agents_invoked")
            if isinstance(agents_invoked_raw, (list, tuple, set)):
                agents_invoked = {str(a).strip() + "_agent" for a in agents_invoked_raw if str(a).strip()}
            elif isinstance(agents_invoked_raw, str):
                try:
                    parsed_agents = json.loads(agents_invoked_raw)
                except (TypeError, ValueError):
                    parsed_agents = None
                if isinstance(parsed_agents, (list, tuple, set)):
                    agents_invoked = {str(a).strip() + "_agent" for a in parsed_agents if str(a).strip()}
                else:
                    agents_invoked = {a.strip() + "_agent" for a in agents_invoked_raw.split(",") if a.strip()}
            else:
                agents_invoked = set()

            for agent in all_agents:
                if agent in agents_invoked:
                    stages_log = _upsert_process(stages_log, "agent_orchestrator", agent, "pending")
                else:
                    stages_log = _upsert_process(
                        stages_log,
                        "agent_orchestrator",
                        agent,
                        "completed",
                        "Agent not invoked for this severity/risk combination",
                    )
            self._save(conn, "classified", stages_log)

            if "forensics_agent" in agents_invoked:
                stages_log = _upsert_process(
                    stages_log,
                    "agent_orchestrator",
                    "forensics_agent",
                    "running",
                    "ForensicsAgent collecting evidence…",
                )
            self._save(
                conn,
                "agent_running",
                stages_log,
                extra={
                    "investigation_id": investigation_id,
                    "investigation_status": investigation_row.get("status"),
                },
            )

            # ── Phase 5: watch agent_findings for per-agent completion ──────────
            _AGENT_TYPE_MAP = {
                "forensics": "forensics_agent",
                "investigation": "investigation_agent",
                "remediation": "remediation_agent",
            }
            seen_findings: set[str] = set()

            complete_deadline = time.monotonic() + AGENT_ORCH_TIMEOUT
            while time.monotonic() < complete_deadline:
                time.sleep(POLL_INTERVAL)

                investigation_row = self._poll_agent_investigation(conn, anomaly_id)
                findings = self._poll_agent_findings(conn, investigation_id)

                # Update stages_log for any new/updated findings
                for finding in findings:
                    agent_type = finding["agent_type"]
                    if not isinstance(agent_type, str) or not agent_type:
                        continue
                    process_key = _AGENT_TYPE_MAP.get(agent_type, agent_type)
                    finding_key = f"{agent_type}-{finding.get('status')}"

                    if finding_key not in seen_findings:
                        seen_findings.add(finding_key)
                        f_status = finding.get("status", "pending")
                        latency = finding.get("latency_ms")
                        detail = f"{agent_type.title()}Agent {f_status}"
                        if latency:
                            detail += f" ({latency}ms)"

                        proc_status = {
                            "pending": "pending",
                            "running": "running",
                            "complete": "completed",
                            "failed": "error",
                            "skipped": "completed",
                        }.get(f_status, f_status) or "pending"

                        stages_log = _upsert_process(stages_log, "agent_orchestrator", process_key, proc_status, detail)

                inv_status = investigation_row.get("status") if investigation_row else None
                self._save(
                    conn,
                    "agent_running",
                    stages_log,
                    extra={
                        "investigation_status": inv_status,
                    },
                )

                if inv_status in ("complete", "failed"):
                    final_stage = "complete" if inv_status == "complete" else "failed"
                    if final_stage == "complete":
                        self._mark_processed(conn, anomaly_id)
                    self._save(
                        conn,
                        final_stage,
                        stages_log,
                        extra={
                            "completed_at": datetime.now(timezone.utc),
                            "investigation_status": inv_status,
                        },
                    )
                    return

            # Deadline exceeded while agent orchestrator was still running
            self._save(
                conn,
                "failed",
                stages_log,
                extra={
                    "completed_at": datetime.now(timezone.utc),
                    "investigation_status": "timeout",
                },
            )

        finally:
            conn.close()
