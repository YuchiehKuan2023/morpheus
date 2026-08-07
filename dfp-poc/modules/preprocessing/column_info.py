"""
Column Info Classes for DFP Preprocessing

This module provides column transformation classes inspired by NVIDIA Morpheus
morpheus.utils.column_info. These classes define how to transform DataFrame columns
during preprocessing.

NVIDIA Reference:
    /nv-morpheus/python/morpheus/morpheus/utils/column_info.py

Notes:
    This is a standalone implementation for the PoC. In production with full Morpheus,
    you would use the official morpheus.utils.column_info classes.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime

import pandas as pd

logger = logging.getLogger(f"morpheus.{__name__}")


@dataclass
class ColumnInfo:
    """
    Basic column information with optional type conversion.

    Parameters
    ----------
    name : str
        Output column name
    dtype : Type
        Target data type for the column
    input_name : Optional[str]
        Source column name (defaults to name if not specified)
    """

    name: str
    dtype: type
    input_name: str | None = None

    def __post_init__(self):
        if self.input_name is None:
            self.input_name = self.name

    def process_column(self, df: pd.DataFrame) -> pd.Series:
        """
        Process a column from the input DataFrame.

        Parameters
        ----------
        df : pd.DataFrame
            Input DataFrame

        Returns
        -------
        pd.Series
            Processed column
        """
        if self.input_name not in df.columns:
            logger.warning(f"Column '{self.input_name}' not found in DataFrame")
            # Return appropriate default based on dtype
            if self.dtype == int:
                return pd.Series([0] * len(df), dtype=self.dtype, name=self.name)
            elif self.dtype == bool:
                return pd.Series([False] * len(df), dtype=self.dtype, name=self.name)
            elif self.dtype == datetime:
                return pd.Series([pd.NaT] * len(df), dtype="datetime64[ns, UTC]", name=self.name)
            else:
                return pd.Series([None] * len(df), dtype=object, name=self.name)

        series = df[self.input_name]

        # Convert dtype if needed
        try:
            if self.dtype == datetime:
                series = pd.to_datetime(series, utc=True, errors="coerce")
            elif self.dtype == bool:
                series = series.astype(bool)
            elif self.dtype == str:
                # For strings, keep NaNs as NaN instead of converting to "nan"
                series = series.astype(object)
            else:
                series = series.astype(self.dtype)
        except Exception as e:
            logger.warning(f"Failed to convert column '{self.name}' to {self.dtype}: {e}")

        return series.rename(self.name)


@dataclass
class DateTimeColumn(ColumnInfo):
    """
    Column for datetime values with timezone handling.

    Parameters
    ----------
    name : str
        Output column name
    dtype : Type
        Should be datetime
    input_name : Optional[str]
        Source column name
    format : Optional[str]
        Datetime format string (None = auto-detect)
    """

    format: str | None = None

    def process_column(self, df: pd.DataFrame) -> pd.Series:
        """Process datetime column with UTC timezone."""
        if self.input_name not in df.columns:
            logger.warning(f"DateTime column '{self.input_name}' not found")
            return pd.Series([None] * len(df), dtype="datetime64[ns, UTC]", name=self.name)

        series = df[self.input_name]

        try:
            if self.format:
                series = pd.to_datetime(series, format=self.format, utc=True, errors="coerce")
            else:
                series = pd.to_datetime(series, utc=True, errors="coerce")
        except Exception as e:
            logger.warning(f"Failed to parse datetime column '{self.name}': {e}")
            series = pd.to_datetime(series, utc=True, errors="coerce")

        return series.rename(self.name)


@dataclass
class StringCatColumn(ColumnInfo):
    """
    Column that concatenates values from multiple columns into a new string column.

    NVIDIA Reference: morpheus.utils.column_info.StringCatColumn
    Used to create composite string columns (e.g., location from city + country)

    Parameters
    ----------
    name : str
        Output column name (e.g., "location")
    dtype : Type
        Data type (should be str)
    input_columns : List[str]
        List of column names to concatenate
    sep : str
        Separator to use when joining values (e.g., ", ")

    Examples
    --------
    >>> # Create location from city and country
    >>> col = StringCatColumn(
    ...     name="location",
    ...     dtype=str,
    ...     input_columns=["city", "country"],
    ...     sep=", "
    ... )
    """

    input_columns: list[str] = field(default_factory=list)
    sep: str = ", "

    def process_column(self, df: pd.DataFrame) -> pd.Series:
        """
        Concatenate values from input columns.

        Parameters
        ----------
        df : pd.DataFrame
            Input DataFrame

        Returns
        -------
        pd.Series
            Concatenated string column
        """
        # Check if all input columns exist
        missing = [col for col in self.input_columns if col not in df.columns]
        if missing:
            logger.warning(f"Missing input columns for {self.name}: {missing}")
            return pd.Series([None] * len(df), dtype=object, name=self.name)

        if not self.input_columns:
            logger.warning(f"No input columns specified for {self.name}")
            return pd.Series([None] * len(df), dtype=object, name=self.name)

        # Start with first column as string
        first_col = df[self.input_columns[0]].astype(str)

        # Concatenate remaining columns if any
        if len(self.input_columns) > 1:
            result = first_col.str.cat(others=df[self.input_columns[1:]].astype(str), sep=self.sep)
        else:
            result = first_col

        return result.rename(self.name)


@dataclass
class IncrementColumn(ColumnInfo):
    """
    NVIDIA OFFICIAL: Column that counts events per group per period (e.g., logcount).

    Follows NVIDIA Morpheus DFP implementation from:
    morpheus/utils/column_info.py lines 479-529

    This creates a cumulative count of rows grouped by user AND time period.
    The key difference from the naive implementation is that it groups by BOTH
    the groupby_column (user) and the period (e.g., day), ensuring that counts
    are comparable between training (60d windows) and inference (1d windows).

    Parameters
    ----------
    name : str
        Output column name (e.g., "logcount")
    dtype : Type
        Data type (typically int)
    input_name : str
        Column containing timestamps (e.g., "timestamp")
    groupby_column : str
        Column to group by (e.g., "username")
    period : str
        Period for time-based grouping (default: "D" for daily)

    Examples
    --------
    >>> # Count events per user per day
    >>> col = IncrementColumn(
    ...     name="logcount",
    ...     dtype=int,
    ...     input_name="timestamp",
    ...     groupby_column="username",
    ...     period="D"
    ... )
    """

    groupby_column: str = "username"
    period: str = "D"  # NVIDIA: Period for time-based grouping

    def process_column(self, df: pd.DataFrame) -> pd.Series:
        """
        NVIDIA OFFICIAL IMPLEMENTATION - Count events grouped by period and user.

        Algorithm (from morpheus/utils/column_info.py lines 519-529):
        1. Convert timestamps to periods (e.g., daily periods)
        2. Group by [groupby_column, period] and use cumcount()
        3. This ensures counts are per-period, not per-window

        Example: With a 60-day window containing 1689 events:
        - Wrong (old): logcount = 1, 2, 3, ..., 1689 (window size dependent)
        - Right (new): logcount = per-day counts like 1-25 per day (window size independent)
        """
        assert self.input_name is not None, f"{self.__class__.__name__} requires input_name"

        required_cols = [self.groupby_column, self.input_name]
        missing_cols = [col for col in required_cols if col not in df.columns]

        if missing_cols:
            logger.error(f"Missing columns for {self.name}: {missing_cols}")
            return pd.Series([0] * len(df), dtype=self.dtype, name=self.name)

        # NVIDIA Step 1: Convert timestamps to periods
        # Remove timezone info to avoid UserWarning
        timestamps = df[self.input_name]
        if timestamps.dt.tz is not None:
            timestamps = timestamps.dt.tz_localize(None)
        period = timestamps.dt.to_period(self.period)

        # NVIDIA Step 2: Group by [groupby_column, period] and cumcount
        # This creates 0-indexed counts, so events 1-10 in a day become 0-9
        series = df.groupby([self.groupby_column, period]).cumcount()

        logger.debug(
            f"Generated {self.name} (NVIDIA algorithm): min={series.min()}, max={series.max()}, "
            f"periods={period.nunique()}, groups={df[self.groupby_column].nunique()}"
        )

        return series.astype(self.dtype).rename(self.name)


@dataclass
class DistinctIncrementColumn(ColumnInfo):
    """
    NVIDIA OFFICIAL: Column that counts distinct values per group over time periods.

    Follows NVIDIA Morpheus DFP implementation from:
    morpheus/utils/column_info.py lines 533-587

    This tracks unique occurrences of a value in `groupby_column` over specific time
    periods based on the `timestamp_column` field. Uses factorization + expanding max
    to create incremental counts that properly continue across inference runs.

    Parameters
    ----------
    name : str
        Output column name (e.g., "locincrement", "appincrement")
    dtype : Type
        Data type (typically int)
    input_name : str
        Column whose distinct values to count (e.g., "location", "appDisplayName")
    groupby_column : str
        Column to group by (default: "username")
    period : str
        Period for time-based grouping (default: "D" for daily)
    timestamp_column : str
        Column used for determining periods (default: "timestamp")

    Examples
    --------
    >>> # Count distinct locations per user per day
    >>> col = DistinctIncrementColumn(
    ...     name="locincrement",
    ...     dtype=int,
    ...     input_name="location",
    ...     groupby_column="username",
    ...     period="D",
    ...     timestamp_column="timestamp"
    ... )
    """

    groupby_column: str = "username"
    period: str = "D"  # NVIDIA: Period for time-based grouping
    timestamp_column: str = "timestamp"

    def process_column(self, df: pd.DataFrame) -> pd.Series:
        """
        NVIDIA OFFICIAL IMPLEMENTATION - Count unique occurrences grouped by period and user.

        Algorithm (from morpheus/utils/column_info.py lines 565-587):
        1. Convert timestamps to periods (e.g., daily periods)
        2. Group by [period, user], factorize values within each group
        3. Use expanding max to get cumulative max across periods

        This creates incremental counts that increase across time periods.
        """
        # Type assertion: input_name is set in __post_init__ if None
        assert self.input_name is not None, f"{self.__class__.__name__} requires input_name"

        required_cols = [self.groupby_column, self.input_name, self.timestamp_column]
        missing_cols = [col for col in required_cols if col not in df.columns]

        if missing_cols:
            logger.error(f"Missing columns for {self.name}: {missing_cols}")
            return pd.Series([0] * len(df), dtype=self.dtype, name=self.name)

        # NVIDIA Step 1: Convert timestamps to periods
        # Remove timezone info to avoid UserWarning about dropping timezone during to_period()
        timestamps = df[self.timestamp_column]
        if timestamps.dt.tz is not None:
            timestamps = timestamps.dt.tz_localize(None)
        per_period = timestamps.dt.to_period(self.period)

        # NVIDIA Step 2: Group by [period, user] and factorize values within each group
        # factorize assigns 0, 1, 2... to distinct values (0-indexed), then we add 1
        cat_col: pd.Series = df.groupby([per_period, self.groupby_column])[self.input_name].transform(
            lambda x: pd.factorize(x.fillna("nan"))[0] + 1
        )

        # NVIDIA Step 3: Use expanding max to get cumulative across periods
        # This carries forward the maximum from previous periods
        increment_col = (
            pd.concat([cat_col, df[self.groupby_column]], axis=1)
            .groupby([per_period, self.groupby_column])[self.input_name]
            .expanding(1)
            .max()
            .droplevel(0)
            .droplevel(0)
        )

        # Convert to proper dtype and set name
        series = increment_col.astype(self.dtype)
        series.name = self.name

        logger.debug(
            f"Generated {self.name} (NVIDIA algorithm): min={series.min()}, max={series.max()}, "
            f"periods={per_period.nunique()}, groups={df[self.groupby_column].nunique()}"
        )

        return series


@dataclass
class DataFrameInputSchema:
    """
    Schema defining how to transform input DataFrame columns.

    This class holds a list of column transformations to apply to an input DataFrame.
    Supports JSON flattening for nested structures (e.g., Azure AD logs).

    Parameters
    ----------
    column_info : List[ColumnInfo]
        List of column transformation specifications
    preserve_columns : List[str]
        Columns to preserve from input without transformation (e.g., ["_batch_id"])
    json_columns : List[str], optional
        List of columns containing nested JSON to flatten (e.g., ["properties"])
        NVIDIA pattern: Azure AD logs have nested "properties" object

    Examples
    --------
    >>> # NVIDIA Azure AD pattern with nested JSON:
    >>> schema = DataFrameInputSchema(
    ...     json_columns=["properties"],
    ...     column_info=[
    ...         DateTimeColumn(name="timestamp", dtype=datetime, input_name="time"),
    ...         RenameColumn(name="username", dtype=str, input_name="properties.userPrincipalName"),
    ...         StringCatColumn(name="location", dtype=str,
    ...                        input_columns=["properties.location.city", "properties.location.countryOrRegion"],
    ...                        sep=", "),
    ...     ],
    ...     preserve_columns=["_batch_id"]
    ... )
    """

    column_info: list[ColumnInfo] = field(default_factory=list)
    preserve_columns: list[str] = field(default_factory=list)
    json_columns: list[str] = field(default_factory=list)

    def get_column_names(self) -> list[str]:
        """Get list of output column names."""
        return [col.name for col in self.column_info]

    def get_input_column_names(self) -> list[str]:
        """Get list of input column names required."""
        input_names = set()
        for col in self.column_info:
            input_names.add(col.input_name)
            # Add special columns for derived features
            if isinstance(col, (IncrementColumn, DistinctIncrementColumn)):
                input_names.add(col.groupby_column)
            if isinstance(col, DistinctIncrementColumn):
                input_names.add(col.timestamp_column)
            # Add input columns for StringCatColumn
            if isinstance(col, StringCatColumn):
                input_names.update(col.input_columns)
        return list(input_names)


def _flatten_json_columns(df: pd.DataFrame, json_columns: list[str]) -> pd.DataFrame:
    """
    Flatten nested JSON columns in DataFrame.

    NVIDIA pattern: Azure AD logs have nested "properties" object.
    This function flattens it so "properties.location.city" becomes a column.

    Parameters
    ----------
    df : pd.DataFrame
        Input DataFrame with nested JSON columns
    json_columns : List[str]
        List of column names containing nested JSON

    Returns
    -------
    pd.DataFrame
        DataFrame with flattened JSON columns

    Example
    -------
    >>> # Input: {"properties": {"location": {"city": "London"}}}
    >>> # Output: column "properties.location.city" = "London"
    """
    if not json_columns:
        return df

    df_flattened = df.copy()

    for json_col in json_columns:
        if json_col not in df.columns:
            logger.warning(f"JSON column '{json_col}' not found in DataFrame")
            continue

        # Normalize JSON column to flatten nested structure
        try:
            # Convert Series to list of dictionaries for json_normalize
            json_data = df[json_col].tolist()
            json_df = pd.json_normalize(json_data)
            # Prefix flattened columns with original column name
            json_df.columns = [f"{json_col}.{col}" for col in json_df.columns]

            # Add flattened columns to DataFrame
            for col in json_df.columns:
                df_flattened[col] = json_df[col].values

            # Drop original JSON column
            df_flattened = df_flattened.drop(columns=[json_col])

            logger.debug(f"Flattened JSON column '{json_col}' into {len(json_df.columns)} columns")

        except Exception as e:
            logger.error(f"Failed to flatten JSON column '{json_col}': {e}")

    return df_flattened


def process_dataframe(df: pd.DataFrame, schema: DataFrameInputSchema) -> pd.DataFrame:
    """
    Process DataFrame according to schema transformations.

    This is the main preprocessing function that applies all column transformations
    defined in the schema. Supports JSON flattening for nested structures.

    NVIDIA Compliance:
        - Flattens nested JSON columns (e.g., "properties" in Azure AD logs)
        - Applies column transformations (rename, concatenate, derive)
        - Preserves specified columns

    Parameters
    ----------
    df : pd.DataFrame
        Input DataFrame with raw data (may have nested JSON)
    schema : DataFrameInputSchema
        Schema defining transformations

    Returns
    -------
    pd.DataFrame
        Processed DataFrame with transformed columns

    Examples
    --------
    >>> # NVIDIA Azure AD pattern:
    >>> schema = DataFrameInputSchema(
    ...     json_columns=["properties"],
    ...     column_info=[...]
    ... )
    >>> df_processed = process_dataframe(df_raw, schema)
    """
    logger.info(f"Processing DataFrame: {len(df)} rows, {len(df.columns)} columns")

    # Step 1: Flatten JSON columns if specified (NVIDIA pattern)
    if schema.json_columns:
        df = _flatten_json_columns(df, schema.json_columns)
        logger.debug(f"After JSON flattening: {len(df.columns)} columns")

    # Step 2: Process each column according to schema
    processed_columns = {}

    for col_info in schema.column_info:
        try:
            processed_columns[col_info.name] = col_info.process_column(df)
        except Exception as e:
            logger.error(f"Failed to process column '{col_info.name}': {e}")
            # Create empty column with correct dtype
            processed_columns[col_info.name] = pd.Series([None] * len(df), dtype=col_info.dtype, name=col_info.name)

    # Step 3: Create output DataFrame
    df_out = pd.DataFrame(processed_columns, index=df.index)

    # Step 4: Add preserved columns
    for col in schema.preserve_columns:
        if col in df.columns:
            df_out[col] = df[col]
        else:
            logger.debug(f"Preserve column '{col}' not found in input")

    logger.info(
        f"Preprocessing complete: {len(df_out)} rows, {len(df_out.columns)} columns "
        f"({len(schema.column_info)} transformed + {len([c for c in schema.preserve_columns if c in df.columns])} preserved)"
    )

    return df_out
