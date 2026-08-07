"""
DFP Inference Module

This module performs inference using trained AutoEncoder models loaded from MLflow.
It supports per-user models with fallback to a generic model, following NVIDIA Morpheus DFP patterns.

Based on NVIDIA reference:
- python/morpheus_dfp/morpheus_dfp/modules/dfp_inference.py
- python/morpheus_dfp/morpheus_dfp/stages/dfp_inference_stage.py

Key Features:
- Load per-user models from MLflow Model Registry
- Fallback to generic model if user-specific model not found
- Compute anomaly scores using AutoEncoder.get_results()
- Add z-score columns: mean_abs_z, max_abs_z, per-feature z-scores
- Add model metadata: model_version (name:version format)

Author: Tomasz Zabek <tzabek@deloitte.co.uk>
Date: 2025-11-11
"""

import logging
import time
from pathlib import Path
from typing import Any

import mlflow
import pandas as pd
from mlflow.exceptions import MlflowException
from mlflow.tracking import MlflowClient

from modules.control.control_message import ControlMessage
from modules.dfencoder import AutoEncoder

logger = logging.getLogger(__name__)


class ModelCache:
    """
    Cache for loaded models with metadata.

    Following NVIDIA pattern from:
        nv-morpheus/python/morpheus_dfp/morpheus_dfp/utils/model_cache.py

    Attributes:
        reg_model_name: Registered model name in MLflow
        reg_model_version: Model version number
        model_uri: URI to load the model from
        load_time: Timestamp when model was loaded
        _model: Cached AutoEncoder instance (loaded lazily)
    """

    def __init__(self, reg_model_name: str, reg_model_version: str, model_uri: str):
        """
        Initialize ModelCache.

        Args:
            reg_model_name: Model name in MLflow Registry
            reg_model_version: Model version number
            model_uri: MLflow URI to load model from
        """
        self.reg_model_name = reg_model_name
        self.reg_model_version = reg_model_version
        self.model_uri = model_uri
        self.load_time = time.time()
        self._model: AutoEncoder | None = None

    def load_model(self) -> AutoEncoder:
        """
        Get the loaded model instance, loading from MLflow if not cached.

        Following NVIDIA pattern: Load PyTorch model directly via mlflow.pytorch.load_model()
        The pickled AutoEncoder object contains all feature information (numeric_fts,
        categorical_fts, etc.) and methods (prepare_df, get_results).

        Returns:
            AutoEncoder instance

        Raises:
            RuntimeError: If model fails to load
        """
        if self._model is None:
            logger.debug(f"Loading model '{self.reg_model_name}:{self.reg_model_version}' from {self.model_uri}")
            try:
                self._model = mlflow.pytorch.load_model(model_uri=self.model_uri)  # type: ignore[attr-defined]
                logger.debug("Model loaded successfully")
            except Exception as e:
                raise RuntimeError(f"Failed to load model from {self.model_uri}: {e}") from e

        # Type check: At this point _model should never be None
        if self._model is None:
            raise RuntimeError("Model loading succeeded but model is None")

        return self._model


