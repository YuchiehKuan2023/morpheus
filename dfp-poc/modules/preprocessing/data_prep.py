"""
Data Preparation Module for DFP Training Pipeline.

This module prepares windowed data for AutoEncoder training by:
1. Selecting feature columns based on schema configuration
2. Filtering out identity columns (username, timestamp, etc.)
3. Returning DataFrame ready for AutoEncoder.fit()

The module follows NVIDIA Morpheus DFPDataPrep module patterns.

NVIDIA Reference:
- python/morpheus_dfp/morpheus_dfp/modules/dfp_data_prep.py
- python/morpheus/morpheus/models/dfencoder/autoencoder.py (prepare_df method)

Author: DFP PoC Implementation
Date: 2025-11-10
"""

import logging

import pandas as pd

logger = logging.getLogger(__name__)


class DataPrep:
    """
    Prepare data for DFP model training or inference.

    This module handles feature selection and validation before feeding
    data to the AutoEncoder model. The AutoEncoder itself handles:
    - StandardScaler normalization for numerical features
    - Categorical encoding
    - Binary feature encoding

    Following NVIDIA Morpheus patterns, this module focuses on:
    - Feature column selection from schema
    - Exclusion of identity columns (username, timestamp, batch_id)
    - Input validation

    Attributes:
        feature_columns (List[str]): List of feature column names to use
        exclude_columns (List[str]): Columns to exclude (identity, metadata)
        timestamp_column (str): Name of timestamp column
        userid_column (str): Name of user ID column

    Example:
        >>> config = {
        ...     "feature_columns": ["logcount", "locincrement", "appincrement"],
        ...     "timestamp_column": "timestamp",
        ...     "userid_column": "username"
        ... }
        >>> data_prep = DataPrep(config)
        >>> df_prepared = data_prep.prepare(df_windowed)
    """

    def __init__(self, config: dict):
        """
        Initialize DataPrep module.

        Parameters:
            config (Dict): Configuration dictionary with keys:
                - feature_columns (List[str]): Feature columns to select
                - timestamp_column (str): Timestamp column name (default: "timestamp")
                - userid_column (str): User ID column name (default: "username")
                - exclude_columns (List[str]): Additional columns to exclude (default: [])
        """
        self.feature_columns = config.get("feature_columns", [])
        self.timestamp_column = config.get("timestamp_column", "timestamp")
        self.userid_column = config.get("userid_column", "username")

        # Build exclusion list
        base_exclude = [
            self.userid_column,
            self.timestamp_column,
            "batch_id",  # Batch identifier
            "_row_hash",  # Rolling window hash column
        ]
        additional_exclude = config.get("exclude_columns", [])
        self.exclude_columns = list(set(base_exclude + additional_exclude))

        logger.debug(
            "DataPrep initialized with %d feature columns, excluding: %s",
            len(self.feature_columns),
            ", ".join(self.exclude_columns),
        )

    def prepare(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Prepare DataFrame for model training/inference.

        This method:
        1. Validates input DataFrame
        2. Selects feature columns
        3. Excludes identity/metadata columns
        4. Returns clean DataFrame ready for AutoEncoder

        Note: The AutoEncoder.fit() method handles:
        - StandardScaler normalization (_init_numeric)
        - Categorical encoding (_init_cats)
        - Binary feature encoding (_init_binary)

        Parameters:
            df (pd.DataFrame): Input DataFrame with all columns

        Returns:
            pd.DataFrame: Prepared DataFrame with only feature columns

        Raises:
            ValueError: If input validation fails
        """
        if df is None or df.empty:
            raise ValueError("Input DataFrame cannot be None or empty")

        # Log preprocessing start
        if logger.isEnabledFor(logging.DEBUG):
            logger.debug("Preparing data: %d rows, %d columns", len(df), len(df.columns))

        # Select feature columns
        df_prepared = self._select_features(df)

        # Validate result
        if df_prepared.empty:
            raise ValueError("Feature selection resulted in empty DataFrame")

        if logger.isEnabledFor(logging.DEBUG):
            logger.debug("Data preparation complete: %d rows, %d features", len(df_prepared), len(df_prepared.columns))

        return df_prepared

    def _select_features(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Select feature columns from DataFrame.

        Selection logic:
        1. If feature_columns specified: use intersection with DataFrame columns
        2. Else: use all columns except excluded ones
        3. Always exclude: userid_column, timestamp_column, batch_id, _row_hash

        Parameters:
            df (pd.DataFrame): Input DataFrame

        Returns:
            pd.DataFrame: DataFrame with selected features
        """
        available_columns = set(df.columns)
        exclude_set = set(self.exclude_columns)

        if self.feature_columns:
            # Use specified feature columns (intersection with available)
            feature_set = set(self.feature_columns)
            selected = feature_set & available_columns

            # Warn about missing columns
            missing = feature_set - available_columns
            if missing:
                logger.warning("Feature columns not found in DataFrame: %s", ", ".join(sorted(missing)))
        else:
            # Use all columns except excluded
            selected = available_columns - exclude_set

        # Always exclude identity/metadata columns
        selected = selected - exclude_set

        if not selected:
            raise ValueError(
                f"No features selected. Available: {sorted(available_columns)}, "
                f"Requested: {sorted(self.feature_columns) if self.feature_columns else 'all'}, "
                f"Excluded: {sorted(exclude_set)}"
            )

        # Maintain column order if feature_columns specified
        if self.feature_columns:
            # Use feature_columns order where available
            ordered_features = [col for col in self.feature_columns if col in selected]
            # Add any remaining selected columns
            remaining = selected - set(ordered_features)
            ordered_features.extend(sorted(remaining))
        else:
            # Alphabetical order
            ordered_features = sorted(selected)

        logger.debug(
            "Selected %d features: %s",
            len(ordered_features),
            ", ".join(ordered_features[:10]) + ("..." if len(ordered_features) > 10 else ""),
        )

        return df[ordered_features].copy()

    def get_feature_columns(self) -> list[str]:
        """
        Get configured feature column names.

        Returns:
            List[str]: List of feature column names
        """
        return self.feature_columns.copy()

    def get_exclude_columns(self) -> list[str]:
        """
        Get excluded column names.

        Returns:
            List[str]: List of excluded column names
        """
        return self.exclude_columns.copy()


def prepare_dataframe(
    df: pd.DataFrame,
    feature_columns: list[str] | None = None,
    timestamp_column: str = "timestamp",
    userid_column: str = "username",
    exclude_columns: list[str] | None = None,
) -> pd.DataFrame:
    """
    Convenience function for preparing a DataFrame.

    This is a stateless wrapper around DataPrep.prepare() for one-time use.
    For multiple DataFrames, create a DataPrep instance for better performance.

    Parameters:
        df (pd.DataFrame): Input DataFrame
        feature_columns (List[str], optional): Feature columns to select
        timestamp_column (str): Timestamp column name
        userid_column (str): User ID column name
        exclude_columns (List[str], optional): Additional columns to exclude

    Returns:
        pd.DataFrame: Prepared DataFrame

    Example:
        >>> df_prepared = prepare_dataframe(
        ...     df,
        ...     feature_columns=["logcount", "locincrement"],
        ...     timestamp_column="timestamp",
        ...     userid_column="username"
        ... )
    """
    config = {
        "feature_columns": feature_columns or [],
        "timestamp_column": timestamp_column,
        "userid_column": userid_column,
        "exclude_columns": exclude_columns or [],
    }

    data_prep = DataPrep(config)
    return data_prep.prepare(df)
