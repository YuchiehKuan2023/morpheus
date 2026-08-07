"""
FFT Burst Detection Test Script

Generates a burst of events to test FFT time-series anomaly detection.
Simulates credential spray or brute force attack patterns by sending rapid login attempts.

Usage:
    python scripts/tests/test_fft_burst.py --username user@example.com --burst-size 50 --burst-duration 60

Author: Tomasz Zabek <tzabek@deloitte.co.uk>
Date: 2025-12-02
"""

import argparse
import json
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

# Add parent directory to path to import utils
sys.path.insert(0, str(Path(__file__).parent.parent))

from kafka import KafkaProducer  # noqa: E402
from utils.extract_user_profile import get_normal_test_event  # noqa: E402
from utils.test_constants import KAFKA_BROKER, KAFKA_TOPIC  # noqa: E402


def generate_burst_events(username: str, burst_size: int, burst_duration: int, attack_type: str = "credential_spray"):
    """
    Generate a burst of events to trigger FFT anomaly detection.

    FFT detects temporal burst patterns by analyzing:
    - Event count signal (events per time window)
    - Location change signal (rapid location hopping)
    - Velocity signal (travel speed patterns)

    Args:
        username: User email to generate burst for
        burst_size: Number of events in burst (default: 50)
        burst_duration: Duration of burst in seconds (default: 60)
        attack_type: Type of attack pattern to simulate
                    - "credential_spray": Many logins from same location
                    - "location_hopping": Rapid logins from different locations
                    - "brute_force": Failed login attempts burst

    Returns:
        List of event dictionaries
    """
    print(f"Generating {attack_type} burst pattern...")
    print(f"  Burst size: {burst_size} events")
    print(f"  Burst duration: {burst_duration} seconds")
    print(f"  Event rate: {burst_size / burst_duration:.2f} events/sec")

    # Get baseline normal event
    base_event = get_normal_test_event(username)

    # Override timestamp to use current time for inference (within 1d window)
    base_time = datetime.now(timezone.utc)

    burst_events = []

    if attack_type == "credential_spray":
        # Credential spray: Many login attempts from same location in short time
        # This creates high event_count signal spike → FFT detects burst
        print("\nSimulating credential spray attack:")
        print("  - Rapid login attempts from same location")
        print("  - High event_count signal → FFT detection")

        for i in range(burst_size):
            event = base_event.copy()
            # Spread events evenly across burst duration
            event_time = base_time + timedelta(seconds=(i * burst_duration / burst_size))
            event["time"] = event_time.isoformat().replace("+00:00", "Z")

            # Keep same location (credential spray from single source)
            # Vary only the timestamp to create temporal burst
            event["id"] = f"burst-event-{i}"

            burst_events.append(event)

    elif attack_type == "location_hopping":
        # Location hopping: Rapid logins from different locations
        # This creates high location_change signal + high velocity → FFT detects burst
        print("\nSimulating location hopping attack:")
        print("  - Rapid logins from alternating locations")
        print("  - High location_change signal → FFT detection")

        # Alternate between two distant locations
        locations = [
            {"city": "New York", "country": "US", "lat": 40.7128, "lon": -74.0060},
            {"city": "London", "country": "GB", "lat": 51.5074, "lon": -0.1278},
        ]

        for i in range(burst_size):
            event = base_event.copy()
            event_time = base_time + timedelta(seconds=(i * burst_duration / burst_size))
            event["time"] = event_time.isoformat().replace("+00:00", "Z")

            # Alternate locations
            loc = locations[i % 2]
            event["properties"]["location"]["city"] = loc["city"]
            event["properties"]["location"]["countryOrRegion"] = loc["country"]
            event["properties"]["location"]["geoCoordinates"]["latitude"] = loc["lat"]
            event["properties"]["location"]["geoCoordinates"]["longitude"] = loc["lon"]
            event["location"]["city"] = loc["city"]
            event["location"]["countryOrRegion"] = loc["country"]
            event["location"]["geoCoordinates"]["latitude"] = loc["lat"]
            event["location"]["geoCoordinates"]["longitude"] = loc["lon"]
            event["location_geoCoordinates_latitude"] = loc["lat"]
            event["location_geoCoordinates_longitude"] = loc["lon"]

            event["id"] = f"burst-event-{i}"
            burst_events.append(event)

    elif attack_type == "brute_force":
        # Brute force: Failed login attempts burst
        # This creates high event_count signal with failure status → FFT detects burst
        print("\nSimulating brute force attack:")
        print("  - Rapid failed login attempts")
        print("  - High event_count signal with failures → FFT detection")

        for i in range(burst_size):
            event = base_event.copy()
            event_time = base_time + timedelta(seconds=(i * burst_duration / burst_size))
            event["time"] = event_time.isoformat().replace("+00:00", "Z")

            # Most attempts fail (simulate brute force)
            if i < burst_size - 1:  # All but last fail
                event["properties"]["status"]["errorCode"] = 50126  # Invalid credentials
                event["properties"]["status"]["failureReason"] = "Invalid username or password"
            else:  # Last one succeeds
                event["properties"]["status"]["errorCode"] = 0
                event["properties"]["status"]["failureReason"] = None

            event["id"] = f"burst-event-{i}"
            burst_events.append(event)

    else:
        raise ValueError(f"Unknown attack type: {attack_type}")

    return burst_events


