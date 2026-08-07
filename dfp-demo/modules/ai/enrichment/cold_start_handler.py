#!/usr/bin/env python3
"""
Cold Start Handler: Progressive AI Feature Enablement

Manages progressive enablement of AI capabilities based on available anomaly data.
Prevents premature use of ML models that require training data, and enables
features gracefully as more anomalies are detected.

Architecture:
    Day 1 (0 anomalies):     Entity extraction, rule-based explanations
    10+ anomalies:           Vector search, similarity detection
    50+ anomalies:           Clustering, pattern detection
    100+ anomalies:          Root cause analysis, risk scoring
    500+ anomalies:          Time series forecasting, capacity planning

Usage:
    >>> handler = ColdStartHandler()
    >>> status = handler.get_feature_status()
    >>> if status['entity_extraction']['enabled']:
    ...     # Extract entities
    >>> if status['vector_search']['enabled']:
    ...     # Search for similar anomalies

Reference:
    docs/implementation/PROGRESS_TRACKER.md (Week 4-5: Cold Start Integration)
    docs/architecture/AI_ARCHITECTURE.md (Progressive Enablement Strategy)

Author: AI Intelligence Layer Team
Date: 2026-02-19
"""

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any

import redis

logger = logging.getLogger(__name__)


class FeatureCategory(Enum):
    """AI feature categories with progressive enablement."""

    # Day 1 features (no data required)
    ENTITY_EXTRACTION = "entity_extraction"
    RULE_BASED_EXPLANATION = "rule_based_explanation"
    KNOWLEDGE_GRAPH = "knowledge_graph"

    # 10+ anomalies required
    VECTOR_SEARCH = "vector_search"
    SIMILARITY_DETECTION = "similarity_detection"
    EMBEDDINGS = "embeddings"

    # 50+ anomalies required
    CLUSTERING = "clustering"
    PATTERN_DETECTION = "pattern_detection"
    CLUSTER_MONITORING = "cluster_monitoring"

    # 100+ anomalies required (labeled data)
    ROOT_CAUSE_ANALYSIS = "root_cause_analysis"
    RISK_SCORING = "risk_scoring"
    CLASSIFICATION = "classification"

    # 500+ anomalies required
    TIME_SERIES_FORECASTING = "time_series_forecasting"
    CAPACITY_PLANNING = "capacity_planning"
    ANOMALY_RATE_PREDICTION = "anomaly_rate_prediction"

    # Advanced features (Phase D)
    MULTI_AGENT_SYSTEM = "multi_agent_system"
    FORENSICS_AGENT = "forensics_agent"
    REMEDIATION_AGENT = "remediation_agent"
    EXPLAINABILITY = "explainability"


@dataclass
class FeatureConfig:
    """
    Configuration for a single AI feature.

    Attributes:
        name: Feature name (enum value)
        display_name: Human-readable name
        description: Feature description
        min_anomalies: Minimum anomalies required to enable
        min_labeled: Minimum labeled anomalies (for supervised learning)
        enabled: Whether feature is currently enabled
        enabled_at: Timestamp when feature was enabled
        dependencies: List of required features (must be enabled first)
    """

    name: str
    display_name: str
    description: str
    min_anomalies: int
    min_labeled: int = 0
    enabled: bool = False
    enabled_at: str | None = None
    dependencies: list[str] = field(default_factory=list)

    def can_enable(self, anomaly_count: int, labeled_count: int, enabled_features: set[str]) -> bool:
        """
        Check if feature can be enabled given current state.

        Args:
            anomaly_count: Total anomalies detected
            labeled_count: Total labeled anomalies
            enabled_features: Set of currently enabled feature names

        Returns:
            True if feature can be enabled
        """
        # Check anomaly count threshold
        if anomaly_count < self.min_anomalies:
            return False

        # Check labeled count threshold (for supervised features)
        if labeled_count < self.min_labeled:
            return False

        # Check dependencies
        for dep in self.dependencies:
            if dep not in enabled_features:
                return False

        return True


