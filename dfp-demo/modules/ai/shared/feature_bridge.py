#!/usr/bin/env python3
"""
Feature Bridge: DFP → AI Feature Transformation

Bridges DFP FilterDetections output to structured AI features.
Parses detection CSV format and extracts entities, relationships, and context
for downstream AI components (entity extraction, embeddings, clustering, graph).

Architecture:
    Input: FilterDetections CSV (user_id, timestamp, anomaly_score, top_features)
    Output: Structured Detection objects with parsed features, entities, metadata

    Detection Format:
        user_id,timestamp,anomaly_score,max_abs_z,threshold,anomaly_source,
        event_count,feature_count,top_features

    top_features Format:
        "feature1=value (z=X.XX), feature2=value (z=Y.YY), ..."

Usage:
    >>> bridge = FeatureBridge()
    >>> detections = bridge.load_detections('data/input/ai/synthetic_paired_detections.csv')
    >>> for detection in detections:
    ...     print(detection.user_id, detection.entities)

Reference:
    docs/implementation/DFP_PIPELINE_TECHNICAL_ANALYSIS.md
    modules/inference/filter_detections.py (detection output format)

Author: AI Intelligence Layer Team
Date: 2026-02-19
"""

import logging
import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd

logger = logging.getLogger(__name__)


@dataclass
class ParsedFeature:
    """
    Single feature extracted from top_features string.

    Attributes:
        name: Feature name (e.g., 'appDisplayName', 'travel_speed_kmph')
        value: Feature value (e.g., 'Office365', 2723)
        z_score: Z-score indicating deviation (e.g., 18.06)
        category: Feature category ('app', 'device', 'location', 'activity')
    """

    name: str
    value: Any
    z_score: float
    category: str

    def __post_init__(self):
        """Automatically categorize feature based on name."""
        if not self.category:
            self.category = self._categorize_feature()

    def _categorize_feature(self) -> str:
        """Categorize feature by name pattern."""
        if "app" in self.name.lower():
            return "app"
        elif "device" in self.name.lower() or "browser" in self.name.lower() or "operating" in self.name.lower():
            return "device"
        elif "loc" in self.name.lower() or "travel" in self.name.lower():
            return "location"
        elif "logcount" in self.name.lower():
            return "activity"
        else:
            return "other"


@dataclass
class DetectionRecord:
    """
    Structured detection record with parsed features.

    Attributes:
        user_id: User identifier (email)
        timestamp: Detection timestamp (ISO format with timezone)
        anomaly_score: Mean absolute z-score (mean_abs_z)
        max_abs_z: Maximum z-score across all features
        threshold: DFP threshold (2.0)
        anomaly_source: Source of detection ('dfp')
        event_count: Number of events contributing (typically 1)
        feature_count: Total features analyzed (typically 10)
        top_features_raw: Unparsed top_features string
        parsed_features: List of ParsedFeature objects
        entities: Extracted entities (apps, devices, browsers, OS)
        severity: Categorized severity (CRITICAL, HIGH, MEDIUM, LOW)
    """

    user_id: str
    timestamp: str
    anomaly_score: float
    max_abs_z: float
    threshold: float
    anomaly_source: str
    event_count: int
    feature_count: int
    top_features_raw: str
    parsed_features: list[ParsedFeature] = field(default_factory=list)
    features_list: list[dict] = field(default_factory=list)
    entities: dict[str, list[str]] = field(default_factory=dict)
    severity: str = ""

    def __post_init__(self):
        """Initialize derived fields."""
        if not self.severity:
            self.severity = self._calculate_severity()
        if not self.entities:
            self.entities = self._extract_entities()

    def _calculate_severity(self) -> str:
        """Calculate severity based on anomaly score."""
        from scripts.utils import severity_from_score

        return severity_from_score(self.anomaly_score)

    def _extract_entities(self) -> dict[str, list[str]]:
        """Extract entities from parsed features."""
        entities: dict[str, list[str]] = {
            "users": [self.user_id],
            "apps": [],
            "devices": [],
            "browsers": [],
            "os": [],
        }

        for feature in self.parsed_features:
            if feature.name == "appDisplayName" and feature.value:
                entities["apps"].append(str(feature.value))
            elif feature.name == "deviceDetaildisplayName" and feature.value:
                entities["devices"].append(str(feature.value))
            elif feature.name == "deviceDetailbrowser" and feature.value:
                entities["browsers"].append(str(feature.value))
            elif feature.name == "deviceDetailoperatingSystem" and feature.value:
                entities["os"].append(str(feature.value))

        return entities

    def get_timestamp_datetime(self) -> datetime:
        """Parse timestamp string to datetime object."""
        return datetime.fromisoformat(self.timestamp)

    def get_features_by_category(self, category: str) -> list[ParsedFeature]:
        """Get all features in a specific category."""
        return [f for f in self.parsed_features if f.category == category]

    def get_feature_dict(self) -> dict[str, Any]:
        """Convert parsed features to simple dict for downstream use."""
        return {f.name: f.value for f in self.parsed_features}


