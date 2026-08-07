#!/usr/bin/env python3
"""
Generate Synthetic Paired Data (Event → Detection)

Creates synthetic Azure AD SignInLog events with anomalous behaviors,
then generates corresponding detection records as if DFP had processed them.

This mimics the real inference pipeline flow:
    Original Event (Azure AD) → DFP Pipeline → Detection (if score > 2.0)

The data is aligned (features in event match features in detection) and
uses real user baselines from training data for consistency.

Key Features:
    - Uses actual user profiles from training data
    - Leverages existing test event generation utilities
    - Applies NOVEL_VALUES for realistic anomalies
    - Calculates realistic travel times for location changes
    - Generates paired (original_event, detection) records

Output: JSONL file with paired records
    Each line: {"original_event": {...}, "detection": {...}}

Usage:
    # Generate 100 paired records for testing
    python scripts/utils/generate_synthetic_detections.py --count 100

    # Generate 1000 records with custom output
    python scripts/utils/generate_synthetic_detections.py --count 1000 --output data/input/ai/test_pairs.jsonl

Author: AI Intelligence Layer Team
Date: 2026-02-19
"""

import argparse
import json
import random
import sys
from datetime import timedelta
from pathlib import Path
from typing import Any

# Add scripts/ to path to import utils
sys.path.insert(0, str(Path(__file__).parents[2]))

from constants.tests import NOVEL_VALUES  # noqa: E402

from utils.shared.extract_user_profile import (  # noqa: E402
    calculate_travel_time,
    extract_all_users,
    get_normal_test_event,
    haversine_distance,
)
from utils.shared.utils import get_last_training_event_info  # noqa: E402


