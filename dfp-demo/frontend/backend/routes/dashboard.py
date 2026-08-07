import logging
import os
import threading
import time

import psycopg2.extras
from auth_utils import get_current_user
from db import get_db
from fastapi import APIRouter, Depends, HTTPException

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# In-memory cache for the /snapshot endpoint
# ---------------------------------------------------------------------------
_snapshot_cache: dict | None = None
_snapshot_cache_ts: float = 0.0
_snapshot_lock = threading.Lock()
SNAPSHOT_TTL = 15  # seconds

router = APIRouter()


@router.get("/stats")
def get_stats(_user: dict = Depends(get_current_user)):
    try:
        with get_db() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT
                        (SELECT COUNT(*) FROM monitored_users) AS total_users,
                        (SELECT COUNT(*) FROM user_training_events) + (SELECT COUNT(*) FROM enriched_anomalies) AS total_events,
                        (SELECT COUNT(*) FROM enriched_anomalies) AS total_anomalies,
                        (SELECT COUNT(DISTINCT user_id) FROM enriched_anomalies) AS active_users,
                        (SELECT COUNT(*) FROM enriched_anomalies WHERE severity = 'CRITICAL') AS critical_anomalies,
                        (SELECT COUNT(*) FROM enriched_anomalies WHERE severity = 'HIGH') AS high_anomalies,
                        (SELECT COUNT(*) FROM enriched_anomalies WHERE severity = 'MEDIUM') AS medium_anomalies,
                        (SELECT COUNT(*) FROM enriched_anomalies WHERE severity = 'LOW') AS low_anomalies,
                        (SELECT ROUND(COALESCE(AVG(anomaly_score), 0)::numeric, 4) FROM enriched_anomalies) AS avg_anomaly_score,
                        (SELECT COUNT(*) FROM enriched_anomalies WHERE status = 'new') AS new_anomalies,
                        (SELECT COUNT(*) FROM enriched_anomalies WHERE status = 'resolved') AS resolved_anomalies,
                        (SELECT COUNT(*) FROM enriched_anomalies WHERE status = 'pending') AS pending_anomalies
                """)
                row = cur.fetchone()
                return {
                    "totalUsers": int(row[0]),
                    "totalEvents": int(row[1]),
                    "totalAnomalies": int(row[2]),
                    "activeUsers": int(row[3]),
                    "anomalies": {
                        "critical": int(row[4]),
                        "high": int(row[5]),
                        "medium": int(row[6]),
                        "low": int(row[7]),
                        "new": int(row[9]),
                        "resolved": int(row[10]),
                        "pending": int(row[11]),
                    },
                    "avgAnomalyScore": float(row[8]),
                }
    except Exception as e:
        logger.error(f"Error fetching stats: {e}")
        raise HTTPException(status_code=500, detail="Database error") from e


@router.get("/recent-anomalies")
def get_recent_anomalies(_user: dict = Depends(get_current_user)):
    """10 most recent anomalies joined with monitored_users."""
    try:
        with get_db() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute("""
                    SELECT
                        ea.anomaly_id,
                        ea.user_id,
                        ea.timestamp,
                        ea.anomaly_score,
                        LOWER(ea.severity)  AS severity,
                        ea.root_cause,
                        ea.sub_category,
                        ea.risk_score,
                        ea.status,
                        ea.original_event,
                        mu.display_name,
                        mu.avatar_color,
                        mu.avatar_initials,
                        mu.avatar_url,
                        mu.company,
                        mu.department,
                        mu.devices,
                        mu.apps,
                        mu.all_locations
                    FROM enriched_anomalies ea
                    LEFT JOIN monitored_users mu ON mu.username = ea.user_id
                    ORDER BY ea.timestamp DESC
                    LIMIT 10
                """)
                rows = cur.fetchall()
                return [
                    {
                        **dict(r),
                        "anomaly_id": str(r["anomaly_id"]),
                        "timestamp": r["timestamp"].isoformat() if r["timestamp"] else None,
                    }
                    for r in rows
                ]
    except Exception as e:
        logger.error(f"Error fetching recent anomalies: {e}")
        raise HTTPException(status_code=500, detail="Database error") from e


@router.get("/risk-distribution")
def get_risk_distribution(_user: dict = Depends(get_current_user)):
    """Severity breakdown counts across ALL enriched_anomalies."""
    try:
        with get_db() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT LOWER(severity), COUNT(*)
                    FROM enriched_anomalies
                    GROUP BY severity
                """)
                rows = cur.fetchall()
                distribution: dict[str, int] = {"critical": 0, "high": 0, "medium": 0, "low": 0}
                for sev, count in rows:
                    if sev in distribution:
                        distribution[sev] = int(count)
                distribution["total"] = sum(distribution.values())
                return distribution
    except Exception as e:
        logger.error(f"Error fetching risk distribution: {e}")
        raise HTTPException(status_code=500, detail="Database error") from e


@router.get("/top-users")
def get_top_users(_user: dict = Depends(get_current_user)):
    """10 users with most anomalies, each with their top 10 highest-scored anomalies."""
    try:
        with get_db() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute("""
                    SELECT
                        mu.*,
                        COUNT(ea.anomaly_id)                                                 AS anomaly_count,
                        MAX(ea.timestamp)                                                    AS last_anomaly_at,
                        ROUND(COALESCE(AVG(ea.anomaly_score), 0)::numeric, 4)               AS avg_anomaly_score,
                        COUNT(ea.anomaly_id) FILTER (WHERE ea.severity = 'CRITICAL')        AS critical_count,
                        (
                            SELECT json_agg(t ORDER BY t.anomaly_score DESC)
                            FROM (
                                SELECT
                                    anomaly_id::text,
                                    anomaly_score,
                                    LOWER(severity)  AS severity,
                                    root_cause,
                                    sub_category,
                                    risk_score,
                                    status,
                                    timestamp,
                                    ai_enrichment
                                FROM enriched_anomalies
                                WHERE user_id = mu.username
                                ORDER BY anomaly_score DESC
                                LIMIT 10
                            ) t
                        ) AS top_anomalies
                    FROM monitored_users mu
                    JOIN enriched_anomalies ea ON ea.user_id = mu.username
                    GROUP BY mu.id
                    ORDER BY anomaly_count DESC
                    LIMIT 10
                """)
                rows = cur.fetchall()
                result = []
                for r in rows:
                    d = dict(r)
                    for ts_col in ("created_at", "updated_at", "last_anomaly_at"):
                        if d.get(ts_col):
                            d[ts_col] = d[ts_col].isoformat()
                    d["anomaly_count"] = int(d["anomaly_count"])
                    d["critical_count"] = int(d["critical_count"])
                    d["avg_anomaly_score"] = float(d["avg_anomaly_score"])
                    result.append(d)
                return result
    except Exception as e:
        logger.error(f"Error fetching top users: {e}")
        raise HTTPException(status_code=500, detail="Database error") from e