class FeatureBridge:
    """
    Bridge DFP detections to structured AI features.

    Parses FilterDetections CSV output and provides clean interfaces
    for AI components (entity extraction, embeddings, clustering, graph).

    Methods:
        load_detections(csv_path): Load and parse detection CSV
        parse_top_features(top_features_str): Parse top_features string
        get_detection_summary(detections): Generate dataset summary
    """

    # Regex pattern to parse "feature=value (z=X.XX)" format
    FEATURE_PATTERN = re.compile(r"(\w+)=([^(]+)\s*\(z=([\d.]+)\)")

    def __init__(self):
        """Initialize FeatureBridge."""
        logger.info("Initialized FeatureBridge")

    def parse_top_features(self, top_features_str: str) -> list[ParsedFeature]:
        """
        Parse top_features string into structured ParsedFeature objects.

        Args:
            top_features_str: String like "feature1=value (z=X.XX), feature2=value (z=Y.YY)"

        Returns:
            List of ParsedFeature objects

        Example:
            >>> bridge = FeatureBridge()
            >>> features = bridge.parse_top_features(
            ...     "travel_speed_kmph=2723 (z=18.06), logcount=12 (z=3.80)"
            ... )
            >>> print(features[0].name, features[0].value, features[0].z_score)
            travel_speed_kmph 2723 18.06
        """
        parsed_features = []

        # Split by comma (handles quoted strings properly)
        for feature_str in top_features_str.split(", "):
            match = self.FEATURE_PATTERN.search(feature_str)
            if match:
                feature_name = match.group(1).strip()
                feature_value_raw = match.group(2).strip()
                z_score = float(match.group(3))

                # Type conversion for known numeric features
                if feature_name in ("logcount", "locincrement", "appincrement", "travel_speed_kmph"):
                    try:
                        feature_value: Any = int(feature_value_raw)
                    except ValueError:
                        feature_value = feature_value_raw
                else:
                    feature_value = feature_value_raw

                parsed_feature = ParsedFeature(
                    name=feature_name,
                    value=feature_value,
                    z_score=z_score,
                    category="",  # Auto-categorized
                )
                parsed_features.append(parsed_feature)
            else:
                logger.warning(f"Could not parse feature string: {feature_str}")

        return parsed_features

    def load_detections(self, csv_path: str | Path, limit: int | None = None) -> list[DetectionRecord]:
        """
        Load and parse detection CSV into structured DetectionRecord objects.

        Args:
            csv_path: Path to FilterDetections CSV file
            limit: Optional limit on number of detections to load

        Returns:
            List of DetectionRecord objects

        Raises:
            FileNotFoundError: If CSV file not found
            ValueError: If CSV format is invalid

        Example:
            >>> bridge = FeatureBridge()
            >>> detections = bridge.load_detections('data/input/ai/synthetic_paired_detections.csv', limit=100)
            >>> print(f"Loaded {len(detections)} detections")
            >>> print(f"First detection: {detections[0].user_id} - {detections[0].severity}")
        """
        csv_path = Path(csv_path)

        if not csv_path.exists():
            raise FileNotFoundError(f"Detection CSV not found: {csv_path}")

        logger.info(f"Loading detections from {csv_path}")

        # Load CSV
        df = pd.read_csv(csv_path)

        if limit:
            df = df.head(limit)
            logger.info(f"Limited to {limit} detections")

        # Validate required columns
        required_cols = [
            "user_id",
            "timestamp",
            "anomaly_score",
            "max_abs_z",
            "threshold",
            "anomaly_source",
            "event_count",
            "feature_count",
            "top_features",
        ]
        missing_cols = [col for col in required_cols if col not in df.columns]
        if missing_cols:
            raise ValueError(f"CSV missing required columns: {missing_cols}")

        # Parse each row into DetectionRecord
        detections = []
        for _, row in df.iterrows():
            # Parse top_features string
            parsed_features = self.parse_top_features(row["top_features"])

            # Create DetectionRecord
            detection = DetectionRecord(
                user_id=row["user_id"],
                timestamp=row["timestamp"],
                anomaly_score=float(row["anomaly_score"]),
                max_abs_z=float(row["max_abs_z"]),
                threshold=float(row["threshold"]),
                anomaly_source=row["anomaly_source"],
                event_count=int(row["event_count"]),
                feature_count=int(row["feature_count"]),
                top_features_raw=row["top_features"],
                parsed_features=parsed_features,
            )

            detections.append(detection)

        logger.info(f"Loaded {len(detections)} detections successfully")
        logger.info(f"  Date range: {detections[0].timestamp} to {detections[-1].timestamp}")
        logger.info(f"  Unique users: {len({d.user_id for d in detections})}")
        logger.info(
            f"  Avg features/detection: {sum(len(d.parsed_features) for d in detections) / len(detections):.1f}"
        )

        return detections

    def dict_to_detection(self, detection_dict: dict[str, Any]) -> DetectionRecord:
        """
        Convert detection dictionary to DetectionRecord object.

        Used for loading paired (event, detection) records from JSONL.

        Args:
            detection_dict: Detection data as dict (from JSONL)

        Returns:
            DetectionRecord object

        Example:
            >>> bridge = FeatureBridge()
            >>> detection_dict = {
            ...     "user_id": "user@example.com",
            ...     "timestamp": "2026-01-19T12:41:19.323731",
            ...     "anomaly_score": 3.125513,
            ...     "max_abs_z": 12.34,
            ...     "threshold": 2.0,
            ...     "anomaly_source": "user_behavioral_anomaly",
            ...     "event_count": 100,
            ...     "feature_count": 20,
            ...     "top_features": "travel_speed_kmph=2723 (z=18.06), ..."
            ... }
            >>> detection = bridge.dict_to_detection(detection_dict)
        """
        # Parse top_features string
        parsed_features = self.parse_top_features(detection_dict["top_features"])

        # Create DetectionRecord
        return DetectionRecord(
            user_id=detection_dict["user_id"],
            timestamp=detection_dict["timestamp"],
            anomaly_score=float(detection_dict["anomaly_score"]),
            max_abs_z=float(detection_dict["max_abs_z"]),
            threshold=float(detection_dict["threshold"]),
            anomaly_source=detection_dict["anomaly_source"],
            event_count=int(detection_dict["event_count"]),
            feature_count=int(detection_dict["feature_count"]),
            top_features_raw=detection_dict["top_features"],
            parsed_features=parsed_features,
            features_list=detection_dict.get("features", []),
        )

    def get_detection_summary(self, detections: list[DetectionRecord]) -> dict[str, Any]:
        """
        Generate summary statistics for detection dataset.

        Args:
            detections: List of DetectionRecord objects

        Returns:
            Dict with summary statistics

        Example:
            >>> bridge = FeatureBridge()
            >>> detections = bridge.load_detections('data/input/ai/synthetic_paired_detections.csv')
            >>> summary = bridge.get_detection_summary(detections)
            >>> print(f"Total: {summary['total_detections']}")
            >>> print(f"CRITICAL: {summary['severity_counts']['CRITICAL']}")
        """
        if not detections:
            return {}

        # Basic counts
        total = len(detections)
        unique_users = len({d.user_id for d in detections})

        # Severity distribution
        severity_counts = {"CRITICAL": 0, "HIGH": 0, "MEDIUM": 0, "LOW": 0}
        for detection in detections:
            severity_counts[detection.severity] += 1

        # Entity counts
        all_apps = set()
        all_devices = set()
        all_browsers = set()
        all_os = set()

        for detection in detections:
            all_apps.update(detection.entities.get("apps", []))
            all_devices.update(detection.entities.get("devices", []))
            all_browsers.update(detection.entities.get("browsers", []))
            all_os.update(detection.entities.get("os", []))

        # Score statistics
        scores = [d.anomaly_score for d in detections]
        avg_score = sum(scores) / len(scores)
        min_score = min(scores)
        max_score = max(scores)

        # Feature richness
        avg_features = sum(len(d.parsed_features) for d in detections) / len(detections)

        return {
            "total_detections": total,
            "unique_users": unique_users,
            "severity_counts": severity_counts,
            "entity_counts": {
                "apps": len(all_apps),
                "devices": len(all_devices),
                "browsers": len(all_browsers),
                "os": len(all_os),
            },
            "score_stats": {"avg": avg_score, "min": min_score, "max": max_score},
            "avg_features_per_detection": avg_features,
            "date_range": {
                "start": detections[0].timestamp,
                "end": detections[-1].timestamp,
            },
        }


