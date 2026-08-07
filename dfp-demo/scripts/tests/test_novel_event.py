import argparse
import json
import random
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from kafka import KafkaProducer

# Add parent directory to path to import utils
sys.path.insert(0, str(Path(__file__).parent.parent))
from constants.tests import KAFKA_BROKER, KAFKA_TOPIC, NOVEL_VALUES  # noqa: E402
from utils.shared.extract_user_profile import (  # noqa: E402
    calculate_travel_time,
    get_normal_test_event,
    haversine_distance,
)


def get_novel_test_event(username: str, scenario: str) -> dict:
    """
    Generate a novel test event by modifying a normal event with unseen values.

    Uses user's last training event as baseline for timestamp calculation.

    Args:
        username: User email
        scenario: Type of novel event to generate
                 - "app": Change only the application
                 - "browser": Change only the browser
                 - "os": Change only the operating system
                 - "device": Change only the device
                 - "location": Change only the location (with realistic travel time)
                 - "all": Change all features to novel values

    Returns:
        Dict representing a novel event based on user's normal pattern
    """
    from utils.shared.utils import get_last_training_event_info

    # Start with a normal event (uses most common values + realistic timestamp from training)
    event = get_normal_test_event(username)

    # Get last training event location for travel distance calculations
    last_info = get_last_training_event_info(username)
    last_training_lat = last_info["latitude"]
    last_training_lon = last_info["longitude"]

    # Modify based on scenario
    if scenario == "app":
        # Novel app only - pick random from list
        event["properties"]["appDisplayName"] = random.choice(NOVEL_VALUES["apps"])
        event["properties"]["appId"] = "00000000-0000-0000-0000-000000000000"  # Unknown app ID

    elif scenario == "browser":
        # Novel browser only - pick random from list
        event["properties"]["deviceDetail"]["browser"] = random.choice(NOVEL_VALUES["browsers"])

    elif scenario == "os":
        # Novel OS only - pick random from list
        event["properties"]["deviceDetail"]["operatingSystem"] = random.choice(NOVEL_VALUES["operating_systems"])

    elif scenario == "device":
        # Novel device only - pick random from list
        event["properties"]["deviceDetail"]["displayName"] = random.choice(NOVEL_VALUES["devices"])
        event["properties"]["deviceDetail"]["deviceId"] = "novel-device-id-" + str(random.randint(100, 999))

    elif scenario == "location":
        # Novel location scenario — always uses current timestamp.
        #
        # The event timestamp is always set to now() regardless of travel distance.
        # This may result in a high travel_speed_kmph for far-away locations, which
        # is intentional (it's a novel/suspicious location after all).  Setting a
        # future timestamp to make the speed "possible" caused downstream issues:
        # the inference pipeline rejected subsequent events as out-of-order, and the
        # AI orchestrator's LLM prompt ballooned past the 8000-token limit.
        #
        # The impossible-travel detection will fire if the distance AND speed breach
        # the pipeline thresholds — that is acceptable and expected behaviour for
        # this scenario.
        now = datetime.now(timezone.utc)
        last_time = last_info["timestamp"]
        if last_time.tzinfo is None:
            last_time = last_time.replace(tzinfo=timezone.utc)
        hours_elapsed = max((now - last_time).total_seconds() / 3600, 0.0)

        # Pick the nearest novel location to minimise travel_speed_kmph while
        # still being a novel location.  This reduces (but does not eliminate)
        # extreme z-scores and prevents the LLM prompt from exceeding token limits.
        sorted_locs = sorted(
            NOVEL_VALUES["locations"],
            key=lambda loc: haversine_distance(last_training_lat, last_training_lon, loc["lat"], loc["lon"]),
        )
        novel_loc = sorted_locs[0]
        dist = haversine_distance(last_training_lat, last_training_lon, novel_loc["lat"], novel_loc["lon"])
        implied_speed = dist / hours_elapsed if hours_elapsed > 0 else 0.0

        # Always stamp with current time — never a future timestamp.
        event["time"] = now.isoformat()
        print(
            f"→ location scenario: {novel_loc['city']} ({dist:.0f} km, "
            f"{hours_elapsed:.1f}h elapsed, implied speed {implied_speed:.0f} km/h — current timestamp)"
        )

        # Update location in all three places
        event["properties"]["location"]["city"] = novel_loc["city"]
        event["properties"]["location"]["state"] = novel_loc["state"]
        event["properties"]["location"]["countryOrRegion"] = novel_loc["country"]
        event["properties"]["location"]["geoCoordinates"]["latitude"] = novel_loc["lat"]
        event["properties"]["location"]["geoCoordinates"]["longitude"] = novel_loc["lon"]
        # Update root-level location
        event["location"]["city"] = novel_loc["city"]
        event["location"]["state"] = novel_loc["state"]
        event["location"]["countryOrRegion"] = novel_loc["country"]
        event["location"]["geoCoordinates"]["latitude"] = novel_loc["lat"]
        event["location"]["geoCoordinates"]["longitude"] = novel_loc["lon"]
        # Update flattened coordinates
        event["location_geoCoordinates_latitude"] = novel_loc["lat"]
        event["location_geoCoordinates_longitude"] = novel_loc["lon"]

    elif scenario == "all":
        # All features novel - pick random values from lists
        event["properties"]["appDisplayName"] = random.choice(NOVEL_VALUES["apps"])
        event["properties"]["appId"] = "00000000-0000-0000-0000-000000000000"
        event["properties"]["deviceDetail"]["browser"] = random.choice(NOVEL_VALUES["browsers"])
        event["properties"]["deviceDetail"]["operatingSystem"] = random.choice(NOVEL_VALUES["operating_systems"])
        event["properties"]["deviceDetail"]["displayName"] = random.choice(NOVEL_VALUES["devices"])
        event["properties"]["deviceDetail"]["deviceId"] = "novel-device-id-" + str(random.randint(100, 999))

        # Location change — apply same reachability logic as the dedicated "location" scenario
        _MAX_SPEED_KMPH = 800.0
        now = datetime.now(timezone.utc)
        last_time = last_info["timestamp"]
        if last_time.tzinfo is None:
            last_time = last_time.replace(tzinfo=timezone.utc)
        hours_elapsed = max((now - last_time).total_seconds() / 3600, 0.0)
        reachable = [
            loc
            for loc in NOVEL_VALUES["locations"]
            if haversine_distance(last_training_lat, last_training_lon, loc["lat"], loc["lon"])
            <= hours_elapsed * _MAX_SPEED_KMPH
        ]
        if reachable:
            novel_loc = random.choice(reachable)
            event["time"] = now.isoformat()
        else:
            sorted_locs = sorted(
                NOVEL_VALUES["locations"],
                key=lambda loc: haversine_distance(last_training_lat, last_training_lon, loc["lat"], loc["lon"]),
            )
            novel_loc = sorted_locs[0]
            dist = haversine_distance(last_training_lat, last_training_lon, novel_loc["lat"], novel_loc["lon"])
            travel_h = calculate_travel_time(dist)
            event["time"] = (last_time + timedelta(hours=travel_h)).isoformat()

        event["properties"]["location"]["city"] = novel_loc["city"]
        event["properties"]["location"]["state"] = novel_loc["state"]
        event["properties"]["location"]["countryOrRegion"] = novel_loc["country"]
        event["properties"]["location"]["geoCoordinates"]["latitude"] = novel_loc["lat"]
        event["properties"]["location"]["geoCoordinates"]["longitude"] = novel_loc["lon"]
        event["location"]["city"] = novel_loc["city"]
        event["location"]["state"] = novel_loc["state"]
        event["location"]["countryOrRegion"] = novel_loc["country"]
        event["location"]["geoCoordinates"]["latitude"] = novel_loc["lat"]
        event["location"]["geoCoordinates"]["longitude"] = novel_loc["lon"]
        event["location_geoCoordinates_latitude"] = novel_loc["lat"]
        event["location_geoCoordinates_longitude"] = novel_loc["lon"]

    elif scenario == "impossible_travel":
        # Location change that is intentionally IMPOSSIBLE to reach in the elapsed time.
        #
        # We prefer the location whose implied travel speed is the highest given the
        # time since the user's last event.  If all NOVEL_VALUES locations happen to
        # be reachable (e.g. the user's last event was very old), we pick the farthest
        # one and log a warning — the pipeline will still flag it as suspicious even if
        # the travel-speed threshold is not technically exceeded.
        print("\nTesting IMPOSSIBLE TRAVEL scenario")
        _MAX_SPEED_KMPH = 800.0
        now = datetime.now(timezone.utc)
        last_time = last_info["timestamp"]
        if last_time.tzinfo is None:
            last_time = last_time.replace(tzinfo=timezone.utc)
        hours_elapsed = max((now - last_time).total_seconds() / 3600, 0.001)  # avoid /0
        max_reachable_km = hours_elapsed * _MAX_SPEED_KMPH

        # Rank by descending implied speed (farthest relative to elapsed time first)
        locs_with_speed = [
            (loc, haversine_distance(last_training_lat, last_training_lon, loc["lat"], loc["lon"]) / hours_elapsed)
            for loc in NOVEL_VALUES["locations"]
        ]
        locs_with_speed.sort(key=lambda x: x[1], reverse=True)

        impossible_locs = [(loc, spd) for loc, spd in locs_with_speed if spd > _MAX_SPEED_KMPH]
        if impossible_locs:
            novel_loc, implied_speed = impossible_locs[0]
        else:
            # All locations reachable — last event was very old.  Use farthest anyway.
            novel_loc, implied_speed = locs_with_speed[0]
            print(
                f"⚠️  All novel locations are technically reachable from last event "
                f"({hours_elapsed:.1f}h ago, max reachable {max_reachable_km:.0f} km). "
                f"Using farthest: {novel_loc['city']} (implied speed {implied_speed:.0f} km/h). "
                f"To get a clean impossible-travel test, send a normal event first to refresh "
                f"the rolling window, then re-run this scenario."
            )

        dist = haversine_distance(last_training_lat, last_training_lon, novel_loc["lat"], novel_loc["lon"])
        realistic_hours = calculate_travel_time(dist)
        print(f"Distance from last location: {dist:.2f} km")
        print(f"Time since last event: {hours_elapsed:.2f}h  |  Realistic travel time: {realistic_hours:.2f}h")
        print(f"Implied travel speed: {implied_speed:.0f} km/h  (threshold: {_MAX_SPEED_KMPH:.0f} km/h)")
        print(f"Truly impossible: {implied_speed > _MAX_SPEED_KMPH}")

        # Always use current time — the anomaly is the speed, not a future timestamp
        event["time"] = now.isoformat()

        event["properties"]["location"]["city"] = novel_loc["city"]
        event["properties"]["location"]["state"] = novel_loc["state"]
        event["properties"]["location"]["countryOrRegion"] = novel_loc["country"]
        event["properties"]["location"]["geoCoordinates"]["latitude"] = novel_loc["lat"]
        event["properties"]["location"]["geoCoordinates"]["longitude"] = novel_loc["lon"]
        event["location"]["city"] = novel_loc["city"]
        event["location"]["state"] = novel_loc["state"]
        event["location"]["countryOrRegion"] = novel_loc["country"]
        event["location"]["geoCoordinates"]["latitude"] = novel_loc["lat"]
        event["location"]["geoCoordinates"]["longitude"] = novel_loc["lon"]
        event["location_geoCoordinates_latitude"] = novel_loc["lat"]
        event["location_geoCoordinates_longitude"] = novel_loc["lon"]

    else:
        raise ValueError(
            f"Unknown scenario: {scenario}. Valid options: app, browser, os, device, location, all, impossible_travel"
        )

    return event


