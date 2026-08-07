import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

import psycopg2.extras
from auth_utils import get_current_user
from db import get_db
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

sys.path.append(str(Path(__file__).resolve().parents[3]))

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("")
def get_anomalies(limit: int = Query(default=100, ge=1, le=1000), _user: dict = Depends(get_current_user)):
    try:
        with get_db() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(
                    """
                    SELECT
                        anomaly_id,
                        user_id,
                        timestamp,
                        anomaly_score,
                        severity,
                        root_cause,
                        sub_category,
                        risk_score,
                        is_anomaly,
                        status,
                        original_event,
                        ai_enrichment,
                        created_at
                    FROM enriched_anomalies
                    ORDER BY timestamp DESC
                    LIMIT %s
                    """,
                    (limit,),
                )
                rows = cur.fetchall()
                return [
                    {
                        **dict(r),
                        "anomaly_id": str(r["anomaly_id"]),
                        "timestamp": r["timestamp"].isoformat() if r["timestamp"] else None,
                        "created_at": r["created_at"].isoformat() if r["created_at"] else None,
                    }
                    for r in rows
                ]
    except Exception as e:
        logger.error(f"Error fetching anomalies: {e}")
        raise HTTPException(status_code=500, detail="Database error") from e


@router.get("/queue/my")
def get_my_queue(
    limit: int = Query(default=100, ge=1, le=1000),
    user: dict = Depends(get_current_user),
):
    """Anomalies assigned to current analyst."""
    try:
        with get_db() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(
                    """SELECT anomaly_id, user_id, timestamp, anomaly_score, severity,
                              root_cause, sub_category, risk_score, is_anomaly, status,
                              analyst_verdict, reviewed_at, created_at
                       FROM enriched_anomalies
                       WHERE assigned_to = %s
                       ORDER BY
                           CASE WHEN status = 'pending' THEN 0
                                WHEN status = 'resolved' THEN 1
                                ELSE 2
                           END,
                           risk_score DESC NULLS LAST,
                           timestamp DESC
                       LIMIT %s""",
                    (user["id"], limit),
                )
                rows = cur.fetchall()
                return [
                    {
                        **dict(r),
                        "anomaly_id": str(r["anomaly_id"]),
                        "timestamp": r["timestamp"].isoformat() if r["timestamp"] else None,
                        "created_at": r["created_at"].isoformat() if r["created_at"] else None,
                        "reviewed_at": r["reviewed_at"].isoformat() if r.get("reviewed_at") else None,
                    }
                    for r in rows
                ]
    except Exception as e:
        logger.error(f"Error fetching my queue: {e}")
        raise HTTPException(status_code=500, detail="Database error") from e


@router.get("/queue/unassigned")
def get_unassigned(limit: int = Query(default=100, ge=1, le=1000), _user: dict = Depends(get_current_user)):
    """Anomalies with no analyst, sorted by risk score desc."""
    try:
        with get_db() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(
                    """SELECT anomaly_id, user_id, timestamp, anomaly_score, severity,
                              root_cause, sub_category, risk_score, is_anomaly, status,
                              created_at
                       FROM enriched_anomalies
                       WHERE assigned_to IS NULL AND status = 'new'
                       ORDER BY risk_score DESC NULLS LAST, timestamp DESC
                       LIMIT %s""",
                    (limit,),
                )
                rows = cur.fetchall()
                return [
                    {
                        **dict(r),
                        "anomaly_id": str(r["anomaly_id"]),
                        "timestamp": r["timestamp"].isoformat() if r["timestamp"] else None,
                        "created_at": r["created_at"].isoformat() if r["created_at"] else None,
                    }
                    for r in rows
                ]
    except Exception as e:
        logger.error(f"Error fetching unassigned queue: {e}")
        raise HTTPException(status_code=500, detail="Database error") from e