# Convenience function
def load_detections(csv_path: str | Path, limit: int | None = None) -> list[DetectionRecord]:
    """
    Convenience function to load detections without creating FeatureBridge instance.

    Args:
        csv_path: Path to FilterDetections CSV
        limit: Optional limit on detections

    Returns:
        List of DetectionRecord objects
    """
    bridge = FeatureBridge()
    return bridge.load_detections(csv_path, limit=limit)


if __name__ == "__main__":
    # Test with production dataset
    import sys

    logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

    if len(sys.argv) > 1:
        csv_path = sys.argv[1]
    else:
        csv_path = "data/input/ai/user_aware_anomalies.csv"

    print("=" * 80)
    print("FEATURE BRIDGE TEST")
    print("=" * 80)

    try:
        # Load detections
        bridge = FeatureBridge()
        detections = bridge.load_detections(csv_path, limit=10)

        # Display first detection
        print("\nFirst Detection:")
        first = detections[0]
        print(f"  User: {first.user_id}")
        print(f"  Timestamp: {first.timestamp}")
        print(f"  Severity: {first.severity} (score: {first.anomaly_score:.2f})")
        print(f"  Features ({len(first.parsed_features)}):")
        for feat in first.parsed_features[:5]:
            print(f"    - {feat.name}={feat.value} (z={feat.z_score:.2f}, category={feat.category})")
        print("  Entities:")
        for entity_type, entities in first.entities.items():
            if entities:
                print(f"    - {entity_type}: {', '.join(entities[:3])}")

        # Summary
        print("\nDataset Summary:")
        summary = bridge.get_detection_summary(detections)
        print(f"  Total detections: {summary['total_detections']}")
        print(f"  Unique users: {summary['unique_users']}")
        print("  Severity breakdown:")
        for severity, count in summary["severity_counts"].items():
            if count > 0:
                pct = count / summary["total_detections"] * 100
                print(f"    - {severity}: {count} ({pct:.1f}%)")
        print("  Entity counts:")
        for entity_type, count in summary["entity_counts"].items():
            print(f"    - {entity_type}: {count}")
        print(f"  Avg features/detection: {summary['avg_features_per_detection']:.1f}")

        print("\nFeature bridge test passed")

    except Exception as e:
        print(f"\nError: {e}")
        import traceback

        traceback.print_exc()
        sys.exit(1)
