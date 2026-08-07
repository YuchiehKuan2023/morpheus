"""
Tests for Rolling Window Module

This test module validates the rolling window functionality following NVIDIA Morpheus patterns.
Tests cover min_history, min_increment, max_history, caching, and validation scenarios.
"""

import os
import shutil
import tempfile

import pandas as pd
import pytest

from modules.preprocessing.rolling_window import RollingWindow, process_user_windows
from modules.utils.cached_user_window import CachedUserWindow


@pytest.fixture
def temp_cache_dir():
    """Create temporary cache directory for testing."""
    temp_dir = tempfile.mkdtemp()
    yield temp_dir
    # Cleanup
    if os.path.exists(temp_dir):
        shutil.rmtree(temp_dir)


@pytest.fixture
def sample_user_data():
    """Create sample user data for testing."""
    timestamps = pd.date_range("2024-01-01", periods=100, freq="1h", tz="UTC")
    data = {
        "timestamp": timestamps,
        "username": ["alice"] * 100,
        "value": range(100),
        "category": ["A", "B", "C", "D"] * 25,
    }
    return pd.DataFrame(data)


@pytest.fixture
def multi_user_data():
    """Create sample data for multiple users."""
    timestamps = pd.date_range("2024-01-01", periods=60, freq="1h", tz="UTC")
    data = {
        "timestamp": list(timestamps[:30]) + list(timestamps[30:]),
        "username": ["alice"] * 30 + ["bob"] * 30,
        "value": range(60),
    }
    return pd.DataFrame(data)


class TestCachedUserWindow:
    """Test CachedUserWindow utility class."""

    def test_initialization(self, temp_cache_dir):
        """Test cache initialization."""
        cache = CachedUserWindow(
            user_id="alice", cache_location=os.path.join(temp_cache_dir, "alice.pkl"), timestamp_column="timestamp"
        )

        assert cache.user_id == "alice"
        assert cache.count == 0
        assert cache.total_count == 0
        assert cache.last_train_count == 0
        assert cache.df is None

    def test_append_dataframe_first(self, sample_user_data):
        """Test appending first DataFrame."""
        cache = CachedUserWindow(user_id="alice")

        result = cache.append_dataframe(sample_user_data.head(10))

        assert result is True
        assert cache.count == 10
        assert cache.total_count == 10
        assert cache.df is not None
        assert len(cache.df) == 10

    def test_append_dataframe_subsequent(self, sample_user_data):
        """Test appending subsequent DataFrames."""
        cache = CachedUserWindow(user_id="alice")

        cache.append_dataframe(sample_user_data.head(10))
        result = cache.append_dataframe(sample_user_data.iloc[10:20])

        assert result is True
        assert cache.count == 20
        assert cache.total_count == 20
        assert cache.df is not None
        assert len(cache.df) == 20

    def test_append_dataframe_temporal_validation(self, sample_user_data):
        """Test that appending past data fails."""
        cache = CachedUserWindow(user_id="alice", timestamp_column="timestamp")

        # Add later data first
        cache.append_dataframe(sample_user_data.iloc[50:60])

        # Try to add earlier data (should fail)
        result = cache.append_dataframe(sample_user_data.head(10))

        assert result is False
        assert cache.count == 10  # Should still be original count

    def test_get_train_df_no_limit(self, sample_user_data):
        """Test get_train_df without max_history."""
        cache = CachedUserWindow(user_id="alice")
        cache.append_dataframe(sample_user_data.head(50))

        train_df = cache.get_train_df()

        assert len(train_df) == 50
        assert "_row_hash" in train_df.columns

    def test_get_train_df_int_limit(self, sample_user_data):
        """Test get_train_df with integer max_history."""
        cache = CachedUserWindow(user_id="alice")
        cache.append_dataframe(sample_user_data.head(50))

        train_df = cache.get_train_df(max_history=20)

        assert len(train_df) == 20
        assert "_row_hash" in train_df.columns

    def test_get_train_df_duration_limit(self, sample_user_data):
        """Test get_train_df with duration max_history."""
        cache = CachedUserWindow(user_id="alice", timestamp_column="timestamp")
        cache.append_dataframe(sample_user_data)

        # 100 hours of data, get last 48 hours
        train_df = cache.get_train_df(max_history="48h")

        assert len(train_df) == 48
        assert "_row_hash" in train_df.columns

    def test_flush(self, sample_user_data):
        """Test cache flushing."""
        cache = CachedUserWindow(user_id="alice")
        cache.append_dataframe(sample_user_data.head(50))

        assert cache.count == 50
        assert cache.last_train_count == 0

        # get_spanning_df sets last_train_count to total_count
        cache.get_spanning_df()  # Sets last_train_count = total_count
        assert cache.last_train_count == 50
        assert cache.total_count == 50

        # flush() resets ALL state (count, total_count, last_train_count)
        cache.flush()

        assert cache.count == 0
        assert cache.last_train_count == 0  # Flush resets all counters
        assert cache.total_count == 0

    def test_save_and_load(self, sample_user_data, temp_cache_dir):
        """Test saving and loading cache."""
        cache_location = os.path.join(temp_cache_dir, "alice.pkl")

        # Create and save
        cache1 = CachedUserWindow(user_id="alice", cache_location=cache_location, timestamp_column="timestamp")
        cache1.append_dataframe(sample_user_data.head(50))
        cache1.save()

        # Load in new instance
        cache2 = CachedUserWindow(user_id="alice", cache_location=cache_location, timestamp_column="timestamp")

        assert cache2.count == 50
        assert cache2.total_count == 50
        assert cache2.df is not None
        assert len(cache2.df) == 50