@router.get("/{anomaly_id}")
def get_anomaly(anomaly_id: str, _user: dict = Depends(get_current_user)):
    try:
        with get_db() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(
                    """
                    SELECT
                        ea.*,
                        le.context_analysis,
                        le.pattern_analysis,
                        le.risk_assessment,
                        le.recommendations,
                        le.reasoning_process,
                        le.evidence_summary,
                        le.entities_referenced,
                        le.confidence_score       AS llm_confidence,
                        le.anomaly_classification,
                        le.severity_level         AS llm_severity_level,
                        le.model_name,
                        le.completion_tokens,
                        le.created_at             AS explanation_created_at,
                        mu.display_name           AS user_display_name,
                        mu.first_name             AS user_first_name,
                        mu.last_name              AS user_last_name,
                        mu.email                  AS user_email,
                        mu.job_title              AS user_job_title,
                        mu.department             AS user_department,
                        mu.company                AS user_company,
                        mu.seniority              AS user_seniority,
                        mu.user_role              AS user_role,
                        mu.avatar_url             AS user_avatar_url,
                        mu.avatar_initials        AS user_avatar_initials,
                        mu.avatar_color           AS user_avatar_color,
                        mu.primary_location_city  AS user_city,
                        mu.primary_location_country AS user_country
                    FROM enriched_anomalies ea
                    LEFT JOIN monitored_users mu ON mu.username = ea.user_id
                    LEFT JOIN LATERAL (
                        SELECT *
                        FROM llm_explanations
                        WHERE detection_id = ea.anomaly_id
                        ORDER BY version DESC, created_at DESC
                        LIMIT 1
                    ) le ON true
                    WHERE ea.anomaly_id = %s
                    """,
                    (anomaly_id,),
                )
                row = cur.fetchone()
                if not row:
                    raise HTTPException(status_code=404, detail="Anomaly not found")
                d = dict(row)
                d["anomaly_id"] = str(d["anomaly_id"])
                for ts_col in (
                    "timestamp",
                    "created_at",
                    "updated_at",
                    "classified_at",
                    "validated_at",
                    "explanation_created_at",
                ):
                    if d.get(ts_col):
                        d[ts_col] = d[ts_col].isoformat()
                return d
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching anomaly {anomaly_id}: {e}")
        raise HTTPException(status_code=500, detail="Database error") from e


