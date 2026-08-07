# NVIDIA Morpheus Digital Fingerprinting - Proof of Concept

[![CI](https://github.com/Deloitte-UK-Innersource/morpheus-dfp/actions/workflows/ci.yml/badge.svg)](https://github.com/Deloitte-UK-Innersource/morpheus-dfp/actions/workflows/ci.yml)
[![Security](https://github.com/Deloitte-UK-Innersource/morpheus-dfp/actions/workflows/security.yml/badge.svg)](https://github.com/Deloitte-UK-Innersource/morpheus-dfp/actions/workflows/security.yml)
[![License](https://img.shields.io/badge/License-Apache%202.0-blue.svg)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.10%20%7C%203.11%20%7C%203.12-blue)](https://www.python.org)
[![Code style: black](https://img.shields.io/badge/code%20style-black-000000.svg)](https://github.com/psf/black)
[![Ruff](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json)](https://github.com/astral-sh/ruff)

A production-ready implementation of NVIDIA Morpheus Digital Fingerprinting (DFP) for user behavior anomaly detection using unsupervised AutoEncoder models.

## Table of Contents

- [Overview](#overview)
- [Architecture](#architecture)
- [Features](#features)
- [Quick Start](#quick-start)
- [Installation](#installation)
- [Usage](#usage)
- [Configuration](#configuration)
- [Project Structure](#project-structure)
- [Development](#development)
- [Testing](#testing)
- [References](#references)

## Overview

This Proof of Concept (PoC) implements NVIDIA's Digital Fingerprinting platform for detecting anomalous user behavior in Azure AD authentication logs. The system uses per-user AutoEncoder models to learn normal behavioral patterns and detect deviations that may indicate security threats.

**Key Capabilities:**

- **DFP behavioral learning with geographic features**:
  - Per-user AutoEncoder models trained on behavioral patterns
  - Geographic features (travel_speed_kmph) included in behavioral learning
  - Models learn normal travel patterns per user (typically 0-100 km/h)
- **FilterDetections**: NVIDIA standard binary filtering (threshold=2.0, mean_abs_z)
- Per-user anomaly detection using AutoEncoder neural networks
- Geographic feature engineering for travel pattern analysis
- Real-time and batch processing modes
- Integrated training and inference pipelines
- MLflow model registry integration
- Kafka streaming support
- Cross-platform support (CPU and GPU with automatic fallback)

**Target Environments:**

- Development: M3 MacBook Pro (CPU)
- Production: NVIDIA GPU systems (CUDA)

## Architecture

### Modular Pipeline Architecture

This implementation follows **NVIDIA Morpheus DFP modular architecture** using separate training and inference pipelines:

```text
┌─────────────────────────────────────────────────────────────┐
│                    Training Pipeline                        │
│              (training_pipeline.py)                         │
├─────────────────────────────────────────────────────────────┤
│ File Data → DFP_PREPROC (Geographic Features)               │
│          → Rolling Window (60d)                             │
│          → Data Prep → DFP Trainer (with travel_speed_kmph) │
│          → MLflow Writer                                    │
└─────────────────────────────────────────────────────────────┘
                              ↓
                      [MLflow Registry]
                              ↓
┌─────────────────────────────────────────────────────────────┐
│                   Inference Pipeline                        │
│              (inference_pipeline.py)                        │
├─────────────────────────────────────────────────────────────┤
│ Kafka Stream → DFP_PREPROC (Geographic Features)            │
│          → Rolling Window (1d)                              │
│          → DFP Inference (Behavioral + Geographic)          │
│          → Filter Detections (Binary Filtering)             │
│          → Kafka Output                                     │
└─────────────────────────────────────────────────────────────┘
```

### Training Pipeline Flow

**Module Chain** (following NVIDIA `dfp_training_pipe.py`):

```text
FileToDataFrame
    ↓ [Raw Azure AD logs]
UserSplitter
    ↓ [Per-user data streams]
RollingWindow (cache_mode="aggregate", max_history="60d")
    ↓ [Aggregated time windows]
DFPPreprocessing (Geographic feature engineering)
    ↓ [Feature-engineered data: behavioral + travel_speed_kmph]
DataPrep
    ↓ [Model-ready features including travel_speed_kmph]
DFPTrainer (AutoEncoder training with geographic features)
    ↓ [Trained AutoEncoder models learn behavioral + geographic patterns]
MLflowModelWriter
    ↓ [Models saved to registry: DFP-{username}, DFP-generic]
```

**Key Characteristics**:

- Batch processing from files
- Aggregate mode preserves cache and `last_train_count`
- 60-day training window
- Per-user model training with generic fallback
- Models versioned in MLflow

### Inference Pipeline Flow

**Module Chain** (following NVIDIA `dfp_inference_pipe.py` with FFT Layer 3):

```text
KafkaConsumer (poll_interval="10millis")
    ↓ [Real-time event stream]
UserSplitter
    ↓ [Per-user data streams]
RollingWindow (cache_mode="batch", max_history="1d")
    ↓ [Time windows with cached baseline]
DFPPreprocessing (Geographic Features)
    ↓ [Feature-engineered data + travel_speed_kmph]
DataPrep
    ↓ [Model-ready features]
DFPInference (Behavioral + Geographic Anomalies)
    ↓ [Anomaly scores, z-scores for all features]
FilterDetections (Binary Filtering: mean_abs_z > 2.0)
    ↓ [Filtered detections with comprehensive feature details]
KafkaProducer
    ↓ [Detections published to Kafka]
```

**Key Characteristics**:

- Real-time Kafka streaming with 10ms poll interval (NVIDIA default)
- DFP behavioral anomaly detection:
  - AutoEncoder models trained on behavioral + geographic features
  - travel_speed_kmph included in behavioral learning
  - Per-user models learn normal travel patterns (0-100 km/h typical)
- FilterDetections binary filtering (mean_abs_z > 2.0)
- 1-day inference window with cached baseline
- Batch mode reads `last_train_count` from cache (read-only)
- Generic model fallback for users without specific models
- Comprehensive detection messages with all feature details and z-scores

## Features

### Core Functionality

- **DFP Behavioral Learning**: AutoEncoder-based anomaly detection
  - Per-user models trained on behavioral + geographic features
  - travel_speed_kmph included in training (models learn normal travel patterns)
  - Z-score based anomaly detection across all features
- **FilterDetections**: NVIDIA standard binary filtering
  - Threshold: mean_abs_z > 2.0 (configurable)
  - Returns None if no anomalies exceed threshold
  - Comprehensive detection messages with feature details
- **Per-User Models**: Separate AutoEncoder model trained for each user
- **Generic Fallback**: Generic model for users with insufficient training data
- **Incremental Training**: Models update incrementally as new data arrives
- **Rolling Windows**: Time-based aggregation (24-hour windows by default)
- **Behavioral Features**: Extracted from Azure AD logs (login patterns, locations, devices)
- **Geographic Feature Engineering**: Calculates haversine distance, time delta, and travel velocity between consecutive user events
- **AutoEncoder Learning**: Includes travel_speed_kmph feature in training, learns normal travel patterns per user (typically 0-100 km/h)
- **Binary Filtering**: FilterDetections module provides post-inference filtering
  - Threshold: mean_abs_z > 2.0 (configurable)
  - Field: mean_abs_z (average of absolute z-scores across all features)
  - Returns None if no anomalies exceed threshold
- **Comprehensive Detection Messages**: Detailed feature information
  - features: Array of all features with {feature, z_score, value}
  - top_features: Top 3 features in "feature=value (z=score)" format
  - Timestamp, anomaly_score, max_abs_z, feature_count
- **Anomaly Scoring**: Z-score based detection with configurable thresholds

### Processing Modes

1. **Training Mode**: Batch training from files using `training_pipeline.py`

   - Processes historical data
   - Trains per-user AutoEncoder models
   - Saves models to MLflow registry
   - Populates rolling window cache

2. **Inference Mode**: Real-time streaming using `inference_pipeline.py`

   - Consumes events from Kafka
   - Loads models from MLflow
   - Computes anomaly scores (z-scores)
   - Publishes detections to Kafka

3. **Modular Architecture**: Separate pipelines with shared cache
   - Training and inference run independently
   - Cache directory shared for feature continuity
   - Models versioned and tracked in MLflow

### Technical Features

- NVIDIA Morpheus DFP architecture alignment
- Geographic feature engineering module (haversine distance, time delta, travel velocity)
- AutoEncoder behavioral learning includes travel_speed_kmph feature
- FilterDetections binary filtering (NVIDIA standard module)
- Comprehensive detection messages with all feature details
- MLflow model versioning and registry
- Control message based routing
- Cached rolling window aggregation with geographic features
- Cross-platform device support (CPU/CUDA/MPS)
- GPU acceleration with automatic CPU fallback (CuPy/NumPy)
- Comprehensive logging and monitoring
- Extensible configuration system (OmegaConf)

### Monitoring & Observability

- **Prometheus Metrics**: Real-time pipeline metrics exposed at `/metrics` endpoint
- **Alert Manager**: 15 predefined alert rules with multi-channel notifications (log, email, Slack, PagerDuty)
- **Grafana Dashboards**: 15-panel dashboard for visualization
- **System Metrics**: CPU, memory, disk, and GPU monitoring
- **Pipeline Metrics**: Events processed, anomalies detected, models loaded, latency, throughput
- **Automated Alerting**: High error rates, low throughput, memory/CPU pressure, anomaly rate spikes

## Quick Start

### Prerequisites

**Required:**

- Python 3.10 or 3.11
- Homebrew (macOS) for service management
- tmux for terminal multiplexing
- Apache Kafka (auto-installed via `brew install kafka`)
- MLflow (auto-installed via `pip install mlflow`)

**Optional:**

- NVIDIA GPU with CUDA for accelerated training
- Prometheus for metrics collection (`brew install prometheus`)
- Grafana for dashboards (`brew install grafana`)

### 1. Start All Services

```bash
cd dfp-poc
./services/start_services.sh
```

This starts:

- **MLflow** (port 5001) - Model registry and experiment tracking
- **Kafka** (port 29092, KRaft mode) - Streaming data pipeline
- **Kafka UI** (port 8080, optional) - Web-based Kafka monitoring
- **API Documentation** (port 8888) - Sphinx documentation server
- **Metrics Server** (port 8000) - Prometheus metrics endpoint
- **DFP Inference Pipeline** - Ready for streaming inference
- **Prometheus** (port 9090, if installed) - Metrics collection
- **Grafana** (port 3000, if installed) - Dashboard visualization

All services run in a tmux session named `dfp-services`.

### 2. Generate Synthetic Data

```bash
python scripts/utils/generate_azure_ad_data.py \
  --output data/input/train/azure_ad_train.jsonl \
  --num-events 150000 \
  --num-users 50 \
  --duration-days 70 \
  --start-time "2025-08-11T00:00:00+00:00" \
  --min-events-per-user 300 \
  --events-per-user variable \
  --user-seed 42 \
  --event-seed 42 \
  --anomaly-rate 0.0
```

### 3. Run Training Pipeline

```bash
python pipelines/pipeline.py training \
    --config config/pipeline.yaml \
    --train-msg control_messages/train.json \
    --log-level INFO
```

**This will**:

- Load training data from paths specified in `train.json`
- Train per-user AutoEncoder models
- Save models to MLflow (port 5001)
- Populate rolling window cache for inference

### 4. Run Inference Pipeline

**Real-Time Streaming:**

```bash
python pipelines/pipeline.py inference \
    --config config/pipeline.yaml \
    --kafka-bootstrap 127.0.0.1:29092
```

**This will**:

- Consume events from `dfp-events` Kafka topic
- Load models from MLflow
- Compute anomaly z-scores
- Publish detections to `dfp-detections` topic

### 5. View Results

- **MLflow UI**: <http://localhost:5001> - Models and experiments
- **Kafka UI**: <http://localhost:8080> - Topics and messages
- **API Documentation**: <http://localhost:8888> - Comprehensive API reference
- **Metrics**: <http://localhost:8000/metrics> - Prometheus format metrics
- **Health**: <http://localhost:8000/health> - Service health check
- **Prometheus**: <http://localhost:9090> - Metrics queries (if installed)
- **Grafana**: <http://localhost:3000> - Dashboards (if installed, default: admin/admin)
- **Anomaly Reports**: `data/output/detections/detections_*.csv`
- **Logs**: `logs/` (includes `alerts.log` for monitoring alerts)

## Services

The DFP platform requires several services to run. All services are managed through scripts in the `services/` directory.

### Service Management

```bash
# Start all services (MLflow, Kafka, monitoring)
./services/start_services.sh

# Stop all services
./services/stop_services.sh

# Restart all services (stop + start)
./services/restart_services.sh

# Restart only inference pipeline
./services/restart_services.sh inference

# Check service status
./services/check_services.sh

# Attach to tmux session to view service logs
tmux attach -t dfp-services
# Press Ctrl+B then 0/1/2/3 to switch windows
# Press Ctrl+B then D to detach
```

### Required Services

**1. MLflow Tracking Server:** (port 5001)

- Model registry and versioning
- Experiment tracking
- Auto-started by `start_services.sh`
- Backend: SQLite (`data/mlflow/mlflow.db`)
- Artifacts: `data/mlflow/`

**2. Apache Kafka:** (port 29092, KRaft mode)

- Streaming data pipeline
- No Zookeeper needed (KRaft mode)
- Auto-started by `start_services.sh`
- Topics: `dfp-events`, `dfp-detections`, `dfp-feedback`, `control-messages`
- Data: `data/kafka-logs/`

**3. Metrics Server:** (port 8000)

- Prometheus-format metrics endpoint
- Auto-started with pipeline
- Endpoints: `/metrics`, `/health`

**4. Alert Manager:**

- Multi-channel alert notifications
- Auto-started with pipeline
- Configuration: `config/alerting.yaml`
- Log: `logs/alerts.log`

### Optional Services

**5. Kafka UI** (port 8080)

- Web interface for Kafka
- Browse topics, messages, consumer groups
- Auto-downloaded on first start
- Skip with: `./services/start_services.sh --skip-kafka-ui`

**6. Prometheus** (port 9090)

- Metrics collection and storage
- Time-series database for historical metrics
- Install: `brew install prometheus`
- **Auto-started and stopped** via `brew services` when using service scripts
- Configuration: `config/prometheus.yml`

**7. Grafana** (port 3000)

- Metrics visualization dashboards
- 15-panel DFP dashboard included
- Install: `brew install grafana`
- **Auto-started and stopped** via `brew services` when using service scripts
- Default credentials: admin/admin
- Import dashboard: `config/grafana_dashboard.json`

### Service Architecture

```text
┌─────────────────────────────────────────────────────────┐
│                    DFP Services                         │
├─────────────────────────────────────────────────────────┤
│ MLflow (5001)          │ Model Registry & Tracking      │
│ Kafka (29092)          │ Streaming Data Pipeline        │
│ Kafka UI (8080)        │ Web Monitoring (optional)      │
│ Metrics Server (8000)  │ Prometheus Endpoint            │
│ Alert Manager          │ Notifications                  │
│ Prometheus (9090)      │ Metrics DB (optional)          │
│ Grafana (3000)         │ Dashboards (optional)          │
└─────────────────────────────────────────────────────────┘
```

See [Services README](services/README.md) for detailed documentation.

## Installation

### Standard Installation

```bash
# Clone repository
git clone https://github.com/Deloitte-UK-Innersource/morpheus-dfp.git
cd morpheus-dfp/dfp-poc

# Create virtual environment
python3 -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate

# Install dependencies
pip install -r ../requirements.txt

# Install development dependencies (optional)
pip install -e ".[dev]"

# Set up pre-commit hooks (recommended)
pre-commit install
```

### GPU Installation (NVIDIA Systems)

```bash
# Install CUDA-enabled PyTorch
pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu118

# Install RAPIDS (optional, for GPU-accelerated preprocessing)
pip install cudf-cu11 cuml-cu11 dask-cudf
```

### Docker Installation

```bash
# Build Docker image
docker build -t morpheus-dfp:latest -f docker/Dockerfile.cpu .

# Run container
docker run -it \
    -v $(pwd)/data:/app/data \
    -v $(pwd)/config:/app/config \
    -p 5001:5001 \
    morpheus-dfp:latest
```

## Usage

### Configuration

All configuration is managed through YAML files in `config/`:

- `base_config.yaml` - Global project settings
- `pipeline.yaml` - Pipeline-specific configuration
- `feature_schema.yaml` - Feature engineering definitions
- `mlflow.yaml` - MLflow tracking and registry settings
- `logging.yaml` - Logging configuration

See [Configuration Guide](config/README.md) for detailed documentation.

### Monitoring and Observability

**Verify Monitoring Setup:**

```bash
python scripts/verify_monitoring.py
```

This tests:

- Metrics collection (counters, gauges, histograms, summaries)
- Pipeline metrics tracking
- System metrics (CPU, memory, disk)
- Alert manager (15 rules, 2+ channels)
- HTTP metrics server (`/metrics`, `/health`)

**View Metrics:**

```bash
# Prometheus format metrics
curl http://localhost:8000/metrics

# Health check
curl http://localhost:8000/health

# Watch alerts
tail -f logs/alerts.log
```

**Grafana Dashboard:**

1. Open <http://localhost:3000> (login: admin/admin)
2. Go to Dashboards → Import
3. Upload `config/grafana_dashboard.json`
4. View 15 panels: events, anomalies, latency, throughput, system resources

**Alert Configuration:**

Edit `config/alerting.yaml` to configure:

- Alert rules (thresholds, conditions)
- Notification channels (email, Slack, PagerDuty)
- Alert severity levels

See [Monitoring Guide](docs/implementation/MONITORING.md) for detailed documentation.

### Training Models

**Run Training Pipeline:**

```bash
python pipelines/pipeline.py training \
    --config config/pipeline.yaml \
    --train-msg control_messages/train.json \
    --cache-dir .cache/dfp \
    --mlflow-uri http://localhost:5001 \
    --log-level INFO
```

**Control Message** (`control_messages/train.json`):

```json
{
  "tasks": [
    {
      "type": "training",
      "properties": {
        "data_path": "data/input/train/azure_ad_logs.json",
        "user_id": "*",
        "timestamp_column": "timestamp"
      }
    }
  ]
}
```

**Expected Output:**

- Per-user models: `DFP-user_01`, `DFP-user_02`, ...
- Generic model: `DFP-generic`
- Models saved to MLflow (viewable at <http://localhost:5001>)
- Training metrics logged (loss, epochs, validation)
- Rolling window cache populated with `last_train_count` baseline

### Running Inference

**Real-Time Kafka Streaming:**

```bash
python pipelines/pipeline.py inference \
    --config config/pipeline.yaml \
    --kafka-bootstrap 127.0.0.1:29092
```

**What Happens:**

1. Kafka consumer polls `dfp-events` topic every 10ms
2. Events processed through DFP preprocessing pipeline
3. Models loaded from MLflow (per-user or generic fallback)
4. Anomaly z-scores computed using reconstruction error
5. Detections (z-score > 3.0) published to `dfp-detections` topic

**Expected Output:**

- Real-time anomaly detections with z-scores
- Model metadata (name, version, load time)
- Per-user inference statistics
- Metrics exposed at <http://localhost:8000/metrics>

### Complete Workflow

**1. Start all services:**

```bash
cd dfp-poc
./services/start_services.sh
./services/check_services.sh
```

**2. Generate training data:**

```bash
python scripts/utils/generate_azure_ad_data.py \
  --output data/input/train/azure_ad_train.jsonl \
  --num-events 150000 \
  --num-users 50 \
  --duration-days 70 \
  --start-time "2025-08-11T00:00:00+00:00" \
  --min-events-per-user 300 \
  --events-per-user variable \
  --user-seed 42 \
  --event-seed 42 \
  --anomaly-rate 0.0
```

**3. Train models:**

```bash
python pipelines/pipeline.py training \
    --config config/pipeline.yaml \
    --train-msg control_messages/train.json
```

**4. Generate inference data (with anomalies):**

```bash
python scripts/utils/generate_azure_ad_data.py \
  --output data/input/train/azure_ad_train.jsonl \
  --num-events 150000 \
  --num-users 50 \
  --duration-days 70 \
  --start-time "2025-08-11T00:00:00+00:00" \
  --min-events-per-user 300 \
  --events-per-user variable \
  --user-seed 43 \
  --event-seed 43 \
  --anomaly-rate 0.10
```

**5. Publish events to Kafka:**

```bash
cat data/input/infer/azure_ad_logs.json | kafka-console-producer \
    --bootstrap-server 127.0.0.1:29092 \
    --topic dfp-events
```

**6. Run real-time inference:**

```bash
python pipelines/pipeline.py inference \
    --config config/pipeline.yaml \
    --kafka-bootstrap 127.0.0.1:29092
```

**7. View detections:**

```bash
kafka-console-consumer \
    --bootstrap-server 127.0.0.1:29092 \
    --topic dfp-detections \
    --from-beginning
```

**Key Points:**

- Pipelines share `.cache/dfp` directory for feature continuity
- Training populates `last_train_count` baseline
- Inference reads baseline from cache for correct increment features
- Models versioned in MLflow for rollback capability

## Main Configuration

### Key Configuration Parameters

**Training Configuration:**

```yaml
training:
  epochs: 100
  validation_size: 0.1
  min_training_samples: 100
  model_kwargs:
    encoder_layers: [512, 500]
    decoder_layers: [512]
    learning_rate: 0.01
    batch_size: 512
```

**Inference Configuration:**

```yaml
inference:
  batch_size: 64
  anomaly_threshold:
    type: "z_score"
    value: 2.0 # Standard deviations
  model_selection:
    prefer_user_specific: true
    fallback_to_generic: true
```

**DFP Configuration:**

```yaml
dfp:
  userid_column: "username"
  timestamp_column: "timestamp"
  training:
    min_history: 300 # Minimum events for training
    min_increment: 300 # Minimum new events to retrain
    max_history: "60d" # Training window
    cache_mode: "aggregate"
  inference:
    min_history: 1
    min_increment: 0
    max_history: "1d"
    cache_mode: "batch"
```

See [Configuration Guide](config/README.md) for complete documentation.

## Project Structure

```bash
dfp-poc/
├── config/                     # Configuration files
│   ├── base_config.yaml        # Global settings
│   ├── pipeline.yaml           # Pipeline configuration
│   ├── feature_schema.yaml     # Feature definitions (1026 lines)
│   ├── mlflow.yaml             # MLflow settings
│   └── logging.yaml            # Logging configuration
├── modules/                    # Core modules
│   ├── control/                # Control message system
│   ├── dfencoder/              # NVIDIA AutoEncoder implementation
│   ├── inference/              # Inference and anomaly detection
│   ├── io/                     # File and stream I/O
│   ├── preprocessing/          # Data preprocessing
│   │   ├── geographic_features.py  # Geographic feature engineering and optional impossible travel detection
│   │   ├── dfp_preprocessing.py    # Feature engineering pipeline
│   │   └── rolling_window.py       # Time-based aggregation
│   ├── training/               # Model training
│   └── utils/                  # Utilities (config, logging, MLflow)
├── pipelines/                  # Pipeline implementations
│   ├── training_pipeline.py    # Training pipeline (DFPTrainingPipeline)
│   ├── inference_pipeline.py   # Inference pipeline (DFPInferencePipeline)
│   ├── pipeline.py             # Main orchestrator with CLI
│   └── README.md               # Pipeline documentation
├── scripts/                    # Utility scripts
│   └── utils/                  # Data generation
├── control_messages/           # Sample control messages
│   ├── train.json
│   └── infer.json
├── services/                   # Service management scripts
│   ├── start_services.sh       # Start all services (includes Prometheus/Grafana)
│   ├── stop_services.sh        # Stop all services (includes Prometheus/Grafana)
│   ├── restart_services.sh     # Restart all services (stop + start)
│   ├── check_services.sh       # Health checks
│   ├── start_monitoring.sh     # Start monitoring only
│   ├── stop_monitoring.sh      # Stop monitoring only
│   ├── check_monitoring.sh     # Monitoring status
│   └── clean_kafka_data.sh     # Clean Kafka storage
├── tests/                      # Test suite (251/251 passing)
├── notebooks/                  # Jupyter notebooks (analysis/examples)
├── data/                       # Data directories
│   ├── raw/                    # Raw input data
│   ├── processed/              # Processed data
│   ├── output/                 # Inference results
│   └── mlflow/                 # MLflow artifacts & tracking
└── logs/                       # Application logs
```

See [Module Documentation](modules/README.md) for detailed module descriptions.

## Development

### Development Setup

```bash
# Install development dependencies
pip install -e ".[dev]"

# Set up pre-commit hooks
pre-commit install

# Run pre-commit on all files
pre-commit run --all-files
```

### Running Tests

```bash
# Run all tests
pytest tests/ -v

# Run with coverage
pytest tests/ --cov=modules --cov=pipelines --cov-report=html

# Run specific test module
pytest tests/test_dfp_trainer.py -v

# Run tests in parallel
pytest tests/ -n auto
```

**Current Test Coverage:** 251/251 tests passing (100%)

### Code Quality

The project uses automated code quality tools via pre-commit hooks:

```bash
# Format and lint with Ruff (recommended - replaces Black + flake8)
ruff format modules/ pipelines/ tests/ scripts/  # Format code
ruff check modules/ pipelines/ tests/ scripts/ --fix  # Lint and auto-fix

# Format and lint all Python files in project (one command)
ruff format . && ruff check . --fix

# Alternative: Use Black for formatting (if preferred)
black modules/ pipelines/ tests/ scripts/
ruff check modules/ pipelines/ tests/ scripts/ --fix

# Type check with mypy
mypy modules/ pipelines/

# Security scan with Bandit
bandit -r modules/ pipelines/ scripts/

# Run all quality checks
pre-commit run --all-files
```

**Quick Commands (Recommended):**

```bash
# Format and lint everything (single workflow)
ruff format . && ruff check . --fix

# Check what would change (dry run)
ruff format --check .
ruff check .

# Format only (no linting)
ruff format .

# Lint only (no formatting)
ruff check . --fix
```

**Note:** Ruff's formatter is compatible with Black, but using both together can cause conflicts. Choose one:

- **Option 1 (Recommended):** Use `ruff format` + `ruff check` (faster, single tool)
- **Option 2:** Use `black` + `ruff check` (if you prefer Black's formatter)

### Conventional Commits

This project uses [Conventional Commits](https://www.conventionalcommits.org/) for automated versioning and changelog generation:

```bash
feat: add new feature
fix: bug fix
docs: documentation changes
style: code style changes
refactor: code refactoring
perf: performance improvements
test: test changes
chore: maintenance tasks
```

### Adding New Features

1. Create feature branch: `git checkout -b feat/feature-name`
2. Create module in appropriate `modules/` subdirectory
3. Add comprehensive docstrings (Google style)
4. Write unit tests in `tests/`
5. Update configuration if needed
6. Document in relevant README
7. Run quality checks: `pre-commit run --all-files`
8. Commit with conventional commits: `git commit -m "feat: add feature description"`
9. Create pull request using the PR template

### Release Process

Releases are automated via semantic versioning:

1. Merge changes to `main` branch
2. Create version tag: `git tag v0.2.0`
3. Push tag: `git push origin v0.2.0`
4. GitHub Actions automatically:
   - Builds release artifacts
   - Generates changelog
   - Creates GitHub release
   - Publishes Docker images

See [CONTRIBUTING.md](CONTRIBUTING.md) for detailed contribution guidelines.

## Testing

### Test Organization

```bash
tests/
├── test_control/              # Control message tests
├── test_preprocessing/        # Preprocessing tests
├── test_training/             # Training module tests
├── test_inference/            # Inference module tests
├── test_io/                   # I/O module tests
└── test_utils/                # Utility tests
```

### Running Specific Test Suites

```bash
# Preprocessing tests
pytest tests/test_preprocessing/ -v

# Training tests
pytest tests/test_training/ -v

# Inference tests
pytest tests/test_inference/ -v

# Integration tests
pytest tests/test_integration/ -v
```

### Test Data

Test fixtures and synthetic data are generated automatically during testing. See `tests/conftest.py` for shared fixtures.

## Performance

### Benchmarks (M3 MacBook Pro)

**Training:**

- Per-user model (1000 events): ~5-10 seconds
- Generic model (50k events): ~2-3 minutes
- 50 users training: ~5-8 minutes total

**Inference:**

- Batch inference (10k events): ~15-20 seconds
- Throughput: ~500-700 events/second
- Latency (p50): ~2-3ms per event

**Memory:**

- Base memory: ~500MB
- Peak during training: ~2-3GB
- Inference: ~1-1.5GB

### GPU Performance (Expected)

Training speedup: 5-10x faster than CPU
Inference throughput: 2000-5000 events/second

## References

### NVIDIA Morpheus Documentation

1. **Digital Fingerprinting Guide**

   - <https://docs.nvidia.com/morpheus/developer_guide/guides/5_digital_fingerprinting.html>

2. **Modular Pipeline Guide**

   - <https://docs.nvidia.com/morpheus/developer_guide/guides/10_modular_pipeline_digital_fingerprinting.html>

3. **DFP Training Module**

   - <https://docs.nvidia.com/morpheus/modules/examples/digital_fingerprinting/dfp_training.html>

4. **DFP Inference Module**
   - <https://docs.nvidia.com/morpheus/modules/examples/digital_fingerprinting/dfp_inference.html>

### NVIDIA Morpheus Repository

- GitHub: <https://github.com/nv-morpheus/Morpheus>
- Branch: `branch-25.10`
- Example: `examples/digital_fingerprinting/production/dfp_integrated_training_batch_pipeline.py`

### Academic References

1. AutoEncoder-based anomaly detection in time series
2. User behavior analytics for security
3. Deep learning for fraud detection

### Project Documentation

- [Architecture Documentation](docs/implementation/ARCHITECTURE.md) - Comprehensive system architecture with diagrams
- [Implementation Status](docs/implementation/STATUS_SUMMARY.md) - Current system capabilities and validation
- [Monitoring & Observability](docs/implementation/MONITORING.md) - Metrics, alerting, and Grafana setup guide
- [Module Documentation](modules/README.md) - Module architecture and interfaces
- [Pipeline Documentation](pipelines/README.md) - Pipeline usage and patterns
- [Configuration Guide](config/README.md) - Configuration reference
- [Jupyter Notebooks](notebooks/) - Exploratory analysis and examples

## License

Copyright (c) 2025 Deloitte. All rights reserved.

This project implements NVIDIA Morpheus DFP architecture. NVIDIA Morpheus components are licensed under Apache 2.0.

## Contributing

We welcome contributions! Please see [CONTRIBUTING.md](CONTRIBUTING.md) for guidelines on:

- Setting up development environment
- Code style and quality standards
- Testing requirements
- Pull request process
- Commit message conventions

## Support

- **Issues**: [GitHub Issues](https://github.com/Deloitte-UK-Innersource/morpheus-dfp/issues)
- **Discussions**: [GitHub Discussions](https://github.com/Deloitte-UK-Innersource/morpheus-dfp/discussions)
- **Email**: DFP Development Team
- **Documentation**: [docs/](docs/)

## Roadmap

**Completed:**

- FilterDetections integration (NVIDIA standard binary filtering)
  - Post-inference filtering with configurable thresholds (mean_abs_z > 2.0)
  - Comprehensive detection messages with all feature details
  - Enhanced top_features format: "feature=value (z=score)"
  - Timestamp extraction from windowed data
  - Test suite improvements for location consistency

**Upcoming Features:**

- Real-time adaptive thresholding for anomaly detection
- Multi-user correlation analysis for coordinated attacks
- Extended geographic feature engineering (geofencing, risk zones)
- Enhanced monitoring and alerting capabilities

---

**Version:** 0.2.0  
**Last Updated:** December 2025  
**Status:** Production PoC with FilterDetections Integration  
**Author:** Tomasz Zabek <tzabek@deloitte.co.uk>  
**Generated By:** Claude Sonnet 4.5
