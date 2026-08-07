#!/usr/bin/env python3
"""
AI Monitoring: Prometheus Metrics Collection

Provides metrics collection and monitoring for AI components.
Tracks performance, accuracy, cache efficiency, and errors across
all AI features (entity extraction, embeddings, clustering, etc.).

Metrics Categories:
    - Latency: Processing time for each AI component
    - Throughput: Detections processed per second
    - Cache: Hit/miss rates for embeddings, entities, etc.
    - Accuracy: Model performance metrics
    - Errors: Error counts by component and type

Integration:
    - Prometheus client library for metrics export
    - /metrics endpoint for Prometheus scraping
    - Decorators for easy instrumentation
    - Context managers for operation tracking

Usage:
    >>> from modules.ai.shared.monitoring import monitor_performance, timing
    >>>
    >>> @monitor_performance("entity_extraction")
    >>> def extract_entities(detection):
    ...     # Entity extraction logic
    ...     return entities
    >>>
    >>> # Or use context manager
    >>> with timing("vector_search"):
    ...     results = search_similar(embedding)

Reference:
    docs/implementation/PROGRESS_TRACKER.md (Week 4: Monitoring)
    config/prometheus.yml (Prometheus scraping config)

Author: AI Intelligence Layer Team
Date: 2026-02-19
"""

import functools
import logging
import time
from collections.abc import Callable
from contextlib import contextmanager
from typing import Any

from prometheus_client import Counter, Gauge, Histogram, Summary

logger = logging.getLogger(__name__)

# ==============================================================================
# Prometheus Metrics Definitions
# ==============================================================================

# Latency metrics (histograms for percentiles)
ai_operation_duration = Histogram(
    "ai_operation_duration_seconds",
    "Duration of AI operations in seconds",
    ["component", "operation"],
    buckets=(0.001, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0),
)

# Throughput metrics
ai_detections_processed = Counter(
    "ai_detections_processed_total", "Total detections processed by AI components", ["component", "status"]
)

ai_operations_total = Counter(
    "ai_operations_total", "Total AI operations executed", ["component", "operation", "status"]
)

# Cache metrics
ai_cache_operations = Counter(
    "ai_cache_operations_total", "Cache operations (hits/misses)", ["cache_type", "operation"]
)

ai_cache_hit_rate = Gauge("ai_cache_hit_rate", "Cache hit rate by type", ["cache_type"])

ai_cache_size = Gauge("ai_cache_size_bytes", "Current cache size in bytes", ["cache_type"])

# Model accuracy metrics (updated periodically)
ai_model_accuracy = Gauge("ai_model_accuracy", "Model accuracy score", ["model_name", "metric_type"])

ai_model_predictions = Counter(
    "ai_model_predictions_total", "Total model predictions", ["model_name", "prediction_class"]
)

# Feature enablement status
ai_feature_enabled = Gauge("ai_feature_enabled", "Whether AI feature is enabled (1=enabled, 0=disabled)", ["feature"])

ai_feature_enablement_count = Gauge("ai_feature_enablement_count", "Number of currently enabled AI features")

# Error metrics
ai_errors_total = Counter("ai_errors_total", "Total AI errors", ["component", "error_type"])

ai_error_rate = Gauge("ai_error_rate", "Error rate by component", ["component"])

# Resource metrics
ai_active_operations = Gauge("ai_active_operations", "Number of currently active operations", ["component"])

ai_queue_size = Gauge("ai_queue_size", "Size of processing queues", ["queue_name"])

# Data quality metrics
ai_data_quality_score = Gauge(
    "ai_data_quality_score", "Data quality score for AI inputs", ["component", "quality_dimension"]
)

ai_anomaly_score_distribution = Summary(
    "ai_anomaly_score_distribution",
    "Distribution of anomaly scores processed",
    ["severity"],
)

# Cold start metrics
ai_cold_start_anomaly_count = Gauge("ai_cold_start_anomaly_count", "Total anomalies detected (for cold start)")

ai_cold_start_labeled_count = Gauge("ai_cold_start_labeled_count", "Total labeled anomalies (for cold start)")

ai_cold_start_progress_pct = Gauge("ai_cold_start_progress_pct", "Cold start progress percentage")


# ==============================================================================
# Decorators and Context Managers
# ==============================================================================


def monitor_performance(component: str, operation: str | None = None) -> Callable:
    """
    Decorator to monitor performance of AI operations.

    Automatically tracks:
    - Execution duration
    - Success/failure status
    - Active operation count

    Args:
        component: Component name (e.g., 'entity_extraction', 'embeddings')
        operation: Optional operation name (defaults to function name)

    Returns:
        Decorated function

    Example:
        >>> @monitor_performance("entity_extraction")
        >>> def extract_entities(detection):
        ...     return entities
        >>>
        >>> @monitor_performance("embeddings", operation="generate")
        >>> def generate_embedding(text):
        ...     return embedding
    """

    def decorator(func: Callable) -> Callable:
        op_name = operation or func.__name__

        @functools.wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            # Increment active operations
            ai_active_operations.labels(component=component).inc()

            start_time = time.time()
            status = "success"
            error = None

            try:
                result = func(*args, **kwargs)
                return result

            except Exception as e:
                status = "error"
                error = type(e).__name__
                ai_errors_total.labels(component=component, error_type=error).inc()
                raise

            finally:
                # Record duration
                duration = time.time() - start_time
                ai_operation_duration.labels(component=component, operation=op_name).observe(duration)

                # Record operation count
                ai_operations_total.labels(component=component, operation=op_name, status=status).inc()

                # Decrement active operations
                ai_active_operations.labels(component=component).dec()

                # Log if slow
                if duration > 1.0:
                    logger.warning(
                        f"Slow AI operation: {component}.{op_name} took {duration:.2f}s "
                        f"(status={status}, error={error})"
                    )

        return wrapper

    return decorator


