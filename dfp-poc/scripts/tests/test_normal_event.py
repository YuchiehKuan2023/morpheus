import argparse
import json
import sys
from pathlib import Path

from kafka import KafkaProducer

# Add parent directory to path to import utils
sys.path.insert(0, str(Path(__file__).parent.parent))
from utils.extract_user_profile import get_normal_test_event  # noqa: E402
from utils.test_constants import KAFKA_BROKER, KAFKA_TOPIC  # noqa: E402


def main():
    parser = argparse.ArgumentParser(description="Send a normal test event to Kafka based on user's training profile")
    parser.add_argument(
        "--username", type=str, required=True, help="User email to test (e.g., jennifer.nguyen@contoso.com)"
    )

    args = parser.parse_args()

    # Get complete normal test event from training data
    # This includes correct timestamp (after last training event + realistic travel time),
    # identity, properties, location, and flattened coordinates
    print(f"Extracting normal event for {args.username}...")
    event = get_normal_test_event(args.username)

    # Send to Kafka
    producer = KafkaProducer(bootstrap_servers=KAFKA_BROKER, value_serializer=lambda v: json.dumps(v).encode("utf-8"))
    producer.send(KAFKA_TOPIC, event)
    producer.flush()
    producer.close()

    # Print summary
    print(f"\nNormal behavior test event sent for {args.username}")
    print(f"   Time: {event['time']}")
    print(f"   App: {event['properties']['appDisplayName']}")
    print(f"   Device: {event['properties']['deviceDetail']['displayName']}")
    print(f"   Browser: {event['properties']['deviceDetail']['browser']}")
    print(f"   OS: {event['properties']['deviceDetail']['operatingSystem']}")
    print(
        f"   Location: {event['properties']['location']['city']}, {event['properties']['location']['countryOrRegion']}"
    )
    print(
        f"   Coordinates: ({event['location_geoCoordinates_latitude']:.4f}, {event['location_geoCoordinates_longitude']:.4f})"
    )
    print(f"   Client: {event['properties']['clientAppUsed']}")


if __name__ == "__main__":
    main()