@router.get("/{anomaly_id}/investigation")
def get_anomaly_investigation(anomaly_id: str, _user: dict = Depends(get_current_user)):
    """Latest investigation for an anomaly, with all agent findings nested."""
    try:
        with get_db() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(
                    """
                    SELECT
                        ai.investigation_id,
                        ai.triggered_at,
                        ai.completed_at,
                        ai.status,
                        ai.severity_at_trigger,
                        ai.agents_invoked,
                        ai.confidence_score,
                        ai.overall_recommendation,
                        au.username         AS analyst_username,
                        au.display_name     AS analyst_display_name,
                        au.first_name       AS analyst_first_name,
                        au.last_name        AS analyst_last_name,
                        au.email            AS analyst_email,
                        au.analyst_role     AS analyst_role,
                        au.level            AS analyst_level,
                        au.avatar_url       AS analyst_avatar_url,
                        au.avatar_initials  AS analyst_avatar_initials,
                        au.avatar_color     AS analyst_avatar_color,
                        COALESCE(
                            json_agg(
                                json_build_object(
                                    'agent_type', af.agent_type,
                                    'status', af.status,
                                    'result', af.result,
                                    'latency_ms', af.latency_ms,
                                    'completed_at', af.completed_at
                                ) ORDER BY af.started_at
                            ) FILTER (WHERE af.finding_id IS NOT NULL),
                            '[]'::json
                        ) AS findings
                    FROM agent_investigations ai
                    LEFT JOIN enriched_anomalies ea ON ea.anomaly_id = ai.anomaly_id
                    LEFT JOIN analyst_users au ON au.id = ea.assigned_to
                    LEFT JOIN agent_findings af ON af.investigation_id = ai.investigation_id
                    WHERE ai.anomaly_id = %s
                    GROUP BY
                        ai.investigation_id,
                        au.username, au.display_name, au.first_name, au.last_name,
                        au.email, au.analyst_role, au.level,
                        au.avatar_url, au.avatar_initials, au.avatar_color
                    ORDER BY ai.triggered_at DESC
                    LIMIT 1
                    """,
                    (anomaly_id,),
                )
                row = cur.fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="No investigation found for this anomaly")
        result = dict(row)
        result["investigation_id"] = str(result["investigation_id"])
        if result.get("triggered_at"):
            result["triggered_at"] = result["triggered_at"].isoformat()
        if result.get("completed_at"):
            result["completed_at"] = result["completed_at"].isoformat()

        # Build nested assigned_analyst object and remove flat analyst columns
        analyst_username = result.pop("analyst_username", None)
        result["assigned_analyst"] = (
            {
                "user_id": analyst_username,
                "display_name": result.pop("analyst_display_name", None),
                "first_name": result.pop("analyst_first_name", None),
                "last_name": result.pop("analyst_last_name", None),
                "email": result.pop("analyst_email", None),
                "role": result.pop("analyst_role", None),
                "level": result.pop("analyst_level", None),
                "avatar_url": result.pop("analyst_avatar_url", None),
                "avatar_initials": result.pop("analyst_avatar_initials", None),
                "avatar_color": result.pop("analyst_avatar_color", None),
            }
            if analyst_username
            else None
        )
        # Clean up any remaining flat keys if analyst was None
        result.pop("analyst_display_name", None)
        result.pop("analyst_first_name", None)
        result.pop("analyst_last_name", None)
        result.pop("analyst_email", None)
        result.pop("analyst_role", None)
        result.pop("analyst_level", None)
        result.pop("analyst_avatar_url", None)
        result.pop("analyst_avatar_initials", None)
        result.pop("analyst_avatar_color", None)

        return result
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching investigation for anomaly {anomaly_id}: {e}")
        raise HTTPException(status_code=500, detail="Database error") from e


@router.get("/{anomaly_id}/explanation")
def get_anomaly_explanation(anomaly_id: str, _user: dict = Depends(get_current_user)):
    """
    SHAP + LIME + confidence score for an anomaly.

    Returns pre-computed SHAP values from risk_factors JSONB, LIME local
    explanation computed on-demand, and the ensemble confidence score.
    """
    try:
        from services.explainability_service import get_explanation

        with get_db() as conn:
            result = get_explanation(anomaly_id, conn)
        return result
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except Exception as e:
        logger.error(f"Error generating explanation for anomaly {anomaly_id}: {e}")
        raise HTTPException(status_code=500, detail="Explanation generation error") from e


