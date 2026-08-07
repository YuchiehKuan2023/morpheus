#!/usr/bin/env python3
"""Extract user profile from training data for creating realistic test events."""

import argparse
import json
import os
import uuid
from collections import Counter
from datetime import datetime, timezone
from math import atan2, cos, radians, sin, sqrt

# Training file path (relative to project root)
TRAINING_FILE = "data/input/train/azure_ad_train.jsonl"

from modules.utils.db import get_db_params  # noqa: E402

# DB connection — used when source='db' or source='auto'.
DB_CONFIG = get_db_params()


def haversine_distance(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """
    Calculate the great circle distance between two points on Earth (in kilometers).

    Args:
        lat1, lon1: Latitude and longitude of first point
        lat2, lon2: Latitude and longitude of second point

    Returns:
        Distance in kilometers
    """
    R = 6371  # Earth's radius in kilometers

    lat1, lon1, lat2, lon2 = map(radians, [lat1, lon1, lat2, lon2])
    dlat = lat2 - lat1
    dlon = lon2 - lon1

    a = sin(dlat / 2) ** 2 + cos(lat1) * cos(lat2) * sin(dlon / 2) ** 2
    c = 2 * atan2(sqrt(a), sqrt(1 - a))

    return R * c


def calculate_travel_time(distance_km: float) -> float:
    """
    Calculate realistic travel time based on distance.

    Args:
        distance_km: Distance in kilometers

    Returns:
        Hours needed for travel
    """
    if distance_km < 50:
        # Local travel - 1 hour minimum
        return 1
    elif distance_km < 500:
        # Regional travel - driving speed ~80 km/h
        return max(2, distance_km / 80)
    else:
        # Long distance - air travel ~800 km/h + 2 hour buffer
        return (distance_km / 800) + 2


def load_user_events_from_db(username: str) -> list[dict]:
    """
    Load all training events for *username* from the user_training_events table.

    Returns events as a list of dicts in the same Azure AD SignInLogs format
    as the JSONL file, ordered chronologically (oldest first).
    """
    import psycopg2

    conn = psycopg2.connect(**DB_CONFIG)
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT event FROM user_training_events WHERE user_id = %s ORDER BY event_time ASC",
                (username,),
            )
            return [row[0] for row in cur.fetchall()]
    finally:
        conn.close()


def extract_all_users_from_db() -> list[str]:
    """Return sorted list of all unique user_ids from the user_training_events table."""
    import psycopg2

    conn = psycopg2.connect(**DB_CONFIG)
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT DISTINCT user_id FROM user_training_events ORDER BY user_id")
            return [row[0] for row in cur.fetchall()]
    finally:
        conn.close()


