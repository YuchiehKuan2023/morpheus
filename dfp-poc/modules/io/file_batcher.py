"""
File Batching Module for DFP Pipeline

This module provides file batching functionality aligned with NVIDIA Morpheus DFP architecture.
It supports batching files by time period, count, or custom sampling strategies.

Key Features:
- Time-based batching (daily, weekly, monthly periods)
- Timestamp extraction from filenames or file metadata
- Time window filtering (start_time, end_time)
- Sampling strategies (frequency, fraction, count)
- NVIDIA-aligned implementation patterns

Reference:
    /nv-morpheus/python/morpheus_dfp/morpheus_dfp/modules/dfp_file_batcher.py
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

# Default ISO date regex pattern for extracting timestamps from filenames
# Matches: YYYY-MM-DD, YYYY-MM-DDTHH:MM:SS, YYYY-MM-DDTHH:MM:SS.ffffff, etc.
DEFAULT_ISO_DATE_REGEX_PATTERN = r"(\d{4}[-]\d{2}[-]\d{2}[T_ ]?\d{2}[:-]\d{2}[:-]\d{2}(?:\.\d{1,6})?)"

logger = logging.getLogger(__name__)


class FileBatcher:
    """
    Batch input files by time period, count, or custom sampling strategy.

    This class follows NVIDIA Morpheus DFP patterns for file batching, supporting:
    - Period-based batching (group files by day/week/month)
    - Time window filtering
    - Sampling strategies (frequency resampling, fraction, or fixed count)
    - Timestamp extraction from filenames or file metadata

    Attributes:
        period (str): Pandas offset string for grouping (e.g., "D", "W", "M")
                     None means no period-based batching
        sampling (Union[str, float, int, None]): Sampling strategy
            - str: Pandas frequency for resampling (e.g., "12H")
            - float [0,1): Sample this fraction of files
            - int >1: Sample this many files
            - None: No sampling
        start_time (datetime): Start of time window (inclusive)
        end_time (datetime): End of time window (exclusive)
        iso_date_regex (re.Pattern): Regex for extracting ISO dates from filenames

    Example:
        >>> config = {"period": "D", "sampling": 0.5}
        >>> batcher = FileBatcher(config)
        >>> batches = batcher.batch_files(file_paths)
        >>> for batch in batches:
        ...     process_batch(batch)
    """

    def __init__(self, config: dict | None = None):
        """
        Initialize FileBatcher with configuration.

        Args:
            config: Configuration dictionary with optional keys:
                - period: Pandas offset string (default: None)
                - sampling: Sampling strategy (default: None)
                - start_time: Start of time window (default: None)
                - end_time: End of time window (default: None)
                - iso_date_regex: Custom regex pattern (default: DEFAULT_ISO_DATE_REGEX_PATTERN)
        """
        config = config or {}

        self.period = config.get("period", None)
        self.sampling = config.get("sampling", None)

        # Parse start_time and end_time (support string or datetime)
        start_time = config.get("start_time", None)
        end_time = config.get("end_time", None)

        if isinstance(start_time, str):
            self.start_time = pd.to_datetime(start_time).to_pydatetime().replace(tzinfo=timezone.utc)
        else:
            self.start_time = start_time

        if isinstance(end_time, str):
            self.end_time = pd.to_datetime(end_time).to_pydatetime().replace(tzinfo=timezone.utc)
        else:
            self.end_time = end_time

        # Compile regex for timestamp extraction
        regex_pattern = config.get("iso_date_regex", DEFAULT_ISO_DATE_REGEX_PATTERN)
        self.iso_date_regex = re.compile(regex_pattern)

        # Validate configuration
        self._validate_config()

        logger.debug(
            f"FileBatcher initialized: period={self.period}, sampling={self.sampling}, "
            f"start_time={self.start_time}, end_time={self.end_time}"
        )

    def _validate_config(self) -> None:
        """Validate configuration parameters."""
        # Validate sampling parameter
        if self.sampling is not None:
            if isinstance(self.sampling, float):
                if not (0.0 < self.sampling < 1.0):
                    raise ValueError(f"Sampling fraction must be in (0, 1), got {self.sampling}")
            elif isinstance(self.sampling, int):
                if self.sampling < 1:
                    raise ValueError(f"Sampling count must be >= 1, got {self.sampling}")
            elif not isinstance(self.sampling, str):
                raise ValueError(
                    f"Sampling must be str (frequency), float (fraction), or int (count), got {type(self.sampling)}"
                )

        # Validate time window
        if self.start_time and self.end_time:
            if self.start_time >= self.end_time:
                raise ValueError("start_time must be < end_time")

    def batch_files(self, file_paths: list[str]) -> list[list[str]]:
        """
        Batch files by time period with optional sampling and time window filtering.

        This is the main entry point for file batching. It:
        1. Extracts timestamps from file paths
        2. Filters by time window if configured
        3. Applies sampling if configured
        4. Groups by period if configured
        5. Returns list of batches

        Args:
            file_paths: List of file paths to batch

        Returns:
            List of batches, where each batch is a list of file paths

        Raises:
            ValueError: If file_paths is empty or invalid
        """
        if not file_paths:
            logger.warning("Empty file_paths provided to batch_files()")
            return []

        # Build DataFrame with timestamps
        file_df = self._build_file_dataframe(file_paths)

        if file_df.empty:
            logger.warning("Could not extract timestamps from any files")
            return []

        # Filter by time window if configured
        if self.start_time or self.end_time:
            file_df = self._filter_by_time_window(file_df)

        if file_df.empty:
            logger.warning("No files remaining after time window filtering")
            return []

        # Apply sampling
        if self.sampling is not None:
            file_df = self.apply_sampling(file_df)

        if file_df.empty:
            logger.warning("No files remaining after sampling")
            return []

        # If no period-based batching, return all files as single batch
        if self.period is None:
            logger.debug(f"No period specified, returning single batch of {len(file_df)} files")
            return [file_df["file_path"].tolist()]

        # Group by period
        batches = self._group_by_period(file_df)
        file_df = self._build_file_dataframe(file_paths)

        if file_df.empty:
            logger.warning("No files with valid timestamps found")
            return []

        # Filter by time window
        if self.start_time or self.end_time:
            file_df = self._filter_by_time_window(file_df)

        if file_df.empty:
            logger.warning("No files remaining after time window filtering")
            return []

        # Apply sampling
        if self.sampling is not None:
            file_df = self.apply_sampling(file_df)

        if file_df.empty:
            logger.warning("No files remaining after sampling")
            return []

        # Group by period
        batches = self._group_by_period(file_df)

        logger.info(f"Created {len(batches)} batches from {len(file_paths)} input files")

        return batches

    def _build_file_dataframe(self, file_paths: list[str]) -> pd.DataFrame:
        """
        Build DataFrame with file paths and extracted timestamps.

        Args:
            file_paths: List of file paths

        Returns:
            DataFrame with columns: file_path, timestamp
        """
        records = []

        for file_path in file_paths:
            timestamp = self.extract_timestamp(file_path)
            if timestamp is not None:
                records.append({"file_path": file_path, "timestamp": timestamp})
            else:
                logger.debug(f"Could not extract timestamp from: {file_path}")

        if not records:
            return pd.DataFrame(columns=["file_path", "timestamp"])

        df = pd.DataFrame(records)
        df = df.sort_values("timestamp").reset_index(drop=True)

        logger.debug(f"Built file DataFrame with {len(df)} files")

        return df

    def extract_timestamp(self, file_path: str) -> datetime | None:
        """
        Extract timestamp from file path or file metadata.

        Made public for testing and utility use.

        Args:
            file_path: Path to the file

        Returns:
            Extracted timezone-aware timestamp or None if extraction failed
        """
        # Try to extract from filename using regex
        filename = Path(file_path).name
        match = self.iso_date_regex.search(filename)

        if match:
            date_str = match.group(1)
            try:
                # Try common datetime formats
                for fmt in [
                    "%Y-%m-%dT%H:%M:%S.%f",  # With microseconds
                    "%Y-%m-%dT%H-%M-%S.%f",  # With microseconds (Windows-safe hyphens)
                    "%Y-%m-%d %H:%M:%S.%f",
                    "%Y-%m-%d_%H:%M:%S.%f",
                    "%Y-%m-%d %H-%M-%S.%f",
                    "%Y-%m-%d %H:%M:%S",
                    "%Y-%m-%dT%H:%M:%S",
                    "%Y-%m-%dT%H-%M-%S",  # Windows-safe hyphens
                    "%Y-%m-%d_%H:%M:%S",
                    "%Y-%m-%d %H-%M-%S",
                    "%Y-%m-%d",
                ]:
                    try:
                        dt = datetime.strptime(date_str, fmt)
                        # Make timezone-aware (UTC)
                        if dt.tzinfo is None:
                            dt = dt.replace(tzinfo=timezone.utc)
                        return dt
                    except ValueError:
                        continue

                # Fallback: try pandas parser
                dt = pd.to_datetime(date_str)
                # Convert to timezone-aware datetime
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                return dt

            except Exception as e:
                logger.debug(f"Failed to parse timestamp '{date_str}' from {filename}: {e}")

        # Fallback: use file modification time
        try:
            path = Path(file_path)
            if path.exists():
                mtime = path.stat().st_mtime
                dt = datetime.fromtimestamp(mtime, tz=timezone.utc)
                return dt
        except Exception as e:
            logger.debug(f"Failed to get modification time for {file_path}: {e}")

        return None

    def _filter_by_time_window(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Filter DataFrame by time window (start_time, end_time).

        Args:
            df: DataFrame with 'timestamp' column

        Returns:
            Filtered DataFrame
        """
        original_len = len(df)

        if self.start_time:
            df = df[df["timestamp"] >= self.start_time]

        if self.end_time:
            df = df[df["timestamp"] < self.end_time]

        filtered_len = len(df)
        logger.debug(
            f"Time window filter: {original_len} -> {filtered_len} files (start={self.start_time}, end={self.end_time})"
        )

        return df.reset_index(drop=True)

    def apply_sampling(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Apply sampling strategy to DataFrame.

        Made public for testing and utility use.

        Sampling modes:
        - str: Pandas frequency for resampling (e.g., "12H", "D")
        - float: Sample this fraction of rows
        - int: Sample this many rows

        Args:
            df: DataFrame with 'timestamp' column

        Returns:
            Sampled DataFrame
        """
        original_len = len(df)

        if isinstance(self.sampling, str):
            # Frequency resampling
            df = df.set_index("timestamp")
            df = df.resample(self.sampling).first().dropna().reset_index()

        elif isinstance(self.sampling, float):
            # Fractional sampling
            sample_size = max(1, int(len(df) * self.sampling))
            df = df.sample(n=sample_size, random_state=42).sort_values("timestamp")
            df = df.reset_index(drop=True)

        elif isinstance(self.sampling, int):
            # Fixed count sampling
            sample_size = min(self.sampling, len(df))
            df = df.sample(n=sample_size, random_state=42).sort_values("timestamp")
            df = df.reset_index(drop=True)

        sampled_len = len(df)
        logger.debug(f"Sampling applied: {original_len} -> {sampled_len} files (strategy={self.sampling})")

        return df

    def _group_by_period(self, df: pd.DataFrame) -> list[list[str]]:
        """
        Group files by time period.

        Args:
            df: DataFrame with 'timestamp' and 'file_path' columns

        Returns:
            List of batches (each batch is a list of file paths)
        """
        # Create period column
        df["period"] = df["timestamp"].dt.to_period(self.period)  # type: ignore[attr-defined]

        # Group by period and extract file paths
        batches = []
        for period, group in df.groupby("period", sort=True):
            batch = group["file_path"].tolist()
            batches.append(batch)
            logger.debug(f"Period {period}: {len(batch)} files")

        return batches

    def batch_by_count(self, file_paths: list[str], batch_size: int = 100) -> list[list[str]]:
        """
        Simple batch by count (no time-based grouping).

        This is a convenience method for when you just want fixed-size batches
        without time-based logic.

        Args:
            file_paths: List of file paths
            batch_size: Number of files per batch

        Returns:
            List of batches

        Example:
            >>> batcher = FileBatcher()
            >>> batches = batcher.batch_by_count(files, batch_size=50)
        """
        if batch_size <= 0:
            raise ValueError(f"batch_size must be > 0, got {batch_size}")

        batches = []
        for i in range(0, len(file_paths), batch_size):
            batch = file_paths[i : i + batch_size]
            batches.append(batch)

        logger.debug(f"Created {len(batches)} batches of size ~{batch_size}")

        return batches


__all__ = ["FileBatcher"]
