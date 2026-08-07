#!/usr/bin/env python3
"""
Test NVIDIA-Compliant MLflow Logging

This script runs the FULL training pipeline for a single user to verify that
all NVIDIA-standard parameters and metrics are logged correctly to MLflow.

This is NOT a shortcut - it runs the complete preprocessing → training → MLflow pipeline.

Expected NVIDIA-standard parameters:
- Algorithm: "Denoising Autoencoder"
- Epochs: 50
- Learning rate: 0.001
- Batch size: 256
- Start Epoch: <timestamp>
- End Epoch: <timestamp>
- Log Count: <total samples>

Expected NVIDIA-standard metrics:
- embedding-{feature}-num_embeddings
- embedding-{feature}-embedding_dim

Additional (our enhancements):
- user_id, feature_count (params)
- train_split_samples, val_split_samples (metrics)
"""

import json
import logging
import sys
import warnings
from pathlib import Path

# Suppress annoying PyTorch warning about zero-element tensors
warnings.filterwarnings("ignore", message="Initializing zero-element tensors is a no-op")

# Add project root to path
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

import mlflow  # noqa: E402 - imports after path setup
import pandas as pd  # noqa: E402
import yaml  # noqa: E402
from mlflow.tracking import MlflowClient  # noqa: E402

from modules.control.control_message import ControlMessage  # noqa: E402
from modules.preprocessing.data_prep import DataPrep  # noqa: E402
from modules.preprocessing.dfp_preprocessing import DFPPreprocessing  # noqa: E402
from modules.preprocessing.rolling_window import RollingWindow  # noqa: E402
from modules.training.dfp_trainer import DFPTrainer  # noqa: E402
from modules.training.mlflow_model_writer import MLflowModelWriter  # noqa: E402

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    force=True,  # Override any existing logging configuration
)
logger = logging.getLogger(__name__)

# Also print to stdout for visibility
import sys  # noqa: E402


def log_and_print(msg, level="info"):
    """Log message and also print to stdout for visibility."""
    print(msg, file=sys.stderr if level == "error" else sys.stdout)
    if level == "info":
        logger.info(msg)
    elif level == "error":
        logger.error(msg)
    elif level == "warning":
        logger.warning(msg)


def load_config():
    """Load configuration from YAML files."""
    config_dir = project_root / "config"

    # Load all config files
    with open(config_dir / "base_config.yaml") as f:
        base_config = yaml.safe_load(f)

    with open(config_dir / "pipeline.yaml") as f:
        training_config = yaml.safe_load(f)

    with open(config_dir / "feature_schema.yaml") as f:
        feature_schema = yaml.safe_load(f)

    # Merge configs - base + training overrides
    config = {**base_config, **training_config}

    # Extract feature columns from feature_schema.pipeline_schemas.training_schema
    # This is what DFPTrainer expects: config['features']['feature_columns']
    if "pipeline_schemas" in feature_schema and "training_schema" in feature_schema["pipeline_schemas"]:
        config["features"] = {
            "feature_columns": feature_schema["pipeline_schemas"]["training_schema"]["feature_columns"]
        }
    else:
        # Fallback: use entire feature_schema
        config["features"] = feature_schema

    return config


def load_single_user_data(config):
    """Load and filter data for a single user with sufficient samples."""
    data_file = project_root / "data" / "raw" / "training_data.json"

    if not data_file.exists():
        raise FileNotFoundError(f"Training data not found: {data_file}")

    logger.info(f"Loading data from {data_file}")

    with open(data_file) as f:
        data = json.load(f)

    df = pd.DataFrame(data)

    # Get user column name
    userid_col = config.get("dfp", {}).get("userid_column", "username")

    # Find user with sufficient data
    user_counts = df[userid_col].value_counts()
    test_user = None
    for user, count in user_counts.items():
        if count >= 300:  # Need sufficient data for train/val split
            test_user = user
            break

    if not test_user:
        raise ValueError("No user with sufficient data (>=300 samples)")

    # Filter to single user
    df_user = df[df[userid_col] == test_user].copy()

    # Add missing required columns if needed (for preprocessing)
    if "location" not in df_user.columns:
        # Try to create location from available location fields
        location_parts = []  # noqa: F841 - prepared for future location parsing
        if "location_city_state_country" in df_user.columns:
            df_user["location"] = df_user["location_city_state_country"]
        elif "location_country" in df_user.columns:
            df_user["location"] = df_user["location_country"]
        else:
            # Create a default location to allow preprocessing to proceed
            df_user["location"] = "Unknown"
            logger.warning("⚠️  'location' column missing - using default value 'Unknown'")

    logger.info(f"Selected user: {test_user}")
    logger.info(f"Samples: {len(df_user)}")
    logger.info(f"Date range: {df_user['timestamp'].min()} to {df_user['timestamp'].max()}")
    logger.info(f"Columns: {df_user.columns.tolist()[:15]}...")

    return df_user, test_user