@router.post("/{anomaly_id}/retrigger")
def retrigger_investigation(anomaly_id: str, _user: dict = Depends(get_current_user)):
    """Re-trigger agent investigation for an anomaly.

    Mode A — repair: If a complete investigation already exists in the DB the
    stage tracker thread is long gone, so we patch simulation_sessions
    stages_log directly from the actual findings.  The SSE poll picks up the
    updated_at change within seconds and the UI refreshes automatically.

    Mode B — re-publish: No complete investigation exists.  Delete any
    failed/error investigation rows then re-publish to dfp-agent-tasks so the
    agent orchestrator creates a fresh investigation.
    """
    import json
    import os
    from datetime import datetime, timezone

    from confluent_kafka import Producer

    _AGENT_TYPE_MAP = {
        "forensics": "forensics_agent",
        "investigation": "investigation_agent",
        "remediation": "remediation_agent",
    }
    _STATUS_MAP = {"complete": "completed", "failed": "error", "skipped": "completed"}

    row = None
    mode_b_needed = True  # whether a Kafka re-publish is required

    try:
        with get_db() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(
                    "SELECT anomaly_id, severity, risk_score, root_cause FROM enriched_anomalies WHERE anomaly_id = %s",
                    (anomaly_id,),
                )
                row = cur.fetchone()
                if not row:
                    raise HTTPException(status_code=404, detail="Anomaly not found")

                # Check for the most recent investigation
                cur.execute(
                    """
                    SELECT investigation_id, status
                    FROM agent_investigations
                    WHERE anomaly_id = %s
                    ORDER BY triggered_at DESC
                    LIMIT 1
                    """,
                    (anomaly_id,),
                )
                inv_row = cur.fetchone()

                if inv_row and inv_row["status"] == "complete":
                    # Mode A: investigation already finished — the stage tracker
                    # timed out before it could see this result.  Patch the
                    # stages_log in simulation_sessions directly.
                    cur.execute(
                        """
                        SELECT agent_type, status, latency_ms
                        FROM agent_findings
                        WHERE investigation_id = %s
                        ORDER BY started_at ASC
                        """,
                        (str(inv_row["investigation_id"]),),
                    )
                    findings = list(cur.fetchall())

                    cur.execute(
                        "SELECT session_id, stages_log FROM simulation_sessions WHERE anomaly_id = %s",
                        (anomaly_id,),
                    )
                    sim_row = cur.fetchone()

                    if sim_row:
                        stages_log = sim_row["stages_log"]
                        if isinstance(stages_log, str):
                            stages_log = json.loads(stages_log)
                        elif stages_log is None:
                            stages_log = []

                        now_iso = datetime.now(timezone.utc).isoformat()
                        for finding in findings:
                            agent_type = finding["agent_type"]
                            process_key = _AGENT_TYPE_MAP.get(agent_type, agent_type)
                            f_status = finding["status"]
                            latency = finding["latency_ms"]
                            detail = f"{agent_type.title()}Agent {f_status}"
                            if latency:
                                detail += f" ({latency}ms)"
                            proc_status = _STATUS_MAP.get(f_status, f_status)

                            patched = False
                            for entry in stages_log:
                                if entry.get("group") == "agent_orchestrator" and entry.get("process") == process_key:
                                    entry["status"] = proc_status
                                    entry["detail"] = detail
                                    entry["ts"] = now_iso
                                    patched = True
                                    break
                            if not patched:
                                stages_log.append(
                                    {
                                        "group": "agent_orchestrator",
                                        "process": process_key,
                                        "status": proc_status,
                                        "detail": detail,
                                        "ts": now_iso,
                                    }
                                )

                        cur.execute(
                            """
                            UPDATE simulation_sessions
                            SET stage = 'complete', stages_log = %s, updated_at = %s
                            WHERE session_id = %s
                            """,
                            (
                                json.dumps(stages_log),
                                datetime.now(timezone.utc),
                                str(sim_row["session_id"]),
                            ),
                        )
                        mode_b_needed = False
                        logger.info(
                            "Repaired stages_log for anomaly %s session %s",
                            anomaly_id,
                            sim_row["session_id"],
                        )
                else:
                    # Mode B: no complete investigation — delete failed/error rows
                    # so a fresh one is created after re-publish.
                    cur.execute(
                        "DELETE FROM agent_investigations WHERE anomaly_id = %s AND status IN ('failed', 'error')",
                        (anomaly_id,),
                    )

            conn.commit()
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"DB error during retrigger for {anomaly_id}: {e}")
        raise HTTPException(status_code=500, detail="Database error") from e

    if not mode_b_needed:
        return {"status": "ok", "anomaly_id": anomaly_id, "repaired": True}

    try:
        bootstrap = os.getenv("KAFKA_BOOTSTRAP_SERVERS", "127.0.0.1:29092")
        producer = Producer({"bootstrap.servers": bootstrap})
        payload = json.dumps(
            {
                "anomaly_id": str(row["anomaly_id"]),
                "severity": row["severity"],
                "risk_score": float(row["risk_score"] or 0),
                "root_cause": row["root_cause"] or "Unknown",
            }
        ).encode()
        producer.produce(topic="dfp-agent-tasks", key=str(row["anomaly_id"]).encode(), value=payload)
        producer.flush(timeout=5)
        logger.info("Retrigger published for anomaly %s", anomaly_id)
    except Exception as e:
        logger.error(f"Kafka publish failed during retrigger for {anomaly_id}: {e}")
        raise HTTPException(status_code=502, detail="Failed to publish retrigger message") from e

    return {"status": "ok", "anomaly_id": anomaly_id, "repaired": False}


