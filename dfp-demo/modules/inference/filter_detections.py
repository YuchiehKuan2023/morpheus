"""
Filter Detections Module

This module filters inference results to identify anomalous detections based on
z-score thresholds, following NVIDIA Morpheus DFP patterns.

Based on NVIDIA reference:
- morpheus/stages/postprocess/filter_detections_stage.py
- morpheus/controllers/filter_detections_controller.py
- docs/source/developer_guide/guides/6_digital_fingerprinting_reference.md

Key Features:
- Filter by mean_abs_z threshold (NVIDIA DFP standard: 2.0-3.0)
- Configurable field name (default: mean_abs_z)
- Output ONLY anomalies (rows above threshold)
- Return None if no detections found
- Statistics tracking (total, anomalies, percentage)

NVIDIA Standard Behavior:
- Binary filtering: anomalies pass through, normal data dropped
- No flag column added
- Uses filter_copy (default) or filter_slice for performance

Author: Tomasz Zabek <tzabek@deloitte.co.uk>
Date: 2025-11-11
"""

import logging
from typing import Any

import pandas as pd

from modules.control.control_message import ControlMessage

logger = logging.getLogger(__name__)


class FilterDetections:
    """
    Filter Detections Module - Filters anomalous detections from inference results.

    This module is responsible for:
    1. Applying z-score threshold to mean_abs_z column
    2. Filtering rows that exceed the threshold
    3. Outputting ONLY anomalous detections (NVIDIA standard)
    4. Tracking filtering statistics

    Following NVIDIA pattern:
    - Input: ControlMessage with inference results (z-scores)
    - Processing: Apply threshold filter to mean_abs_z
    - Output: ControlMessage with only anomalous detections (or None if no anomalies)

    NVIDIA Default Threshold:
    - DFP uses threshold of 2.0 (2 standard deviations)
    - Documentation recommends 2.0-3.0 range
    - Higher threshold = fewer false positives, more false negatives

    Reference:
        NVIDIA Morpheus FilterDetectionsStage
        morpheus/controllers/filter_detections_controller.py
    """

    def __init__(self, config: dict[str, Any]):
        """
        Initialize Filter Detections module.

        Args:
            config: Configuration dictionary with keys:
                - detection_criteria: Detection filtering criteria
                    - field_name: Column name to filter on (default: "mean_abs_z")
                    - threshold: Z-score threshold (default: 2.0)
                    - filter_source: Source type (default: "DATAFRAME")
                - output: Output configuration
                    - copy_data: Copy data instead of filtering (default: True)

        Raises:
            ValueError: If required configuration keys are missing

        Note:
            Following NVIDIA Morpheus FilterDetectionsStage pattern:
            - Outputs ONLY anomalies (rows above threshold)
            - No is_anomaly flag added
            - Returns None if no detections found
        """
        self.config = config
        self._validate_config()

        # Extract configuration
        detection_criteria = config.get("detection_criteria", {})
        output_config = config.get("output", {})

        self.field_name = detection_criteria.get("field_name", "mean_abs_z")
        self.threshold = detection_criteria.get("threshold", 2.0)
        self.filter_source = detection_criteria.get("filter_source", "DATAFRAME")

        self.copy_data = output_config.get("copy_data", True)

        # Statistics tracking
        self.total_processed = 0
        self.total_anomalies = 0

        logger.info(
            f"FilterDetections initialized: field={self.field_name}, threshold={self.threshold}, copy={self.copy_data}"
        )

    def _validate_config(self) -> None:
        """
        Validate configuration dictionary.

        Raises:
            ValueError: If required keys are missing or invalid
        """
        # Configuration is optional with defaults, so just validate types
        if "detection_criteria" in self.config:
            criteria = self.config["detection_criteria"]
            if "threshold" in criteria and not isinstance(criteria["threshold"], int | float):
                raise ValueError("detection_criteria.threshold must be a number")

    def filter(self, control_message: ControlMessage) -> ControlMessage | None:
        """
        Filter detections from ControlMessage.

        This is the main entry point for filtering. It:
        1. Validates message and extracts DataFrame
        2. Checks if field_name column exists
        3. Applies threshold filter
        4. Optionally adds is_anomaly flag
        5. Creates output ControlMessage with filtered results

        Args:
            control_message: Input ControlMessage with:
                - payload: DataFrame with z-scores (must contain field_name column)

        Returns:
            ControlMessage with filtered detections (or None if no anomalies)

        Raises:
            ValueError: If message format is invalid
            RuntimeError: If filtering fails
        """
        try:
            # Validate message
            self._validate_message(control_message)

            # Extract data
            user_id = control_message.get_metadata("user_id", "unknown")
            data = self._extract_data(control_message)

            logger.debug(
                f"Filtering detections for user_id='{user_id}': "
                f"{len(data)} rows, field='{self.field_name}', threshold={self.threshold}"
            )

            # Check if field exists
            if self.field_name not in data.columns:
                raise ValueError(
                    f"Field '{self.field_name}' not found in data. Available columns: {list(data.columns)}"
                )

            # Apply filter
            filtered_df = self._apply_filter(data, user_id, control_message)

            # If no anomalies and not including all, return None
            if filtered_df is None or filtered_df.empty:
                logger.info(f"No anomalies detected for user_id='{user_id}'")
                return None

            # Log detailed detection information
            self._log_detection_details(filtered_df, user_id, data)

            # Create output message
            output_message = self._create_output_message(filtered_df=filtered_df, original_message=control_message)

            logger.info(
                f"Filtering complete for user_id='{user_id}': {len(filtered_df)}/{len(data)} rows (anomalies/total)"
            )

            return output_message

        except Exception as e:
            logger.error(f"Filtering failed for control message: {e}")
            raise RuntimeError(f"Filtering failed: {e}") from e

    def _log_detection_details(self, filtered_df: pd.DataFrame, user_id: str, original_data: pd.DataFrame) -> None:
        """
        Log comprehensive detection details for analysis.

        Args:
            filtered_df: Filtered anomalies DataFrame
            user_id: User ID
            original_data: Original data before filtering
        """
        if filtered_df.empty:
            return

        # Get z-score columns (pattern: feature_name_z_loss)
        # NVIDIA AutoEncoder creates columns: feature_z_loss (numeric z-scores)
        # Also exclude metadata column 'z_loss_scaler_type' (string)
        z_score_cols = [col for col in filtered_df.columns if col.endswith("_z_loss")]

        # Log summary statistics
        logger.info(f"\n{'=' * 80}")
        logger.info(f"DETECTION REPORT - User: {user_id}")
        logger.info(f"{'=' * 80}")
        logger.info(f"Total events analyzed: {len(original_data)}")
        logger.info(f"Anomalies detected: {len(filtered_df)} ({len(filtered_df) / len(original_data) * 100:.1f}%)")
        logger.info(f"Detection threshold: {self.threshold} (mean_abs_z)")

        # Get top anomalies (highest mean_abs_z scores)
        top_anomalies = filtered_df.nlargest(min(5, len(filtered_df)), self.field_name)

        logger.info(f"\nTop {len(top_anomalies)} Anomalies:")
        logger.info("-" * 80)

        for idx, (_row_idx, row) in enumerate(top_anomalies.iterrows(), 1):
            mean_abs_z = row[self.field_name]
            logger.info(f"\nAnomaly #{idx}: Score = {mean_abs_z:.3f} (threshold: {self.threshold})")

            # Find which z-scores contributed most
            if z_score_cols:
                # All feature_z_loss columns are numeric
                z_scores = {
                    col.replace("_z_loss", ""): abs(float(row[col])) for col in z_score_cols if col in row.index
                }

                if z_scores:
                    top_features = sorted(z_scores.items(), key=lambda x: x[1], reverse=True)[:5]

                    logger.info("  Top contributing features (by z-score):")
                    for feature, z_val in top_features:
                        logger.info(f"    - {feature}: z={z_val:.3f}")

            # Log timestamp if available
            if "timestamp" in row.index:
                logger.info(f"  Timestamp: {row['timestamp']}")

        # Log overall z-score statistics
        mean_abs_z_values = filtered_df[self.field_name]
        logger.info("\nAnomaly Score Statistics:")
        logger.info(f"  Min: {mean_abs_z_values.min():.3f}")
        logger.info(f"  Max: {mean_abs_z_values.max():.3f}")
        logger.info(f"  Mean: {mean_abs_z_values.mean():.3f}")
        logger.info(f"  Median: {mean_abs_z_values.median():.3f}")
        logger.info(f"{'=' * 80}\n")

    def _validate_message(self, control_message: ControlMessage) -> None:
        """
        Validate ControlMessage format.

        Args:
            control_message: Message to validate

        Raises:
            ValueError: If message format is invalid
        """
        # Check if it's a ControlMessage
        if not hasattr(control_message, "payload"):
            raise ValueError(f"Expected ControlMessage with payload() method, got {type(control_message)}")

        # Check payload
        if control_message.payload() is None:
            raise ValueError("ControlMessage has no payload")

    def _extract_data(self, control_message: ControlMessage) -> pd.DataFrame:
        """
        Extract data from ControlMessage payload.

        Args:
            control_message: Input message

        Returns:
            Data DataFrame

        Raises:
            ValueError: If payload format is invalid
        """
        payload = control_message.payload()

        if payload is None:
            raise ValueError("ControlMessage has no payload")

        # Type narrowing
        df: Any = payload

        # Convert to pandas if needed (cuDF → pandas)
        if hasattr(df, "to_pandas"):
            df = df.to_pandas()

        if not isinstance(df, pd.DataFrame):
            raise ValueError(f"Expected DataFrame payload, got {type(df)}")

        if df.empty:
            raise ValueError("Data is empty")

        return df

    def _apply_filter(
        self, data: pd.DataFrame, user_id: str, control_message: ControlMessage | None = None
    ) -> pd.DataFrame | None:
        """
        Apply NVIDIA standard binary threshold filter to data.

        Filters detections based on mean_abs_z threshold (default: 2.0):
        - DFP AutoEncoder: Behavioral + geographic anomaly detection
        - Binary filtering: mean_abs_z > threshold
        - Returns None if no anomalies exceed threshold (NVIDIA standard)

        Args:
            data: Input DataFrame with z-scores
            user_id: User identifier (for logging)
            control_message: ControlMessage (optional, for future extensibility)

        Returns:
            Filtered DataFrame (or None if no anomalies and not include_all)
        """
        # Copy data if requested (to avoid modifying original)
        if self.copy_data:
            df = data.copy()
        else:
            df = data

        # DFP AutoEncoder detection (z-score threshold)
        dfp_anomaly_mask = df[self.field_name] > self.threshold
        dfp_anomalies = dfp_anomaly_mask.sum()

        # Simple binary filtering
        anomaly_mask = dfp_anomaly_mask
        num_anomalies = anomaly_mask.sum()

        # Add source attribution column
        df["anomaly_source"] = "normal"
        df.loc[dfp_anomaly_mask, "anomaly_source"] = "dfp"

        # Update statistics
        self.total_processed += len(df)
        self.total_anomalies += num_anomalies

        # Log statistics
        anomaly_percentage = (num_anomalies / len(df)) * 100 if len(df) > 0 else 0.0
        logger.debug(
            f"Filter results for user_id='{user_id}': {num_anomalies}/{len(df)} anomalies ({anomaly_percentage:.2f}%) "
            f"[DFP anomalies: {dfp_anomalies}]"
        )

        # NVIDIA standard: Output only anomalies, return None if no detections
        if num_anomalies == 0:
            return None

        if self.copy_data:
            # Copy filtered rows (NVIDIA filter_copy pattern)
            filtered_df = df[anomaly_mask].copy()
        else:
            # Use sliced view for performance (NVIDIA filter_slice pattern)
            filtered_df = df[anomaly_mask]

        return filtered_df

    def _create_output_message(self, filtered_df: pd.DataFrame, original_message: ControlMessage) -> ControlMessage:
        """
        Create output ControlMessage with filtered results.

        Args:
            filtered_df: Filtered DataFrame
            original_message: Input ControlMessage

        Returns:
            Output ControlMessage with filtered data
        """
        # Create output message
        output_message = ControlMessage()

        # Copy metadata from original message
        if original_message.has_metadata("user_id"):
            output_message.set_metadata("user_id", original_message.get_metadata("user_id"))

        if original_message.has_metadata("model_version"):
            output_message.set_metadata("model_version", original_message.get_metadata("model_version"))

        # Set payload with filtered data
        output_message.payload(filtered_df)

        return output_message

    def filter_batch(self, control_messages: list[ControlMessage]) -> list[ControlMessage]:
        """
        Filter detections for a batch of ControlMessages.

        This is a convenience method for processing multiple messages,
        commonly used in pipeline implementations.

        Args:
            control_messages: List of input ControlMessages

        Returns:
            List of output ControlMessages with filtered detections
            Note: Messages with no anomalies are filtered out (if include_all=False)
        """
        output_messages = []

        for msg in control_messages:
            try:
                output_msg = self.filter(msg)
                if output_msg is not None:
                    output_messages.append(output_msg)
            except Exception as e:
                logger.error(f"Failed to process message: {e}")
                # Continue processing remaining messages
                continue

        logger.info(f"Batch filtering complete: {len(output_messages)}/{len(control_messages)} messages with anomalies")

        return output_messages

    def get_statistics(self) -> dict[str, Any]:
        """
        Get filtering statistics.

        Returns:
            Dictionary with statistics:
                - total_processed: Total rows processed
                - total_anomalies: Total anomalies detected
                - anomaly_rate: Percentage of anomalies
                - threshold: Current threshold
                - field_name: Field being filtered
        """
        anomaly_rate = (self.total_anomalies / self.total_processed) * 100 if self.total_processed > 0 else 0.0

        return {
            "total_processed": self.total_processed,
            "total_anomalies": self.total_anomalies,
            "anomaly_rate": anomaly_rate,
            "threshold": self.threshold,
            "field_name": self.field_name,
        }

    def reset_statistics(self) -> None:
        """Reset statistics counters."""
        self.total_processed = 0
        self.total_anomalies = 0
        logger.debug("Statistics reset")


# Convenience function for standalone filtering
def filter_detections(
    data: pd.DataFrame, field_name: str = "mean_abs_z", threshold: float = 2.0, include_all: bool = False
) -> pd.DataFrame:
    """
    Filter detections from DataFrame (standalone function).

    Convenience function for filtering without ControlMessage wrapper.

    Args:
        data: Input DataFrame with z-scores
        field_name: Column name to filter on (default: "mean_abs_z")
        threshold: Z-score threshold (default: 2.0)
        include_all: Return all rows with is_anomaly flag (default: False)

    Returns:
        Filtered DataFrame

    Raises:
        ValueError: If field_name not in DataFrame

    Example:
        >>> results_df = model.get_results(input_df, return_abs=True)
        >>> anomalies = filter_detections(results_df, threshold=3.0)
        >>> print(f"Found {len(anomalies)} anomalies")
    """
    if field_name not in data.columns:
        raise ValueError(f"Field '{field_name}' not found in data. Available columns: {list(data.columns)}")

    # Apply filter
    anomaly_mask = data[field_name] > threshold

    if include_all:
        # Return all with flag
        result = data.copy()
        result["is_anomaly"] = anomaly_mask
        return result
    else:
        # Return only anomalies
        return data[anomaly_mask].copy()