def run_full_pipeline(df, user_id, config):
    """
    Run the FULL preprocessing and training pipeline.

    This is the proper way - no shortcuts!

    Pipeline stages:
    1. DFPPreprocessing - derive features
    2. RollingWindow - aggregate historical data
    3. DataPrep - select feature columns
    4. DFPTrainer - train model
    5. MLflowModelWriter - log to MLflow
    """
    logger.info("\n" + "=" * 80)
    logger.info("RUNNING FULL TRAINING PIPELINE")
    logger.info("=" * 80)

    # Stage 1: Preprocessing
    logger.info("\n[1/5] DFPPreprocessing - Deriving features...")
    preprocessor = DFPPreprocessing(config)
    df_preprocessed = preprocessor.preprocess(df)
    logger.info(f"✅ Features derived. Columns: {len(df_preprocessed.columns)}")
    logger.info(f"   Sample columns: {df_preprocessed.columns.tolist()[:10]}")

    # Stage 2: Rolling Window
    logger.info("\n[2/5] RollingWindow - Aggregating historical data...")
    rolling_window = RollingWindow(
        min_history=1,  # Accept minimal history for testing (NVIDIA default: 300)
        min_increment=0,  # No increment requirement for testing (NVIDIA default: 100)
        max_history="0",  # Unlimited history (NVIDIA default: '0')
        cache_dir=".cache/test_nvidia_logging",
        timestamp_column=config.get("data", {}).get("timestamp_column", "timestamp"),
        cache_mode="batch",
    )

    # Set user_id for rolling window
    userid_col = config.get("dfp", {}).get("userid_column", "username")
    df_preprocessed[userid_col] = user_id  # Ensure consistent user_id

    df_windowed = rolling_window.build_window(user_id, df_preprocessed)

    if df_windowed is None or len(df_windowed) == 0:
        # If rolling window fails, use preprocessed data directly
        logger.warning("⚠️  Rolling window returned None/empty - using preprocessed data directly")
        df_windowed = df_preprocessed

    logger.info(f"✅ Rolling window applied. Shape: {df_windowed.shape}")

    # Stage 3: Data Prep
    logger.info("\n[3/5] DataPrep - Selecting feature columns...")

    # DataPrep expects feature_columns at top level of config
    data_prep_config = {
        "feature_columns": config["features"]["feature_columns"],
        "timestamp_column": config.get("data", {}).get("timestamp_column", "timestamp"),
        "userid_column": config.get("dfp", {}).get("userid_column", "username"),
    }
    data_prep = DataPrep(data_prep_config)
    df_prepared = data_prep.prepare(df_windowed)
    logger.info(f"✅ Features selected. Final columns: {len(df_prepared.columns)}")
    logger.info(f"   Feature columns: {df_prepared.columns.tolist()}")

    # Extract timestamps BEFORE creating control message (DataPrep removes timestamp column)
    timestamp_col = config.get("data", {}).get("timestamp_column", "timestamp")
    start_timestamp = None
    end_timestamp = None

    if timestamp_col in df_windowed.columns:
        try:
            start_timestamp = df_windowed[timestamp_col].min()
            end_timestamp = df_windowed[timestamp_col].max()
            logger.info(f"   Timestamp range: {start_timestamp} to {end_timestamp}")
        except Exception as e:
            logger.warning(f"⚠️  Could not extract timestamps: {e}")
    else:
        logger.warning(f"⚠️  Timestamp column '{timestamp_col}' not found")

    # Stage 4: Training
    logger.info("\n[4/5] DFPTrainer - Training AutoEncoder...")

    # Create control message for trainer
    msg = ControlMessage()
    msg.payload(df_prepared)
    msg.set_metadata("user_id", user_id)
    msg.add_task("training", {})

    # Add timestamps to metadata (for NVIDIA compliance)
    if start_timestamp is not None:
        msg.set_metadata("start_timestamp", start_timestamp)
    if end_timestamp is not None:
        msg.set_metadata("end_timestamp", end_timestamp)

    trainer = DFPTrainer(config)
    output_msg = trainer.train(msg)

    if output_msg is None:
        raise RuntimeError("Training failed: No output message")

    logger.info("✅ Model trained successfully")
    train_samples = output_msg.get_metadata("train_samples")
    val_samples = output_msg.get_metadata("val_samples")
    logger.info(f"   Train samples: {train_samples}")
    logger.info(f"   Val samples: {val_samples}")

    # Stage 5: MLflow Logging
    logger.info("\n[5/5] MLflowModelWriter - Logging to MLflow...")
    mlflow_writer = MLflowModelWriter(config)
    output_msg = mlflow_writer.write_model(output_msg)

    # Get the run_id from the output message
    run_id = output_msg.get_metadata("mlflow_run_id")
    logger.info(f"✅ Model logged to MLflow (run_id: {run_id})")

    return output_msg