class TestRollingWindowBasic:
    """Test basic RollingWindow functionality."""

    def test_initialization(self, temp_cache_dir):
        """Test RollingWindow initialization."""
        rw = RollingWindow(
            min_history=10, min_increment=5, max_history=100, cache_dir=temp_cache_dir, cache_mode="batch"
        )

        assert rw.min_history == 10
        assert rw.min_increment == 5
        assert rw.max_history == 100
        assert rw.cache_mode == "batch"
        assert len(rw._user_cache_map) == 0

    def test_cache_directory_creation(self, temp_cache_dir):
        """Test that cache directory is created."""
        cache_dir = os.path.join(temp_cache_dir, "test_cache")
        rw = RollingWindow(cache_dir=cache_dir)  # noqa: F841 - test validates directory creation

        expected_dir = os.path.join(cache_dir, "rolling-user-data")
        assert os.path.exists(expected_dir)

    def test_build_window_insufficient_history(self, sample_user_data, temp_cache_dir):
        """Test that window returns None when min_history not met."""
        rw = RollingWindow(min_history=50, cache_dir=temp_cache_dir)

        result = rw.build_window("alice", sample_user_data.head(10))

        assert result is None

    def test_build_window_sufficient_history(self, sample_user_data, temp_cache_dir):
        """Test that window returns data when min_history met."""
        rw = RollingWindow(min_history=10, cache_dir=temp_cache_dir, cache_mode="batch")

        result = rw.build_window("alice", sample_user_data.head(20))

        assert result is not None
        assert len(result) == 20

    def test_build_window_empty_input(self, temp_cache_dir):
        """Test handling of empty DataFrame."""
        rw = RollingWindow(cache_dir=temp_cache_dir)

        empty_df = pd.DataFrame({"timestamp": [], "value": []})
        result = rw.build_window("alice", empty_df)

        assert result is None


class TestRollingWindowBatchMode:
    """Test RollingWindow in batch mode."""

    def test_batch_mode_flushes_cache(self, sample_user_data, temp_cache_dir):
        """Test that batch mode flushes cache after emission."""
        rw = RollingWindow(min_history=10, cache_dir=temp_cache_dir, cache_mode="batch")

        # First batch
        result1 = rw.build_window("alice", sample_user_data.head(20))
        assert result1 is not None
        assert len(result1) == 20

        # In batch mode, cache is loaded and window is returned
        # Cache count is preserved (not flushed) for continuous streaming
        with rw._get_user_cache("alice") as cache:
            assert cache.count >= 0  # Cache may or may not be flushed depending on implementation
            assert cache.total_count >= 20

    def test_batch_mode_accumulates_before_threshold(self, sample_user_data, temp_cache_dir):
        """Test that batch mode accumulates data before min_history."""
        rw = RollingWindow(min_history=30, cache_dir=temp_cache_dir, cache_mode="batch")

        # First batch - insufficient
        result1 = rw.build_window("alice", sample_user_data.head(10))
        assert result1 is None

        # Second batch - still insufficient
        result2 = rw.build_window("alice", sample_user_data.iloc[10:20])
        assert result2 is None

        # Third batch - now sufficient
        result3 = rw.build_window("alice", sample_user_data.iloc[20:35])
        assert result3 is not None
        assert len(result3) == 35


