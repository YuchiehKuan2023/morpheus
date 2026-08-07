# NVIDIA Morpheus Digital Fingerprinting — Demo with AI Intelligence Layer

[![CI](https://github.com/Deloitte-UK-Innersource/morpheus-dfp/actions/workflows/ci.yml/badge.svg)](https://github.com/Deloitte-UK-Innersource/morpheus-dfp/actions/workflows/ci.yml)
[![Security](https://github.com/Deloitte-UK-Innersource/morpheus-dfp/actions/workflows/security.yml/badge.svg)](https://github.com/Deloitte-UK-Innersource/morpheus-dfp/actions/workflows/security.yml)
[![License](https://img.shields.io/badge/License-Apache%202.0-blue.svg)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.10%20%7C%203.11%20%7C%203.12-blue)](https://www.python.org)
[![Code style: black](https://img.shields.io/badge/code%20style-black-000000.svg)](https://github.com/psf/black)
[![Ruff](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json)](https://github.com/astral-sh/ruff)

A production-ready implementation of NVIDIA Morpheus Digital Fingerprinting (DFP) extended with a full **AI Intelligence Layer** and a **React analyst dashboard**. Detects anomalous user behavior in Azure AD authentication logs using per-user AutoEncoder models, then enriches every detection with root cause classification, risk scoring, LLM-generated explanations, and semantic similarity search — delivering analyst-ready intelligence in real time.

## Table of Contents

- [Overview](#overview)
- [Architecture](#architecture)
- [AI Intelligence Layer](#ai-intelligence-layer)
- [Features](#features)
- [Quick Start](#quick-start)
- [Installation](#installation)
- [Usage](#usage)
- [Configuration](#configuration)
- [Services](#services)
- [Frontend](#frontend)
- [Project Structure](#project-structure)
- [Development](#development)
- [Testing](#testing)
- [References](#references)

## Overview

This implementation extends NVIDIA's Digital Fingerprinting platform for detecting anomalous user behavior in Azure AD authentication logs. The system uses per-user AutoEncoder models to learn normal behavioral patterns and detect deviations that may indicate security threats — then routes every detection through a multi-stage AI intelligence pipeline that produces risk scores, root cause labels, LLM explanations, and a React analyst dashboard.

**DFP Core Capabilities:**

- **DFP behavioral learning with geographic features**:
  - Per-user AutoEncoder models trained on behavioral patterns
  - Geographic features (`travel_speed_kmph`) included in behavioral learning
  - Models learn normal travel patterns per user (typically 0–100 km/h)
- **FilterDetections**: NVIDIA standard binary filtering (threshold=2.0, mean_abs_z)
- Per-user anomaly detection using AutoEncoder neural networks
- Geographic feature engineering for travel pattern analysis
- Real-time and batch processing modes
- Integrated training and inference pipelines
- MLflow model registry integration
- Kafka streaming support
- Cross-platform support (CPU and GPU with automatic fallback)

**AI Intelligence Layer (additional):**

- **AI Orchestrator**: Dual-thread processor — anomalous events enriched + labeled; clean events persisted for DFP retraining
- **Enrichment**: User profile, device, location, and historical behaviour context attached to every detection
- **Entity Extraction**: spaCy NER extracts named entities (users, IPs, systems, resources) and populates a Neo4j knowledge graph
- **Semantic Search**: Sentence-BERT embeddings in Qdrant retrieve similar past detections for context
- **Root Cause Classification**: DistilBERT 9-class model (Impossible Travel, Unusual Location, Unusual App/Browser/OS, Unknown Device, Location+Device, High Logcount, Multi-Factor)
- **Risk Scoring**: XGBoost + SHAP — 0–100 risk score with explainable contributing factors
- **LLM Explanation**: RAG pipeline (GPT-4 / Llama 3) generates plain-English analyst narratives
- **Feedback Loop**: AI auto-labeling (true/false positive) feeds validated clean events back to DFP retraining

**Frontend Dashboard:**

- React 19 + TypeScript + Vite 7 + Tailwind CSS v4 + shadcn/ui (Nova preset)
- Dashboard, Anomalies, and Users pages backed by FastAPI serving enriched PostgreSQL data

**Target Environments:**

- Development: M3 MacBook Pro (CPU, native macOS services)
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

## AI Intelligence Layer

After the DFP inference pipeline emits an anomaly detection (via the `dfp-detections` Kafka topic), the AI Intelligence Layer enriches and scores it before persisting to PostgreSQL for the frontend.

### End-to-End Flow

```text
DFP Inference Pipeline
        │
        ▼
  Kafka: dfp-detections ──────────────────────────────────────────┐
        │                                                          │
        ▼                                                          ▼
 AI Orchestrator                                        Kafka: dfp-clean-events
 (Thread A: Anomalies)                                  (Thread B: Clean Events)
        │                                                          │
        ▼                                                          ▼
 Enrichment Service                                     dfp_feedback_service
 ├─ User profile (Redis cache)                          (false positives → retraining)
 ├─ Device / location context
 ├─ Historical behaviour summary
 │
 ├─► Entity Extraction (spaCy NER → Neo4j)
 ├─► Vector Embedding (Sentence-BERT → Qdrant)
 ├─► Semantic Similarity Search (Qdrant k-NN)
 ├─► Root Cause Classification (DistilBERT, 9 classes)
 ├─► Risk Scoring (XGBoost, 0–100 + SHAP)
 ├─► LLM Explanation (GPT-4 / Llama 3 + RAG)
 └─► Auto-Labeling (heuristic + LLM ensemble)
        │
        ▼
 PostgreSQL: enriched_anomalies
        │
        ▼
 FastAPI Backend → Frontend Dashboard
```

### AI Services

| Service           | Technology               | Purpose                                        |
| ----------------- | ------------------------ | ---------------------------------------------- |
| Enrichment        | Python + Redis           | Context assembly, user/device/geo profiles     |
| Entity Extraction | spaCy NER                | Named entity recognition (users, IPs, systems) |
| Knowledge Graph   | Neo4j                    | Entity relationships, blast radius analysis    |
| Semantic Search   | Sentence-BERT + Qdrant   | Similar detection retrieval                    |
| Root Cause        | DistilBERT (fine-tuned)  | 9-class anomaly categorisation                 |
| Risk Scoring      | XGBoost + SHAP           | 0–100 risk score with explainability           |
| LLM Explanation   | GPT-4 / Llama 3          | RAG-based analyst narrative generation         |
| Auto-Labeling     | Heuristic + LLM ensemble | True/false positive classification             |

### Running the AI Orchestrator

```bash
# After starting all services
cd dfp-demo
python scripts/run_ai_orchestrator.py

# Or via services script (tmux window 8: AI-Orch)
./services/start_services.sh
```

See [AI Intelligence Layer docs](docs/implementation/AI_INTELLIGENCE_LAYER.md) and [AI Orchestrator docs](docs/implementation/AI_ORCHESTRATOR.md) for detailed architecture documentation.

## Features

### DFP Core Functionality

- **DFP Behavioral Learning**: AutoEncoder-based anomaly detection
  - Per-user models trained on behavioral + geographic features
  - `travel_speed_kmph` included in training (models learn normal travel patterns)
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
- **Binary Filtering**: FilterDetections module provides post-inference filtering
  - Field: mean_abs_z (average of absolute z-scores across all features)
  - Comprehensive detection messages: `features`, `top_features`, timestamp, anomaly_score, max_abs_z, feature_count
- **Anomaly Scoring**: Z-score based detection with configurable thresholds

### AI Intelligence Layer Features

- **Enrichment**: User profile, historical behaviour, device, and geo context attached per detection
- **Entity Extraction & Knowledge Graph**: spaCy NER → Neo4j; entities linked across detections for blast radius analysis
- **Semantic Similarity Search**: Sentence-BERT + Qdrant; retrieves previous detections that are contextually similar
- **Root Cause Classification (9 classes)**:
  - Impossible Travel, Unusual Location, Unusual Application, Unusual Browser, Unusual OS
  - Unknown Device, Location + Device, High Login Count, Multi-Factor deviation
  - Model: DistilBERT fine-tuned on 1,652 labeled anomalies
- **Risk Scoring**: XGBoost model; 0–100 score with SHAP feature contributions stored as JSONB
- **LLM Explanation (RAG)**: GPT-4 / Llama 3 narrative generation using detection context + retrieved similar cases
- **Auto-Labeling**: AI ensemble (heuristic + LLM) labels detections as True/False Positive automatically
- **DFP Feedback Loop**: Validated false positives re-ingested as clean training events for model retraining

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
cd dfp-demo
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

- **MLflow UI**: <http://localhost:5001> — Models and experiments
- **Kafka UI**: <http://localhost:8080> — Topics and messages
- **Metrics**: <http://localhost:8000/metrics> — Prometheus format metrics
- **Health**: <http://localhost:8000/health> — Service health check
- **Prometheus**: <http://localhost:9090> — Metrics queries (optional)
- **Grafana**: <http://localhost:3000> — DFP dashboard (optional, default: admin/admin)
- **Frontend Dashboard**: <http://localhost:5173> — React analyst dashboard
- **Backend API**: <http://localhost:8000/docs> — FastAPI Swagger UI (enriched data)
- **Neo4j Browser**: <http://localhost:7474> — Knowledge graph exploration
- **Qdrant Dashboard**: <http://localhost:6333/dashboard> — Vector database UI
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
# Press Ctrl+B then 0/1/2/3/5/6/7/8 to switch windows
# Windows: MLflow, Kafka, Metrics, API, Backend, Frontend, Grafana, AI-Orch
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
- Topics: `dfp-events`, `dfp-detections`, `dfp-clean-events`, `dfp-feedback`, `control-messages`
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

### AI Intelligence Layer Services

**8. PostgreSQL** (port 5432)

- Source of truth for all enriched detections, labels, and risk scores
- Stores: `enriched_anomalies`, `user_training_events`, `llm_explanations`
- Queried by the FastAPI backend to serve the frontend dashboard

**9. Qdrant** (ports 6333 REST, 6334 gRPC)

- Vector database for semantic similarity search
- Stores: Sentence-BERT embeddings (384-dim) for every enriched detection
- Enables retrieval of similar historical detections for RAG context

**10. Neo4j** (ports 7474 HTTP, 7687 Bolt)

- Knowledge graph for entity relationships
- Stores: users, IPs, devices, resources and their connections across detections
- Enables blast radius analysis and entity correlation

**11. Redis** (port 6379)

- High-speed cache for AI features and session state
- Caches: user profiles, embedding lookups, enrichment intermediate results
- Provides 1,944x speedup vs cold computation for repeat queries

**12. AI Orchestrator** (background process)

- Started by `start_services.sh` (tmux window 8: `AI-Orch`)
- Dual-thread: Thread A consumes `dfp-detections`, Thread B consumes `dfp-clean-events`
- Runs independently of the inference pipeline; processes 1–3 seconds per event

### Service Architecture

```text
┌────────────────────────────────────────────────────────────────┐
│                      DFP Core Services                         │
├────────────────────────────────────────────────────────────────┤
│ MLflow (5001)          │ Model Registry & Tracking             │
│ Kafka (29092)          │ Streaming Pipeline (KRaft, no ZK)     │
│ Kafka UI (8080)        │ Web Monitoring (optional)             │
│ Metrics Server (8000)  │ Prometheus Endpoint                   │
│ Pushgateway (9091)     │ Batch Job Metrics Persistence         │
│ Alert Manager          │ Multi-Channel Notifications           │
│ Prometheus (9090)      │ Metrics DB (optional)                 │
│ Grafana (3000)         │ 15-Panel Dashboard (optional)         │
├────────────────────────────────────────────────────────────────┤
│                   AI Intelligence Services                     │
├────────────────────────────────────────────────────────────────┤
│ PostgreSQL (5432)      │ Enriched Anomalies (source of truth)  │
│ Qdrant (6333/6334)     │ Vector DB — Semantic Similarity       │
│ Neo4j (7474/7687)      │ Knowledge Graph — Entity Relations    │
│ Redis (6379)           │ AI Feature Cache                      │
│ AI Orchestrator        │ Async Enrichment Processing           │
├────────────────────────────────────────────────────────────────┤
│                       Frontend Services                        │
├────────────────────────────────────────────────────────────────┤
│ Backend API (8000)     │ FastAPI — Enriched Data REST API      │
│ Frontend UI (5173)     │ React Dashboard                       │
└────────────────────────────────────────────────────────────────┘
```

Kafka Topics:

- `dfp-events` — raw user activity events (inference input)
- `dfp-detections` — anomaly detections (FilterDetections output)
- `dfp-clean-events` — non-anomalous events (AI orchestrator input)
- `dfp-feedback` — false positive feedback
- `control-messages` — pipeline control

See [Services README](services/README.md) for detailed documentation.

## Installation

### Standard Installation

```bash
# Clone repository
git clone https://github.com/Deloitte-UK-Innersource/morpheus-dfp.git
cd morpheus-dfp/dfp-demo

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
cd dfp-demo
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

## Frontend

The React analyst dashboard provides real-time visibility into enriched anomaly detections.

### Tech Stack

- **React 19** + **TypeScript** — component framework and type safety
- **Vite 7** — build tool and HMR development server
- **Tailwind CSS v4** — utility-first styling (CSS-first configuration, `@tailwindcss/vite` plugin)
- **shadcn/ui (Nova preset)** — Radix UI component library
- **Redux Toolkit** — application state management
- **React Router v7** — client-side navigation
- **FastAPI** — Python backend REST API serving enriched data from PostgreSQL

### Pages

- **Dashboard** — KPI cards, live anomaly statistics, model health, recent detections
- **Anomalies** — full detection list with severity filter, AI risk score, root cause badge, LLM explanation
- **Users** — per-user profiles, behavioral baseline, anomaly history, risk trend

### Setup

```bash
# Frontend UI
cd frontend/ui
npm install
npm run dev       # http://localhost:5173
npm run build     # Production build

# Backend API
cd frontend/backend
pip install -r requirements.txt
python main.py    # http://localhost:8000
```

### Environment

```env
# frontend/ui/.env
VITE_API_URL=http://localhost:8000

# frontend/backend/.env
MLFLOW_TRACKING_URI=http://localhost:5001
KAFKA_BOOTSTRAP_SERVERS=localhost:29092
KAFKA_DETECTIONS_TOPIC=dfp-detections
DB_HOST=localhost
DB_PORT=5432
```

See [Frontend README](frontend/README.md) for full setup and API documentation.

## Project Structure

```bash
dfp-demo/
├── config/                     # Configuration files
│   ├── base_config.yaml        # Global settings (includes dfp-clean-events topic)
│   ├── pipeline.yaml           # Pipeline configuration
│   ├── feature_schema.yaml     # Feature definitions
│   ├── mlflow.yaml             # MLflow settings
│   ├── alerting.yaml           # Alert rules (15 predefined)
│   └── logging.yaml            # Logging configuration
├── modules/                    # Core modules
│   ├── control/                # Control message system
│   ├── dfencoder/              # NVIDIA AutoEncoder implementation
│   ├── inference/              # Inference and anomaly detection
│   ├── io/                     # File and stream I/O
│   ├── preprocessing/          # Data preprocessing
│   │   ├── geographic_features.py  # Geographic feature engineering
│   │   ├── dfp_preprocessing.py    # Feature engineering pipeline
│   │   └── rolling_window.py       # Time-based aggregation
│   ├── training/               # Model training
│   ├── utils/                  # Utilities (config, logging, MLflow)
│   └── ai/                     # AI Intelligence Layer
│       ├── orchestrator/       # AI Orchestrator (dual-thread Kafka consumer)
│       │   ├── ai_orchestrator.py  # Main orchestrator class
│       │   └── event_router.py     # EventType / RoutedEvent dataclass
│       ├── enrichment/         # Enrichment service and persistence
│       │   ├── enrichment_service.py   # Main orchestration (722 lines)
│       │   ├── persistence_service.py  # PostgreSQL write path
│       │   └── cold_start_handler.py  # Progressive enablement logic
│       ├── embeddings/         # Vector search
│       │   ├── embedding_service.py   # Sentence-BERT (all-MiniLM-L6-v2, 384-dim)
│       │   ├── vector_store.py        # Qdrant integration
│       │   └── similarity_search.py   # Search API
│       ├── entity_extraction/  # NER and knowledge graph
│       │   ├── ner_service.py         # spaCy NER
│       │   └── graph_populator.py     # Neo4j population
│       ├── root_cause/         # Root cause classification
│       │   ├── classifier.py          # DistilBERT 9-class inference
│       │   ├── labeling_worker.py     # Classify single / batch
│       │   └── training.py            # Fine-tuning
│       ├── risk_scoring/       # Risk assessment
│       │   ├── risk_scorer.py         # XGBoost predict
│       │   └── explainer.py           # SHAP values
│       ├── llm/                # LLM and RAG
│       │   ├── llm_service.py         # GPT-4 / Llama 3 (871 lines)
│       │   ├── rag_pipeline.py        # RAG context assembly
│       │   ├── db_persistence.py      # LLM output → PostgreSQL
│       │   └── json_parser.py         # LLM response parsing
│       ├── auto_labeling/      # Auto-labeling and feedback
│       │   ├── anomaly_validator.py   # 3-method weighted ensemble
│       │   ├── batch_labeler.py       # Bulk + single labeling
│       │   └── dfp_feedback_service.py # False positive → retraining
│       └── shared/             # Utilities
│           ├── feature_bridge.py      # DFP features → AI features
│           └── monitoring.py          # 23 Prometheus metrics
├── pipelines/                  # Pipeline implementations
│   ├── training_pipeline.py    # Training pipeline (DFPTrainingPipeline)
│   ├── inference_pipeline.py   # Inference pipeline + clean event publishing
│   └── pipeline.py             # Main orchestrator with CLI
├── scripts/                    # Utility scripts
│   ├── run_ai_orchestrator.py  # AI Orchestrator entrypoint
│   ├── db/migrations/          # PostgreSQL migration SQL files
│   └── utils/                  # Data generation + labeling tools
├── frontend/                   # Analyst dashboard
│   ├── ui/                     # React app (Vite + Tailwind v4 + shadcn)
│   └── backend/                # FastAPI REST API
├── control_messages/           # Sample control messages
├── services/                   # Service management scripts
│   ├── start_services.sh       # Start all services (AI + DFP + frontend)
│   ├── stop_services.sh        # Graceful shutdown
│   ├── restart_services.sh     # Stop + start
│   ├── check_services.sh       # Health checks (all 12 services)
│   └── clean_kafka_data.sh     # Clean Kafka storage
├── tests/                      # Test suite (15/15 orchestrator tests passing)
├── notebooks/                  # Jupyter notebooks
├── data/                       # Data directories
│   ├── input/                  # Training and inference data
│   ├── output/                 # Inference results
│   ├── mlflow/                 # MLflow artifacts & tracking
│   └── ai/                     # AI service data (qdrant, neo4j, redis, postgres)
└── docs/
    └── implementation/
        ├── PROGRESS_TRACKER.md       # Live implementation status
        ├── AI_INTELLIGENCE_LAYER.md  # Architecture reference
        ├── AI_ORCHESTRATOR.md        # Orchestrator design
        └── AI_PIPELINE.md            # End-to-end pipeline documentation
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

- [Architecture Documentation](docs/implementation/ARCHITECTURE.md) — Comprehensive system architecture with diagrams
- [AI Intelligence Layer](docs/implementation/AI_INTELLIGENCE_LAYER.md) — AI layer architecture reference
- [AI Orchestrator](docs/implementation/AI_ORCHESTRATOR.md) — Orchestrator design and Kafka topic flow
- [AI Pipeline](docs/implementation/AI_PIPELINE.md) — End-to-end detection-to-intelligence pipeline
- [Progress Tracker](docs/implementation/PROGRESS_TRACKER.md) — Live implementation status
- [Monitoring & Observability](docs/poc-progress/implementation/MONITORING.md) — Metrics, alerting, and Grafana setup
- [Labeling & Feedback Architecture](docs/implementation/LABELING_FEEDBACK_ARCHITECTURE.md) — Auto-labeling and DFP feedback loop design
- [Module Documentation](modules/README.md) — Module architecture and interfaces
- [Pipeline Documentation](pipelines/README.md) — Pipeline usage and patterns
- [Configuration Guide](config/README.md) — Configuration reference
- [Services README](services/README.md) — All 12 services: setup, management, troubleshooting
- [Frontend README](frontend/README.md) — Dashboard setup and API documentation
- [Jupyter Notebooks](notebooks/) — Exploratory analysis and examples

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
- Geographic feature engineering (haversine distance, travel velocity)
- Per-user AutoEncoder models with generic fallback
- AI Intelligence Layer (Phases A–C complete):
  - Enrichment service (user profile, device, geo context)
  - Entity extraction → Neo4j knowledge graph
  - Sentence-BERT embeddings → Qdrant semantic search
  - DistilBERT root cause classifier (9 classes, 1,652 training samples)
  - XGBoost + SHAP risk scoring
  - LLM explanation via RAG (GPT-4 / Llama 3)
  - AI auto-labeling (heuristic + LLM ensemble)
  - DFP feedback loop (false positives → clean event retraining)
  - AI Orchestrator (dual-thread, 15/15 tests passing)
- Frontend dashboard (React 19, Tailwind v4, shadcn Nova)
- FastAPI backend with PostgreSQL integration

**In Progress / Upcoming:**

- Backend REST API endpoints serving enriched data to frontend
- Frontend: anomaly detail view with LLM explanation and SHAP factors
- Frontend: real-time updates via WebSocket or polling
- Live end-to-end integration test (inference → orchestrator → `enriched_anomalies`)
- Risk scorer retraining on real detections
- User authentication and multi-tenant support
- Time series forecasting (Prophet) for anomaly rate prediction

---

**Version:** 1.0.0  
**Last Updated:** March 2026  
**Status:** AI Intelligence Layer complete; frontend in active development  
**Author:** Tomasz Zabek <tzabek@deloitte.co.uk>
