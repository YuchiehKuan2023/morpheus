"""
Simulation routes — REST endpoints + SSE stream.

Endpoints:
    GET  /users          List available monitored users
    POST /start          Start a simulation run
    POST /stop           Stop the current run
    GET  /status         Current run status
    GET  /sessions       Recent sessions for a run (reconnect recovery)
    GET  /stream         SSE — real-time session updates
"""

import asyncio
import json
import logging
from datetime import datetime, timezone

import psycopg2
import psycopg2.extras
from auth_utils import get_current_user
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from simulation.simulation_manager import get_manager

from modules.utils.db import get_db_params

logger = logging.getLogger(__name__)

router = APIRouter()

SSE_POLL_INTERVAL = 2  # seconds between DB polls in the SSE generator
SSE_KEEPALIVE_INTERVAL = 15  # seconds between keepalive comments
SSE_DRAIN_WINDOW = 300  # seconds to keep streaming after run stops (lets in-flight trackers finish)


# ── DB helper ──────────────────────────────────────────────────────────────────


def _db_params() -> dict:
    return get_db_params()


def _row_to_session(row: dict) -> dict:
    """Serialise a simulation_sessions DB row to a JSON-safe dict."""

    def _iso(v):
        return v.isoformat() if v and hasattr(v, "isoformat") else v

    return {
        "session_id": str(row["session_id"]),
        "run_id": str(row["run_id"]),
        "user_id": row["user_id"],
        "event_type": row["event_type"],
        "scenario": row["scenario"],
        "sent_at": _iso(row["sent_at"]),
        "updated_at": _iso(row["updated_at"]),
        "stage": row["stage"],
        "anomaly_id": str(row["anomaly_id"]) if row["anomaly_id"] else None,
        "anomaly_score": row["anomaly_score"],
        "severity": row["severity"],
        "root_cause": row["root_cause"],
        "risk_score": row["risk_score"],
        "investigation_id": str(row["investigation_id"]) if row["investigation_id"] else None,
        "investigation_status": row["investigation_status"],
        "completed_at": _iso(row["completed_at"]),
        "stages_log": row["stages_log"] if isinstance(row["stages_log"], list) else [],
    }


def _sse_event(event_type: str, data: dict | list) -> str:
    """Format a server-sent event string."""
    return f"event: {event_type}\ndata: {json.dumps(data)}\n\n"


# ── GET /users ─────────────────────────────────────────────────────────────────


@router.get("/users")
def get_simulation_users(_user: dict = Depends(get_current_user)):
    """Return the list of all monitored users available for simulation."""
    try:
        with psycopg2.connect(**_db_params()) as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(
                    """
                    SELECT
                        mu.username                                                   AS user_id,
                        mu.display_name,
                        mu.avatar_initials,
                        mu.avatar_color,
                        mu.avatar_url,
                        COUNT(ea.anomaly_id) FILTER (WHERE ea.is_anomaly = true)              AS anomaly_count,
                        COUNT(ea.anomaly_id)                                                   AS total_events
                    FROM monitored_users mu
                    LEFT JOIN enriched_anomalies ea ON ea.user_id = mu.username
                    GROUP BY mu.username, mu.display_name, mu.avatar_initials,
                             mu.avatar_color, mu.avatar_url
                    ORDER BY anomaly_count DESC, mu.username ASC
                    """
                )
                rows = cur.fetchall()

        _colours = [
            "#6366f1",
            "#8b5cf6",
            "#ec4899",
            "#f59e0b",
            "#10b981",
            "#3b82f6",
            "#ef4444",
            "#14b8a6",
        ]

        users = []
        for row in rows:
            uid = row["user_id"]
            # Fall back to email-derived values only when monitored_users has no entry
            parts = uid.split("@")[0].split(".")
            display = row["display_name"] or " ".join(p.capitalize() for p in parts)
            initials = row["avatar_initials"] or "".join(p[0].upper() for p in parts[:2])
            colour = row["avatar_color"] or _colours[abs(hash(uid)) % len(_colours)]
            users.append(
                {
                    "user_id": uid,
                    "display_name": display,
                    "avatar_initials": initials,
                    "avatar_color": colour,
                    "avatar_url": row["avatar_url"],
                    "anomaly_count": row["anomaly_count"],
                    "total_events": row["total_events"],
                }
            )
        return users
    except Exception as exc:
        logger.error("Error fetching simulation users: %s", exc)
        raise HTTPException(status_code=500, detail="Database error") from exc


# ── POST /start ────────────────────────────────────────────────────────────────


class StartRequest(BaseModel):
    users: list[str]
    speed: str = "demo"


