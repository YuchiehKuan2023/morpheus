"""
Preprocessing Module for DFP Pipeline

This module contains preprocessing stages for the Digital Fingerprinting Pipeline,
following NVIDIA Morpheus DFP architecture.
"""

from modules.preprocessing.column_info import (
    ColumnInfo,
    DataFrameInputSchema,
    DateTimeColumn,
    DistinctIncrementColumn,
    IncrementColumn,
    process_dataframe,
)
from modules.preprocessing.data_prep import DataPrep, prepare_dataframe
from modules.preprocessing.dfp_preprocessing import DFPPreprocessing, create_preprocessing_stage
from modules.preprocessing.rolling_window import RollingWindow, process_user_windows
from modules.preprocessing.schema_builder import (
    build_preprocessing_schema_from_config,
    get_excluded_columns,
    get_feature_columns,
    get_preprocessing_config,
)
from modules.preprocessing.user_splitting import UserSplitter, split_dataframe_by_user

__all__ = [
    # Column transformations
    "ColumnInfo",
    "DateTimeColumn",
    "IncrementColumn",
    "DistinctIncrementColumn",
    "DataFrameInputSchema",
    "process_dataframe",
    # Schema builder
    "build_preprocessing_schema_from_config",
    "get_feature_columns",
    "get_excluded_columns",
    "get_preprocessing_config",
    # Main preprocessing
    "DFPPreprocessing",
    "create_preprocessing_stage",
    # User splitting
    "UserSplitter",
    "split_dataframe_by_user",
    # Rolling window
    "RollingWindow",
    "process_user_windows",
    # Data preparation
    "DataPrep",
    "prepare_dataframe",
]
