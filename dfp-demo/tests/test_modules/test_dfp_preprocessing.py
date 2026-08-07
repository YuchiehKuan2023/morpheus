"""
Unit Tests for DFP Preprocessing Module

Tests the DFPPreprocessing class and related preprocessing functionality.
"""

from datetime import datetime

import pandas as pd
import pytest
import yaml

from modules.preprocessing import DFPPreprocessing, build_preprocessing_schema_from_config, get_feature_columns


@pytest.fixture
def sample_schema_file(tmp_path):
    """Create a temporary feature schema YAML file for testing."""
    schema_content = {
        "version": "1.0",
        "description": "Test feature schema",
        "model_features": {
            "default": [
                "timestamp",
                "username",
                "appDisplayName",
                "location",
                "logcount",
                "locincrement",
                "appincrement",
                "hour",
                "dayofweek",
                "is_weekend",
            ],
            "minimal": ["timestamp", "username", "logcount"],
        },
        "categorical_features": {
            "appDisplayName": {"enabled": True, "dtype": "string"},
            "location": {"enabled": True, "dtype": "string"},
        },
        "behavioral_features": {
            "logcount": {
                "description": "Cumulative event count per user",
                "morpheus_params": {
                    "input_name": "timestamp",
                    "groupby_column": "username",
                },
            },
            "locincrement": {
                "description": "Distinct location count per user",
                "morpheus_params": {
                    "input_name": "location",
                    "groupby_column": "username",
                    "timestamp_column": "timestamp",
                },
            },
            "appincrement": {
                "description": "Distinct app count per user",
                "morpheus_params": {
                    "input_name": "appDisplayName",
                    "groupby_column": "username",
                    "timestamp_column": "timestamp",
                },
            },
        },
        "excluded_fields": ["username", "timestamp"],
        "preprocessing": {
            "missing_values": {
                "strategy": "fill",
                "numerical_fill": 0,
                "categorical_fill": "unknown",
            }
        },
    }

    schema_file = tmp_path / "test_schema.yaml"
    with open(schema_file, "w") as f:
        yaml.dump(schema_content, f)

    return str(schema_file)


@pytest.fixture
def sample_raw_data():
    """Create sample raw Azure AD log data."""
    # Create data with proper datetime (not string) timestamps
    timestamps = pd.to_datetime(
        [
            "2024-01-01 10:00:00",
            "2024-01-01 11:30:00",
            "2024-01-01 14:15:00",
            "2024-01-01 10:30:00",
            "2024-01-01 15:00:00",
        ],
        utc=True,
    )

    data = {
        "timestamp": timestamps,
        "username": ["user1@company.co.uk"] * 3 + ["user2@company.co.uk"] * 2,
        "appDisplayName": ["Office 365", "Azure Portal", "Office 365", "Teams", "Office 365"],
        "location": ["London", "London", "Manchester", "London", "London"],
    }
    return pd.DataFrame(data)


class TestColumnInfo:
    """Test column_info classes"""

    def test_column_info_basic(self, sample_raw_data):
        """Test basic ColumnInfo transformation"""
        from modules.preprocessing.column_info import ColumnInfo

        col = ColumnInfo(name="username", dtype=str)
        result = col.process_column(sample_raw_data)

        assert result.name == "username"
        assert len(result) == 5
        assert result.dtype == object  # str maps to object in pandas

    def test_datetime_column(self, sample_raw_data):
        """Test DateTimeColumn transformation"""
        from modules.preprocessing.column_info import DateTimeColumn

        col = DateTimeColumn(name="timestamp", dtype=datetime, input_name="timestamp")
        result = col.process_column(sample_raw_data)

        assert result.name == "timestamp"
        assert pd.api.types.is_datetime64_any_dtype(result)
        # Check if timezone-aware by verifying result is datetime64[ns, UTC]
        assert str(result.dtype).startswith("datetime64[ns,") or result.iloc[0].tzinfo is not None

    def test_increment_column(self, sample_raw_data):
        """Test IncrementColumn (logcount) transformation"""
        from modules.preprocessing.column_info import IncrementColumn

        # IncrementColumn requires datetime column, convert first
        df = sample_raw_data.copy()
        df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)

        col = IncrementColumn(name="logcount", dtype=int, input_name="timestamp", groupby_column="username")
        result = col.process_column(df)

        assert result.name == "logcount"
        # Counts are 0-indexed (NVIDIA algorithm uses cumcount)
        # user1 should have counts 0, 1, 2
        assert result.iloc[0] == 0
        assert result.iloc[1] == 1
        assert result.iloc[2] == 2
        # user2 should have counts 0, 1
        assert result.iloc[3] == 0
        assert result.iloc[4] == 1

    def test_distinct_increment_column(self, sample_raw_data):
        """Test DistinctIncrementColumn (locincrement) transformation"""
        from modules.preprocessing.column_info import DistinctIncrementColumn

        # Parse timestamps first
        df = sample_raw_data.copy()
        df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)

        col = DistinctIncrementColumn(
            name="locincrement",
            dtype=int,
            input_name="location",
            groupby_column="username",
            timestamp_column="timestamp",
        )
        result = col.process_column(df)

        assert result.name == "locincrement"
        # user1: London(1), London(1), Manchester(2)
        assert result.iloc[0] == 1
        assert result.iloc[1] == 1
        assert result.iloc[2] == 2
        # user2: London(1), London(1)
        assert result.iloc[3] == 1
        assert result.iloc[4] == 1