def get_combined_novel_event(username: str, scenarios: list[str]) -> dict:
    """
    Generate a novel test event with multiple independent scenario modifications applied.

    Produces a single event in which all specified feature dimensions are simultaneously
    changed to novel values.  This lets you test compound anomalies, e.g. a new browser
    *and* a new OS in the same authentication event.

    Only the "soft" feature scenarios can be combined::

        "app", "browser", "os", "device"

    Location-based scenarios ("location", "impossible_travel") require timestamp
    manipulation and must be tested individually via get_novel_test_event().

    Args:
        username: User email (Azure AD userPrincipalName)
        scenarios: Non-empty list of soft scenario names to apply. Duplicates are ignored.
                   Order does not matter.

    Returns:
        Dict (Azure AD SignInLogs format) with all specified modifications applied on top
        of the user's most-common behavioral baseline.

    Raises:
        ValueError: If scenarios is empty, contains duplicates, or includes unsupported names.

    Example::

        event = get_combined_novel_event("alice@contoso.com", ["browser", "device"])
        # event has a novel browser AND a novel device name simultaneously

    """
    _SOFT = {"app", "browser", "os", "device"}
    invalid = [s for s in scenarios if s not in _SOFT]
    if invalid:
        raise ValueError(
            f"Only soft scenarios ({sorted(_SOFT)}) can be combined. "
            f"Unsupported: {invalid}. Use get_novel_test_event() for location scenarios."
        )
    if not scenarios:
        raise ValueError("scenarios list must not be empty")

    event = get_normal_test_event(username)

    for scenario in dict.fromkeys(scenarios):  # deduplicate while preserving order
        if scenario == "app":
            event["properties"]["appDisplayName"] = random.choice(NOVEL_VALUES["apps"])
            event["properties"]["appId"] = "00000000-0000-0000-0000-000000000000"
        elif scenario == "browser":
            event["properties"]["deviceDetail"]["browser"] = random.choice(NOVEL_VALUES["browsers"])
        elif scenario == "os":
            event["properties"]["deviceDetail"]["operatingSystem"] = random.choice(NOVEL_VALUES["operating_systems"])
        elif scenario == "device":
            event["properties"]["deviceDetail"]["displayName"] = random.choice(NOVEL_VALUES["devices"])
            event["properties"]["deviceDetail"]["deviceId"] = "novel-device-id-" + str(random.randint(100, 999))

    return event


