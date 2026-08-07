"""
DFP Training Pipeline - NVIDIA Morpheus Modular Pattern

Implements NVIDIA's dfp_training_pipe module pattern for batch training.
Reference: python/morpheus_dfp/morpheus_dfp/modules/dfp_training_pipe.py

Architecture (NVIDIA Modular DFP):
    DFP_PREPROC (file_to_df → split_users)
        ↓
    Geographic Features (calculate travel_speed_kmph before caching)
        ↓
    dfp_rolling_window (cache_mode="aggregate", 60d history WITH geographic features)
        ↓
    dfp_data_prep (applies preprocess_schema - calculates increment features)
        ↓ [Features include travel_speed_kmph for behavioral pattern learning]
    dfp_training (AutoEncoder learns behavioral + geographic patterns)
        ↓
    mlflow_model_writer (saves versioned models: DFP-{username}, DFP-generic)

DFP Behavioral Learning:
    - Geographic features (travel_speed_kmph) included in training
    - AutoEncoder learns normal behavioral + geographic patterns
    - FilterDetections applies binary threshold filtering during inference

Author: Tomasz Zabek <tzabek@deloitte.co.uk>
Date: 2025-12-01
"""

import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from modules.control.control_message import ControlMessage
from modules.io.file_to_df import FileToDataFrame
from modules.preprocessing.data_prep import DataPrep
from modules.preprocessing.dfp_preprocessing import DFPPreprocessing
from modules.preprocessing.geographic_features import calculate_travel_features
from modules.preprocessing.rolling_window import RollingWindow
from modules.preprocessing.source_schema import build_azure_source_schema
from modules.preprocessing.user_splitting import UserSplitter
from modules.training.dfp_trainer import DFPTrainer
from modules.training.mlflow_model_writer import MLflowModelWriter
from modules.utils.metrics_utils import PipelineMetrics

logger = logging.getLogger(__name__)


