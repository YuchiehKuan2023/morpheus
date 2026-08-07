"""
Comprehensive tests for Data Preparation module.

Tests cover:
1. Initialization and configuration
2. Feature selection logic
3. Input validation
4. Edge cases
5. Integration with real data

Author: DFP PoC Tests
Date: 2025-11-10
"""

import numpy as np
import pandas as pd
import pytest

from modules.preprocessing.data_prep import DataPrep, prepare_dataframe

# =============================================================================
# Test Fixtures
# =============================================================================


@pytest.fixture
def sample_dataframe():
    """Create sample DataFrame with mixed column types."""
    return pd.DataFrame(
        {
            "username": ["user1"] * 10,
            "timestamp": pd.date_range("2024-01-01", periods=10, freq="h"),
            "batch_id": [1] * 10,
            "_row_hash": range(10),
            "logcount": range(10),
            "locincrement": range(1, 11),
            "appincrement": range(2, 12),
            "hour": [0, 1, 2, 3, 4, 5, 6, 7, 8, 9],
            "dayofweek": [0] * 10,
        }
    )


@pytest.fixture
def basic_config():
    """Basic configuration for DataPrep."""
    return {
        "feature_columns": ["logcount", "locincrement", "appincrement", "hour", "dayofweek"],
        "timestamp_column": "timestamp",
        "userid_column": "username",
    }


# =============================================================================
# Test Class 1: Initialization
# =============================================================================


class TestDataPrepInitialization:
    """Test DataPrep initialization and configuration."""

    def test_initialization_with_full_config(self, basic_config):
        """Test initialization with complete configuration."""
        data_prep = DataPrep(basic_config)

        assert data_prep.feature_columns == basic_config["feature_columns"]
        assert data_prep.timestamp_column == "timestamp"
        assert data_prep.userid_column == "username"
        assert "username" in data_prep.exclude_columns
        assert "timestamp" in data_prep.exclude_columns
        assert "batch_id" in data_prep.exclude_columns
        assert "_row_hash" in data_prep.exclude_columns

    def test_initialization_with_defaults(self):
        """Test initialization with default values."""
        config = {"feature_columns": ["feat1", "feat2"]}
        data_prep = DataPrep(config)

        assert data_prep.timestamp_column == "timestamp"
        assert data_prep.userid_column == "username"
        assert len(data_prep.exclude_columns) >= 4  # At least base excludes

    def test_initialization_with_additional_excludes(self):
        """Test initialization with additional exclude columns."""
        config = {"feature_columns": ["feat1"], "exclude_columns": ["custom_col1", "custom_col2"]}
        data_prep = DataPrep(config)

        assert "custom_col1" in data_prep.exclude_columns
        assert "custom_col2" in data_prep.exclude_columns


# =============================================================================
# Test Class 2: Feature Selection
# =============================================================================


class TestFeatureSelection:
    """Test feature selection logic."""

    def test_select_specified_features(self, sample_dataframe, basic_config):
        """Test selecting specified feature columns."""
        data_prep = DataPrep(basic_config)
        df_prepared = data_prep.prepare(sample_dataframe)

        assert list(df_prepared.columns) == basic_config["feature_columns"]
        assert len(df_prepared) == len(sample_dataframe)

    def test_select_features_without_specification(self, sample_dataframe):
        """Test selecting all columns when no features specified."""
        config = {"timestamp_column": "timestamp", "userid_column": "username"}
        data_prep = DataPrep(config)
        df_prepared = data_prep.prepare(sample_dataframe)

        # Should include all columns except excluded ones
        assert "username" not in df_prepared.columns
        assert "timestamp" not in df_prepared.columns
        assert "batch_id" not in df_prepared.columns
        assert "_row_hash" not in df_prepared.columns
        assert "logcount" in df_prepared.columns
        assert "locincrement" in df_prepared.columns

    def test_feature_order_preservation(self, sample_dataframe):
        """Test that feature column order is preserved."""
        config = {
            "feature_columns": ["hour", "dayofweek", "logcount"],  # Specific order
            "timestamp_column": "timestamp",
            "userid_column": "username",
        }
        data_prep = DataPrep(config)
        df_prepared = data_prep.prepare(sample_dataframe)

        assert list(df_prepared.columns) == ["hour", "dayofweek", "logcount"]

    def test_partial_feature_availability(self, sample_dataframe, caplog):
        """Test selecting features when some are not available."""
        config = {
            "feature_columns": ["logcount", "missing_feature", "hour"],
            "timestamp_column": "timestamp",
            "userid_column": "username",
        }
        data_prep = DataPrep(config)

        with caplog.at_level("WARNING"):
            df_prepared = data_prep.prepare(sample_dataframe)

        # Should only include available features
        assert "logcount" in df_prepared.columns
        assert "hour" in df_prepared.columns
        assert "missing_feature" not in df_prepared.columns

        # Should log warning about missing feature
        assert "missing_feature" in caplog.text


