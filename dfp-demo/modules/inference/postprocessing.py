"""
Post-Processing Module

This module performs post-processing on DFP inference results, adding metadata
and formatting output for downstream consumers.

Based on NVIDIA reference:
- morpheus_dfp/modules/dfp_postprocessing.py
- morpheus_dfp/stages/dfp_postprocessing_stage.py
- docs/source/developer_guide/guides/6_digital_fingerprinting_reference.md

Key Features:
- Add event_time timestamp (detection time)
- Add/preserve user_id metadata
- Add/preserve model_version metadata
- Replace NaN values with string 'NaN'
- Format timestamps to ISO 8601
- Statistics tracking

Author: Tomasz Zabek <tzabek@deloitte.co.uk>
Date: 2025-11-11
"""

import logging
from datetime import datetime
from typing import Any

import numpy as np
import pandas as pd

from modules.control.control_message import ControlMessage

logger = logging.getLogger(__name__)


class DFPPostProcessing:
    """
    Post-Processing Module - Adds metadata and formats DFP inference results.

    This module is responsible for:
    1. Adding event_time column (detection timestamp)
    2. Preserving/adding user_id metadata
    3. Preserving/adding model_version metadata
    4. Replacing NaN values with string 'NaN'
    5. Formatting timestamps to ISO 8601

    Following NVIDIA pattern:
    - Input: ControlMessage with filtered detections
    - Processing: Add metadata columns and format data
    - Output: ControlMessage with enriched detections

    NVIDIA Standard Metadata:
    - event_time: Time when anomaly was detected (ISO 8601 format)
    - user_id: User identifier (from ControlMessage metadata)
    - model_version: Model used for detection (from ControlMessage metadata)

    Reference:
        NVIDIA Morpheus DFPPostprocessingStage
        docs/source/developer_guide/guides/6_digital_fingerprinting_reference.md:371-373
    """

    def __init__(self, config: dict[str, Any]):
        """
        Initialize Post-Processing module.

        Args:
            config: Configuration dictionary with keys:
                - timestamp_column_name: Name of timestamp column (default: "timestamp")
                - replace_nan: Whether to replace NaN values (default: True)
                - nan_replacement: Value to use for NaN replacement (default: 'NaN')
                - event_time_format: ISO 8601 format string (default: '%Y-%m-%dT%H:%M:%SZ')

        Raises:
            ValueError: If configuration is invalid
        """
        self.config = config
        self._validate_config()

        # Extract configuration
        self.timestamp_column_name = config.get("timestamp_column_name", "timestamp")
        self.replace_nan = config.get("replace_nan", True)
        self.nan_replacement = config.get("nan_replacement", "NaN")
        self.event_time_format = config.get("event_time_format", "%Y-%m-%dT%H:%M:%SZ")

        # Statistics tracking
        self.total_processed = 0
        self.total_events = 0

        logger.info(
            f"DFPPostProcessing initialized: timestamp_column={self.timestamp_column_name}, "
            f"replace_nan={self.replace_nan}"
        )

    def _validate_config(self) -> None:
        """
        Validate configuration dictionary.

        Raises:
            ValueError: If configuration is invalid
        """
        # Configuration is optional with defaults, so just validate types
        if "timestamp_column_name" in self.config:
            if not isinstance(self.config["timestamp_column_name"], str):
                raise ValueError("timestamp_column_name must be a string")

    def process(self, control_message: ControlMessage) -> ControlMessage | None:
        """
        Process ControlMessage and add metadata.

        This is the main entry point for post-processing. It:
        1. Validates message and extracts DataFrame
        2. Adds event_time column (current timestamp)
        3. Optionally replaces NaN values
        4. Preserves/adds metadata (user_id, model_version)
        5. Creates output ControlMessage with enriched data

        Args:
            control_message: Input ControlMessage with:
                - payload: DataFrame with detections
                - metadata: user_id, model_version (optional)

        Returns:
            ControlMessage with post-processed detections (or None if empty)

        Raises:
            ValueError: If message format is invalid
            RuntimeError: If processing fails
        """
        try:
            # Validate message
            self._validate_message(control_message)

            # Extract data
            user_id = control_message.get_metadata("user_id", "unknown")
            model_version = control_message.get_metadata("model_version", "unknown")
            data = self._extract_data(control_message)

            logger.debug(f"Post-processing detections for user_id='{user_id}': {len(data)} events")

            # Process events
            processed_df = self._process_events(data=data, user_id=user_id, model_version=model_version)

            # Update statistics
            self.total_processed += 1
            self.total_events += len(processed_df)

            # Create output message
            output_message = self._create_output_message(processed_df=processed_df, original_message=control_message)

            logger.info(f"Post-processing complete for user_id='{user_id}': {len(processed_df)} events processed")

            return output_message

        except Exception as e:
            logger.error(f"Post-processing failed for control message: {e}")
            raise RuntimeError(f"Post-processing failed: {e}") from e

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

    def _process_events(self, data: pd.DataFrame, user_id: str, model_version: str) -> pd.DataFrame:
        """
        Process events by adding metadata and formatting.

        Args:
            data: Input DataFrame with detections
            user_id: User identifier
            model_version: Model version identifier

        Returns:
            Processed DataFrame with added metadata
        """
        # Copy data to avoid modifying original
        df = data.copy()

        # Add event_time (detection timestamp)
        # NVIDIA pattern: Use current time in ISO 8601 format
        event_time = datetime.now().strftime(self.event_time_format)
        df["event_time"] = event_time

        # Add user_id if not present
        if "user_id" not in df.columns:
            df["user_id"] = user_id

        # Add model_version if not present
        if "model_version" not in df.columns:
            df["model_version"] = model_version

        # Replace NaN values if configured
        if self.replace_nan:
            df = df.replace([np.nan, np.inf, -np.inf], self.nan_replacement)

        # Format timestamp column to ISO 8601 if present
        if self.timestamp_column_name in df.columns:
            try:
                df[self.timestamp_column_name] = pd.to_datetime(df[self.timestamp_column_name]).dt.strftime(
                    self.event_time_format
                )
            except Exception as e:
                logger.warning(f"Failed to format timestamp column '{self.timestamp_column_name}': {e}")

        return df

    def _create_output_message(self, processed_df: pd.DataFrame, original_message: ControlMessage) -> ControlMessage:
        """
        Create output ControlMessage with processed data.

        Args:
            processed_df: Processed DataFrame
            original_message: Input ControlMessage

        Returns:
            Output ControlMessage with processed data
        """
        # Create output message
        output_message = ControlMessage()

        # Copy metadata from original message
        if original_message.has_metadata("user_id"):
            output_message.set_metadata("user_id", original_message.get_metadata("user_id"))

        if original_message.has_metadata("model_version"):
            output_message.set_metadata("model_version", original_message.get_metadata("model_version"))

        # Set payload with processed data
        output_message.payload(processed_df)

        return output_message

    def process_batch(self, control_messages: list[ControlMessage]) -> list[ControlMessage]:
        """
        Process a batch of ControlMessages.

        This is a convenience method for processing multiple messages,
        commonly used in pipeline implementations.

        Args:
            control_messages: List of input ControlMessages

        Returns:
            List of output ControlMessages with post-processed data
        """
        output_messages = []

        for msg in control_messages:
            try:
                output_msg = self.process(msg)
                if output_msg is not None:
                    output_messages.append(output_msg)
            except Exception as e:
                logger.error(f"Failed to process message: {e}")
                # Continue processing remaining messages
                continue

        logger.info(
            f"Batch post-processing complete: {len(output_messages)}/{len(control_messages)} messages processed"
        )

        return output_messages

    def get_statistics(self) -> dict[str, Any]:
        """
        Get post-processing statistics.

        Returns:
            Dictionary with statistics:
                - total_processed: Total messages processed
                - total_events: Total events processed
                - avg_events_per_message: Average events per message
        """
        avg_events = self.total_events / self.total_processed if self.total_processed > 0 else 0.0

        return {
            "total_processed": self.total_processed,
            "total_events": self.total_events,
            "avg_events_per_message": avg_events,
        }

    def reset_statistics(self) -> None:
        """Reset statistics counters."""
        self.total_processed = 0
        self.total_events = 0
        logger.debug("Statistics reset")


