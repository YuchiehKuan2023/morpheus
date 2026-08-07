"""
Training Evaluation Module

This module computes baseline statistics from training/validation data for use
during inference anomaly detection. Following NVIDIA pattern, this computes
z-score normalization parameters (mean and std) from reconstruction errors.

Based on NVIDIA reference:
- examples/digital_fingerprinting/production/morpheus/dfp_postprocessing.py
- python/morpheus/morpheus/models/dfencoder/autoencoder.py (get_results method)

Key Features:
- Compute reconstruction error statistics (mean, std, percentiles)
- Z-score normalization parameters for anomaly scoring
- Distribution analysis for threshold tuning
- MLflow metrics logging
- NO classification metrics (unsupervised learning)

Author: Tomasz Zabek <tzabek@deloitte.co.uk>
Date: 2025-11-11
"""

import logging
from typing import Any

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


class TrainingEvaluator:
    """
    Training Evaluator - Computes baseline statistics for anomaly detection.

    This module is responsible for:
    1. Computing reconstruction errors on validation set
    2. Calculating mean and std for z-score normalization
    3. Computing percentiles for threshold analysis
    4. Analyzing loss distribution
    5. Storing baseline stats with model

    The baseline statistics are used during inference:
    - z_score = (loss - baseline_mean) / baseline_std
    - anomaly = z_score > threshold (e.g., 3.0)

    Following NVIDIA pattern:
    - Use validation set (or training set if no validation)
    - Compute per-row anomaly scores (mean reconstruction loss)
    - Calculate statistics for z-score normalization
    - Store with model for inference use

    Reference:
        NVIDIA Morpheus DFP postprocessing and AutoEncoder.get_results()
    """

    def __init__(self, config: dict[str, Any] | None = None):
        """
        Initialize Training Evaluator.

        Args:
            config: Optional configuration dictionary (reserved for future use)
        """
        self.config = config or {}
        logger.info("TrainingEvaluator initialized")

    def evaluate(self, model: Any, validation_data: pd.DataFrame) -> dict[str, Any]:
        """
        Evaluate trained model on validation data.

        Computes baseline statistics for anomaly detection:
        - mean: Mean reconstruction loss (for z-score normalization)
        - std: Std reconstruction loss (for z-score normalization)
        - percentiles: p50, p95, p99 (for threshold tuning)
        - sample_count: Number of validation samples

        Args:
            model: Trained model instance (DFPAutoEncoder)
            validation_data: Validation DataFrame

        Returns:
            Dictionary with baseline statistics:
                {
                    'mean': float,
                    'std': float,
                    'p50': float,
                    'p95': float,
                    'p99': float,
                    'min': float,
                    'max': float,
                    'sample_count': int
                }

        Raises:
            ValueError: If model is not trained or data is invalid
            RuntimeError: If evaluation fails
        """
        try:
            logger.info(f"Evaluating model on {len(validation_data)} validation samples")

            # Validate inputs
            self._validate_inputs(model, validation_data)

            # Compute anomaly scores (reconstruction losses)
            anomaly_scores = model.get_anomaly_score(validation_data)

            # Convert to numpy for statistics
            scores = np.array(anomaly_scores)

            # Compute statistics
            baseline_stats = {
                "mean": float(np.mean(scores)),
                "std": float(np.std(scores)),
                "p50": float(np.percentile(scores, 50)),
                "p95": float(np.percentile(scores, 95)),
                "p99": float(np.percentile(scores, 99)),
                "min": float(np.min(scores)),
                "max": float(np.max(scores)),
                "sample_count": len(scores),
            }

            logger.info(
                f"Baseline statistics computed: mean={baseline_stats['mean']:.4f}, "
                f"std={baseline_stats['std']:.4f}, p95={baseline_stats['p95']:.4f}, "
                f"p99={baseline_stats['p99']:.4f}"
            )

            return baseline_stats

        except Exception as e:
            logger.error(f"Evaluation failed: {e}")
            raise RuntimeError(f"Model evaluation failed: {e}") from e

    def _validate_inputs(self, model: Any, data: pd.DataFrame) -> None:
        """
        Validate evaluation inputs.

        Args:
            model: Model to validate
            data: Data to validate

        Raises:
            ValueError: If inputs are invalid
        """
        if model is None:
            raise ValueError("Model is None")

        if not hasattr(model, "is_trained"):
            raise ValueError("Model missing 'is_trained' attribute")

        if not model.is_trained:
            raise ValueError("Model has not been trained")

        if not hasattr(model, "get_anomaly_score"):
            raise ValueError("Model missing 'get_anomaly_score' method")

        if not isinstance(data, pd.DataFrame):
            raise ValueError(f"Expected DataFrame, got {type(data)}")

        if data.empty:
            raise ValueError("Validation data is empty")

    def compute_z_scores(self, anomaly_scores: pd.Series, baseline_mean: float, baseline_std: float) -> pd.Series:
        """
        Compute z-scores from anomaly scores using baseline statistics.

        This is the standard anomaly detection formula:
        z_score = (score - mean) / std

        Args:
            anomaly_scores: Raw anomaly scores (reconstruction losses)
            baseline_mean: Baseline mean from training
            baseline_std: Baseline std from training

        Returns:
            Z-scores (standardized anomaly scores)

        Example:
            >>> scores = pd.Series([0.5, 1.0, 2.5, 5.0])
            >>> z_scores = evaluator.compute_z_scores(
            >>>     scores, baseline_mean=1.0, baseline_std=0.5
            >>> )
            >>> # z_scores = [-1.0, 0.0, 3.0, 8.0]
        """
        if baseline_std == 0:
            logger.warning("Baseline std is 0, returning zeros for z-scores")
            return pd.Series(np.zeros(len(anomaly_scores)), index=anomaly_scores.index)

        z_scores = (anomaly_scores - baseline_mean) / baseline_std
        return z_scores

    def evaluate_with_fallback(
        self, model: Any, validation_data: pd.DataFrame | None, training_data: pd.DataFrame | None
    ) -> dict[str, Any]:
        """
        Evaluate model with fallback to training data if no validation data.

        Following NVIDIA pattern:
        - Prefer validation data (use_val_for_loss_stats=True)
        - Fall back to training data if validation is unavailable

        Args:
            model: Trained model instance
            validation_data: Validation DataFrame (optional)
            training_data: Training DataFrame (fallback)

        Returns:
            Baseline statistics dictionary

        Raises:
            ValueError: If both datasets are None or empty
        """
        # Try validation data first
        if validation_data is not None and not validation_data.empty:
            logger.info("Computing baseline statistics from validation data")
            return self.evaluate(model, validation_data)

        # Fall back to training data
        if training_data is not None and not training_data.empty:
            logger.warning(
                "No validation data available, computing baseline statistics from training data (may overfit)"
            )
            return self.evaluate(model, training_data)

        # No data available
        raise ValueError("Both validation_data and training_data are None or empty")

    def analyze_distribution(self, anomaly_scores: pd.Series, baseline_stats: dict[str, Any]) -> dict[str, Any]:
        """
        Analyze anomaly score distribution.

        Provides additional insights for threshold tuning:
        - How many samples exceed p95, p99
        - Outlier detection (beyond 3 std)
        - Distribution shape (skewness, kurtosis)

        Args:
            anomaly_scores: Raw anomaly scores
            baseline_stats: Baseline statistics from evaluate()

        Returns:
            Distribution analysis dictionary
        """
        try:
            scores = np.array(anomaly_scores)

            # Compute z-scores
            z_scores = self.compute_z_scores(anomaly_scores, baseline_stats["mean"], baseline_stats["std"])

            # Compute skewness and kurtosis (type: ignore for pandas Scalar return type)
            skew_val = pd.Series(scores).skew()
            kurt_val = pd.Series(scores).kurtosis()

            # Convert to float with type ignore (pandas returns numpy scalar types)
            skew_float: float = 0.0 if pd.isna(skew_val) else float(skew_val)  # type: ignore[arg-type]
            kurt_float: float = 0.0 if pd.isna(kurt_val) else float(kurt_val)  # type: ignore[arg-type]

            analysis = {
                "total_samples": len(scores),
                "above_p95_count": int(np.sum(scores > baseline_stats["p95"])),
                "above_p99_count": int(np.sum(scores > baseline_stats["p99"])),
                "above_3std_count": int(np.sum(np.abs(z_scores) > 3.0)),
                "above_p95_pct": float(np.mean(scores > baseline_stats["p95"]) * 100),
                "above_p99_pct": float(np.mean(scores > baseline_stats["p99"]) * 100),
                "above_3std_pct": float(np.mean(np.abs(z_scores) > 3.0) * 100),
                "skewness": skew_float,
                "kurtosis": kurt_float,
            }

            logger.info(
                f"Distribution analysis: {analysis['above_p95_pct']:.2f}% above p95, "
                f"{analysis['above_p99_pct']:.2f}% above p99, "
                f"{analysis['above_3std_pct']:.2f}% outliers (>3std)"
            )

            return analysis

        except Exception as e:
            logger.error(f"Distribution analysis failed: {e}")
            raise RuntimeError(f"Failed to analyze distribution: {e}") from e