@router.get("/user-metrics")
def get_user_metrics(_user: dict = Depends(get_current_user)):
    """Aggregate metrics across ALL monitored users for gauge display."""
    try:
        with get_db() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    WITH
                    total_users AS (
                        SELECT COUNT(*) AS n FROM monitored_users
                    ),
                    affected_users AS (
                        SELECT COUNT(DISTINCT user_id) AS n FROM enriched_anomalies
                    ),
                    critical_users AS (
                        SELECT COUNT(DISTINCT user_id) AS n
                        FROM enriched_anomalies WHERE severity = 'CRITICAL'
                    ),
                    resolution AS (
                        SELECT
                            COUNT(*) FILTER (WHERE LOWER(status) = 'resolved') AS resolved,
                            COUNT(*) AS total
                        FROM enriched_anomalies
                    ),
                    avg_score AS (
                        SELECT ROUND(COALESCE(AVG(anomaly_score), 0)::numeric, 4) AS v
                        FROM enriched_anomalies
                    ),
                    mtba AS (
                        SELECT ROUND(COALESCE(AVG(hours_between), 0)::numeric, 2) AS v
                        FROM (
                            SELECT
                                EXTRACT(EPOCH FROM (
                                    timestamp - LAG(timestamp) OVER (
                                        PARTITION BY user_id ORDER BY timestamp
                                    )
                                )) / 3600.0 AS hours_between
                            FROM enriched_anomalies
                        ) gaps
                        WHERE hours_between IS NOT NULL
                    )
                    SELECT
                        total_users.n,
                        affected_users.n,
                        critical_users.n,
                        resolution.resolved,
                        resolution.total,
                        avg_score.v,
                        mtba.v
                    FROM total_users, affected_users, critical_users,
                         resolution, avg_score, mtba
                """)
                row = cur.fetchone()
                total_users, affected, critical_users, resolved, total_anomalies, avg_score, mtba = row

                exposure_rate = round(float(affected) / float(total_users) * 100, 1) if total_users else 0.0
                # % of ALL monitored users (not just affected) with ≥1 CRITICAL anomaly
                critical_ratio = round(float(critical_users) / float(total_users) * 100, 1) if total_users else 0.0
                resolution_rate = round(float(resolved) / float(total_anomalies) * 100, 1) if total_anomalies else 0.0

                return {
                    "exposureRate": exposure_rate,
                    "criticalRatio": critical_ratio,
                    "avgRiskScore": float(avg_score),
                    "resolutionRate": resolution_rate,
                    "mtbaHours": float(mtba),
                }
    except Exception as e:
        logger.error(f"Error fetching user metrics: {e}")
        raise HTTPException(status_code=500, detail="Database error") from e


@router.get("/activity-heatmap")
def get_activity_heatmap(_user: dict = Depends(get_current_user)):
    """Daily anomaly counts for the last 17 weeks, used to render the activity heatmap."""
    try:
        with get_db() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute("""
                    SELECT
                        DATE(timestamp)                                                         AS date,
                        COUNT(*)                                                                AS count,
                        ROUND(MAX(anomaly_score)::numeric, 2)                                   AS max_score,
                        COUNT(*) FILTER (WHERE status = 'resolved')                            AS confirmed_count,
                        COUNT(*) FILTER (WHERE analyst_verdict = 'false_positive')              AS false_positive_count,
                        COUNT(*) FILTER (WHERE status = 'new')                                  AS new_count
                    FROM enriched_anomalies
                    WHERE timestamp >= NOW() - INTERVAL '119 days'
                    GROUP BY DATE(timestamp)
                    ORDER BY date ASC
                """)
                rows = cur.fetchall()
                return [
                    {
                        "date": str(r["date"]),
                        "count": int(r["count"]),
                        "max_score": float(r["max_score"]) if r["max_score"] is not None else None,
                        "confirmed_count": int(r["confirmed_count"]),
                        "false_positive_count": int(r["false_positive_count"]),
                        "new_count": int(r["new_count"]),
                    }
                    for r in rows
                ]
    except Exception as e:
        logger.error(f"Error fetching activity heatmap: {e}")
        raise HTTPException(status_code=500, detail="Database error") from e


@router.get("/top-root-causes")
def get_top_root_causes(_user: dict = Depends(get_current_user)):
    """Top 5 root causes by anomaly volume with severity breakdown and affected user count."""
    try:
        with get_db() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute("""
                    SELECT
                        root_cause,
                        COUNT(*)                                                    AS anomaly_count,
                        COUNT(DISTINCT user_id)                                     AS affected_users,
                        ROUND(AVG(anomaly_score)::numeric, 4)                       AS avg_anomaly_score,
                        ROUND(COALESCE(AVG(risk_score), 0)::numeric, 4)             AS avg_risk_score,
                        COUNT(*) FILTER (WHERE severity = 'CRITICAL')               AS critical_count,
                        COUNT(*) FILTER (WHERE severity = 'HIGH')                   AS high_count,
                        COUNT(*) FILTER (WHERE severity = 'MEDIUM')                 AS medium_count,
                        COUNT(*) FILTER (WHERE severity = 'LOW')                    AS low_count,
                        MAX(timestamp)                                              AS last_seen_at
                    FROM enriched_anomalies
                    WHERE root_cause IS NOT NULL
                    GROUP BY root_cause
                    ORDER BY anomaly_count DESC
                    LIMIT 5
                """)
                rows = cur.fetchall()
                return [
                    {
                        **dict(r),
                        "anomaly_count": int(r["anomaly_count"]),
                        "affected_users": int(r["affected_users"]),
                        "avg_anomaly_score": float(r["avg_anomaly_score"]),
                        "avg_risk_score": float(r["avg_risk_score"]),
                        "critical_count": int(r["critical_count"]),
                        "high_count": int(r["high_count"]),
                        "medium_count": int(r["medium_count"]),
                        "low_count": int(r["low_count"]),
                        "last_seen_at": r["last_seen_at"].isoformat() if r["last_seen_at"] else None,
                    }
                    for r in rows
                ]
    except Exception as e:
        logger.error(f"Error fetching top root causes: {e}")
        raise HTTPException(status_code=500, detail="Database error") from e


@router.get("/system-maturity")
def get_system_maturity(_user: dict = Depends(get_current_user)):
    """Rule-based anomaly maturity classification and aggregate score.

    Classification per anomaly:
      resolved → resilient
      pending  → managed
      new + LOW/MEDIUM severity → managed
      new + HIGH/CRITICAL severity → exposed

    Score (0-100):
      resilient=100 pts, managed=65 pts, exposed=20 pts  → weighted avg.

    Overall level from score:
      80-100 → Resilient | 55-79 → Managed | 30-54 → Developing | 0-29 → Exposed
    """
    try:
        with get_db() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT
                        COUNT(*) FILTER (
                            WHERE LOWER(status) = 'resolved'
                        ) AS resilient,
                        COUNT(*) FILTER (
                            WHERE LOWER(status) = 'pending'
                               OR (LOWER(status) = 'new'
                                   AND UPPER(severity) IN ('LOW', 'MEDIUM'))
                        ) AS managed,
                        COUNT(*) FILTER (
                            WHERE LOWER(status) = 'new'
                              AND UPPER(severity) IN ('HIGH', 'CRITICAL')
                        ) AS exposed,
                        COUNT(*) AS total
                    FROM enriched_anomalies
                """)
                row = cur.fetchone()
                resilient, managed, exposed, total = (int(row[0]), int(row[1]), int(row[2]), int(row[3]))

        if total == 0:
            return {
                "score": 0.0,
                "level": "Exposed",
                "total": 0,
                "distribution": {
                    "resilient": {"count": 0, "pct": 0.0},
                    "managed": {"count": 0, "pct": 0.0},
                    "exposed": {"count": 0, "pct": 0.0},
                },
            }

        score = round((resilient * 100 + managed * 65 + exposed * 20) / total, 1)

        if score >= 80:
            level = "Resilient"
        elif score >= 55:
            level = "Managed"
        elif score >= 30:
            level = "Developing"
        else:
            level = "Exposed"

        def pct(n: int) -> float:
            return round(n / total * 100, 1)

        return {
            "score": score,
            "level": level,
            "total": total,
            "distribution": {
                "resilient": {"count": resilient, "pct": pct(resilient)},
                "managed": {"count": managed, "pct": pct(managed)},
                "exposed": {"count": exposed, "pct": pct(exposed)},
            },
        }
    except Exception as e:
        logger.error(f"Error fetching system maturity: {e}")
        raise HTTPException(status_code=500, detail="Database error") from e


