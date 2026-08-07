"""
Metrics collection and export utilities for DFP PoC.

This module provides Prometheus-compatible metrics collection for monitoring
pipeline performance, model health, and system resource usage.

Features:
    - Prometheus metrics export
    - Pipeline performance metrics
    - Anomaly detection metrics
    - Model performance tracking
    - System resource monitoring
    - Custom metric types (Counter, Gauge, Histogram, Summary)
"""

import logging
import time
from collections import defaultdict
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from threading import Lock
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class MetricValue:
    """Container for a metric value with timestamp and labels."""

    value: int | float
    timestamp: float = field(default_factory=time.time)
    labels: dict[str, str] = field(default_factory=dict)


class MetricsCollector:
    """
    Centralized metrics collector for DFP pipeline.

    Collects and exports metrics in Prometheus text format.

    Example:
        >>> collector = MetricsCollector()
        >>> collector.increment_counter('events_processed', labels={'pipeline': 'training'})
        >>> collector.set_gauge('active_models', 10)
        >>> collector.observe_histogram('inference_latency', 0.025)
        >>> metrics = collector.export_prometheus()
    """

    def __init__(self):
        """Initialize metrics collector."""
        self._counters: dict[str, MetricValue] = {}
        self._gauges: dict[str, MetricValue] = {}
        self._histograms: dict[str, list[float]] = defaultdict(list)
        self._summaries: dict[str, list[float]] = defaultdict(list)
        self._lock = Lock()
        self._start_time = time.time()

    def increment_counter(self, name: str, value: int | float = 1, labels: dict[str, str] | None = None):
        """
        Increment a counter metric.

        Args:
            name: Metric name
            value: Increment value (default: 1)
            labels: Optional metric labels
        """
        with self._lock:
            key = self._make_key(name, labels)
            if key in self._counters:
                self._counters[key].value += value
                self._counters[key].timestamp = time.time()
            else:
                self._counters[key] = MetricValue(value=value, labels=labels or {})

    def set_gauge(self, name: str, value: int | float, labels: dict[str, str] | None = None):
        """
        Set a gauge metric.

        Args:
            name: Metric name
            value: Metric value
            labels: Optional metric labels
        """
        with self._lock:
            key = self._make_key(name, labels)
            self._gauges[key] = MetricValue(value=value, labels=labels or {})

    def observe_histogram(self, name: str, value: float, labels: dict[str, str] | None = None):
        """
        Observe a value for a histogram metric.

        Args:
            name: Metric name
            value: Observed value
            labels: Optional metric labels
        """
        with self._lock:
            key = self._make_key(name, labels)
            self._histograms[key].append(value)

    def observe_summary(self, name: str, value: float, labels: dict[str, str] | None = None):
        """
        Observe a value for a summary metric.

        Args:
            name: Metric name
            value: Observed value
            labels: Optional metric labels
        """
        with self._lock:
            key = self._make_key(name, labels)
            self._summaries[key].append(value)

    def reset_metric(self, name: str):
        """Reset all values for a metric."""
        with self._lock:
            # Remove from all metric types
            prefix = f"{name}{{"
            self._counters = {k: v for k, v in self._counters.items() if not k.startswith(prefix) and k != name}
            self._gauges = {k: v for k, v in self._gauges.items() if not k.startswith(prefix) and k != name}
            self._histograms = {k: v for k, v in self._histograms.items() if not k.startswith(prefix) and k != name}
            self._summaries = {k: v for k, v in self._summaries.items() if not k.startswith(prefix) and k != name}

    def reset_all(self):
        """Reset all metrics."""
        with self._lock:
            self._counters.clear()
            self._gauges.clear()
            self._histograms.clear()
            self._summaries.clear()

    def get_counter(self, name: str, labels: dict[str, str] | None = None) -> float:
        """Get current counter value."""
        key = self._make_key(name, labels)
        return self._counters.get(key, MetricValue(0)).value

    def get_gauge(self, name: str, labels: dict[str, str] | None = None) -> float:
        """Get current gauge value."""
        key = self._make_key(name, labels)
        return self._gauges.get(key, MetricValue(0)).value

    def export_prometheus(self, include_timestamp: bool = True) -> str:
        """
        Export metrics in Prometheus text format.

        Args:
            include_timestamp: Whether to include timestamps (False for Pushgateway)

        Returns:
            Prometheus-formatted metrics string
        """
        lines = []

        with self._lock:
            # Export counters
            for key, metric in self._counters.items():
                name, labels_str = self._parse_key(key)
                lines.append(f"# TYPE {name} counter")
                if include_timestamp:
                    lines.append(f"{name}{labels_str} {metric.value} {int(metric.timestamp * 1000)}")
                else:
                    lines.append(f"{name}{labels_str} {metric.value}")

            # Export gauges
            for key, metric in self._gauges.items():
                name, labels_str = self._parse_key(key)
                lines.append(f"# TYPE {name} gauge")
                if include_timestamp:
                    lines.append(f"{name}{labels_str} {metric.value} {int(metric.timestamp * 1000)}")
                else:
                    lines.append(f"{name}{labels_str} {metric.value}")

            # Export histograms
            for key, values in self._histograms.items():
                if not values:
                    continue

                name, labels_str = self._parse_key(key)
                lines.append(f"# TYPE {name} histogram")

                # Calculate histogram buckets
                buckets = [0.001, 0.01, 0.1, 0.5, 1.0, 5.0, 10.0, float("inf")]
                bucket_counts = [sum(1 for v in values if v <= b) for b in buckets]

                for bucket, count in zip(buckets, bucket_counts, strict=True):
                    bucket_str = "+Inf" if bucket == float("inf") else str(bucket)
                    lines.append(
                        f'{name}_bucket{{le="{bucket_str}"{labels_str[1:-1] if labels_str != "{}" else ""} {count}'
                    )

                lines.append(f"{name}_sum{labels_str} {sum(values)}")
                lines.append(f"{name}_count{labels_str} {len(values)}")

            # Export summaries
            for key, values in self._summaries.items():
                if not values:
                    continue

                name, labels_str = self._parse_key(key)
                lines.append(f"# TYPE {name} summary")

                # Calculate quantiles
                sorted_values = sorted(values)
                n = len(sorted_values)
                quantiles = [0.5, 0.9, 0.95, 0.99]

                for q in quantiles:
                    idx = int(n * q)
                    value = sorted_values[min(idx, n - 1)]
                    lines.append(f'{name}{{quantile="{q}"{labels_str[1:-1] if labels_str != "{}" else ""} {value}')

                lines.append(f"{name}_sum{labels_str} {sum(values)}")
                lines.append(f"{name}_count{labels_str} {len(values)}")

        return "\n".join(lines)

    def export_json(self) -> dict[str, Any]:
        """
        Export metrics as JSON.

        Returns:
            Dictionary of all metrics
        """
        with self._lock:
            return {
                "counters": {k: v.value for k, v in self._counters.items()},
                "gauges": {k: v.value for k, v in self._gauges.items()},
                "histograms": {
                    k: {
                        "count": len(vals),
                        "sum": sum(vals),
                        "min": min(vals) if vals else 0,
                        "max": max(vals) if vals else 0,
                        "mean": sum(vals) / len(vals) if vals else 0,
                    }
                    for k, vals in self._histograms.items()
                },
                "summaries": {
                    k: {
                        "count": len(vals),
                        "sum": sum(vals),
                        "min": min(vals) if vals else 0,
                        "max": max(vals) if vals else 0,
                        "mean": sum(vals) / len(vals) if vals else 0,
                    }
                    for k, vals in self._summaries.items()
                },
                "uptime_seconds": time.time() - self._start_time,
            }

    def _make_key(self, name: str, labels: dict[str, str] | None) -> str:
        """Create a unique key for a metric with labels."""
        if not labels:
            return name

        labels_str = ",".join(f"{k}={v}" for k, v in sorted(labels.items()))
        return f"{name}{{{labels_str}}}"

    def _parse_key(self, key: str) -> tuple:
        """Parse metric key into name and labels string."""
        if "{" not in key:
            return key, "{}"

        name, labels = key.split("{", 1)
        return name, "{" + labels


class PipelineMetrics:
    """
    Pipeline-specific metrics collector.

    Tracks metrics for training and inference pipelines.

    Example:
        >>> metrics = PipelineMetrics('training')
        >>> with metrics.time_operation('data_loading'):
        ...     load_data()
        >>> metrics.record_batch_processed(100)
        >>> metrics.log_summary()
    """

    def __init__(self, pipeline_name: str, collector: MetricsCollector | None = None):
        """
        Initialize pipeline metrics.

        Args:
            pipeline_name: Name of the pipeline (training, inference)
            collector: Optional shared metrics collector (defaults to global singleton)
        """
        self.pipeline_name = pipeline_name
        self.collector = collector or get_metrics_collector()
        self.labels = {"pipeline": pipeline_name}
        self._operation_times: dict[str, list[float]] = defaultdict(list)

    def record_batch_processed(self, count: int = 1):
        """Record a batch processed."""
        self.collector.increment_counter("dfp_batches_processed_total", value=count, labels=self.labels)

    def record_events_processed(self, count: int):
        """Record number of events processed."""
        self.collector.increment_counter("dfp_events_processed_total", value=count, labels=self.labels)

    def record_anomalies_detected(self, count: int):
        """Record number of anomalies detected."""
        self.collector.increment_counter("dfp_anomalies_detected_total", value=count, labels=self.labels)

    def record_models_trained(self, count: int = 1):
        """Record number of models trained."""
        self.collector.increment_counter("dfp_models_trained_total", value=count, labels=self.labels)

    def record_models_loaded(self, count: int = 1):
        """Record number of models loaded."""
        self.collector.increment_counter("dfp_models_loaded_total", value=count, labels=self.labels)

    def record_errors(self, count: int = 1):
        """Record pipeline errors."""
        self.collector.increment_counter("dfp_errors_total", value=count, labels=self.labels)

    def set_active_users(self, count: int):
        """Set number of active users."""
        self.collector.set_gauge("dfp_active_users", value=count, labels=self.labels)

    def set_active_models(self, count: int):
        """Set number of active models."""
        self.collector.set_gauge("dfp_active_models", value=count, labels=self.labels)

    def record_latency(self, latency_seconds: float, operation: str = "total"):
        """Record operation latency."""
        labels = {**self.labels, "operation": operation}
        self.collector.observe_histogram("dfp_operation_latency_seconds", value=latency_seconds, labels=labels)
        self._operation_times[operation].append(latency_seconds)

    def record_throughput(self, events_per_second: float):
        """Record throughput."""
        self.collector.set_gauge("dfp_throughput_events_per_second", value=events_per_second, labels=self.labels)

    def record_detection_rate(self, rate: float):
        """Record anomaly detection rate (0-1)."""
        self.collector.set_gauge("dfp_detection_rate", value=rate, labels=self.labels)

    def record_model_loss(self, loss: float, model_name: str):
        """Record model training/validation loss."""
        labels = {**self.labels, "model": model_name}
        self.collector.observe_summary("dfp_model_loss", value=loss, labels=labels)

    def record_reconstruction_error(self, error: float, model_name: str):
        """Record reconstruction error."""
        labels = {**self.labels, "model": model_name}
        self.collector.observe_summary("dfp_reconstruction_error", value=error, labels=labels)

    def record_z_score(self, z_score: float):
        """Record z-score for anomaly detection."""
        self.collector.observe_histogram("dfp_z_score", value=z_score, labels=self.labels)

    @contextmanager
    def time_operation(self, operation: str):
        """
        Context manager to time an operation.

        Args:
            operation: Name of the operation

        Example:
            >>> with metrics.time_operation('model_loading'):
            ...     load_model()
        """
        start_time = time.time()
        try:
            yield
        finally:
            elapsed = time.time() - start_time
            self.record_latency(elapsed, operation)

    def get_summary(self) -> dict[str, Any]:
        """Get summary of collected metrics."""
        summary = {
            "pipeline": self.pipeline_name,
            "batches_processed": self.collector.get_counter("dfp_batches_processed_total", self.labels),
            "events_processed": self.collector.get_counter("dfp_events_processed_total", self.labels),
            "anomalies_detected": self.collector.get_counter("dfp_anomalies_detected_total", self.labels),
            "models_trained": self.collector.get_counter("dfp_models_trained_total", self.labels),
            "models_loaded": self.collector.get_counter("dfp_models_loaded_total", self.labels),
            "errors": self.collector.get_counter("dfp_errors_total", self.labels),
            "active_users": self.collector.get_gauge("dfp_active_users", self.labels),
            "active_models": self.collector.get_gauge("dfp_active_models", self.labels),
        }

        # Add operation timing statistics
        for operation, times in self._operation_times.items():
            if times:
                summary[f"{operation}_avg_time"] = sum(times) / len(times)
                summary[f"{operation}_total_time"] = sum(times)
                summary[f"{operation}_count"] = len(times)

        return summary

    def log_summary(self, logger: logging.Logger | None = None):
        """Log metrics summary."""
        log = logger or logging.getLogger(__name__)
        summary = self.get_summary()

        log.info(f"Pipeline Metrics Summary ({self.pipeline_name}):")
        for key, value in summary.items():
            if isinstance(value, float):
                log.info(f"  {key}: {value:.4f}")
            else:
                log.info(f"  {key}: {value}")


class SystemMetrics:
    """
    System resource metrics collector.

    Tracks CPU, memory, GPU usage, and disk I/O.

    Example:
        >>> system_metrics = SystemMetrics()
        >>> system_metrics.collect()
        >>> metrics = system_metrics.get_metrics()
    """

    def __init__(self, collector: MetricsCollector | None = None):
        """
        Initialize system metrics.

        Args:
            collector: Optional shared metrics collector (defaults to global singleton)
        """
        self.collector = collector or get_metrics_collector()

        # Try to import resource monitoring libraries
        try:
            import psutil

            self.psutil = psutil
        except ImportError:
            self.psutil = None
            logger.warning("psutil not available, system metrics will be limited")

        try:
            import GPUtil

            self.gputil = GPUtil
        except ImportError:
            self.gputil = None
            logger.debug("GPUtil not available, GPU metrics disabled")

    def collect(self):
        """Collect current system metrics."""
        if self.psutil:
            # CPU metrics
            cpu_percent = self.psutil.cpu_percent(interval=0.1)
            self.collector.set_gauge("system_cpu_percent", cpu_percent)

            # Memory metrics
            memory = self.psutil.virtual_memory()
            self.collector.set_gauge("system_memory_used_bytes", memory.used)
            self.collector.set_gauge("system_memory_available_bytes", memory.available)
            self.collector.set_gauge("system_memory_percent", memory.percent)

            # Disk metrics
            disk = self.psutil.disk_usage("/")
            self.collector.set_gauge("system_disk_used_bytes", disk.used)
            self.collector.set_gauge("system_disk_free_bytes", disk.free)
            self.collector.set_gauge("system_disk_percent", disk.percent)

        if self.gputil:
            # GPU metrics
            try:
                gpus = self.gputil.getGPUs()
                for i, gpu in enumerate(gpus):
                    labels = {"gpu": str(i)}
                    self.collector.set_gauge("system_gpu_utilization", gpu.load * 100, labels)
                    self.collector.set_gauge("system_gpu_memory_used_mb", gpu.memoryUsed, labels)
                    self.collector.set_gauge("system_gpu_memory_total_mb", gpu.memoryTotal, labels)
                    self.collector.set_gauge("system_gpu_temperature_celsius", gpu.temperature, labels)
            except Exception as e:
                logger.debug(f"Failed to collect GPU metrics: {e}")

    def get_metrics(self) -> dict[str, Any]:
        """Get current system metrics as dictionary."""
        metrics = {}

        if self.psutil:
            metrics["cpu_percent"] = self.collector.get_gauge("system_cpu_percent")
            metrics["memory_used_bytes"] = self.collector.get_gauge("system_memory_used_bytes")
            metrics["memory_percent"] = self.collector.get_gauge("system_memory_percent")
            metrics["disk_percent"] = self.collector.get_gauge("system_disk_percent")

        return metrics


# Global metrics collector instance
_global_collector: MetricsCollector | None = None


def get_metrics_collector() -> MetricsCollector:
    """Get or create global metrics collector."""
    global _global_collector
    if _global_collector is None:
        _global_collector = MetricsCollector()
    return _global_collector


def export_metrics_to_file(filepath: str, format: str = "prometheus"):
    """
    Export metrics to file.

    Args:
        filepath: Output file path
        format: Export format ('prometheus' or 'json')
    """
    collector = get_metrics_collector()

    if format == "prometheus":
        content = collector.export_prometheus()
    elif format == "json":
        import json

        content = json.dumps(collector.export_json(), indent=2)
    else:
        raise ValueError(f"Unknown format: {format}")

    Path(filepath).parent.mkdir(parents=True, exist_ok=True)
    with open(filepath, "w") as f:
        f.write(content)

    logger.info(f"Metrics exported to {filepath} ({format} format)")


def start_metrics_server(port: int = 8000):
    """
    Start HTTP server to expose Prometheus metrics.

    Args:
        port: Server port

    Example:
        >>> start_metrics_server(8000)
        # Metrics available at http://localhost:8000/metrics
    """
    import threading
    from http.server import BaseHTTPRequestHandler, HTTPServer

    class MetricsHandler(BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path == "/metrics":
                collector = get_metrics_collector()
                content = collector.export_prometheus()

                self.send_response(200)
                self.send_header("Content-Type", "text/plain; version=0.0.4")
                self.end_headers()
                self.wfile.write(content.encode("utf-8"))
            elif self.path == "/health":
                import json

                health_data = {"status": "healthy", "timestamp": str(datetime.now())}
                content = json.dumps(health_data)

                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(content.encode("utf-8"))
            else:
                self.send_response(404)
                self.end_headers()

        def log_message(self, format, *args):
            # Suppress request logs
            pass

    # Try to start server, handle port conflicts
    max_attempts = 5
    current_port = port

    for _attempt in range(max_attempts):
        try:
            server = HTTPServer(("0.0.0.0", current_port), MetricsHandler)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            logger.info(f"Metrics server started on http://0.0.0.0:{current_port}/metrics")
            return server
        except OSError as e:
            if e.errno == 48:  # Address already in use
                logger.warning(f"Port {current_port} already in use, trying {current_port + 1}")
                current_port += 1
            else:
                raise

    logger.error(f"Could not start metrics server after {max_attempts} attempts")
    return None


def push_metrics_to_gateway(job: str, instance: str | None = None, gateway: str = "localhost:9091"):
    """
    Push metrics to Prometheus Pushgateway for batch job persistence.

    Use this at the end of batch jobs (like training) to persist metrics
    after the process exits.

    Args:
        job: Job name (e.g., "dfp_training", "dfp_preprocessing")
        instance: Optional instance identifier (default: hostname)
        gateway: Pushgateway address (default: "localhost:9091")

    Example:
        >>> # At end of training
        >>> push_metrics_to_gateway(job="dfp_training", instance="batch_001")
    """
    import socket

    import requests

    if instance is None:
        instance = socket.gethostname()

    collector = get_metrics_collector()
    # Pushgateway doesn't accept timestamps in metrics
    metrics_data = collector.export_prometheus(include_timestamp=False)

    if not metrics_data.strip():
        logger.warning(f"No metrics to push for job={job}")
        return

    # Pushgateway URL format: /metrics/job/<JOB_NAME>/instance/<INSTANCE>
    url = f"http://{gateway}/metrics/job/{job}/instance/{instance}"

    # Ensure metrics data ends with newline (Pushgateway requirement)
    if not metrics_data.endswith("\n"):
        metrics_data += "\n"

    try:
        response = requests.post(
            url,
            data=metrics_data.encode("utf-8"),
            headers={"Content-Type": "text/plain; version=0.0.4; charset=utf-8"},
            timeout=5,
        )
        response.raise_for_status()

        metric_count = len([line for line in metrics_data.split("\n") if line and not line.startswith("#")])
        logger.info(f"✓ Pushed {metric_count} metrics to Pushgateway (job={job}, instance={instance})")

    except requests.exceptions.RequestException as e:
        logger.warning(f"Failed to push metrics to Pushgateway: {e}")
        logger.info("Metrics will not persist after process exit")
