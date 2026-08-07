#!/usr/bin/env python3
"""Extract user profile from training data for creating realistic test events."""

import argparse
import json
from collections import Counter
from datetime import timedelta
from math import atan2, cos, radians, sin, sqrt


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


def extract_user_profile(username: str) -> dict:
    """
    Extract user's behavioral profile from training data.

    Args:
        training_file: Path to training JSONL file
        username: User email to analyze

    Returns:
        Dict with user's apps, devices, locations, browsers, OS, etc.
    """
    # Import here to avoid module-level import issues
    from utils.test_constants import TRAINING_FILE

    user_events = []

    # Load user's events
    with open(TRAINING_FILE) as f:
        for line in f:
            event = json.loads(line)
            if event["properties"]["userPrincipalName"] == username:
                user_events.append(event)

    if not user_events:
        raise ValueError(f"No events found for user: {username}")

    print(f"Found {len(user_events)} events for {username}\n")

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

    for event in user_events:
        props = event["properties"]

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
            device_ids.append((device, device_id if device_id else "N/A"))
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

    # Count frequencies
    app_counts = Counter(apps)
    device_counts = Counter(devices)
    location_counts = Counter(locations)
    browser_counts = Counter(browsers)
    os_counts = Counter(os_list)
    ip_counts = Counter(ips)
    client_counts = Counter(client_apps)

    # Build profile
    profile = {
        "username": username,
        "total_events": len(user_events),
        "first_event": user_events[0]["time"],
        "last_event": user_events[-1]["time"],
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
    }

    return profile


def get_normal_test_event(username: str) -> dict:
    """
    Generate a normal test event based on user's most common patterns.

    Uses user's last training event as baseline for timestamp calculation.

    Args:
        username: User email

    Returns:
        Dict representing a normal event with most common values, matching training data format
    """
    # Import here to avoid module-level import issues
    from utils.test_helpers import get_last_training_event_info

    profile = extract_user_profile(username)

    # Get most common of each attribute
    most_app = profile["apps"]["most_common"][0][0]
    most_device = profile["devices"]["most_common"][0][0]
    most_browser = profile["browsers"]["most_common"][0][0]
    most_os = profile["operating_systems"]["most_common"][0][0]
    most_loc = profile["locations"]["most_common"][0][0]
    most_client = profile["client_apps"]["most_common"][0][0]
    most_ip = profile["ips"]["most_common"][0][0] if profile["ips"]["most_common"] else "10.0.0.1"

    # Parse location string
    loc_parts = most_loc.split(", ")
    city = loc_parts[0] if len(loc_parts) > 0 else "Unknown"
    state = loc_parts[1] if len(loc_parts) > 1 else ""
    country = loc_parts[2] if len(loc_parts) > 2 else ""

    # Get coordinates for most common location
    coords = None
    for loc_city, lat, lon in profile["locations"]["coordinates"]:
        if loc_city == city:
            coords = (lat, lon)
            break

    if not coords:
        coords = (0.0, 0.0)

    # Get last training event's location to calculate realistic travel time
    last_info = get_last_training_event_info(username)
    last_lat = last_info["latitude"]
    last_lon = last_info["longitude"]
    last_event_time = last_info["timestamp"]

    # Calculate distance between last event and test event location
    distance_km = haversine_distance(last_lat, last_lon, coords[0], coords[1])

    # Calculate realistic travel time based on distance
    hours_needed = calculate_travel_time(distance_km)

    # Add extra buffer to ensure test event is well-separated from training events
    # This prevents impossible travel detection when multiple training events are close together
    hours_needed = max(hours_needed, 2.0)  # Minimum 2 hours between events

    # Generate timestamp AFTER the user's last event with realistic travel time
    test_event_time = last_event_time + timedelta(hours=hours_needed)

    # Build normal test event matching training data structure
    event = {
        "time": test_event_time.isoformat(),
        "identity": username,
        "properties": {
            "appDisplayName": most_app,
            "appId": profile["app_ids"].get(most_app, ""),
            "clientAppUsed": most_client,
            "ipAddress": most_ip,
            "userPrincipalName": username,
            "location": {
                "city": city,
                "state": state,
                "countryOrRegion": country,
                "geoCoordinates": {"latitude": coords[0], "longitude": coords[1]},
            },
            "deviceDetail": {
                "displayName": most_device,
                "deviceId": profile["device_ids"].get(most_device, ""),
                "browser": most_browser,
                "operatingSystem": most_os,
                "isCompliant": True,
                "isManaged": True,
                "trustType": "Hybrid Azure AD joined",
            },
            "status": {"errorCode": 0, "failureReason": "None"},
        },
        # Location at ROOT level (not just in properties) - matches training data format
        "location": {
            "city": city,
            "state": state,
            "countryOrRegion": country,
            "geoCoordinates": {"latitude": coords[0], "longitude": coords[1]},
        },
        # Also include flattened coordinates at root for source schema preservation
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
    for os, count in profile["operating_systems"]["most_common"]:
        pct = 100 * count / profile["total_events"]
        print(f"  • {os:40s} {count:4d} ({pct:5.1f}%)")

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
    # Import here to avoid module-level import issues
    from utils.test_constants import TRAINING_FILE

    users = set()
    with open(TRAINING_FILE) as f:
        for line in f:
            event = json.loads(line)
            user = event["properties"].get("userPrincipalName")
            if user:
                users.add(user)
    return sorted(users)


def main():
    import os

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

    # Extract all users or single user
    if args.all or args.username is None:
        print("Extracting profiles for ALL users in training data...")
        print("=" * 80)

        users = extract_all_users()
        print(f"\nFound {len(users)} unique users\n")

        success_count = 0
        error_count = 0

        for i, username in enumerate(users, 1):
            try:
                print(f"[{i}/{len(users)}] Processing: {username}")
                profile = extract_user_profile(username)

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
        profile = extract_user_profile(args.username)

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