# =============================================================================
# Test Class 3: Input Validation
# =============================================================================


class TestValidation:
    """Test input validation and error handling."""

    def test_none_dataframe_raises_error(self, basic_config):
        """Test that None DataFrame raises ValueError."""
        data_prep = DataPrep(basic_config)

        with pytest.raises(ValueError, match="cannot be None or empty"):
            data_prep.prepare(None)  # type: ignore[arg-type]

    def test_empty_dataframe_raises_error(self, basic_config):
        """Test that empty DataFrame raises ValueError."""
        data_prep = DataPrep(basic_config)
        empty_df = pd.DataFrame()

        with pytest.raises(ValueError, match="cannot be None or empty"):
            data_prep.prepare(empty_df)

    def test_no_features_selected_raises_error(self):
        """Test error when no features can be selected."""
        config = {
            "feature_columns": ["missing1", "missing2"],
            "timestamp_column": "timestamp",
            "userid_column": "username",
        }
        data_prep = DataPrep(config)

        df = pd.DataFrame({"username": ["user1"], "timestamp": [pd.Timestamp("2024-01-01")], "other_col": [1]})

        with pytest.raises(ValueError, match="No features selected"):
            data_prep.prepare(df)


# =============================================================================
# Test Class 4: Edge Cases
# =============================================================================


class TestEdgeCases:
    """Test edge cases and boundary conditions."""

    def test_single_row_dataframe(self, basic_config):
        """Test processing DataFrame with single row."""
        df = pd.DataFrame(
            {
                "username": ["user1"],
                "timestamp": [pd.Timestamp("2024-01-01")],
                "logcount": [5],
                "locincrement": [2],
                "appincrement": [3],
                "hour": [10],
                "dayofweek": [1],
            }
        )

        data_prep = DataPrep(basic_config)
        df_prepared = data_prep.prepare(df)

        assert len(df_prepared) == 1
        assert list(df_prepared.columns) == basic_config["feature_columns"]

    def test_duplicate_column_names_in_config(self):
        """Test handling duplicate feature names in config."""
        config = {
            "feature_columns": ["feat1", "feat2", "feat1"],  # Duplicate
            "timestamp_column": "timestamp",
            "userid_column": "username",
        }

        df = pd.DataFrame(
            {"username": ["user1"], "timestamp": [pd.Timestamp("2024-01-01")], "feat1": [1], "feat2": [2]}
        )

        data_prep = DataPrep(config)
        df_prepared = data_prep.prepare(df)

        # Should handle duplicates gracefully
        assert "feat1" in df_prepared.columns
        assert "feat2" in df_prepared.columns

    def test_all_columns_excluded(self):
        """Test when all columns would be excluded."""
        config = {
            "feature_columns": ["username", "timestamp"],  # Both in exclude list
            "timestamp_column": "timestamp",
            "userid_column": "username",
        }

        df = pd.DataFrame({"username": ["user1"], "timestamp": [pd.Timestamp("2024-01-01")]})

        data_prep = DataPrep(config)

        with pytest.raises(ValueError, match="No features selected"):
            data_prep.prepare(df)

    def test_large_dataframe(self, basic_config):
        """Test processing large DataFrame."""
        # Create large DataFrame (1000 rows)
        df = pd.DataFrame(
            {
                "username": ["user1"] * 1000,
                "timestamp": pd.date_range("2024-01-01", periods=1000, freq="h"),
                "logcount": range(1000),
                "locincrement": range(1, 1001),
                "appincrement": range(2, 1002),
                "hour": [i % 24 for i in range(1000)],
                "dayofweek": [i % 7 for i in range(1000)],
            }
        )

        data_prep = DataPrep(basic_config)
        df_prepared = data_prep.prepare(df)

        assert len(df_prepared) == 1000
        assert list(df_prepared.columns) == basic_config["feature_columns"]

    def test_unicode_column_names(self):
        """Test handling Unicode characters in column names."""
        config = {
            "feature_columns": ["特徴1", "特徴2", "особенность"],
            "timestamp_column": "timestamp",
            "userid_column": "username",
        }

        df = pd.DataFrame(
            {
                "username": ["user1"],
                "timestamp": [pd.Timestamp("2024-01-01")],
                "特徴1": [1],
                "特徴2": [2],
                "особенность": [3],
            }
        )

        data_prep = DataPrep(config)
        df_prepared = data_prep.prepare(df)

        assert len(df_prepared.columns) == 3
        assert "特徴1" in df_prepared.columns


