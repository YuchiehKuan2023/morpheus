"""
MLflow utilities for DFP PoC.

This module provides utilities for MLflow integration including:
    - Experiment and run management
    - Model registration and versioning
    - Metric and parameter logging
    - Model loading with user-specific fallback

Reference:
    - NVIDIA Morpheus MLflow patterns
    - MLflow documentation: https://mlflow.org/docs/latest/index.html
"""

import logging
from typing import Any

import mlflow
from mlflow.entities import Run
from mlflow.tracking import MlflowClient

# Import pytorch module conditionally to handle type checking
try:
    import mlflow.pytorch as mlflow_pytorch
except (ImportError, AttributeError):
    mlflow_pytorch = None  # type: ignore

# Get logger
logger = logging.getLogger("dfp.mlflow")


class MLflowManager:
    """
    Manager for MLflow operations.

    Handles experiment creation, run management, model logging,
    and model retrieval with user-specific fallback logic.
    """

    def __init__(
        self,
        tracking_uri: str = "http://localhost:5001",
        experiment_name: str | None = None,
        artifact_location: str | None = None,
    ):
        """
        Initialize MLflow manager.

        Args:
            tracking_uri: MLflow tracking server URI
            experiment_name: Name of the experiment
            artifact_location: Path for artifact storage

        Example:
            >>> manager = MLflowManager(
            ...     tracking_uri="http://localhost:5001",
            ...     experiment_name="dfp_training"
            ... )
        """
        self.tracking_uri = tracking_uri
        self.experiment_name = experiment_name
        self.artifact_location = artifact_location

        # Set tracking URI
        mlflow.set_tracking_uri(tracking_uri)
        logger.info(f"MLflow tracking URI set to: {tracking_uri}")

        # Initialize client
        self.client = MlflowClient(tracking_uri=tracking_uri)

        # Create or get experiment
        if experiment_name:
            self.experiment_id = self._get_or_create_experiment(experiment_name)
        else:
            self.experiment_id = None

    def _get_or_create_experiment(self, experiment_name: str) -> str:
        """
        Get existing experiment or create new one.

        Args:
            experiment_name: Name of the experiment

        Returns:
            Experiment ID
        """
        experiment = self.client.get_experiment_by_name(experiment_name)

        if experiment is None:
            # Create experiment
            experiment_id = self.client.create_experiment(
                name=experiment_name, artifact_location=self.artifact_location
            )
            logger.info(f"Created new experiment: {experiment_name} (ID: {experiment_id})")
        else:
            experiment_id = experiment.experiment_id
            logger.info(f"Using existing experiment: {experiment_name} (ID: {experiment_id})")

        return experiment_id

    def start_run(self, run_name: str | None = None, tags: dict[str, str] | None = None, nested: bool = False) -> Run:
        """
        Start a new MLflow run.

        Args:
            run_name: Name for the run
            tags: Dictionary of tags to attach to the run
            nested: Whether this is a nested run

        Returns:
            MLflow Run object

        Example:
            >>> manager.start_run(run_name="training_user123", tags={"user_id": "user123"})
        """
        run = mlflow.start_run(experiment_id=self.experiment_id, run_name=run_name, tags=tags, nested=nested)

        logger.debug(f"Started MLflow run: {run.info.run_id}")
        return run

    def end_run(self, status: str = "FINISHED"):
        """
        End the current MLflow run.

        Args:
            status: Run status ("FINISHED", "FAILED", "KILLED")

        Example:
            >>> manager.end_run(status="FINISHED")
        """
        mlflow.end_run(status=status)
        logger.debug(f"Ended MLflow run with status: {status}")

    def log_params(self, params: dict[str, Any]):
        """
        Log parameters to current run.

        Args:
            params: Dictionary of parameters

        Example:
            >>> manager.log_params({"epochs": 50, "batch_size": 32})
        """
        mlflow.log_params(params)
        logger.debug(f"Logged {len(params)} parameters")

    def log_param(self, key: str, value: Any):
        """
        Log a single parameter.

        Args:
            key: Parameter name
            value: Parameter value
        """
        mlflow.log_param(key, value)

    def log_metrics(self, metrics: dict[str, float], step: int | None = None):
        """
        Log metrics to current run.

        Args:
            metrics: Dictionary of metrics
            step: Optional step number (for iterative processes)

        Example:
            >>> manager.log_metrics({"loss": 0.5, "accuracy": 0.95}, step=10)
        """
        mlflow.log_metrics(metrics, step=step)
        logger.debug(f"Logged {len(metrics)} metrics")

    def log_metric(self, key: str, value: float, step: int | None = None):
        """
        Log a single metric.

        Args:
            key: Metric name
            value: Metric value
            step: Optional step number
        """
        mlflow.log_metric(key, value, step=step)

    def log_artifact(self, local_path: str, artifact_path: str | None = None):
        """
        Log a file or directory as an artifact.

        Args:
            local_path: Path to local file or directory
            artifact_path: Path within artifact store

        Example:
            >>> manager.log_artifact("model/config.yaml", artifact_path="config")
        """
        mlflow.log_artifact(local_path, artifact_path=artifact_path)
        logger.debug(f"Logged artifact: {local_path}")

    def log_artifacts(self, local_dir: str, artifact_path: str | None = None):
        """
        Log a directory of artifacts.

        Args:
            local_dir: Path to local directory
            artifact_path: Path within artifact store
        """
        mlflow.log_artifacts(local_dir, artifact_path=artifact_path)
        logger.debug(f"Logged artifacts from: {local_dir}")

    def log_model(self, model: Any, artifact_path: str, registered_model_name: str | None = None, **kwargs) -> Any:
        """
        Log a PyTorch model.

        Args:
            model: PyTorch model to log
            artifact_path: Path within artifact store
            registered_model_name: Name for model registry
            **kwargs: Additional arguments for mlflow.pytorch.log_model

        Returns:
            Model info

        Example:
            >>> manager.log_model(
            ...     model=autoencoder,
            ...     artifact_path="model",
            ...     registered_model_name="dfencoder_dfp"
            ... )
        """
        if mlflow_pytorch is None:
            raise ImportError("mlflow.pytorch module is required for logging PyTorch models")

        model_info = mlflow_pytorch.log_model(
            pytorch_model=model, artifact_path=artifact_path, registered_model_name=registered_model_name, **kwargs
        )

        logger.info(f"Logged model: {artifact_path}")
        if registered_model_name:
            logger.info(f"Registered model: {registered_model_name}")

        return model_info

    def register_model(self, model_uri: str, model_name: str, tags: dict[str, str] | None = None):
        """
        Register a model in the model registry.

        Args:
            model_uri: URI of the model (e.g., "runs:/<run_id>/model")
            model_name: Name for the registered model
            tags: Tags to attach to the model version

        Returns:
            Model version

        Example:
            >>> manager.register_model(
            ...     model_uri="runs:/<run_id>/model",
            ...     model_name="dfencoder_user123",
            ...     tags={"user_id": "user123"}
            ... )
        """
        model_version = mlflow.register_model(model_uri, model_name)

        # Add tags if provided
        if tags:
            for key, value in tags.items():
                self.client.set_model_version_tag(name=model_name, version=model_version.version, key=key, value=value)

        logger.info(f"Registered model {model_name} version {model_version.version}")
        return model_version

    def load_model(self, model_name: str, version: int | str | None = None, stage: str | None = None) -> Any:
        """
        Load a model from the model registry.

        Args:
            model_name: Name of the registered model
            version: Model version (number or "latest")
            stage: Model stage ("Staging", "Production", "Archived")

        Returns:
            Loaded model

        Example:
            >>> model = manager.load_model("dfencoder_dfp", version="latest")
            >>> model = manager.load_model("dfencoder_dfp", stage="Production")
        """
        if mlflow_pytorch is None:
            raise ImportError("mlflow.pytorch module is required for loading PyTorch models")

        if stage:
            model_uri = f"models:/{model_name}/{stage}"
        elif version:
            model_uri = f"models:/{model_name}/{version}"
        else:
            model_uri = f"models:/{model_name}/latest"

        logger.info(f"Loading model from: {model_uri}")
        model = mlflow_pytorch.load_model(model_uri)

        return model

    def load_model_for_user(
        self,
        base_model_name: str,
        user_id: str | None = None,
        version: int | str | None = "latest",
        fallback_to_generic: bool = True,
    ) -> Any:
        """
        Load a user-specific model with fallback to generic model.

        This implements the DFP pattern where each user can have their own model,
        but falls back to a generic model if a user-specific model doesn't exist.

        Args:
            base_model_name: Base name for models (e.g., "dfencoder_dfp")
            user_id: User ID for user-specific model
            version: Model version to load
            fallback_to_generic: Whether to fallback to generic model

        Returns:
            Loaded model

        Example:
            >>> model = manager.load_model_for_user(
            ...     base_model_name="dfencoder_dfp",
            ...     user_id="user123",
            ...     fallback_to_generic=True
            ... )
        """
        # Try to load user-specific model first
        if user_id:
            user_model_name = f"{base_model_name}_user_{user_id}"
            try:
                model = self.load_model(user_model_name, version=version)
                logger.info(f"Loaded user-specific model for {user_id}")
                return model
            except Exception as e:
                logger.warning(f"User-specific model not found for {user_id}: {e}")

        # Fallback to generic model
        if fallback_to_generic:
            generic_model_name = f"{base_model_name}_generic"
            try:
                model = self.load_model(generic_model_name, version=version)
                logger.info("Loaded generic fallback model")
                return model
            except Exception as e:
                logger.error(f"Generic model not found: {e}")
                raise ValueError(f"Could not load model for user {user_id} and no generic model available") from e

        raise ValueError(f"Could not load model for user {user_id}")

    def get_run(self, run_id: str) -> Run:
        """Get a run by ID."""
        return self.client.get_run(run_id)

    def search_runs(
        self, filter_string: str | None = None, max_results: int = 1000, order_by: list[str] | None = None
    ) -> list[Run]:
        """
        Search for runs in the experiment.

        Args:
            filter_string: Filter query string
            max_results: Maximum number of results
            order_by: List of order by clauses

        Returns:
            List of matching runs

        Example:
            >>> runs = manager.search_runs(
            ...     filter_string="metrics.loss < 0.5",
            ...     order_by=["metrics.loss ASC"]
            ... )
        """
        return self.client.search_runs(
            experiment_ids=[self.experiment_id] if self.experiment_id else [],
            filter_string=filter_string if filter_string is not None else "",
            max_results=max_results,
            order_by=order_by,
        )

    def delete_run(self, run_id: str):
        """Delete a run."""
        self.client.delete_run(run_id)
        logger.info(f"Deleted run: {run_id}")

    def set_experiment_tag(self, key: str, value: str):
        """Set a tag on the experiment."""
        if self.experiment_id:
            self.client.set_experiment_tag(self.experiment_id, key, value)

    def set_run_tag(self, key: str, value: str):
        """Set a tag on the current run."""
        mlflow.set_tag(key, value)


