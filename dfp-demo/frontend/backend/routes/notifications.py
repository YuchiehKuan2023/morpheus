import logging
from datetime import datetime, timezone

import psycopg2.extras
from auth_utils import get_current_user
from db import get_db
from fastapi import APIRouter, Depends, HTTPException, Query

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("")
def get_notifications(
    limit: int = Query(default=50, ge=1, le=200),
    user: dict = Depends(get_current_user),
):
    """List notifications for the current analyst, unread first."""
    try:
        with get_db() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(
                    """SELECT id, anomaly_id, type, title, message, seen_at, created_at
                       FROM analyst_notifications
                       WHERE analyst_id = %s
                       ORDER BY seen_at IS NOT NULL, created_at DESC
                       LIMIT %s""",
                    (user["id"], limit),
                )
                rows = cur.fetchall()
                return [
                    {
                        **dict(r),
                        "anomaly_id": str(r["anomaly_id"]) if r["anomaly_id"] else None,
                        "seen_at": r["seen_at"].isoformat() if r["seen_at"] else None,
                        "created_at": r["created_at"].isoformat() if r["created_at"] else None,
                    }
                    for r in rows
                ]
    except Exception as e:
        logger.error(f"Error fetching notifications: {e}")
        raise HTTPException(status_code=500, detail="Database error") from e


@router.get("/unread-count")
def get_unread_count(user: dict = Depends(get_current_user)):
    """Return count of unseen notifications for the current analyst."""
    try:
        with get_db() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT COUNT(*) FROM analyst_notifications WHERE analyst_id = %s AND seen_at IS NULL",
                    (user["id"],),
                )
                count = cur.fetchone()[0]
        return {"count": count}
    except Exception as e:
        logger.error(f"Error fetching unread count: {e}")
        raise HTTPException(status_code=500, detail="Database error") from e


@router.patch("/{notification_id}/seen")
def mark_seen(notification_id: int, user: dict = Depends(get_current_user)):
    """Mark a single notification as seen."""
    try:
        with get_db() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """UPDATE analyst_notifications
                       SET seen_at = %s
                       WHERE id = %s AND analyst_id = %s AND seen_at IS NULL""",
                    (datetime.now(timezone.utc), notification_id, user["id"]),
                )
            conn.commit()
        return {"status": "ok"}
    except Exception as e:
        logger.error(f"Error marking notification {notification_id} as seen: {e}")
        raise HTTPException(status_code=500, detail="Database error") from e


@router.patch("/seen-all")
def mark_all_seen(user: dict = Depends(get_current_user)):
    """Mark all unseen notifications as seen for the current analyst."""
    try:
        with get_db() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """UPDATE analyst_notifications
                       SET seen_at = %s
                       WHERE analyst_id = %s AND seen_at IS NULL""",
                    (datetime.now(timezone.utc), user["id"]),
                )
                updated = cur.rowcount
            conn.commit()
        return {"status": "ok", "marked": updated}
    except Exception as e:
        logger.error(f"Error marking all notifications as seen: {e}")
        raise HTTPException(status_code=500, detail="Database error") from e