def extract_user_profile(username: str, source: str = "auto") -> dict:
    """
    Extract user's behavioral profile from training data.

    Args:
        username : User email to analyze.
        source   : Where to load events from.
                   'db'    — query the user_training_events table (seed + feedback).
                   'jsonl' — read the original azure_ad_train.jsonl file.
                   'auto'  — try DB first; fall back to JSONL if DB is unreachable
                             or returns no events (default).

    Returns:
        Dict with user's apps, devices, locations, browsers, OS, etc.
        Structure is identical regardless of source.
    """
    # ── Load events from the chosen source ───────────────────────────────────
    if source == "db":
        user_events = load_user_events_from_db(username)
    elif source == "auto":
        try:
            user_events = load_user_events_from_db(username)
        except Exception:
            user_events = []
        if not user_events:
            # DB unavailable or no rows — fall back to JSONL.
            user_events = []
            with open(TRAINING_FILE) as f:
                for line in f:
                    event = json.loads(line)
                    if event.get("properties", {}).get("userPrincipalName") == username:
                        user_events.append(event)
    else:  # 'jsonl'
        user_events = []
        with open(TRAINING_FILE) as f:
            for line in f:
                event = json.loads(line)
                if event.get("properties", {}).get("userPrincipalName") == username:
                    user_events.append(event)

    if not user_events:
        raise ValueError(f"No events found for user: {username} (source={source})")

    print(f"Found {len(user_events)} events for {username} (source={source})\n")

    # Extract all attributes
    apps = []
    app_ids = []
    devices = []
    device_ids = []
    browsers = []
    os_list = []
    locations = []
    coords = []
    ips = []
    client_apps = []
    resources = []  # (resourceDisplayName, resourceId) pairs
    mfa_details = []  # (authMethod, authDetail) pairs
    asn_values = []  # autonomousSystemNumber integers
    user_display_name = ""
    user_id_guid = ""

    for event in user_events:
        props = event["properties"]

        # User identity constants (take first non-empty value)
        if not user_display_name:
            user_display_name = props.get("userDisplayName", "")
        if not user_id_guid:
            user_id_guid = props.get("userId", "")

        # Apps
        app = props.get("appDisplayName")
        app_id = props.get("appId")
        if app:
            apps.append(app)
            app_ids.append((app, app_id))

        # Devices
        device_detail = props.get("deviceDetail", {})
        device = device_detail.get("displayName")
        device_id = device_detail.get("deviceId")
        browser = device_detail.get("browser")
        os = device_detail.get("operatingSystem")

        if device:
            devices.append(device)
            device_ids.append((device, device_id if device_id else ""))
        if browser:
            browsers.append(browser)
        if os:
            os_list.append(os)

        # Locations
        location = props.get("location", {})
        city = location.get("city")
        state = location.get("state")
        country = location.get("countryOrRegion")
        geo = location.get("geoCoordinates", {})
        lat = geo.get("latitude")
        lon = geo.get("longitude")

        if city:
            loc_str = f"{city}, {state}, {country}"
            locations.append(loc_str)
            if lat is not None and lon is not None:
                coords.append((city, lat, lon))

        # Network
        ip = props.get("ipAddress")
        if ip:
            ips.append(ip)

        client = props.get("clientAppUsed")
        if client:
            client_apps.append(client)

        # Resource accessed
        res_name = props.get("resourceDisplayName", "")
        res_id = props.get("resourceId", "")
        if res_name:
            resources.append((res_name, res_id))

        # MFA detail
        mfa = props.get("mfaDetail", {})
        if mfa:
            mfa_details.append((mfa.get("authMethod", ""), mfa.get("authDetail", "")))

        # Autonomous system
        asn = props.get("autonomousSystemNumber")
        if asn is not None:
            asn_values.append(asn)

    # Count frequencies
    app_counts = Counter(apps)
    device_counts = Counter(devices)
    location_counts = Counter(locations)
    browser_counts = Counter(browsers)
    os_counts = Counter(os_list)
    ip_counts = Counter(ips)
    client_counts = Counter(client_apps)
    resource_counts = Counter(rn for rn, _ in resources)
    resource_ids = {rn: rid for rn, rid in resources if rid}  # name → id
    mfa_counts = Counter(mfa_details)
    asn_counts = Counter(asn_values)

    # Temporal distributions — use UTC hour and weekday from each event timestamp
    _WEEKDAY_NAMES = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
    hours_list: list[int] = []
    weekdays_list: list[str] = []
    for event in user_events:
        try:
            ts = event.get("time", "")
            # Handle both 'Z' suffix and '+00:00'
            ts_clean = ts.replace("Z", "+00:00")
            dt = datetime.fromisoformat(ts_clean).astimezone(timezone.utc)
            hours_list.append(dt.hour)
            weekdays_list.append(_WEEKDAY_NAMES[dt.weekday()])
        except (ValueError, AttributeError):
            pass

    hour_counts = Counter(hours_list)
    weekday_counts = Counter(weekdays_list)

    # Peak hours: top 5 most frequent, sorted ascending
    peak_hours = sorted([h for h, _ in hour_counts.most_common(5)])

    # Typical activity range: continuous block covering 90% of events, capped to reasonable span
    total_temporal = sum(hour_counts.values())
    if total_temporal > 0:
        threshold_5pct = max(1, total_temporal * 0.05)
        significant_hours = sorted([h for h, c in hour_counts.items() if c >= threshold_5pct])
        if significant_hours:
            end_hour = significant_hours[-1] + 1
            end_str = "24:00" if end_hour == 24 else f"{end_hour:02d}:00"
            active_range_str = f"{significant_hours[0]:02d}:00-{end_str} UTC"
        else:
            active_range_str = "N/A"
        # Hours that are genuinely inactive (<1% of events)
        inactive_threshold = max(1, total_temporal * 0.01)
        off_hours = sorted([h for h in range(24) if hour_counts.get(h, 0) < inactive_threshold])
    else:
        active_range_str = "N/A"
        off_hours = []

    # Typical days: weekdays with >=10% of events, ordered Mon→Sun
    weekday_threshold = max(1, total_temporal * 0.10)
    typical_days = [d for d in _WEEKDAY_NAMES if weekday_counts.get(d, 0) >= weekday_threshold]

    # Chronological last event (by timestamp, not file position)
    last_event_obj = max(user_events, key=lambda e: e.get("time", ""))

    # Most common resource and MFA
    most_common_resource = resource_counts.most_common(1)
    most_common_mfa = mfa_counts.most_common(1)
    most_common_asn = asn_counts.most_common(1)

    # Build profile
    profile = {
        "username": username,
        "total_events": len(user_events),
        "first_event": user_events[0]["time"],
        "last_event": last_event_obj["time"],
        # Identity constants — same for every event of this user
        "meta": {
            "user_display_name": user_display_name,
            "user_id_guid": user_id_guid,
            "resource_display_name": most_common_resource[0][0] if most_common_resource else "Microsoft 365",
            "resource_id_guid": resource_ids.get(most_common_resource[0][0], "") if most_common_resource else "",
            "mfa_auth_method": most_common_mfa[0][0][0] if most_common_mfa else "Phone App Notification",
            "mfa_auth_detail": most_common_mfa[0][0][1] if most_common_mfa else "Approved",
            "autonomous_system_number": most_common_asn[0][0] if most_common_asn else 0,
        },
        "apps": {
            "count": len(app_counts),
            "most_common": app_counts.most_common(5),
            "all": sorted(app_counts.items(), key=lambda x: (-x[1], x[0])),
        },
        "app_ids": dict(set(app_ids)),
        "devices": {
            "count": len(device_counts),
            "most_common": device_counts.most_common(3),
            "all": sorted(device_counts.items(), key=lambda x: (-x[1], x[0])),
        },
        "device_ids": dict(set(device_ids)),
        "browsers": {
            "count": len(browser_counts),
            "most_common": browser_counts.most_common(3),
            "all": sorted(browser_counts.items(), key=lambda x: (-x[1], x[0])),
        },
        "operating_systems": {
            "count": len(os_counts),
            "most_common": os_counts.most_common(3),
            "all": sorted(os_counts.items(), key=lambda x: (-x[1], x[0])),
        },
        "locations": {
            "count": len(location_counts),
            "most_common": location_counts.most_common(5),
            "all": sorted(location_counts.items(), key=lambda x: (-x[1], x[0])),
            "coordinates": sorted(set(coords), key=lambda x: x[0]),
        },
        "ips": {"count": len(ip_counts), "most_common": ip_counts.most_common(3)},
        "client_apps": {
            "count": len(client_counts),
            "most_common": client_counts.most_common(3),
            "all": sorted(client_counts.items(), key=lambda x: (-x[1], x[0])),
        },
        # Temporal activity patterns (UTC)
        "activity_hours_utc": {
            "distribution": dict(sorted(hour_counts.items())),
            "peak_hours": peak_hours,
            "typical_range": active_range_str,
            "off_hours": off_hours,
        },
        "active_days_of_week": {
            "distribution": {d: weekday_counts.get(d, 0) for d in _WEEKDAY_NAMES},
            "typical_days": typical_days,
        },
    }

    return profile