# =============================================================================
# Test Class 5: Integration with Real Data
# =============================================================================


class TestWithRealData:
    """Test with realistic DFP data."""

    def test_typical_dfp_features(self):
        """Test with typical DFP feature set."""
        config = {
            "feature_columns": [
                "logcount",
                "locincrement",
                "appincrement",
                "new_city_counter",
                "new_country_counter",
                "hour",
                "dayofweek",
                "day",
                "month",
            ],
            "timestamp_column": "timestamp",
            "userid_column": "username",
        }

        # Create realistic DFP data
        df = pd.DataFrame(
            {
                "username": ["alice"] * 50,
                "timestamp": pd.date_range("2024-01-01", periods=50, freq="h"),
                "batch_id": [1] * 50,
                "logcount": range(50),
                "locincrement": [1, 1, 2, 2, 3, 3] * 8 + [1, 1],
                "appincrement": [1, 2, 3, 4, 5] * 10,
                "new_city_counter": [0] * 10 + [1] * 20 + [2] * 20,
                "new_country_counter": [0] * 25 + [1] * 25,
                "hour": [i % 24 for i in range(50)],
                "dayofweek": [i % 7 for i in range(50)],
                "day": [1] * 50,
                "month": [1] * 50,
            }
        )

        data_prep = DataPrep(config)
        df_prepared = data_prep.prepare(df)

        assert len(df_prepared) == 50
        assert len(df_prepared.columns) == 9
        assert "username" not in df_prepared.columns
        assert "timestamp" not in df_prepared.columns

    def test_mixed_data_types(self):
        """Test with mixed data types (int, float, bool)."""
        config = {
            "feature_columns": ["int_feat", "float_feat", "bool_feat"],
            "timestamp_column": "timestamp",
            "userid_column": "username",
        }

        df = pd.DataFrame(
            {
                "username": ["user1"] * 10,
                "timestamp": pd.date_range("2024-01-01", periods=10, freq="h"),
                "int_feat": range(10),
                "float_feat": np.random.randn(10),
                "bool_feat": [True, False] * 5,
            }
        )

        data_prep = DataPrep(config)
        df_prepared = data_prep.prepare(df)

        assert len(df_prepared) == 10
        assert df_prepared["int_feat"].dtype == np.int64 or df_prepared["int_feat"].dtype == np.int32
        assert df_prepared["float_feat"].dtype == np.float64
        assert df_prepared["bool_feat"].dtype == bool


# =============================================================================
# Test Class 6: Convenience Function
# =============================================================================


