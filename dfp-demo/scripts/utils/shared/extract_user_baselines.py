"""
Extract user baselines from training data to populate config/user_baselines.yaml

This utility analyzes your 70 days of CLEAN training data and automatically
generates user baseline configurations for all 50 trained users.

Usage:
    python scripts/utils/extract_user_baselines.py \
        --input data/input/train/azure_ad_train.jsonl \
        --output config/user_baselines_generated.yaml

The generated file can then be reviewed and merged into config/user_baselines.yaml
"""

import argparse
import json
import logging
from collections import Counter
from typing import Any

import pandas as pd
import yaml

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class UserBaselineExtractor:
    """
    Analyze training data and extract behavioral baselines per user.

    For each user, extracts:
    - Typical applications used
    - Typical locations (city, lat, lon)
    - Typical browsers and OS
    - Work hours (start and end)
    - Work days (which days of week are active)
    - Activity ranges (min/max events per session)
    - Never-accessed applications
    - Travel patterns
    """

    def __init__(self, training_data_paths: list[str]):
        """Load training data from JSONL files with Azure AD schema."""
        logger.info(f"Loading training data from {len(training_data_paths)} files...")

        records = []
        for path in training_data_paths:
            logger.info(f"  Reading {path}...")
            with open(path) as f:
                for line in f:
                    try:
                        rec = json.loads(line)
                        # Normalize Azure AD schema to flat structure
                        normalized = {
                            "username": rec.get("identity"),
                            "timestamp": rec.get("time"),
                            "appDisplayName": rec.get("properties", {}).get("appDisplayName"),
                            "location": rec.get("location", {}).get("city"),
                            "latitude": rec.get("location_geoCoordinates_latitude"),
                            "longitude": rec.get("location_geoCoordinates_longitude"),
                            "deviceDetailbrowser": rec.get("properties", {}).get("deviceDetail", {}).get("browser"),
                            "deviceDetailoperatingSystem": rec.get("properties", {})
                            .get("deviceDetail", {})
                            .get("operatingSystem"),
                        }
                        records.append(normalized)
                    except json.JSONDecodeError as e:
                        logger.warning(f"Skipping malformed line: {e}")
                        continue

        self.df = pd.DataFrame(records)
        logger.info(f"Loaded {len(self.df)} records")

        # Convert timestamp to datetime
        if "timestamp" in self.df.columns:
            self.df["timestamp"] = pd.to_datetime(self.df["timestamp"], errors="coerce")
            self.df["hour"] = self.df["timestamp"].dt.hour  # type: ignore
            self.df["day_of_week"] = self.df["timestamp"].dt.dayofweek  # type: ignore

        # Get unique users
        if "username" in self.df.columns:
            self.users = self.df["username"].dropna().unique()
            logger.info(f"Found {len(self.users)} unique users")
        else:
            raise ValueError("Training data must have 'username' column")

    def extract_baseline_for_user(self, username: str) -> dict[str, Any] | None:
        """Extract baseline behavior for specific user."""
        user_df = self.df[self.df["username"] == username]

        if len(user_df) == 0:
            logger.warning(f"No data found for user: {username}")
            return None

        logger.info(f"Extracting baseline for {username} ({len(user_df)} records)...")

        baseline = {"normal_behavior": {}}

        behavior = baseline["normal_behavior"]

        # 1. Typical applications
        if "appDisplayName" in user_df.columns:
            app_counts = user_df["appDisplayName"].value_counts()
            # Apps that appear in >5% of sessions
            threshold = len(user_df) * 0.05
            typical_apps = app_counts[app_counts > threshold].index.tolist()  # type: ignore
            behavior["typical_apps"] = typical_apps[:10]  # Top 10

        # 2. Typical locations
        if all(col in user_df.columns for col in ["location", "latitude", "longitude"]):
            location_data = user_df.groupby(["location", "latitude", "longitude"]).size()
            location_data = location_data.sort_values(ascending=False)

            typical_locations = []
            for idx, _ in location_data.head(3).items():  # type: ignore
                city, lat, lon = idx  # type: ignore  # Unpack the tuple index
                typical_locations.append({"city": str(city), "lat": float(lat), "lon": float(lon)})
            behavior["typical_locations"] = typical_locations

        # 3. Typical browsers
        if "deviceDetailbrowser" in user_df.columns:
            browser_counts = user_df["deviceDetailbrowser"].value_counts()
            threshold = len(user_df) * 0.05
            typical_browsers = browser_counts[browser_counts > threshold].index.tolist()  # type: ignore
            behavior["typical_browsers"] = typical_browsers

        # 4. Typical OS
        if "deviceDetailoperatingSystem" in user_df.columns:
            os_counts = user_df["deviceDetailoperatingSystem"].value_counts()
            threshold = len(user_df) * 0.05
            typical_os = os_counts[os_counts > threshold].index.tolist()  # type: ignore
            behavior["typical_os"] = typical_os

        # 5. Work hours
        if "hour" in user_df.columns:
            hour_counts = user_df["hour"].value_counts()
            # Find hours with significant activity (>5% of records)
            threshold = len(user_df) * 0.05
            active_hours = hour_counts[hour_counts > threshold].index.tolist()  # type: ignore

            if active_hours:
                work_start = min(active_hours)
                work_end = max(active_hours)
            else:
                # Default 9-5
                work_start = 9
                work_end = 17

            behavior["work_hours"] = {"start": int(work_start), "end": int(work_end)}

        # 6. Work days
        if "day_of_week" in user_df.columns:
            day_counts = user_df["day_of_week"].value_counts()
            threshold = len(user_df) * 0.05
            work_days = sorted(day_counts[day_counts > threshold].index.tolist())  # type: ignore
            behavior["work_days"] = work_days

        # 7. Activity range
        if "activity_count" in user_df.columns:
            activity_counts = user_df["activity_count"]
            behavior["typical_activity_range"] = {
                "min": int(activity_counts.quantile(0.1)),  # 10th percentile
                "max": int(activity_counts.quantile(0.9)),  # 90th percentile
            }
        else:
            # Estimate from number of records per session
            # Group by date and count
            if "timestamp" in user_df.columns:
                user_df["date"] = user_df["timestamp"].dt.date  # type: ignore
                daily_counts = user_df.groupby("date").size()
                behavior["typical_activity_range"] = {
                    "min": int(daily_counts.quantile(0.1)),
                    "max": int(daily_counts.quantile(0.9)),
                }

        # 8. Apps per session
        if "appDisplayName" in user_df.columns and "timestamp" in user_df.columns:
            user_df["date"] = user_df["timestamp"].dt.date  # type: ignore
            apps_per_day = user_df.groupby("date")["appDisplayName"].nunique()
            behavior["typical_apps_per_session"] = int(apps_per_day.median())

        # 9. Never accessed (from global app list)
        all_apps = set(self.df["appDisplayName"].unique()) if "appDisplayName" in self.df.columns else set()
        user_apps = set(user_df["appDisplayName"].unique()) if "appDisplayName" in user_df.columns else set()
        never_accessed = list(all_apps - user_apps)

        # Only include common apps that this user never touched
        common_apps = ["Azure Portal", "AWS Console", "GitHub", "Salesforce", "SAP", "Jira"]
        behavior["never_accessed"] = [app for app in common_apps if app in never_accessed]

        # 10. Travel pattern
        if "location" in user_df.columns:
            unique_locations = user_df["location"].nunique()
            if unique_locations == 1:
                travel_pattern = "stationary"
            elif unique_locations <= 3:
                travel_pattern = "occasional"
            else:
                travel_pattern = "frequent"
            behavior["travel_pattern"] = travel_pattern

        # 11. Privileged access (heuristic: accesses admin portals)
        if "appDisplayName" in user_df.columns:
            admin_apps = ["Azure Portal", "AWS Console", "Admin Console", "Active Directory"]
            has_admin_access = any(app in user_df["appDisplayName"].values for app in admin_apps)
            behavior["privileged_access"] = bool(has_admin_access)

        # 12. User role (heuristic based on apps)
        if "appDisplayName" in user_df.columns:
            apps = set(user_df["appDisplayName"].unique())

            if any(app in apps for app in ["Azure Portal", "AWS Console", "GitHub"]):
                user_role = "engineering"
            elif any(app in apps for app in ["Salesforce", "LinkedIn", "HubSpot"]):
                user_role = "sales_marketing"
            elif any(app in apps for app in ["SAP", "QuickBooks", "NetSuite"]):
                user_role = "finance"
            elif any(app in apps for app in ["Workday", "LinkedIn Recruiter"]):
                user_role = "hr"
            else:
                user_role = "general"

            behavior["user_role"] = user_role

        return baseline

    def extract_all_baselines(self) -> dict[str, Any]:
        """Extract baselines for all users."""
        config = {
            "users": {},
            "anomaly_distribution": {
                "percentage_users_with_anomalies": 0.35,
                "anomaly_types": {
                    "impossible_travel": {
                        "probability": 0.25,
                        "description": "Access from geographically distant location in impossible timeframe",
                        "severity": "high",
                        "applies_to": "all",
                    },
                    "off_hours_access": {
                        "probability": 0.20,
                        "description": "Access outside trained work hours (per user baseline)",
                        "severity": "medium",
                        "applies_to": ["users without late-night work pattern"],
                    },
                    "unusual_application": {
                        "probability": 0.15,
                        "description": "Access to application never seen during training",
                        "severity": "medium",
                        "applies_to": "all",
                    },
                    "excessive_activity": {
                        "probability": 0.20,
                        "description": "Activity count > 2x user's typical maximum",
                        "severity": "medium",
                        "applies_to": "all",
                    },
                    "privilege_escalation": {
                        "probability": 0.10,
                        "description": "Non-privileged user accessing admin resources",
                        "severity": "critical",
                        "applies_to": ["users without privileged_access"],
                    },
                    "unusual_device": {
                        "probability": 0.10,
                        "description": "Access from browser/OS never seen in training",
                        "severity": "low",
                        "applies_to": "all",
                        "malicious": False,
                    },
                },
            },
            "settings": {
                "global_locations": [
                    {"city": "Moscow, Russia", "lat": 55.7558, "lon": 37.6173, "suspicious": True},
                    {"city": "Beijing, China", "lat": 39.9042, "lon": 116.4074, "suspicious": False},
                    {"city": "Lagos, Nigeria", "lat": 6.5244, "lon": 3.3792, "suspicious": True},
                    {"city": "Sydney, Australia", "lat": -33.8688, "lon": 151.2093, "suspicious": False},
                    {"city": "London, UK", "lat": 51.5074, "lon": -0.1278, "suspicious": False},
                ],
                "unusual_applications": [
                    "TOR Browser",
                    "Kali Linux Tools",
                    "Anonymous VPN",
                    "File Transfer Pro",
                    "Cryptocurrency Wallet",
                ],
                "default_date_range": {"start_days_ago": 30, "end_days_ago": 0},
            },
        }

        for username in self.users:  # type: ignore
            baseline = self.extract_baseline_for_user(str(username))
            if baseline:
                config["users"][str(username)] = baseline

        logger.info(f"✅ Extracted baselines for {len(config['users'])} users")

        return config

    def save_config(self, config: dict, output_path: str):
        """Save config to YAML file."""
        with open(output_path, "w") as f:
            yaml.dump(config, f, default_flow_style=False, sort_keys=False, allow_unicode=True)

        logger.info(f"✅ Saved configuration to: {output_path}")

    def print_summary(self, config: dict):
        """Print summary of extracted baselines."""
        logger.info("\n" + "=" * 60)
        logger.info("BASELINE EXTRACTION SUMMARY")
        logger.info("=" * 60)
        logger.info(f"Total users: {len(config['users'])}")

        # Count users by role
        role_counts = Counter()
        for _, data in config["users"].items():
            if data:
                role = data.get("normal_behavior", {}).get("user_role", "unknown")
                role_counts[role] += 1

        logger.info("\nUsers by Role:")
        for role, count in role_counts.most_common():
            logger.info(f"  {role}: {count}")

        # Count privileged users
        privileged_count = sum(
            1
            for _, data in config["users"].items()
            if data and data.get("normal_behavior", {}).get("privileged_access", False)
        )
        logger.info(f"\nPrivileged users: {privileged_count}")

        # Travel patterns
        travel_counts = Counter()
        for _, data in config["users"].items():
            if data:
                travel = data.get("normal_behavior", {}).get("travel_pattern", "unknown")
                travel_counts[travel] += 1

        logger.info("\nTravel Patterns:")
        for pattern, count in travel_counts.most_common():
            logger.info(f"  {pattern}: {count}")

        logger.info("\n" + "=" * 60)
        logger.info("✅ Review the generated file and adjust as needed")
        logger.info("=" * 60 + "\n")


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(description="Extract user baselines from training data")
    parser.add_argument(
        "--input",
        type=str,
        nargs="+",
        default=["data/input/train/azure_ad_train.jsonl"],
        help="Input training data JSONL files (default: data/input/train/azure_ad_train.jsonl)",
    )
    parser.add_argument(
        "--output",
        type=str,
        default="config/user_baselines_generated.yaml",
        help="Output YAML file path",
    )

    args = parser.parse_args()

    # Expand wildcards
    from glob import glob

    input_files = []
    for pattern in args.input:
        input_files.extend(glob(pattern))

    if not input_files:
        logger.error(f"No files found matching patterns: {args.input}")
        return

    logger.info(f"Found {len(input_files)} input files")

    # Extract baselines
    extractor = UserBaselineExtractor(input_files)
    config = extractor.extract_all_baselines()

    # Save
    extractor.save_config(config, args.output)

    # Print summary
    extractor.print_summary(config)

    logger.info(f"\n✅ DONE! Review and edit: {args.output}")
    logger.info("Then merge into: config/user_baselines.yaml")


if __name__ == "__main__":
    main()