class TestSchemaBuilder:
    """Test schema builder functions"""

    def test_build_schema_default(self, sample_schema_file):
        """Test building schema with default feature set"""
        schema = build_preprocessing_schema_from_config(sample_schema_file, feature_set="default")

        assert schema is not None
        assert len(schema.column_info) > 0

        # Check that key transformations are included
        column_names = [col.name for col in schema.column_info]
        assert "timestamp" in column_names
        assert "username" in column_names
        assert "logcount" in column_names

    def test_build_schema_minimal(self, sample_schema_file):
        """Test building schema with minimal feature set"""
        schema = build_preprocessing_schema_from_config(sample_schema_file, feature_set="minimal")

        column_names = [col.name for col in schema.column_info]
        assert "logcount" in column_names
        # Minimal set should have fewer columns than default
        assert len(column_names) <= 5

    def test_get_feature_columns(self, sample_schema_file):
        """Test getting feature column list"""
        features = get_feature_columns(sample_schema_file, "default")

        assert isinstance(features, list)
        assert len(features) > 0
        assert "logcount" in features
        assert "timestamp" in features


class TestDFPPreprocessing:
    """Test main DFPPreprocessing class"""

    def test_initialization(self, sample_schema_file):
        """Test DFPPreprocessing initialization"""
        config = {
            "schema_file": sample_schema_file,
            "feature_set": "default",
            "fill_missing": True,
        }

        preprocessor = DFPPreprocessing(config)

        assert preprocessor.schema_file == sample_schema_file
        assert preprocessor.feature_set == "default"
        assert preprocessor.fill_missing is True
        assert len(preprocessor.feature_columns) > 0

    def test_preprocess_basic(self, sample_schema_file, sample_raw_data):
        """Test basic preprocessing pipeline"""
        config = {
            "schema_file": sample_schema_file,
            "feature_set": "default",
            "fill_missing": True,
        }

        preprocessor = DFPPreprocessing(config)
        df_processed = preprocessor.preprocess(sample_raw_data)

        assert len(df_processed) == len(sample_raw_data)
        assert len(df_processed.columns) > 0

        # Check that behavioral features are created
        assert "logcount" in df_processed.columns
        assert "locincrement" in df_processed.columns
        assert "appincrement" in df_processed.columns

    def test_temporal_features_extraction(self, sample_schema_file, sample_raw_data):
        """Test temporal feature extraction"""
        config = {
            "schema_file": sample_schema_file,
            "feature_set": "default",
        }

        preprocessor = DFPPreprocessing(config)
        df_processed = preprocessor.preprocess(sample_raw_data)

        # Check temporal features
        if "hour" in preprocessor.feature_columns:
            assert "hour" in df_processed.columns
            assert df_processed["hour"].min() >= 0
            assert df_processed["hour"].max() <= 23

        if "dayofweek" in preprocessor.feature_columns:
            assert "dayofweek" in df_processed.columns
            assert df_processed["dayofweek"].min() >= 0
            assert df_processed["dayofweek"].max() <= 6

        if "is_weekend" in preprocessor.feature_columns:
            assert "is_weekend" in df_processed.columns
            assert df_processed["is_weekend"].dtype == bool

    def test_logcount_values(self, sample_schema_file, sample_raw_data):
        """Test logcount feature calculation"""
        config = {
            "schema_file": sample_schema_file,
            "feature_set": "default",
        }

        preprocessor = DFPPreprocessing(config)
        df_processed = preprocessor.preprocess(sample_raw_data)

        # Check logcount values
        user1_mask = sample_raw_data["username"] == "user1@company.co.uk"
        user1_rows = df_processed[user1_mask]

        # Should be sequential: 0, 1, 2 (NVIDIA algorithm uses 0-indexed cumcount)
        assert user1_rows["logcount"].iloc[0] == 0
        assert user1_rows["logcount"].iloc[1] == 1
        assert user1_rows["logcount"].iloc[2] == 2

    def test_locincrement_values(self, sample_schema_file, sample_raw_data):
        """Test locincrement feature calculation"""
        config = {
            "schema_file": sample_schema_file,
            "feature_set": "default",
        }

        preprocessor = DFPPreprocessing(config)
        df_processed = preprocessor.preprocess(sample_raw_data)

        # Check locincrement values
        user1_mask = sample_raw_data["username"] == "user1@company.co.uk"
        user1_rows = df_processed[user1_mask]

        # user1: London, London, Manchester -> 1, 1, 2
        assert user1_rows["locincrement"].iloc[0] == 1  # First London
        assert user1_rows["locincrement"].iloc[1] == 1  # Still London
        assert user1_rows["locincrement"].iloc[2] == 2  # New city: Manchester

    def test_appincrement_values(self, sample_schema_file, sample_raw_data):
        """Test appincrement feature calculation"""
        config = {
            "schema_file": sample_schema_file,
            "feature_set": "default",
        }

        preprocessor = DFPPreprocessing(config)
        df_processed = preprocessor.preprocess(sample_raw_data)

        # Check appincrement values
        user1_mask = sample_raw_data["username"] == "user1@company.co.uk"
        user1_rows = df_processed[user1_mask]

        # user1: Office 365, Azure Portal, Office 365 -> 1, 2, 2
        assert user1_rows["appincrement"].iloc[0] == 1  # First app: Office 365
        assert user1_rows["appincrement"].iloc[1] == 2  # New app: Azure Portal
        assert user1_rows["appincrement"].iloc[2] == 2  # Still 2 distinct apps

    def test_missing_value_handling(self, sample_schema_file):
        """Test missing value filling"""
        import numpy as np

        # Use datetime timestamps (not strings with NaN) to avoid parsing errors
        data_with_nans = pd.DataFrame(
            {
                "timestamp": pd.to_datetime(
                    ["2024-01-01 10:00:00", "2024-01-01 11:00:00", "2024-01-01 12:00:00"], utc=True
                ),
                "username": ["user1@company.co.uk", "user2@company.co.uk", "user3@company.co.uk"],
                "appDisplayName": ["Office 365", np.nan, "Teams"],
                "location": ["London", "Manchester", "London"],
            }
        )

        config = {
            "schema_file": sample_schema_file,
            "feature_set": "default",
            "fill_missing": True,
        }

        preprocessor = DFPPreprocessing(config)
        df_processed = preprocessor.preprocess(data_with_nans)

        # Check that NaNs were filled
        assert not df_processed["appDisplayName"].isna().any()
        assert df_processed["appDisplayName"].iloc[1] == "unknown"

    def test_empty_dataframe(self, sample_schema_file):
        """Test preprocessing with empty DataFrame"""
        empty_df = pd.DataFrame()

        config = {
            "schema_file": sample_schema_file,
            "feature_set": "default",
        }

        preprocessor = DFPPreprocessing(config)
        df_processed = preprocessor.preprocess(empty_df)

        assert df_processed.empty

    def test_get_feature_names(self, sample_schema_file):
        """Test getting feature names"""
        config = {
            "schema_file": sample_schema_file,
            "feature_set": "default",
        }

        preprocessor = DFPPreprocessing(config)
        feature_names = preprocessor.get_feature_names()

        assert isinstance(feature_names, list)
        assert len(feature_names) > 0
        assert "logcount" in feature_names

    def test_get_excluded_columns(self, sample_schema_file):
        """Test getting excluded columns"""
        config = {
            "schema_file": sample_schema_file,
            "feature_set": "default",
        }

        preprocessor = DFPPreprocessing(config)
        excluded = preprocessor.get_excluded_columns()

        assert isinstance(excluded, list)
        assert "username" in excluded
        assert "timestamp" in excluded