class TestPrepareDataFrame:
    """Test the prepare_dataframe convenience function."""

    def test_convenience_function_basic(self, sample_dataframe):
        """Test basic usage of convenience function."""
        df_prepared = prepare_dataframe(
            sample_dataframe,
            feature_columns=["logcount", "locincrement", "hour"],
            timestamp_column="timestamp",
            userid_column="username",
        )

        assert list(df_prepared.columns) == ["logcount", "locincrement", "hour"]
        assert len(df_prepared) == len(sample_dataframe)

    def test_convenience_function_defaults(self, sample_dataframe):
        """Test convenience function with default parameters."""
        df_prepared = prepare_dataframe(sample_dataframe)

        # Should exclude default columns
        assert "username" not in df_prepared.columns
        assert "timestamp" not in df_prepared.columns
        assert "batch_id" not in df_prepared.columns


# =============================================================================
# Test Class 7: Getter Methods
# =============================================================================


class TestGetterMethods:
    """Test getter methods for configuration access."""

    def test_get_feature_columns(self, basic_config):
        """Test get_feature_columns method."""
        data_prep = DataPrep(basic_config)
        features = data_prep.get_feature_columns()

        assert features == basic_config["feature_columns"]
        # Verify it returns a copy
        features.append("new_feature")
        assert "new_feature" not in data_prep.get_feature_columns()

    def test_get_exclude_columns(self, basic_config):
        """Test get_exclude_columns method."""
        data_prep = DataPrep(basic_config)
        excludes = data_prep.get_exclude_columns()

        assert "username" in excludes
        assert "timestamp" in excludes
        # Verify it returns a copy
        excludes.append("new_exclude")
        assert "new_exclude" not in data_prep.get_exclude_columns()


# =============================================================================
# Test Class 8: Integration Scenarios
# =============================================================================


class TestIntegrationScenarios:
    """Test realistic integration scenarios."""

    def test_pipeline_flow(self):
        """Test full pipeline flow: preprocess -> split -> window -> data_prep."""
        # Simulate data after rolling window stage
        windowed_data = pd.DataFrame(
            {
                "username": ["alice"] * 100,
                "timestamp": pd.date_range("2024-01-01", periods=100, freq="h"),
                "_row_hash": range(100),
                "batch_id": [1] * 100,
                "logcount": range(100),
                "locincrement": [1, 2, 3] * 33 + [1],
                "appincrement": [1, 2] * 50,
                "hour": [i % 24 for i in range(100)],
                "dayofweek": [i % 7 for i in range(100)],
                "day": [1] * 100,
                "month": [1] * 100,
            }
        )

        config = {
            "feature_columns": ["logcount", "locincrement", "appincrement", "hour", "dayofweek", "day", "month"],
            "timestamp_column": "timestamp",
            "userid_column": "username",
        }

        data_prep = DataPrep(config)
        df_prepared = data_prep.prepare(windowed_data)

        # Verify prepared for training
        assert len(df_prepared) == 100
        assert len(df_prepared.columns) == 7
        assert "username" not in df_prepared.columns
        assert "timestamp" not in df_prepared.columns
        assert "_row_hash" not in df_prepared.columns

        # Verify data types suitable for training
        for col in df_prepared.columns:
            assert df_prepared[col].dtype in [np.int64, np.int32, np.float64, np.float32]

    def test_multiple_users_preparation(self):
        """Test preparing data for multiple users."""
        users = ["alice", "bob", "charlie"]
        user_dfs = {}

        config = {
            "feature_columns": ["logcount", "locincrement", "hour"],
            "timestamp_column": "timestamp",
            "userid_column": "username",
        }

        data_prep = DataPrep(config)

        for user in users:
            df = pd.DataFrame(
                {
                    "username": [user] * 50,
                    "timestamp": pd.date_range("2024-01-01", periods=50, freq="h"),
                    "logcount": range(50),
                    "locincrement": range(1, 51),
                    "hour": [i % 24 for i in range(50)],
                }
            )

            user_dfs[user] = data_prep.prepare(df)

        # Verify all users prepared correctly
        assert len(user_dfs) == 3
        for _user, df_prepared in user_dfs.items():
            assert len(df_prepared) == 50
            assert list(df_prepared.columns) == ["logcount", "locincrement", "hour"]