def main():
    parser = argparse.ArgumentParser(description="Send a novel test event to Kafka based on user's training profile")
    parser.add_argument(
        "--username", type=str, required=True, help="User email to test (e.g., jennifer.nguyen@contoso.com)"
    )
    parser.add_argument(
        "--scenario",
        type=str,
        required=True,
        choices=["app", "browser", "os", "device", "location", "all", "impossible_travel"],
        help="Type of novel event: app, browser, os, device, location, all, or impossible_travel",
    )

    args = parser.parse_args()

    # Get novel test event based on scenario
    print(f"Generating {args.scenario} novel event for {args.username}...")
    event = get_novel_test_event(args.username, args.scenario)

    # Send to Kafka
    producer = KafkaProducer(bootstrap_servers=KAFKA_BROKER, value_serializer=lambda v: json.dumps(v).encode("utf-8"))
    producer.send(KAFKA_TOPIC, event)
    producer.flush()
    producer.close()

    # Print summary
    print(f"\n{'=' * 80}")
    print(f"NOVEL EVENT TEST - Scenario: {args.scenario.upper()}")
    print(f"{'=' * 80}")
    print(f"User: {args.username}")
    print(f"Time: {event['time']}")
    print(f"App: {event['properties']['appDisplayName']}")
    print(f"Device: {event['properties']['deviceDetail']['displayName']}")
    print(f"Browser: {event['properties']['deviceDetail']['browser']}")
    print(f"OS: {event['properties']['deviceDetail']['operatingSystem']}")
    print(f"Location: {event['properties']['location']['city']}, {event['properties']['location']['countryOrRegion']}")
    print(
        f"Coordinates: ({event['location_geoCoordinates_latitude']:.4f}, {event['location_geoCoordinates_longitude']:.4f})"
    )
    print(f"Client: {event['properties']['clientAppUsed']}")

    # Show what changed for location/all scenarios
    if args.scenario in ["location", "all"]:
        print("\nTravel Distance Calculated:")
        print(f"   Novel location selected: {event['properties']['location']['city']}")
        print("   Timestamp adjusted for realistic travel time")

    print(f"{'=' * 80}")
    print("\nNovel event sent to Kafka")
    print("Run inference pipeline to see anomaly detection results")


if __name__ == "__main__":
    main()