class ModelManager:
    """
    Manages loading and caching of models from MLflow.

    Following NVIDIA pattern for model management with user-specific
    and generic fallback models.
    """

    def __init__(
        self, model_name_formatter: str = "DFP-{user_id}", cache_size_max: int = 10, cache_timeout_sec: float = 600.0
    ):
        """
        Initialize ModelManager.

        Args:
            model_name_formatter: Format string for model names (default: "DFP-{user_id}")
            cache_size_max: Maximum number of models to cache
            cache_timeout_sec: Cache timeout in seconds (default: 600 = 10 minutes)
        """
        self.model_name_formatter = model_name_formatter
        self.cache_size_max = cache_size_max
        self.cache_timeout_sec = cache_timeout_sec
        self._model_cache: dict[str, ModelCache] = {}

    def load_user_model(
        self, client: MlflowClient, user_id: str, fallback_user_ids: list[str] | None = None, timeout: float = 1.0
    ) -> ModelCache | None:
        """
        Load model for a specific user with fallback support.

        Following NVIDIA pattern:
        1. Try to load user-specific model
        2. If not found, try fallback users (e.g., generic_user)
        3. Return None if no model found

        Args:
            client: MLflow tracking client
            user_id: User identifier
            fallback_user_ids: List of fallback user IDs to try (default: ['generic_user'])
            timeout: Timeout for model loading (seconds)

        Returns:
            ModelCache instance or None if model not found
        """
        if fallback_user_ids is None:
            fallback_user_ids = ["generic_user"]

        # Try user-specific model first
        users_to_try = [user_id] + fallback_user_ids

        for try_user_id in users_to_try:
            # Check cache first
            cache_key = try_user_id
            if cache_key in self._model_cache:
                cached = self._model_cache[cache_key]
                # Check if cache is still valid
                cache_age = time.time() - cached.load_time
                if cache_age < self.cache_timeout_sec:
                    logger.debug(f"Using cached model for user_id='{try_user_id}' (age: {cache_age:.1f}s)")
                    return cached
                else:
                    # Cache expired, remove it
                    logger.debug(f"Cache expired for user_id='{try_user_id}' (age: {cache_age:.1f}s)")
                    del self._model_cache[cache_key]

            # Try to load from MLflow
            try:
                model_cache = self._load_from_mlflow(client, try_user_id, timeout)
                if model_cache is not None:
                    # Add to cache
                    self._add_to_cache(cache_key, model_cache)

                    if try_user_id == user_id:
                        logger.info(f"Loaded user-specific model for user_id='{user_id}'")
                    else:
                        logger.warning(
                            f"User-specific model not found for user_id='{user_id}', "
                            f"using fallback model for '{try_user_id}'"
                        )

                    return model_cache
            except Exception as e:
                logger.debug(f"Failed to load model for user_id='{try_user_id}': {e}")
                continue

        logger.error(f"No model found for user_id='{user_id}' or fallback users: {fallback_user_ids}")
        return None

    def _load_from_mlflow(self, client: MlflowClient, user_id: str, timeout: float) -> ModelCache | None:
        """
        Load model from MLflow Model Registry.

        Following NVIDIA pattern from:
            nv-morpheus/python/morpheus_dfp/morpheus_dfp/utils/model_cache.py
            ModelManager.load_model_cache() method

        Key differences from previous approach:
        1. Returns ModelCache with model_uri (lazy loading)
        2. Uses model version's source URI (UUID-based, avoids @ issues)
        3. No wrapping - AutoEncoder loaded directly via mlflow.pytorch.load_model()

        Args:
            client: MLflow tracking client
            user_id: User identifier
            timeout: Timeout for model loading

        Returns:
            ModelCache instance or None if model not found
        """
        start_time = time.time()

        try:
            # Format model name
            model_name = self.model_name_formatter.format(user_id=user_id)

            logger.debug(f"Searching for model '{model_name}' in MLflow registry...")

            # Get latest model version
            try:
                model_versions = client.search_model_versions(f"name='{model_name}'")

                if not model_versions:
                    logger.debug(f"No versions found for model '{model_name}'")
                    return None

                # Get latest version (NVIDIA uses get_latest_versions but search works too)
                latest_version = max(model_versions, key=lambda v: int(v.version))
                version_number = latest_version.version

                logger.debug(f"Found model '{model_name}' version {version_number}")

            except MlflowException as e:
                if e.error_code == "RESOURCE_DOES_NOT_EXIST":
                    logger.debug(f"Model '{model_name}' does not exist in registry")
                    return None
                raise

            # Check timeout
            elapsed = time.time() - start_time
            if elapsed > timeout:
                logger.warning(f"Model search timeout exceeded: {elapsed:.2f}s > {timeout}s for '{model_name}'")
                return None

            # NVIDIA pattern: Use latest_version.source (UUID-based URI)
            # This avoids issues with special characters in model names
            # Format: "models:/m-{uuid}" instead of "models:/DFP-user@domain.com/version"
            model_uri = latest_version.source
            if not model_uri:
                # Fallback to standard format if source is None
                model_uri = f"models:/{model_name}/{version_number}"

            logger.debug(f"Using model URI from version.source: {model_uri}")

            # Create cache entry (lazy loading - model loaded when load_model() is called)
            # NVIDIA pattern: ModelCache stores URI and loads on-demand
            model_cache = ModelCache(reg_model_name=model_name, reg_model_version=version_number, model_uri=model_uri)

            logger.info(f"Model '{model_name}:{version_number}' ready for loading")

            return model_cache

        except Exception as e:
            logger.error(f"Error searching for model user_id='{user_id}': {e}")
            return None

    def _add_to_cache(self, cache_key: str, model_cache: ModelCache) -> None:
        """
        Add model to cache with size management.

        Args:
            cache_key: Cache key (usually user_id)
            model_cache: ModelCache instance to cache
        """
        # Remove oldest entry if cache is full
        if len(self._model_cache) >= self.cache_size_max:
            # Find oldest entry
            oldest_key = min(self._model_cache.keys(), key=lambda k: self._model_cache[k].load_time)
            logger.debug(f"Cache full, removing oldest entry: '{oldest_key}'")
            del self._model_cache[oldest_key]

        # Add new entry
        self._model_cache[cache_key] = model_cache
        logger.debug(f"Added model to cache: '{cache_key}' (cache size: {len(self._model_cache)})")