class SyntheticPairedDataGenerator:
    """Generate synthetic paired (event, detection) data using real user baselines"""

    def __init__(self, seed: int = 42, num_users: int = 20):
        """Initialize generator with random seed"""
        random.seed(seed)

        # Load all available users from training data
        print("Loading users from training data...")
        all_users = extract_all_users()
        print(f"   Loaded {len(all_users)} total users")

        # Select subset of users for synthetic data generation
        self.users = random.sample(all_users, min(num_users, len(all_users)))
        print(f"   Using {len(self.users)} users for synthetic data")

        # Track last timestamp per user for sequential event generation
        self.user_last_timestamp = {}

        # Anomaly type distribution
        # New types added 2026-03-09 for 9-class coverage:
        #   location_device  → Location with Unusual Device
        #   unknown_device   → Unknown Device
        #   app_browser      → multi-feature low-severity (app + browser only)
        #   app_device       → multi-feature medium (app + device, no location)
        #   high_logcount    → Broad Deviation via excessive activity count
        self.anomaly_types = [
            "app",
            "browser",
            "os",
            "device",
            "location",
            "impossible_travel",
            "all",
            "location_device",
            "unknown_device",
            "app_browser",
            "app_device",
            "high_logcount",
        ]

    def generate_anomalous_event(self, username: str, anomaly_type: str = "random") -> tuple[dict[str, Any], list[str]]:
        """
        Generate an anomalous Azure AD SignInLog event for a specific user.

        Uses user's actual baseline from training data and applies novel values.
        Generates sequential timestamps for each user.

        Args:
            username: User email from training data
            anomaly_type: Type of anomaly to generate

        Returns:
            tuple: (event_dict, list_of_anomalous_features)
        """
        # Get normal event for this user (based on their training baseline)
        event = get_normal_test_event(username)

        # Get last training event info for location context
        last_info = get_last_training_event_info(username)
        last_training_lat = last_info["latitude"]
        last_training_lon = last_info["longitude"]

        # Initialize user's last timestamp if first time
        if username not in self.user_last_timestamp:
            last_training_time = last_info["timestamp"]
            # Start from 1-7 days after last training event (realistic gap)
            self.user_last_timestamp[username] = last_training_time + timedelta(hours=random.uniform(24, 168))

        # Get last generated timestamp for this user
        last_timestamp = self.user_last_timestamp[username]

        anomalous_features = []

        # Select random anomaly type if not specified
        if anomaly_type == "random":
            anomaly_type = random.choice(self.anomaly_types)

        # Apply anomaly based on type
        if anomaly_type == "app":
            # Novel app never seen in training
            novel_app = random.choice(NOVEL_VALUES["apps"])
            event["properties"]["appDisplayName"] = novel_app
            event["properties"]["appId"] = "00000000-0000-0000-0000-000000000000"
            anomalous_features.append(f"appDisplayName={novel_app}")

            # Update timestamp: 15 minutes to 2 hours after last event
            time_gap_hours = random.uniform(0.25, 2.0)
            event["time"] = (last_timestamp + timedelta(hours=time_gap_hours)).isoformat()
            self.user_last_timestamp[username] = last_timestamp + timedelta(hours=time_gap_hours)

        elif anomaly_type == "browser":
            # Novel browser never seen in training
            novel_browser = random.choice(NOVEL_VALUES["browsers"])
            event["properties"]["deviceDetail"]["browser"] = novel_browser
            anomalous_features.append(f"deviceDetailbrowser={novel_browser}")

            # Update timestamp: 15 minutes to 2 hours after last event
            time_gap_hours = random.uniform(0.25, 2.0)
            event["time"] = (last_timestamp + timedelta(hours=time_gap_hours)).isoformat()
            self.user_last_timestamp[username] = last_timestamp + timedelta(hours=time_gap_hours)

        elif anomaly_type == "os":
            # Novel OS never seen in training
            novel_os = random.choice(NOVEL_VALUES["operating_systems"])
            event["properties"]["deviceDetail"]["operatingSystem"] = novel_os
            anomalous_features.append(f"deviceDetailoperatingSystem={novel_os}")

            # Update timestamp: 15 minutes to 2 hours after last event
            time_gap_hours = random.uniform(0.25, 2.0)
            event["time"] = (last_timestamp + timedelta(hours=time_gap_hours)).isoformat()
            self.user_last_timestamp[username] = last_timestamp + timedelta(hours=time_gap_hours)

        elif anomaly_type == "device":
            # Novel device never seen in training
            novel_device = random.choice(NOVEL_VALUES["devices"])
            event["properties"]["deviceDetail"]["displayName"] = novel_device
            event["properties"]["deviceDetail"]["deviceId"] = f"novel-device-id-{random.randint(100, 999)}"
            anomalous_features.append(f"deviceDetaildisplayName={novel_device}")

            # Update timestamp: 15 minutes to 2 hours after last event
            time_gap_hours = random.uniform(0.25, 2.0)
            event["time"] = (last_timestamp + timedelta(hours=time_gap_hours)).isoformat()
            self.user_last_timestamp[username] = last_timestamp + timedelta(hours=time_gap_hours)

        elif anomaly_type == "location":
            # Novel location with realistic travel time
            novel_loc = random.choice(NOVEL_VALUES["locations"])

            # Calculate distance from last training location
            distance_km = haversine_distance(last_training_lat, last_training_lon, novel_loc["lat"], novel_loc["lon"])

            # Calculate realistic travel time (minimum 2 hours for shorter distances)
            hours_needed = max(calculate_travel_time(distance_km), 2.0)

            # Update timestamp from last generated event (sequential)
            new_timestamp = last_timestamp + timedelta(hours=hours_needed)
            event["time"] = new_timestamp.isoformat()
            self.user_last_timestamp[username] = new_timestamp

            # Update location in all three places (event structure has 3 location fields)
            # 1. Root level location
            event["location"]["city"] = novel_loc["city"]
            event["location"]["state"] = novel_loc["state"]
            event["location"]["countryOrRegion"] = novel_loc["country"]
            event["location"]["geoCoordinates"]["latitude"] = novel_loc["lat"]
            event["location"]["geoCoordinates"]["longitude"] = novel_loc["lon"]

            # 2. Properties level location
            event["properties"]["location"]["city"] = novel_loc["city"]
            event["properties"]["location"]["state"] = novel_loc["state"]
            event["properties"]["location"]["countryOrRegion"] = novel_loc["country"]
            event["properties"]["location"]["geoCoordinates"]["latitude"] = novel_loc["lat"]
            event["properties"]["location"]["geoCoordinates"]["longitude"] = novel_loc["lon"]

            # 3. Flattened coordinates
            event["location_geoCoordinates_latitude"] = novel_loc["lat"]
            event["location_geoCoordinates_longitude"] = novel_loc["lon"]

            anomalous_features.append(f"locationCity={novel_loc['city']}")
            anomalous_features.append(f"locationCountry={novel_loc['country']}")

        elif anomaly_type == "impossible_travel":
            # Location change WITHOUT realistic travel time (extreme anomaly)
            novel_loc = random.choice(NOVEL_VALUES["locations"])

            # Calculate distance
            distance_km = haversine_distance(last_training_lat, last_training_lon, novel_loc["lat"], novel_loc["lon"])

            # Use only 0.5-1 hour regardless of distance - creates impossible travel_speed
            hours_needed = random.uniform(0.5, 1.0)
            travel_speed_kmph = distance_km / hours_needed

            # Update timestamp (sequential from last event)
            new_timestamp = last_timestamp + timedelta(hours=hours_needed)
            event["time"] = new_timestamp.isoformat()
            self.user_last_timestamp[username] = new_timestamp

            # Update location in all three places
            event["location"]["city"] = novel_loc["city"]
            event["location"]["state"] = novel_loc["state"]
            event["location"]["countryOrRegion"] = novel_loc["country"]
            event["location"]["geoCoordinates"]["latitude"] = novel_loc["lat"]
            event["location"]["geoCoordinates"]["longitude"] = novel_loc["lon"]

            event["properties"]["location"]["city"] = novel_loc["city"]
            event["properties"]["location"]["state"] = novel_loc["state"]
            event["properties"]["location"]["countryOrRegion"] = novel_loc["country"]
            event["properties"]["location"]["geoCoordinates"]["latitude"] = novel_loc["lat"]
            event["properties"]["location"]["geoCoordinates"]["longitude"] = novel_loc["lon"]

            event["location_geoCoordinates_latitude"] = novel_loc["lat"]
            event["location_geoCoordinates_longitude"] = novel_loc["lon"]

            anomalous_features.append(f"travel_speed_kmph={travel_speed_kmph:.0f}")
            anomalous_features.append(f"locationCity={novel_loc['city']}")
            anomalous_features.append(f"locationCountry={novel_loc['country']}")

        elif anomaly_type == "all":
            # All features novel - pick random values from lists
            novel_app = random.choice(NOVEL_VALUES["apps"])
            novel_browser = random.choice(NOVEL_VALUES["browsers"])
            novel_os = random.choice(NOVEL_VALUES["operating_systems"])
            novel_device = random.choice(NOVEL_VALUES["devices"])
            novel_loc = random.choice(NOVEL_VALUES["locations"])

            # Update app
            event["properties"]["appDisplayName"] = novel_app
            event["properties"]["appId"] = "00000000-0000-0000-0000-000000000000"
            anomalous_features.append(f"appDisplayName={novel_app}")

            # Update browser
            event["properties"]["deviceDetail"]["browser"] = novel_browser
            anomalous_features.append(f"deviceDetailbrowser={novel_browser}")

            # Update OS
            event["properties"]["deviceDetail"]["operatingSystem"] = novel_os
            anomalous_features.append(f"deviceDetailoperatingSystem={novel_os}")

            # Update device
            event["properties"]["deviceDetail"]["displayName"] = novel_device
            event["properties"]["deviceDetail"]["deviceId"] = f"novel-device-id-{random.randint(100, 999)}"
            anomalous_features.append(f"deviceDetaildisplayName={novel_device}")

            # Location change with realistic travel time from last generated event
            distance_km = haversine_distance(last_training_lat, last_training_lon, novel_loc["lat"], novel_loc["lon"])

            # Calculate realistic travel time (minimum 2 hours)
            hours_needed = max(calculate_travel_time(distance_km), 2.0)

            # Update timestamp from last generated event (sequential)
            new_timestamp = last_timestamp + timedelta(hours=hours_needed)
            event["time"] = new_timestamp.isoformat()
            self.user_last_timestamp[username] = new_timestamp

            # Update location in all three places
            event["location"]["city"] = novel_loc["city"]
            event["location"]["state"] = novel_loc["state"]
            event["location"]["countryOrRegion"] = novel_loc["country"]
            event["location"]["geoCoordinates"]["latitude"] = novel_loc["lat"]
            event["location"]["geoCoordinates"]["longitude"] = novel_loc["lon"]

            event["properties"]["location"]["city"] = novel_loc["city"]
            event["properties"]["location"]["state"] = novel_loc["state"]
            event["properties"]["location"]["countryOrRegion"] = novel_loc["country"]
            event["properties"]["location"]["geoCoordinates"]["latitude"] = novel_loc["lat"]
            event["properties"]["location"]["geoCoordinates"]["longitude"] = novel_loc["lon"]

            event["location_geoCoordinates_latitude"] = novel_loc["lat"]
            event["location_geoCoordinates_longitude"] = novel_loc["lon"]

            anomalous_features.append(f"locationCity={novel_loc['city']}")
            anomalous_features.append(f"locationCountry={novel_loc['country']}")

        elif anomaly_type == "location_device":
            # Novel location (realistic travel time) + novel device — no app
            # → heuristic: has_device + has_location → Location with Unusual Device
            novel_loc = random.choice(NOVEL_VALUES["locations"])
            novel_device = random.choice([d for d in NOVEL_VALUES["devices"] if "UNKNOWN" not in d])

            distance_km = haversine_distance(last_training_lat, last_training_lon, novel_loc["lat"], novel_loc["lon"])
            hours_needed = max(calculate_travel_time(distance_km), 2.0)
            new_timestamp = last_timestamp + timedelta(hours=hours_needed)
            event["time"] = new_timestamp.isoformat()
            self.user_last_timestamp[username] = new_timestamp

            for loc_dict in (
                event["location"],
                event["properties"]["location"],
            ):
                loc_dict["city"] = novel_loc["city"]
                loc_dict["state"] = novel_loc["state"]
                loc_dict["countryOrRegion"] = novel_loc["country"]
                loc_dict["geoCoordinates"]["latitude"] = novel_loc["lat"]
                loc_dict["geoCoordinates"]["longitude"] = novel_loc["lon"]
            event["location_geoCoordinates_latitude"] = novel_loc["lat"]
            event["location_geoCoordinates_longitude"] = novel_loc["lon"]

            event["properties"]["deviceDetail"]["displayName"] = novel_device
            event["properties"]["deviceDetail"]["deviceId"] = f"novel-device-id-{random.randint(100, 999)}"

            anomalous_features.append(f"locationCity={novel_loc['city']}")
            anomalous_features.append(f"locationCountry={novel_loc['country']}")
            anomalous_features.append(f"deviceDetaildisplayName={novel_device}")

        elif anomaly_type == "unknown_device":
            # Device with UNKNOWN- prefix — triggers heuristic 'Unknown Device' rule
            novel_device = "UNKNOWN-LAPTOP-999"
            event["properties"]["deviceDetail"]["displayName"] = novel_device
            event["properties"]["deviceDetail"]["deviceId"] = f"unknown-device-id-{random.randint(100, 999)}"
            event["properties"]["deviceDetail"]["isManaged"] = False
            event["properties"]["deviceDetail"]["isCompliant"] = False

            time_gap_hours = random.uniform(0.25, 2.0)
            event["time"] = (last_timestamp + timedelta(hours=time_gap_hours)).isoformat()
            self.user_last_timestamp[username] = last_timestamp + timedelta(hours=time_gap_hours)

            anomalous_features.append(f"deviceDetaildisplayName={novel_device}")

        elif anomaly_type == "app_browser":
            # App + browser — low-severity multi-feature, often near threshold
            # → heuristic: has_app only (browser doesn't trigger app rule alone)
            #   but combined app+browser → Multi-Factor is NOT triggered (no device/location)
            #   → falls to Unusual Application rule
            novel_app = random.choice(NOVEL_VALUES["apps"])
            novel_browser = random.choice(NOVEL_VALUES["browsers"])
            event["properties"]["appDisplayName"] = novel_app
            event["properties"]["appId"] = "00000000-0000-0000-0000-000000000000"
            event["properties"]["deviceDetail"]["browser"] = novel_browser

            time_gap_hours = random.uniform(0.25, 2.0)
            event["time"] = (last_timestamp + timedelta(hours=time_gap_hours)).isoformat()
            self.user_last_timestamp[username] = last_timestamp + timedelta(hours=time_gap_hours)

            anomalous_features.append(f"appDisplayName={novel_app}")
            anomalous_features.append(f"deviceDetailbrowser={novel_browser}")

        elif anomaly_type == "app_device":
            # App + device (no location) — medium severity
            # → heuristic rule 2: has_app + has_device → Multi-Factor Anomaly
            novel_app = random.choice(NOVEL_VALUES["apps"])
            novel_device = random.choice([d for d in NOVEL_VALUES["devices"] if "UNKNOWN" not in d])
            event["properties"]["appDisplayName"] = novel_app
            event["properties"]["appId"] = "00000000-0000-0000-0000-000000000000"
            event["properties"]["deviceDetail"]["displayName"] = novel_device
            event["properties"]["deviceDetail"]["deviceId"] = f"novel-device-id-{random.randint(100, 999)}"

            time_gap_hours = random.uniform(0.25, 2.0)
            event["time"] = (last_timestamp + timedelta(hours=time_gap_hours)).isoformat()
            self.user_last_timestamp[username] = last_timestamp + timedelta(hours=time_gap_hours)

            anomalous_features.append(f"appDisplayName={novel_app}")
            anomalous_features.append(f"deviceDetaildisplayName={novel_device}")

        elif anomaly_type == "high_logcount":
            # Excessive login activity well above user's daily baseline
            # → heuristic fallback: Broad Deviation (no specific feature present)
            time_gap_hours = random.uniform(0.25, 4.0)
            event["time"] = (last_timestamp + timedelta(hours=time_gap_hours)).isoformat()
            self.user_last_timestamp[username] = last_timestamp + timedelta(hours=time_gap_hours)

            anomalous_features.append("logCount=excessive_activity")

        return event, anomalous_features

    def create_detection_from_event(self, event: dict[str, Any], anomalous_features: list[str]) -> dict[str, Any]:
        """
        Create a detection record from an event.

        Simulates what DFP would produce (scores don't need to be exact).

        Args:
            event: Azure AD SignInLog event
            anomalous_features: List of anomalous feature strings

        Returns:
            Detection record dict matching CSV format
        """
        user_id = event["identity"]
        timestamp = event["time"]

        # ── Scoring model (updated 2026-03-09) ────────────────────────────────
        # Reflects real DFP behaviour: score is a statistical Z-score aggregate
        # that depends heavily on how far a feature deviates from the user model.
        #
        # Severity bands (used by heuristic_label.py):
        #   < 2.0         : below detection threshold — never stored
        #   2.0 – 2.5     : LOW  (possible false positive, very mild deviation)
        #   2.5 – 3.0     : MEDIUM (borderline, low-confidence TP)
        #   3.0 – 5.0     : HIGH (real anomaly, single/double feature)
        #   > 5.0         : CRITICAL (impossible travel, mass deviation)
        #
        # Key rules:
        #   - App or browser ALONE rarely exceed 2.0 (often not even detected)
        #   - App + browser combined stay in 2.0–2.5 range (very low)
        #   - Device alone: 2.5–3.5 (crosses threshold but modest)
        #   - OS alone: 2.5–3.5
        #   - Location alone (realistic travel): 2.5–4.0
        #   - App + device: 3.0–4.5 (multi-factor, reliably above threshold)
        #   - Location + device: 3.5–5.5 (higher — two independent signals)
        #   - Unknown device: 3.0–4.5 (unmanaged + unrecognised)
        #   - App + browser + os + device (all): 5.0–8.0 (high multi-factor)
        #   - Impossible travel: 8.0–20.0  (always CRITICAL)
        #   - High logcount alone: 2.5–4.0 (depends on how much it exceeds baseline)
        feat_str = " ".join(anomalous_features)

        if "travel_speed_kmph" in feat_str:
            # Impossible travel — always CRITICAL
            anomaly_score = random.uniform(8.0, 20.0)
            max_abs_z = random.uniform(15.0, 35.0)

        elif "logCount=excessive_activity" in feat_str:
            # High login count — Broad Deviation, score varies with excess amount
            anomaly_score = random.uniform(2.5, 4.0)
            max_abs_z = random.uniform(5.0, 10.0)

        elif len(anomalous_features) >= 5:
            # All features anomalous (app + browser + os + device + location)
            anomaly_score = random.uniform(5.0, 8.0)
            max_abs_z = random.uniform(10.0, 20.0)

        elif (
            "locationcity" in feat_str.lower() or "locationcountry" in feat_str.lower()
        ) and "devicedetail" in feat_str.lower():
            # Location + device — two independent signals: HIGH to low-CRITICAL
            anomaly_score = random.uniform(3.5, 5.5)
            max_abs_z = random.uniform(8.0, 15.0)

        elif "locationcity" in feat_str.lower() or "locationcountry" in feat_str.lower():
            # Location alone (realistic travel time, not impossible)
            anomaly_score = random.uniform(2.5, 4.0)
            max_abs_z = random.uniform(5.0, 10.0)

        elif "appdisplayname" in feat_str.lower() and "devicedetail" in feat_str.lower():
            # App + device (no location) — multi-factor, reliably HIGH
            anomaly_score = random.uniform(3.0, 4.5)
            max_abs_z = random.uniform(6.0, 12.0)

        elif "unknown" in feat_str.lower() and "devicedetail" in feat_str.lower():
            # Unknown/unmanaged device
            anomaly_score = random.uniform(3.0, 4.5)
            max_abs_z = random.uniform(6.0, 10.0)

        elif "devicedetailoperatingsystem" in feat_str.lower():
            # Unusual OS alone
            anomaly_score = random.uniform(2.5, 3.5)
            max_abs_z = random.uniform(4.0, 8.0)

        elif (
            sum(
                1
                for f in ("devicedetailbrowser", "devicedetaildisplayname", "devicedetailoperatingsystem")
                if f in feat_str.lower()
            )
            >= 1
            and "appdisplayname" not in feat_str.lower()
        ):
            # Device name or browser alone (no app, no location)
            anomaly_score = random.uniform(2.5, 3.5)
            max_abs_z = random.uniform(4.0, 8.0)

        elif "appdisplayname" in feat_str.lower() and "devicedetailbrowser" in feat_str.lower():
            # App + browser only — low combined signal, often near threshold
            anomaly_score = random.uniform(2.0, 2.8)
            max_abs_z = random.uniform(3.0, 6.0)

        elif "appdisplayname" in feat_str.lower():
            # App alone — weakest signal, near detection threshold
            anomaly_score = random.uniform(2.0, 2.6)
            max_abs_z = random.uniform(2.5, 5.0)

        else:
            # Fallback
            anomaly_score = random.uniform(2.0, 3.0)
            max_abs_z = random.uniform(3.0, 6.0)

        # Build top_features string (matches CSV format: "feature=value (z=X.XX), ...")
        # logCount pseudo-feature gets special treatment so heuristic labeler can detect it.
        top_features_parts = []
        min_z_score = max(2.0, max_abs_z * 0.5)  # z-scores span lower half → upper of max_abs_z
        for feature in anomalous_features[:5]:  # Top 5
            if feature == "logCount=excessive_activity":
                # Express as a realistic count exceeding baseline
                excess_factor = random.uniform(2.5, 6.0)
                count_val = int(random.uniform(80, 200) * excess_factor)
                z_score = random.uniform(min_z_score, max_abs_z)
                top_features_parts.append(f"logCount={count_val} (z={z_score:.2f})")
            elif "=" in feature:
                name, value = feature.split("=", 1)
                z_score = random.uniform(min_z_score, max_abs_z)
                top_features_parts.append(f"{name}={value} (z={z_score:.2f})")

        top_features = ", ".join(top_features_parts) if top_features_parts else "normal_behavior (z=2.1)"

        return {
            "user_id": user_id,
            "timestamp": timestamp,
            "anomaly_score": round(anomaly_score, 6),
            "max_abs_z": round(max_abs_z, 6),
            "threshold": 2.0,
            "anomaly_source": "dfp",
            "event_count": random.randint(50, 200),
            "feature_count": random.randint(15, 30),
            "top_features": top_features,
        }

    def generate_paired_record(self, username: str | None = None, anomaly_type: str = "random") -> dict[str, Any]:
        """
        Generate a single paired (event, detection) record for a user.

        Args:
            username: User email (random if None)
            anomaly_type: Type of anomaly to generate

        Returns:
            dict: {"original_event": {...}, "detection": {...}, "anomaly_type": "..."}
        """
        if username is None:
            username = random.choice(self.users)

        # Select random anomaly type if not specified
        if anomaly_type == "random":
            anomaly_type = random.choice(self.anomaly_types)

        # Generate anomalous event using user's baseline
        event, anomalous_features = self.generate_anomalous_event(username, anomaly_type)

        # Create detection from event (simulated DFP scoring)
        detection = self.create_detection_from_event(event, anomalous_features)

        return {"original_event": event, "detection": detection, "anomaly_type": anomaly_type}

    def generate_batch(
        self, count: int, output_path: str, anomaly_distribution: dict[str, float] | None = None
    ) -> dict[str, Any]:
        """
        Generate batch of paired records.

        Args:
            count: Number of paired records to generate
            output_path: Path to output JSONL file
            anomaly_distribution: Distribution of anomaly types
                Example: {"app": 0.2, "browser": 0.15, "location": 0.3, ...}

        Returns:
            dict: Generation statistics
        """
        if anomaly_distribution is None:
            # Updated 2026-03-09: covers all 9 sub_categories for DistilBERT training diversity.
            # Types that map to each heuristic class:
            #   impossible_travel → Impossible Travel
            #   location          → Unusual Location
            #   location_device   → Location with Unusual Device
            #   unknown_device    → Unknown Device
            #   app / app_browser → Unusual Application  (app alone may score < 2.0)
            #   app_device        → Multi-Factor Anomaly  (app + device)
            #   all               → Multi-Factor Anomaly  (all features)
            #   browser           → Unusual Browser
            #   os                → Unusual Operating System
            #   high_logcount     → Broad Deviation
            anomaly_distribution = {
                "impossible_travel": 0.14,  # → Impossible Travel
                "location": 0.10,  # → Unusual Location
                "location_device": 0.10,  # → Location with Unusual Device
                "unknown_device": 0.10,  # → Unknown Device
                "app": 0.08,  # → Unusual Application (some below threshold)
                "app_browser": 0.07,  # → Unusual Application (low combined)
                "app_device": 0.10,  # → Multi-Factor Anomaly
                "all": 0.07,  # → Multi-Factor Anomaly
                "browser": 0.08,  # → Unusual Browser
                "os": 0.08,  # → Unusual Operating System
                "device": 0.04,  # → Broad Deviation (device, no app/loc)
                "high_logcount": 0.04,  # → Broad Deviation
            }

        print(f"\n{'=' * 70}")
        print(f"Generating {count} paired (event, detection) records")
        print(f"{'=' * 70}\n")

        # Build anomaly type list based on distribution
        anomaly_types = []
        for anom_type, ratio in anomaly_distribution.items():
            anomaly_types.extend([anom_type] * int(count * ratio))

        # Pad to exact count
        while len(anomaly_types) < count:
            anomaly_types.append(random.choice(list(anomaly_distribution.keys())))

        random.shuffle(anomaly_types)

        # Distribute records across users evenly (round-robin)
        user_cycle = self.users * (count // len(self.users) + 1)  # Repeat user list to cover all records
        random.shuffle(user_cycle)  # Shuffle for randomness, but ensures even distribution

        # Generate records
        output_file = Path(output_path)
        output_file.parent.mkdir(parents=True, exist_ok=True)

        stats = {
            "total": count,
            "by_type": dict.fromkeys(anomaly_distribution.keys(), 0),
            "by_user": {},
        }

        with open(output_file, "w") as f:
            for i, (anomaly_type, username) in enumerate(zip(anomaly_types, user_cycle, strict=False)):
                # Generate paired record for specific user (ensures sequential timestamps)
                paired = self.generate_paired_record(username=username, anomaly_type=anomaly_type)

                # Write as JSONL
                f.write(json.dumps(paired) + "\n")

                # Update stats
                stats["by_type"][anomaly_type] += 1
                user = paired["detection"]["user_id"]
                stats["by_user"][user] = stats["by_user"].get(user, 0) + 1

                if (i + 1) % 100 == 0:
                    print(f"Progress: {i + 1}/{count} records generated")

        print(f"\nGenerated {count} paired records")
        print(f"   Output: {output_file}")
        print("\n   Distribution by type:")
        for anom_type, cnt in sorted(stats["by_type"].items()):
            print(f"     - {anom_type:20s}: {cnt:4d} ({cnt / count * 100:5.1f}%)")
        print("\n   Distribution by user:")
        print(f"     Total users: {len(stats['by_user'])}")
        top_users = sorted(stats["by_user"].items(), key=lambda x: x[1], reverse=True)[:5]
        for user, cnt in top_users:
            print(f"     - {user:40s}: {cnt:4d}")

        return stats


def main():
    """Generate synthetic paired data"""
    parser = argparse.ArgumentParser(
        description="Generate synthetic paired (event, detection) data using real user baselines"
    )
    parser.add_argument("--count", type=int, default=100, help="Number of records to generate (default: 100)")
    parser.add_argument(
        "--output", default="data/input/ai/synthetic_paired_detections.jsonl", help="Output file path (JSONL format)"
    )
    parser.add_argument("--seed", type=int, default=42, help="Random seed for reproducibility (default: 42)")
    parser.add_argument("--users", type=int, default=20, help="Number of users to generate data for (default: 20)")
    args = parser.parse_args()

    # Generate data
    generator = SyntheticPairedDataGenerator(seed=args.seed, num_users=args.users)
    generator.generate_batch(args.count, args.output)

    print(f"\n{'=' * 70}")
    print("Generation complete!")
    print(f"{'=' * 70}")
    print("\nNext steps:")
    print("  1. Clear databases: python scripts/clear_test_data.py --confirm")
    print(
        f"  2. Test enrichment: cd dfp-demo && python modules/ai/enrichment/enrichment_service.py --jsonl {args.output} --limit 10 --save"
    )
    print("\n")


if __name__ == "__main__":
    main()
