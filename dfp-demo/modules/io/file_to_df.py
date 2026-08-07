"""
File to DataFrame Module for DFP Pipeline

This module loads files (JSON, CSV, Parquet) into pandas DataFrames with schema validation,
null filtering, timestamp parsing, and source schema transformation.
Aligned with NVIDIA Morpheus DFP architecture.

Key Features:
- Multi-format support (JSON, JSON Lines, CSV, Parquet)
- Source schema transformation (nested JSON flattening, column renaming)
- Schema validation and enforcement
- Null value filtering
- Timestamp parsing and timezone handling
- Configurable parser parameters
- NVIDIA-aligned implementation patterns

NVIDIA Compliance:
    - Applies source schema to flatten nested JSON (e.g., Azure AD "properties")
    - Creates derived fields (e.g., "location" from city + country via StringCatColumn)
    - Matches DFPFileToDataFrameStage behavior

Reference:
    /nv-morpheus/python/morpheus_dfp/morpheus_dfp/stages/dfp_file_to_df.py
"""

from __future__ import annotations

import logging
from pathlib import Path

import pandas as pd

logger = logging.getLogger(__name__)


class FileToDataFrame:
    """
    Load files into pandas DataFrames with validation and preprocessing.

    This class provides robust file loading with:
    - Automatic format detection (JSON/CSV/Parquet)
    - Schema validation (required columns, types)
    - Null filtering
    - Timestamp parsing
    - Error handling and logging

    Attributes:
        schema (Dict): Expected schema definition
        filter_null (bool): Whether to filter rows with null values
        file_type (str): Expected file type ("JSON", "CSV", "PARQUET", "AUTO")
        parser_kwargs (Dict): Additional kwargs for pandas read functions
        timestamp_column (str): Name of timestamp column
        required_columns (Set[str]): Set of required column names

    Example:
        >>> config = {
        ...     "file_type": "JSON",
        ...     "timestamp_column_name": "timestamp",
        ...     "filter_null": True
        ... }
        >>> loader = FileToDataFrame(config)
        >>> df = loader.load_files(["data.json"])
    """

    def __init__(self, config: dict | None = None):
        """
        Initialize FileToDataFrame with configuration.

        Args:
            config: Configuration dictionary with optional keys:
                - source_schema: DataFrameInputSchema for source transformation (NVIDIA pattern)
                - schema: Schema definition with 'required' field
                - filter_null: Filter null values (default: True)
                - file_type: File type ("JSON", "CSV", "PARQUET", "AUTO") (default: "AUTO")
                - parser_kwargs: Additional parser arguments (default: {})
                - timestamp_column_name: Timestamp column name (default: "timestamp")

        Note:
            If source_schema is provided, it will be applied after loading to transform
            nested JSON structures (e.g., Azure AD logs with "properties" object).
        """
        config = config or {}

        self.source_schema = config.get("source_schema", None)
        self.schema = config.get("schema", None)
        self.filter_null = config.get("filter_null", True)
        self.file_type = config.get("file_type", "AUTO").upper()
        self.parser_kwargs = config.get("parser_kwargs", {})
        self.timestamp_column = config.get("timestamp_column_name", "timestamp")

        # Extract required columns from schema
        self.required_columns: set[str] = set()
        if self.schema and "required" in self.schema:
            self.required_columns = set(self.schema["required"])

        logger.debug(
            f"FileToDataFrame initialized: file_type={self.file_type}, "
            f"filter_null={self.filter_null}, timestamp_column={self.timestamp_column}, "
            f"has_source_schema={self.source_schema is not None}"
        )

    def load_files(self, file_paths: list[str]) -> pd.DataFrame:
        """
        Load and concatenate multiple files into a single DataFrame.

        This method (NVIDIA pattern):
        1. Loads each file individually
        2. Applies source schema transformation (if configured) - FLATTENS NESTED JSON
        3. Validates schema for each file
        4. Concatenates all DataFrames
        5. Parses timestamps
        6. Filters nulls if configured
        7. Resets index

        Args:
            file_paths: List of file paths to load

        Returns:
            Concatenated pandas DataFrame with source schema applied

        Raises:
            ValueError: If no valid files could be loaded
        """
        if not file_paths:
            logger.warning("Empty file_paths provided to load_files()")
            return pd.DataFrame()

        frames: list[pd.DataFrame] = []

        for file_path in file_paths:
            try:
                df = self.load_single_file(file_path)
                print(f"DEBUG FileToDataFrame: After load_single_file: {len(df)} rows")

                if df.empty:
                    logger.warning(f"Empty DataFrame from {file_path}, skipping")
                    continue

                # NVIDIA pattern: Apply source schema to transform nested JSON
                if self.source_schema is not None:
                    df = self.apply_source_schema(df)
                    print(f"DEBUG FileToDataFrame: After apply_source_schema: {len(df)} rows")

                # Validate schema
                if not self.validate_schema(df):
                    logger.error(f"Schema validation failed for {file_path}, skipping")
                    continue

                frames.append(df)
                logger.debug(f"Loaded {len(df)} rows from {file_path}")

            except Exception as e:
                logger.error(f"Failed to load {file_path}: {e}", exc_info=True)
                continue

        if not frames:
            logger.warning("No valid files loaded")
            return pd.DataFrame()

        # Concatenate all DataFrames
        df = pd.concat(frames, ignore_index=True, copy=False)
        logger.info(f"Concatenated {len(frames)} files into DataFrame with {len(df)} rows")
        print(f"DEBUG FileToDataFrame: After concat: {len(df)} rows")

        # Parse timestamps
        df = self.parse_timestamps(df)
        print(f"DEBUG FileToDataFrame: After parse_timestamps: {len(df)} rows")

        # Filter nulls
        if self.filter_null:
            df = self.filter_nulls(df)
            print(f"DEBUG FileToDataFrame: After filter_nulls: {len(df)} rows")

        # Reset index
        df = df.reset_index(drop=True)

        logger.info(f"Final DataFrame: {len(df)} rows, {len(df.columns)} columns")

        return df

    def load_single_file(self, file_path: str) -> pd.DataFrame:
        """
        Load a single file into a DataFrame.

        Supports:
        - JSON (array or JSON Lines)
        - CSV
        - Parquet

        Args:
            file_path: Path to file

        Returns:
            pandas DataFrame

        Raises:
            FileNotFoundError: If file doesn't exist
            ValueError: If file format is unsupported
        """
        path = Path(file_path)

        if not path.exists():
            raise FileNotFoundError(f"File not found: {file_path}")

        # Determine file type
        if self.file_type == "AUTO":
            file_type = self._detect_file_type(path)
        else:
            file_type = self.file_type

        logger.debug(f"Loading {file_path} as {file_type}")

        try:
            if file_type == "JSON":
                df = self._load_json(path)
            elif file_type == "CSV":
                df = self._load_csv(path)
            elif file_type == "PARQUET":
                df = self._load_parquet(path)
            else:
                raise ValueError(f"Unsupported file type: {file_type}")

            return df

        except Exception as e:
            logger.error(f"Error loading {file_path}: {e}")
            raise

    def _detect_file_type(self, path: Path) -> str:
        """
        Detect file type from extension.

        Args:
            path: Path object

        Returns:
            File type string ("JSON", "CSV", "PARQUET")
        """
        suffix = path.suffix.lower()

        if suffix in {".json", ".jsonl"}:
            return "JSON"
        elif suffix == ".csv":
            return "CSV"
        elif suffix in {".parquet", ".pq"}:
            return "PARQUET"
        else:
            # Default to JSON for unknown extensions
            logger.warning(f"Unknown file extension '{suffix}', assuming JSON")
            return "JSON"

    def _load_json(self, path: Path) -> pd.DataFrame:
        """
        Load JSON file (array or JSON Lines).

        Tries JSON Lines first, then JSON array.

        Args:
            path: Path to JSON file

        Returns:
            pandas DataFrame
        """
        # Try JSON Lines first (more common for log data)
        try:
            df = pd.read_json(path, lines=True, **self.parser_kwargs)
            logger.debug(f"Loaded as JSON Lines: {len(df)} rows")
            return df
        except ValueError:
            pass

        # Try JSON array
        try:
            df = pd.read_json(path, **self.parser_kwargs)
            logger.debug(f"Loaded as JSON array: {len(df)} rows")
            return df
        except Exception as e:
            logger.error(f"Failed to parse JSON from {path}: {e}")
            raise

    def _load_csv(self, path: Path) -> pd.DataFrame:
        """
        Load CSV file.

        Args:
            path: Path to CSV file

        Returns:
            pandas DataFrame
        """
        df = pd.read_csv(path, **self.parser_kwargs)
        logger.debug(f"Loaded CSV: {len(df)} rows")
        return df

    def _load_parquet(self, path: Path) -> pd.DataFrame:
        """
        Load Parquet file.

        Args:
            path: Path to Parquet file

        Returns:
            pandas DataFrame
        """
        df = pd.read_parquet(path, **self.parser_kwargs)
        logger.debug(f"Loaded Parquet: {len(df)} rows")
        return df

    def validate_schema(self, df: pd.DataFrame) -> bool:
        """
        Validate DataFrame against expected schema.

        Checks:
        1. Required columns are present
        2. No unexpected critical issues

        Args:
            df: DataFrame to validate

        Returns:
            True if schema is valid, False otherwise
        """
        if not self.required_columns:
            # No schema defined, skip validation
            return True

        # Check required columns
        missing_columns = self.required_columns - set(df.columns)

        if missing_columns:
            logger.error(f"Missing required columns: {missing_columns}")
            return False

        logger.debug("Schema validation passed: all required columns present")
        return True

    def filter_nulls(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Remove rows with null values in critical columns.

        Filters rows where timestamp or userid columns have null values.

        Args:
            df: DataFrame to filter

        Returns:
            Filtered DataFrame
        """
        original_len = len(df)

        # Define critical columns (must not be null)
        critical_columns = []

        if self.timestamp_column in df.columns:
            critical_columns.append(self.timestamp_column)

        # Also check for common userid columns
        for userid_col in ["username", "user_id", "userid", "Username"]:
            if userid_col in df.columns:
                critical_columns.append(userid_col)
                break

        if not critical_columns:
            logger.warning("No critical columns found for null filtering")
            return df

        print(f"DEBUG filter_nulls: Critical columns: {critical_columns}")
        print(f"DEBUG filter_nulls: DataFrame columns: {df.columns.tolist()[:15]}")
        for col in critical_columns:
            null_count = df[col].isna().sum()
            print(f"DEBUG filter_nulls: {col} has {null_count}/{len(df)} null values")

        # Filter nulls
        df = df.dropna(subset=critical_columns)

        filtered_len = len(df)

        if filtered_len < original_len:
            logger.info(
                f"Filtered {original_len - filtered_len} rows with null values in critical columns: {critical_columns}"
            )

        return df

    def parse_timestamps(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Parse timestamp column to datetime type.

        Converts timestamp column to pandas datetime with UTC timezone.

        Args:
            df: DataFrame with timestamp column

        Returns:
            DataFrame with parsed timestamps
        """
        if self.timestamp_column not in df.columns:
            logger.warning(f"Timestamp column '{self.timestamp_column}' not found in DataFrame")
            return df

        try:
            print(f"DEBUG parse_timestamps: timestamp dtype BEFORE: {df[self.timestamp_column].dtype}")
            print(f"DEBUG parse_timestamps: First 3 timestamps BEFORE: {df[self.timestamp_column].head(3).tolist()}")

            # Convert to datetime
            df[self.timestamp_column] = pd.to_datetime(df[self.timestamp_column], utc=True)

            print(f"DEBUG parse_timestamps: timestamp dtype AFTER: {df[self.timestamp_column].dtype}")
            print(f"DEBUG parse_timestamps: Null count AFTER: {df[self.timestamp_column].isna().sum()}")
            print(f"DEBUG parse_timestamps: First 3 timestamps AFTER: {df[self.timestamp_column].head(3).tolist()}")

            logger.debug(f"Parsed {self.timestamp_column} to datetime (UTC)")

        except Exception as e:
            logger.error(f"Failed to parse timestamps: {e}")
            # Don't fail hard - return original DataFrame

        return df

    def apply_source_schema(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Apply source schema transformation to DataFrame using NVIDIA's process_dataframe.

        NVIDIA pattern: SIMPLE transformations ONLY (flatten JSON, rename columns).
        Does NOT calculate increment features - that happens in dfp_data_prep AFTER rolling window!

        This is where:
        - Nested JSON gets flattened (e.g., "properties.location.city" → "city")
        - Columns get renamed (e.g., "identity" → "username")
        - Simple derived fields (e.g., "location" = city + country via StringCatColumn)

        CRITICAL: Does NOT calculate increment features - that's for dfp_data_prep!

        Args:
            df: Raw DataFrame with nested JSON

        Returns:
            Transformed DataFrame with flattened columns (NO increment features yet)

        Reference:
            NVIDIA: morpheus/utils/schema_transforms.py::process_dataframe()
            - Iterates through column_info
            - Calls _process_column() on each (RenameColumn, DateTimeColumn, etc.)
            - Handles JSON flattening via DataFrameInputSchema.prep_dataframe
        """
        if self.source_schema is None:
            return df

        try:
            logger.debug(f"Applying source schema to {len(df)} rows, {len(df.columns)} columns")
            logger.debug(f"Input columns: {list(df.columns)}")

            # Use our local process_dataframe implementation (NVIDIA pattern)
            # This handles column transformations (rename, type conversion, etc.)
            from modules.preprocessing.column_info import process_dataframe

            df_transformed = process_dataframe(df, self.source_schema)

            logger.info(f"Source schema applied: {len(df_transformed)} rows, {len(df_transformed.columns)} columns")
            logger.debug(f"Output columns: {list(df_transformed.columns)}")

            return df_transformed

        except Exception as e:
            logger.error(f"Failed to apply source schema: {e}", exc_info=True)
            logger.error(f"Available columns: {list(df.columns)}")
            raise


__all__ = ["FileToDataFrame"]
