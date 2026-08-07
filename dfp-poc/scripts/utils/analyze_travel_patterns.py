#!/usr/bin/env python3
"""
Analyze travel patterns in generated Azure AD data.
Validates distance, time, speed, and stay duration for all location changes.
"""

import json
import sys
from collections import Counter
from datetime import datetime
from math import atan2, cos, radians, sin, sqrt


def haversine(lat1, lon1, lat2, lon2):
    """Calculate distance between two coordinates in km."""
    R = 6371
    dlat = radians(lat2 - lat1)
    dlon = radians(lon2 - lon1)
    a = sin(dlat / 2) ** 2 + cos(radians(lat1)) * cos(radians(lat2)) * sin(dlon / 2) ** 2
    c = 2 * atan2(sqrt(a), sqrt(1 - a))
    return R * c


def get_travel_mode(distance_km, time_hours):
    """Determine likely travel mode based on distance and time."""
    if time_hours == 0:
        return "INSTANT"
    speed = distance_km / time_hours

    if distance_km < 50:
        if speed < 60:
            return "Local (car/taxi)"
        else:
            return "Local (fast)"
    elif distance_km < 200:
        if speed < 100:
            return "Regional (car/train)"
        else:
            return "Regional (fast train)"
    elif distance_km < 500:
        if speed < 150:
            return "Long regional (train)"
        else:
            return "Short flight"
    else:
        if speed < 700:
            return "Long flight"
        else:
            return "Very fast flight"


def analyze_travel_patterns(filepath):
    """Analyze travel patterns for all users."""

    # Load events
    events = []
    with open(filepath) as f:
        for line in f:
            events.append(json.loads(line))

    # Group by user
    user_events = {}
    for e in events:
        user = e["properties"]["userPrincipalName"]
        if user not in user_events:
            user_events[user] = []
        user_events[user].append(e)

    # Sort each user's events
    for user in user_events:
        user_events[user].sort(key=lambda x: x["time"])

    print("=" * 80)
    print("TRAVEL ANALYSIS - ALL LOCATION CHANGES PER USER")
    print("=" * 80)

    for user, user_evts in sorted(user_events.items()):
        print(f"\n{'=' * 80}")
        print(f"USER: {user}")
        print(f"{'=' * 80}")
        print(f"Total events: {len(user_evts)}")

        travels = []
        location_stays = []
        current_location: str | None = None
        location_start_time: datetime | None = None

        for i, e in enumerate(user_evts):
            loc = e["properties"]["location"]["city"]
            time = datetime.fromisoformat(e["time"].replace("Z", "+00:00"))

            if i == 0:
                current_location = loc
                location_start_time = time
                continue

            if loc != current_location and location_start_time is not None:
                # Location changed - record travel
                prev = user_evts[i - 1]

                prev_time = datetime.fromisoformat(prev["time"].replace("Z", "+00:00"))
                time_diff = (time - prev_time).total_seconds() / 3600

                prev_lat = prev["properties"]["location"]["geoCoordinates"]["latitude"]
                prev_lon = prev["properties"]["location"]["geoCoordinates"]["longitude"]
                curr_lat = e["properties"]["location"]["geoCoordinates"]["latitude"]
                curr_lon = e["properties"]["location"]["geoCoordinates"]["longitude"]

                distance = haversine(prev_lat, prev_lon, curr_lat, curr_lon)
                speed = distance / time_diff if time_diff > 0 else float("inf")
                travel_mode = get_travel_mode(distance, time_diff)

                # Calculate time spent at previous location
                stay_duration = (prev_time - location_start_time).total_seconds() / 3600
                location_stays.append(stay_duration)

                travels.append(
                    {
                        "from": current_location,
                        "to": loc,
                        "distance_km": distance,
                        "time_hours": time_diff,
                        "speed_kmh": speed,
                        "travel_mode": travel_mode,
                        "stay_duration_hours": stay_duration,
                    }
                )

                current_location = loc
                location_start_time = time

        if travels:
            print("\nTRAVEL SUMMARY:")
            print(f"  Total travels: {len(travels)}")
            print(f"  Travel rate: {len(travels) / len(user_evts) * 100:.1f}% of events")

            # Distance stats
            distances = [t["distance_km"] for t in travels]
            print("\nDISTANCE STATS:")
            print(f"  Min: {min(distances):.0f} km")
            print(f"  Max: {max(distances):.0f} km")
            print(f"  Avg: {sum(distances) / len(distances):.0f} km")

            # Travel time stats
            times = [t["time_hours"] for t in travels]
            print("\nTRAVEL TIME STATS:")
            print(f"  Min: {min(times):.1f} hours")
            print(f"  Max: {max(times):.1f} hours")
            print(f"  Avg: {sum(times) / len(times):.1f} hours")

            # Speed stats
            speeds = [t["speed_kmh"] for t in travels if t["speed_kmh"] != float("inf")]
            if speeds:
                print("\nTRAVEL SPEED STATS:")
                print(f"  Min: {min(speeds):.0f} km/h")
                print(f"  Max: {max(speeds):.0f} km/h")
                print(f"  Avg: {sum(speeds) / len(speeds):.0f} km/h")

            # Travel modes
            modes = Counter([t["travel_mode"] for t in travels])
            print("\nTRAVEL MODES:")
            for mode, count in modes.most_common():
                print(f"  {mode}: {count} ({count / len(travels) * 100:.1f}%)")

            # Location stay duration
            if location_stays:
                print("\nLOCATION STAY DURATION:")
                print(f"  Min: {min(location_stays):.1f} hours")
                print(f"  Max: {max(location_stays):.1f} hours")
                print(f"  Avg: {sum(location_stays) / len(location_stays):.1f} hours")

            # Show sample travels
            print("\nSAMPLE TRAVELS (first 5):")
            for i, t in enumerate(travels[:5]):
                print(f"  {i + 1}. {t['from']} -> {t['to']}")
                print(
                    f"     Distance: {t['distance_km']:.0f} km, Time: {t['time_hours']:.1f}h, Speed: {t['speed_kmh']:.0f} km/h"
                )
                print(f"     Mode: {t['travel_mode']}, Stay at {t['from']}: {t['stay_duration_hours']:.1f}h")

            # Check for suspicious patterns
            print("\nVALIDATION:")
            impossible = [t for t in travels if t["speed_kmh"] > 900]
            if impossible:
                print(f"ERROR: {len(impossible)} impossible travels (>900 km/h)")
            else:
                print("OK: All travel speeds realistic (<900 km/h)")

            very_short_stays = [t for t in travels if t["stay_duration_hours"] < 1]
            if very_short_stays:
                print(
                    f"  {len(very_short_stays)} locations with <1h stay ({len(very_short_stays) / len(travels) * 100:.1f}%)"
                )
            else:
                print("OK: All location stays >= 1 hour")
        else:
            print("\nOK: No travel - user stayed in home location")

    print(f"\n{'=' * 80}")
    print("TRAVEL ANALYSIS COMPLETE")
    print("=" * 80)


if __name__ == "__main__":
    default_path = "data/input/train/azure_ad_train.jsonl"
    filepath = sys.argv[1] if len(sys.argv) > 1 else default_path

    print(f"Analyzing: {filepath}\n")
    analyze_travel_patterns(filepath)