@contextmanager
def timing(component: str, operation: str | None = None):
    """
    Context manager for timing AI operations.

    Args:
        component: Component name
        operation: Operation name (optional)

    Yields:
        None

    Example:
        >>> with timing("vector_search", "similarity"):
        ...     results = search_similar(embedding)
    """
    op_name = operation or "operation"
    ai_active_operations.labels(component=component).inc()

    start_time = time.time()
    status = "success"

    try:
        yield

    except Exception as e:
        status = "error"
        error_type = type(e).__name__
        ai_errors_total.labels(component=component, error_type=error_type).inc()
        raise

    finally:
        duration = time.time() - start_time
        ai_operation_duration.labels(component=component, operation=op_name).observe(duration)
        ai_operations_total.labels(component=component, operation=op_name, status=status).inc()
        ai_active_operations.labels(component=component).dec()


# ==============================================================================
# Metric Update Functions
# ==============================================================================


def record_detection_processed(component: str, status: str = "success"):
    """
    Record a detection processed by an AI component.

    Args:
        component: Component name
        status: Processing status ('success', 'error', 'skipped')

    Example:
        >>> record_detection_processed("entity_extraction", "success")
    """
    ai_detections_processed.labels(component=component, status=status).inc()


def record_cache_operation(cache_type: str, hit: bool):
    """
    Record a cache operation (hit or miss).

    Args:
        cache_type: Type of cache ('embedding', 'entity', 'cluster')
        hit: Whether it was a cache hit

    Example:
        >>> record_cache_operation("embedding", hit=True)
        >>> record_cache_operation("entity", hit=False)
    """
    operation = "hit" if hit else "miss"
    ai_cache_operations.labels(cache_type=cache_type, operation=operation).inc()


def update_cache_hit_rate(cache_type: str, hit_rate: float):
    """
    Update cache hit rate metric.

    Args:
        cache_type: Type of cache
        hit_rate: Hit rate (0.0 to 1.0)

    Example:
        >>> update_cache_hit_rate("embedding", 0.85)
    """
    ai_cache_hit_rate.labels(cache_type=cache_type).set(hit_rate)


def update_cache_size(cache_type: str, size_bytes: int):
    """
    Update cache size metric.

    Args:
        cache_type: Type of cache
        size_bytes: Cache size in bytes

    Example:
        >>> update_cache_size("embedding", 1024 * 1024 * 50)  # 50 MB
    """
    ai_cache_size.labels(cache_type=cache_type).set(size_bytes)


def record_model_prediction(model_name: str, prediction_class: str):
    """
    Record a model prediction.

    Args:
        model_name: Name of the model
        prediction_class: Predicted class/category

    Example:
        >>> record_model_prediction("root_cause_classifier", "credential_theft")
    """
    ai_model_predictions.labels(model_name=model_name, prediction_class=prediction_class).inc()


def update_model_accuracy(model_name: str, metric_type: str, score: float):
    """
    Update model accuracy metric.

    Args:
        model_name: Name of the model
        metric_type: Type of metric ('accuracy', 'precision', 'recall', 'f1')
        score: Metric score (0.0 to 1.0)

    Example:
        >>> update_model_accuracy("root_cause_classifier", "f1", 0.87)
    """
    ai_model_accuracy.labels(model_name=model_name, metric_type=metric_type).set(score)


def update_feature_enabled(feature: str, enabled: bool):
    """
    Update feature enablement status.

    Args:
        feature: Feature name
        enabled: Whether feature is enabled

    Example:
        >>> update_feature_enabled("entity_extraction", True)
        >>> update_feature_enabled("vector_search", False)
    """
    ai_feature_enabled.labels(feature=feature).set(1 if enabled else 0)


def update_feature_count(count: int):
    """
    Update total enabled feature count.

    Args:
        count: Number of enabled features

    Example:
        >>> update_feature_count(5)
    """
    ai_feature_enablement_count.set(count)


def record_anomaly_score(score: float, severity: str):
    """
    Record an anomaly score for distribution tracking.

    Args:
        score: Anomaly score
        severity: Severity level ('CRITICAL', 'HIGH', 'MEDIUM', 'LOW')

    Example:
        >>> record_anomaly_score(5.3, "CRITICAL")
    """
    ai_anomaly_score_distribution.labels(severity=severity).observe(score)