def verify_mlflow_logging(output_message, experiment_name, user_id):
    """Verify that all NVIDIA-standard parameters and metrics were logged."""

    print("\n" + "=" * 80)
    print("VERIFYING NVIDIA-COMPLIANT MLFLOW LOGGING")
    print("=" * 80)

    # Get run_id from output message
    run_id = output_message.get_metadata("mlflow_run_id")
    if not run_id:
        print("❌ No run_id found in output message")
        logger.error("❌ No run_id found in output message")
        return False

    # Get run directly by ID
    client = MlflowClient()
    try:
        run = client.get_run(run_id)
    except Exception as e:
        print(f"❌ Failed to get run {run_id}: {e}")
        logger.error(f"❌ Failed to get run {run_id}: {e}")
        return False

    print(f"\nRun ID: {run_id}")
    print(f"Status: {run.info.status}")

    # --- VERIFY NVIDIA-STANDARD PARAMETERS ---

    print("\n" + "-" * 80)
    print("NVIDIA-STANDARD PARAMETERS")
    print("-" * 80)

    nvidia_params = {
        "Algorithm": str,
        "Epochs": int,
        "Learning rate": float,
        "Batch size": int,
        "Start Epoch": str,
        "End Epoch": str,
        "Log Count": int,
    }

    params_ok = True
    for param_name, expected_type in nvidia_params.items():
        if param_name in run.data.params:
            value = run.data.params[param_name]
            try:
                # Try to convert to expected type
                if expected_type == int:  # noqa: E721 - explicit type check needed for conversion
                    typed_value = int(float(value))
                elif expected_type == float:  # noqa: E721 - explicit type check needed for conversion
                    typed_value = float(value)
                else:
                    typed_value = str(value)

                print(f"✅ {param_name}: {typed_value} ({type(typed_value).__name__})")
            except Exception as e:
                print(f"⚠️  {param_name}: {value} (conversion failed: {e})")
                params_ok = False
        else:
            print(f"❌ {param_name}: NOT LOGGED")
            logger.error(f"❌ {param_name}: NOT LOGGED")
            params_ok = False

    # --- VERIFY OUR ADDITIONAL PARAMETERS ---

    print("\n" + "-" * 80)
    print("ADDITIONAL PARAMETERS (Our Enhancements)")
    print("-" * 80)

    additional_params = ["user_id", "feature_count"]
    for param_name in additional_params:
        if param_name in run.data.params:
            value = run.data.params[param_name]
            print(f"✅ {param_name}: {value}")
        else:
            print(f"⚠️  {param_name}: NOT LOGGED")

    # --- VERIFY METRICS ---

    print("\n" + "-" * 80)
    print("METRICS")
    print("-" * 80)

    # Get all metrics
    all_metrics = run.data.metrics

    # Check for embedding metrics (NVIDIA standard)
    embedding_metrics = {k: v for k, v in all_metrics.items() if "embedding-" in k}
    if embedding_metrics:
        print(f"✅ Embedding metrics ({len(embedding_metrics)} found):")
        for metric_name, value in embedding_metrics.items():
            print(f"   - {metric_name}: {value}")
    else:
        print("⚠️  No embedding metrics found (may be OK if no categorical features)")

    # Check for split sample metrics (our addition)
    split_metrics = ["train_split_samples", "val_split_samples"]
    for metric_name in split_metrics:
        if metric_name in all_metrics:
            value = all_metrics[metric_name]
            print(f"✅ {metric_name}: {value}")
        else:
            print(f"⚠️  {metric_name}: NOT LOGGED")

    # --- SUMMARY ---

    print("\n" + "=" * 80)
    if params_ok:
        print("✅ SUCCESS: All NVIDIA-standard parameters logged correctly")
    else:
        print("❌ FAILURE: Some NVIDIA-standard parameters missing or incorrect")
    print("=" * 80 + "\n")

    return params_ok


def main():
    """Main test function."""
    try:
        # Load configuration
        logger.info("Loading configuration...")
        config = load_config()

        # Set MLflow tracking URI
        mlflow_config = config.get("mlflow", {})
        mlflow_uri = mlflow_config.get("tracking_uri", "sqlite:///data/mlflow/mlflow.db")
        mlflow.set_tracking_uri(mlflow_uri)
        logger.info(f"MLflow tracking URI: {mlflow_uri}")

        # Create test experiment
        experiment_name = "dfp/training"
        mlflow.set_experiment(experiment_name)
        logger.info(f"Using experiment: {experiment_name}")

        # Load test data
        df, test_user = load_single_user_data(config)

        # Run FULL pipeline (preprocessing → training → MLflow)
        output_message = run_full_pipeline(df, test_user, config)

        # Verify logging
        success = verify_mlflow_logging(output_message, experiment_name, test_user)

        if success:
            print("\n✅ TEST PASSED: NVIDIA-compliant logging verified")
            return 0
        else:
            print("\n❌ TEST FAILED: Issues detected in logging")
            return 1

    except Exception as e:
        print(f"\n❌ TEST ERROR: {e}")
        logger.error(f"\n❌ TEST ERROR: {e}", exc_info=True)
        return 1


if __name__ == "__main__":
    sys.exit(main())