def send_burst_to_kafka(events: list, real_time: bool = False, delay_seconds: float | None = None):
    """
    Send burst events to Kafka.

    Args:
        events: List of event dictionaries
        real_time: If True, send events with delays to simulate real attack timing
        delay_seconds: Override delay between events (if None, calculated from burst_duration)
    """
    producer = KafkaProducer(bootstrap_servers=KAFKA_BROKER, value_serializer=lambda v: json.dumps(v).encode("utf-8"))

    print(f"\nSending {len(events)} events to Kafka...")

    if real_time:
        # Calculate delay from burst duration if not specified
        if delay_seconds is None:
            burst_duration = (
                datetime.fromisoformat(events[-1]["time"].replace("Z", "+00:00"))
                - datetime.fromisoformat(events[0]["time"].replace("Z", "+00:00"))
            ).total_seconds()
            delay_seconds = burst_duration / len(events)

        print(f"Real-time mode: {delay_seconds:.3f}s delay between events")

        for i, event in enumerate(events):
            producer.send(KAFKA_TOPIC, event)
            if i < len(events) - 1:  # Don't delay after last event
                time.sleep(delay_seconds)
            if (i + 1) % 10 == 0:
                print(f"  Sent {i + 1}/{len(events)} events...")
    else:
        # Send all events immediately (batch mode)
        print("Batch mode: sending all events immediately")
        for event in events:
            producer.send(KAFKA_TOPIC, event)

    producer.flush()
    producer.close()
    print(f"✓ All {len(events)} events sent to Kafka topic: {KAFKA_TOPIC}")


def main():
    parser = argparse.ArgumentParser(
        description="Generate FFT burst test events to trigger time-series anomaly detection"
    )
    parser.add_argument(
        "--username", type=str, required=True, help="User email to test (e.g., jennifer.nguyen@contoso.com)"
    )
    parser.add_argument(
        "--burst-size", type=int, default=50, help="Number of events in burst (default: 50, FFT needs 10+)"
    )
    parser.add_argument(
        "--burst-duration", type=int, default=60, help="Duration of burst in seconds (default: 60, creates 1min burst)"
    )
    parser.add_argument(
        "--attack-type",
        type=str,
        default="credential_spray",
        choices=["credential_spray", "location_hopping", "brute_force"],
        help="Attack pattern: credential_spray (same location), location_hopping (rapid moves), brute_force (failed logins)",
    )
    parser.add_argument(
        "--real-time",
        action="store_true",
        help="Send events with delays to simulate real attack timing (default: batch)",
    )
    parser.add_argument(
        "--delay", type=float, default=None, help="Override delay between events in seconds (only with --real-time)"
    )

    args = parser.parse_args()

    # Validate FFT requirements
    if args.burst_size < 10:
        print("WARNING: FFT requires min_history >= 10 events. Burst size should be at least 10.")
        print("         Increasing burst size to 10...")
        args.burst_size = 10

    print("=" * 80)
    print("FFT BURST DETECTION TEST (Time-Series Anomaly Detection)")
    print("=" * 80)
    print(f"\nTarget User: {args.username}")
    print(f"Attack Type: {args.attack_type}")
    print("Burst Config:")
    print(f"  - Size: {args.burst_size} events")
    print(f"  - Duration: {args.burst_duration} seconds")
    print(f"  - Rate: {args.burst_size / args.burst_duration:.2f} events/sec")
    print(f"  - Mode: {'Real-time' if args.real_time else 'Batch'}")

    # Generate burst events
    burst_events = generate_burst_events(args.username, args.burst_size, args.burst_duration, args.attack_type)

    print(f"\n{'=' * 80}")
    print("BURST SUMMARY")
    print(f"{'=' * 80}")
    print(f"First event time: {burst_events[0]['time']}")
    print(f"Last event time: {burst_events[-1]['time']}")
    print(f"Time span: {args.burst_duration} seconds")

    if args.attack_type == "credential_spray":
        print(
            f"Location: {burst_events[0]['properties']['location']['city']}, {burst_events[0]['properties']['location']['countryOrRegion']}"
        )
        print("Pattern: Rapid login attempts from SAME location (credential spray)")
    elif args.attack_type == "location_hopping":
        print("Pattern: Rapid login attempts from DIFFERENT locations")
        print("  Locations alternating between:")
        print(f"    - {burst_events[0]['properties']['location']['city']}")
        print(f"    - {burst_events[1]['properties']['location']['city']}")
    elif args.attack_type == "brute_force":
        print(f"Pattern: Rapid failed login attempts ({args.burst_size - 1} failures, 1 success)")

    # Send to Kafka
    send_burst_to_kafka(burst_events, real_time=args.real_time, delay_seconds=args.delay)

    print(f"\n{'=' * 80}")
    print("FFT DETECTION EXPECTED")
    print(f"{'=' * 80}")
    print("FFT should detect this burst pattern via:")
    if args.attack_type == "credential_spray":
        print("  ✓ Event count signal: High frequency spike in 1H window")
        print("  ✓ FFT analysis: Temporal burst pattern detected")
        print("  ✓ Z-score > 8 (default threshold)")
    elif args.attack_type == "location_hopping":
        print("  ✓ Location change signal: Rapid location switches")
        print("  ✓ Velocity signal: High travel speed between events")
        print("  ✓ FFT analysis: Temporal burst pattern detected")
    elif args.attack_type == "brute_force":
        print("  ✓ Event count signal: High frequency spike with failures")
        print("  ✓ FFT analysis: Temporal burst pattern detected")

    print("\nRun inference pipeline to see FFT detection:")
    print("  python pipelines/pipeline.py inference --kafka-bootstrap 127.0.0.1:29092")
    print("\nMonitor detections topic:")
    print("  kafka-console-consumer --bootstrap-server 127.0.0.1:29092 --topic dfp-detections")
    print(f"\n{'=' * 80}")


if __name__ == "__main__":
    main()