# Convenience functions
def init_mlflow(
    tracking_uri: str = "http://localhost:5001",
    experiment_name: str | None = None,
    artifact_location: str | None = None,
) -> MLflowManager:
    """
    Initialize MLflow manager.

    Args:
        tracking_uri: MLflow tracking server URI
        experiment_name: Name of the experiment
        artifact_location: Path for artifact storage

    Returns:
        MLflowManager instance

    Example:
        >>> mlflow_manager = init_mlflow(
        ...     tracking_uri="http://localhost:5001",
        ...     experiment_name="dfp_training"
        ... )
    """
    return MLflowManager(
        tracking_uri=tracking_uri, experiment_name=experiment_name, artifact_location=artifact_location
    )


def log_model_metadata(
    user_id: str | None = None,
    model_type: str = "user_specific",
    feature_columns: list[str] | None = None,
    **kwargs,
):
    """
    Log model metadata as parameters.

    Args:
        user_id: User ID for user-specific models
        model_type: Type of model ("user_specific" or "generic")
        feature_columns: List of feature column names
        **kwargs: Additional metadata to log

    Example:
        >>> log_model_metadata(
        ...     user_id="user123",
        ...     model_type="user_specific",
        ...     feature_columns=["hour", "dayofweek"],
        ...     training_samples=1000
        ... )
    """
    metadata = {"model_type": model_type, **kwargs}

    if user_id:
        metadata["user_id"] = user_id

    if feature_columns:
        metadata["feature_columns"] = ",".join(feature_columns)
        metadata["num_features"] = len(feature_columns)

    mlflow.log_params(metadata)


