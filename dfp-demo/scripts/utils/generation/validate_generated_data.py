#!/usr/bin/env python3
"""
Comprehensive validation script for generated Azure AD data.
Checks every event, every field for inconsistencies, impossible travel, and data validity.
"""

import json
import sys
from collections import defaultdict
from datetime import datetime
from math import atan2, cos, radians, sin, sqrt


def haversine(lat1, lon1, lat2, lon2):
    """Calculate distance between two coordinates in km."""
    R = 6371  # Earth radius in km
    dlat = radians(lat2 - lat1)
    dlon = radians(lon2 - lon1)
    a = sin(dlat / 2) ** 2 + cos(radians(lat1)) * cos(radians(lat2)) * sin(dlon / 2) ** 2
    c = 2 * atan2(sqrt(a), sqrt(1 - a))
    return R * c


def validate_data(filepath):
    """Run comprehensive validation on generated data."""

    # Load all events
    events = []
    with open(filepath) as f:
        for line in f:
            events.append(json.loads(line))

    print("=" * 80)
    print("COMPREHENSIVE DATA VALIDATION - ALL EVENTS, ALL FIELDS")
    print("=" * 80)
    print(f"Total events: {len(events)}\n")

    issues = []

    # 1. APP CONSISTENCY CHECK
    print("1. APP CONSISTENCY (appId vs appDisplayName)")
    print("-" * 80)
    app_mappings = defaultdict(set)
    for e in events:
        app_name = e["properties"]["appDisplayName"]
        app_id = e["properties"]["appId"]
        app_mappings[app_name].add(app_id)

    inconsistent_apps = {name: ids for name, ids in app_mappings.items() if len(ids) > 1}
    if inconsistent_apps:
        print("INCONSISTENT: Same app has multiple appIds!")
        for app, ids in inconsistent_apps.items():
            print(f"   {app}: {len(ids)} different appIds")
            issues.append(f"App '{app}' has {len(ids)} different appIds")
    else:
        print("PASS: Each app has consistent appId")

    # 2. IMPOSSIBLE TRAVEL CHECK (PER USER)
    print("\n2. IMPOSSIBLE TRAVEL DETECTION (per user)")
    print("-" * 80)

    # Group events by user
    user_events = defaultdict(list)
    for e in events:
        user = e["properties"]["userPrincipalName"]
        user_events[user].append(e)

    # Sort each user's events by time
    for user in user_events:
        user_events[user].sort(key=lambda x: x["time"])

    impossible_travel = []
    for user, user_evts in user_events.items():
        for i in range(1, len(user_evts)):
            prev = user_evts[i - 1]
            curr = user_evts[i]

            prev_time = datetime.fromisoformat(prev["time"].replace("Z", "+00:00"))
            curr_time = datetime.fromisoformat(curr["time"].replace("Z", "+00:00"))
            time_diff_hours = (curr_time - prev_time).total_seconds() / 3600

            prev_lat = prev["properties"]["location"]["geoCoordinates"]["latitude"]
            prev_lon = prev["properties"]["location"]["geoCoordinates"]["longitude"]
            curr_lat = curr["properties"]["location"]["geoCoordinates"]["latitude"]
            curr_lon = curr["properties"]["location"]["geoCoordinates"]["longitude"]

            distance_km = haversine(prev_lat, prev_lon, curr_lat, curr_lon)

            if distance_km > 0:  # Location changed
                # Maximum realistic travel speed: 900 km/h (flight)
                required_speed = distance_km / time_diff_hours if time_diff_hours > 0 else float("inf")

                if required_speed > 900:
                    prev_city = prev["properties"]["location"]["city"]
                    curr_city = curr["properties"]["location"]["city"]
                    impossible_travel.append(
                        {
                            "user": user,
                            "event_pair": (i - 1, i),
                            "prev_time": prev_time,
                            "curr_time": curr_time,
                            "time_gap_hours": time_diff_hours,
                            "prev_location": prev_city,
                            "curr_location": curr_city,
                            "distance_km": distance_km,
                            "required_speed_kmh": required_speed,
                        }
                    )

    if impossible_travel:
        print(f"FOUND {len(impossible_travel)} IMPOSSIBLE TRAVEL INSTANCES:")
        for it in impossible_travel[:10]:  # Show first 10
            print(f"   {it['user']}:")
            print(f"     {it['prev_location']} → {it['curr_location']}")
            print(f"     Distance: {it['distance_km']:.1f} km in {it['time_gap_hours']:.2f} hours")
            print(f"     Required speed: {it['required_speed_kmh']:.0f} km/h (max realistic: 900 km/h)")
            issues.append(
                f"Impossible travel for {it['user']}: {it['prev_location']} → {it['curr_location']} at {it['required_speed_kmh']:.0f} km/h"
            )
    else:
        print("PASS: No impossible travel detected")

    # 3. DEVICE_ID CONSISTENCY
    print("\n3. DEVICE_ID CONSISTENCY")
    print("-" * 80)
    device_id_mappings = defaultdict(set)
    for e in events:
        device_name = e["properties"]["deviceDetail"]["displayName"]
        device_id = e["properties"]["deviceDetail"]["deviceId"]
        if device_id:  # Only check non-empty device_ids
            device_id_mappings[device_name].add(device_id)

    unstable_devices = {name: ids for name, ids in device_id_mappings.items() if len(ids) > 1}
    if unstable_devices:
        print("UNSTABLE: Device has multiple device_ids!")
        for device, ids in unstable_devices.items():
            print(f"   {device}: {len(ids)} different device_ids")
            issues.append(f"Device '{device}' has {len(ids)} different device_ids")
    else:
        print("PASS: All devices have stable device_id")

    # 4. CORRELATION_ID UNIQUENESS
    print("\n4. CORRELATION_ID UNIQUENESS")
    print("-" * 80)
    correlation_ids = [e["correlationId"] for e in events]
    if len(correlation_ids) == len(set(correlation_ids)):
        print("PASS: All correlationIds are unique")
    else:
        duplicates = len(correlation_ids) - len(set(correlation_ids))
        print(f"FAIL: {duplicates} duplicate correlationIds found")
        issues.append(f"{duplicates} duplicate correlationIds")

    # 5. TIMESTAMP ORDERING
    print("\n5. TIMESTAMP CHRONOLOGICAL ORDER")
    print("-" * 80)
    timestamps = [datetime.fromisoformat(e["time"].replace("Z", "+00:00")) for e in events]
    is_sorted = all(timestamps[i] <= timestamps[i + 1] for i in range(len(timestamps) - 1))
    if is_sorted:
        print("PASS: All timestamps in chronological order")
    else:
        print("FAIL: Timestamps are not in chronological order")
        issues.append("Timestamps not chronologically ordered")

    # 6. LOCATION COORDINATE VALIDATION
    print("\n6. LOCATION COORDINATE VALIDATION")
    print("-" * 80)
    invalid_coords = []
    for i, e in enumerate(events):
        lat = e["properties"]["location"]["geoCoordinates"]["latitude"]
        lon = e["properties"]["location"]["geoCoordinates"]["longitude"]
        if not (-90 <= lat <= 90 and -180 <= lon <= 180):
            invalid_coords.append((i, lat, lon))

    if invalid_coords:
        print(f"FAIL: {len(invalid_coords)} events with invalid coordinates")
        for idx, lat, lon in invalid_coords[:5]:
            print(f"   Event {idx}: lat={lat}, lon={lon}")
            issues.append(f"Event {idx} has invalid coordinates")
    else:
        print("PASS: All coordinates are valid")

    # 7. REQUIRED FIELDS PRESENCE
    print("\n7. REQUIRED FIELDS PRESENCE")
    print("-" * 80)
    required_fields = [
        "time",
        "category",
        "operationName",
        "resultType",
        "callerIpAddress",
        "correlationId",
        "identity",
    ]
    missing_fields = []
    for i, e in enumerate(events):
        for field in required_fields:
            if field not in e or not e[field]:
                missing_fields.append((i, field))

    if missing_fields:
        print(f"FAIL: {len(missing_fields)} missing required fields")
        for idx, field in missing_fields[:10]:
            print(f"   Event {idx}: missing '{field}'")
            issues.append(f"Event {idx} missing field '{field}'")
    else:
        print("PASS: All required fields present")

    # 8. IP ADDRESS VALIDATION
    print("\n8. IP ADDRESS VALIDATION")
    print("-" * 80)
    invalid_ips = []
    for i, e in enumerate(events):
        ip = e["callerIpAddress"]
        parts = ip.split(".")
        if len(parts) != 4 or not all(p.isdigit() and 0 <= int(p) <= 255 for p in parts):
            invalid_ips.append((i, ip))

    if invalid_ips:
        print(f"FAIL: {len(invalid_ips)} invalid IP addresses")
        for idx, ip in invalid_ips[:5]:
            print(f"   Event {idx}: {ip}")
            issues.append(f"Event {idx} has invalid IP: {ip}")
    else:
        print("PASS: All IP addresses valid")

    # 9. DEVICE/OS/BROWSER CONSISTENCY
    print("\n9. DEVICE/OS/BROWSER CONSISTENCY")
    print("-" * 80)
    device_profiles = defaultdict(lambda: {"os": set(), "browser": set()})
    for e in events:
        device = e["properties"]["deviceDetail"]["displayName"]
        os = e["properties"]["deviceDetail"]["operatingSystem"]
        browser = e["properties"]["deviceDetail"]["browser"]
        device_profiles[device]["os"].add(os)
        device_profiles[device]["browser"].add(browser)

    inconsistent_profiles = {d: p for d, p in device_profiles.items() if len(p["os"]) > 1 or len(p["browser"]) > 1}
    if inconsistent_profiles:
        print("INCONSISTENT: Device has multiple OS/browser combinations")
        for device, profile in inconsistent_profiles.items():
            print(f"   {device}:")
            if len(profile["os"]) > 1:
                print(f"     Multiple OS: {profile['os']}")
            if len(profile["browser"]) > 1:
                print(f"     Multiple browsers: {profile['browser']}")
            issues.append(f"Device '{device}' has inconsistent OS/browser")
    else:
        print("PASS: Each device has consistent OS/browser")

    # 10. LOGIN FAILURE VALIDATION
    print("\n10. LOGIN FAILURE DATA CONSISTENCY")
    print("-" * 80)
    failure_inconsistencies = []
    for i, e in enumerate(events):
        result_type = e["resultType"]
        error_code = e["properties"]["status"]["errorCode"]
        failure_reason = e["properties"]["status"]["failureReason"]

        # If resultType != '0', must have error details
        if result_type != "0":
            if error_code == 0 or failure_reason == "None":
                failure_inconsistencies.append(i)

    if failure_inconsistencies:
        print(f"FAIL: {len(failure_inconsistencies)} events with inconsistent failure data")
        for idx in failure_inconsistencies[:5]:
            e = events[idx]
            print(
                f"   Event {idx}: resultType={e['resultType']}, errorCode={e['properties']['status']['errorCode']}, reason={e['properties']['status']['failureReason']}"
            )
            issues.append(f"Event {idx} has inconsistent failure data")
    else:
        print("PASS: All failure data is consistent")

    # FINAL SUMMARY
    print("\n" + "=" * 80)
    print("VALIDATION SUMMARY")
    print("=" * 80)
    if issues:
        print(f"ERROR: VALIDATION FAILED: {len(issues)} issues found\n")
        print("Issues:")
        for issue in issues[:20]:  # Show first 20
            print(f"  • {issue}")
        if len(issues) > 20:
            print(f"  ... and {len(issues) - 20} more issues")
        return False
    else:
        print("OK: ALL CHECKS PASSED")
        print("Data is clean, consistent, and realistic!")
        return True


if __name__ == "__main__":
    default_path = "data/input/train/azure_ad_train.jsonl"
    filepath = sys.argv[1] if len(sys.argv) > 1 else default_path

    print(f"Validating: {filepath}\n")
    success = validate_data(filepath)
    sys.exit(0 if success else 1)