@router.get("/top-anomalies")
def get_top_anomalies(_user: dict = Depends(get_current_user)):
    """10 anomalies with the highest anomaly score, with joined user info."""
    try:
        with get_db() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute("""
                    SELECT
                        ea.anomaly_id,
                        ea.user_id,
                        ea.timestamp,
                        ea.anomaly_score,
                        LOWER(ea.severity)  AS severity,
                        ea.root_cause,
                        ea.sub_category,
                        ea.risk_score,
                        ea.is_anomaly,
                        ea.status,
                        ea.original_event,
                        ea.ai_enrichment,
                        ea.created_at,
                        mu.display_name,
                        mu.avatar_color,
                        mu.avatar_initials,
                        mu.avatar_url,
                        mu.department,
                        mu.company
                    FROM enriched_anomalies ea
                    LEFT JOIN monitored_users mu ON mu.username = ea.user_id
                    ORDER BY ea.anomaly_score DESC
                    LIMIT 10
                """)
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
        logger.error(f"Error fetching top anomalies: {e}")
        raise HTTPException(status_code=500, detail="Database error") from e


@router.get("/anomalies/{anomaly_id}/investigation")
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
                        COALESCE(
                            json_agg(
                                json_build_object(
                                    'agent_type', af.agent_type,
                                    'status', af.status,
                                    'result', af.result,
                                    'latency_ms', af.latency_ms,
                                    'completed_at', af.completed_at
                                ) ORDER BY af.started_at
                            ) FILTER (WHERE af.investigation_id IS NOT NULL),
                            '[]'::json
                        ) AS findings
                    FROM agent_investigations ai
                    LEFT JOIN agent_findings af ON af.investigation_id = ai.investigation_id
                    WHERE ai.anomaly_id = %s
                    GROUP BY ai.investigation_id
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
        return result
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching investigation for anomaly {anomaly_id}: {e}")
        raise HTTPException(status_code=500, detail="Database error") from e


@router.get("/investigations")
def list_investigations(
    status: str | None = None, limit: int = 20, offset: int = 0, _user: dict = Depends(get_current_user)
):
    """Paginated list of investigations joined with enriched_anomalies."""
    try:
        with get_db() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(
                    """
                    SELECT
                        ai.investigation_id,
                        ai.anomaly_id,
                        ai.triggered_at,
                        ai.completed_at,
                        ai.status,
                        ai.severity_at_trigger,
                        ai.confidence_score,
                        ai.overall_recommendation,
                        ea.user_id,
                        ea.root_cause,
                        ea.risk_score
                    FROM agent_investigations ai
                    JOIN enriched_anomalies ea ON ea.anomaly_id = ai.anomaly_id
                    WHERE (%s IS NULL OR ai.status = %s)
                    ORDER BY ai.triggered_at DESC
                    LIMIT %s OFFSET %s
                    """,
                    (status, status, limit, offset),
                )
                rows = cur.fetchall()
        return [
            {
                **dict(r),
                "investigation_id": str(r["investigation_id"]),
                "anomaly_id": str(r["anomaly_id"]),
                "triggered_at": r["triggered_at"].isoformat() if r["triggered_at"] else None,
                "completed_at": r["completed_at"].isoformat() if r["completed_at"] else None,
            }
            for r in rows
        ]
    except Exception as e:
        logger.error(f"Error fetching investigations: {e}")
        raise HTTPException(status_code=500, detail="Database error") from e