def get_normal_test_event(username: str) -> dict:
    """
    Generate a normal test event based on user's most common patterns.

    Emits a full Azure AD SignInLogs-format event matching the training data
    schema exactly, so the DFP autoencoder and all downstream enrichment
    stages receive the same field set as the original training events.

    Args:
        username: User email

    Returns:
        Dict representing a normal event with most common values, matching
        the complete training data format (all fields present).
    """
    profile = extract_user_profile(username)
    meta = profile["meta"]

    # Most common value per feature dimension
    most_app = profile["apps"]["most_common"][0][0]
    most_device = profile["devices"]["most_common"][0][0]
    most_browser = profile["browsers"]["most_common"][0][0]
    most_os = profile["operating_systems"]["most_common"][0][0]
    most_loc = profile["locations"]["most_common"][0][0]
    most_client = profile["client_apps"]["most_common"][0][0]
    most_ip = profile["ips"]["most_common"][0][0] if profile["ips"]["most_common"] else "10.0.0.1"

    # Parse location string "city, state, country"
    loc_parts = most_loc.split(", ")
    city = loc_parts[0] if len(loc_parts) > 0 else "Unknown"
    state = loc_parts[1] if len(loc_parts) > 1 else ""
    country = loc_parts[2] if len(loc_parts) > 2 else ""

    # Coordinates for most common location
    coords = (0.0, 0.0)
    for loc_city, lat, lon in profile["locations"]["coordinates"]:
        if loc_city == city:
            coords = (lat, lon)
            break

    # deviceId: use stored profile value, or generate a deterministic UUID
    # from username+device so the same user/device always produces the same ID.
    raw_device_id = profile["device_ids"].get(most_device, "")
    device_id = raw_device_id if raw_device_id else str(uuid.uuid5(uuid.NAMESPACE_DNS, f"{username}:{most_device}"))

    # Event timestamp: current time ensures the test event always lands after
    # all training history regardless of when it is sent.
    now = datetime.now(timezone.utc)
    now_iso = now.isoformat()
    event_id = str(uuid.uuid4())
    correlation_id = str(uuid.uuid4())

    location_block = {
        "city": city,
        "state": state,
        "countryOrRegion": country,
        "geoCoordinates": {"latitude": coords[0], "longitude": coords[1]},
    }

    # Full Azure AD SignInLogs training-format event
    event = {
        "time": now_iso,
        "category": "SignInLogs",
        "operationName": "Sign-in activity",
        "resultType": "0",
        "resultDescription": "Success",
        "durationMs": 0,
        "callerIpAddress": most_ip,
        "correlationId": correlation_id,
        "identity": username,
        "Level": 4,
        "location": location_block,
        "properties": {
            "id": event_id,
            "createdDateTime": now_iso,
            "userDisplayName": meta["user_display_name"],
            "userPrincipalName": username,
            "userId": meta["user_id_guid"],
            "appId": profile["app_ids"].get(most_app, ""),
            "appDisplayName": most_app,
            "ipAddress": most_ip,
            "clientAppUsed": most_client,
            "correlationId": correlation_id,
            "conditionalAccessStatus": "success",
            "isInteractive": True,
            "riskDetail": "none",
            "riskLevelAggregated": "none",
            "riskLevelDuringSignIn": "none",
            "riskState": "none",
            "resourceDisplayName": meta["resource_display_name"],
            "resourceId": meta["resource_id_guid"],
            "status": {"errorCode": 0, "failureReason": "None", "additionalDetails": "None"},
            "deviceDetail": {
                "deviceId": device_id,
                "displayName": most_device,
                "operatingSystem": most_os,
                "browser": most_browser,
                "isCompliant": True,
                "isManaged": True,
                "trustType": "Hybrid Azure AD joined",
            },
            "location": location_block,
            "mfaDetail": {
                "authMethod": meta["mfa_auth_method"],
                "authDetail": meta["mfa_auth_detail"],
            },
            "autonomousSystemNumber": meta["autonomous_system_number"],
        },
        "location_geoCoordinates_latitude": coords[0],
        "location_geoCoordinates_longitude": coords[1],
    }

    return event


