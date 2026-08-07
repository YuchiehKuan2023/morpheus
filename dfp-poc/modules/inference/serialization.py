"""
Serialization Module

This module handles serialization of DFP detection results to various output formats
(CSV, JSON, JSONLines), following NVIDIA Morpheus patterns.

Based on NVIDIA reference:
- morpheus/stages/postprocess/serialize_stage.py
- morpheus/stages/output/write_to_file_stage.py
- morpheus/io/serializers.py

Key Features:
- Serialize to CSV format
- Serialize to JSON format (lines or records)
- Serialize to JSONLines format (streaming)
- Column filtering (include/exclude patterns)
- Configurable output paths and options
- Statistics tracking

Author: Tomasz Zabek <tzabek@deloitte.co.uk>
Date: 2025-11-11
"""

import json
import logging
from io import StringIO
from pathlib import Path
from typing import Any

import pandas as pd

from modules.control.control_message import ControlMessage

logger = logging.getLogger(__name__)


class DFPSerializer:
    """
    Serialization Module - Serializes DFP detections to file formats.

    This module is responsible for:
    1. Serializing detections to CSV format
    2. Serializing detections to JSON/JSONLines format
    3. Filtering columns (include/exclude patterns)
    4. Writing to output files with append support
    5. Managing output directories

    Following NVIDIA pattern:
    - Input: ControlMessage with post-processed detections
    - Processing: Serialize to specified format
    - Output: Write to file(s)

    NVIDIA Standard Formats:
    - CSV: Comma-separated values with optional header
    - JSON: JSON array or JSON Lines (one JSON object per line)
    - JSONLines: Streaming JSON format (newline-delimited)

    Reference:
        NVIDIA Morpheus SerializeStage, WriteToFileStage
        morpheus/io/serializers.py
    """

    def __init__(self, config: dict[str, Any]):
        """
        Initialize Serialization module.

        Args:
            config: Configuration dictionary with keys:
                - output_dir: Output directory for serialized files (default: 'data/output')
                - file_format: Output format ('csv', 'json', 'jsonlines') (default: 'csv')
                - output_filename: Base filename for output (default: 'dfp_detections')
                - overwrite: Whether to overwrite existing files (default: False)
                - include_index: Include DataFrame index (default: False)
                - include_columns: List of columns to include (default: all)
                - exclude_columns: List of columns to exclude (default: ['_row_hash', '_batch_id'])
                - json_orient: JSON orientation ('records', 'split', 'index') (default: 'records')
                - json_lines: Use JSON Lines format for JSON (default: True)
                - csv_header: Include CSV header (default: True)

        Raises:
            ValueError: If configuration is invalid
        """
        self.config = config
        self._validate_config()

        # Extract configuration
        self.output_dir = Path(config.get("output_dir", "data/output"))
        self.file_format = config.get("file_format", "csv").lower()
        self.output_filename = config.get("output_filename", "dfp_detections")
        self.overwrite = config.get("overwrite", False)
        self.include_index = config.get("include_index", False)
        self.include_columns = config.get("include_columns", None)
        self.exclude_columns = config.get("exclude_columns", ["_row_hash", "_batch_id"])
        self.json_orient = config.get("json_orient", "records")
        self.json_lines = config.get("json_lines", True)
        self.csv_header = config.get("csv_header", True)

        # Build full output path
        self.output_path = self._build_output_path()

        # Create output directory
        self.output_dir.mkdir(parents=True, exist_ok=True)

        # Track if file has been written (for header management)
        self.is_first_write = True

        # Statistics tracking
        self.total_messages = 0
        self.total_rows = 0

        logger.info(f"DFPSerializer initialized: format={self.file_format}, output={self.output_path}")

    def _validate_config(self) -> None:
        """
        Validate configuration dictionary.

        Raises:
            ValueError: If configuration is invalid
        """
        # Validate file format
        file_format = self.config.get("file_format", "csv").lower()
        valid_formats = ["csv", "json", "jsonlines"]
        if file_format not in valid_formats:
            raise ValueError(f"Invalid file_format '{file_format}'. Must be one of: {valid_formats}")

        # Validate JSON orientation
        if file_format == "json":
            json_orient = self.config.get("json_orient", "records")
            valid_orients = ["records", "split", "index", "columns", "values"]
            if json_orient not in valid_orients:
                raise ValueError(f"Invalid json_orient '{json_orient}'. Must be one of: {valid_orients}")

    def _build_output_path(self) -> Path:
        """
        Build full output file path with extension.

        Returns:
            Path object for output file
        """
        # Determine extension based on format
        extension_map = {"csv": ".csv", "json": ".json", "jsonlines": ".jsonl"}
        extension = extension_map.get(self.file_format, ".csv")

        # Add extension if not present
        filename = self.output_filename
        if not filename.endswith(extension):
            filename += extension

        return self.output_dir / filename

    def serialize(self, control_message: ControlMessage) -> Path | None:
        """
        Serialize ControlMessage to file.

        This is the main entry point for serialization. It:
        1. Validates message and extracts DataFrame
        2. Filters columns based on include/exclude patterns
        3. Serializes to specified format
        4. Writes to output file (append mode if not overwrite)
        5. Returns path to output file

        Args:
            control_message: Input ControlMessage with:
                - payload: DataFrame with detections

        Returns:
            Path to output file (or None if serialization failed)

        Raises:
            ValueError: If message format is invalid
            RuntimeError: If serialization fails
        """
        try:
            # Validate message
            self._validate_message(control_message)

            # Extract data
            user_id = control_message.get_metadata("user_id", "unknown")
            data = self._extract_data(control_message)

            logger.debug(f"Serializing detections for user_id='{user_id}': {len(data)} rows to {self.file_format}")

            # Filter columns
            filtered_df = self._filter_columns(data)

            if filtered_df.empty:
                logger.warning(f"No data to serialize for user_id='{user_id}'")
                return None

            # Serialize to format
            serialized_data = self._serialize_data(filtered_df)

            # Write to file
            self._write_to_file(serialized_data)

            # Update statistics
            self.total_messages += 1
            self.total_rows += len(filtered_df)

            logger.info(
                f"Serialization complete for user_id='{user_id}': {len(filtered_df)} rows written to {self.output_path}"
            )

            return self.output_path

        except Exception as e:
            logger.error(f"Serialization failed for control message: {e}")
            raise RuntimeError(f"Serialization failed: {e}") from e

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

    def _filter_columns(self, data: pd.DataFrame) -> pd.DataFrame:
        """
        Filter DataFrame columns based on include/exclude patterns.

        Args:
            data: Input DataFrame

        Returns:
            Filtered DataFrame
        """
        df = data.copy()

        # Apply include filter (if specified)
        if self.include_columns:
            # Keep only specified columns
            available_cols = [col for col in self.include_columns if col in df.columns]
            df = df[available_cols]

        # Apply exclude filter
        if self.exclude_columns:
            # Remove excluded columns
            cols_to_drop = [col for col in self.exclude_columns if col in df.columns]
            df = df.drop(columns=cols_to_drop)

        return df

    def _serialize_data(self, data: pd.DataFrame) -> str:
        """
        Serialize DataFrame to string format.

        Args:
            data: Input DataFrame

        Returns:
            Serialized data as string
        """
        if self.file_format == "csv":
            return self._serialize_to_csv(data)
        elif self.file_format == "json":
            return self._serialize_to_json(data)
        elif self.file_format == "jsonlines":
            return self._serialize_to_jsonlines(data)
        else:
            raise ValueError(f"Unsupported format: {self.file_format}")

    def _serialize_to_csv(self, data: pd.DataFrame) -> str:
        """
        Serialize DataFrame to CSV format.

        Args:
            data: Input DataFrame

        Returns:
            CSV-formatted string
        """
        # Determine if header should be included
        # Header only on first write (unless overwrite mode)
        include_header = self.csv_header and (self.is_first_write or self.overwrite)

        # Serialize to CSV
        buf = StringIO()
        data.to_csv(buf, index=self.include_index, header=include_header, lineterminator="\n")

        return buf.getvalue()

    def _serialize_to_json(self, data: pd.DataFrame) -> str:
        """
        Serialize DataFrame to JSON format.

        Args:
            data: Input DataFrame

        Returns:
            JSON-formatted string
        """
        if self.json_lines:
            # JSON Lines format (newline-delimited JSON objects)
            return self._serialize_to_jsonlines(data)
        else:
            # Standard JSON array/object format
            json_str = data.to_json(orient=self.json_orient, lines=False, date_format="iso")
            return json_str + "\n"

    def _serialize_to_jsonlines(self, data: pd.DataFrame) -> str:
        """
        Serialize DataFrame to JSON Lines format.

        Args:
            data: Input DataFrame

        Returns:
            JSON Lines formatted string (one JSON object per line)
        """
        # Convert each row to JSON and join with newlines
        lines = []
        for _, row in data.iterrows():
            json_obj = row.to_dict()
            json_line = json.dumps(json_obj, default=str)
            lines.append(json_line)

        return "\n".join(lines) + "\n"

    def _write_to_file(self, data: str) -> None:
        """
        Write serialized data to output file.

        Args:
            data: Serialized data string
        """
        # Determine write mode
        if self.overwrite and self.is_first_write:
            mode = "w"  # Overwrite on first write
        else:
            mode = "a"  # Append on subsequent writes

        # Write to file
        with open(self.output_path, mode, encoding="utf-8") as f:
            f.write(data)

        # Update first write flag
        if self.is_first_write:
            self.is_first_write = False

    def serialize_batch(self, control_messages: list[ControlMessage]) -> Path | None:
        """
        Serialize a batch of ControlMessages to file.

        This is a convenience method for processing multiple messages,
        commonly used in pipeline implementations.

        Args:
            control_messages: List of input ControlMessages

        Returns:
            Path to output file (or None if no messages)
        """
        if not control_messages:
            logger.warning("No messages to serialize")
            return None

        output_path = None

        for msg in control_messages:
            try:
                output_path = self.serialize(msg)
            except Exception as e:
                logger.error(f"Failed to serialize message: {e}")
                # Continue processing remaining messages
                continue

        logger.info(
            f"Batch serialization complete: {len(control_messages)} messages, "
            f"{self.total_rows} total rows written to {output_path}"
        )

        return output_path

    def get_statistics(self) -> dict[str, Any]:
        """
        Get serialization statistics.

        Returns:
            Dictionary with statistics:
                - total_messages: Total messages serialized
                - total_rows: Total rows written
                - output_path: Path to output file
                - file_format: Output format
                - file_size: Size of output file (bytes)
        """
        file_size = 0
        if self.output_path.exists():
            file_size = self.output_path.stat().st_size

        return {
            "total_messages": self.total_messages,
            "total_rows": self.total_rows,
            "output_path": str(self.output_path),
            "file_format": self.file_format,
            "file_size": file_size,
        }

    def reset_statistics(self) -> None:
        """Reset statistics counters."""
        self.total_messages = 0
        self.total_rows = 0
        self.is_first_write = True
        logger.debug("Statistics reset")