def update_cold_start_metrics(total_anomalies: int, labeled_anomalies: int, progress_pct: float):
    """
    Update cold start progress metrics.

    Args:
        total_anomalies: Total anomaly count
        labeled_anomalies: Labeled anomaly count
        progress_pct: Progress percentage (0-100)

    Example:
        >>> update_cold_start_metrics(total=150, labeled=75, progress_pct=15.0)
    """
    ai_cold_start_anomaly_count.set(total_anomalies)
    ai_cold_start_labeled_count.set(labeled_anomalies)
    ai_cold_start_progress_pct.set(progress_pct)


def update_queue_size(queue_name: str, size: int):
    """
    Update processing queue size.

    Args:
        queue_name: Name of the queue
        size: Current queue size

    Example:
        >>> update_queue_size("enrichment_requests", 42)
    """
    ai_queue_size.labels(queue_name=queue_name).set(size)


def update_data_quality(component: str, dimension: str, score: float):
    """
    Update data quality score.

    Args:
        component: Component name
        dimension: Quality dimension ('completeness', 'accuracy', 'consistency')
        score: Quality score (0.0 to 1.0)

    Example:
        >>> update_data_quality("entity_extraction", "completeness", 0.95)
    """
    ai_data_quality_score.labels(component=component, quality_dimension=dimension).set(score)


# ==============================================================================
# Helper Functions
# ==============================================================================


def calculate_error_rate(component: str, error_count: int, total_count: int):
    """
    Calculate and update error rate for a component.

    Args:
        component: Component name
        error_count: Number of errors
        total_count: Total operations

    Example:
        >>> calculate_error_rate("entity_extraction", error_count=5, total_count=1000)
    """
    if total_count > 0:
        error_rate = error_count / total_count
        ai_error_rate.labels(component=component).set(error_rate)
    else:
        ai_error_rate.labels(component=component).set(0.0)


def get_metrics_summary() -> dict[str, Any]:
    """
    Get summary of current metrics (for debugging/testing).

    Returns:
        Dict with metric summaries

    Example:
        >>> summary = get_metrics_summary()
        >>> print(summary["total_collectors"])
    """
    from prometheus_client import REGISTRY

    metrics = {}
    collector_count = 0

    for collector in REGISTRY._collector_to_names:
        collector_count += 1
        # Use getattr to safely access _name without type issues
        name = getattr(collector, "_name", f"collector_{collector_count}")
        metrics[name] = collector

    metrics["_summary"] = {"total_collectors": collector_count, "collector_names": list(metrics.keys())}

    return metrics


# ==============================================================================
# Initialization
# ==============================================================================


def initialize_metrics():
    """
    Initialize all metrics with default values.

    Call this on application startup to ensure all metrics exist
    in Prometheus even if not yet recorded.
    """
    logger.info("Initializing AI monitoring metrics")

    # Initialize common components
    components = ["entity_extraction", "embeddings", "vector_search", "clustering", "root_cause", "risk_scoring"]

    for component in components:
        ai_active_operations.labels(component=component).set(0)
        ai_error_rate.labels(component=component).set(0.0)

    # Initialize cache types
    cache_types = ["embedding", "entity", "cluster"]
    for cache_type in cache_types:
        ai_cache_hit_rate.labels(cache_type=cache_type).set(0.0)
        ai_cache_size.labels(cache_type=cache_type).set(0)

    # Initialize cold start metrics
    update_cold_start_metrics(total_anomalies=0, labeled_anomalies=0, progress_pct=0.0)

    logger.info("AI monitoring metrics initialized")


if __name__ == "__main__":
    # Test monitoring module
    import sys

    logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

    print("=" * 80)
    print("AI MONITORING TEST")
    print("=" * 80)

    try:
        # Initialize metrics
        initialize_metrics()
        print("\nMetrics initialized")

        # Test decorator
        @monitor_performance("test_component")
        def test_operation(duration: float):
            time.sleep(duration)
            return f"Completed in {duration}s"

        print("\nTesting decorator...")
        result = test_operation(0.1)
        print(f"   Result: {result}")

        # Test context manager
        print("\nTesting context manager...")
        with timing("test_component", "context_test"):
            time.sleep(0.05)
        print("   Context test completed")

        # Test metric recording
        print("\nRecording test metrics...")
        record_detection_processed("entity_extraction", "success")
        record_cache_operation("embedding", hit=True)
        update_cache_hit_rate("embedding", 0.85)
        update_model_accuracy("test_model", "f1", 0.92)
        update_feature_enabled("entity_extraction", True)
        update_cold_start_metrics(100, 50, 10.0)
        print("   Metrics recorded")

        # Get summary
        print("\nMetrics summary:")
        summary = get_metrics_summary()
        print(f"   Total metrics defined: {len(summary)}")

        print("\n" + "=" * 80)
        print("AI monitoring test passed")
        print("=" * 80)
        print("\nIn production, metrics are exposed at /metrics endpoint for Prometheus")

    except Exception as e:
        print(f"\nError: {e}")
        import traceback

        traceback.print_exc()
        sys.exit(1)