# Convenience function for standalone post-processing
def postprocess_detections(
    data: pd.DataFrame,
    user_id: str = "unknown",
    model_version: str = "unknown",
    timestamp_column_name: str = "timestamp",
    replace_nan: bool = True,
) -> pd.DataFrame:
    """
    Post-process detections DataFrame (standalone function).

    Convenience function for post-processing without ControlMessage wrapper.

    Args:
        data: Input DataFrame with detections
        user_id: User identifier (default: 'unknown')
        model_version: Model version identifier (default: 'unknown')
        timestamp_column_name: Name of timestamp column (default: 'timestamp')
        replace_nan: Whether to replace NaN values (default: True)

    Returns:
        Post-processed DataFrame with metadata

    Example:
        >>> filtered_df = filter_detections(results_df, threshold=2.0)
        >>> enriched_df = postprocess_detections(
        ...     filtered_df,
        ...     user_id='user123',
        ...     model_version='dfp-model:1'
        ... )
        >>> print(enriched_df[['event_time', 'user_id', 'model_version']].head())
    """
    # Copy data
    df = data.copy()

    # Add event_time
    event_time_format = "%Y-%m-%dT%H:%M:%SZ"
    event_time = datetime.now().strftime(event_time_format)
    df["event_time"] = event_time

    # Add user_id and model_version
    if "user_id" not in df.columns:
        df["user_id"] = user_id

    if "model_version" not in df.columns:
        df["model_version"] = model_version

    # Replace NaN values
    if replace_nan:
        df = df.replace([np.nan, np.inf, -np.inf], "NaN")

    # Format timestamp
    if timestamp_column_name in df.columns:
        try:
            df[timestamp_column_name] = pd.to_datetime(df[timestamp_column_name]).dt.strftime(event_time_format)
        except Exception:
            pass  # Ignore formatting errors

    return df