def print_profile(profile: dict):
    """Pretty print user profile."""
    print("=" * 80)
    print(f"USER PROFILE: {profile['username']}")
    print("=" * 80)

    print(f"\nTotal events: {profile['total_events']}")
    print(f"Time range: {profile['first_event']} → {profile['last_event']}")

    print(f"\nAPPLICATIONS ({profile['apps']['count']} unique):")
    for app, count in profile["apps"]["most_common"]:
        pct = 100 * count / profile["total_events"]
        app_id = profile["app_ids"].get(app, "N/A")
        print(f"  • {app:40s} {count:4d} ({pct:5.1f}%)  [ID: {app_id}]")

    print(f"\nDEVICES ({profile['devices']['count']} unique):")
    for device, count in profile["devices"]["most_common"]:
        pct = 100 * count / profile["total_events"]
        device_id = profile["device_ids"].get(device, "N/A")
        print(f"  • {device:40s} {count:4d} ({pct:5.1f}%)  [ID: {device_id}]")

    print(f"\nBROWSERS ({profile['browsers']['count']} unique):")
    for browser, count in profile["browsers"]["most_common"]:
        pct = 100 * count / profile["total_events"]
        print(f"  • {browser:40s} {count:4d} ({pct:5.1f}%)")

    print(f"\nOPERATING SYSTEMS ({profile['operating_systems']['count']} unique):")
    for operating_system, count in profile["operating_systems"]["most_common"]:
        pct = 100 * count / profile["total_events"]
        print(f"  • {operating_system:40s} {count:4d} ({pct:5.1f}%)")

    print(f"\nLOCATIONS ({profile['locations']['count']} unique):")
    for loc, count in profile["locations"]["most_common"]:
        pct = 100 * count / profile["total_events"]
        print(f"  • {loc:40s} {count:4d} ({pct:5.1f}%)")

    if profile["locations"]["coordinates"]:
        print("\nCOORDINATES (for test events):")
        for city, lat, lon in profile["locations"]["coordinates"][:5]:
            print(f"  • {city:30s} lat={lat:.6f}, lon={lon:.6f}")

    print(f"\nCLIENT APPS ({profile['client_apps']['count']} unique):")
    for client, count in profile["client_apps"]["most_common"]:
        pct = 100 * count / profile["total_events"]
        print(f"  • {client:40s} {count:4d} ({pct:5.1f}%)")

    print(f"\nIP ADDRESSES ({profile['ips']['count']} unique):")
    for ip, count in profile["ips"]["most_common"]:
        pct = 100 * count / profile["total_events"]
        print(f"  • {ip:40s} {count:4d} ({pct:5.1f}%)")

    print("\n" + "=" * 80)
    print("RECOMMENDED TEST EVENT (most common values):")
    print("=" * 80)

    # Get most common of each
    most_app = profile["apps"]["most_common"][0][0]
    most_device = profile["devices"]["most_common"][0][0]
    most_browser = profile["browsers"]["most_common"][0][0]
    most_os = profile["operating_systems"]["most_common"][0][0]
    most_loc = profile["locations"]["most_common"][0][0]
    most_client = profile["client_apps"]["most_common"][0][0]
    most_ip = profile["ips"]["most_common"][0][0] if profile["ips"]["most_common"] else "192.168.1.1"

    # Get coordinates for most common location
    most_coords = None
    for city, lat, lon in profile["locations"]["coordinates"]:
        if city in most_loc:
            most_coords = (lat, lon)
            break

    print(
        f"""
  "userPrincipalName": "{profile["username"]}",
  "appDisplayName": "{most_app}",
  "appId": "{profile["app_ids"].get(most_app, "N/A")}",
  "deviceDetail": {{
    "displayName": "{most_device}",
    "browser": "{most_browser}",
    "operatingSystem": "{most_os}"
  }},
  "deviceDetail_deviceId": "{profile["device_ids"].get(most_device, "N/A")}",
  "location": {{
    "city": "{most_loc.split(",")[0].strip()}",
    "state": "{most_loc.split(",")[1].strip() if len(most_loc.split(",")) > 1 else ""}",
    "countryOrRegion": "{most_loc.split(",")[2].strip() if len(most_loc.split(",")) > 2 else ""}"
  }},
  "location_geoCoordinates_latitude": {most_coords[0] if most_coords else "N/A"},
  "location_geoCoordinates_longitude": {most_coords[1] if most_coords else "N/A"},
  "clientAppUsed": "{most_client}",
  "callerIpAddress": "{most_ip}",
  "statusfailureReason": ""
"""
    )