@router.get("/stats-trend")
def get_stats_trend(_user: dict = Depends(get_current_user)):
    """7-day vs previous-7-day severity counts for trend arrows on KPI cards."""
    try:
        with get_db() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT
                        COUNT(*) FILTER (WHERE severity = 'CRITICAL' AND timestamp >= NOW() - INTERVAL '7 days')  AS critical_cur,
                        COUNT(*) FILTER (WHERE severity = 'CRITICAL'
                            AND timestamp >= NOW() - INTERVAL '14 days'
                            AND timestamp <  NOW() - INTERVAL '7 days')                                            AS critical_prev,
                        COUNT(*) FILTER (WHERE severity = 'HIGH'    AND timestamp >= NOW() - INTERVAL '7 days')  AS high_cur,
                        COUNT(*) FILTER (WHERE severity = 'HIGH'
                            AND timestamp >= NOW() - INTERVAL '14 days'
                            AND timestamp <  NOW() - INTERVAL '7 days')                                            AS high_prev,
                        COUNT(*) FILTER (WHERE severity = 'MEDIUM'  AND timestamp >= NOW() - INTERVAL '7 days')  AS medium_cur,
                        COUNT(*) FILTER (WHERE severity = 'MEDIUM'
                            AND timestamp >= NOW() - INTERVAL '14 days'
                            AND timestamp <  NOW() - INTERVAL '7 days')                                            AS medium_prev,
                        COUNT(*) FILTER (WHERE severity = 'LOW'     AND timestamp >= NOW() - INTERVAL '7 days')  AS low_cur,
                        COUNT(*) FILTER (WHERE severity = 'LOW'
                            AND timestamp >= NOW() - INTERVAL '14 days'
                            AND timestamp <  NOW() - INTERVAL '7 days')                                            AS low_prev
                    FROM enriched_anomalies
                    WHERE timestamp >= NOW() - INTERVAL '14 days'
                """)
                row = cur.fetchone()

        def _trend(cur: int, prev: int) -> dict:
            if prev == 0:
                delta_pct = 100.0 if cur > 0 else 0.0
            else:
                delta_pct = round((cur - prev) / prev * 100, 1)
            return {"current": cur, "previous": prev, "delta_pct": delta_pct}

        return {
            "critical": _trend(int(row[0]), int(row[1])),
            "high": _trend(int(row[2]), int(row[3])),
            "medium": _trend(int(row[4]), int(row[5])),
            "low": _trend(int(row[6]), int(row[7])),
        }
    except Exception as e:
        logger.error(f"Error fetching stats trend: {e}")
        raise HTTPException(status_code=500, detail="Database error") from e


@router.get("/investigation-trend")
def get_investigation_trend(_user: dict = Depends(get_current_user)):
    """Daily investigation throughput over the last 30 days.

    Returns one row per day with triggered/completed/failed counts,
    completion rate %, average confidence score, and average duration in hours.
    """
    try:
        with get_db() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute("""
                    SELECT
                        DATE(triggered_at)                                              AS day,
                        COUNT(*)                                                        AS triggered,
                        COUNT(*) FILTER (WHERE status = 'complete')                    AS completed,
                        COUNT(*) FILTER (WHERE status = 'failed')                      AS failed,
                        COUNT(*) FILTER (WHERE status = 'pending')                     AS pending,
                        ROUND(
                            COUNT(*) FILTER (WHERE status = 'complete')::numeric
                            / NULLIF(COUNT(*), 0) * 100, 1
                        )                                                               AS completion_rate,
                        ROUND(AVG(confidence_score)::numeric, 3)                       AS avg_confidence,
                        ROUND(
                            AVG(
                                EXTRACT(EPOCH FROM (completed_at - triggered_at)) / 3600.0
                            ) FILTER (WHERE completed_at IS NOT NULL)::numeric, 4
                        )                                                               AS avg_duration_hours
                    FROM agent_investigations
                    WHERE triggered_at >= NOW() - INTERVAL '30 days'
                    GROUP BY DATE(triggered_at)
                    ORDER BY day ASC
                """)
                rows = cur.fetchall()
        return [
            {
                "day": str(r["day"]),
                "triggered": int(r["triggered"]),
                "completed": int(r["completed"]),
                "failed": int(r["failed"]),
                "pending": int(r["pending"]),
                "completion_rate": float(r["completion_rate"]) if r["completion_rate"] is not None else None,
                "avg_confidence": float(r["avg_confidence"]) if r["avg_confidence"] is not None else None,
                "avg_duration_hours": float(r["avg_duration_hours"]) if r["avg_duration_hours"] is not None else None,
            }
            for r in rows
        ]
    except Exception as e:
        logger.error(f"Error fetching investigation trend: {e}")
        raise HTTPException(status_code=500, detail="Database error") from e


@router.get("/intraday-rhythm")
def get_intraday_rhythm(_user: dict = Depends(get_current_user)):
    """Per hour-of-day × day-of-week anomaly counts over last 90 days.

    Returns a flat list of 168 cells (7 DOW × 24 hours).
    DOW: 0=Mon … 6=Sun  (ISO convention).
    """
    try:
        with get_db() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT
                        EXTRACT(ISODOW FROM timestamp)::int - 1  AS dow,
                        EXTRACT(HOUR   FROM timestamp)::int       AS hour,
                        COUNT(*)                                   AS total_count,
                        ROUND(AVG(anomaly_score)::numeric, 2)     AS avg_score
                    FROM enriched_anomalies
                    WHERE timestamp >= NOW() - INTERVAL '90 days'
                    GROUP BY dow, hour
                    ORDER BY dow, hour
                """)
                rows = cur.fetchall()

        lookup: dict[tuple[int, int], tuple[int, float]] = {
            (int(r[0]), int(r[1])): (int(r[2]), float(r[3])) for r in rows
        }

        cells = []
        for dow in range(7):
            for hour in range(24):
                count, avg_score = lookup.get((dow, hour), (0, 0.0))
                cells.append({"dow": dow, "hour": hour, "count": count, "avg_score": avg_score})
        return cells
    except Exception as e:
        logger.error(f"Error fetching intraday rhythm: {e}")
        raise HTTPException(status_code=500, detail="Database error") from e