def log_baseline_statistics(
    mean_error: float,
    std_error: float,
    min_error: float,
    max_error: float,
    percentiles: dict[int, float] | None = None,
):
    """
    Log baseline reconstruction error statistics.

    These statistics are used for z-score calculation during inference.

    Args:
        mean_error: Mean reconstruction error
        std_error: Standard deviation of reconstruction error
        min_error: Minimum reconstruction error
        max_error: Maximum reconstruction error
        percentiles: Dictionary of percentile values

    Example:
        >>> log_baseline_statistics(
        ...     mean_error=0.05,
        ...     std_error=0.02,
        ...     min_error=0.01,
        ...     max_error=0.15,
        ...     percentiles={95: 0.09, 99: 0.12}
        ... )
    """
    metrics = {
        "baseline_mean_error": mean_error,
        "baseline_std_error": std_error,
        "baseline_min_error": min_error,
        "baseline_max_error": max_error,
    }

    if percentiles:
        for p, value in percentiles.items():
            metrics[f"baseline_p{p}_error"] = value

    mlflow.log_metrics(metrics)


def log_training_summary(
    epochs: int,
    final_train_loss: float,
    final_val_loss: float,
    best_epoch: int | None = None,
    training_time: float | None = None,
):
    """
    Log training summary metrics.

    Args:
        epochs: Total number of epochs trained
        final_train_loss: Final training loss
        final_val_loss: Final validation loss
        best_epoch: Epoch with best validation loss
        training_time: Total training time in seconds

    Example:
        >>> log_training_summary(
        ...     epochs=50,
        ...     final_train_loss=0.05,
        ...     final_val_loss=0.06,
        ...     best_epoch=45,
        ...     training_time=120.5
        ... )
    """
    summary = {
        "total_epochs": epochs,
        "final_train_loss": final_train_loss,
        "final_val_loss": final_val_loss,
    }

    if best_epoch is not None:
        summary["best_epoch"] = best_epoch

    if training_time is not None:
        summary["training_time_seconds"] = training_time
        summary["time_per_epoch"] = training_time / epochs if epochs > 0 else 0

    mlflow.log_metrics(summary)


