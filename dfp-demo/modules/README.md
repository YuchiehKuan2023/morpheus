# DFP Modules Documentation

This directory contains all modular components for the Digital Fingerprinting Proof of Concept, organized following NVIDIA Morpheus DFP architecture patterns.

## Table of Contents

- [Module Overview](#module-overview)
- [Architecture](#architecture)
- [Module Descriptions](#module-descriptions)
- [Usage Patterns](#usage-patterns)
- [Extension Guide](#extension-guide)
- [API Documentation](#api-documentation)

## API Documentation

Comprehensive API documentation is available via the documentation server:

**Start Documentation Server:**

```bash
# Automatically started with services
./services/start_services.sh

# Or manually
cd docs && ./serve.sh
```

**Access Documentation:**

- **API Reference**: <http://localhost:8888>
- **Module Documentation**: <http://localhost:8888/api/>
- **Examples**: <http://localhost:8888/examples.html>
- **Architecture**: <http://localhost:8888/architecture.html>

The documentation includes:

- Complete API reference for all modules
- Type hints and parameter descriptions
- Usage examples for key functions
- Module architecture diagrams
- Configuration guides

## Module Overview

The modules are organized into logical packages, each handling a specific aspect of the DFP pipeline:

| Package          | Purpose                    | Key Components                                 | Lines of Code |
| ---------------- | -------------------------- | ---------------------------------------------- | ------------- |
| `control/`       | Control message routing    | ControlMessage, MessageRouter                  | ~1,100        |
| `dfencoder/`     | AutoEncoder implementation | AutoEncoder, AEModule, DataLoader              | ~3,500        |
| `preprocessing/` | Data transformation        | DFPPreprocessing, RollingWindow, UserSplitter  | ~2,000        |
| `training/`      | Model training             | DFPTrainer, MLflowModelWriter, Evaluator       | ~2,300        |
| `inference/`     | Anomaly detection          | DFPInference, FilterDetections                 | ~2,200        |
| `io/`            | Data I/O operations        | FileBatcher, KafkaConsumer, KafkaProducer      | ~1,800        |
| `utils/`         | Shared utilities           | Config, Logging, MLflow, Environment           | ~2,400        |

**Total:** ~15,300 lines of production code

## Architecture

### Data Flow

```text
Raw Data
    |
    v
[IO Modules] ---------> Read files, Kafka streams
    |
    v
[Preprocessing] ------> Extract features, normalize
    |
    v
[Control Router] -----> Route to training or inference
    |
    +---> [Training Path]
    |         |
    |         v
    |     [DFP Trainer] --> Train AutoEncoder
    |         |
    |         v
    |     [MLflow Writer] -> Save model
    |
    +---> [Inference Path]
              |
              v
          [DFP Inference] -> Load model, score
              |
              v
          [Filter Detections] -> Apply threshold
              |
              v
          [Serialization] -> Output results
```

### Module Dependencies

```text
dfencoder (base)
    ^
    |
training (uses dfencoder)
    ^
    |
inference (uses dfencoder, training outputs)
    ^
    |
preprocessing (prepares data for training/inference)
    ^
    |
io (loads/saves data)
    ^
    |
control (routes data through pipeline)
    ^
    |
utils (supports all modules)
```

## Module Descriptions

### 1. Control Package (`control/`)

**Purpose:** Implements NVIDIA's control message system for routing data between training and inference paths.

**Key Components:**

- **ControlMessage** (`control_message.py`)

  - Core data structure for pipeline communication
  - Carries task type, metadata, and payload
  - Supports training and inference tasks
  - Thread-safe payload management

- **MessageRouter** (`message_router.py`)
  - Routes messages based on task type
  - Validates message structure
  - Handles error cases

**Usage Example:**

```python
from modules.control import ControlMessage, ControlMessageType

# Create training message
msg = ControlMessage()
msg.set_metadata("user_id", "user123")
msg.set_metadata("model_name", "DFP-user123")
msg.task_type = ControlMessageType.TRAINING
msg.payload = training_data

# Route message
pipeline = route_message(msg)
```

**NVIDIA Reference:**

- `morpheus/messages/control_message.py`
- `morpheus_dfp/modules/dfp_deployment.py`

---

### 2. DFEncoder Package (`dfencoder/`)

**Purpose:** NVIDIA's AutoEncoder implementation for unsupervised anomaly detection.

**Key Components:**

- **AutoEncoder** (`autoencoder.py`)

  - Main AutoEncoder model class
  - Handles numerical and categorical features
  - Computes reconstruction error for anomaly scoring
  - Methods: `fit()`, `predict()`, `get_results()`

- **AEModule** (`ae_module.py`)

  - Neural network architecture
  - Encoder/decoder layers with embeddings
  - Swap-noise injection for denoising

- **DataLoader** (`dataloader.py`)

  - Custom DataLoader for AutoEncoder training
  - Handles mixed numerical/categorical data
  - Supports file-based and DataFrame datasets

- **Scalers** (`scalers.py`)
  - Data normalization: StandardScaler, GaussRankScaler
  - Feature scaling for neural network input

**Usage Example:**

```python
from modules.dfencoder import AutoEncoder

# Create and train model
model = AutoEncoder(
    encoder_layers=[512, 500],
    decoder_layers=[512],
    activation='relu',
    learning_rate=0.01
)

model.fit(
    X=training_data,
    epochs=100,
    batch_size=512
)

# Compute anomaly scores
results = model.get_results(test_data)
# Returns: DataFrame with reconstruction errors and z-scores
```

**NVIDIA Reference:**

- `morpheus/models/dfencoder/`

---

### 3. Preprocessing Package (`preprocessing/`)

**Purpose:** Transforms raw Azure AD logs into model-ready features.

**Key Components:**

- **DFPPreprocessing** (`dfp_preprocessing.py`)

  - Main preprocessing orchestrator
  - Schema-based feature extraction
  - Temporal feature engineering
  - Missing value imputation

- **GeographicFeatures** (`geographic_features.py`)

  - Geographic feature engineering for travel pattern analysis
  - Haversine distance calculation between consecutive events
  - Time delta and travel velocity computation
  - Key features:
    - `distance_km`: Haversine distance (excluded from training, metadata only)
    - `ts_delta_hour`: Time between events (excluded from training, metadata only)
    - `travel_speed_kmph`: Travel velocity (INCLUDED in training, AutoEncoder learns patterns)
  - Note: travel_speed_kmph is included in model training, allowing AutoEncoder to learn normal travel patterns per user (typically 0-100 km/h)

- **RollingWindow** (`rolling_window.py`)

  - Time-based window aggregation
  - Per-user history management
  - Cached window storage
  - Supports aggregate and batch modes

- **UserSplitter** (`user_splitting.py`)

  - Splits data by user_id
  - Filters users by minimum sample count
  - Produces per-user DataFrames

- **DataPrep** (`data_prep.py`)

  - Final data preparation for model input
  - Feature selection and ordering
  - Normalization (if enabled)
  - Train/validation splitting

- **ColumnInfo** (`column_info.py`)

  - Column transformation definitions
  - DateTime parsing
  - Categorical encoding
  - Increment feature calculation

- **SchemaBuilder** (`schema_builder.py`)
  - Builds preprocessing schema from YAML
  - Extracts feature columns
  - Manages feature dependencies

**Usage Example:**

```python
from modules.preprocessing import DFPPreprocessing, RollingWindow

# Initialize preprocessing
preprocessor = DFPPreprocessing({
    "schema_file": "config/feature_schema.yaml",
    "feature_set": "default",
    "fill_missing": True
})

# Process data
df_processed = preprocessor.preprocess(df_raw)

# Apply rolling window
rolling_window = RollingWindow(
    min_history=300,
    max_history="60d",
    cache_dir=".cache/dfp"
)

df_windowed = rolling_window.process(df_processed, user_id="user123")
```

**NVIDIA Reference:**

- `morpheus_dfp/stages/dfp_preprocessing_stage.py`
- `morpheus_dfp/stages/dfp_rolling_window_stage.py`

---

### 4. Training Package (`training/`)

**Purpose:** Trains per-user AutoEncoder models and saves to MLflow.

**Key Components:**

- **DFPTrainer** (`dfp_trainer.py`)

  - Core training logic
  - Per-user model training
  - Generic model training (fallback)
  - Train/validation splitting
  - Integration with ControlMessage

- **DFPAutoEncoder** (`autoencoder_wrapper.py`)

  - Wrapper around dfencoder.AutoEncoder
  - Simplified interface for DFP use case
  - Configuration management
  - Device handling (CPU/GPU)

- **MLflowModelWriter** (`mlflow_model_writer.py`)

  - Saves trained models to MLflow Registry
  - Logs training metrics and parameters
  - Stores baseline statistics
  - Handles model versioning

- **TrainingEvaluator** (`evaluation.py`)
  - Computes baseline statistics for anomaly detection
  - Calculates reconstruction error distribution
  - Provides normalization parameters (mean, std)

**Usage Example:**

```python
from modules.training import DFPTrainer
from modules.control import ControlMessage

# Initialize trainer
trainer = DFPTrainer({
    "model": {
        "encoder_layers": [512, 500],
        "decoder_layers": [512]
    },
    "training": {
        "epochs": 100,
        "validation_size": 0.1
    },
    "features": {
        "feature_columns": ["logcount", "locincrement", ...]
    }
})

# Train from control message
output_msg = trainer.train(control_message)

# Access trained model
model = output_msg.get_metadata("model")
```

**NVIDIA Reference:**

- `morpheus_dfp/modules/dfp_training.py`
- `morpheus/modules/mlflow_model_writer.py`

---

### 5. Inference Package (`inference/`)

**Purpose:** Loads models and performs DFP behavioral anomaly detection with FilterDetections binary filtering.

**Key Components:**

- **DFPInference** (`dfp_inference.py`)

  - DFP AutoEncoder behavioral anomaly detection
  - Trained on behavioral + geographic features (including travel_speed_kmph)
  - Loads models from MLflow Registry
  - Computes reconstruction errors for all features
  - Calculates z-scores for anomaly detection
  - Supports user-specific and generic models
  - Model caching for performance

- **FilterDetections** (`filter_detections.py`)

  - NVIDIA standard binary filtering module
  - Applies threshold filtering (mean_abs_z > 2.0, configurable)
  - Returns None if no anomalies exceed threshold
  - Generates comprehensive detection messages:
    - features: Array of all features with {feature, z_score, value}
    - top_features: Top 3 features in "feature=value (z=score)" format
    - timestamp, anomaly_score, max_abs_z, feature_count
  - Configurable filtering strategies

- **DFPPostProcessing** (`postprocessing.py`)

  - Enriches detections with metadata
  - Adds model version information
  - Computes summary statistics
  - Formats output for downstream systems

- **DFPSerializer** (`serialization.py`)
  - Serializes results to multiple formats
  - Supports CSV, JSON, JSONLines
  - Configurable output options
  - Compression support

**Usage Example:**

```python
from modules.inference import DFPInference, FilterDetections

# Initialize inference
inference = DFPInference({
    "mlflow": {
        "tracking_uri": "http://localhost:5001",
        "model_name_formatter": "DFP-{user_id}"
    },
    "fallback_username": "generic"
})

# Run inference
results_msg = inference.infer(control_message)

# Filter detections with binary filtering
filter_stage = FilterDetections({
    "detection_criteria": {
        "field_name": "mean_abs_z",
        "threshold": 2.0
    }
})

detections = filter_stage.filter(results_msg)
# Returns comprehensive detection messages with all feature details
# Returns None if no anomalies exceed threshold
```

**NVIDIA Reference:**

- `morpheus_dfp/modules/dfp_inference.py`
- `morpheus/modules/filter_detections.py`

---

### 6. IO Package (`io/`)

**Purpose:** Handles data input/output operations.

**Key Components:**

- **FileBatcher** (`file_batcher.py`)

  - Batches files by time period
  - Timestamp extraction from filenames
  - Sampling strategies (frequency, fraction, count)
  - Time window filtering

- **FileToDataFrame** (`file_to_df.py`)

  - Loads files into pandas DataFrames
  - Supports JSON, CSV, Parquet
  - Schema validation
  - Batch processing

- **DataFrameToOutput** (`df_to_output.py`)

  - Writes DataFrames to files
  - Multiple format support
  - Append or overwrite modes
  - Directory creation

- **DFPKafkaConsumer** (`kafka_consumer.py`)

  - Consumes events from Kafka topics
  - JSON deserialization
  - Batch consumption
  - Error handling

- **DFPKafkaProducer** (`kafka_producer.py`)
  - Produces events to Kafka topics
  - JSON serialization
  - Async sending
  - Retry logic

**Usage Example:**

```python
from modules.io import FileBatcher, FileToDataFrame

# Batch files by day
batcher = FileBatcher(
    period="D",
    sampling="12H",
    start_time="2025-01-01",
    end_time="2025-01-31"
)

file_batches = batcher.batch_files(
    files=glob("data/raw/*.json")
)

# Load batch
loader = FileToDataFrame(file_type="json")
df = loader.load_batch(file_batches[0])
```

**NVIDIA Reference:**

- `morpheus/modules/file_batcher.py`
- `morpheus/modules/file_to_df.py`

---

### 7. Utils Package (`utils/`)

**Purpose:** Shared utilities used across all modules.

**Key Components:**

- **ConfigLoader** (`config_utils.py`)

  - Loads YAML configurations with OmegaConf
  - Supports variable interpolation
  - Configuration merging
  - Validation

- **LoggingUtils** (`logging_utils.py`)

  - Structured logging setup
  - Module-specific loggers
  - Performance timing decorators
  - Context logging

- **MLflowManager** (`mlflow_utils.py`)

  - MLflow experiment management
  - Run tracking
  - Model logging helpers
  - Artifact management

- **EnvironmentUtils** (`environment_utils.py`)

  - Device detection (CPU/CUDA/MPS)
  - System information
  - Memory checks
  - PyTorch configuration

- **CachedUserWindow** (`cached_user_window.py`)
  - Per-user data caching
  - Disk-based persistence
  - History management
  - Cache flushing

**Usage Example:**

```python
from modules.utils import ConfigLoader, setup_logging, MLflowManager

# Load configuration
config = ConfigLoader.load("config/pipeline.yaml")

# Setup logging
setup_logging(config.logging)

# Initialize MLflow
mlflow_manager = MLflowManager(
    tracking_uri=config.mlflow.tracking_uri,
    experiment_name=config.mlflow.experiment_name
)
```

---

## Usage Patterns

### Pattern 1: Training Pipeline

```python
# 1. Load and preprocess data
from modules.io import FileToDataFrame
from modules.preprocessing import DFPPreprocessing, UserSplitter, RollingWindow

loader = FileToDataFrame(file_type="json")
df_raw = loader.load("data/raw/training_data.json")

preprocessor = DFPPreprocessing(config["preprocessing"])
df_processed = preprocessor.preprocess(df_raw)

splitter = UserSplitter(config["dfp"])
user_dfs = splitter.split(df_processed)

# 2. Apply rolling window per user
rolling_window = RollingWindow(config["dfp"]["training"])
for user_id, user_df in user_dfs.items():
    windowed_df = rolling_window.process(user_df, user_id)

    # 3. Train model
    from modules.training import DFPTrainer, MLflowModelWriter

    trainer = DFPTrainer(config)
    control_msg = create_training_message(
        user_id=user_id,
        data=windowed_df
    )

    trained_msg = trainer.train(control_msg)

    # 4. Save to MLflow
    writer = MLflowModelWriter(config["mlflow"])
    writer.write(trained_msg)
```

### Pattern 2: Inference Pipeline

```python
# 1. Load and preprocess data
from modules.io import FileToDataFrame
from modules.preprocessing import DFPPreprocessing, RollingWindow

loader = FileToDataFrame(file_type="json")
df_raw = loader.load("data/raw/inference_data.json")

preprocessor = DFPPreprocessing(config["preprocessing"])
df_processed = preprocessor.preprocess(df_raw)

# 2. Apply rolling window
rolling_window = RollingWindow(config["dfp"]["inference"])
df_windowed = rolling_window.process(df_processed, user_id)

# 3. Run inference
from modules.inference import DFPInference, FilterDetections, DFPSerializer

inference = DFPInference(config)
control_msg = create_inference_message(
    user_id=user_id,
    data=df_windowed
)

results_msg = inference.infer(control_msg)

# 4. Filter and serialize
filter_stage = FilterDetections(config["inference"])
detections = filter_stage.filter(results_msg)

serializer = DFPSerializer(config["output"])
serializer.to_csv(detections, "output/detections.csv")
```

### Pattern 3: Integrated Pipeline

```python
# Single process with shared cache
from modules.control import MessageRouter

router = MessageRouter(config)

# Process training messages
for train_msg in training_messages:
    router.route(train_msg)  # -> Training path

# Process inference messages (uses training cache)
for infer_msg in inference_messages:
    router.route(infer_msg)  # -> Inference path

# Cache is shared, last_train_count preserved
```

## Extension Guide

### Adding a New Preprocessing Step

**1. Create module in `preprocessing/`:**

```python
# modules/preprocessing/custom_feature.py

class CustomFeatureExtractor:
    """Extract custom behavioral features."""

    def __init__(self, config: dict):
        self.config = config

    def extract(self, df: pd.DataFrame) -> pd.DataFrame:
        # Add custom features
        df["custom_feature"] = ...
        return df
```

**2. Update `DFPPreprocessing` to include new step:**

```python
# In dfp_preprocessing.py
from modules.preprocessing.custom_feature import CustomFeatureExtractor

class DFPPreprocessing:
    def preprocess(self, df: pd.DataFrame) -> pd.DataFrame:
        # ... existing steps ...

        # Add custom feature extraction
        extractor = CustomFeatureExtractor(self.config)
        df = extractor.extract(df)

        return df
```

**3. Add configuration:**

```yaml
# config/feature_schema.yaml
custom_features:
  enabled: true
  feature_name: "custom_feature"
  parameters:
    param1: value1
```

### Adding a New Anomaly Detection Method

**1. Create module in `inference/`:**

```python
# modules/inference/custom_detector.py

class CustomAnomalyDetector:
    """Custom anomaly detection algorithm."""

    def __init__(self, config: dict):
        self.threshold = config.get("threshold", 0.5)

    def detect(self, df: pd.DataFrame) -> pd.DataFrame:
        # Implement detection logic
        df["is_anomaly"] = df["score"] > self.threshold
        return df
```

**2. Integrate with `DFPInference`:**

```python
# In dfp_inference.py
def infer(self, control_message: ControlMessage):
    # ... existing inference ...

    # Apply custom detector
    if self.config.get("use_custom_detector"):
        detector = CustomAnomalyDetector(self.config["custom_detector"])
        results = detector.detect(results)

    return results
```

### Adding a New Output Format

**1. Extend `DFPSerializer`:**

```python
# In serialization.py
class DFPSerializer:
    def to_parquet(
        self,
        df: pd.DataFrame,
        output_path: str,
        compression: str = "snappy"
    ):
        """Serialize to Parquet format."""
        df.to_parquet(
            output_path,
            compression=compression,
            index=False
        )
```

**2. Add configuration:**

```yaml
# config/pipeline.yaml
output:
  format: "parquet"
  compression: "snappy"
```

## Testing

Each module has corresponding unit tests in `tests/`:

```bash
# Test preprocessing
pytest tests/test_preprocessing/ -v

# Test training
pytest tests/test_training/ -v

# Test inference
pytest tests/test_inference/ -v
```

## Performance Considerations

### Memory Optimization

- Use `RollingWindow` cache mode appropriately:
  - `aggregate`: For training (accumulates history)
  - `batch`: For inference (flushes after use)

### GPU Acceleration

- Set `device="cuda"` in configuration
- AutoEncoder automatically uses GPU if available
- Preprocessing remains on CPU (pandas-based)

### Batch Processing

- Adjust `batch_size` based on available memory
- Larger batches = better GPU utilization
- Smaller batches = lower memory usage

## Troubleshooting

### Common Issues

**Issue: Cache cold start (increment features = 0):**

Solution: Use integrated pipeline or `cache_mode="aggregate"`

**Issue: Model not found in MLflow:**

Solution: Verify model name format matches `model_name_formatter`

**Issue: Out of memory during training:**

Solution: Reduce `batch_size` or enable `auto_batch_size`

**Issue: Slow preprocessing:**

Solution: Increase `num_workers` or enable GPU preprocessing (RAPIDS)

## Further Reading

- [Pipeline Documentation](../pipelines/README.md)
- [Configuration Guide](../config/README.md)
- [NVIDIA Morpheus DFP Guide](https://docs.nvidia.com/morpheus/developer_guide/guides/5_digital_fingerprinting.html)

---

**Last Updated:** November 2025
**Version:** 0.1.0
**Author:** Tomasz Zabek <tzabek@deloitte.co.uk>
**Generated By:** Claude Sonnet 4.5
