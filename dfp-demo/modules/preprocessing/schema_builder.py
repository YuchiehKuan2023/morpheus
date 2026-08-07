"""
Schema Builder for DFP Preprocessing

This module constructs a DataFrameInputSchema from the feature_schema.yaml configuration.
It creates the appropriate column_info objects (ColumnInfo, DateTimeColumn, IncrementColumn, etc.)
based on the feature definitions in the YAML schema.

NVIDIA Reference:
    /nv-morpheus/examples/digital_fingerprinting/production/dfp_azure_pipeline.py
    Lines 294-371: preprocess_column_info definition
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import TYPE_CHECKING, Any

import yaml

if TYPE_CHECKING:
    from modules.preprocessing.column_info import DataFrameInputSchema

logger = logging.getLogger(f"morpheus.{__name__}")


def build_preprocessing_schema_from_config(
    schema_file: str, feature_set: str = "default", preserve_columns: list[str] | None = None
) -> DataFrameInputSchema:
    """
    Build DataFrameInputSchema from feature_schema.yaml configuration.

    This function reads the feature schema YAML and constructs a DataFrameInputSchema
    with the appropriate column_info transformations. It follows the NVIDIA Azure AD pattern.

    Parameters
    ----------
    schema_file : str
        Path to feature_schema.yaml file
    feature_set : str
        Which feature set to use: "default", "azure_ad_standard", "minimal", "extended"
        (default: "default")
    preserve_columns : Optional[List[str]]
        Additional columns to preserve through preprocessing (e.g., ["_batch_id"])

    Returns
    -------
    DataFrameInputSchema
        Configured schema ready for process_dataframe()

    Examples
    --------
    >>> schema = build_preprocessing_schema_from_config("config/feature_schema.yaml")
    >>> df_processed = process_dataframe(df, schema)

    Notes
    -----
    The schema includes:
    - Core columns (username, timestamp, app, device, location fields)
    - Derived behavioral features (logcount, locincrement, appincrement)
    - Type casting for proper dtypes

    Column info types used:
    - ColumnInfo: Basic column with type casting
    - DateTimeColumn: Timestamp parsing with UTC timezone
    - IncrementColumn: Cumulative count per user (logcount)
    - DistinctIncrementColumn: Distinct value counter (locincrement, appincrement)
    """
    from modules.preprocessing.column_info import (
        ColumnInfo,
        DataFrameInputSchema,
        DateTimeColumn,
        DistinctIncrementColumn,
        IncrementColumn,
    )

    # Load feature schema
    with open(schema_file) as f:
        feature_config = yaml.safe_load(f)

    # Get feature set configuration
    model_features = feature_config.get("model_features", {})
    if feature_set not in model_features:
        logger.warning(f"Feature set '{feature_set}' not found in schema, using 'default'")
        feature_set = "default"

    selected_features = model_features[feature_set]
    logger.info(f"Building preprocessing schema with feature set '{feature_set}' ({len(selected_features)} features)")

    # Build column_info list following NVIDIA Azure AD pattern
    column_info = []

    # 1. Core columns (identity and temporal)
    # Timestamp column - convert to datetime with UTC
    column_info.append(DateTimeColumn(name="timestamp", dtype=datetime, input_name="timestamp"))

    # Username column
    column_info.append(ColumnInfo(name="username", dtype=str))

    # 2. Categorical columns (apps, devices, locations)
    # These get basic ColumnInfo with string dtype
    categorical_features = feature_config.get("categorical_features", {})

    categorical_columns = [
        "appDisplayName",
        "resourceDisplayName",
        "clientAppUsed",
        "deviceDetailbrowser",
        "deviceDetaildisplayName",
        "deviceDetailoperatingSystem",
        "statusfailureReason",
        "location",
        "location_city_state_country",
        "location_state_country",
        "location_country",
        "autonomousSystemNumber",
        "category",
    ]

    for col in categorical_columns:
        # Only add if it's in selected features or is a dependency
        if col in selected_features or _is_dependency_column(col, selected_features, feature_config):
            # Check if enabled in config
            if col in categorical_features:
                if categorical_features[col].get("enabled", True):
                    column_info.append(ColumnInfo(name=col, dtype=str))
            else:
                # Not in config, include by default if in selected features
                if col in selected_features:
                    column_info.append(ColumnInfo(name=col, dtype=str))

    # 3. Numerical columns (coordinates, metrics)
    numerical_columns = {
        "location_geoCoordinates_latitude": float,
        "location_geoCoordinates_longitude": float,
        "travel_speed_kmph": float,
        "distance_km": float,
        "ts_delta_hour": float,
        "autonomousSystemNumber": int,
    }

    # CRITICAL: Always include coordinate columns if travel_speed_kmph is in features
    # Coordinates are required as INPUT to calculate geographic features (travel_speed_kmph)
    # even though they may not be in the final model feature set
    coordinate_cols = ["location_geoCoordinates_latitude", "location_geoCoordinates_longitude"]
    coords_added = set()  # Track which coordinates we've already added
    if "travel_speed_kmph" in selected_features:
        for col in coordinate_cols:
            if col not in selected_features:
                logger.debug(f"Adding {col} as dependency for travel_speed_kmph calculation")
                column_info.append(ColumnInfo(name=col, dtype=float))
                coords_added.add(col)

    for col, dtype in numerical_columns.items():
        if col in selected_features and col not in coords_added:
            column_info.append(ColumnInfo(name=col, dtype=dtype))

    # 4. Boolean columns
    boolean_columns = ["is_corp_vpn", "is_weekend"]
    for col in boolean_columns:
        if col in selected_features:
            column_info.append(ColumnInfo(name=col, dtype=bool))

    # 5. Location column
    # NVIDIA pattern: location is created in source schema via StringCatColumn from JSON properties
    # Our synthetic data generator already includes the "location" field (city, country)
    # So we just include it as-is in the schema
    column_info.append(ColumnInfo(name="location", dtype=str))

    # 6. Derived behavioral features (NVIDIA pattern)
    # These are the key DFP features using Morpheus column info classes

    behavioral_features = feature_config.get("behavioral_features", {})

    # logcount: Cumulative count of events per user
    # Uses IncrementColumn to count events based on timestamp
    if "logcount" in selected_features:
        logcount_params = behavioral_features.get("logcount", {}).get("morpheus_params", {})
        column_info.append(
            IncrementColumn(
                name="logcount",
                dtype=int,
                input_name=logcount_params.get("input_name", "timestamp"),
                groupby_column=logcount_params.get("groupby_column", "username"),
            )
        )
        logger.debug("Added IncrementColumn for 'logcount'")

    # locincrement: Count of distinct locations per user
    # Uses DistinctIncrementColumn to track location changes
    if "locincrement" in selected_features:
        locincrement_params = behavioral_features.get("locincrement", {}).get("morpheus_params", {})
        column_info.append(
            DistinctIncrementColumn(
                name="locincrement",
                dtype=int,
                input_name=locincrement_params.get("input_name", "location"),
                groupby_column=locincrement_params.get("groupby_column", "username"),
                timestamp_column=locincrement_params.get("timestamp_column", "timestamp"),
            )
        )
        logger.debug("Added DistinctIncrementColumn for 'locincrement'")

    # appincrement: Count of distinct applications per user
    # Uses DistinctIncrementColumn to track app changes
    if "appincrement" in selected_features:
        appincrement_params = behavioral_features.get("appincrement", {}).get("morpheus_params", {})
        column_info.append(
            DistinctIncrementColumn(
                name="appincrement",
                dtype=int,
                input_name=appincrement_params.get("input_name", "appDisplayName"),
                groupby_column=appincrement_params.get("groupby_column", "username"),
                timestamp_column=appincrement_params.get("timestamp_column", "timestamp"),
            )
        )
        logger.debug("Added DistinctIncrementColumn for 'appincrement'")

    # Preserve columns (e.g., _batch_id for tracking through pipeline)
    if preserve_columns is None:
        preserve_columns = ["_batch_id"]

    # Create and return DataFrameInputSchema
    schema = DataFrameInputSchema(column_info=column_info, preserve_columns=preserve_columns)

    logger.info(
        f"Built preprocessing schema with {len(column_info)} column transformations, "
        f"preserving {len(preserve_columns)} columns"
    )

    return schema


def _is_dependency_column(column: str, selected_features: list[str], feature_config: dict) -> bool:
    """
    Check if a column is a dependency for derived features.

    For example, 'location' is needed for 'locincrement' even if not in selected features.

    Parameters
    ----------
    column : str
        Column name to check
    selected_features : List[str]
        List of selected feature names
    feature_config : Dict
        Full feature configuration from YAML

    Returns
    -------
    bool
        True if column is a dependency for any selected feature
    """
    behavioral_features = feature_config.get("behavioral_features", {})

    # Check if any selected behavioral feature depends on this column
    for feature_name in selected_features:
        if feature_name in behavioral_features:
            params = behavioral_features[feature_name].get("morpheus_params", {})
            input_name = params.get("input_name", "")
            if input_name == column:
                return True

    return False


def get_feature_columns(schema_file: str, feature_set: str = "default") -> list[str]:
    """
    Get list of feature column names for a given feature set.

    Parameters
    ----------
    schema_file : str
        Path to feature_schema.yaml file
    feature_set : str
        Which feature set to use (default: "default")

    Returns
    -------
    List[str]
        List of feature column names
    """
    with open(schema_file) as f:
        feature_config = yaml.safe_load(f)

    model_features = feature_config.get("model_features", {})
    return model_features.get(feature_set, [])


def get_excluded_columns(schema_file: str) -> list[str]:
    """
    Get list of columns to exclude from model training.

    These are identity, metadata, and intermediate columns that should
    not be used as model features.

    Parameters
    ----------
    schema_file : str
        Path to feature_schema.yaml file

    Returns
    -------
    List[str]
        List of column names to exclude
    """
    with open(schema_file) as f:
        feature_config = yaml.safe_load(f)

    return feature_config.get("excluded_fields", [])


def get_preprocessing_config(schema_file: str) -> dict[str, Any]:
    """
    Get preprocessing configuration from schema file.

    Parameters
    ----------
    schema_file : str
        Path to feature_schema.yaml file

    Returns
    -------
    Dict[str, Any]
        Preprocessing configuration including normalization, missing value handling, etc.
    """
    with open(schema_file) as f:
        feature_config = yaml.safe_load(f)

    return feature_config.get("preprocessing", {})
