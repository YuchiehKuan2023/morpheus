"""
DataFrame to Output Module for DFP Pipeline

This module serializes pandas DataFrames to various output formats (JSON, CSV, Parquet)
with configurable options for file output or streaming.

Key Features:
- Multi-format output (JSON, JSON Lines, CSV, Parquet)
- Configurable JSON orientation
- Directory creation
- Error handling and logging
- NVIDIA-aligned implementation patterns

Reference:
    NVIDIA Morpheus output serialization patterns
"""

from __future__ import annotations

import logging
from pathlib import Path

import pandas as pd

logger = logging.getLogger(__name__)


class DataFrameToOutput:
    """
    Serialize pandas DataFrames to various output formats.

    Supports:
    - JSON (array or JSON Lines)
    - CSV
    - Parquet

    Attributes:
        output_format (str): Output format ("json", "csv", "parquet")
        output_path (str): Default output path
        json_orient (str): JSON orientation for pd.to_json()
        json_lines (bool): Whether to use JSON Lines format
        csv_index (bool): Whether to include index in CSV
        parquet_compression (str): Parquet compression algorithm

    Example:
        >>> config = {
        ...     "format": "json",
        ...     "json_lines": True,
        ...     "output_path": "data/output/detections"
        ... }
        >>> saver = DataFrameToOutput(config)
        >>> saver.save_dataframe(df, "output.jsonl")
    """

    def __init__(self, config: dict | None = None):
        """
        Initialize DataFrameToOutput with configuration.

        Args:
            config: Configuration dictionary with optional keys:
                - format: Output format ("json", "csv", "parquet") (default: "json")
                - output_path: Default output directory (default: None)
                - json_orient: JSON orientation (default: "records")
                - json_lines: Use JSON Lines format (default: False)
                - csv_index: Include index in CSV (default: False)
                - parquet_compression: Compression algorithm (default: "snappy")
        """
        config = config or {}

        self.output_format = config.get("format", "json").lower()
        self.output_path = config.get("output_path", None)
        self.json_orient = config.get("json_orient", "records")
        self.json_lines = config.get("json_lines", False)
        self.csv_index = config.get("csv_index", False)
        self.parquet_compression = config.get("parquet_compression", "snappy")

        logger.debug(
            f"DataFrameToOutput initialized: format={self.output_format}, "
            f"json_lines={self.json_lines}, output_path={self.output_path}"
        )

    def save_dataframe(
        self, df: pd.DataFrame, output_path: str | None = None, output_format: str | None = None
    ) -> None:
        """
        Save DataFrame to file in configured format.

        Args:
            df: DataFrame to save
            output_path: Output file path (overrides default)
            output_format: Output format (overrides default)

        Raises:
            ValueError: If output_path is not provided and no default is set
            ValueError: If DataFrame is empty
        """
        if df.empty:
            logger.warning("Attempting to save empty DataFrame")
            return

        # Determine output path
        if output_path is None:
            if self.output_path is None:
                raise ValueError("output_path must be provided or configured")
            output_path = self.output_path

        # Determine output format
        format_to_use = output_format or self.output_format

        # Create output directory if needed
        output_file = Path(str(output_path))
        output_file.parent.mkdir(parents=True, exist_ok=True)

        logger.info(f"Saving DataFrame ({len(df)} rows) to {output_path} as {format_to_use}")

        try:
            if format_to_use == "json":
                self.to_json(df, str(output_file))
            elif format_to_use == "csv":
                self.to_csv(df, str(output_file))
            elif format_to_use == "parquet":
                self.to_parquet(df, str(output_file))
            else:
                raise ValueError(f"Unsupported output format: {format_to_use}")

            logger.info(f"Successfully saved to {output_path}")

        except Exception as e:
            logger.error(f"Failed to save DataFrame to {output_path}: {e}", exc_info=True)
            raise

    def to_json(self, df: pd.DataFrame, path: str) -> None:
        """
        Save DataFrame as JSON.

        Supports both JSON array and JSON Lines (JSONL) formats.

        Args:
            df: DataFrame to save
            path: Output file path
        """
        if self.json_lines:
            # JSON Lines format (one object per line)
            df.to_json(path, orient=self.json_orient, lines=True, date_format="iso", date_unit="s")
            logger.debug(f"Saved as JSON Lines: {len(df)} records")
        else:
            # JSON array format
            df.to_json(path, orient=self.json_orient, indent=2, date_format="iso", date_unit="s")
            logger.debug(f"Saved as JSON array: {len(df)} records")

    def to_csv(self, df: pd.DataFrame, path: str) -> None:
        """
        Save DataFrame as CSV.

        Args:
            df: DataFrame to save
            path: Output file path
        """
        df.to_csv(path, index=self.csv_index)
        logger.debug(f"Saved as CSV: {len(df)} rows, {len(df.columns)} columns")

    def to_parquet(self, df: pd.DataFrame, path: str) -> None:
        """
        Save DataFrame as Parquet.

        Args:
            df: DataFrame to save
            path: Output file path
        """
        df.to_parquet(path, compression=self.parquet_compression, index=False)
        logger.debug(
            f"Saved as Parquet ({self.parquet_compression} compression): {len(df)} rows, {len(df.columns)} columns"
        )

    def dataframe_to_dict(self, df: pd.DataFrame, orient: str | None = None) -> dict:
        """
        Convert DataFrame to dictionary (useful for API responses or streaming).

        Args:
            df: DataFrame to convert
            orient: JSON orientation (overrides default)

        Returns:
            Dictionary representation of DataFrame
        """
        orient_to_use = orient if orient is not None else self.json_orient
        result = df.to_dict(orient=orient_to_use)  # type: ignore
        return result  # type: ignore


__all__ = ["DataFrameToOutput"]
