"""
MLflow Model Writer Module

This module handles model persistence and registration in MLflow Model Registry,
following NVIDIA Morpheus DFP patterns for model naming, experiment tracking,
and metadata management.

Based on NVIDIA reference:
- python/morpheus_dfp/morpheus_dfp/modules/mlflow_model_writer.py
- python/morpheus_dfp/morpheus_dfp/modules/dfp_mlflow_model_writer.py
- examples/digital_fingerprinting/production/morpheus/dfp_training_pipe.py

Key Features:
- Model logging with MLflow (mlflow.pytorch.log_model)
- Model Registry registration and versioning
- NVIDIA naming patterns: model="DFP-{user_id}", experiment="dfp/training/{model_name}"
- Metadata tagging (user_id, timestamp, training_samples, etc.)
- Conda environment packaging for deployment

Author: Tomasz Zabek <tzabek@deloitte.co.uk>
Date: 2025-11-11
"""

import logging
import re
from datetime import datetime
from typing import Any

import mlflow
import mlflow.pytorch
import numpy as np
from mlflow.exceptions import MlflowException
from mlflow.models.signature import infer_signature
from mlflow.tracking import MlflowClient

from modules.control.control_message import ControlMessage

logger = logging.getLogger(__name__)


def sanitize_model_name(name: str) -> str:
    """
    Sanitize model name for MLflow 3.x compatibility.

    MLflow 3.x requires model names to be non-empty strings that don't contain
    the following characters: '/', ':', '.', '%', '"', "'"

    Args:
        name: Original name (may contain invalid characters like email addresses)

    Returns:
        Sanitized name with invalid characters replaced by underscores

    Examples:
        >>> sanitize_model_name("user@company.co.uk")
        'user_company_co_uk'
        >>> sanitize_model_name("user/test:123")
        'user_test_123'
    """
    # Replace invalid characters with underscores
    # Invalid: '/', ':', '.', '%', '"', "'"
    sanitized = re.sub(r'[/:\.%"\']', "_", name)

    # Ensure it's not empty
    if not sanitized:
        sanitized = "unknown"

    return sanitized


