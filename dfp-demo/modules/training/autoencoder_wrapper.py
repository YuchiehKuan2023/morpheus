"""
DFP AutoEncoder Wrapper Module

This module provides a wrapper around the NVIDIA Morpheus dfencoder AutoEncoder
to simplify configuration and usage within the DFP training pipeline.

Based on NVIDIA reference:
- python/morpheus/morpheus/models/dfencoder/autoencoder.py
- examples/digital_fingerprinting/production/morpheus/dfp_*.py

Author: Tomasz Zabek <tzabek@deloitte.co.uk>
Date: 2025-11-11
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

import numpy as np
import pandas as pd

if TYPE_CHECKING:
    from modules.dfencoder import AutoEncoder

logger = logging.getLogger(__name__)


class DFPAutoEncoder:
    """
    Wrapper class for NVIDIA Morpheus dfencoder AutoEncoder.

    This wrapper simplifies configuration by:
    1. Loading NVIDIA-aligned defaults from config YAML
    2. Providing convenience methods for training and inference
    3. Handling feature selection and validation
    4. Managing model state and metadata

    The underlying AutoEncoder is a denoising autoencoder that:
    - Automatically handles numerical (MSE), binary (BCE), and categorical (CCE) features
    - Uses swap_probability for robustness training
    - Computes per-feature reconstruction losses for anomaly scoring
    - Supports early stopping with validation monitoring

    Architecture:
        Input → Encoder (compression) → Latent Space → Decoder (reconstruction) → Output

    Loss Calculation:
        total_loss = MSE(numerical) + BCE(binary) + CCE(categorical)
        anomaly_score = mean(per_feature_losses)

    Reference:
        NVIDIA Morpheus dfencoder documentation and source code
    """

    def __init__(self, config: dict[str, Any]):
        """
        Initialize DFP AutoEncoder with configuration.

        Args:
            config: Configuration dictionary with model parameters
                Required keys:
                    - encoder_layers: List of encoder layer sizes (e.g., [512, 500])
                    - decoder_layers: List of decoder layer sizes (e.g., [512])
                    - feature_columns: List of feature column names
                Optional keys (with NVIDIA defaults):
                    - activation: Activation function ('relu', 'tanh', 'sigmoid') [default: 'relu']
                    - swap_probability: Denoising swap probability [default: 0.2]
                    - learning_rate: Training learning rate [default: 0.01]
                    - learning_rate_decay: LR decay per epoch [default: 0.99]
                    - batch_size: Training batch size [default: 512]
                    - eval_batch_size: Evaluation batch size [default: 1024]
                    - optimizer: Optimizer ('sgd', 'adam') [default: 'sgd']
                    - scaler: Feature scaler ('standard', 'gauss_rank', 'modified') [default: 'standard']
                    - min_cats: Minimum category frequency [default: 1]
                    - patience: Early stopping patience [default: 5]
                    - device: Compute device ('cuda', 'cpu') [default: 'cpu']
                    - loss_scaler: Loss scaling for z-score ('standard', 'gauss_rank') [default: 'standard']

        Raises:
            ImportError: If dfencoder package is not installed
            ValueError: If required config keys are missing
        """
        self.config = config
        self._validate_config()

        # Import dfencoder from our local copy (NVIDIA source)
        from modules.dfencoder import AutoEncoder as AutoEncoderClass

        self.AutoEncoder = AutoEncoderClass
        logger.info("Using NVIDIA dfencoder (local copy, CPU-compatible)")

        # Extract configuration with NVIDIA defaults
        self.encoder_layers = config["encoder_layers"]
        self.decoder_layers = config["decoder_layers"]
        self.feature_columns = config["feature_columns"]

        # Optional parameters with NVIDIA defaults
        self.activation = config.get("activation", "relu")
        self.swap_probability = config.get("swap_probability", 0.2)
        self.learning_rate = config.get("learning_rate", 0.01)  # NVIDIA default: 0.01 for SGD
        self.learning_rate_decay = config.get("learning_rate_decay", 0.99)
        self.batch_size = config.get("batch_size", 512)
        self.eval_batch_size = config.get("eval_batch_size", 1024)
        self.optimizer = config.get("optimizer", "sgd")
        self.scaler = config.get("scaler", "standard")
        self.min_cats = config.get("min_cats", 1)
        self.patience = config.get("patience", 5)
        self.device = config.get("device", "cpu")
        self.loss_scaler = config.get("loss_scaler", "standard")

        # Model instance (created on first fit)
        # Type hint as AutoEncoder for proper type checking
        self._model: AutoEncoder | None = None

        logger.info(
            f"DFPAutoEncoder initialized: "
            f"encoder={self.encoder_layers}, decoder={self.decoder_layers}, "
            f"features={len(self.feature_columns)}, device={self.device}"
        )

    def _validate_config(self) -> None:
        """
        Validate configuration dictionary.

        Raises:
            ValueError: If required keys are missing or invalid
        """
        required_keys = ["encoder_layers", "decoder_layers", "feature_columns"]
        missing_keys = [key for key in required_keys if key not in self.config]

        if missing_keys:
            raise ValueError(f"Missing required configuration keys: {missing_keys}. Required: {required_keys}")

        if not isinstance(self.config["encoder_layers"], list):
            raise ValueError("encoder_layers must be a list of integers")

        if not isinstance(self.config["decoder_layers"], list):
            raise ValueError("decoder_layers must be a list of integers")

        if not self.config["encoder_layers"]:
            raise ValueError("encoder_layers cannot be empty")

        if not self.config["decoder_layers"]:
            raise ValueError("decoder_layers cannot be empty")

        if not isinstance(self.config["feature_columns"], list):
            raise ValueError("feature_columns must be a list of strings")

        if not self.config["feature_columns"]:
            raise ValueError("feature_columns cannot be empty")

    def fit(
        self,
        training_data: pd.DataFrame,
        epochs: int = 50,
        validation_data: pd.DataFrame | None = None,
        run_validation: bool = True,
        use_val_for_loss_stats: bool = True,
    ) -> None:
        """
        Train the AutoEncoder model.

        This method creates a new AutoEncoder instance and trains it on the provided data.
        Following NVIDIA best practices:
        - Uses validation data for early stopping
        - Computes loss statistics on validation set (use_val_for_loss_stats=True)
        - Monitors validation loss for patience-based stopping

        Args:
            training_data: Training DataFrame (must contain feature_columns)
            epochs: Number of training epochs [default: 50]
            validation_data: Optional validation DataFrame for early stopping
            run_validation: Whether to run validation during training [default: True]
            use_val_for_loss_stats: Use validation set for loss normalization [default: True]
                NVIDIA recommends True for better anomaly detection

        Raises:
            ValueError: If training_data is missing required columns
            RuntimeError: If training fails
        """
        # Validate feature columns
        missing_cols = set(self.feature_columns) - set(training_data.columns)
        if missing_cols:
            raise ValueError(f"Training data missing required feature columns: {missing_cols}")

        # Select feature columns
        train_features = training_data[self.feature_columns]
        val_features = validation_data[self.feature_columns] if validation_data is not None else None

        logger.info(
            f"Training AutoEncoder: {len(train_features)} train samples, "
            f"{len(val_features) if val_features is not None else 0} validation samples, "
            f"{len(self.feature_columns)} features, {epochs} epochs"
        )

        try:
            # Create AutoEncoder instance with NVIDIA API
            self._model = self.AutoEncoder(
                encoder_layers=self.encoder_layers,
                decoder_layers=self.decoder_layers,
                activation=self.activation,
                swap_probability=self.swap_probability,
                learning_rate=self.learning_rate,
                learning_rate_decay=self.learning_rate_decay,
                batch_size=self.batch_size,
                eval_batch_size=self.eval_batch_size,
                optimizer=self.optimizer,
                scaler=self.scaler,
                min_cats=self.min_cats,
                patience=self.patience,
                device=self.device,
                loss_scaler=self.loss_scaler,
                verbose=False,  # Use logging instead
            )

            # Type narrowing: assert model is not None
            assert self._model is not None, "Model initialization failed"

            # Train model with NVIDIA API
            self._model.fit(
                train_features,
                epochs=epochs,
                validation_data=val_features,
                run_validation=run_validation,
                use_val_for_loss_stats=use_val_for_loss_stats,
            )

            logger.info(
                f"Training complete. Model trained on {len(train_features)} samples "
                f"with {len(self.feature_columns)} features."
            )

        except Exception as e:
            logger.error(f"Training failed: {e}")
            raise RuntimeError(f"AutoEncoder training failed: {e}") from e

    def get_anomaly_score(self, data: pd.DataFrame) -> np.ndarray:
        """
        Compute anomaly scores (mean reconstruction loss per row).

        This method computes the mean of all per-feature reconstruction losses,
        providing a single anomaly score per row. Lower scores indicate more
        normal behavior; higher scores indicate anomalous behavior.

        Args:
            data: Input DataFrame (must contain feature_columns)

        Returns:
            NumPy array of anomaly scores (one per row)

        Raises:
            ValueError: If model is not trained or data is missing columns
        """
        self._check_model_trained()

        # Type narrowing: assert model is trained
        assert self._model is not None, "Model should be trained at this point"

        # Validate feature columns
        missing_cols = set(self.feature_columns) - set(data.columns)
        if missing_cols:
            raise ValueError(f"Data missing required feature columns: {missing_cols}")

        # Select feature columns
        features = data[self.feature_columns]

        try:
            scores = self._model.get_anomaly_score(features)
            logger.debug(f"Computed anomaly scores for {len(scores)} samples")
            return scores
        except Exception as e:
            logger.error(f"Anomaly scoring failed: {e}")
            raise RuntimeError(f"Failed to compute anomaly scores: {e}") from e

    def get_results(self, data: pd.DataFrame, return_abs: bool = True) -> pd.DataFrame:
        """
        Get detailed results with per-feature losses and z-scores.

        This method returns a comprehensive DataFrame containing:
        - mean_abs_z: Mean absolute z-score (primary anomaly metric)
        - max_abs_z: Maximum absolute z-score across features
        - Per-feature z-scores (one column per feature)

        Note: This method is only available with NVIDIA Morpheus dfencoder.
        For standalone dfencoder, only anomaly scores are available via get_anomaly_score().

        Args:
            data: Input DataFrame (must contain feature_columns)
            return_abs: Return absolute values of z-scores [default: True]

        Returns:
            DataFrame with anomaly metrics and per-feature z-scores

        Raises:
            ValueError: If model is not trained or data is missing columns
        """
        self._check_model_trained()

        # Type narrowing: assert model is trained
        assert self._model is not None, "Model should be trained at this point"

        # Validate feature columns
        missing_cols = set(self.feature_columns) - set(data.columns)
        if missing_cols:
            raise ValueError(f"Data missing required feature columns: {missing_cols}")

        # Select feature columns
        features = data[self.feature_columns]

        try:
            results = self._model.get_results(features, return_abs=return_abs)
            logger.debug(
                f"Computed detailed results for {len(results)} samples "
                f"with {len(self.feature_columns)} feature z-scores"
            )
            return results
        except Exception as e:
            logger.error(f"Results computation failed: {e}")
            raise RuntimeError(f"Failed to compute results: {e}") from e

    def _check_model_trained(self) -> None:
        """
        Check if model has been trained.

        Raises:
            ValueError: If model has not been trained
        """
        if self._model is None:
            raise ValueError("Model has not been trained. Call fit() before inference.")

    @property
    def model(self) -> Any:
        """
        Get the underlying dfencoder AutoEncoder instance.

        Returns:
            AutoEncoder instance (or None if not trained)
        """
        return self._model

    @property
    def is_trained(self) -> bool:
        """
        Check if model is trained.

        Returns:
            True if model has been trained, False otherwise
        """
        return self._model is not None

    def get_model_info(self) -> dict[str, Any]:
        """
        Get model configuration and status information.

        Returns:
            Dictionary with model metadata
        """
        return {
            "encoder_layers": self.encoder_layers,
            "decoder_layers": self.decoder_layers,
            "feature_columns": self.feature_columns,
            "activation": self.activation,
            "swap_probability": self.swap_probability,
            "learning_rate": self.learning_rate,
            "learning_rate_decay": self.learning_rate_decay,
            "batch_size": self.batch_size,
            "optimizer": self.optimizer,
            "scaler": self.scaler,
            "loss_scaler": self.loss_scaler,
            "device": self.device,
            "is_trained": self.is_trained,
            "num_features": len(self.feature_columns),
        }
