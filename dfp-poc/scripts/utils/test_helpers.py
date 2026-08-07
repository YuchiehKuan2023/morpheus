"""Shared utility functions for DFP test scripts."""

import json
from datetime import datetime

from .test_constants import TRAINING_FILE


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
            json.loads(line) for line in f if json.loads(line)["properties"]["userPrincipalName"] == username
        ]

    if not user_events:
        raise ValueError(f"No events found for user: {username}")

    return user_events


def get_last_training_event_info(username: str) -> dict:
    """
    Get location and timestamp information from user's last training event.

    Args:
        username: User email

    Returns:
        Dict with keys: latitude, longitude, timestamp (datetime object)
    """
    user_events = load_user_events(username)
    last_event = user_events[-1]

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
