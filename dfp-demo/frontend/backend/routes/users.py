import logging

import psycopg2.extras
from auth_utils import get_current_user
from db import get_db
from fastapi import APIRouter, Depends, HTTPException, Query

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("")
def get_users(_user: dict = Depends(get_current_user)):
    try:
        with get_db() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute("""
                    SELECT
                        mu.*,
                        COUNT(ea.anomaly_id)                                          AS anomaly_count,
                        MAX(ea.timestamp)                                             AS last_anomaly_at,
                        ROUND(COALESCE(AVG(ea.risk_score), 0)::numeric, 4)           AS avg_risk_score,
                        COUNT(ea.anomaly_id) FILTER (WHERE ea.severity = 'CRITICAL') AS critical_count
                    FROM monitored_users mu
                    LEFT JOIN enriched_anomalies ea ON ea.user_id = mu.username
                    GROUP BY mu.id
                    ORDER BY avg_risk_score DESC, anomaly_count DESC
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
                    d["avg_risk_score"] = float(d["avg_risk_score"])
                    result.append(d)
                return result
    except Exception as e:
        logger.error(f"Error fetching users: {e}")
        raise HTTPException(status_code=500, detail="Database error") from e


@router.get("/{username}/trend")
def get_user_trend(username: str, days: int = 0, _user: dict = Depends(get_current_user)):
    """Daily anomaly count and avg score for a specific user.
    days=0 (default) returns all-time data; days>0 limits to the last N days.
    """
    try:
        with get_db() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                if days > 0:
                    days = min(days, 3650)  # hard cap at 10 years
                    cur.execute(
                        """
                        SELECT
                            DATE_TRUNC('day', timestamp)::date        AS bucket,
                            COUNT(*)                                  AS count,
                            ROUND(AVG(anomaly_score)::numeric, 2)    AS avg_score
                        FROM enriched_anomalies
                        WHERE user_id = %s
                          AND timestamp >= NOW() - (%s * INTERVAL '1 day')
                        GROUP BY bucket
                        ORDER BY bucket
                        """,
                        (username, days),
                    )
                else:
                    cur.execute(
                        """
                        SELECT
                            DATE_TRUNC('day', timestamp)::date        AS bucket,
                            COUNT(*)                                  AS count,
                            ROUND(AVG(anomaly_score)::numeric, 2)    AS avg_score
                        FROM enriched_anomalies
                        WHERE user_id = %s
                        GROUP BY bucket
                        ORDER BY bucket
                        """,
                        (username,),
                    )
                rows = cur.fetchall()
                return [
                    {
                        "bucket": str(r["bucket"]),
                        "count": int(r["count"]),
                        "avg_score": float(r["avg_score"]),
                    }
                    for r in rows
                ]
    except Exception as e:
        logger.error(f"Error fetching trend for user {username}: {e}")
        raise HTTPException(status_code=500, detail="Database error") from e


@router.get("/{username}/anomalies")
def get_user_anomalies(
    username: str,
    page: int = Query(1, ge=1),
    page_size: int = Query(9, ge=1, le=100),
    sort_by: str = Query("timestamp", pattern="^(timestamp|severity|risk_score|anomaly_score)$"),
    sort_dir: str = Query("desc", pattern="^(asc|desc)$"),
    root_cause: str = Query(None),
    sub_category: str = Query(None),
    _user: dict = Depends(get_current_user),
):
    """Paginated, sorted, filtered anomalies for a user."""
    try:
        with get_db() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                # Build WHERE clause
                conditions = ["user_id = %s"]
                params: list = [username]

                if root_cause:
                    conditions.append("root_cause = %s")
                    params.append(root_cause)
                if sub_category:
                    conditions.append("sub_category = %s")
                    params.append(sub_category)

                where = " AND ".join(conditions)

                # Count total
                cur.execute(f"SELECT COUNT(*) FROM enriched_anomalies WHERE {where}", params)
                total_items = cur.fetchone()["count"]

                # Root-cause options: counts filtered by current sub_category
                rc_conditions = ["user_id = %s", "root_cause IS NOT NULL"]
                rc_params: list = [username]
                if sub_category:
                    rc_conditions.append("sub_category = %s")
                    rc_params.append(sub_category)
                cur.execute(
                    f"""
                    SELECT root_cause AS value, COUNT(*) AS count
                    FROM enriched_anomalies
                    WHERE {" AND ".join(rc_conditions)}
                    GROUP BY root_cause
                    ORDER BY root_cause
                    """,
                    rc_params,
                )
                root_cause_options = [{"value": r["value"], "count": int(r["count"])} for r in cur.fetchall()]

                # Sub-category options: counts filtered by current root_cause
                sc_conditions = ["user_id = %s", "sub_category IS NOT NULL"]
                sc_params: list = [username]
                if root_cause:
                    sc_conditions.append("root_cause = %s")
                    sc_params.append(root_cause)
                cur.execute(
                    f"""
                    SELECT sub_category AS value, COUNT(*) AS count
                    FROM enriched_anomalies
                    WHERE {" AND ".join(sc_conditions)}
                    GROUP BY sub_category
                    ORDER BY sub_category
                    """,
                    sc_params,
                )
                sub_category_options = [{"value": r["value"], "count": int(r["count"])} for r in cur.fetchall()]

                # Sort mapping
                if sort_by == "severity":
                    order_clause = (
                        f"CASE LOWER(severity) "
                        f"WHEN 'critical' THEN 4 WHEN 'high' THEN 3 "
                        f"WHEN 'medium' THEN 2 WHEN 'low' THEN 1 ELSE 0 END "
                        f"{'DESC' if sort_dir == 'desc' else 'ASC'}"
                    )
                else:
                    col_map = {
                        "timestamp": "timestamp",
                        "risk_score": "risk_score",
                        "anomaly_score": "anomaly_score",
                    }

                    order_clause = f"{col_map[sort_by]} {'DESC' if sort_dir == 'desc' else 'ASC'} NULLS LAST"

                offset = (page - 1) * page_size
                cur.execute(
                    f"""
                    SELECT
                        anomaly_id::text,
                        anomaly_score,
                        LOWER(severity) AS severity,
                        root_cause,
                        sub_category,
                        risk_score,
                        status,
                        timestamp,
                        ai_enrichment
                    FROM enriched_anomalies
                    WHERE {where}
                    ORDER BY {order_clause}
                    LIMIT %s OFFSET %s
                    """,
                    params + [page_size, offset],
                )
                rows = cur.fetchall()

        # Process anomalies
        items = []
        for row in rows:
            ai_raw = row["ai_enrichment"] or {}
            similar_count = len(ai_raw.get("similar_detections") or [])

            raw_gc = ai_raw.get("graph_context") or {}
            trimmed_gc = None
            if raw_gc:
                trimmed_gc = {
                    "detected_ips": list(raw_gc.get("detected_ips") or []),
                    "detected_devices": list(raw_gc.get("detected_devices") or []),
                    "detected_browsers": list(raw_gc.get("detected_browsers") or []),
                    "detected_locations": list(raw_gc.get("detected_locations") or []),
                    "detected_client_apps": list(raw_gc.get("detected_client_apps") or []),
                    "detected_applications": list(raw_gc.get("detected_applications") or []),
                    "detected_operating_systems": list(raw_gc.get("detected_operating_systems") or []),
                    "recent_detections": int(raw_gc.get("recent_detections") or 0),
                    "related_anomalies_count": int(raw_gc.get("related_anomalies_count") or 0),
                }

            items.append(
                {
                    "anomaly_id": row["anomaly_id"],
                    "anomaly_score": float(row["anomaly_score"]),
                    "severity": row["severity"],
                    "root_cause": row["root_cause"],
                    "sub_category": row["sub_category"],
                    "risk_score": float(row["risk_score"]) if row["risk_score"] is not None else None,
                    "status": row["status"],
                    "timestamp": row["timestamp"].isoformat() if row["timestamp"] else None,
                    "similar_detections_count": similar_count,
                    "graph_context": trimmed_gc,
                }
            )

        total_pages = max(1, -(-total_items // page_size))  # ceil division

        return {
            "items": items,
            "page": page,
            "pageSize": page_size,
            "totalItems": total_items,
            "totalPages": total_pages,
            "filters": {
                "rootCauses": root_cause_options,
                "subCategories": sub_category_options,
            },
        }

    except Exception as e:
        logger.error(f"Error fetching anomalies for user {username}: {e}")
        raise HTTPException(status_code=500, detail="Database error") from e


@router.get("/{username}/full")
def get_user_full(username: str, _user: dict = Depends(get_current_user)):
    """Full user detail: profile + all anomalies (trimmed ai_enrichment) +
    user_baseline extracted once + graph_context_combined + daily trend.
    """
    try:
        with get_db() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                # ── 1. User profile + aggregates ──────────────────────────────
                cur.execute(
                    """
                    SELECT
                        mu.*,
                        COUNT(ea.anomaly_id)                                              AS anomaly_count,
                        MAX(ea.timestamp)                                                 AS last_anomaly_at,
                        ROUND(COALESCE(AVG(ea.anomaly_score), 0)::numeric, 4)            AS avg_anomaly_score,
                        COUNT(ea.anomaly_id) FILTER (WHERE ea.severity = 'CRITICAL')     AS critical_count
                    FROM monitored_users mu
                    LEFT JOIN enriched_anomalies ea ON ea.user_id = mu.username
                    WHERE mu.username = %s
                    GROUP BY mu.id
                    """,
                    (username,),
                )
                user_row = cur.fetchone()
                if not user_row:
                    raise HTTPException(status_code=404, detail="User not found")

                profile = dict(user_row)
                for ts_col in ("created_at", "updated_at", "last_anomaly_at"):
                    if profile.get(ts_col):
                        profile[ts_col] = profile[ts_col].isoformat()
                profile["anomaly_count"] = int(profile["anomaly_count"])
                profile["critical_count"] = int(profile["critical_count"])
                profile["avg_anomaly_score"] = float(profile["avg_anomaly_score"])

                # ── 2. Daily trend ─────────────────────────────────────────────
                cur.execute(
                    """
                    SELECT
                        DATE_TRUNC('day', timestamp)::date     AS bucket,
                        COUNT(*)                               AS count,
                        ROUND(AVG(anomaly_score)::numeric, 2)  AS avg_score
                    FROM enriched_anomalies
                    WHERE user_id = %s
                    GROUP BY bucket
                    ORDER BY bucket
                    """,
                    (username,),
                )
                trend = [
                    {"bucket": str(r["bucket"]), "count": int(r["count"]), "avg_score": float(r["avg_score"])}
                    for r in cur.fetchall()
                ]

                # ── 3. All anomalies (raw, with full ai_enrichment JSONB) ──────
                cur.execute(
                    """
                    SELECT
                        anomaly_id::text,
                        anomaly_score,
                        LOWER(severity)   AS severity,
                        root_cause,
                        sub_category,
                        risk_score,
                        status,
                        timestamp,
                        ai_enrichment,
                        original_event->'location' AS event_location
                    FROM enriched_anomalies
                    WHERE user_id = %s
                    ORDER BY anomaly_score DESC
                    """,
                    (username,),
                )
                raw_anomalies = cur.fetchall()

        # ── 4. Process anomalies outside DB cursor ─────────────────────────
        all_anomalies = []
        user_baseline = None
        gc_combined: dict = {
            "detected_ips": set(),
            "detected_devices": set(),
            "detected_browsers": set(),
            "detected_locations": set(),
            "detected_client_apps": set(),
            "detected_applications": set(),
            "detected_operating_systems": set(),
            "detected_location_coords": {},
            "total_recent_detections": 0,
        }

        for row in raw_anomalies:
            ai_raw = row["ai_enrichment"] or {}

            # Extract location coordinates from the raw event for the map
            event_loc = row.get("event_location") or {}
            if event_loc:
                loc_city = event_loc.get("city")
                loc_country = event_loc.get("countryOrRegion")
                geo = event_loc.get("geoCoordinates") or {}
                loc_lat = geo.get("latitude")
                loc_lon = geo.get("longitude")
                if loc_city and loc_country and loc_lat is not None and loc_lon is not None:
                    loc_key = f"{loc_city}, {loc_country}"
                    if loc_key not in gc_combined["detected_location_coords"]:
                        gc_combined["detected_location_coords"][loc_key] = {
                            "lat": loc_lat,
                            "lon": loc_lon,
                        }

            # Extract graph_context — strip detection_relationships
            raw_gc = ai_raw.get("graph_context") or {}
            trimmed_gc = None
            if raw_gc:
                trimmed_gc = {
                    "detected_ips": list(raw_gc.get("detected_ips") or []),
                    "detected_devices": list(raw_gc.get("detected_devices") or []),
                    "detected_browsers": list(raw_gc.get("detected_browsers") or []),
                    "detected_locations": list(raw_gc.get("detected_locations") or []),
                    "detected_client_apps": list(raw_gc.get("detected_client_apps") or []),
                    "detected_applications": list(raw_gc.get("detected_applications") or []),
                    "detected_operating_systems": list(raw_gc.get("detected_operating_systems") or []),
                    "recent_detections": int(raw_gc.get("recent_detections") or 0),
                    "related_anomalies_count": int(raw_gc.get("related_anomalies_count") or 0),
                }
                # Accumulate into combined
                for key in (
                    "detected_ips",
                    "detected_devices",
                    "detected_browsers",
                    "detected_locations",
                    "detected_client_apps",
                    "detected_applications",
                    "detected_operating_systems",
                ):
                    gc_combined[key].update(trimmed_gc[key])
                gc_combined["total_recent_detections"] += trimmed_gc["recent_detections"]

            # Extract user_baseline once from first anomaly that has a non-empty one
            if user_baseline is None:
                raw_baseline = ai_raw.get("user_baseline") or {}
                if raw_baseline:
                    user_baseline = raw_baseline

            similar_count = len(ai_raw.get("similar_detections") or [])

            all_anomalies.append(
                {
                    "anomaly_id": row["anomaly_id"],
                    "anomaly_score": float(row["anomaly_score"]),
                    "severity": row["severity"],
                    "root_cause": row["root_cause"],
                    "sub_category": row["sub_category"],
                    "risk_score": float(row["risk_score"]) if row["risk_score"] is not None else None,
                    "status": row["status"],
                    "timestamp": row["timestamp"].isoformat() if row["timestamp"] else None,
                    "similar_detections_count": similar_count,
                    "graph_context": trimmed_gc,
                }
            )

        # Convert sets → sorted lists for JSON serialisation
        graph_context_combined = (
            {k: sorted(v) if isinstance(v, set) else v for k, v in gc_combined.items()}
            if any(isinstance(v, set) and v for v in gc_combined.values())
            else None
        )

        return {
            **profile,
            "trend": trend,
            "all_anomalies": all_anomalies,
            "user_baseline": user_baseline,
            "graph_context_combined": graph_context_combined,
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching full detail for user {username}: {e}")
        raise HTTPException(status_code=500, detail="Database error") from e


@router.get("/{username:path}")
def get_user(username: str, _user: dict = Depends(get_current_user)):
    try:
        with get_db() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(
                    """
                    SELECT
                        mu.*,
                        COUNT(ea.anomaly_id)                                          AS anomaly_count,
                        MAX(ea.timestamp)                                             AS last_anomaly_at,
                        ROUND(COALESCE(AVG(ea.risk_score), 0)::numeric, 4)           AS avg_risk_score,
                        COUNT(ea.anomaly_id) FILTER (WHERE ea.severity = 'CRITICAL') AS critical_count
                    FROM monitored_users mu
                    LEFT JOIN enriched_anomalies ea ON ea.user_id = mu.username
                    WHERE mu.username = %s
                    GROUP BY mu.id
                    """,
                    (username,),
                )
                row = cur.fetchone()
                if not row:
                    raise HTTPException(status_code=404, detail="User not found")
                d = dict(row)
                for ts_col in ("created_at", "updated_at", "last_anomaly_at"):
                    if d.get(ts_col):
                        d[ts_col] = d[ts_col].isoformat()
                d["anomaly_count"] = int(d["anomaly_count"])
                d["critical_count"] = int(d["critical_count"])
                d["avg_risk_score"] = float(d["avg_risk_score"])
                return d
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching user {username}: {e}")
        raise HTTPException(status_code=500, detail="Database error") from e