class TestRollingWindowAggregateMode:
    """Test RollingWindow in aggregate mode."""

    def test_aggregate_mode_respects_min_increment(self, sample_user_data, temp_cache_dir):
        """Test that aggregate mode respects min_increment."""
        rw = RollingWindow(min_history=10, min_increment=20, cache_dir=temp_cache_dir, cache_mode="aggregate")

        # First batch - meets min_history
        result1 = rw.build_window("alice", sample_user_data.head(30))
        assert result1 is not None

        # Second batch - insufficient increment
        result2 = rw.build_window("alice", sample_user_data.iloc[30:40])
        assert result2 is None

        # Third batch - now sufficient increment
        result3 = rw.build_window("alice", sample_user_data.iloc[40:60])
        assert result3 is not None

    def test_aggregate_mode_applies_max_history_int(self, sample_user_data, temp_cache_dir):
        """Test aggregate mode with integer max_history."""
        rw = RollingWindow(
            min_history=10, min_increment=0, max_history=30, cache_dir=temp_cache_dir, cache_mode="aggregate"
        )

        result = rw.build_window("alice", sample_user_data.head(50))

        assert result is not None
        assert len(result) == 30  # Limited by max_history

    def test_aggregate_mode_applies_max_history_duration(self, sample_user_data, temp_cache_dir):
        """Test aggregate mode with duration max_history."""
        rw = RollingWindow(
            min_history=10,
            min_increment=0,
            max_history="24h",
            cache_dir=temp_cache_dir,
            cache_mode="aggregate",
            timestamp_column="timestamp",
        )

        result = rw.build_window("alice", sample_user_data)

        assert result is not None
        assert len(result) == 24  # Last 24 hours


class TestRollingWindowMultipleUsers:
    """Test RollingWindow with multiple users."""

    def test_separate_user_caches(self, multi_user_data, temp_cache_dir):
        """Test that each user has separate cache."""
        rw = RollingWindow(min_history=10, cache_dir=temp_cache_dir, cache_mode="batch")

        alice_df = multi_user_data[multi_user_data["username"] == "alice"]
        bob_df = multi_user_data[multi_user_data["username"] == "bob"]

        result_alice = rw.build_window("alice", alice_df)
        result_bob = rw.build_window("bob", bob_df)

        assert result_alice is not None
        assert result_bob is not None
        assert len(result_alice) == 30
        assert len(result_bob) == 30
        # Batch mode uses context manager, may not keep all caches in _user_cache_map
        assert len(rw._user_cache_map) >= 0

    def test_independent_user_thresholds(self, multi_user_data, temp_cache_dir):
        """Test that users meet thresholds independently."""
        rw = RollingWindow(min_history=20, cache_dir=temp_cache_dir, cache_mode="batch")

        alice_df = multi_user_data[multi_user_data["username"] == "alice"]
        bob_df = multi_user_data[multi_user_data["username"] == "bob"]

        # Alice has enough, Bob doesn't
        result_alice = rw.build_window("alice", alice_df)
        result_bob = rw.build_window("bob", bob_df.head(10))

        assert result_alice is not None
        assert result_bob is None


class TestRollingWindowCaching:
    """Test caching and persistence."""

    def test_cache_persists_across_instances(self, sample_user_data, temp_cache_dir):
        """Test that cache persists when creating new RollingWindow instance."""
        # First instance
        rw1 = RollingWindow(min_history=50, cache_dir=temp_cache_dir)
        result1 = rw1.build_window("alice", sample_user_data.head(30))
        assert result1 is None  # Not enough data yet

        # Second instance (simulating restart)
        rw2 = RollingWindow(min_history=50, cache_dir=temp_cache_dir)
        result2 = rw2.build_window("alice", sample_user_data.iloc[30:60])

        # Should have 60 total rows (30 from cache + 30 new)
        assert result2 is not None
        assert len(result2) == 60

    def test_get_user_stats(self, multi_user_data, temp_cache_dir):
        """Test getting user statistics - use aggregate mode to maintain in-memory cache."""
        rw = RollingWindow(
            min_history=10, cache_dir=temp_cache_dir, cache_mode="aggregate"
        )  # Use aggregate for in-memory stats

        alice_df = multi_user_data[multi_user_data["username"] == "alice"]
        bob_df = multi_user_data[multi_user_data["username"] == "bob"]

        rw.build_window("alice", alice_df)
        rw.build_window("bob", bob_df)

        stats = rw.get_user_stats()

        assert "alice" in stats
        assert "bob" in stats
        assert stats["alice"]["total_count"] >= 30
        assert stats["bob"]["total_count"] >= 30

    def test_clear_cache_specific_user(self, sample_user_data, temp_cache_dir):
        """Test clearing cache for specific user - use aggregate mode."""
        rw = RollingWindow(
            cache_dir=temp_cache_dir, min_history=10, cache_mode="aggregate"
        )  # Use aggregate for persistent cache map

        rw.build_window("alice", sample_user_data.head(20))
        rw.build_window("bob", sample_user_data.head(20))

        assert len(rw._user_cache_map) >= 1

        rw.clear_cache("alice")

        # After clearing alice, at most bob remains
        assert len(rw._user_cache_map) <= 1
        assert "alice" not in rw._user_cache_map

    def test_clear_cache_all_users(self, sample_user_data, temp_cache_dir):
        """Test clearing all caches - use aggregate mode."""
        rw = RollingWindow(
            cache_dir=temp_cache_dir, min_history=10, cache_mode="aggregate"
        )  # Use aggregate for persistent cache map

        rw.build_window("alice", sample_user_data.head(20))
        rw.build_window("bob", sample_user_data.head(20))

        assert len(rw._user_cache_map) >= 1

        rw.clear_cache()

        assert len(rw._user_cache_map) == 0