# ── Pipeline history ─────────────────────────────────────────────────────────


@router.get("/{anomaly_id}/pipeline")
def get_pipeline(anomaly_id: str, _user: dict = Depends(get_current_user)):
    """Return the stages_log from the most recent simulation_sessions row for this anomaly."""
    try:
        with get_db() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(
                    """SELECT stage, stages_log
                       FROM simulation_sessions
                       WHERE anomaly_id = %s
                       ORDER BY updated_at DESC
                       LIMIT 1""",
                    (anomaly_id,),
                )
                row = cur.fetchone()
        if not row:
            return {"stage": None, "stages_log": []}
        stages_log = row.get("stages_log")
        if isinstance(stages_log, str):
            stages_log = json.loads(stages_log)
        elif not isinstance(stages_log, list):
            stages_log = []
        return {
            "stage": row["stage"],
            "stages_log": stages_log,
        }
    except Exception as e:
        logger.error("Error fetching pipeline for %s: %s", anomaly_id, e)
        raise HTTPException(status_code=500, detail="Database error") from e


# ── Re-orchestration ─────────────────────────────────────────────────────────


@router.post("/{anomaly_id}/reorchestrate")
def start_reorchestration(anomaly_id: str, _user: dict = Depends(get_current_user)):
    """Kick off the full AI pipeline on an existing unprocessed anomaly."""
    from services.reorchestration_service import reorchestrate_anomaly

    try:
        result = reorchestrate_anomaly(anomaly_id)
    except LookupError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e)) from e
    except Exception as e:
        logger.error("Reorchestration failed for %s: %s", anomaly_id, e)
        raise HTTPException(status_code=500, detail="Reorchestration failed") from e

    return result


@router.get("/{anomaly_id}/reorchestrate/stream")
async def reorchestrate_stream(
    anomaly_id: str,
    session_id: str = Query(...),
    _user: dict = Depends(get_current_user),
):
    """SSE stream for a single re-orchestration session."""
    import asyncio
    import json

    import psycopg2.extras

    from modules.utils.db import get_db_params

    _POLL = 2
    _KEEPALIVE = 15
    _TIMEOUT = 600  # max stream lifetime

    def _iso(v):
        return v.isoformat() if v and hasattr(v, "isoformat") else v

    def _decode_stages_log(raw):
        if isinstance(raw, list):
            return raw
        if isinstance(raw, str):
            return json.loads(raw)
        return []

    def _row_to_session(row: dict) -> dict:
        return {
            "session_id": str(row["session_id"]),
            "run_id": str(row["run_id"]),
            "user_id": row["user_id"],
            "event_type": row["event_type"],
            "scenario": row.get("scenario"),
            "sent_at": _iso(row["sent_at"]),
            "updated_at": _iso(row["updated_at"]),
            "stage": row["stage"],
            "anomaly_id": str(row["anomaly_id"]) if row["anomaly_id"] else None,
            "anomaly_score": row.get("anomaly_score"),
            "severity": row.get("severity"),
            "root_cause": row.get("root_cause"),
            "risk_score": row.get("risk_score"),
            "investigation_id": str(row["investigation_id"]) if row.get("investigation_id") else None,
            "investigation_status": row.get("investigation_status"),
            "completed_at": _iso(row.get("completed_at")),
            "stages_log": _decode_stages_log(row.get("stages_log")),
        }

    def _sse(event_type: str, data: dict) -> str:
        return f"event: {event_type}\ndata: {json.dumps(data)}\n\n"

    db_params = get_db_params()

    async def event_generator():
        started = asyncio.get_event_loop().time()
        last_keepalive = started

        while (asyncio.get_event_loop().time() - started) < _TIMEOUT:
            await asyncio.sleep(_POLL)
            now = asyncio.get_event_loop().time()

            if (now - last_keepalive) >= _KEEPALIVE:
                yield ": keepalive\n\n"
                last_keepalive = now

            try:
                conn = await asyncio.get_event_loop().run_in_executor(None, lambda: psycopg2.connect(**db_params))
                try:
                    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                        cur.execute(
                            """SELECT *
                               FROM simulation_sessions
                               WHERE session_id = %s
                                 AND anomaly_id = %s
                                 AND event_type = 'reorchestration'""",
                            (session_id, anomaly_id),
                        )
                        row = cur.fetchone()
                finally:
                    conn.close()
            except Exception as exc:
                logger.error("Reorchestrate SSE poll error: %s", exc)
                continue

            if not row:
                continue

            session = _row_to_session(dict(row))
            yield _sse("session_update", session)

            if session["stage"] in ("complete", "failed", "clean"):
                yield _sse("reorchestrate_complete", session)
                return

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


