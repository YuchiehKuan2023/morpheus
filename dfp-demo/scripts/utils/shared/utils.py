"""Shared utility functions for the DFP pipeline.

Provides:
- JSON serialization helpers for pandas/numpy types
- Timestamp extraction from raw event dicts
- Training-event loading (DB-first, JSONL fallback)
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

try:
    from constants.tests import TRAINING_FILE
except ImportError:
    from scripts.constants.tests import TRAINING_FILE

from modules.utils.db import get_db_params

# ── DB config (mirrors dfp_feedback_service so scripts share the same DB) ──
_DB_CONFIG = get_db_params()


def to_jsonable(obj: Any) -> Any:
    """Recursively convert a value from pandas/numpy to JSON-safe Python primitives.

    Handles:
        - dict / list  (recursed)
        - NaN float    → None
        - datetime / Timestamp → ISO string
        - numpy integer, floating, bool_ → int / float / bool
        - numpy ndarray → list
        - everything else → returned as-is

    Args:
        obj: Any Python value, potentially containing numpy/pandas types.

    Returns:
        A JSON-serializable equivalent of ``obj``.
    """
    try:
        import numpy as np
    except ImportError:
        np = None  # type: ignore[assignment]

    if isinstance(obj, dict):
        return {k: to_jsonable(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [to_jsonable(v) for v in obj]
    if isinstance(obj, float) and obj != obj:  # NaN check (NaN != NaN)
        return None
    if not isinstance(obj, float) and hasattr(obj, "isoformat"):  # datetime / pandas Timestamp
        return obj.isoformat()
    if np is not None:
        if isinstance(obj, np.integer):
            return int(obj)
        if isinstance(obj, np.floating):
            return float(obj)
        if isinstance(obj, np.bool_):
            return bool(obj)
        if isinstance(obj, np.ndarray):
            return obj.tolist()
    return obj


def extract_event_timestamp(raw_event: dict[str, Any]) -> datetime | None:
    """
    Safely extract a datetime timestamp from a raw event dictionary.
    Tries a set of common timestamp keys and supports both datetime objects
    and ISO-8601-like strings (including those with a trailing 'Z').
    Returns None if no usable timestamp can be derived.
    """
    # Try a few common timestamp field names in order of preference.
    ts_value: Any = (
        raw_event.get("timestamp")
        or raw_event.get("time")
        or raw_event.get("eventTime")
        or raw_event.get("enqueuedTimeUtc")
    )
    if ts_value is None:
        return None
    if isinstance(ts_value, datetime):
        return ts_value
    if isinstance(ts_value, str):
        # Handle trailing 'Z' (UTC designator) if present.
        ts_str = ts_value
        if ts_str.endswith("Z"):
            ts_str = ts_str[:-1] + "+00:00"
        try:
            return datetime.fromisoformat(ts_str)
        except Exception:
            return None
    # Unsupported type
    return None


def load_user_events(username: str) -> list:
    """
    Load all events for a specific user from training data.

    Args:
        username: User email to filter by

    Returns:
        List of event dictionaries for the user
    """
    with open(TRAINING_FILE) as f:
        user_events = [
            e for line in f if (e := json.loads(line)) and e.get("properties", {}).get("userPrincipalName") == username
        ]

    if not user_events:
        raise ValueError(f"No events found for user: {username}")

    return user_events


def get_last_training_event_info(username: str) -> dict:
    """
    Get location and timestamp information from the user's most recent training event.

    Queries the user_training_events DB table first (includes seed + feedback events).
    Falls back to loading from the JSONL file if the table is unavailable or empty
    for this user.

    Args:
        username: User email (Azure AD userPrincipalName)

    Returns:
        Dict with keys: latitude, longitude, timestamp (datetime object)
    """
    # ── Try DB first ──────────────────────────────────────────────────────────
    try:
        import psycopg2

        conn = psycopg2.connect(**_DB_CONFIG)
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT event FROM user_training_events
                    WHERE user_id = %s
                    ORDER BY event_time DESC
                    LIMIT 1
                    """,
                    (username,),
                )
                row = cur.fetchone()
        finally:
            conn.close()

        if row:
            last_event = row[0]  # psycopg2 returns JSONB as a Python dict
            last_location = last_event.get("properties", {}).get("location", {})
            last_geo = last_location.get("geoCoordinates", {})
            time_str = last_event.get("time", "")
            last_time = (
                datetime.fromisoformat(time_str.replace("Z", "+00:00")) if time_str else datetime.now(timezone.utc)
            )
            return {
                "latitude": float(last_geo.get("latitude", 0)),
                "longitude": float(last_geo.get("longitude", 0)),
                "timestamp": last_time,
            }
    except Exception:
        pass  # fall through to JSONL

    # ── Fallback: load from JSONL ─────────────────────────────────────────────
    user_events = load_user_events(username)
    # Select chronologically last event by timestamp, not by file position.
    # File position is not reliable: feedback events appended later may have
    # earlier timestamps than the original training events.
    last_event = max(user_events, key=lambda e: e.get("time", ""))

    last_location = last_event["properties"].get("location", {})
    last_geo = last_location.get("geoCoordinates", {})
    last_lat = last_geo.get("latitude", 0.0)
    last_lon = last_geo.get("longitude", 0.0)
    last_time = datetime.fromisoformat(last_event["time"].replace("Z", "+00:00"))

    return {
        "latitude": last_lat,
        "longitude": last_lon,
        "timestamp": last_time,
    }