def extract_all_users() -> list[str]:
    """
    Extract list of all unique users from training data.

    Returns:
        List of user email addresses
    """
    users = set()
    with open(TRAINING_FILE) as f:
        for line in f:
            event = json.loads(line)
            user = event["properties"].get("userPrincipalName")
            if user:
                users.add(user)
    return sorted(users)


def main():
    parser = argparse.ArgumentParser(description="Extract user behavioral profile(s) from training data")

    parser.add_argument(
        "--username",
        type=str,
        help="User email to analyze (e.g., jennifer.nguyen@contoso.com). If not provided, extracts all users.",
    )

    parser.add_argument(
        "--all",
        action="store_true",
        help="Extract profiles for all users in training data (same as omitting --username)",
    )

    parser.add_argument(
        "--source",
        choices=["db", "jsonl", "auto"],
        default="db",
        help="Event source: 'db' (user_training_events table, default), 'jsonl' (original file), "
        "'auto' (DB with JSONL fallback)",
    )

    parser.add_argument(
        "--save",
        action="store_true",
        default=True,
        help="Save profile(s) to JSON files in data/output/profiles/ (default: True)",
    )

    parser.add_argument(
        "--no-save", action="store_false", dest="save", help="Do not save profile(s) to JSON, only print to console"
    )

    args = parser.parse_args()

    # Ensure output directory exists if saving
    if args.save:
        os.makedirs("data/output/profiles", exist_ok=True)

    source = args.source

    # Extract all users or single user
    if args.all or args.username is None:
        print(f"Extracting profiles for ALL users (source={source})...")
        print("=" * 80)

        users = extract_all_users_from_db() if source == "db" else extract_all_users()
        print(f"\nFound {len(users)} unique users\n")

        success_count = 0
        error_count = 0

        for i, username in enumerate(users, 1):
            try:
                print(f"[{i}/{len(users)}] Processing: {username}")
                profile = extract_user_profile(username, source=source)

                if args.save:
                    output_file = f"data/output/profiles/{username.replace('@', '_at_')}.json"
                    with open(output_file, "w") as f:
                        json.dump(profile, f, indent=2)
                    print(f"  ✓ Saved to: {output_file}")
                else:
                    print(f"  ✓ Profile extracted ({profile['total_events']} events)")

                success_count += 1

            except Exception as e:
                print(f"  ✗ Error: {e}")
                error_count += 1

            print()

        print("=" * 80)
        print(f"SUMMARY: {success_count} successful, {error_count} errors")
        print("=" * 80)

    else:
        # Single user extraction
        profile = extract_user_profile(args.username, source=source)

        # Print to console
        print_profile(profile)

        # Save profile if requested
        if args.save:
            output_file = f"data/output/profiles/{args.username.replace('@', '_at_')}.json"
            with open(output_file, "w") as f:
                json.dump(profile, f, indent=2)
            print(f"\nProfile saved to: {output_file}")


if __name__ == "__main__":
    main()