class ReviewBody(BaseModel):
    verdict: str
    analyst_notes: str
    resolution_notes: str


# ── Helper: create notification ──────────────────────────────────────────────


def _create_notification(
    conn,
    analyst_id: int,
    anomaly_id: str,
    notification_type: str,
    title: str,
    message: str | None = None,
) -> None:
    """Insert a row into analyst_notifications."""
    with conn.cursor() as cur:
        cur.execute(
            """INSERT INTO analyst_notifications (analyst_id, anomaly_id, type, title, message)
               VALUES (%s, %s, %s, %s, %s)""",
            (analyst_id, anomaly_id, notification_type, title, message),
        )


# ── Analyst review endpoints ─────────────────────────────────────────────────


@router.post("/{anomaly_id}/assign")
def assign_anomaly(anomaly_id: str, user: dict = Depends(get_current_user)):
    """Self-assign an anomaly to the current analyst."""
    try:
        with get_db() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(
                    "SELECT anomaly_id, assigned_to, status, severity, user_id FROM enriched_anomalies WHERE anomaly_id = %s",
                    (anomaly_id,),
                )
                row = cur.fetchone()
                if not row:
                    raise HTTPException(status_code=404, detail="Anomaly not found")
                if row["assigned_to"] is not None and row["assigned_to"] != user["id"]:
                    raise HTTPException(status_code=409, detail="Anomaly already assigned to another analyst")

                cur.execute(
                    """UPDATE enriched_anomalies
                       SET assigned_to = %s,
                           status = CASE WHEN status = 'new' THEN 'pending' ELSE status END,
                           updated_at = %s
                       WHERE anomaly_id = %s""",
                    (user["id"], datetime.now(timezone.utc), anomaly_id),
                )
                _create_notification(
                    conn,
                    analyst_id=user["id"],
                    anomaly_id=anomaly_id,
                    notification_type="anomaly_assigned",
                    title=f"Anomaly assigned: {row['severity'] or 'UNKNOWN'} — {row['user_id']}",
                    message=f"You have been assigned anomaly {anomaly_id[:8]}… for user {row['user_id']}.",
                )
            conn.commit()
        return {"status": "ok", "anomaly_id": anomaly_id, "assigned_to": user["id"]}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error assigning anomaly {anomaly_id}: {e}")
        raise HTTPException(status_code=500, detail="Database error") from e


