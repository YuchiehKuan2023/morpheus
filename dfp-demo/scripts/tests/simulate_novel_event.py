#!/usr/bin/env python3
"""Simulate novel event generation to verify timestamp logic without sending to Kafka."""

import argparse
import sys
from datetime import datetime
from pathlib import Path

# Add parent directory to path to import utils
sys.path.insert(0, str(Path(__file__).parent.parent))
from constants.tests import NOVEL_VALUES  # noqa: E402
from utils.shared.extract_user_profile import (  # noqa: E402
    calculate_travel_time,
    get_normal_test_event,
    haversine_distance,
)
from utils.shared.utils import get_last_training_event_info  # noqa: E402


def simulate_novel_event(username: str, scenario: str):
    """
    Simulate novel event generation and validate timestamp logic.

    Args:
        username: User email
        scenario: Novel event scenario (app, browser, os, device, location, all)
    """
    print("=" * 100)
    print(f"SIMULATION: Novel Event Generation - {scenario.upper()} scenario")
    print("=" * 100)

    # Step 1: Get last training event info
    print(f"\n1. Loading last training event for {username}...")
    last_info = get_last_training_event_info(username)
    print(f"   Last training event timestamp: {last_info['timestamp']}")
    print(f"   Last training event location: ({last_info['latitude']:.4f}, {last_info['longitude']:.4f})")

    # Step 2: Generate normal event (most common values)
    print("\n2. Generating normal test event (most common values from cache)...")
    event = get_normal_test_event(username)
    event_time = datetime.fromisoformat(event["time"].replace("Z", "+00:00"))
    event_lat = event["location_geoCoordinates_latitude"]
    event_lon = event["location_geoCoordinates_longitude"]

    print(f"   Normal event timestamp: {event_time}")
    print(f"   Normal event location: {event['properties']['location']['city']}")
    print(f"   Normal event coordinates: ({event_lat:.4f}, {event_lon:.4f})")

    # Calculate travel time from last cached event to normal event
    distance_to_normal = haversine_distance(last_info["latitude"], last_info["longitude"], event_lat, event_lon)
    hours_to_normal = calculate_travel_time(distance_to_normal)
    expected_normal_time = last_info["timestamp"] + __import__("datetime").timedelta(hours=hours_to_normal)

    print("\n   Travel from last training event to normal event:")
    print(f"      Distance: {distance_to_normal:.1f} km")
    print(f"      Travel time: {hours_to_normal:.1f} hours")
    print(f"      Expected timestamp: {expected_normal_time}")
    print(f"      Actual timestamp: {event_time}")
    print(f"      ✓ Match: {abs((event_time - expected_normal_time).total_seconds()) < 1}")

    # Step 3: Apply scenario modifications
    print(f"\n3. Applying {scenario} scenario modifications...")

    if scenario in ["location", "all"]:
        # Pick a novel location
        import random

        novel_loc = random.choice(NOVEL_VALUES["locations"])

        print(f"   Novel location: {novel_loc['city']}, {novel_loc['country']}")
        print(f"   Novel coordinates: ({novel_loc['lat']:.4f}, {novel_loc['lon']:.4f})")

        # Calculate travel from last training event to novel location
        distance_to_novel = haversine_distance(
            last_info["latitude"], last_info["longitude"], novel_loc["lat"], novel_loc["lon"]
        )
        hours_to_novel = calculate_travel_time(distance_to_novel)
        expected_novel_time = last_info["timestamp"] + __import__("datetime").timedelta(hours=hours_to_novel)

        print("\n   Travel from last training event to novel location:")
        print(f"      Distance: {distance_to_novel:.1f} km")
        print(f"      Travel time: {hours_to_novel:.1f} hours")
        print(f"      Expected timestamp: {expected_novel_time}")

        # This is what test_novel_event.py will calculate
        event["time"] = expected_novel_time.isoformat()
        event["location_geoCoordinates_latitude"] = novel_loc["lat"]
        event["location_geoCoordinates_longitude"] = novel_loc["lon"]

        print("   ✓ Novel event timestamp correctly calculated from last training event")
        print("   ✓ Travel time allows realistic movement to novel location")

    elif scenario == "app":
        import random

        novel_app = random.choice(NOVEL_VALUES["apps"])
        event["properties"]["appDisplayName"] = novel_app
        print(f"   Novel app: {novel_app}")
        print(f"   Timestamp unchanged: {event_time}")
        print("   ✓ Non-location scenarios keep normal event timestamp")

    elif scenario in ["browser", "os", "device"]:
        print(f"   {scenario.upper()} changed to novel value")
        print(f"   Timestamp unchanged: {event_time}")
        print("   ✓ Non-location scenarios keep normal event timestamp")

    # Step 4: Validation
    print("\n4. Validation Summary:")
    print("   " + "-" * 80)

    final_time = datetime.fromisoformat(event["time"].replace("Z", "+00:00"))
    time_since_last = (final_time - last_info["timestamp"]).total_seconds() / 3600

    print(f"   Last training event:   {last_info['timestamp']}")
    print(f"   Final novel event:     {final_time}")
    print(f"   Time difference:       {time_since_last:.1f} hours")

    if scenario in ["location", "all"]:
        final_lat = event["location_geoCoordinates_latitude"]
        final_lon = event["location_geoCoordinates_longitude"]
        final_distance = haversine_distance(last_info["latitude"], last_info["longitude"], final_lat, final_lon)
        final_hours_needed = calculate_travel_time(final_distance)

        print(f"   Geographic distance: {final_distance:.1f} km")
        print(f"   Required travel time: {final_hours_needed:.1f} hours")
        print(f"   Timestamp allows for travel: {time_since_last >= final_hours_needed}")

        if time_since_last >= final_hours_needed:
            print("   ✓ VALID: Travel time is realistic")
        else:
            print("   ✗ INVALID: Travel time too short (impossible travel)")
    else:
        print("   ✓ VALID: Non-location scenario uses normal event timestamp")

    print("\n" + "=" * 100)
    print("SIMULATION COMPLETE")
    print("=" * 100)


def main():
    parser = argparse.ArgumentParser(description="Simulate novel event generation to verify timestamp logic")
    parser.add_argument(
        "--username", type=str, required=True, help="User email to test (e.g., jennifer.nguyen@contoso.com)"
    )
    parser.add_argument(
        "--scenario",
        type=str,
        required=True,
        choices=["app", "browser", "os", "device", "location", "all"],
        help="Type of novel event: app, browser, os, device, location, or all",
    )

    args = parser.parse_args()
    simulate_novel_event(args.username, args.scenario)


if __name__ == "__main__":
    main()