class DFPTrainingPipeline:
    """
    NVIDIA Morpheus DFP Training Pipeline (Modular Pattern).

    Follows NVIDIA's dfp_training_pipe module pattern with geographic features:
    - DFP_PREPROC: file_to_df → split_users
    - Geographic Features: calculate travel_speed_kmph BEFORE caching
    - dfp_rolling_window: aggregate mode (60d history, preserves cache WITH geographic features)
    - dfp_data_prep: applies preprocess_schema AFTER rolling window (includes travel_speed_kmph)
    - dfp_training: AutoEncoder learns behavioral + geographic patterns
    - mlflow_model_writer: versioned model storage (DFP-{username}, DFP-generic)

    DFP Behavioral Learning:
        - Geographic features (travel_speed_kmph) included in training
        - AutoEncoder learns normal behavioral + geographic patterns
        - FilterDetections binary filtering applied during inference (not training)

    CRITICAL: Uses aggregate cache mode (preserves last_train_count for inference).

    Reference:
        /nv-morpheus/python/morpheus_dfp/morpheus_dfp/modules/dfp_training_pipe.py
    """

    def __init__(self, config: dict[str, Any], cache_dir: str, mlflow_manager: Any, metrics: PipelineMetrics):
        """
        Initialize training pipeline.

        Args:
            config: Pipeline configuration
            cache_dir: Cache directory for rolling window
            mlflow_manager: MLflow manager instance
            metrics: Pipeline metrics collector
        """
        self.config = config
        self.cache_dir = Path(cache_dir)
        self.mlflow_manager = mlflow_manager
        self.metrics = metrics

        # Initialize modules
        self._init_modules()

        logger.info("DFP Training Pipeline initialized (NVIDIA modular pattern)")

    def _init_modules(self):
        """Initialize training pipeline modules."""

        # DFP_PREPROC: file_to_df with source_schema
        self.file_to_df = FileToDataFrame(
            config={
                "source_schema": build_azure_source_schema(),
                "filter_null": True,
                "timestamp_column_name": self.config.get("timestamp_column", "timestamp"),
            }
        )

        # DFP_PREPROC: split_users
        self.user_splitter = UserSplitter(
            userid_column=self.config.get("userid_column", "username"),
            include_generic=False,
            include_individual=True,
            timestamp_column=self.config.get("timestamp_column", "timestamp"),
        )

        # dfp_rolling_window (NVIDIA training defaults)
        # Note: RollingWindow adds "rolling-user-data" subdirectory internally
        training_config = self.config.get("training", {})
        self.rolling_window = RollingWindow(
            cache_dir=str(self.cache_dir),
            timestamp_column=self.config.get("timestamp_column", "timestamp"),
            cache_mode="aggregate",  # NVIDIA training standard
            cache_to_disk=True,  # Enable disk persistence
            min_history=training_config.get("min_history", 300),
            min_increment=training_config.get("min_increment", 300),
            max_history=training_config.get("max_history", "60d"),
        )

        # dfp_data_prep (applies preprocess_schema)
        self.preprocessing = DFPPreprocessing(
            {
                "schema_file": self.config.get("schema_file", "config/feature_schema.yaml"),
                "feature_set": self.config.get("feature_set", "default"),
                "fill_missing": True,
                "preserve_columns": [
                    "_batch_id",
                    "location_geoCoordinates_latitude",
                    "location_geoCoordinates_longitude",
                ],
            }
        )

        # Data preparation (feature selection)
        self.data_prep = DataPrep(
            {
                "feature_columns": list(self.config.get("feature_columns", [])),
                "timestamp_column": self.config.get("timestamp_column", "timestamp"),
                "userid_column": self.config.get("userid_column", "username"),
                "exclude_columns": [],
            }
        )

        # dfp_training (AutoEncoder)
        feature_columns = list(self.config.get("feature_columns", []))
        training_config = dict(self.config.get("training", {}))
        model_kwargs = training_config.get("model_kwargs", {})

        self.trainer = DFPTrainer(
            {
                "model": {
                    "encoder_layers": list(model_kwargs.get("encoder_layers", [512, 500])),
                    "decoder_layers": list(model_kwargs.get("decoder_layers", [512])),
                    "activation": model_kwargs.get("activation", "relu"),
                    "swap_probability": float(model_kwargs.get("swap_probability", 0.2)),
                    "learning_rate": float(model_kwargs.get("learning_rate", 0.01)),
                    "learning_rate_decay": float(model_kwargs.get("learning_rate_decay", 0.99)),
                    "batch_size": int(model_kwargs.get("batch_size", 512)),
                    "optimizer": str(model_kwargs.get("optimizer", "sgd")),
                    "scaler": str(model_kwargs.get("scaler", "standard")),
                    "feature_columns": feature_columns,
                },
                "training": {
                    "epochs": int(training_config.get("epochs", 30)),
                    "validation_size": float(training_config.get("validation_size", 0.1)),
                    "min_training_samples": int(training_config.get("min_training_samples", 100)),
                    "seed": int(training_config.get("seed", 42)),
                },
                "features": {"feature_columns": feature_columns},
            }
        )

        # mlflow_model_writer
        self.model_writer = MLflowModelWriter(
            {
                "mlflow": {
                    "tracking_uri": self.mlflow_manager.tracking_uri,
                    "model_name_template": "DFP-{user_id}",
                    "experiment_name": self.config.get("mlflow", {}).get("experiment_name", "dfp/training"),
                    "register_model": True,
                }
            }
        )

    def run(self, data_path: str) -> dict[str, Any]:
        """
        Execute training pipeline following NVIDIA modular pattern.

        NVIDIA dfp_training_pipe flow (with geographic features):
            1. DFP_PREPROC: file_to_df (source_schema) → split_users
            2. Geographic Features: calculate travel_speed_kmph BEFORE caching
            3. dfp_rolling_window: aggregate mode (60d, preserves cache WITH geographic features)
            4. dfp_data_prep: preprocess_schema (calculates increment features, includes travel_speed_kmph)
            5. dfp_training: AutoEncoder learns behavioral + geographic patterns
            6. mlflow_model_writer: save versioned models (DFP-{username}, DFP-generic)

        DFP Behavioral Learning:
            - Geographic features (travel_speed_kmph) included in AutoEncoder training
            - Model learns normal behavioral + geographic patterns from historical data
            - FilterDetections binary filtering applied during inference (not training)

        Args:
            data_path: Path to training data file

        Returns:
            Training statistics dictionary
        """
        logger.info("=" * 80)
        logger.info("DFP TRAINING PIPELINE (NVIDIA Modular)")
        logger.info("=" * 80)
        logger.info(f"Data path: {data_path}")
        logger.info("Cache mode: aggregate (preserves last_train_count)")
        logger.info(f"Max history: {self.rolling_window.max_history}")

        start_time = datetime.now(timezone.utc)

        # Module 1: DFP_PREPROC - file_to_df (source_schema only)
        logger.info("\n[Module 1/5] DFP_PREPROC: file_to_df (source_schema)")
        with self.metrics.time_operation("file_to_df"):
            df = self.file_to_df.load_files([data_path])
        logger.info(f"  Loaded {len(df)} records, {len(df.columns)} columns")

        # Module 2: DFP_PREPROC - split_users
        logger.info("\n[Module 2/5] DFP_PREPROC: split_users")
        with self.metrics.time_operation("split_users"):
            user_dfs = self.user_splitter.split_users(df)
        logger.info(f"  Split into {len(user_dfs)} users")

        # Module 2.5: Calculate geographic features BEFORE caching
        # This ensures rolling window cache contains geographic features
        logger.info("\n[Module 2.5/5] Calculate geographic features (pre-cache)")
        user_dfs_with_geo = {}
        # Read from dfp.preprocessing.enable_geographic_features
        preprocessing_config = self.config.get("dfp", {}).get("preprocessing", {})
        geographic_enabled = preprocessing_config.get("enable_geographic_features", True)

        for user_id, user_df in user_dfs.items():
            # Check if coordinates are present
            has_coords = (
                "location_geoCoordinates_latitude" in user_df.columns
                and "location_geoCoordinates_longitude" in user_df.columns
            )

            if geographic_enabled and has_coords:
                try:
                    # Calculate travel features on raw data before caching
                    user_df = calculate_travel_features(
                        user_df,
                        user_col=self.config.get("userid_column", "username"),
                        timestamp_col=self.config.get("timestamp_column", "timestamp"),
                    )
                    logger.debug(
                        f"  {user_id}: calculated geographic features (travel_speed_kmph, distance_km, ts_delta_hour)"
                    )
                except Exception as e:
                    logger.warning(
                        f"  {user_id}: failed to calculate geographic features: {e}. "
                        "Continuing without geographic features."
                    )
            elif geographic_enabled and not has_coords:
                logger.debug(f"  {user_id}: no coordinates, skipping geographic features")

            user_dfs_with_geo[user_id] = user_df

        logger.info(
            f"  Geographic features calculated for {sum(1 for uid, udf in user_dfs_with_geo.items() if 'travel_speed_kmph' in udf.columns)}/{len(user_dfs_with_geo)} users"
        )

        # Module 3: dfp_rolling_window (aggregate mode, NOW with geographic features)
        logger.info("\n[Module 3/5] dfp_rolling_window (aggregate mode, caching WITH geographic features)")
        user_windows = {}
        for user_id, user_df in user_dfs_with_geo.items():
            windowed_df = self.rolling_window.build_window(user_id=user_id, incoming_df=user_df)
            if windowed_df is not None and len(windowed_df) > 0:
                user_windows[user_id] = windowed_df
                logger.debug(f"  {user_id}: {len(windowed_df)} rows windowed")
        logger.info(f"  Windowed data ready for {len(user_windows)} users")
        print(f"[HANG_DEBUG] About to start Module 4, user_windows count: {len(user_windows)}", flush=True)

        # Module 4: dfp_data_prep (preprocess_schema - AFTER rolling window)
        print("[HANG_DEBUG] About to log Module 4 message...", flush=True)
        logger.info("\n[Module 4/5] dfp_data_prep (calculates increment features)")
        print("[HANG_DEBUG] Module 4 message logged, starting loop...", flush=True)
        preprocessed_user_dfs = {}
        for user_id, window_df in user_windows.items():
            print(f"[DEBUG] Processing {user_id}: input cols={len(window_df.columns)}", flush=True)
            with self.metrics.time_operation("dfp_data_prep"):
                preprocessed_df = self.preprocessing.preprocess(window_df)
            print(
                f"[DEBUG] After preprocess: output cols={len(preprocessed_df.columns)}, has travel_speed_kmph={'travel_speed_kmph' in preprocessed_df.columns}",
                flush=True,
            )

            # Data prep (feature selection)
            features = self.data_prep.prepare(preprocessed_df)
            if features is not None and len(features) > 0:
                preprocessed_user_dfs[user_id] = features
                print(
                    f"[DEBUG] After data_prep: {len(features.columns)} features, has travel_speed_kmph={'travel_speed_kmph' in features.columns}",
                    flush=True,
                )

                # Debug increment features
                if "appincrement" in preprocessed_df.columns:
                    logger.debug(
                        f"  {user_id}: appincrement range "
                        f"{preprocessed_df['appincrement'].min()}-{preprocessed_df['appincrement'].max()}"
                    )
        logger.info(f"  Features prepared for {len(preprocessed_user_dfs)} users")

        # Module 5: dfp_training + mlflow_model_writer
        logger.info("\n[Module 5/5] dfp_training + mlflow_model_writer")
        trained_count = 0
        saved_count = 0

        for user_id, features in preprocessed_user_dfs.items():
            try:
                # Create ControlMessage for training
                train_msg = ControlMessage()
                train_msg.set_metadata("user_id", user_id)
                train_msg.payload(features)

                # Add training task (required by dfp_trainer validation)
                train_msg.add_task("training", {"type": "training", "properties": {}})

                # Add timestamp metadata
                if user_id in user_windows:
                    window_df = user_windows[user_id]
                    timestamp_col = self.config.get("timestamp_column", "timestamp")
                    if timestamp_col in window_df.columns:
                        train_msg.set_metadata("start_timestamp", window_df[timestamp_col].min())
                        train_msg.set_metadata("end_timestamp", window_df[timestamp_col].max())

                # Train model
                with self.metrics.time_operation("dfp_training"):
                    result_msg = self.trainer.train(train_msg)

                if result_msg is not None:
                    trained_count += 1

                    # Save to MLflow
                    self.model_writer.write_model(result_msg)
                    saved_count += 1

                    # Record metrics
                    self.metrics.record_batch_processed(count=1)

                    logger.info(f"  ✓ {user_id}: trained and saved")

            except Exception as e:
                logger.error(f"  ✗ {user_id}: training failed - {e}")
                self.metrics.record_errors(count=1)

        # Statistics
        duration = (datetime.now(timezone.utc) - start_time).total_seconds()
        stats = {
            "total_records": len(df),
            "total_users": len(user_dfs),
            "users_trained": trained_count,
            "models_saved": saved_count,
            "cache_populated": True,
            "duration_seconds": duration,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

        # Record final training metrics
        self.metrics.record_events_processed(count=len(df))
        if duration > 0:
            throughput = len(df) / duration
            self.metrics.record_throughput(events_per_second=throughput)

        # Push metrics to Pushgateway for persistence (training is a batch job)
        from modules.utils.metrics_utils import push_metrics_to_gateway

        push_metrics_to_gateway(
            job="dfp_training", instance=f"batch_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}"
        )

        logger.info("\n" + "=" * 80)
        logger.info("TRAINING COMPLETE")
        logger.info(f"  Duration: {duration:.1f}s")
        logger.info(f"  Users trained: {trained_count}/{len(user_dfs)}")
        logger.info(f"  Models saved: {saved_count}")
        logger.info("  Cache state: READY (last_train_count set for inference)")
        logger.info("=" * 80)

        return stats