@router.post("/{anomaly_id}/review")
def review_anomaly(anomaly_id: str, body: ReviewBody, user: dict = Depends(get_current_user)):
    """Submit analyst verdict for an anomaly."""
    valid_verdicts = {"confirmed", "false_positive", "escalated", "dismissed"}
    if body.verdict not in valid_verdicts:
        raise HTTPException(
            status_code=422, detail=f"Invalid verdict. Must be one of: {', '.join(sorted(valid_verdicts))}"
        )

    try:
        now = datetime.now(timezone.utc)
        with get_db() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(
                    """SELECT anomaly_id, root_cause, is_anomaly, status,
                              analyst_verdict, original_event, anomaly_score, user_id
                       FROM enriched_anomalies WHERE anomaly_id = %s""",
                    (anomaly_id,),
                )
                row = cur.fetchone()
                if not row:
                    raise HTTPException(status_code=404, detail="Anomaly not found")

                previous_verdict = row.get("analyst_verdict")

                # All verdicts lead to resolved status.
                # The verdict itself (confirmed/false_positive/escalated/dismissed)
                # is stored in analyst_verdict. Status only tracks workflow state.
                new_status = "resolved"

                # If verdict disagrees with AI (is_anomaly), flag for retraining
                ai_says_anomaly = row["is_anomaly"]
                disagreement = False
                if ai_says_anomaly is not None:
                    if body.verdict == "false_positive" and ai_says_anomaly is True:
                        disagreement = True
                    elif body.verdict == "confirmed" and ai_says_anomaly is False:
                        disagreement = True

                update_fields = {
                    "analyst_verdict": body.verdict,
                    "analyst_notes": body.analyst_notes,
                    "resolution_notes": body.resolution_notes,
                    "reviewed_by": user["id"],
                    "reviewed_at": now,
                    "status": new_status,
                    "updated_at": now,
                }
                # All verdicts are terminal — set resolved_at
                update_fields["resolved_at"] = now

                set_clause = ", ".join(f"{k} = %({k})s" for k in update_fields)
                update_fields["anomaly_id"] = anomaly_id

                cur.execute(
                    f"UPDATE enriched_anomalies SET {set_clause} WHERE anomaly_id = %(anomaly_id)s",
                    update_fields,
                )

                # ── Feedback loop: sync user_training_events ──────────────
                # If AI originally labelled this as false_positive, a feedback
                # training event was auto-inserted.  When the analyst overrides
                # to confirmed/escalated, remove that event so the model doesn't
                # train on a true anomaly.  Conversely, if the analyst now says
                # false_positive but the AI said true anomaly, add the event.
                was_fp = previous_verdict == "false_positive" or (
                    previous_verdict is None and row.get("is_anomaly") is False
                )
                now_fp = body.verdict == "false_positive"

                if was_fp and not now_fp:
                    # Remove the feedback training event
                    cur.execute(
                        "DELETE FROM user_training_events WHERE anomaly_id = %s AND source = 'feedback'",
                        (anomaly_id,),
                    )
                    logger.info(f"Removed feedback training event for {anomaly_id} (analyst override)")
                elif now_fp and not was_fp:
                    # Add the original event as a feedback training event
                    # and check the DFP retrain threshold via DFPFeedbackService.
                    # Use a separate connection so the feedback service's internal
                    # commit() does not prematurely commit the review transaction.
                    try:
                        from modules.ai.auto_labeling.dfp_feedback_service import DFPFeedbackService

                        feedback_svc = DFPFeedbackService()
                        with get_db() as feedback_conn:
                            triggered = feedback_svc.add_false_positive(
                                {
                                    "anomaly_id": anomaly_id,
                                    "user_id": row["user_id"],
                                    "original_event": row.get("original_event"),
                                    "anomaly_score": row.get("anomaly_score"),
                                },
                                db_conn=feedback_conn,
                            )
                        if triggered:
                            logger.info(f"DFP retrain job triggered for user {row['user_id']} (analyst false_positive)")
                        else:
                            logger.info(f"Added feedback training event for {anomaly_id} (analyst false_positive)")
                    except Exception:
                        logger.exception(f"Failed to record feedback for {anomaly_id} via DFPFeedbackService")
            conn.commit()

        return {
            "status": "ok",
            "anomaly_id": anomaly_id,
            "verdict": body.verdict,
            "new_status": new_status,
            "disagreement": disagreement,
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error reviewing anomaly {anomaly_id}: {e}")
        raise HTTPException(status_code=500, detail="Database error") from e