def log_inference_summary(
    num_samples: int,
    num_anomalies: int,
    inference_time: float,
    mean_reconstruction_error: float,
    std_reconstruction_error: float,
):
    """
    Log inference summary metrics.

    Args:
        num_samples: Number of samples processed
        num_anomalies: Number of anomalies detected
        inference_time: Total inference time in seconds
        mean_reconstruction_error: Mean reconstruction error
        std_reconstruction_error: Std of reconstruction error

    Example:
        >>> log_inference_summary(
        ...     num_samples=1000,
        ...     num_anomalies=15,
        ...     inference_time=10.5,
        ...     mean_reconstruction_error=0.05,
        ...     std_reconstruction_error=0.02
        ... )
    """
    anomaly_rate = (num_anomalies / num_samples * 100) if num_samples > 0 else 0
    throughput = num_samples / inference_time if inference_time > 0 else 0

    summary = {
        "num_samples": num_samples,
        "num_anomalies": num_anomalies,
        "anomaly_rate_percent": anomaly_rate,
        "inference_time_seconds": inference_time,
        "throughput_samples_per_sec": throughput,
        "mean_reconstruction_error": mean_reconstruction_error,
        "std_reconstruction_error": std_reconstruction_error,
    }

    mlflow.log_metrics(summary)
