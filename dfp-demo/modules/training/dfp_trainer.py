"""
DFP Training Module

This module implements the core training logic for the Digital Fingerprinting
Platform, training separate AutoEncoder models per user_id for anomaly detection.

Based on NVIDIA reference:
- python/morpheus_dfp/morpheus_dfp/modules/dfp_training.py
- examples/digital_fingerprinting/production/morpheus/dfp_training_pipe.py

Key Features:
- Per-user model training (separate model for each user_id)
- Generic model training (fallback model trained on all users)
- Train/validation split with configurable ratio
- Insufficient data handling (minimum sample requirements)
- Integration with ControlMessage for pipeline communication
- MLflow-ready model output with metadata

Author: Tomasz Zabek <tzabek@deloitte.co.uk>
Date: 2025-11-11
"""

import logging
from typing import Any

import pandas as pd
from sklearn.model_selection import train_test_split

from modules.control.control_message import ControlMessage
from modules.training.autoencoder_wrapper import DFPAutoEncoder

logger = logging.getLogger(__name__)


class DFPTrainer:
    """
    DFP Training Module - Trains AutoEncoder models per user.

    This module is responsible for:
    1. Extracting user_id and training data from ControlMessage
    2. Validating sufficient data for training
    3. Splitting data into train/validation sets
    4. Training AutoEncoder model
    5. Creating output ControlMessage with trained model

    Following NVIDIA pattern:
    - Input: ControlMessage with task=ControlMessageType.TRAINING
    - Processing: Extract payload → validate → split → train
    - Output: ControlMessage with trained model attached

    Training Strategy:
    - Per-user models: Train separate model for each user_id
    - Generic model: Train fallback model on all users ("generic_user")
    - Minimum samples: Skip training if insufficient data

    Reference:
        NVIDIA Morpheus dfp_training.py module
    """

    def __init__(self, config: dict[str, Any]):
        """
        Initialize DFP Trainer with configuration.

        Args:
            config: Configuration dictionary with keys:
                - model: Model configuration (encoder_layers, decoder_layers, etc.)
                - training: Training configuration
                    - epochs: Number of training epochs [default: 50]
                    - validation_size: Validation split ratio [default: 0.1]
                    - min_training_samples: Minimum samples required [default: 100]
                    - use_val_for_loss_stats: Use validation for loss normalization [default: True]
                - features: Feature configuration
                    - feature_columns: List of feature column names

        Raises:
            ValueError: If required configuration keys are missing
        """
        self.config = config
        self._validate_config()

        # Extract configuration
        self.model_config = config["model"]
        self.training_config = config.get("training", {})
        self.feature_columns = config["features"]["feature_columns"]

        # Validate required training parameters
        if "epochs" not in self.training_config:
            raise ValueError("training.epochs is required in trainer configuration")

        # Training parameters
        self.epochs = self.training_config["epochs"]  # Use config value directly (validated above)

        # DEBUG: Log epochs value
        logger.info(f"DEBUG DFPTrainer: self.epochs = {self.epochs} (type: {type(self.epochs)})")
        self.validation_size = self.training_config.get("validation_size", 0.1)
        self.min_training_samples = self.training_config.get("min_training_samples", 100)
        self.use_val_for_loss_stats = self.training_config.get("use_val_for_loss_stats", True)

        # NOTE: Do NOT add feature_columns to model_config here!
        # model_config is shared across all users, causing categorical vocabulary contamination.
        # Instead, pass feature_columns separately when creating each model instance.

        logger.info(
            f"DFPTrainer initialized: epochs={self.epochs}, "
            f"validation_size={self.validation_size}, "
            f"min_samples={self.min_training_samples}, "
            f"features={len(self.feature_columns)}"
        )

    def _validate_config(self) -> None:
        """
        Validate configuration dictionary.

        Raises:
            ValueError: If required keys are missing or invalid
        """
        required_keys = ["model", "features"]
        missing_keys = [key for key in required_keys if key not in self.config]

        if missing_keys:
            raise ValueError(f"Missing required configuration keys: {missing_keys}. Required: {required_keys}")

        if "feature_columns" not in self.config["features"]:
            raise ValueError("features.feature_columns is required in configuration")

        if not isinstance(self.config["features"]["feature_columns"], list):
            raise ValueError("features.feature_columns must be a list")

        if not self.config["features"]["feature_columns"]:
            raise ValueError("features.feature_columns cannot be empty")

    def train(self, control_message: ControlMessage) -> ControlMessage | None:
        """
        Train AutoEncoder model from ControlMessage.

        This is the main entry point for training. It:
        1. Validates message type and task
        2. Extracts user_id and training data
        3. Checks for sufficient data
        4. Splits into train/validation sets
        5. Trains AutoEncoder model
        6. Creates output ControlMessage with model

        Args:
            control_message: Input ControlMessage with:
                - task: ControlMessageType.TRAINING
                - metadata['user_id']: User identifier
                - payload: MessageMeta with training data

        Returns:
            ControlMessage with trained model (or None if insufficient data)

        Raises:
            ValueError: If message format is invalid
            RuntimeError: If training fails
        """
        try:
            # Validate message
            self._validate_message(control_message)

            # Extract user_id and data
            user_id = control_message.get_metadata("user_id")
            training_data = self._extract_training_data(control_message)

            logger.info(
                f"Training model for user_id='{user_id}': "
                f"{len(training_data)} samples, {len(training_data.columns)} columns"
            )

            # Check minimum samples
            if len(training_data) < self.min_training_samples:
                logger.warning(
                    f"Insufficient data for user_id='{user_id}': "
                    f"{len(training_data)} samples < {self.min_training_samples} minimum. "
                    f"Skipping training."
                )
                return None

            # Validate feature columns
            missing_cols = set(self.feature_columns) - set(training_data.columns)
            if missing_cols:
                raise ValueError(f"Training data missing required feature columns: {missing_cols}")

            # Split train/validation
            train_df, val_df = self._split_data(training_data)

            logger.info(f"Data split: {len(train_df)} train, {len(val_df)} validation samples")

            # Train model
            model = self._train_model(train_df, val_df, user_id)

            # Create output message
            output_message = self._create_output_message(
                model=model,
                user_id=user_id,
                train_samples=len(train_df),
                val_samples=len(val_df),
                original_message=control_message,
            )

            logger.info(f"Training complete for user_id='{user_id}'. Model trained on {len(train_df)} samples.")

            return output_message

        except Exception as e:
            logger.error(f"Training failed for control message: {e}")
            raise RuntimeError(f"Training failed: {e}") from e

    def _validate_message(self, control_message: ControlMessage) -> None:
        """
        Validate ControlMessage format.

        Args:
            control_message: Message to validate

        Raises:
            ValueError: If message format is invalid
        """
        # Check if it's a ControlMessage (allow duck typing for import flexibility)
        if not hasattr(control_message, "get_metadata") or not hasattr(control_message, "payload"):
            raise ValueError(
                f"Expected ControlMessage with get_metadata() and payload() methods, got {type(control_message)}"
            )

        # Check task type
        tasks = control_message.get_tasks()
        if not tasks:
            raise ValueError("ControlMessage has no tasks")

        # Check if 'training' task exists
        has_training = control_message.has_task("training")
        if not has_training:
            raise ValueError(f"Expected 'training' task, got task types: {list(tasks.keys())}")

        # Check user_id
        if not control_message.has_metadata("user_id"):
            raise ValueError("ControlMessage missing 'user_id' metadata")

        # Check payload
        if control_message.payload() is None:
            raise ValueError("ControlMessage has no payload")

    def _extract_training_data(self, control_message: ControlMessage) -> pd.DataFrame:
        """
        Extract training data from ControlMessage payload.

        Args:
            control_message: Input message

        Returns:
            Training DataFrame

        Raises:
            ValueError: If payload format is invalid
        """
        payload = control_message.payload()

        if payload is None:
            raise ValueError("ControlMessage has no payload")

        # Type narrowing: at this point payload is not None
        df: Any = payload

        # Convert to pandas if needed (cuDF → pandas)
        if hasattr(df, "to_pandas"):
            df = df.to_pandas()

        if not isinstance(df, pd.DataFrame):
            raise ValueError(f"Expected DataFrame payload, got {type(df)}")

        if df.empty:
            raise ValueError("Training data is empty")

        return df

    def _split_data(self, data: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
        """
        Split data into train and validation sets.

        Args:
            data: Full training dataset

        Returns:
            Tuple of (train_df, val_df)
        """
        if self.validation_size > 0 and len(data) > 10:  # Need at least 10 samples to split
            train_df, val_df = train_test_split(data, test_size=self.validation_size, random_state=42, shuffle=True)
            return train_df, val_df
        else:
            # No validation split (use all for training)
            return data, pd.DataFrame(columns=data.columns)

    def _train_model(self, train_df: pd.DataFrame, val_df: pd.DataFrame, user_id: str) -> DFPAutoEncoder:
        """
        Train AutoEncoder model.

        Args:
            train_df: Training data
            val_df: Validation data (may be empty)
            user_id: User identifier (for logging)

        Returns:
            Trained DFPAutoEncoder instance

        Raises:
            RuntimeError: If training fails
        """
        try:
            # Create a COPY of model_config for this user to prevent cross-contamination
            # If we reuse the same dict, categorical vocabularies leak between users
            import copy

            user_model_config = copy.deepcopy(self.model_config)
            user_model_config["feature_columns"] = self.feature_columns

            # Create model with user-specific config
            model = DFPAutoEncoder(user_model_config)

            # Prepare validation data
            validation_data = val_df if not val_df.empty else None
            run_validation = validation_data is not None

            logger.info(
                f"Training AutoEncoder for user_id='{user_id}': "
                f"{len(train_df)} train samples, "
                f"{len(val_df) if not val_df.empty else 0} validation samples, "
                f"{self.epochs} epochs"
            )

            # Train
            model.fit(
                training_data=train_df,
                epochs=self.epochs,
                validation_data=validation_data,
                run_validation=run_validation,
                use_val_for_loss_stats=self.use_val_for_loss_stats,
            )

            return model

        except Exception as e:
            logger.error(f"Model training failed for user_id='{user_id}': {e}")
            raise RuntimeError(f"Model training failed: {e}") from e

    def _create_output_message(
        self,
        model: DFPAutoEncoder,
        user_id: str,
        train_samples: int,
        val_samples: int,
        original_message: ControlMessage,
    ) -> ControlMessage:
        """
        Create output ControlMessage with trained model.

        Following NVIDIA pattern:
        - Copy metadata from input message
        - Attach trained model to metadata
        - Add training statistics
        - Add timestamp range for NVIDIA MLflow compliance
        - Set task to inference (optional, depends on pipeline)

        Args:
            model: Trained AutoEncoder
            user_id: User identifier
            train_samples: Number of training samples
            val_samples: Number of validation samples
            original_message: Input ControlMessage

        Returns:
            Output ControlMessage with model
        """
        # Create output message
        output_message = ControlMessage()

        # Copy user_id and other metadata
        output_message.set_metadata("user_id", user_id)

        # Attach trained model
        output_message.set_metadata("model", model)

        # Add training statistics
        output_message.set_metadata("train_samples", train_samples)
        output_message.set_metadata("val_samples", val_samples)
        output_message.set_metadata("total_samples", train_samples + val_samples)

        # DEBUG: Log before setting epochs
        logger.info(f"DEBUG: Setting epochs metadata: self.epochs = {self.epochs}")
        output_message.set_metadata("epochs", self.epochs)
        logger.info(f"DEBUG: After setting, get_metadata('epochs') = {output_message.get_metadata('epochs')}")

        output_message.set_metadata("feature_count", len(self.feature_columns))

        # Add timestamp range from original data (for NVIDIA MLflow compliance)
        # NVIDIA logs "Start Epoch" and "End Epoch" using timestamp column

        # First check if timestamps were already provided in input message metadata
        if original_message.has_metadata("start_timestamp") and original_message.has_metadata("end_timestamp"):
            # Use timestamps from input metadata (preferred - already extracted)
            output_message.set_metadata("start_timestamp", original_message.get_metadata("start_timestamp"))
            output_message.set_metadata("end_timestamp", original_message.get_metadata("end_timestamp"))
            logger.debug("Using timestamps from input message metadata")
        else:
            # Try to extract from payload (fallback)
            original_payload = original_message.payload()
            if original_payload is not None and not original_payload.empty:
                # Try common timestamp column names
                timestamp_col = None
                for col_name in ["timestamp", "time", "event_time", "_time"]:
                    if col_name in original_payload.columns:
                        timestamp_col = col_name
                        break

                if timestamp_col:
                    try:
                        min_ts = original_payload[timestamp_col].min()
                        max_ts = original_payload[timestamp_col].max()
                        output_message.set_metadata("start_timestamp", min_ts)
                        output_message.set_metadata("end_timestamp", max_ts)
                        logger.debug(f"Extracted timestamps from payload: {min_ts} to {max_ts}")
                    except Exception as e:
                        logger.warning(f"Could not extract timestamps from column '{timestamp_col}': {e}")
                else:
                    logger.warning(
                        f"No timestamp column found. Available columns: {original_payload.columns.tolist()[:10]}"
                    )
            else:
                logger.warning("Original message payload is None or empty - cannot extract timestamps")

            # Copy payload (some pipelines pass training data forward for evaluation)
            output_message.payload(original_payload)  # setter

        # Add task (optional, depends on pipeline routing)
        # output_message.add_task(ControlMessageType.INFERENCE, {})

        return output_message

    def train_batch(self, control_messages: list[ControlMessage]) -> list[ControlMessage]:
        """
        Train models for a batch of ControlMessages.

        This is a convenience method for processing multiple messages,
        commonly used in pipeline implementations.

        Args:
            control_messages: List of input ControlMessages

        Returns:
            List of output ControlMessages (with trained models)
            Note: Messages with insufficient data are filtered out
        """
        output_messages = []

        for msg in control_messages:
            try:
                output_msg = self.train(msg)
                if output_msg is not None:
                    output_messages.append(output_msg)
            except Exception as e:
                logger.error(f"Failed to process message: {e}")
                # Continue processing remaining messages
                continue

        logger.info(
            f"Batch training complete: {len(output_messages)}/{len(control_messages)} models trained successfully"
        )

        return output_messages