class DFPInference:
    """
    DFP Inference Module - Performs inference using trained AutoEncoder models.

    This module is responsible for:
    1. Loading models from MLflow by user_id (with fallback)
    2. Running inference using AutoEncoder.get_results()
    3. Computing z-scores (mean_abs_z, max_abs_z, per-feature)
    4. Adding model metadata (model_version)
    5. Creating output ControlMessage with results

    Following NVIDIA pattern:
    - Input: ControlMessage with inference task
    - Processing: Load model → inference → compute z-scores
    - Output: ControlMessage with results DataFrame + metadata

    Reference:
        NVIDIA Morpheus dfp_inference.py module
    """

    def __init__(self, config: dict[str, Any]):
        """
        Initialize DFP Inference module.

        Args:
            config: Configuration dictionary with keys:
                - mlflow: MLflow configuration
                    - tracking_uri: MLflow tracking server URI
                    - model_name_formatter: Model name format (default: "DFP-{user_id}")
                - inference: Inference configuration
                    - fallback_username: Fallback user for generic model (default: "generic_user")
                    - model_fetch_timeout: Timeout for model loading (default: 1.0s)
                    - timestamp_column_name: Timestamp column name (default: "timestamp")

        Raises:
            ValueError: If required configuration keys are missing
        """
        self.config = config
        self._validate_config()

        # Extract configuration
        mlflow_config = config["mlflow"]
        inference_config = config.get("inference", {})

        self.tracking_uri = mlflow_config["tracking_uri"]
        self.model_name_formatter = mlflow_config.get("model_name_formatter", "DFP-{user_id}")
        self.fallback_username = inference_config.get("fallback_username", "generic_user")
        self.model_fetch_timeout = inference_config.get("model_fetch_timeout", 1.0)
        self.timestamp_column_name = inference_config.get("timestamp_column_name", "timestamp")

        # Set MLflow tracking URI globally (required for mlflow.pytorch.load_model)
        mlflow.set_tracking_uri(self.tracking_uri)

        # Initialize MLflow client
        self.client = MlflowClient(tracking_uri=self.tracking_uri)

        # Initialize model manager
        self.model_manager = ModelManager(model_name_formatter=self.model_name_formatter)

        logger.info(
            f"DFPInference initialized: tracking_uri={self.tracking_uri}, "
            f"fallback_user={self.fallback_username}, "
            f"model_fetch_timeout={self.model_fetch_timeout}s"
        )

        # Pre-warm the MLflow HTTP server connection.
        # The first search_model_versions call against an SQLite-backed MLflow
        # HTTP server takes 10-12s (SQLAlchemy connection-pool init + SQLite
        # page-cache cold start).  Paying that cost here — at pipeline init —
        # means the first real per-user inference request sees the warm server.
        self._prewarm_mlflow_connection()

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

    def _prewarm_mlflow_connection(self) -> None:
        """
        Issue a cheap MLflow query at startup to force SQLAlchemy connection-pool
        initialisation and bring the SQLite page-cache warm before the first real
        per-user inference request arrives.

        The MLflow HTTP server backed by SQLite can take 10-12 s on its very first
        search_model_versions call (connection-pool init + disk I/O).  Subsequent
        calls complete in <50 ms.  Running this once during pipeline init means
        every user sees the fast path at inference time.
        """
        import time as _time

        t0 = _time.time()
        try:
            # max_results=1 keeps the query cheap regardless of how many models exist
            self.client.search_model_versions("name like 'DFP-%'", max_results=1)
            logger.info(f"MLflow connection pre-warmed in {_time.time() - t0:.2f}s")
        except Exception as e:
            # Non-fatal: log and continue.  The first real inference will pay the
            # cold-start cost, but that is no worse than before this change.
            logger.warning(f"MLflow pre-warm query failed (non-fatal): {e}")

    def infer(self, control_message: ControlMessage) -> ControlMessage | None:
        """
        Perform inference on ControlMessage.

        This is the main entry point for inference. It:
        1. Validates message type and task
        2. Extracts user_id and inference data
        3. Loads model from MLflow (user-specific or generic fallback)
        4. Runs inference using AutoEncoder.get_results()
        5. Adds z-score columns and model metadata
        6. Creates output ControlMessage with results

        Args:
            control_message: Input ControlMessage with:
                - task: 'inference' task
                - metadata['user_id']: User identifier
                - payload: DataFrame with inference data

        Returns:
            ControlMessage with inference results (or None if inference fails)

        Raises:
            ValueError: If message format is invalid
            RuntimeError: If inference fails
        """
        try:
            # Validate message
            self._validate_message(control_message)

            # Extract user_id and data
            user_id = control_message.get_metadata("user_id")
            inference_data = self._extract_inference_data(control_message)

            logger.info(
                f"Running inference for user_id='{user_id}': "
                f"{len(inference_data)} samples, {len(inference_data.columns)} columns"
            )

            start_time = time.time()

            # Load model (user-specific or generic fallback)
            model_cache = self.model_manager.load_user_model(
                client=self.client,
                user_id=user_id,
                fallback_user_ids=[self.fallback_username],
                timeout=self.model_fetch_timeout,
            )

            if model_cache is None:
                raise RuntimeError(
                    f"Could not load model for user_id='{user_id}' or fallback user '{self.fallback_username}'"
                )

            post_model_time = time.time()

            # Get loaded model
            loaded_model = model_cache.load_model()

            # DEBUG: Log input features vs model vocabulary
            import sys

            if len(inference_data) > 0:
                last_row = inference_data.iloc[-1]
                debug_msg = f"\n{'=' * 60}\nDEBUG INPUT (LAST ROW) for {user_id}:\n"
                debug_msg += f"  appDisplayName: {last_row.get('appDisplayName', 'MISSING')}\n"
                debug_msg += f"  logcount: {last_row.get('logcount', 'MISSING')}\n"
                debug_msg += f"  logcount_incr: {last_row.get('logcount_incr', 'MISSING')}\n"

                # Check ALL categorical features
                for feat_name in [
                    "appDisplayName",
                    "clientAppUsed",
                    "deviceDetailbrowser",
                    "deviceDetaildisplayName",
                    "deviceDetailoperatingSystem",
                    "statusfailureReason",
                ]:
                    if feat_name in last_row:
                        actual_val = last_row.get(feat_name)
                        model_vocab = loaded_model.categorical_fts.get(feat_name, {}).get("cats", [])
                        in_vocab = actual_val in model_vocab if model_vocab else False
                        debug_msg += f"\n  {feat_name}:\n"
                        debug_msg += f"    Actual: '{actual_val}'\n"
                        debug_msg += f"    Model vocab: {model_vocab}\n"
                        debug_msg += f"    In vocab: {in_vocab}\n"

                Path("data/logs").mkdir(parents=True, exist_ok=True)
                with open("data/logs/debug-inference.log", "a") as f:
                    f.write(debug_msg)
                print(debug_msg, flush=True)
                sys.stdout.flush()

            # DEBUG: Check what data looks like for first vs last rows
            Path("data/logs").mkdir(parents=True, exist_ok=True)
            with open("data/logs/debug-inference.log", "a") as f:
                f.write(f"\nDEBUG INFERENCE INPUT DATA for {user_id}:\n")
                f.write(f"  Total rows: {len(inference_data)}\n")
                f.write("  First 3 rows device features:\n")
                for idx in range(min(3, len(inference_data))):
                    row = inference_data.iloc[idx]
                    f.write(
                        f"    Row {idx}: browser={row.get('deviceDetailbrowser')}, OS={row.get('deviceDetailoperatingSystem')}, logcount={row.get('logcount')}\n"
                    )
                f.write("  Last 3 rows device features:\n")
                for idx in range(max(0, len(inference_data) - 3), len(inference_data)):
                    row = inference_data.iloc[idx]
                    f.write(
                        f"    Row {idx}: browser={row.get('deviceDetailbrowser')}, OS={row.get('deviceDetailoperatingSystem')}, logcount={row.get('logcount')}\n"
                    )

            # Run inference using AutoEncoder.get_results()
            # This returns DataFrame with:
            # - mean_abs_z: Mean absolute z-score
            # - max_abs_z: Maximum absolute z-score
            # - <feature>_loss: Per-feature reconstruction loss
            # - <feature>_z_loss: Per-feature z-score
            # - <feature>_pred: Per-feature predicted value

            # DEBUG: Log input shape before inference
            Path("data/logs").mkdir(parents=True, exist_ok=True)
            with open("data/logs/debug-inference.log", "a") as f:
                f.write(f"\nCALLING model.get_results() for {user_id}:\n")
                f.write(f"  Input shape: {inference_data.shape}\n")
                f.write(f"  Input columns: {list(inference_data.columns)}\n")
                f.write(f"  Input dtypes: {dict(inference_data.dtypes)}\n")

            try:
                results_df = loaded_model.get_results(inference_data, return_abs=True)

                # DEBUG: Log output shape
                with open("data/logs/debug-inference.log", "a") as f:
                    f.write(f"  Results shape: {results_df.shape}\n")
                    f.write(f"  Results columns: {list(results_df.columns)}\n")

            except Exception as e:
                with open("data/logs/debug-inference.log", "a") as f:
                    f.write(f"  ERROR in get_results(): {type(e).__name__}: {e}\n")
                raise

            # DEBUG: Log ALL z-scores with actual vs predicted values
            if len(results_df) > 0:
                z_cols = [col for col in results_df.columns if col.endswith("_z_loss")]
                if z_cols and len(results_df) > 0:
                    last_row_results = results_df.iloc[-1]
                    last_row_input = inference_data.iloc[-1]
                    z_scores = {col: last_row_results[col] for col in z_cols}
                    sorted_z = sorted(z_scores.items(), key=lambda x: abs(x[1]), reverse=True)

                    debug_msg = f"\nDEBUG ALL Z-SCORES for {user_id} ({len(sorted_z)} total features):\n"
                    all_z_values = []
                    for feat, z in sorted_z:
                        feat_name = feat.replace("_z_loss", "")
                        loss_col = feat_name + "_loss"
                        pred_col = feat_name + "_pred"
                        loss_val = last_row_results.get(loss_col, "N/A")
                        actual_val = last_row_input.get(feat_name, "N/A")
                        pred_val = last_row_results.get(pred_col, "N/A")
                        all_z_values.append(abs(z))
                        debug_msg += f"  {feat_name}: z={z:.2f}, loss={loss_val}\n"
                        if feat_name in [
                            "statusfailureReason",
                            "deviceDetailbrowser",
                            "deviceDetailoperatingSystem",
                            "deviceDetaildisplayName",
                        ]:
                            debug_msg += f"    SINGLE-VALUED: actual={actual_val}, pred={pred_val}\n"

                    manual_mean = sum(all_z_values) / len(all_z_values) if all_z_values else 0
                    reported_mean = last_row_results.get("mean_abs_z", "N/A")
                    debug_msg += "\nZ-SCORE STATISTICS:\n"
                    debug_msg += f"  Manual mean: {manual_mean:.4f}\n"
                    debug_msg += f"  Model mean_abs_z: {reported_mean}\n"
                    debug_msg += f"  Feature count: {len(all_z_values)}\n"
                    debug_msg += f"{'=' * 60}\n"

                    with open("data/logs/debug-inference.log", "a") as f:
                        f.write(debug_msg)
                    print(debug_msg, flush=True)
                    sys.stdout.flush()

            # Get columns that are not in original data
            results_cols = list(set(results_df.columns) - set(inference_data.columns))

            # Merge results with original data
            output_df = pd.concat([inference_data, results_df[results_cols]], axis=1)

            # Add model version column
            model_version_str = f"{model_cache.reg_model_name}:{model_cache.reg_model_version}"
            output_df["model_version"] = model_version_str

            # Create output message
            output_message = self._create_output_message(
                results_df=output_df, user_id=user_id, model_version=model_version_str, original_message=control_message
            )

            # Log timing
            if logger.isEnabledFor(logging.DEBUG):
                load_model_duration = (post_model_time - start_time) * 1000.0
                inference_duration = (time.time() - post_model_time) * 1000.0

                logger.debug(
                    f"Inference complete for user_id='{user_id}': "
                    f"Model load: {load_model_duration:.1f}ms, "
                    f"Inference: {inference_duration:.1f}ms, "
                    f"Time range: {inference_data[self.timestamp_column_name].min()} - "
                    f"{inference_data[self.timestamp_column_name].max()}"
                )

            logger.info(
                f"Inference complete for user_id='{user_id}': "
                f"{len(output_df)} results with {len(results_cols)} z-score columns"
            )

            return output_message

        except Exception as e:
            logger.error(f"Inference failed for control message: {e}")
            raise RuntimeError(f"Inference failed: {e}") from e

    def _validate_message(self, control_message: ControlMessage) -> None:
        """
        Validate ControlMessage format.

        Args:
            control_message: Message to validate

        Raises:
            ValueError: If message format is invalid
        """
        # Check if it's a ControlMessage
        if not hasattr(control_message, "get_metadata") or not hasattr(control_message, "payload"):
            raise ValueError(
                f"Expected ControlMessage with get_metadata() and payload() methods, got {type(control_message)}"
            )

        # Check if 'inference' task exists
        has_inference = control_message.has_task("inference")
        if not has_inference:
            tasks = control_message.get_tasks()
            raise ValueError(f"Expected 'inference' task, got task types: {list(tasks.keys())}")

        # Check user_id
        if not control_message.has_metadata("user_id"):
            raise ValueError("ControlMessage missing 'user_id' metadata")

        # Check payload
        if control_message.payload() is None:
            raise ValueError("ControlMessage has no payload")

    def _extract_inference_data(self, control_message: ControlMessage) -> pd.DataFrame:
        """
        Extract inference data from ControlMessage payload.

        Args:
            control_message: Input message

        Returns:
            Inference DataFrame

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
            raise ValueError("Inference data is empty")

        return df

    def _create_output_message(
        self, results_df: pd.DataFrame, user_id: str, model_version: str, original_message: ControlMessage
    ) -> ControlMessage:
        """
        Create output ControlMessage with inference results.

        Args:
            results_df: Results DataFrame with z-scores
            user_id: User identifier
            model_version: Model version string (name:version)
            original_message: Input ControlMessage

        Returns:
            Output ControlMessage with results
        """
        # Create output message
        output_message = ControlMessage()

        # Copy user_id metadata
        output_message.set_metadata("user_id", user_id)

        # Add model metadata
        output_message.set_metadata("model_version", model_version)

        # Set payload with results
        output_message.payload(results_df)  # setter

        # Remove inference task (completed)
        # Note: In a full pipeline, downstream stages might add new tasks

        return output_message

    def infer_batch(self, control_messages: list[ControlMessage]) -> list[ControlMessage]:
        """
        Perform inference for a batch of ControlMessages.

        This is a convenience method for processing multiple messages,
        commonly used in pipeline implementations.

        Args:
            control_messages: List of input ControlMessages

        Returns:
            List of output ControlMessages with inference results
            Note: Messages that fail inference are filtered out
        """
        output_messages = []

        for msg in control_messages:
            try:
                output_msg = self.infer(msg)
                if output_msg is not None:
                    output_messages.append(output_msg)
            except Exception as e:
                logger.error(f"Failed to process message: {e}")
                # Continue processing remaining messages
                continue

        logger.info(
            f"Batch inference complete: {len(output_messages)}/{len(control_messages)} messages processed successfully"
        )

        return output_messages
