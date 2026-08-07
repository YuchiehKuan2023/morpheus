import argparse
import json
import random
import sys
from datetime import timedelta
from pathlib import Path

from kafka import KafkaProducer

# Add parent directory to path to import utils
sys.path.insert(0, str(Path(__file__).parent.parent))
from utils.extract_user_profile import calculate_travel_time, get_normal_test_event, haversine_distance  # noqa: E402
from utils.test_constants import KAFKA_BROKER, KAFKA_TOPIC, NOVEL_VALUES  # noqa: E402


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
    from utils.test_helpers import get_last_training_event_info

    # Start with a normal event (uses most common values + realistic timestamp from training)
    event = get_normal_test_event(username)

    # For location changes, we need to recalculate timestamp from last training event
    last_info = get_last_training_event_info(username)
    last_training_lat = last_info["latitude"]
    last_training_lon = last_info["longitude"]
    last_training_time = last_info["timestamp"]

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
        # Novel location only (with realistic travel time to avoid impossible travel)
        novel_loc = random.choice(NOVEL_VALUES["locations"])

        # Calculate distance from last training event to novel location
        distance_km = haversine_distance(last_training_lat, last_training_lon, novel_loc["lat"], novel_loc["lon"])

        # Calculate realistic travel time based on distance
        hours_needed = calculate_travel_time(distance_km)

        # Add extra buffer to ensure test event is well-separated from training events
        # Use 24 hours minimum to prevent extreme travel_speed calculations
        hours_needed = max(hours_needed, 24.0)  # Minimum 24 hours between events

        # Update timestamp from last training event (not from event's current timestamp)
        event["time"] = (last_training_time + timedelta(hours=hours_needed)).isoformat()

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

        # Location change with realistic travel time from last training event
        novel_loc = random.choice(NOVEL_VALUES["locations"])
        distance_km = haversine_distance(last_training_lat, last_training_lon, novel_loc["lat"], novel_loc["lon"])

        hours_needed = calculate_travel_time(distance_km)

        # Add extra buffer to ensure test event is well-separated from training events
        # Use 24 hours minimum to prevent extreme travel_speed calculations
        hours_needed = max(hours_needed, 24.0)  # Minimum 24 hours between events

        # Calculate timestamp from last training event (not from event's current timestamp)
        event["time"] = (last_training_time + timedelta(hours=hours_needed)).isoformat()

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
        # Location change WITHOUT realistic travel time (extreme anomaly test)
        print("\nTesting IMPOSSIBLE TRAVEL scenario")
        novel_loc = random.choice(NOVEL_VALUES["locations"])
        distance_km = haversine_distance(last_training_lat, last_training_lon, novel_loc["lat"], novel_loc["lon"])
        realistic_hours = calculate_travel_time(distance_km)

        print(f"Distance: {distance_km:.2f} km")
        print(f"Realistic travel time: {realistic_hours:.2f} hours")
        print("Using: 1 hour (TELEPORTATION)")
        print(f"Expected speed: ~{distance_km:.0f} km/h")

        # Use only 1 hour regardless of distance - creates extreme travel_speed
        event["time"] = (last_training_time + timedelta(hours=1.0)).isoformat()

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