@router.get("/platform-stats")
def get_platform_stats(_user: dict = Depends(get_current_user)):
    """Aggregated stats for the Platform Overview cards."""
    try:
        with get_db() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    WITH monitored_user_counts AS (
                        SELECT COUNT(*) AS monitored_users
                        FROM monitored_users
                    ),
                    enriched_anomaly_counts AS (
                        SELECT
                            COUNT(*) AS total_detections,
                            COUNT(*) FILTER (WHERE is_anomaly = TRUE) AS true_positives,
                            COUNT(*) FILTER (WHERE is_anomaly IS NOT NULL) AS labeled_records,
                            COUNT(DISTINCT root_cause) FILTER (WHERE root_cause IS NOT NULL) AS root_cause_count,
                            COUNT(DISTINCT user_id) FILTER (WHERE is_anomaly = TRUE) AS users_with_anomalies
                        FROM enriched_anomalies
                    ),
                    investigation_counts AS (
                        SELECT
                            COUNT(*) AS total_investigations,
                            COUNT(*) FILTER (WHERE status = 'completed') AS completed_investigations
                        FROM agent_investigations
                    ),
                    finding_counts AS (
                        SELECT COUNT(*) AS total_findings
                        FROM agent_findings
                    ),
                    migration_counts AS (
                        SELECT COUNT(*) AS migration_count
                        FROM schema_migrations
                    )
                    SELECT
                        muc.monitored_users,
                        eac.total_detections,
                        eac.true_positives,
                        eac.labeled_records,
                        eac.root_cause_count,
                        ic.total_investigations,
                        ic.completed_investigations,
                        fc.total_findings,
                        mc.migration_count,
                        eac.users_with_anomalies
                    FROM monitored_user_counts muc
                    CROSS JOIN enriched_anomaly_counts eac
                    CROSS JOIN investigation_counts ic
                    CROSS JOIN finding_counts fc
                    CROSS JOIN migration_counts mc
                """)
                row = cur.fetchone()

        pg_stats = {
            "monitoredUsers": int(row[0]),
            "totalDetections": int(row[1]),
            "truePositives": int(row[2]),
            "labeledRecords": int(row[3]),
            "rootCauseCount": int(row[4]),
            "totalInvestigations": int(row[5]),
            "completedInvestigations": int(row[6]),
            "totalFindings": int(row[7]),
            "migrationCount": int(row[8]),
            "usersWithAnomalies": int(row[9]),
        }

        # Qdrant — best-effort, falls back to 0 if unavailable
        qdrant_docs = 0
        qdrant_collections = 0
        try:
            from qdrant_client import QdrantClient  # type: ignore[import]

            qc = QdrantClient(
                host=os.getenv("QDRANT_HOST", "localhost"),
                port=int(os.getenv("QDRANT_PORT", "6333")),
                api_key=os.getenv("QDRANT_API_KEY") or None,
                timeout=3,
            )
            cols = qc.get_collections().collections
            qdrant_collections = len(cols)
            for col in cols:
                info = qc.get_collection(col.name)
                qdrant_docs += info.points_count or 0
        except Exception as qe:
            logger.warning(f"Qdrant stats unavailable: {qe}")

        return {
            **pg_stats,
            "qdrantDocuments": qdrant_docs,
            "qdrantCollections": qdrant_collections,
        }

    except Exception as e:
        logger.error(f"Error fetching platform stats: {e}")
        raise HTTPException(status_code=500, detail="Database error") from e


# ---------------------------------------------------------------------------
# Consolidated snapshot — single endpoint replaces 12+ individual calls
# ---------------------------------------------------------------------------


def _build_snapshot() -> dict:
    """Execute all dashboard queries in one DB connection and return combined payload."""
    with get_db() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            # ── 1. Core stats (single scan with FILTER) ──────────────────
            cur.execute("""
                SELECT
                    COUNT(*)                                                            AS total_anomalies,
                    COUNT(DISTINCT user_id)                                             AS active_users,
                    ROUND(COALESCE(AVG(anomaly_score), 0)::numeric, 4)                 AS avg_anomaly_score,
                    COUNT(*) FILTER (WHERE severity = 'CRITICAL')                      AS critical,
                    COUNT(*) FILTER (WHERE severity = 'HIGH')                          AS high,
                    COUNT(*) FILTER (WHERE severity = 'MEDIUM')                        AS medium,
                    COUNT(*) FILTER (WHERE severity = 'LOW')                           AS low,
                    COUNT(*) FILTER (WHERE status = 'new')                             AS new,
                    COUNT(*) FILTER (WHERE status = 'resolved')                        AS resolved,
                    COUNT(*) FILTER (WHERE status = 'pending')                         AS pending,
                    -- system maturity buckets
                    COUNT(*) FILTER (WHERE LOWER(status) = 'resolved')                 AS sm_resilient,
                    COUNT(*) FILTER (
                        WHERE LOWER(status) = 'pending'
                           OR (LOWER(status) = 'new' AND UPPER(severity) IN ('LOW','MEDIUM'))
                    )                                                                   AS sm_managed,
                    COUNT(*) FILTER (
                        WHERE LOWER(status) = 'new' AND UPPER(severity) IN ('HIGH','CRITICAL')
                    )                                                                   AS sm_exposed
                FROM enriched_anomalies
            """)
            agg = dict(cur.fetchone())

            cur.execute("SELECT COUNT(*) AS n FROM monitored_users")
            total_users = cur.fetchone()["n"]
            cur.execute("SELECT COUNT(*) AS n FROM user_training_events")
            training_events = cur.fetchone()["n"]

            stats = {
                "totalUsers": int(total_users),
                "totalEvents": int(training_events) + int(agg["total_anomalies"]),
                "totalAnomalies": int(agg["total_anomalies"]),
                "activeUsers": int(agg["active_users"]),
                "anomalies": {
                    "critical": int(agg["critical"]),
                    "high": int(agg["high"]),
                    "medium": int(agg["medium"]),
                    "low": int(agg["low"]),
                    "new": int(agg["new"]),
                    "resolved": int(agg["resolved"]),
                    "pending": int(agg["pending"]),
                },
                "avgAnomalyScore": float(agg["avg_anomaly_score"]),
            }

            # Risk distribution (already computed)
            risk_distribution = {
                "critical": int(agg["critical"]),
                "high": int(agg["high"]),
                "medium": int(agg["medium"]),
                "low": int(agg["low"]),
                "total": int(agg["critical"]) + int(agg["high"]) + int(agg["medium"]) + int(agg["low"]),
            }

            # System maturity (already computed)
            sm_resilient = int(agg["sm_resilient"])
            sm_managed = int(agg["sm_managed"])
            sm_exposed = int(agg["sm_exposed"])
            sm_total = int(agg["total_anomalies"])
            if sm_total == 0:
                system_maturity = {
                    "score": 0.0,
                    "level": "Exposed",
                    "total": 0,
                    "distribution": {
                        "resilient": {"count": 0, "pct": 0.0},
                        "managed": {"count": 0, "pct": 0.0},
                        "exposed": {"count": 0, "pct": 0.0},
                    },
                }
            else:
                sm_score = round((sm_resilient * 100 + sm_managed * 65 + sm_exposed * 20) / sm_total, 1)
                sm_level = (
                    "Resilient"
                    if sm_score >= 80
                    else "Managed"
                    if sm_score >= 55
                    else "Developing"
                    if sm_score >= 30
                    else "Exposed"
                )

                def sm_pct(n):
                    return round(n / sm_total * 100, 1)

                system_maturity = {
                    "score": sm_score,
                    "level": sm_level,
                    "total": sm_total,
                    "distribution": {
                        "resilient": {"count": sm_resilient, "pct": sm_pct(sm_resilient)},
                        "managed": {"count": sm_managed, "pct": sm_pct(sm_managed)},
                        "exposed": {"count": sm_exposed, "pct": sm_pct(sm_exposed)},
                    },
                }

            # ── 2. Stats trend (7-day vs previous-7-day) ─────────────────
            cur.execute("""
                SELECT
                    COUNT(*) FILTER (WHERE severity = 'CRITICAL' AND timestamp >= NOW() - INTERVAL '7 days')   AS critical_cur,
                    COUNT(*) FILTER (WHERE severity = 'CRITICAL'
                        AND timestamp >= NOW() - INTERVAL '14 days'
                        AND timestamp <  NOW() - INTERVAL '7 days')                                             AS critical_prev,
                    COUNT(*) FILTER (WHERE severity = 'HIGH' AND timestamp >= NOW() - INTERVAL '7 days')       AS high_cur,
                    COUNT(*) FILTER (WHERE severity = 'HIGH'
                        AND timestamp >= NOW() - INTERVAL '14 days'
                        AND timestamp <  NOW() - INTERVAL '7 days')                                             AS high_prev,
                    COUNT(*) FILTER (WHERE severity = 'MEDIUM' AND timestamp >= NOW() - INTERVAL '7 days')     AS medium_cur,
                    COUNT(*) FILTER (WHERE severity = 'MEDIUM'
                        AND timestamp >= NOW() - INTERVAL '14 days'
                        AND timestamp <  NOW() - INTERVAL '7 days')                                             AS medium_prev,
                    COUNT(*) FILTER (WHERE severity = 'LOW' AND timestamp >= NOW() - INTERVAL '7 days')        AS low_cur,
                    COUNT(*) FILTER (WHERE severity = 'LOW'
                        AND timestamp >= NOW() - INTERVAL '14 days'
                        AND timestamp <  NOW() - INTERVAL '7 days')                                             AS low_prev
                FROM enriched_anomalies
                WHERE timestamp >= NOW() - INTERVAL '14 days'
            """)
            tr = cur.fetchone()

            def _trend(c: int, p: int) -> dict:
                if p == 0:
                    dp = 100.0 if c > 0 else 0.0
                else:
                    dp = round((c - p) / p * 100, 1)
                return {"current": c, "previous": p, "delta_pct": dp}

            stats_trend = {
                "critical": _trend(int(tr["critical_cur"]), int(tr["critical_prev"])),
                "high": _trend(int(tr["high_cur"]), int(tr["high_prev"])),
                "medium": _trend(int(tr["medium_cur"]), int(tr["medium_prev"])),
                "low": _trend(int(tr["low_cur"]), int(tr["low_prev"])),
            }

            # ── 3. User metrics ──────────────────────────────────────────
            cur.execute("""
                WITH
                affected_users AS (
                    SELECT COUNT(DISTINCT user_id) AS n FROM enriched_anomalies
                ),
                critical_users AS (
                    SELECT COUNT(DISTINCT user_id) AS n
                    FROM enriched_anomalies WHERE severity = 'CRITICAL'
                ),
                resolution AS (
                    SELECT
                        COUNT(*) FILTER (WHERE LOWER(status) = 'resolved') AS resolved,
                        COUNT(*) AS total
                    FROM enriched_anomalies
                ),
                avg_score AS (
                    SELECT ROUND(COALESCE(AVG(anomaly_score), 0)::numeric, 4) AS v
                    FROM enriched_anomalies
                ),
                mtba AS (
                    SELECT ROUND(COALESCE(AVG(hours_between), 0)::numeric, 2) AS v
                    FROM (
                        SELECT
                            EXTRACT(EPOCH FROM (
                                timestamp - LAG(timestamp) OVER (
                                    PARTITION BY user_id ORDER BY timestamp
                                )
                            )) / 3600.0 AS hours_between
                        FROM enriched_anomalies
                    ) gaps
                    WHERE hours_between IS NOT NULL
                )
                SELECT
                    affected_users.n  AS affected,
                    critical_users.n  AS critical_users,
                    resolution.resolved,
                    resolution.total  AS total_anomalies,
                    avg_score.v       AS avg_score,
                    mtba.v            AS mtba
                FROM affected_users, critical_users, resolution, avg_score, mtba
            """)
            um = cur.fetchone()
            tu = float(total_users)
            ta = float(um["total_anomalies"]) if um["total_anomalies"] else 0
            user_metrics = {
                "exposureRate": round(float(um["affected"]) / tu * 100, 1) if tu else 0.0,
                "criticalRatio": round(float(um["critical_users"]) / tu * 100, 1) if tu else 0.0,
                "avgRiskScore": float(um["avg_score"]),
                "resolutionRate": round(float(um["resolved"]) / ta * 100, 1) if ta else 0.0,
                "mtbaHours": float(um["mtba"]),
            }

            # ── 4. Recent anomalies ──────────────────────────────────────
            cur.execute("""
                SELECT
                    ea.anomaly_id, ea.user_id, ea.timestamp, ea.anomaly_score,
                    LOWER(ea.severity) AS severity, ea.root_cause, ea.sub_category,
                    ea.risk_score, ea.status, ea.original_event,
                    mu.display_name, mu.avatar_color, mu.avatar_initials,
                    mu.avatar_url, mu.company, mu.department, mu.devices,
                    mu.apps, mu.all_locations
                FROM enriched_anomalies ea
                LEFT JOIN monitored_users mu ON mu.username = ea.user_id
                ORDER BY ea.timestamp DESC
                LIMIT 10
            """)
            recent_anomalies = [
                {
                    **dict(r),
                    "anomaly_id": str(r["anomaly_id"]),
                    "timestamp": r["timestamp"].isoformat() if r["timestamp"] else None,
                }
                for r in cur.fetchall()
            ]

            # ── 5. Top anomalies ─────────────────────────────────────────
            cur.execute("""
                SELECT
                    ea.anomaly_id, ea.user_id, ea.timestamp, ea.anomaly_score,
                    LOWER(ea.severity) AS severity, ea.root_cause, ea.sub_category,
                    ea.risk_score, ea.is_anomaly, ea.status, ea.original_event,
                    ea.ai_enrichment, ea.created_at,
                    mu.display_name, mu.avatar_color, mu.avatar_initials,
                    mu.avatar_url, mu.department, mu.company
                FROM enriched_anomalies ea
                LEFT JOIN monitored_users mu ON mu.username = ea.user_id
                ORDER BY ea.anomaly_score DESC
                LIMIT 10
            """)
            top_anomalies = [
                {
                    **dict(r),
                    "anomaly_id": str(r["anomaly_id"]),
                    "timestamp": r["timestamp"].isoformat() if r["timestamp"] else None,
                    "created_at": r["created_at"].isoformat() if r["created_at"] else None,
                }
                for r in cur.fetchall()
            ]

            # ── 6. Top users ─────────────────────────────────────────────
            cur.execute("""
                SELECT
                    mu.*,
                    COUNT(ea.anomaly_id)                                                 AS anomaly_count,
                    MAX(ea.timestamp)                                                    AS last_anomaly_at,
                    ROUND(COALESCE(AVG(ea.anomaly_score), 0)::numeric, 4)               AS avg_anomaly_score,
                    COUNT(ea.anomaly_id) FILTER (WHERE ea.severity = 'CRITICAL')        AS critical_count,
                    (
                        SELECT json_agg(t ORDER BY t.anomaly_score DESC)
                        FROM (
                            SELECT
                                anomaly_id::text, anomaly_score,
                                LOWER(severity) AS severity, root_cause,
                                sub_category, risk_score, status, timestamp, ai_enrichment
                            FROM enriched_anomalies
                            WHERE user_id = mu.username
                            ORDER BY anomaly_score DESC
                            LIMIT 10
                        ) t
                    ) AS top_anomalies
                FROM monitored_users mu
                JOIN enriched_anomalies ea ON ea.user_id = mu.username
                GROUP BY mu.id
                ORDER BY anomaly_count DESC
                LIMIT 10
            """)
            top_users = []
            for r in cur.fetchall():
                d = dict(r)
                for ts_col in ("created_at", "updated_at", "last_anomaly_at"):
                    if d.get(ts_col):
                        d[ts_col] = d[ts_col].isoformat()
                d["anomaly_count"] = int(d["anomaly_count"])
                d["critical_count"] = int(d["critical_count"])
                d["avg_anomaly_score"] = float(d["avg_anomaly_score"])
                top_users.append(d)

            # ── 7. Top root causes ───────────────────────────────────────
            cur.execute("""
                SELECT
                    root_cause,
                    COUNT(*)                                                    AS anomaly_count,
                    COUNT(DISTINCT user_id)                                     AS affected_users,
                    ROUND(AVG(anomaly_score)::numeric, 4)                       AS avg_anomaly_score,
                    ROUND(COALESCE(AVG(risk_score), 0)::numeric, 4)             AS avg_risk_score,
                    COUNT(*) FILTER (WHERE severity = 'CRITICAL')               AS critical_count,
                    COUNT(*) FILTER (WHERE severity = 'HIGH')                   AS high_count,
                    COUNT(*) FILTER (WHERE severity = 'MEDIUM')                 AS medium_count,
                    COUNT(*) FILTER (WHERE severity = 'LOW')                    AS low_count,
                    MAX(timestamp)                                              AS last_seen_at
                FROM enriched_anomalies
                WHERE root_cause IS NOT NULL
                GROUP BY root_cause
                ORDER BY anomaly_count DESC
                LIMIT 5
            """)
            top_root_causes = [
                {
                    **dict(r),
                    "anomaly_count": int(r["anomaly_count"]),
                    "affected_users": int(r["affected_users"]),
                    "avg_anomaly_score": float(r["avg_anomaly_score"]),
                    "avg_risk_score": float(r["avg_risk_score"]),
                    "critical_count": int(r["critical_count"]),
                    "high_count": int(r["high_count"]),
                    "medium_count": int(r["medium_count"]),
                    "low_count": int(r["low_count"]),
                    "last_seen_at": r["last_seen_at"].isoformat() if r["last_seen_at"] else None,
                }
                for r in cur.fetchall()
            ]

            # ── 8. Activity heatmap ──────────────────────────────────────
            cur.execute("""
                SELECT
                    DATE(timestamp)                                                         AS date,
                    COUNT(*)                                                                AS count,
                    ROUND(MAX(anomaly_score)::numeric, 2)                                   AS max_score,
                    COUNT(*) FILTER (WHERE status = 'resolved')                            AS confirmed_count,
                    COUNT(*) FILTER (WHERE analyst_verdict = 'false_positive')              AS false_positive_count,
                    COUNT(*) FILTER (WHERE status = 'new')                                  AS new_count
                FROM enriched_anomalies
                WHERE timestamp >= NOW() - INTERVAL '119 days'
                GROUP BY DATE(timestamp)
                ORDER BY date ASC
            """)
            activity_heatmap = [
                {
                    "date": str(r["date"]),
                    "count": int(r["count"]),
                    "max_score": float(r["max_score"]) if r["max_score"] is not None else None,
                    "confirmed_count": int(r["confirmed_count"]),
                    "false_positive_count": int(r["false_positive_count"]),
                    "new_count": int(r["new_count"]),
                }
                for r in cur.fetchall()
            ]

            # ── 9. Intraday rhythm ───────────────────────────────────────
            cur.execute("""
                SELECT
                    EXTRACT(ISODOW FROM timestamp)::int - 1  AS dow,
                    EXTRACT(HOUR   FROM timestamp)::int       AS hour,
                    COUNT(*)                                   AS total_count,
                    ROUND(AVG(anomaly_score)::numeric, 2)     AS avg_score
                FROM enriched_anomalies
                WHERE timestamp >= NOW() - INTERVAL '90 days'
                GROUP BY dow, hour
                ORDER BY dow, hour
            """)
            lookup: dict[tuple[int, int], tuple[int, float]] = {
                (int(r["dow"]), int(r["hour"])): (int(r["total_count"]), float(r["avg_score"])) for r in cur.fetchall()
            }
            intraday_rhythm = []
            for dow in range(7):
                for hour in range(24):
                    count, avg_score = lookup.get((dow, hour), (0, 0.0))
                    intraday_rhythm.append({"dow": dow, "hour": hour, "count": count, "avg_score": avg_score})

            # ── 10. Investigation trend ──────────────────────────────────
            cur.execute("""
                SELECT
                    DATE(triggered_at)                                              AS day,
                    COUNT(*)                                                        AS triggered,
                    COUNT(*) FILTER (WHERE status = 'complete')                    AS completed,
                    COUNT(*) FILTER (WHERE status = 'failed')                      AS failed,
                    COUNT(*) FILTER (WHERE status = 'pending')                     AS pending,
                    ROUND(
                        COUNT(*) FILTER (WHERE status = 'complete')::numeric
                        / NULLIF(COUNT(*), 0) * 100, 1
                    )                                                               AS completion_rate,
                    ROUND(AVG(confidence_score)::numeric, 3)                       AS avg_confidence,
                    ROUND(
                        AVG(
                            EXTRACT(EPOCH FROM (completed_at - triggered_at)) / 3600.0
                        ) FILTER (WHERE completed_at IS NOT NULL)::numeric, 4
                    )                                                               AS avg_duration_hours
                FROM agent_investigations
                WHERE triggered_at >= NOW() - INTERVAL '30 days'
                GROUP BY DATE(triggered_at)
                ORDER BY day ASC
            """)
            investigation_trend = [
                {
                    "day": str(r["day"]),
                    "triggered": int(r["triggered"]),
                    "completed": int(r["completed"]),
                    "failed": int(r["failed"]),
                    "pending": int(r["pending"]),
                    "completion_rate": float(r["completion_rate"]) if r["completion_rate"] is not None else None,
                    "avg_confidence": float(r["avg_confidence"]) if r["avg_confidence"] is not None else None,
                    "avg_duration_hours": float(r["avg_duration_hours"])
                    if r["avg_duration_hours"] is not None
                    else None,
                }
                for r in cur.fetchall()
            ]

            # ── 11. Platform stats ───────────────────────────────────────
            cur.execute("""
                WITH monitored_user_counts AS (
                    SELECT COUNT(*) AS monitored_users FROM monitored_users
                ),
                enriched_anomaly_counts AS (
                    SELECT
                        COUNT(*) AS total_detections,
                        COUNT(*) FILTER (WHERE is_anomaly = TRUE) AS true_positives,
                        COUNT(*) FILTER (WHERE is_anomaly IS NOT NULL) AS labeled_records,
                        COUNT(DISTINCT root_cause) FILTER (WHERE root_cause IS NOT NULL) AS root_cause_count,
                        COUNT(DISTINCT user_id) FILTER (WHERE is_anomaly = TRUE) AS users_with_anomalies
                    FROM enriched_anomalies
                ),
                investigation_counts AS (
                    SELECT
                        COUNT(*) AS total_investigations,
                        COUNT(*) FILTER (WHERE status = 'completed') AS completed_investigations
                    FROM agent_investigations
                ),
                finding_counts AS (
                    SELECT COUNT(*) AS total_findings FROM agent_findings
                ),
                migration_counts AS (
                    SELECT COUNT(*) AS migration_count FROM schema_migrations
                )
                SELECT
                    muc.monitored_users, eac.total_detections, eac.true_positives,
                    eac.labeled_records, eac.root_cause_count,
                    ic.total_investigations, ic.completed_investigations,
                    fc.total_findings, mc.migration_count, eac.users_with_anomalies
                FROM monitored_user_counts muc
                CROSS JOIN enriched_anomaly_counts eac
                CROSS JOIN investigation_counts ic
                CROSS JOIN finding_counts fc
                CROSS JOIN migration_counts mc
            """)
            ps = cur.fetchone()
            platform_stats = {
                "monitoredUsers": int(ps["monitored_users"]),
                "totalDetections": int(ps["total_detections"]),
                "truePositives": int(ps["true_positives"]),
                "labeledRecords": int(ps["labeled_records"]),
                "rootCauseCount": int(ps["root_cause_count"]),
                "totalInvestigations": int(ps["total_investigations"]),
                "completedInvestigations": int(ps["completed_investigations"]),
                "totalFindings": int(ps["total_findings"]),
                "migrationCount": int(ps["migration_count"]),
                "usersWithAnomalies": int(ps["users_with_anomalies"]),
            }

    # Qdrant — best-effort, falls back to 0 if unavailable
    qdrant_docs = 0
    qdrant_collections = 0
    try:
        from qdrant_client import QdrantClient  # type: ignore[import]

        qc = QdrantClient(
            host=os.getenv("QDRANT_HOST", "localhost"),
            port=int(os.getenv("QDRANT_PORT", "6333")),
            api_key=os.getenv("QDRANT_API_KEY") or None,
            timeout=3,
        )
        cols = qc.get_collections().collections
        qdrant_collections = len(cols)
        for col in cols:
            info = qc.get_collection(col.name)
            qdrant_docs += info.points_count or 0
    except Exception as qe:
        logger.warning(f"Qdrant stats unavailable (snapshot): {qe}")

    platform_stats["qdrantDocuments"] = qdrant_docs
    platform_stats["qdrantCollections"] = qdrant_collections

    return {
        "stats": stats,
        "statsTrend": stats_trend,
        "recentAnomalies": recent_anomalies,
        "riskDistribution": risk_distribution,
        "topAnomalies": top_anomalies,
        "topUsers": top_users,
        "topRootCauses": top_root_causes,
        "activityHeatmap": activity_heatmap,
        "userMetrics": user_metrics,
        "systemMaturity": system_maturity,
        "intradayRhythm": intraday_rhythm,
        "investigationTrend": investigation_trend,
        "platformStats": platform_stats,
    }


@router.get("/snapshot")
def get_snapshot(_user: dict = Depends(get_current_user)):
    """All dashboard data in a single cached response.

    Returns the full payload needed by the dashboard page.
    Cached in-memory for SNAPSHOT_TTL seconds so concurrent
    clients share the same pre-computed result.
    """
    global _snapshot_cache, _snapshot_cache_ts

    now = time.monotonic()
    if _snapshot_cache is not None and (now - _snapshot_cache_ts) < SNAPSHOT_TTL:
        return _snapshot_cache

    with _snapshot_lock:
        # Double-check after acquiring lock (another thread may have refreshed)
        now = time.monotonic()
        if _snapshot_cache is not None and (now - _snapshot_cache_ts) < SNAPSHOT_TTL:
            return _snapshot_cache

        try:
            result = _build_snapshot()
            _snapshot_cache = result
            _snapshot_cache_ts = time.monotonic()
            return result
        except Exception as e:
            logger.error(f"Error building dashboard snapshot: {e}")
            raise HTTPException(status_code=500, detail="Database error") from e