class MLflowModelWriter:
    """
    MLflow Model Writer - Persists trained models to MLflow Model Registry.

    This module is responsible for:
    1. Extracting trained model from ControlMessage
    2. Logging model to MLflow with mlflow.pytorch.log_model
    3. Registering model in MLflow Model Registry
    4. Tagging with metadata (user_id, timestamp, metrics)
    5. Creating model versions for tracking

    Following NVIDIA naming patterns:
    - Model name: "DFP-{user_id}" (e.g., "DFP-alice", "DFP-bob")
    - Experiment name: "dfp/training/{model_name}" or "dfp/training"
    - Run name: "{user_id}_{timestamp}"

    Model Registry Benefits:
    - Centralized model storage
    - Version tracking (v1, v2, v3, ...)
    - Stage management (None, Staging, Production, Archived)
    - Model lineage and metadata

    Reference:
        NVIDIA Morpheus mlflow_model_writer.py
    """

    def __init__(self, config: dict[str, Any]):
        """
        Initialize MLflow Model Writer with configuration.

        Args:
            config: Configuration dictionary with keys:
                - mlflow: MLflow configuration
                    - tracking_uri: MLflow tracking server URI
                    - experiment_name: Experiment name template (optional)
                    - model_name_template: Model name template (optional, default: "DFP-{user_id}")
                    - conda_env: Conda environment for model packaging (optional)
                    - register_model: Whether to register in Model Registry [default: True]

        Raises:
            ValueError: If required configuration keys are missing
        """
        self.config = config
        self._validate_config()

        # Extract MLflow configuration
        mlflow_config = config["mlflow"]
        self.tracking_uri = mlflow_config["tracking_uri"]
        self.experiment_name = mlflow_config.get("experiment_name", "dfp/training")
        self.model_name_template = mlflow_config.get("model_name_template", "DFP-{user_id}")
        self.register_model = mlflow_config.get("register_model", True)
        self.conda_env = mlflow_config.get("conda_env")

        # Set MLflow tracking URI
        mlflow.set_tracking_uri(self.tracking_uri)

        # Initialize MLflow client for Registry operations
        self.client = MlflowClient(tracking_uri=self.tracking_uri)

        logger.info(
            f"MLflowModelWriter initialized: tracking_uri={self.tracking_uri}, "
            f"experiment={self.experiment_name}, register={self.register_model}"
        )

    def _validate_config(self) -> None:
        """
        Validate configuration dictionary.

        Raises:
            ValueError: If required keys are missing or invalid
        """
        if "mlflow" not in self.config:
            raise ValueError("Missing 'mlflow' configuration section")

        mlflow_config = self.config["mlflow"]

        if "tracking_uri" not in mlflow_config:
            raise ValueError("mlflow.tracking_uri is required in configuration")

        if not mlflow_config["tracking_uri"]:
            raise ValueError("mlflow.tracking_uri cannot be empty")

    def write_model(self, control_message: ControlMessage) -> ControlMessage:
        """
        Write trained model to MLflow from ControlMessage.

        This is the main entry point for model persistence. It:
        1. Validates message and extracts model
        2. Creates/gets MLflow experiment
        3. Starts MLflow run
        4. Logs model with mlflow.pytorch.log_model
        5. Tags with metadata
        6. Registers in Model Registry (if enabled)
        7. Returns updated ControlMessage with MLflow metadata

        Args:
            control_message: ControlMessage with trained model in metadata['model']

        Returns:
            ControlMessage with MLflow metadata added:
                - mlflow_run_id: MLflow run ID
                - mlflow_model_name: Registered model name
                - mlflow_model_version: Model version (if registered)

        Raises:
            ValueError: If message format is invalid
            RuntimeError: If MLflow operations fail
        """
        try:
            # Validate message and extract data
            self._validate_message(control_message)
            user_id = control_message.get_metadata("user_id")
            model = control_message.get_metadata("model")

            # Get model name
            model_name = self._get_model_name(user_id)

            logger.info(f"Writing model to MLflow: user_id='{user_id}', model_name='{model_name}'")

            # Get or create experiment
            experiment_id = self._get_or_create_experiment()

            # Create run name with timestamp
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            run_name = f"{user_id}_{timestamp}"

            # Start MLflow run and log model
            with mlflow.start_run(experiment_id=experiment_id, run_name=run_name) as run:
                # Log model
                model_info = self._log_model(model=model, model_name=model_name, user_id=user_id)

                # Log metrics and parameters
                self._log_metrics_and_params(control_message, user_id)

                # Tag run with metadata
                self._tag_run(control_message, user_id, model_name)

                run_id = run.info.run_id

                logger.info(f"Model logged to MLflow: run_id={run_id}, model_name={model_name}")

                # Register model in Model Registry
                model_version = None
                if self.register_model:
                    model_version = self._register_model(
                        model_uri=model_info.model_uri, model_name=model_name, run_id=run_id
                    )

                # Update ControlMessage with MLflow metadata
                control_message.set_metadata("mlflow_run_id", run_id)
                control_message.set_metadata("mlflow_model_name", model_name)
                if model_version is not None:
                    control_message.set_metadata("mlflow_model_version", model_version)

                logger.info(
                    f"Model persistence complete: model_name={model_name}, version={model_version}, run_id={run_id}"
                )

                return control_message

        except Exception as e:
            logger.error(f"Failed to write model to MLflow: {e}")
            raise RuntimeError(f"MLflow model writing failed: {e}") from e

    def _validate_message(self, control_message: ControlMessage) -> None:
        """
        Validate ControlMessage format.

        Args:
            control_message: Message to validate

        Raises:
            ValueError: If message format is invalid
        """
        # Check if it's a ControlMessage (allow duck typing for import flexibility)
        if not hasattr(control_message, "get_metadata") or not hasattr(control_message, "has_metadata"):
            raise ValueError(
                f"Expected ControlMessage with get_metadata() and has_metadata() methods, got {type(control_message)}"
            )

        # Check user_id
        if not control_message.has_metadata("user_id"):
            raise ValueError("ControlMessage missing 'user_id' metadata")

        # Check model
        if not control_message.has_metadata("model"):
            raise ValueError("ControlMessage missing 'model' metadata")

        model = control_message.get_metadata("model")
        if model is None:
            raise ValueError("Model is None")

    def _get_model_name(self, user_id: str) -> str:
        """
        Generate model name from template.

        Following NVIDIA pattern: "DFP-{user_id}"

        Args:
            user_id: User identifier

        Returns:
            Formatted model name
        """
        try:
            model_name = self.model_name_template.format(user_id=user_id)
            return model_name
        except KeyError as e:
            raise ValueError(
                f"Invalid model_name_template: {self.model_name_template}. Missing placeholder: {e}"
            ) from e

    def _get_or_create_experiment(self) -> str:
        """
        Get or create MLflow experiment.

        Returns:
            Experiment ID
        """
        try:
            experiment = mlflow.get_experiment_by_name(self.experiment_name)
            if experiment is None:
                # Create experiment with custom artifact location to avoid experiment ID in path
                artifact_location = "data/mlflow"
                experiment_id = mlflow.create_experiment(self.experiment_name, artifact_location=artifact_location)
                logger.info(f"Created MLflow experiment: {self.experiment_name} (artifacts: {artifact_location})")
            else:
                experiment_id = experiment.experiment_id
                logger.debug(f"Using existing MLflow experiment: {self.experiment_name}")

            return experiment_id

        except Exception as e:
            raise RuntimeError(f"Failed to get/create MLflow experiment '{self.experiment_name}': {e}") from e

    def _log_model(self, model: Any, model_name: str, user_id: str) -> Any:
        """
        Log model to MLflow.

        Args:
            model: Trained model instance (DFPAutoEncoder)
            model_name: Model name for artifact path
            user_id: User identifier

        Returns:
            ModelInfo from mlflow.pytorch.log_model
        """
        try:
            # Get the underlying PyTorch model from DFPAutoEncoder wrapper
            if hasattr(model, "model") and model.model is not None:
                pytorch_model = model.model
            else:
                raise ValueError("Model has no 'model' attribute or is not trained")

            # Sanitize user_id for MLflow 3.x compatibility (no @, ., :, /, %, ", ')
            sanitized_user_id = sanitize_model_name(user_id)

            # Create model name (using 'name' parameter in MLflow 3.x)
            model_artifact_name = f"dfencoder-{sanitized_user_id}"

            logger.debug(f"Sanitized user_id '{user_id}' to '{sanitized_user_id}' for MLflow model name")

            # Prepare conda environment
            conda_env = self.conda_env
            if conda_env is None:
                # Default conda environment
                conda_env = {
                    "channels": ["defaults", "conda-forge", "pytorch"],
                    "dependencies": [
                        "python=3.10",
                        "pip",
                        {"pip": ["mlflow", "torch", "pandas", "numpy", "scikit-learn", "dfencoder"]},
                    ],
                    "name": "dfp_env",
                }

            # Create input example for model signature
            # pytorch_model is AutoEncoder, which has .model (AEModule) with encoder/decoder
            input_example = None
            signature = None
            try:
                # Access the AEModule inside AutoEncoder
                if hasattr(pytorch_model, "model") and pytorch_model.model is not None:
                    ae_module = pytorch_model.model

                    # AEModule has encoder as a list of CompleteLayer objects
                    if hasattr(ae_module, "encoder") and len(ae_module.encoder) > 0:
                        # Get the first layer (CompleteLayer)
                        first_layer = ae_module.encoder[0]

                        # CompleteLayer has a layers list with Linear as first element
                        if hasattr(first_layer, "layers") and len(first_layer.layers) > 0:
                            linear_layer = first_layer.layers[0]
                            if hasattr(linear_layer, "in_features"):
                                input_dim = linear_layer.in_features

                                # Create input and output examples for signature
                                input_array = np.random.randn(1, input_dim).astype(np.float32)
                                input_example = input_array  # noqa: F841 - prepared for future signature usage

                                # For autoencoder, output has same shape as input
                                output_array = np.random.randn(1, input_dim).astype(np.float32)

                                # Create signature manually
                                signature = infer_signature(input_array, output_array)

                                logger.info(
                                    f"Created model signature: input shape (1, {input_dim}), "
                                    f"output shape (1, {input_dim})"
                                )
            except Exception as e:
                logger.warning(f"Could not create model signature: {e}. Model will be logged without signature.")

            # Log model using MLflow 3.x API (name instead of artifact_path)
            log_model_kwargs = {"pytorch_model": pytorch_model, "name": model_artifact_name, "conda_env": conda_env}

            # Add signature if created
            # Note: We only provide signature without input_example to avoid validation
            # errors since AutoEncoder doesn't implement forward() method
            if signature is not None:
                log_model_kwargs["signature"] = signature
                logger.debug("Logging model with signature (without input_example to avoid validation)")

            model_info = mlflow.pytorch.log_model(**log_model_kwargs)  # type: ignore[attr-defined]

            logger.debug(f"Model logged with name: {model_artifact_name}, model_uri: {model_info.model_uri}")

            return model_info

        except Exception as e:
            raise RuntimeError(f"Failed to log model to MLflow: {e}") from e

    def _log_metrics_and_params(self, control_message: ControlMessage, user_id: str) -> None:
        """
        Log training metrics and parameters to MLflow following NVIDIA Morpheus DFP standard.

        NVIDIA Reference:
            nv-morpheus/python/morpheus/morpheus/controllers/mlflow_model_writer_controller.py
            Lines 259-281

        Logs NVIDIA-standard parameters:
            - Algorithm: Model type ("Denoising Autoencoder")
            - Epochs: Training epochs
            - Learning rate: Model learning rate
            - Batch size: Training batch size
            - Start Epoch: Min timestamp in training data
            - End Epoch: Max timestamp in training data
            - Log Count: Total training samples

        Logs NVIDIA-standard metrics:
            - embedding-{feature}-num_embeddings: Categorical feature embedding size
            - embedding-{feature}-embedding_dim: Embedding dimension

        Additional parameters (our enhancements):
            - user_id: User identifier (essential for multi-user tracking)
            - feature_count: Number of features

        Additional metrics (our enhancements):
            - train_split_samples: Training set size after split
            - val_split_samples: Validation set size after split

        Args:
            control_message: ControlMessage with training metadata
            user_id: User identifier
        """
        try:
            # Extract model from metadata
            model = control_message.get_metadata("model")
            if model is None:
                logger.warning("No model in metadata, skipping metrics/params logging")
                return

            # Get underlying dfencoder model
            dfencoder_model = model.get_model() if hasattr(model, "get_model") else model

            # --- NVIDIA STANDARD PARAMETERS ---

            # DEBUG: Check epochs in control message
            epochs_value = control_message.get_metadata("epochs")
            logger.info(
                f"DEBUG MLflow: control_message.get_metadata('epochs') = {epochs_value} (type: {type(epochs_value)})"
            )

            params = {
                # NVIDIA standard: Exact parameter names with exact casing
                "Algorithm": "Denoising Autoencoder",
                "Epochs": epochs_value,  # Use actual trained value (no hardcoded default)
                "Learning rate": getattr(dfencoder_model, "learning_rate", 0.01),  # NVIDIA default: 0.01
                "Batch size": getattr(dfencoder_model, "batch_size", 512),  # NVIDIA default: 512
            }

            # Timestamps from training data (NVIDIA standard)
            if control_message.has_metadata("start_timestamp"):
                start_ts = control_message.get_metadata("start_timestamp")
                # Convert to ISO string if it's a timestamp
                if hasattr(start_ts, "isoformat"):
                    params["Start Epoch"] = start_ts.isoformat()
                else:
                    params["Start Epoch"] = str(start_ts)

            if control_message.has_metadata("end_timestamp"):
                end_ts = control_message.get_metadata("end_timestamp")
                # Convert to ISO string if it's a timestamp
                if hasattr(end_ts, "isoformat"):
                    params["End Epoch"] = end_ts.isoformat()
                else:
                    params["End Epoch"] = str(end_ts)

            # Total sample count (NVIDIA standard)
            if control_message.has_metadata("total_samples"):
                params["Log Count"] = control_message.get_metadata("total_samples")
            elif control_message.has_metadata("train_samples"):
                # Fallback: sum train + val
                train_samples = control_message.get_metadata("train_samples", 0)
                val_samples = control_message.get_metadata("val_samples", 0)
                params["Log Count"] = train_samples + val_samples

            # --- OUR ADDITIONS (useful but not in NVIDIA) ---

            params["user_id"] = user_id  # Essential for multi-user tracking

            if control_message.has_metadata("feature_count"):
                params["feature_count"] = control_message.get_metadata("feature_count")

            # Log all parameters
            mlflow.log_params(params)

            # --- NVIDIA STANDARD METRICS: Embedding Dimensions ---

            metrics_dict = {}

            if hasattr(dfencoder_model, "categorical_fts"):
                cat_fts = dfencoder_model.categorical_fts
                if cat_fts:
                    logger.debug(f"Found {len(cat_fts)} categorical features for {user_id}")
                    for key, value in cat_fts.items():
                        if isinstance(value, dict):
                            embedding = value.get("embedding", None)
                            if embedding is not None and hasattr(embedding, "num_embeddings"):
                                # NVIDIA format: embedding-{feature_name}-{property}
                                metrics_dict[f"embedding-{key}-num_embeddings"] = float(embedding.num_embeddings)
                                metrics_dict[f"embedding-{key}-embedding_dim"] = float(embedding.embedding_dim)
                else:
                    logger.debug(f"No categorical features found for {user_id} - model may not use embeddings")

            # --- OUR ADDITIONS: Train/Val split sizes ---

            if control_message.has_metadata("train_samples"):
                # Renamed from 'train_samples' to clarify this is AFTER split
                metrics_dict["train_split_samples"] = float(control_message.get_metadata("train_samples"))

            if control_message.has_metadata("val_samples"):
                # Renamed from 'val_samples' to clarify this is AFTER split
                metrics_dict["val_split_samples"] = float(control_message.get_metadata("val_samples"))

            # Log all metrics
            if metrics_dict:
                mlflow.log_metrics(metrics_dict)

            logger.debug(
                f"Logged {len(params)} parameters and {len(metrics_dict)} metrics "
                f"for user_id={user_id} (NVIDIA-compliant)"
            )

        except Exception as e:
            logger.warning(f"Failed to log metrics/params: {e}")
            # Don't fail the entire operation if metrics logging fails

    def _tag_run(self, control_message: ControlMessage, user_id: str, model_name: str) -> None:
        """
        Tag MLflow run with metadata.

        Args:
            control_message: ControlMessage with metadata
            user_id: User identifier
            model_name: Model name
        """
        try:
            tags = {
                "user_id": user_id,
                "model_name": model_name,
                "timestamp": datetime.now().isoformat(),
                "pipeline_stage": "training",
            }

            mlflow.set_tags(tags)

            logger.debug(f"Tagged run with metadata for user_id={user_id}")

        except Exception as e:
            logger.warning(f"Failed to tag run: {e}")
            # Don't fail the entire operation if tagging fails

    def _register_model(self, model_uri: str, model_name: str, run_id: str) -> int:
        """
        Register model in MLflow Model Registry.

        Args:
            model_uri: Model URI from log_model
            model_name: Model name for registry
            run_id: MLflow run ID

        Returns:
            Model version number
        """
        try:
            # Register model (creates new version)
            model_version = mlflow.register_model(model_uri=model_uri, name=model_name)

            version_number = int(model_version.version)

            logger.info(f"Model registered: name={model_name}, version={version_number}, run_id={run_id}")

            return version_number

        except MlflowException as e:
            # Model might already be registered, just create new version
            logger.warning(f"Model registration warning: {e}")
            # Try to get latest version
            try:
                versions = self.client.search_model_versions(f"name='{model_name}'")
                if versions:
                    latest_version = max(int(v.version) for v in versions)
                    logger.info(f"Using existing model version: {latest_version}")
                    return latest_version
            except Exception as inner_e:
                logger.error(f"Failed to get model versions: {inner_e}")

            raise RuntimeError(f"Failed to register model: {e}") from e

    def write_batch(self, control_messages: list[ControlMessage]) -> list[ControlMessage]:
        """
        Write models for a batch of ControlMessages.

        This is a convenience method for processing multiple messages,
        commonly used in pipeline implementations.

        Args:
            control_messages: List of input ControlMessages with trained models

        Returns:
            List of output ControlMessages with MLflow metadata
        """
        output_messages = []

        for msg in control_messages:
            try:
                output_msg = self.write_model(msg)
                output_messages.append(output_msg)
            except Exception as e:
                logger.error(f"Failed to write model: {e}")
                # Continue processing remaining messages
                continue

        logger.info(
            f"Batch model writing complete: {len(output_messages)}/{len(control_messages)} models written successfully"
        )

        return output_messages