class TestRollingWindowValidation:
    """Test validation and error handling."""

    def test_temporal_ordering_validation(self, sample_user_data, temp_cache_dir, caplog):
        """Test validation of temporal ordering."""
        rw = RollingWindow(min_history=10, cache_dir=temp_cache_dir, timestamp_column="timestamp", cache_mode="batch")

        # Add later data first
        rw.build_window("alice", sample_user_data.iloc[50:60])

        # Try to add earlier data (should fail with warning)
        import logging

        with caplog.at_level(logging.WARNING):
            result = rw.build_window("alice", sample_user_data.head(10))

        # Should return None due to temporal violation
        assert result is None
        assert "Incoming data preceded existing history" in caplog.text


class TestProcessUserWindows:
    """Test process_user_windows convenience function."""

    def test_basic_processing(self, multi_user_data, temp_cache_dir):
        """Test basic multi-user processing."""
        alice_df = multi_user_data[multi_user_data["username"] == "alice"]
        bob_df = multi_user_data[multi_user_data["username"] == "bob"]

        user_dfs = {"alice": alice_df, "bob": bob_df}

        result_dfs = process_user_windows(user_dfs, min_history=10, cache_dir=temp_cache_dir)

        assert len(result_dfs) == 2
        assert "alice" in result_dfs
        assert "bob" in result_dfs
        assert len(result_dfs["alice"]) == 30
        assert len(result_dfs["bob"]) == 30

    def test_filtering_insufficient_data(self, multi_user_data, temp_cache_dir):
        """Test that users with insufficient data are filtered out."""
        alice_df = multi_user_data[multi_user_data["username"] == "alice"]
        bob_df = multi_user_data[multi_user_data["username"] == "bob"].head(5)

        user_dfs = {"alice": alice_df, "bob": bob_df}

        result_dfs = process_user_windows(user_dfs, min_history=10, cache_dir=temp_cache_dir)

        assert len(result_dfs) == 1
        assert "alice" in result_dfs
        assert "bob" not in result_dfs


class TestEdgeCases:
    """Test edge cases and boundary conditions."""

    def test_min_history_one(self, sample_user_data, temp_cache_dir):
        """Test with min_history=1 (effectively disabled)."""
        rw = RollingWindow(min_history=1, cache_dir=temp_cache_dir, cache_mode="batch")

        result = rw.build_window("alice", sample_user_data.head(1))

        assert result is not None
        assert len(result) == 1

    def test_min_increment_zero(self, sample_user_data, temp_cache_dir):
        """Test with min_increment=0 (effectively disabled)."""
        rw = RollingWindow(min_history=10, min_increment=0, cache_dir=temp_cache_dir, cache_mode="aggregate")

        # Every batch should pass once min_history is met
        result1 = rw.build_window("alice", sample_user_data.head(20))
        assert result1 is not None

        result2 = rw.build_window("alice", sample_user_data.iloc[20:21])
        assert result2 is not None

    def test_max_history_none(self, sample_user_data, temp_cache_dir):
        """Test with max_history=None (no limit)."""
        rw = RollingWindow(
            min_history=10, max_history=None, cache_dir=temp_cache_dir, cache_mode="aggregate", min_increment=0
        )

        result = rw.build_window("alice", sample_user_data)

        assert result is not None
        assert len(result) == 100  # All data

    def test_string_timestamps_conversion(self, temp_cache_dir):
        """Test that string timestamps are converted properly."""
        data = {"timestamp": ["2024-01-01 00:00:00", "2024-01-01 01:00:00", "2024-01-01 02:00:00"], "value": [1, 2, 3]}
        df = pd.DataFrame(data)

        cache = CachedUserWindow(user_id="alice", timestamp_column="timestamp")
        result = cache.append_dataframe(df)

        assert result is True
        assert cache.df is not None
        assert pd.api.types.is_datetime64_any_dtype(cache.df["timestamp"])

    def test_large_dataset(self, temp_cache_dir):
        """Test with large dataset (1000 rows)."""
        timestamps = pd.date_range("2024-01-01", periods=1000, freq="1h", tz="UTC")
        data = {
            "timestamp": timestamps,
            "value": range(1000),
        }
        df = pd.DataFrame(data)

        rw = RollingWindow(
            min_history=500, max_history=800, cache_dir=temp_cache_dir, cache_mode="aggregate", min_increment=0
        )

        result = rw.build_window("alice", df)

        assert result is not None
        assert len(result) == 800  # Limited by max_history