# Convenience functions for standalone serialization
def serialize_to_csv(
    data: pd.DataFrame,
    output_path: str | Path,
    include_index: bool = False,
    include_header: bool = True,
    append: bool = False,
) -> Path:
    """
    Serialize DataFrame to CSV file (standalone function).

    Convenience function for CSV serialization without ControlMessage wrapper.

    Args:
        data: Input DataFrame
        output_path: Path to output file
        include_index: Include DataFrame index (default: False)
        include_header: Include CSV header (default: True)
        append: Append to existing file (default: False)

    Returns:
        Path to output file

    Example:
        >>> enriched_df = postprocess_detections(filtered_df)
        >>> output_file = serialize_to_csv(
        ...     enriched_df,
        ...     'data/output/detections/detections.csv',
        ...     include_header=True
        ... )
        >>> print(f"Saved to {output_file}")
    """
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    mode = "a" if append else "w"

    data.to_csv(output_path, index=include_index, header=include_header, mode=mode, lineterminator="\n")

    return output_path


def serialize_to_json(data: pd.DataFrame, output_path: str | Path, orient: str = "records", lines: bool = True) -> Path:
    """
    Serialize DataFrame to JSON file (standalone function).

    Convenience function for JSON serialization without ControlMessage wrapper.

    Args:
        data: Input DataFrame
        output_path: Path to output file
        orient: JSON orientation ('records', 'split', 'index') (default: 'records')
        lines: Use JSON Lines format (default: True)

    Returns:
        Path to output file

    Example:
        >>> enriched_df = postprocess_detections(filtered_df)
        >>> output_file = serialize_to_json(
        ...     enriched_df,
        ...     'data/output/detections/detections.jsonl',
        ...     lines=True
        ... )
        >>> print(f"Saved to {output_file}")
    """
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    data.to_json(output_path, orient=orient, lines=lines, date_format="iso")  # type: ignore[arg-type]

    return output_path
