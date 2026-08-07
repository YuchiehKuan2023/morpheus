# Configuration Guide

This directory contains all configuration files for the Digital Fingerprinting Platform. Configurations use YAML format with OmegaConf for variable interpolation and validation.

## Table of Contents

- [Configuration Files](#configuration-files)
- [Configuration Hierarchy](#configuration-hierarchy)
- [Base Configuration](#base-configuration)
- [Pipeline Configuration](#pipeline-configuration)
- [Feature Schema](#feature-schema)
- [MLflow Configuration](#mlflow-configuration)
- [Logging Configuration](#logging-configuration)
- [Variable Interpolation](#variable-interpolation)
- [Environment Variables](#environment-variables)
- [Configuration Patterns](#configuration-patterns)
- [Validation](#validation)
- [Troubleshooting](#troubleshooting)

## Configuration Files

| File                  | Purpose                         | Size        | Priority  |
| --------------------- | ------------------------------- | ----------- | --------- |
| `base_config.yaml`    | Global project settings         | 200 lines   | Base      |
| `pipeline.yaml`       | Pipeline-specific configuration | 400 lines   | Override  |
| `feature_schema.yaml` | Feature engineering definitions | 1,026 lines | Reference |
| `mlflow.yaml`         | MLflow tracking and registry    | 350 lines   | Reference |
| `logging.yaml`        | Logging configuration           | 300 lines   | Reference |

## Configuration Hierarchy

Configurations are loaded in hierarchical order:

```text
base_config.yaml (lowest priority)
    |
    v
pipeline.yaml (inherits from base)
    |
    v
Command-line arguments (highest priority)
```

**Override Rules:**

- Nested keys are merged recursively
- Command-line arguments override all file-based config
- Later configurations override earlier ones

**Example:**

```yaml
# base_config.yaml
training:
  epochs: 100
  batch_size: 32

# pipeline.yaml
defaults:
  - base_config

training:
  epochs: 50  # Overrides base_config

# Result: epochs=50, batch_size=32 (inherited)
```

## Base Configuration

**File:** `base_config.yaml`

**Purpose:** Global settings inherited by all pipelines and modules.

### Project Settings

```yaml
project:
  name: "morpheus-dfp-demo"
  version: "0.1.0"
  description: "NVIDIA Morpheus Digital Fingerprinting Proof of Concept"
```

### Environment Settings

```yaml
environment:
  device: "auto" # Device selection: auto, cpu, cuda, mps
  seed: 42 # Random seed for reproducibility
  num_workers: 4 # Parallel data loading workers
  debug: false # Enable debug mode
```

**Device Options:**

- `auto`: Automatically detect best available device (CUDA > MPS > CPU)
- `cpu`: Force CPU execution
- `cuda`: Force NVIDIA GPU (requires CUDA)
- `mps`: Force Apple Silicon GPU (M1/M2/M3)

### Path Configuration

```yaml
paths:
  root: "./dfp-demo"
  data:
    root: "${paths.root}/data"
    raw: "${paths.data.root}/raw"
    processed: "${paths.data.root}/processed"
    models: "${paths.data.root}/models"
    output: "${paths.data.root}/output"
  mlflow:
    artifacts: "${paths.data.root}/mlflow"
  logs: "${paths.root}/logs"
  configs: "${paths.root}/config"
```

**Path Variables:**

- Use `${paths.root}` to reference root directory
- All paths support variable interpolation
- Relative paths are resolved from project root

### Resource Limits

```yaml
resources:
  max_memory_gb: 0 # 0 = unlimited
  auto_batch_size: true # Automatically adjust batch size
  profile_memory: false # Enable memory profiling
```

### Kafka Configuration

```yaml
kafka:
  bootstrap_servers: "127.0.0.1:29092"

  topics:
    input: "dfp-events"
    output: "dfp-detections"
    control: "control-messages"

  consumer:
    group_id: "morpheus-dfp-inference"
    auto_offset_reset: "latest"
    enable_auto_commit: true
    poll_interval: "10millis"

  producer:
    acks: "1"
    compression_type: "gzip"
    async_commits: true
```

**Important Notes:**

- Use `127.0.0.1` instead of `localhost` to avoid IPv6 issues
- `poll_interval` follows pandas Timedelta format
- `auto_offset_reset="latest"` means only consume new events (NVIDIA default)

## Pipeline Configuration

**File:** `pipeline.yaml`

**Purpose:** Pipeline-specific settings for integrated batch execution.

### Pipeline Settings

```yaml
pipeline:
  name: "dfp_integrated_batch"
  type: "integrated_batch"
  description: "NVIDIA DFP integrated batch pipeline"
```

### DFP Configuration

Critical settings for Digital Fingerprinting behavior:

```yaml
dfp:
  userid_column: "username"
  timestamp_column: "timestamp"

  preprocessing:
    schema_file: "config/feature_schema.yaml"
    feature_set: "default"
    fill_missing: true
    normalize: true
    enable_geographic_features: true
    min_distance_for_travel_km: 500
```

#### Training Path Configuration

```yaml
dfp:
  training:
    min_history: 300 # Minimum events required for training
    min_increment: 300 # Minimum new events to trigger retraining
    max_history: "60d" # Training window (60 days)
    cache_mode: "aggregate" # Accumulate cache statistics
    cache_dir: ".cache/demo" # Cache directory
    timestamp_column: "timestamp"
```

**Parameter Guide:**

- **min_history**: Minimum number of events per user before training a model
  - Recommendation: 300-500 for stable models
  - Lower values may result in overfitting
- **min_increment**: Minimum new events required to retrain an existing model
  - Recommendation: Match `min_history` for consistency
  - Higher values reduce retraining frequency
- **max_history**: Maximum time window for training data
  - Format: Pandas Timedelta string ("60d", "24h", "1w")
  - Limits memory usage and focuses on recent behavior
- **cache_mode**: Cache behavior for rolling window
  - `aggregate`: Accumulate statistics (populates `last_train_count`)
  - `batch`: Read from cache and flush at end
  - Training MUST use `aggregate`, inference MUST use `batch`
- **enable_geographic_features**: Enable geographic feature engineering
  - `true`: Calculate distance_km, ts_delta_hour, travel_speed_kmph features
  - `false`: Skip geographic feature calculation
  - Note: travel_speed_kmph is INCLUDED in AutoEncoder training (model learns normal patterns per user, typically 0-100 km/h)
  - Note: distance_km and ts_delta_hour are EXCLUDED from training (metadata only)
- **min_distance_for_travel_km**: Minimum distance for meaningful travel features
  - Default: 500 km (ignore local travel, focus on significant movement)
  - Used to filter which events contribute to travel velocity statistics

#### Inference Path Configuration

```yaml
dfp:
  inference:
    min_history: 1 # Accept any events (no minimum)
    min_increment: 0 # No increment requirement
    max_history: "1d" # Inference window (1 day)
    cache_mode: "batch" # Read cache, flush at end
    cache_dir: ".cache/demo" # MUST match training cache_dir
    timestamp_column: "timestamp"
```

**Critical:**

- `cache_dir` MUST match training configuration
- `cache_mode="batch"` reads `last_train_count` from training cache
- Shorter `max_history` reduces memory usage during inference

### Training Configuration

Model training hyperparameters:

```yaml
training:
  epochs: 100
  validation_size: 0.1
  min_training_samples: 100
  use_val_for_loss_stats: true
  seed: 42

  model_kwargs:
    encoder_layers: [512, 500]
    decoder_layers: [512]
    activation: "relu"
    swap_probability: 0.2
    learning_rate: 0.01
    learning_rate_decay: 0.99
    batch_size: 512
    eval_batch_size: 1024
    optimizer: "sgd"
    scaler: "standard"
    loss_scaler: "standard"
    patience: 5
```

**Parameter Guide:**

- **epochs**: Number of training iterations
  - Higher = better model, longer training
  - Recommendation: 50-100 for most cases
- **validation_size**: Fraction of data for validation
  - Range: 0.05-0.2
  - Used for early stopping and loss statistics
- **encoder_layers**: Neural network encoder architecture
  - NVIDIA default: [512, 500]
  - Deeper networks = more capacity, slower training
- **decoder_layers**: Neural network decoder architecture
  - NVIDIA default: [512]
  - Should mirror encoder (reversed)
- **learning_rate**: SGD optimizer learning rate
  - NVIDIA default: 0.01
  - Lower = more stable, slower convergence
- **batch_size**: Training batch size
  - Larger = faster training, more memory
  - Recommendation: 256-512 CPU, 1024-2048 GPU
- **patience**: Early stopping patience (epochs)
  - Stop if validation loss doesn't improve for N epochs

### Inference Configuration

Anomaly detection settings:

```yaml
inference:
  batch_size: 64

  anomaly_threshold:
    type: "z_score"
    value: 2.0
    adaptive: false

  model_selection:
    prefer_user_specific: true
    fallback_to_generic: true
    version: "latest"
    stage: null

  output:
    format: "csv"
    include_all_rows: false
    include_details: true
    include_model_metadata: true
    compression: null
```

**Parameter Guide:**

- **anomaly_threshold.type**: Threshold method
  - `z_score`: Standard deviations from mean (recommended)
  - `percentile`: Percentile-based threshold
  - `absolute`: Absolute reconstruction error threshold
- **anomaly_threshold.value**: Threshold value
  - For z_score: 2.0 = 2 standard deviations (99.7% of normal data)
  - NVIDIA target: ~11% detection rate with z=2.0
  - Lower values = more detections, higher false positive rate
- **model_selection.prefer_user_specific**: Try user model first
  - true: Load DFP-{username} if available
  - false: Always use generic model
- **model_selection.fallback_to_generic**: Use generic if user model missing
  - true: Load DFP-generic as fallback (recommended)
  - false: Fail if user model not found
- **output.include_all_rows**: Include non-anomalies in output
  - false: Only output anomalies (recommended)
  - true: Output all events with anomaly scores

### MLflow Configuration

Model registry settings:

```yaml
mlflow:
  tracking_uri: "http://localhost:5001"
  experiment_name: "dfp/demo-pipeline"
  model_name_formatter: "DFP-{user_id}"
  per_user_models: true
  incremental_training: true

  retention:
    keep_versions: 7
    cleanup_days: 30
```

**Parameter Guide:**

- **model_name_formatter**: Model naming pattern
  - `{user_id}` is replaced with actual username
  - Example: "DFP-user123", "DFP-generic"
- **incremental_training**: Enable incremental model updates
  - true: Load v1 → train → save v2
  - false: Always train from scratch

### Feature Columns

List of features produced by preprocessing:

```yaml
feature_columns:
  - "appDisplayName"
  - "clientAppUsed"
  - "deviceDetailbrowser"
  - "deviceDetaildisplayName"
  - "deviceDetailoperatingSystem"
  - "statusfailureReason"
  - "appincrement"
  - "locincrement"
  - "logcount"
```

**Important:**

- Must match output of `DFPPreprocessing` module
- Order matters for model compatibility
- Defined in `feature_schema.yaml`

## Feature Schema

**File:** `feature_schema.yaml`

**Purpose:** Defines feature engineering transformations and feature sets.

### Structure

```yaml
metadata:
  version: "2.0"
  description: "Azure AD Log Feature Schema"
  author: "Tomasz Zabek <tzabek@deloitte.co.uk>"

columns:
  # Column definitions
  timestamp:
    type: "datetime"
    input_column: "timestamp"
    # ... transformation details

  username:
    type: "string"
    input_column: "username"
    # ... transformation details

features:
  default:
    description: "NVIDIA standard feature set"
    columns:
      - "logcount"
      - "locincrement"
      - ...

preprocessing:
  # Preprocessing configuration
  fill_missing: true
  fill_value: 0
  normalize: true
```

**Key Sections:**

1. **columns**: Column-level transformations
   - Type conversion
   - Feature extraction
   - Encoding strategies
2. **features**: Feature set definitions
   - `default`: NVIDIA standard features
   - Can define custom feature sets
3. **preprocessing**: Preprocessing directives
   - Missing value handling
   - Normalization settings

See [Feature Schema Documentation](feature_schema.yaml) for complete reference (1,026 lines).

## MLflow Main Configuration

**File:** `mlflow.yaml`

**Purpose:** MLflow tracking server and model registry configuration.

### Server Configuration

```yaml
server:
  tracking_uri: "http://localhost:5001"
  backend_store_uri: "sqlite:///./data/mlflow/mlflow.db"
  default_artifact_root: "./data/mlflow"
  host: "127.0.0.1"
  port: 5001
  auth_enabled: false
  timeout: 300
```

### Experiment Configuration

```yaml
experiments:
  training:
    name: "dfp_training"
    description: "DFP training experiments"
    tags:
      project: "morpheus-dfp-demo"
      pipeline: "training"

  inference:
    name: "dfp_inference"
    description: "DFP inference experiments"
    tags:
      project: "morpheus-dfp-demo"
      pipeline: "inference"
```

### Model Registry

```yaml
model_registry:
  model_name: "dfencoder_dfp"
  model_description: "DFEncoder AutoEncoder for DFP"
  default_tags:
    framework: "pytorch"
    model_type: "autoencoder"

  stages:
    - "None"
    - "Staging"
    - "Production"
    - "Archived"

  auto_register: true
  auto_stage_transition: false
  use_aliases: true
```

### Training Metrics

```yaml
training:
  log_frequency: 1
  metrics:
    - "train_loss"
    - "val_loss"
    - "learning_rate"
    - "reconstruction_error_mean"
    - ...

  parameters:
    - "epochs"
    - "batch_size"
    - "learning_rate"
    - ...

  artifacts:
    - "model"
    - "training_plots"
    - "baseline_statistics"
    - ...
```

## Logging Configuration

**File:** `logging.yaml`

**Purpose:** Structured logging configuration for all modules.

### Log Levels

```bash
TRACE: 5      # Very detailed debugging
VERBOSE: 15   # Between DEBUG and INFO
DEBUG: 10     # Debugging information
INFO: 20      # General information
NOTICE: 25    # Between INFO and WARNING
WARNING: 30   # Warning messages
ERROR: 40     # Error messages
CRITICAL: 50  # Critical errors
SUCCESS: 35   # Between WARNING and ERROR
```

### Handlers

```yaml
handlers:
  console:
    class: logging.StreamHandler
    level: INFO
    formatter: colored

  file_all:
    class: logging.handlers.RotatingFileHandler
    level: DEBUG
    formatter: detailed
    filename: ./dfp-demo/logs/dfp_all.log
    maxBytes: 10485760 # 10MB
    backupCount: 5
```

### Loggers

```yaml
loggers:
  dfp.training:
    level: DEBUG
    handlers:
      - console
      - file_training

  dfp.inference:
    level: DEBUG
    handlers:
      - console
      - file_inference
```

## Variable Interpolation

OmegaConf supports variable interpolation using `${...}` syntax:

### Basic Interpolation

```yaml
paths:
  root: "./dfp-demo"
  data: "${paths.root}/data"
  raw: "${paths.data}/raw"
```

Result: `paths.raw = "./dfp-demo/data/raw"`

### Nested Interpolation

```yaml
project:
  name: "morpheus-dfp"

mlflow:
  experiment_name: "${project.name}/training"
```

Result: `mlflow.experiment_name = "morpheus-dfp/training"`

### Environment Variables

```yaml
mlflow:
  tracking_uri: "${oc.env:MLFLOW_TRACKING_URI,http://localhost:5001}"
```

Uses environment variable `MLFLOW_TRACKING_URI` if set, otherwise defaults to `http://localhost:5001`.

### Conditional Values

```yaml
execution:
  device: "${oc.select:cuda,cpu}" # Select first available
```

## Main Environment Variables

Override configuration via environment variables:

### MLflow

```bash
export MLFLOW_TRACKING_URI="http://mlflow-server:5000"
export MLFLOW_EXPERIMENT_NAME="production/dfp"
```

### Device Selection

```bash
export DEVICE="cuda"               # Force CUDA
export CUDA_VISIBLE_DEVICES="0,1"  # Use specific GPUs
```

### Paths

```bash
export DATA_ROOT="/mnt/data/dfp"
export CACHE_DIR="/tmp/dfp-cache"
```

### Logging

```bash
export LOG_LEVEL="DEBUG"
export LOG_FILE="/var/log/dfp/pipeline.log"
```

## Configuration Patterns

### Pattern 1: Development vs Production

**Development:**

```yaml
# config/dev.yaml
execution:
  device: "cpu"
  verbose: true
  dry_run: false

training:
  epochs: 10 # Quick training

mlflow:
  tracking_uri: "http://localhost:5001"
```

**Production:**

```yaml
# config/prod.yaml
execution:
  device: "cuda"
  verbose: false
  dry_run: false

training:
  epochs: 100 # Full training

mlflow:
  tracking_uri: "http://mlflow-prod:5000"
```

### Pattern 2: Per-Environment Configuration

```yaml
# config/pipeline.yaml
defaults:
  - base_config
  - ${environment} # Load environment-specific config

execution:
  device: "auto"
```

Then:

```bash
# Development
ENVIRONMENT=dev python pipelines/pipeline.py ...

# Production
ENVIRONMENT=prod python pipelines/pipeline.py ...
```

### Pattern 3: User-Specific Overrides

```yaml
# config/user_overrides.yaml
training:
  epochs: 50

inference:
  anomaly_threshold:
    value: 2.5
```

Load with:

```bash
python pipelines/pipeline.py \
    --config config/pipeline.yaml \
    --config config/user_overrides.yaml
```

## Validation

### Schema Validation

Configuration is validated on load:

```python
from modules.utils import ConfigLoader

try:
    config = ConfigLoader.load("config/pipeline.yaml")
except ValueError as e:
    print(f"Configuration error: {e}")
```

### Required Fields

Critical fields that must be present:

**Pipeline:**

- `dfp.userid_column`
- `dfp.timestamp_column`
- `feature_columns`

**Training:**

- `training.epochs`
- `training.model_kwargs`

**Inference:**

- `inference.anomaly_threshold`

### Type Validation

OmegaConf validates types automatically:

```yaml
training:
  epochs: 100 # Must be int
  learning_rate: 0.01 # Must be float
  feature_columns: [] # Must be list
```

## Troubleshooting

### Issue: Variable Interpolation Error

**Error:**

```text
omegaconf.errors.InterpolationKeyError: Interpolation key 'paths.root' not found
```

**Solution:**
Ensure referenced variable is defined before use:

```yaml
# Wrong order
data_path: "${paths.root}/data"
paths:
  root: "./dfp-demo"

# Correct order
paths:
  root: "./dfp-demo"
data_path: "${paths.root}/data"
```

### Issue: Configuration Override Not Working

**Problem:**
Command-line argument doesn't override config file value

**Solution:**
Use dotted notation for nested overrides:

```bash
# Wrong
python pipeline.py --config pipeline.yaml --epochs 50

# Correct
python pipeline.py \
    --config pipeline.yaml \
    training.epochs=50
```

### Issue: Missing Configuration File

**Error:**

```text
FileNotFoundError: config/pipeline.yaml not found
```

**Solution:**
Use absolute path or ensure working directory is correct:

```bash
cd /path/to/dfp-demo
python pipelines/pipeline.py --config config/pipeline.yaml
```

Or use absolute path:

```bash
python pipelines/pipeline.py \
    --config /absolute/path/to/config/pipeline.yaml
```

### Issue: Invalid YAML Syntax

**Error:**

```text
yaml.scanner.ScannerError: while scanning for the next token
```

**Solution:**
Check YAML syntax:

- Consistent indentation (2 or 4 spaces, not tabs)
- Quoted strings with special characters
- No duplicate keys

Use YAML validator:

```bash
yamllint config/pipeline.yaml
```

## Configuration Best Practices

### 1. Use Variable Interpolation

Avoid duplication:

```yaml
# Bad
paths:
  raw: "./dfp-demo/data/raw"
  processed: "./dfp-demo/data/processed"

# Good
paths:
  root: "./dfp-demo"
  data: "${paths.root}/data"
  raw: "${paths.data}/raw"
  processed: "${paths.data}/processed"
```

### 2. Document Parameters

Add comments explaining non-obvious parameters:

```yaml
training:
  epochs: 100 # Number of training iterations
  patience: 5 # Early stopping patience (epochs without improvement)
```

### 3. Use Sensible Defaults

Provide defaults that work for most cases:

```yaml
execution:
  device: "auto" # Auto-detect best device
  verbose: true # Helpful for development
```

### 4. Validate Critical Settings

Add validation in code:

```python
assert config.dfp.training.cache_mode == "aggregate"
assert config.dfp.inference.cache_mode == "batch"
assert config.dfp.training.cache_dir == config.dfp.inference.cache_dir
```

### 5. Version Configurations

Track configuration changes:

```yaml
metadata:
  version: "2.0"
  last_updated: "2025-11-20"
  changelog: "Added Kafka streaming support"
```

## Additional Resources

- [OmegaConf Documentation](https://omegaconf.readthedocs.io/)
- [YAML Specification](https://yaml.org/spec/)
- [Module Documentation](../modules/README.md)
- [Pipeline Documentation](../pipelines/README.md)

---

**Last Updated:** November 2025
**Version:** 0.1.0
**Author:** Tomasz Zabek <tzabek@deloitte.co.uk>
**Generated By:** Claude Sonnet 4.5
