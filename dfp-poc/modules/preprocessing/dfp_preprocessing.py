"""
DFP Preprocessing Module

This module implements the Digital Fingerprinting preprocessing stage, which transforms
raw Azure AD log data into model-ready features following NVIDIA Morpheus DFP architecture.

Key Features:
- Temporal feature extraction (hour, day_of_week, is_weekend)
- Behavioral feature derivation (logcount, locincrement, appincrement)
- Categorical encoding (one-hot or label encoding)
- Missing value imputation
- Feature normalization

NVIDIA References:
    /nv-morpheus/python/morpheus_dfp/morpheus_dfp/stages/dfp_preprocessing.py
    /nv-morpheus/examples/digital_fingerprinting/production/dfp_azure_pipeline.py
"""

from __future__ import annotations

import logging

import pandas as pd

from modules.preprocessing.column_info import process_dataframe
from modules.preprocessing.geographic_features import (
    calculate_travel_features,
    detect_impossible_travel,
    get_travel_statistics,
)
from modules.preprocessing.schema_builder import (
    build_preprocessing_schema_from_config,
    get_excluded_columns,
    get_feature_columns,
    get_preprocessing_config,
)

logger = logging.getLogger(f"morpheus.{__name__}")


class DFPPreprocessing:
    """
    DFP Preprocessing Stage following NVIDIA Morpheus architecture.

    This class handles all feature engineering and data transformation required
    before model training/inference.

    Parameters
    ----------
    config : Dict
        Preprocessing configuration containing:
        - schema_file: Path to feature_schema.yaml
        - feature_set: Which feature set to use (default: "default")
        - cache_dir: Directory for caching preprocessing artifacts
        - fill_missing: Whether to fill missing values (default: True)
        - normalize: Whether to normalize numerical features (default: False, done in data_prep)

    Examples
    --------
    >>> config = {
    ...     "schema_file": "config/feature_schema.yaml",
    ...     "feature_set": "default",
    ...     "fill_missing": True
    ... }
    >>> preprocessor = DFPPreprocessing(config)
    >>> df_processed = preprocessor.preprocess(df_raw)

    Notes
    -----
    Processing pipeline:
    1. Schema-based column transformations (via process_dataframe)
    2. Temporal feature extraction
    3. Missing value handling
    4. Column ordering and validation
    """

    def __init__(self, config: dict):
        """
        Initialize DFP preprocessing with configuration.

        Parameters
        ----------
        config : Dict
            Configuration dictionary with preprocessing parameters
        """
        self.config = config
        self.schema_file = config.get("schema_file", "config/feature_schema.yaml")
        self.feature_set = config.get("feature_set", "default")
        self.fill_missing = config.get("fill_missing", True)
        self.normalize = config.get("normalize", False)

        # Load schema configuration
        self.preprocessing_config = get_preprocessing_config(self.schema_file)
        self.feature_columns = get_feature_columns(self.schema_file, self.feature_set)
        self.excluded_columns = get_excluded_columns(self.schema_file)

        # Build preprocessing schema (column transformations)
        self.schema = build_preprocessing_schema_from_config(
            schema_file=self.schema_file,
            feature_set=self.feature_set,
            preserve_columns=config.get("preserve_columns", ["_batch_id"]),
        )

        # Geographic features configuration (NVIDIA Grafana pattern)
        self.enable_geographic = config.get("enable_geographic_features", True)
        self.impossible_travel_threshold = config.get("impossible_travel_speed_kmph", 800)
        self.distance_threshold = config.get("distance_threshold_km", 500)

        logger.info(
            f"DFPPreprocessing initialized: "
            f"feature_set={self.feature_set}, "
            f"features={len(self.feature_columns)}, "
            f"fill_missing={self.fill_missing}, "
            f"geographic_features={self.enable_geographic}"
        )

        if self.enable_geographic:
            logger.debug(
                f"Geographic detection thresholds: "
                f"speed={self.impossible_travel_threshold}km/h, "
                f"distance={self.distance_threshold}km"
            )

    def preprocess(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Main preprocessing function that transforms raw data to model-ready features.

        This follows the NVIDIA Morpheus DFP preprocessing pipeline:
        1. Apply schema-based column transformations (via process_dataframe)
        2. Extract temporal features from timestamps
        3. Handle missing values
        4. Validate and order columns

        Parameters
        ----------
        df : pd.DataFrame
            Raw input DataFrame with Azure AD log data

        Returns
        -------
        pd.DataFrame
            Preprocessed DataFrame ready for model training/inference

        Raises
        ------
        ValueError
            If required columns are missing
        """
        logger.info(f"Starting preprocessing: {len(df)} rows, {len(df.columns)} columns")
        import sys

        sys.stdout.flush()

        # Validate input
        if df.empty:
            logger.warning("Empty DataFrame provided to preprocessing")
            return pd.DataFrame()

        # Step 1: Apply schema-based transformations
        # This handles: type conversions, behavioral features (logcount, locincrement, appincrement)
        # NVIDIA pattern: Only process_dataframe(), no custom feature extraction
        logger.info(
            f"[GEO_DEBUG] Before schema processing: {len(df.columns)} columns, has lat/lon: {'location_geoCoordinates_latitude' in df.columns}"
        )
        sys.stdout.flush()
        logger.info("[GEO_DEBUG] About to call process_dataframe()...")
        sys.stdout.flush()
        df_processed = process_dataframe(df, self.schema)
        logger.info("[GEO_DEBUG] process_dataframe() returned!")
        sys.stdout.flush()
        logger.info(
            f"[GEO_DEBUG] After schema processing: {len(df_processed.columns)} columns, has lat/lon: {'location_geoCoordinates_latitude' in df_processed.columns}"
        )
        sys.stdout.flush()
        logger.debug(f"After schema processing: {len(df_processed.columns)} columns")

        # Step 2: Calculate geographic features (NVIDIA Grafana pattern)
        # CRITICAL: Must happen AFTER schema processing (requires lat/lon columns)
        # CRITICAL: Must happen BEFORE missing value filling (preserves raw coordinates)
        logger.info(f"[GEO_DEBUG] enable_geographic={self.enable_geographic}")
        has_coords = self._has_geo_coordinates(df_processed)
        logger.info(f"[GEO_DEBUG] _has_geo_coordinates()={has_coords}")
        logger.info(f"[GEO_DEBUG] DataFrame shape before geographic: {df_processed.shape}")
        logger.info("[GEO_DEBUG] Last 3 rows coordinates:")
        if len(df_processed) >= 3:
            for idx in range(max(0, len(df_processed) - 3), len(df_processed)):
                row = df_processed.iloc[idx]
                logger.info(
                    f"[GEO_DEBUG]   Row {idx}: lat={row.get('location_geoCoordinates_latitude', 'MISSING')}, lon={row.get('location_geoCoordinates_longitude', 'MISSING')}"
                )

        if self.enable_geographic and has_coords:
            logger.debug("Calculating geographic travel features...")

            try:
                df_before_geo = df_processed.copy()  # Keep copy for comparison
                df_processed = calculate_travel_features(
                    df_processed,
                    user_col=self.preprocessing_config.get("userid_column", "username"),
                    timestamp_col=self.preprocessing_config.get("timestamp_column", "timestamp"),
                )

                df_processed = detect_impossible_travel(
                    df_processed,
                    speed_threshold=self.impossible_travel_threshold,
                    distance_threshold=self.distance_threshold,
                )

                # DEBUG: Check what was calculated
                logger.info("[GEO_DEBUG] After calculate_travel_features, last 3 rows:")
                if len(df_processed) >= 3:
                    last_3 = df_processed[
                        [
                            "location_geoCoordinates_latitude",
                            "location_geoCoordinates_longitude",
                            "distance_km",
                            "ts_delta_hour",
                            "travel_speed_kmph",
                        ]
                    ].tail(3)
                    for idx, row in last_3.iterrows():
                        logger.info(
                            f"[GEO_DEBUG]   Row {idx}: lat={row['location_geoCoordinates_latitude']:.4f}, lon={row['location_geoCoordinates_longitude']:.4f}, "
                            f"dist={row['distance_km']:.2f}km, time={row['ts_delta_hour']:.2f}h, speed={row['travel_speed_kmph']:.2f}km/h"
                        )

                # DEBUG: Compare before and after
                logger.info("[GEO_DEBUG] Comparing geographic features before and after calculation:")
                logger.info(
                    f"[GEO_DEBUG]   distance_km changed: {not df_before_geo['distance_km'].equals(df_processed['distance_km']) if 'distance_km' in df_before_geo.columns else 'new column'}"
                )
                logger.info(f"[GEO_DEBUG]   NaN count - distance_km: {df_processed['distance_km'].isna().sum()}")
                logger.info(
                    f"[GEO_DEBUG]   NaN count - travel_speed_kmph: {df_processed['travel_speed_kmph'].isna().sum()}"
                )

                # Log statistics for monitoring
                stats = get_travel_statistics(df_processed)
                logger.info(
                    f"Geographic features calculated: "
                    f"mean_speed={stats['mean_speed']:.1f}km/h, "
                    f"max_speed={stats['max_speed']:.1f}km/h, "
                    f"impossible_rate={stats['impossible_rate']:.2f}%"
                )

                # Alert on impossible travel detection
                if stats["impossible_rate"] > 0:
                    logger.warning(
                        f"⚠️  SECURITY ALERT: {stats['impossible_rate']:.2f}% of events "
                        f"flagged as impossible travel (speed > {self.impossible_travel_threshold} km/h)"
                    )

            except Exception as e:
                logger.error(f"Failed to calculate geographic features: {e}", exc_info=True)
                logger.warning("Continuing without geographic features (graceful degradation)")
                # Add default columns to maintain schema consistency
                df_processed["distance_km"] = 0.0
                df_processed["ts_delta_hour"] = 0.0
                df_processed["travel_speed_kmph"] = 0.0
                df_processed["impossible_travel"] = False
        else:
            if not self.enable_geographic:
                logger.debug("Geographic features disabled in configuration")
            else:
                logger.warning(
                    "Geographic coordinates not found in data. "
                    "Skipping travel feature calculation. "
                    "Ensure location_geoCoordinates_latitude and _longitude columns exist."
                )
                # Add default columns to maintain schema consistency
                df_processed["distance_km"] = 0.0
                df_processed["ts_delta_hour"] = 0.0
                df_processed["travel_speed_kmph"] = 0.0
                df_processed["impossible_travel"] = False

        # Step 3: Handle missing values
        if self.fill_missing:
            df_processed = self._fill_missing_values(df_processed)
            logger.debug("Missing values filled")

        # Step 4: Validate output columns
        df_processed = self._validate_and_order_columns(df_processed)

        logger.info(f"Preprocessing complete: {len(df_processed)} rows, {len(df_processed.columns)} columns")

        return df_processed

    def _fill_missing_values(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Fill missing values according to preprocessing configuration.

        Strategy:
        - Numerical columns: Fill with configured value (typically 0 or median)
        - Categorical columns: Fill with configured value (typically "unknown")
        - Boolean columns: Fill with False
        - Timestamp columns: Forward fill (use previous value)

        Parameters
        ----------
        df : pd.DataFrame
            DataFrame possibly containing missing values

        Returns
        -------
        pd.DataFrame
            DataFrame with missing values filled
        """
        missing_config = self.preprocessing_config.get("missing_values", {})
        strategy = missing_config.get("strategy", "fill")

        if strategy == "drop":
            # Drop rows with any missing values (not recommended for DFP)
            original_len = len(df)
            df = df.dropna()
            dropped = original_len - len(df)
            if dropped > 0:
                logger.warning(f"Dropped {dropped} rows with missing values")
            return df

        # Fill strategy
        numerical_fill = missing_config.get("numerical_fill", 0)
        categorical_fill = missing_config.get("categorical_fill", "unknown")

        for col in df.columns:
            if df[col].isna().any():
                # Determine column type and fill accordingly
                if pd.api.types.is_numeric_dtype(df[col]):
                    # Numerical column
                    df[col] = df[col].fillna(numerical_fill)
                    logger.debug(f"Filled {col} (numerical) with {numerical_fill}")

                elif pd.api.types.is_bool_dtype(df[col]):
                    # Boolean column
                    df[col] = df[col].fillna(False)
                    logger.debug(f"Filled {col} (boolean) with False")

                elif pd.api.types.is_datetime64_any_dtype(df[col]):
                    # Timestamp column - forward fill
                    df[col] = df[col].ffill()
                    # If still NaN at start, use backward fill
                    df[col] = df[col].bfill()
                    logger.debug(f"Filled {col} (datetime) with forward/backward fill")

                else:
                    # Categorical/string column
                    df[col] = df[col].fillna(categorical_fill)
                    logger.debug(f"Filled {col} (categorical) with '{categorical_fill}'")

        return df

    def _validate_and_order_columns(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Validate that all required columns are present and order them consistently.

        This ensures:
        1. All feature columns from schema are present
        2. Columns are in consistent order
        3. Excluded columns (username, timestamp) are removed if not needed for next stage

        Parameters
        ----------
        df : pd.DataFrame
            Preprocessed DataFrame

        Returns
        -------
        pd.DataFrame
            DataFrame with validated and ordered columns
        """
        # Check for missing feature columns
        missing_cols = set(self.feature_columns) - set(df.columns)
        if missing_cols:
            logger.warning(
                f"Missing expected feature columns: {missing_cols}. These will be created with default values."
            )
            # Create missing columns with default values
            for col in missing_cols:
                df[col] = 0  # Default to 0 for missing features

        # Get final column order: feature columns + preserved columns
        preserved_cols = [col for col in df.columns if col.startswith("_")]

        # Order columns: preserved columns first, then feature columns
        ordered_cols = preserved_cols + [col for col in self.feature_columns if col in df.columns]

        # Add any extra columns that aren't in feature_columns or preserved
        extra_cols = [col for col in df.columns if col not in ordered_cols]
        if extra_cols:
            logger.debug(f"Extra columns found (will be included): {extra_cols}")
            ordered_cols.extend(extra_cols)

        df = df[ordered_cols]

        logger.debug(
            f"Final column order: {len(ordered_cols)} columns "
            f"({len(preserved_cols)} preserved + {len(self.feature_columns)} features)"
        )

        return df

    def _has_geo_coordinates(self, df: pd.DataFrame) -> bool:
        """
        Check if DataFrame has required geographic columns for travel calculation.

        Required columns for geographic feature calculation:
        - location_geoCoordinates_latitude
        - location_geoCoordinates_longitude
        - timestamp (for time delta calculation)

        Parameters
        ----------
        df : pd.DataFrame
            DataFrame to check for geographic columns

        Returns
        -------
        bool
            True if all required geographic columns exist and have non-null values,
            False otherwise

        Notes
        -----
        This method also validates that columns contain actual data (not all nulls).
        If columns exist but are empty, returns False to prevent unnecessary processing.
        """
        required = ["location_geoCoordinates_latitude", "location_geoCoordinates_longitude", "timestamp"]

        # Check if columns exist
        has_coords = all(col in df.columns for col in required)

        if not has_coords:
            missing = [col for col in required if col not in df.columns]
            logger.debug(f"[GEO_CHECK] Geographic columns missing: {missing}")
            return False

        # DEBUG: Check data types
        logger.debug(
            f"[GEO_CHECK] Column dtypes: lat={df['location_geoCoordinates_latitude'].dtype}, lon={df['location_geoCoordinates_longitude'].dtype}"
        )

        # Verify columns have non-null values
        lat_non_null = df["location_geoCoordinates_latitude"].notna().sum()
        lon_non_null = df["location_geoCoordinates_longitude"].notna().sum()
        both_non_null = (
            df["location_geoCoordinates_latitude"].notna() & df["location_geoCoordinates_longitude"].notna()
        ).sum()

        logger.debug(
            f"[GEO_CHECK] Non-null counts: lat={lat_non_null}, lon={lon_non_null}, both={both_non_null}/{len(df)}"
        )

        non_null_count = df[required].notna().all(axis=1).sum()
        if non_null_count == 0:
            logger.warning(
                "[GEO_CHECK] Geographic columns exist but all values are null. Cannot calculate travel features."
            )
            return False

        logger.debug(f"Geographic columns validated: {non_null_count}/{len(df)} rows have complete coordinate data")
        return True

    def get_feature_names(self) -> list[str]:
        """
        Get list of feature column names that will be output.

        Returns
        -------
        List[str]
            List of feature column names
        """
        return self.feature_columns.copy()

    def get_excluded_columns(self) -> list[str]:
        """
        Get list of columns that should be excluded from model training.

        These are identity and metadata columns that should not be used as features.

        Returns
        -------
        List[str]
            List of excluded column names
        """
        return self.excluded_columns.copy()


def create_preprocessing_stage(config: dict) -> DFPPreprocessing:
    """
    Factory function to create a DFP preprocessing stage.

    Parameters
    ----------
    config : Dict
        Configuration dictionary

    Returns
    -------
    DFPPreprocessing
        Configured preprocessing stage

    Examples
    --------
    >>> config = {"schema_file": "config/feature_schema.yaml"}
    >>> stage = create_preprocessing_stage(config)
    >>> df_out = stage.preprocess(df_in)
    """
    return DFPPreprocessing(config)