class ColdStartHandler:
    """
    Manages progressive enablement of AI features based on available data.

    Tracks anomaly counts and automatically enables features when thresholds are met.
    Provides API for checking feature availability and current status.

    Methods:
        get_feature_status(): Get current status of all features
        update_anomaly_count(total, labeled): Update counts and check for new enablements
        is_feature_enabled(feature): Check if specific feature is enabled
        get_enabled_features(): Get list of currently enabled features
    """

    # Default feature configurations
    DEFAULT_FEATURES = [
        # Day 1 features (0 anomalies)
        FeatureConfig(
            name=FeatureCategory.ENTITY_EXTRACTION.value,
            display_name="Entity Extraction",
            description="Extract users, apps, devices, locations from anomaly features",
            min_anomalies=0,
        ),
        FeatureConfig(
            name=FeatureCategory.RULE_BASED_EXPLANATION.value,
            display_name="Rule-Based Explanations",
            description="Generate human-readable explanations using rules",
            min_anomalies=0,
        ),
        FeatureConfig(
            name=FeatureCategory.KNOWLEDGE_GRAPH.value,
            display_name="Knowledge Graph",
            description="Build graph of users, apps, devices, and relationships",
            min_anomalies=0,
            dependencies=[FeatureCategory.ENTITY_EXTRACTION.value],
        ),
        # 10+ anomalies
        FeatureConfig(
            name=FeatureCategory.EMBEDDINGS.value,
            display_name="Embedding Generation",
            description="Generate vector embeddings for anomaly features",
            min_anomalies=10,
        ),
        FeatureConfig(
            name=FeatureCategory.VECTOR_SEARCH.value,
            display_name="Vector Search",
            description="Search for similar anomalies using embeddings",
            min_anomalies=10,
            dependencies=[FeatureCategory.EMBEDDINGS.value],
        ),
        FeatureConfig(
            name=FeatureCategory.SIMILARITY_DETECTION.value,
            display_name="Similarity Detection",
            description="Find similar historical anomalies",
            min_anomalies=10,
            dependencies=[FeatureCategory.VECTOR_SEARCH.value],
        ),
        # 50+ anomalies
        FeatureConfig(
            name=FeatureCategory.CLUSTERING.value,
            display_name="Anomaly Clustering",
            description="Group similar anomalies into clusters",
            min_anomalies=50,
            dependencies=[FeatureCategory.EMBEDDINGS.value],
        ),
        FeatureConfig(
            name=FeatureCategory.PATTERN_DETECTION.value,
            display_name="Pattern Detection",
            description="Detect recurring patterns and trends",
            min_anomalies=50,
            dependencies=[FeatureCategory.CLUSTERING.value],
        ),
        FeatureConfig(
            name=FeatureCategory.CLUSTER_MONITORING.value,
            display_name="Cluster Monitoring",
            description="Monitor for new anomaly patterns",
            min_anomalies=50,
            dependencies=[FeatureCategory.CLUSTERING.value],
        ),
        # 100+ labeled anomalies
        FeatureConfig(
            name=FeatureCategory.ROOT_CAUSE_ANALYSIS.value,
            display_name="Root Cause Analysis",
            description="Identify likely root causes using ML classifier",
            min_anomalies=100,
            min_labeled=100,
        ),
        FeatureConfig(
            name=FeatureCategory.RISK_SCORING.value,
            display_name="Risk Scoring",
            description="Calculate risk scores using XGBoost + SHAP",
            min_anomalies=100,
            min_labeled=100,
        ),
        FeatureConfig(
            name=FeatureCategory.CLASSIFICATION.value,
            display_name="Anomaly Classification",
            description="Classify anomaly types automatically",
            min_anomalies=100,
            min_labeled=100,
        ),
        # 500+ anomalies
        FeatureConfig(
            name=FeatureCategory.TIME_SERIES_FORECASTING.value,
            display_name="Time Series Forecasting",
            description="Forecast future anomaly rates using Prophet",
            min_anomalies=500,
        ),
        FeatureConfig(
            name=FeatureCategory.CAPACITY_PLANNING.value,
            display_name="Capacity Planning",
            description="Predict capacity needs based on trends",
            min_anomalies=500,
            dependencies=[FeatureCategory.TIME_SERIES_FORECASTING.value],
        ),
        FeatureConfig(
            name=FeatureCategory.ANOMALY_RATE_PREDICTION.value,
            display_name="Anomaly Rate Prediction",
            description="Predict anomaly rates for next 7/30 days",
            min_anomalies=500,
            dependencies=[FeatureCategory.TIME_SERIES_FORECASTING.value],
        ),
        # Advanced features (Phase D - manual enablement)
        FeatureConfig(
            name=FeatureCategory.MULTI_AGENT_SYSTEM.value,
            display_name="Multi-Agent System",
            description="Orchestrate multiple AI agents for investigation",
            min_anomalies=1000,
            dependencies=[
                FeatureCategory.ROOT_CAUSE_ANALYSIS.value,
                FeatureCategory.RISK_SCORING.value,
            ],
        ),
        FeatureConfig(
            name=FeatureCategory.FORENSICS_AGENT.value,
            display_name="Forensics Agent",
            description="Reconstruct attack timelines and sequences",
            min_anomalies=1000,
            dependencies=[FeatureCategory.MULTI_AGENT_SYSTEM.value],
        ),
        FeatureConfig(
            name=FeatureCategory.REMEDIATION_AGENT.value,
            display_name="Remediation Agent",
            description="Recommend remediation actions",
            min_anomalies=1000,
            dependencies=[FeatureCategory.MULTI_AGENT_SYSTEM.value],
        ),
        FeatureConfig(
            name=FeatureCategory.EXPLAINABILITY.value,
            display_name="Explainability (LIME/SHAP)",
            description="Explain ML model predictions",
            min_anomalies=1000,
            dependencies=[
                FeatureCategory.ROOT_CAUSE_ANALYSIS.value,
                FeatureCategory.RISK_SCORING.value,
            ],
        ),
    ]

    def __init__(self, redis_host: str = "localhost", redis_port: int = 6379, redis_db: int = 0):
        """
        Initialize ColdStartHandler.

        Args:
            redis_host: Redis host
            redis_port: Redis port
            redis_db: Redis database number
        """
        self.redis_client = redis.Redis(host=redis_host, port=redis_port, db=redis_db, decode_responses=True)
        self.features: dict[str, FeatureConfig] = {f.name: f for f in self.DEFAULT_FEATURES}

        # Load state from Redis
        self._load_state()

        logger.info("Initialized ColdStartHandler")

    def _load_state(self):
        """Load feature state from Redis."""
        try:
            # Load anomaly counts
            anomaly_count = int(self.redis_client.get("ai:cold_start:anomaly_count") or "0")  # type: ignore
            labeled_count = int(self.redis_client.get("ai:cold_start:labeled_count") or "0")  # type: ignore

            # Load enabled features
            enabled_features_json = self.redis_client.get("ai:cold_start:enabled_features")
            if enabled_features_json:
                enabled_data = json.loads(enabled_features_json)  # type: ignore
                for feature_name, data in enabled_data.items():
                    if feature_name in self.features:
                        self.features[feature_name].enabled = data.get("enabled", False)
                        self.features[feature_name].enabled_at = data.get("enabled_at")

            logger.info(
                f"Loaded state: {anomaly_count} anomalies, {labeled_count} labeled, "
                f"{sum(1 for f in self.features.values() if f.enabled)} features enabled"
            )

        except Exception as e:
            logger.warning(f"Could not load state from Redis: {e}. Starting fresh.")

    def _save_state(self):
        """Save feature state to Redis."""
        try:
            # Save anomaly counts
            anomaly_count = int(self.redis_client.get("ai:cold_start:anomaly_count") or "0")  # type: ignore
            labeled_count = int(self.redis_client.get("ai:cold_start:labeled_count") or "0")  # type: ignore

            # Save enabled features
            enabled_data = {
                name: {"enabled": feature.enabled, "enabled_at": feature.enabled_at}
                for name, feature in self.features.items()
                if feature.enabled
            }
            self.redis_client.set("ai:cold_start:enabled_features", json.dumps(enabled_data))

            logger.debug(f"Saved state: {anomaly_count} anomalies, {labeled_count} labeled")

        except Exception as e:
            logger.error(f"Could not save state to Redis: {e}")

    def update_anomaly_count(self, total: int, labeled: int = 0) -> list[str]:
        """
        Update anomaly counts and check for new feature enablements.

        Args:
            total: Total number of anomalies detected
            labeled: Number of labeled anomalies (for supervised learning)

        Returns:
            List of newly enabled feature names

        Example:
            >>> handler = ColdStartHandler()
            >>> newly_enabled = handler.update_anomaly_count(total=50, labeled=0)
            >>> if newly_enabled:
            ...     print(f"New features enabled: {newly_enabled}")
        """
        # Update counts in Redis
        self.redis_client.set("ai:cold_start:anomaly_count", total)
        self.redis_client.set("ai:cold_start:labeled_count", labeled)

        # Check for new enablements
        newly_enabled = []
        enabled_feature_names = {name for name, f in self.features.items() if f.enabled}

        for feature_name, feature in self.features.items():
            if not feature.enabled and feature.can_enable(total, labeled, enabled_feature_names):
                # Enable feature
                feature.enabled = True
                feature.enabled_at = datetime.now(timezone.utc).isoformat()
                newly_enabled.append(feature_name)
                enabled_feature_names.add(feature_name)

                logger.info(
                    f"Enabled feature: {feature.display_name} "
                    f"(total={total}, labeled={labeled}, threshold={feature.min_anomalies})"
                )

        # Save state if changes occurred
        if newly_enabled:
            self._save_state()

        return newly_enabled

    def is_feature_enabled(self, feature: FeatureCategory | str) -> bool:
        """
        Check if specific feature is enabled.

        Args:
            feature: Feature category (enum or string)

        Returns:
            True if feature is enabled

        Example:
            >>> handler = ColdStartHandler()
            >>> if handler.is_feature_enabled(FeatureCategory.ENTITY_EXTRACTION):
            ...     # Use entity extraction
        """
        feature_name = feature.value if isinstance(feature, FeatureCategory) else feature
        return self.features.get(
            feature_name, FeatureConfig(name="", display_name="", description="", min_anomalies=999999)
        ).enabled

    def get_enabled_features(self) -> list[str]:
        """
        Get list of currently enabled feature names.

        Returns:
            List of enabled feature names

        Example:
            >>> handler = ColdStartHandler()
            >>> enabled = handler.get_enabled_features()
            >>> print(f"Enabled features: {', '.join(enabled)}")
        """
        return [name for name, feature in self.features.items() if feature.enabled]

    def get_feature_status(self) -> dict[str, Any]:
        """
        Get comprehensive status of all features.

        Returns:
            Dict with feature status, counts, and metadata

        Example:
            >>> handler = ColdStartHandler()
            >>> status = handler.get_feature_status()
            >>> print(f"Total anomalies: {status['counts']['total']}")
            >>> print(f"Enabled features: {status['counts']['enabled_features']}")
            >>> for feature_name, feature_data in status['features'].items():
            ...     print(f"{feature_data['display_name']}: {feature_data['enabled']}")
        """
        # Get counts from Redis
        anomaly_count = int(self.redis_client.get("ai:cold_start:anomaly_count") or "0")  # type: ignore
        labeled_count = int(self.redis_client.get("ai:cold_start:labeled_count") or "0")  # type: ignore

        # Build feature status map
        features_status = {}
        enabled_feature_names = {name for name, f in self.features.items() if f.enabled}

        for name, feature in self.features.items():
            can_enable = feature.can_enable(anomaly_count, labeled_count, enabled_feature_names)

            features_status[name] = {
                "name": name,
                "display_name": feature.display_name,
                "description": feature.description,
                "enabled": feature.enabled,
                "enabled_at": feature.enabled_at,
                "can_enable": can_enable,
                "min_anomalies": feature.min_anomalies,
                "min_labeled": feature.min_labeled,
                "dependencies": feature.dependencies,
                "dependencies_met": all(dep in enabled_feature_names for dep in feature.dependencies),
            }

        # Calculate next milestone
        next_milestone = None
        for threshold in [10, 50, 100, 500, 1000]:
            if anomaly_count < threshold:
                next_milestone = threshold
                break

        return {
            "counts": {
                "total": anomaly_count,
                "labeled": labeled_count,
                "enabled_features": sum(1 for f in self.features.values() if f.enabled),
                "total_features": len(self.features),
            },
            "next_milestone": next_milestone,
            "progress_pct": min(100, (anomaly_count / 1000) * 100) if anomaly_count else 0,
            "features": features_status,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }


# Convenience functions
def get_handler() -> ColdStartHandler:
    """Get singleton ColdStartHandler instance."""
    global _handler_instance
    if "_handler_instance" not in globals():
        _handler_instance = ColdStartHandler()
    return _handler_instance


def is_feature_enabled(feature: FeatureCategory | str) -> bool:
    """Check if feature is enabled (convenience function)."""
    return get_handler().is_feature_enabled(feature)


if __name__ == "__main__":
    # Test cold start handler
    import sys

    logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

    print("=" * 80)
    print("COLD START HANDLER TEST")
    print("=" * 80)

    try:
        handler = ColdStartHandler()

        # Simulate progressive enablement
        test_scenarios = [
            (0, 0, "Day 1 - No anomalies"),
            (10, 0, "Day N - 10 anomalies detected"),
            (50, 0, "Week N - 50 anomalies detected"),
            (100, 100, "Month 1 - 100 labeled anomalies"),
            (500, 250, "Month 3 - 500 anomalies, 250 labeled"),
            (1000, 500, "Month 6 - 1000 anomalies, 500 labeled"),
        ]

        for total, labeled, description in test_scenarios:
            print(f"\n{'=' * 80}")
            print(f"Scenario: {description}")
            print(f"{'=' * 80}")

            newly_enabled = handler.update_anomaly_count(total=total, labeled=labeled)

            if newly_enabled:
                print(f"Newly enabled features ({len(newly_enabled)}):")
                for feature_name in newly_enabled:
                    feature = handler.features[feature_name]
                    print(f"   - {feature.display_name}")

            status = handler.get_feature_status()
            print("\nStatus:")
            print(f"  Total anomalies: {status['counts']['total']}")
            print(f"  Labeled anomalies: {status['counts']['labeled']}")
            print(f"  Enabled features: {status['counts']['enabled_features']}/{status['counts']['total_features']}")
            print(f"  Progress: {status['progress_pct']:.1f}%")
            if status["next_milestone"]:
                print(f"  Next milestone: {status['next_milestone']} anomalies")

            print("\nEnabled features:")
            for feature_name in handler.get_enabled_features():
                feature = handler.features[feature_name]
                print(f"   ✓ {feature.display_name}")

        print("\n" + "=" * 80)
        print("Cold start handler test passed")
        print("=" * 80)

    except Exception as e:
        print(f"\nError: {e}")
        import traceback

        traceback.print_exc()
        sys.exit(1)