@router.post("/start")
def start_simulation(body: StartRequest, _user: dict = Depends(get_current_user)):
    if body.speed not in ("realistic", "fast", "demo"):
        raise HTTPException(status_code=400, detail="speed must be realistic | fast | demo")
    if not body.users:
        raise HTTPException(status_code=400, detail="at least one user is required")

    manager = get_manager()
    try:
        run_id = manager.start(users=body.users, speed=body.speed)
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    return {
        "run_id": str(run_id),
        "started_at": datetime.now(timezone.utc).isoformat(),
        "users": body.users,
        "speed": body.speed,
    }


# ── POST /stop ─────────────────────────────────────────────────────────────────


@router.post("/stop")
def stop_simulation(_user: dict = Depends(get_current_user)):
    manager = get_manager()
    summary = manager.stop()
    return summary


# ── GET /status ────────────────────────────────────────────────────────────────


@router.get("/status")
def simulation_status(_user: dict = Depends(get_current_user)):
    """Return manager status enriched with all-time DB totals."""
    data = dict(get_manager().status())
    try:
        with psycopg2.connect(**_db_params()) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT
                        COUNT(*)                                              AS total_sent,
                        COUNT(*) FILTER (WHERE event_type = 'novel')         AS total_anomalies,
                        COUNT(*) FILTER (WHERE event_type = 'clean')         AS total_clean
                    FROM simulation_sessions
                    """
                )
                row = cur.fetchone()
        data["total_sent"] = int(row[0])
        data["total_anomalies"] = int(row[1])
        data["total_clean"] = int(row[2])
    except Exception as exc:
        logger.warning("Could not fetch DB totals for status: %s", exc)
        data.setdefault("total_sent", 0)
        data.setdefault("total_anomalies", 0)
        data.setdefault("total_clean", 0)
    return data


# ── GET /sessions ──────────────────────────────────────────────────────────────


@router.get("/sessions")
def get_sessions(
    run_id: str | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=10, ge=1, le=50),
    tab: str = Query(default="all", pattern="^(all|anomalies|clean|in_progress)$"),
    _user: dict = Depends(get_current_user),
):
    """Return paginated sessions with category counts.

    Query params:
        run_id    - scope to a specific simulation run
        page      - 1-based page number
        page_size - items per page (10 when idle, 15 when running)
        tab       - filter: all | anomalies | clean | in_progress
    """
    terminal_stages = ("complete", "clean", "failed", "labeled")

    try:
        with psycopg2.connect(**_db_params()) as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                # Build WHERE clause fragments
                where_parts: list[str] = ["event_type IN ('novel', 'clean')"]
                params: list = []

                if run_id:
                    where_parts.append("run_id = %s")
                    params.append(run_id)

                base_where = ("WHERE " + " AND ".join(where_parts)) if where_parts else ""

                # ── Counts (single query, all categories) ────────────────
                cur.execute(
                    f"""
                    SELECT
                        COUNT(*)                                                              AS total,
                        COUNT(*) FILTER (WHERE anomaly_id IS NOT NULL)                       AS anomalies,
                        COUNT(*) FILTER (WHERE stage IN %s AND anomaly_id IS NULL)           AS clean,
                        COUNT(*) FILTER (WHERE stage NOT IN %s)                              AS in_progress
                    FROM simulation_sessions
                    {base_where}
                    """,
                    [terminal_stages, terminal_stages, *params],
                )
                counts_row = dict(cur.fetchone())
                counts = {
                    "all": int(counts_row["total"]),
                    "anomalies": int(counts_row["anomalies"]),
                    "clean": int(counts_row["clean"]),
                    "in_progress": int(counts_row["in_progress"]),
                }

                # ── Tab filter ───────────────────────────────────────────
                tab_parts = list(where_parts)  # copy base filters
                tab_params = list(params)

                if tab == "anomalies":
                    tab_parts.append("anomaly_id IS NOT NULL")
                elif tab == "clean":
                    tab_parts.append("stage IN %s")
                    tab_params.append(terminal_stages)
                    tab_parts.append("anomaly_id IS NULL")
                elif tab == "in_progress":
                    tab_parts.append("stage NOT IN %s")
                    tab_params.append(terminal_stages)

                tab_where = ("WHERE " + " AND ".join(tab_parts)) if tab_parts else ""

                # ── Total for current tab (for pagination math) ──────────
                filtered_total = counts[tab]

                # ── Paginated rows ───────────────────────────────────────
                offset = (page - 1) * page_size
                cur.execute(
                    f"""
                    SELECT * FROM simulation_sessions
                    {tab_where}
                    ORDER BY sent_at DESC
                    LIMIT %s OFFSET %s
                    """,
                    [*tab_params, page_size, offset],
                )
                rows = cur.fetchall()

        import math

        total_pages = max(1, math.ceil(filtered_total / page_size))

        return {
            "items": [_row_to_session(dict(r)) for r in rows],
            "counts": counts,
            "page": page,
            "pageSize": page_size,
            "totalItems": filtered_total,
            "totalPages": total_pages,
        }
    except Exception as exc:
        logger.error("Error fetching simulation sessions: %s", exc)
        raise HTTPException(status_code=500, detail="Database error") from exc


# ── GET /stream  (SSE) ─────────────────────────────────────────────────────────


@router.get("/stream")
async def simulation_stream(run_id: str | None = Query(default=None), _user: dict = Depends(get_current_user)):
    """
    Server-sent events stream.

    On connect:
      1. Sends a 'snapshot' event with all current sessions for the run.
      2. Every SSE_POLL_INTERVAL seconds: sends 'session_update' for any row
         whose updated_at > last_poll.
      3. Every SSE_KEEPALIVE_INTERVAL seconds: sends a keepalive comment.
      4. When the run is stopped: sends 'run_stopped' and widens the scope to
         all sessions so in-flight stage trackers continue to update the feed.
      5. After SSE_DRAIN_WINDOW seconds (or when the frontend disconnects):
         sends 'run_complete' and closes.
    """
    manager = get_manager()

    # Resolve run_id: use provided, or fall back to current manager run
    effective_run_id = run_id or (str(manager.run_id) if manager.run_id else None)

    async def event_generator():
        nonlocal effective_run_id
        last_poll = datetime.now(timezone.utc)
        last_keepalive = last_poll
        drain_started_at: datetime | None = None
        completed_run_id: str | None = effective_run_id  # captured when drain begins; see run_complete
        db_params = _db_params()

        # ── Snapshot ────────────────────────────────────────────────────────────
        try:
            conn = await asyncio.get_event_loop().run_in_executor(None, lambda: psycopg2.connect(**db_params))
            try:
                with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                    if effective_run_id:
                        cur.execute(
                            "SELECT * FROM simulation_sessions WHERE run_id = %s ORDER BY sent_at DESC",
                            (effective_run_id,),
                        )
                    else:
                        cur.execute(
                            "SELECT * FROM simulation_sessions WHERE event_type IN ('novel', 'clean') ORDER BY sent_at DESC LIMIT 100"
                        )
                    snapshot_rows = [_row_to_session(dict(r)) for r in cur.fetchall()]
            finally:
                conn.close()

            yield _sse_event("snapshot", {"sessions": snapshot_rows, "run_id": effective_run_id})
        except Exception as exc:
            logger.error("SSE snapshot error: %s", exc)
            yield _sse_event("error", {"detail": "Snapshot failed"})
            return

        # ── Polling loop ────────────────────────────────────────────────────────
        while True:
            await asyncio.sleep(SSE_POLL_INTERVAL)
            now = datetime.now(timezone.utc)

            # Keepalive comment
            if (now - last_keepalive).total_seconds() >= SSE_KEEPALIVE_INTERVAL:
                yield ": keepalive\n\n"
                last_keepalive = now

            # Updated sessions
            try:
                conn = await asyncio.get_event_loop().run_in_executor(None, lambda: psycopg2.connect(**db_params))
                try:
                    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                        if effective_run_id:
                            cur.execute(
                                """
                                SELECT * FROM simulation_sessions
                                WHERE run_id = %s AND updated_at > %s
                                ORDER BY updated_at ASC
                                """,
                                (effective_run_id, last_poll),
                            )
                        else:
                            cur.execute(
                                """
                                SELECT * FROM simulation_sessions
                                WHERE updated_at > %s
                                  AND event_type IN ('novel', 'clean')
                                ORDER BY updated_at ASC
                                LIMIT 100
                                """,
                                (last_poll,),
                            )
                        updated_rows = [_row_to_session(dict(r)) for r in cur.fetchall()]
                finally:
                    conn.close()
            except Exception as exc:
                logger.error("SSE poll error: %s", exc)
                updated_rows = []

            for session in updated_rows:
                yield _sse_event("session_update", session)

            last_poll = now

            # Status update every poll
            status = manager.status()
            yield _sse_event("status_update", status)

            # Run stopped / drain logic
            if not status["running"]:
                if drain_started_at is None:
                    # First poll after stop: notify frontend and widen to all sessions
                    # so in-flight stage trackers continue feeding updates.
                    drain_started_at = now
                    completed_run_id = effective_run_id  # capture before clearing scope
                    yield _sse_event("run_stopped", {"run_id": effective_run_id, "summary": status})
                    effective_run_id = None  # unscoped polling from here on
                elif (now - drain_started_at).total_seconds() >= SSE_DRAIN_WINDOW:
                    yield _sse_event("run_complete", {"run_id": completed_run_id, "summary": status})
                    return

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )
