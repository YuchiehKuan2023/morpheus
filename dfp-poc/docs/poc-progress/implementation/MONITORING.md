# Monitoring & Observability Guide

This guide explains how to set up and use the monitoring and alerting infrastructure for the DFP PoC.

## Table of Contents

1. [Overview](#overview)
2. [Metrics Collection](#metrics-collection)
3. [Alert Management](#alert-management)
4. [Grafana Dashboard](#grafana-dashboard)
5. [Logging](#logging)
6. [Setup Instructions](#setup-instructions)
7. [Troubleshooting](#troubleshooting)

---

## Overview

The DFP PoC includes comprehensive monitoring capabilities:

- **Prometheus Metrics**: Track pipeline performance, model health, and system resources
- **Alerting System**: Multi-channel notifications (log, file, email, Slack, PagerDuty)
- **Grafana Dashboard**: Real-time visualization of metrics
- **Structured Logging**: JSON logs for aggregation and analysis

### Architecture

```text
┌─────────────────────────────────────────────────────────────┐
│                      DFP Pipelines                          │
│                                                             │
│  ┌──────────────────┐         ┌──────────────────┐          │
│  │  Training        │         │  Inference       │          │
│  │  (batch job)     │         │  (long-running)  │          │
│  └────────┬─────────┘         └────────┬─────────┘          │
│           │                            │                    │
│           │ push on exit               │ serve real-time    │
│           ▼                            ▼                    │
│  ┌──────────────────┐         ┌──────────────────┐          │
│  │  Pushgateway     │         │  HTTP Server     │          │
│  │  (port 9091)     │         │  (port 8000)     │          │
│  │  Persists        │         │  In-process      │          │
│  └────────┬─────────┘         └────────┬─────────┘          │
└───────────┼──────────────────────────── ┼───────────────────┘
            │                             │
            │ scrape                      │ scrape
            ▼                             ▼
       ┌────────────────────────────────────┐
       │       Prometheus Server            │
       │       (port 9090)                  │
       │  - Scrapes 3 targets every 10s     │
       │  - Stores TSDB                     │
       │  - Evaluates alert rules           │
       └────────┬──────────────┬────────────┘
                │              │
                │ query        │ alerts
                ▼              ▼
       ┌───────────────┐  ┌─────────────────┐
       │    Grafana    │  │  AlertManager   │
       │  (port 3000)  │  │  (in-process)   │
       │  Dashboards   │  └────────┬────────┘
       └───────────────┘           │
                                   │ notifications
                                   ▼
                       ┌────────────────────────────────┐
                       │  Log │ File │ Email │ Slack    │
                       └────────────────────────────────┘
```

**Key Architecture Decisions**:

- **Training (batch)**: Pushes metrics to Pushgateway before exit → metrics persist
- **Inference (continuous)**: Serves metrics via HTTP server → real-time scraping
- **Pushgateway**: Solves the ephemeral batch job problem
- **Prometheus**: Single source of truth, scrapes from both endpoints

---

## Metrics Collection

### Available Metrics

#### Pipeline Metrics

| Metric                          | Type      | Description                       |
| ------------------------------- | --------- | --------------------------------- |
| `dfp_batches_processed_total`   | Counter   | Total batches processed           |
| `dfp_events_processed_total`    | Counter   | Total events processed            |
| `dfp_anomalies_detected_total`  | Counter   | Total anomalies detected          |
| `dfp_models_trained_total`      | Counter   | Total models trained              |
| `dfp_models_loaded_total`       | Counter   | Total models loaded               |
| `dfp_errors_total`              | Counter   | Total errors by type              |
| `dfp_active_users`              | Gauge     | Current active users              |
| `dfp_active_models`             | Gauge     | Current active models             |
| `dfp_throughput`                | Gauge     | Current throughput (events/sec)   |
| `dfp_detection_rate`            | Gauge     | Current anomaly detection rate    |
| `dfp_operation_latency_seconds` | Histogram | Operation latency distribution    |
| `dfp_z_score`                   | Summary   | Z-score distribution              |
| `dfp_reconstruction_error`      | Summary   | Reconstruction error distribution |

#### System Metrics

| Metric                           | Type  | Description                    |
| -------------------------------- | ----- | ------------------------------ |
| `system_cpu_percent`             | Gauge | CPU usage percentage           |
| `system_memory_used_bytes`       | Gauge | Memory used in bytes           |
| `system_memory_percent`          | Gauge | Memory usage percentage        |
| `system_disk_used_bytes`         | Gauge | Disk used in bytes             |
| `system_disk_percent`            | Gauge | Disk usage percentage          |
| `system_gpu_utilization_percent` | Gauge | GPU utilization (if available) |
| `system_gpu_memory_used_bytes`   | Gauge | GPU memory used (if available) |
| `system_gpu_temperature_celsius` | Gauge | GPU temperature (if available) |

### Using MetricsCollector

```python
from modules.utils.metrics_utils import get_metrics_collector

# Get the global collector
collector = get_metrics_collector()

# Increment counters
collector.increment_counter("dfp_events_processed_total",
                          labels={"pipeline": "training", "user_id": "user123"})

# Set gauges
collector.set_gauge("dfp_active_models", 5,
                   labels={"pipeline": "inference"})

# Observe histograms (for latency)
collector.observe_histogram("dfp_operation_latency_seconds", 0.125,
                           labels={"operation": "preprocess"})

# Observe summaries (for distributions)
collector.observe_summary("dfp_z_score", 2.5,
                         labels={"user_id": "user123", "model": "autoencoder_v1"})
```

### Using PipelineMetrics

```python
from modules.utils.metrics_utils import PipelineMetrics

# Create pipeline metrics tracker
metrics = PipelineMetrics(pipeline_name="training")

# Track batches and events
metrics.increment_batches(count=1, labels={"user_id": "user123"})
metrics.increment_events(count=100)

# Track anomalies
metrics.increment_anomalies(count=5)

# Track model operations
metrics.increment_models_trained()
metrics.increment_models_loaded()

# Track errors
metrics.increment_errors(error_type="preprocessing_error")

# Set gauges
metrics.set_active_users(50)
metrics.set_active_models(10)
metrics.set_throughput(1250.5)  # events/sec
metrics.set_detection_rate(0.05)  # 5% detection rate

# Time operations
with metrics.time_operation("training"):
    # ... training code ...
    pass

# Get summary
summary = metrics.get_summary()
metrics.log_summary()
```

### Using SystemMetrics

```python
from modules.utils.metrics_utils import SystemMetrics

# Collect and update system metrics
system_metrics = SystemMetrics()
system_metrics.collect_and_update()

# Access metrics
print(f"CPU: {system_metrics.cpu_percent}%")
print(f"Memory: {system_metrics.memory_percent}%")
print(f"Disk: {system_metrics.disk_percent}%")

if system_metrics.gpu_available:
    print(f"GPU: {system_metrics.gpu_utilization}%")
    print(f"GPU Memory: {system_metrics.gpu_memory_used / 1024**3:.2f} GB")
    print(f"GPU Temp: {system_metrics.gpu_temperature}°C")
```

### Exporting Metrics

#### Prometheus Text Format

```python
# Export to Prometheus format
prometheus_text = collector.export_prometheus()
print(prometheus_text)

# Export to file
from modules.utils.metrics_utils import export_metrics_to_file
export_metrics_to_file("metrics.txt", format="prometheus")
```

#### JSON Format

```python
# Export to JSON
import json
metrics_json = collector.export_json()
print(json.dumps(metrics_json, indent=2))

# Export to file
export_metrics_to_file("metrics.json", format="json")
```

#### HTTP Metrics Server (Inference - Long-Running)

```python
# Start HTTP server for Prometheus scraping
from modules.utils.metrics_utils import start_metrics_server

server = start_metrics_server(port=8000)
# Metrics available at http://localhost:8000/metrics
# Health check at http://localhost:8000/health

# Server runs as background thread in same process
# Metrics persist as long as the process runs
```

**Note**: The inference pipeline starts this automatically. You don't need to start it manually.

#### Pushgateway (Training - Batch Jobs)

```python
# Push metrics to Pushgateway before batch job exits
from modules.utils.metrics_utils import push_metrics_to_gateway

# Record metrics during training
collector = get_metrics_collector()
collector.increment_counter('dfp_batches_processed_total', value=3)
collector.increment_counter('dfp_events_processed_total', value=15000)
collector.set_gauge('dfp_throughput_events_per_second', value=250.5)

# Push to Pushgateway before exiting (metrics persist)
push_metrics_to_gateway(
    job="dfp_training",
    instance="batch_20241124_100500",
    gateway="localhost:9091"  # default
)
```

**Why Pushgateway?**

- Training is a batch job that exits after completion
- Without Pushgateway, metrics would disappear when process exits
- Pushgateway persists metrics so Prometheus can scrape them
- Inference doesn't need it (runs continuously)

**Test Pushgateway**:

```bash
# View persisted training metrics
curl http://localhost:9091/metrics | grep dfp_

# Metrics survive after training exits
# Prometheus scrapes them every 10 seconds
```

---

## Alert Management

### Alert Configuration

Alerts are configured in `config/alerting.yaml`:

```yaml
alerting:
  enabled: true
  evaluation_interval: 30 # seconds

  channels:
    log:
      enabled: true
      level: WARNING

    file:
      enabled: true
      path: logs/alerts.log

    email:
      enabled: false # Configure SMTP to enable
      smtp_host: smtp.gmail.com
      smtp_port: 587
      from_email: alerts@example.com
      to_emails:
        - admin@example.com

    slack:
      enabled: false # Set webhook URL to enable
      webhook_url: ${SLACK_WEBHOOK_URL}

    pagerduty:
      enabled: false
      integration_key: ${PAGERDUTY_KEY}

rules:
  - name: pipeline_errors_high
    description: Pipeline error rate is too high
    condition: "rate(dfp_errors_total[5m]) > 5"
    duration: 2m
    severity: CRITICAL
    labels:
      category: pipeline_health
    annotations:
      summary: High pipeline error rate detected
      description: Pipeline {{ $labels.pipeline }} has {{ $value }} errors/min
```

### Using AlertManager

```python
from modules.utils.alerting_utils import get_alert_manager

# Get the global alert manager
alert_mgr = get_alert_manager()

# Start alert evaluation
alert_mgr.start()

# ... run your pipeline ...

# Check active alerts
active = alert_mgr.get_active_alerts()
for alert in active:
    print(f"ALERT: {alert.name} - {alert.description}")
    print(f"  Severity: {alert.severity}")
    print(f"  Duration: {alert.duration}")

# Get alert history
history = alert_mgr.get_alert_history(hours=24)
print(f"Alerts in last 24h: {len(history)}")

# Stop alert evaluation
alert_mgr.stop()
```

### Alert Rules

The system includes 15+ predefined alert rules:

**Pipeline Health:**

- `pipeline_errors_high`: Error rate > 5 errors/min
- `pipeline_stopped`: No events processed for 5 minutes

**Performance:**

- `high_latency`: Operation latency > 5 seconds
- `low_throughput`: Throughput < 100 events/sec

**Model Health:**

- `model_loading_failures`: Models failing to load
- `high_reconstruction_error`: Reconstruction error > 0.5
- `anomaly_rate_spike`: Detection rate > 30%
- `anomaly_rate_drop`: Detection rate < 0.1%

**System Resources:**

- `high_memory_usage`: Memory > 90%
- `high_cpu_usage`: CPU > 90%
- `disk_space_low`: Disk > 85%
- `gpu_temperature_high`: GPU temp > 80°C

**MLflow:**

- `mlflow_connection_failed`: MLflow server unreachable

**Data Quality:**

- `no_data_received`: No data for 10 minutes
- `high_data_filtering_rate`: > 50% data filtered

### Alert Channels

#### Log Channel

Logs alerts using the standard logging system:

```python
from modules.utils.alerting_utils import LogAlertChannel, AlertSeverity

channel = LogAlertChannel(name="log", level=AlertSeverity.WARNING)
```

#### File Channel

Writes alerts to a file with timestamps:

```python
from modules.utils.alerting_utils import FileAlertChannel

channel = FileAlertChannel(name="file", filepath="logs/alerts.log")
```

#### Email Channel

Sends alerts via SMTP:

```python
from modules.utils.alerting_utils import EmailAlertChannel

channel = EmailAlertChannel(
    name="email",
    smtp_host="smtp.gmail.com",
    smtp_port=587,
    smtp_user="alerts@example.com",
    smtp_password="your_password",
    from_email="alerts@example.com",
    to_emails=["admin@example.com"]
)
```

#### Slack Channel

Sends alerts to Slack webhook:

```python
from modules.utils.alerting_utils import SlackAlertChannel

channel = SlackAlertChannel(
    name="slack",
    webhook_url="https://hooks.slack.com/services/YOUR/WEBHOOK/URL"
)
```

---

## Grafana Dashboard

### Dashboard Overview

The Grafana dashboard (`config/grafana_dashboard.json`) provides:

- **Pipeline Health**: Error rate, events processed, detection rate, active models
- **Throughput**: Real-time event processing rate
- **Anomaly Detection**: Anomaly counts and trends
- **Latency**: P95 operation latency by operation type
- **Model Performance**: Z-score distributions, reconstruction error
- **System Resources**: CPU, memory, disk usage
- **Training Activity**: Model training rate
- **Error Analysis**: Errors by type and pipeline
- **Top Anomalous Users**: Users with highest anomaly counts

### Importing the Dashboard

1. Open Grafana web interface
2. Click **+** → **Import**
3. Upload `config/grafana_dashboard.json`
4. Select your Prometheus data source
5. Click **Import**

### Dashboard Variables

The dashboard includes templating variables:

- **pipeline**: Filter by pipeline name (training, inference)
- **interval**: Adjust time aggregation (5m, 10m, 30m, 1h, etc.)

### Setting Up Alerts in Grafana

The dashboard includes pre-configured alerts:

- **High CPU Usage**: Triggers when CPU > 90%
- Additional alerts can be configured per panel

---

## Logging

### Structured Logging

All logs support JSON format for aggregation:

```python
from modules.utils.logging_utils import get_logger

logger = get_logger(__name__)

# Structured logging with extra fields
logger.info("Processing batch", extra={
    "batch_id": "batch_123",
    "user_id": "user_456",
    "event_count": 100,
    "duration_ms": 125.5
})
```

### Log Levels

- `TRACE` (5): Most detailed, for deep debugging
- `DEBUG` (10): Detailed information for debugging
- `VERBOSE` (15): More verbose than INFO
- `INFO` (20): General informational messages
- `NOTICE` (25): Important informational messages
- `SUCCESS` (25): Success messages
- `WARNING` (30): Warning messages
- `ERROR` (40): Error messages
- `CRITICAL` (50): Critical errors

### Log Files

Logs are written to multiple files based on configuration in `config/logging.yaml`:

- `logs/dfp_all.log`: All logs
- `logs/dfp_error.log`: Errors and critical logs only
- `logs/dfp_json.log`: JSON-formatted logs for aggregation
- `logs/dfp_training.log`: Training pipeline logs
- `logs/dfp_inference.log`: Inference pipeline logs
- `logs/dfp_performance.log`: Performance metrics logs

### Performance Logging

```python
from modules.utils.logging_utils import PerformanceLogger

perf_logger = PerformanceLogger(logger_name="performance")

with perf_logger.log_time("batch_processing"):
    # ... process batch ...
    pass

# Or use decorator
@perf_logger.log_performance("train_model")
def train_model():
    # ... training code ...
    pass
```

---

## Setup Instructions

### 1. Install Dependencies

```bash
pip install prometheus-client psutil python-json-logger requests
```

Optional for GPU monitoring:

```bash
pip install GPUtil
```

### 2. Configure Alerting

Edit `config/alerting.yaml`:

```yaml
alerting:
  enabled: true
  evaluation_interval: 30

  channels:
    # Enable log channel (always on)
    log:
      enabled: true
      level: WARNING

    # Configure email alerts
    email:
      enabled: true
      smtp_host: smtp.gmail.com
      smtp_port: 587
      smtp_user: ${SMTP_USER}
      smtp_password: ${SMTP_PASSWORD}
      from_email: dfp-alerts@example.com
      to_emails:
        - admin@example.com

    # Configure Slack alerts
    slack:
      enabled: true
      webhook_url: ${SLACK_WEBHOOK_URL}
```

Set environment variables:

```bash
export SMTP_USER="your_email@example.com"
export SMTP_PASSWORD="your_password"
export SLACK_WEBHOOK_URL="https://hooks.slack.com/services/YOUR/WEBHOOK/URL"
```

### 3. Start Monitoring Services

```bash
# Start all monitoring services (includes Pushgateway)
./services/start_monitoring.sh

# This starts:
# - Pushgateway (port 9091) - for batch job metrics
# - Prometheus (port 9090) - scrapes metrics
# - Grafana (port 3000, optional) - visualizes metrics

# Verify services
curl http://localhost:9091/metrics  # Pushgateway
curl http://localhost:9090/api/v1/targets  # Prometheus targets
```

**Note**: The metrics HTTP server (port 8000) is started automatically by the pipeline, not by this script.

### 4. Configure Prometheus (Already Done)

The project includes a pre-configured `config/prometheus.yml`:

```yaml
global:
  scrape_interval: 10s

scrape_configs:
  # Real-time inference metrics (long-running pipeline)
  - job_name: "dfp-pipeline"
    static_configs:
      - targets: ["localhost:8000"]

  # Persisted training metrics (batch jobs)
  - job_name: "pushgateway"
    honor_labels: true # Preserve job labels from pushed metrics
    static_configs:
      - targets: ["localhost:9091"]

  # Prometheus self-monitoring
  - job_name: "prometheus"
    static_configs:
      - targets: ["localhost:9090"]
```

Prometheus is started automatically by `start_monitoring.sh` with this config.

**Verify scraping**:

```bash
# Check all 3 targets are being scraped
curl http://localhost:9090/api/v1/targets | python3 -c "
import sys, json
data = json.load(sys.stdin)
targets = data['data']['activeTargets']
print(f'Total targets: {len(targets)}')
for t in targets:
    print(f\"  - {t['labels']['job']}: {t['scrapeUrl']} (health: {t['health']})\")
"
```

### 5. Set Up Grafana

1. Install Grafana: `brew install grafana`
2. Start Grafana: `brew services start grafana` (or via `start_monitoring.sh`)
3. Open <http://localhost:3000> (default login: admin/admin)
4. Add Prometheus data source:
   - Configuration → Data Sources → Add data source
   - Select Prometheus
   - URL: <http://localhost:9090>
   - Click "Save & Test"
5. Import dashboard:
   - Click **+** → **Import**
   - Upload `config/grafana_dashboard.json`
   - Select Prometheus data source
   - Click "Import"

**Dashboard includes**:

- Training metrics (batches processed, throughput) - from Pushgateway
- Inference metrics (events, anomalies, detection rate) - from real-time server
- System metrics (CPU, memory, GPU) - from both pipelines

### 6. Integrate into Pipelines

#### Training Pipeline (Batch Job)

```python
from modules.utils.metrics_utils import PipelineMetrics, push_metrics_to_gateway
from modules.utils.alerting_utils import get_alert_manager

# Initialize
metrics = PipelineMetrics(pipeline_name="training")
alert_mgr = get_alert_manager()
alert_mgr.start()

try:
    for batch in batches:
        with metrics.time_operation("preprocessing"):
            preprocessed = preprocess(batch)

        metrics.record_batch_processed(count=1)
        metrics.record_events_processed(count=len(batch))

        with metrics.time_operation("training"):
            model = train_model(preprocessed)

    # Calculate final metrics
    duration = time.time() - start_time
    throughput = total_events / duration
    metrics.record_throughput(events_per_second=throughput)

    # IMPORTANT: Push metrics before exiting (batch job)
    push_metrics_to_gateway(
        job="dfp_training",
        instance=f"batch_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    )

finally:
    alert_mgr.stop()
    metrics.log_summary()
```

**Key difference from inference**: Training calls `push_metrics_to_gateway()` before exit to persist metrics in Pushgateway.

#### Inference Pipeline

```python
from modules.utils.metrics_utils import PipelineMetrics

metrics = PipelineMetrics(pipeline_name="inference")

for event_batch in event_stream:
    with metrics.time_operation("inference"):
        scores = model.predict(event_batch)

    metrics.increment_events(count=len(event_batch))

    anomalies = scores[scores > threshold]
    metrics.increment_anomalies(count=len(anomalies))

    # Track detection rate
    detection_rate = len(anomalies) / len(event_batch)
    metrics.set_detection_rate(detection_rate)

    # Record z-scores
    for score in scores:
        metrics.observe_summary("z_score", score)
```

---

## Troubleshooting

### Metrics Not Appearing in Prometheus

1. **Check metrics server is running**:

   ```bash
   curl http://localhost:8000/metrics
   ```

2. **Verify Prometheus is scraping**:

   - Open Prometheus UI: <http://localhost:9090>
   - Status → Targets
   - Check if `dfp-pipeline` target is UP

3. **Check firewall**:

   ```bash
   sudo lsof -i :8000  # Verify port is open
   ```

### Alerts Not Firing

1. **Check alert manager is started**:

   ```python
   alert_mgr = get_alert_manager()
   if not alert_mgr.running:
       alert_mgr.start()
   ```

2. **Verify alert rules**:

   ```python
   for rule in alert_mgr.rules:
       print(f"Rule: {rule.name}, Enabled: {rule.enabled}")
   ```

3. **Check alert history**:

   ```python
   history = alert_mgr.get_alert_history(hours=1)
   for alert in history:
       print(f"{alert.name}: {alert.severity} - {alert.description}")
   ```

4. **Enable debug logging**:

   ```python
   import logging
   logging.getLogger("modules.utils.alerting_utils").setLevel(logging.DEBUG)
   ```

### Grafana Dashboard Shows No Data

1. **Check Prometheus data source**:

   - Grafana → Configuration → Data Sources
   - Click on Prometheus
   - Click "Test" button

2. **Verify metrics exist in Prometheus**:

   - Open Prometheus UI
   - Graph → Insert Metric → Search for `dfp_`

3. **Check time range**:
   - Ensure dashboard time range includes recent data
   - Try "Last 5 minutes"

### High Memory Usage

If metrics collection causes high memory:

1. **Reset metrics periodically**:

   ```python
   collector.reset_all()
   ```

2. **Limit label cardinality**:

   - Avoid high-cardinality labels (e.g., unique IDs)
   - Use label prefixes/buckets instead

3. **Reduce histogram/summary buckets**:
   - Edit `metrics_utils.py`
   - Reduce number of buckets in histograms

### Email Alerts Not Sending

1. **Check SMTP configuration**:

   ```bash
   echo $SMTP_USER
   echo $SMTP_PASSWORD
   ```

2. **Test SMTP connection**:

   ```python
   import smtplib

   server = smtplib.SMTP('smtp.gmail.com', 587)
   server.starttls()
   server.login('your_email@example.com', 'your_password')
   server.quit()
   print("SMTP connection successful")
   ```

3. **Enable app password** (for Gmail):
   - Google Account → Security → 2-Step Verification
   - App passwords → Generate password

### Slack Alerts Not Sending

1. **Verify webhook URL**:

   ```bash
   curl -X POST -H 'Content-type: application/json' \
     --data '{"text":"Test message"}' \
     $SLACK_WEBHOOK_URL
   ```

2. **Check webhook permissions**:
   - Slack workspace settings
   - Verify webhook has permissions to post

### GPU Metrics Not Available

If GPU metrics show as unavailable:

1. **Install GPUtil**:

   ```bash
   pip install GPUtil
   ```

2. **Verify GPU detection**:

   ```python
   import GPUtil
   gpus = GPUtil.getGPUs()
   print(f"Found {len(gpus)} GPUs")
   ```

3. **Check NVIDIA drivers**:

   ```bash
   nvidia-smi
   ```

---

## Best Practices

### Metrics Collection Details

1. **Label Cardinality**: Keep label values bounded (avoid unique IDs)
2. **Naming Convention**: Use `<namespace>_<metric>_<unit>` (e.g., `dfp_events_processed_total`)
3. **Reset Periodically**: Reset metrics between pipeline runs to avoid memory growth
4. **Sampling**: For high-frequency operations, consider sampling metrics

### Alerting Details

1. **Alert Fatigue**: Set appropriate thresholds to avoid too many alerts
2. **Inhibition Rules**: Use inhibition to suppress lower-severity alerts when critical alerts fire
3. **Routing**: Route critical alerts to PagerDuty, warnings to Slack, info to logs
4. **Runbooks**: Include links to troubleshooting docs in alert annotations

### Logging Details

1. **Structured Fields**: Use consistent field names across logs
2. **Correlation IDs**: Include batch_id, user_id for log correlation
3. **Log Levels**: Use appropriate log levels (don't log everything at INFO)
4. **Sampling**: Sample high-volume logs in production

### Dashboards Details

1. **Time Range**: Default to last 6 hours, allow customization
2. **Refresh Rate**: Set to 30s for real-time monitoring
3. **Annotations**: Add deployment markers for context
4. **Variables**: Use templating for flexible filtering

---

## References

- [Prometheus Documentation](https://prometheus.io/docs/)
- [Grafana Documentation](https://grafana.com/docs/)
- [Prometheus Python Client](https://github.com/prometheus/client_python)
- [Alert Configuration](../config/alerting.yaml)
- [Grafana Dashboard](../config/grafana_dashboard.json)
- [Architecture Documentation](ARCHITECTURE.md)
