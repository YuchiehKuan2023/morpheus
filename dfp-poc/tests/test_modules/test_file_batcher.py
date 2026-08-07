"""
Unit tests for FileBatcher module

Tests file batching logic, timestamp extraction, sampling, and time window filtering.
"""

import tempfile
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import pytest

from modules.io.file_batcher import DEFAULT_ISO_DATE_REGEX_PATTERN, FileBatcher


@pytest.fixture
def temp_files():
    """Fixture that creates temporary test files"""
    with tempfile.TemporaryDirectory() as tmpdir:
        files = []
        for i in range(3):
            file_path = Path(tmpdir) / f"file_{i}.json"
            file_path.touch()
            files.append(file_path)
        yield files


class TestFileBatcher:
    """Test suite for FileBatcher class"""

    def test_init_default_config(self):
        """Test FileBatcher initialization with default config"""
        batcher = FileBatcher({})
        assert batcher.period is None
        assert batcher.sampling is None
        assert batcher.start_time is None
        assert batcher.end_time is None
        assert batcher.iso_date_regex.pattern == DEFAULT_ISO_DATE_REGEX_PATTERN

    def test_init_custom_config(self):
        """Test FileBatcher initialization with custom config"""
        config = {
            "period": "W",
            "sampling": 0.5,
            "start_time": datetime(2024, 1, 1),
            "end_time": datetime(2024, 12, 31),
        }
        batcher = FileBatcher(config)
        assert batcher.period == "W"
        assert batcher.sampling == 0.5
        assert batcher.start_time == datetime(2024, 1, 1)
        assert batcher.end_time == datetime(2024, 12, 31)

    def test_batch_files_single_file(self, temp_files):
        """Test batching with a single file"""
        batcher = FileBatcher({})
        file_path = temp_files[0]

        batches = batcher.batch_files([str(file_path)])  # noqa: F841 - test validates no exception

    def test_batch_files_multiple_files_no_period(self):
        """Test batching multiple files without period (single batch)"""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create test files
            files = []
            for i in range(3):
                file_path = Path(tmpdir) / f"test_{i}.json"
                file_path.touch()
                files.append(str(file_path))

            batcher = FileBatcher({"period": None})
            batches = batcher.batch_files(files)

            assert len(batches) == 1
            assert len(batches[0]) == 3
            assert set(batches[0]) == set(files)

    def test_batch_files_empty_list(self):
        """Test batching empty file list"""
        batcher = FileBatcher({})
        batches = batcher.batch_files([])
        assert batches == []

    def test_extract_timestamp_from_filename_iso(self):
        """Test timestamp extraction from filename with ISO format"""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Filename with ISO timestamp (colons replaced with hyphens for Windows compatibility)
            file_path = Path(tmpdir) / "log-2024-03-15T10-30-45Z.json"
            file_path.touch()

            batcher = FileBatcher({})
            timestamp = batcher.extract_timestamp(str(file_path))

            assert timestamp == datetime(2024, 3, 15, 10, 30, 45, tzinfo=timezone.utc)

    def test_extract_timestamp_from_filename_with_microseconds(self):
        """Test timestamp extraction with microseconds"""
        with tempfile.TemporaryDirectory() as tmpdir:
            file_path = Path(tmpdir) / "log-2024-03-15T10-30-45.123456Z.json"
            file_path.touch()

            batcher = FileBatcher({})
            timestamp = batcher.extract_timestamp(str(file_path))

            assert timestamp == datetime(2024, 3, 15, 10, 30, 45, 123456, tzinfo=timezone.utc)

    def test_extract_timestamp_from_file_mtime(self):
        """Test timestamp extraction from file modification time"""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Filename without ISO timestamp
            file_path = Path(tmpdir) / "data.json"
            file_path.touch()

            batcher = FileBatcher({})
            timestamp = batcher.extract_timestamp(str(file_path))

            # Should use file mtime (within last few seconds)
            now = datetime.now(timezone.utc)
            assert isinstance(timestamp, datetime)
            assert timestamp.tzinfo == timezone.utc
            assert (now - timestamp).total_seconds() < 10  # Within 10 seconds

    def test_extract_timestamp_nonexistent_file(self):
        """Test timestamp extraction fails for nonexistent file"""
        batcher = FileBatcher({})
        result = batcher.extract_timestamp("/nonexistent/file.json")
        assert result is None  # Should return None for nonexistent file

    def test_apply_sampling_frequency(self):
        """Test frequency-based sampling"""
        # Create DataFrame with hourly timestamps as a column
        timestamps = pd.date_range("2024-01-01", periods=24, freq="h")
        df = pd.DataFrame({"timestamp": timestamps, "file_path": [f"file_{i}.json" for i in range(24)]})

        batcher = FileBatcher({"sampling": "6h"})  # Sample every 6 hours
        df_sampled = batcher.apply_sampling(df)

        # Should have 4 files (0, 6, 12, 18 hours)
        assert len(df_sampled) == 4

    def test_apply_sampling_fraction(self):
        """Test fraction-based sampling"""
        # Create DataFrame with 100 files
        timestamps = pd.date_range("2024-01-01", periods=100, freq="h")
        df = pd.DataFrame({"timestamp": timestamps, "file_path": [f"file_{i}.json" for i in range(100)]})

        batcher = FileBatcher({"sampling": 0.1})  # Sample 10%
        df_sampled = batcher.apply_sampling(df)

        # Should have approximately 10 files
        assert len(df_sampled) == 10  # Exact with random_state=42

    def test_apply_sampling_fixed_count(self):
        """Test fixed count sampling"""
        # Create DataFrame with 100 files
        timestamps = pd.date_range("2024-01-01", periods=100, freq="h")
        df = pd.DataFrame({"timestamp": timestamps, "file_path": [f"file_{i}.json" for i in range(100)]})

        batcher = FileBatcher({"sampling": 10})  # Sample exactly 10 files
        df_sampled = batcher.apply_sampling(df)

        assert len(df_sampled) == 10

    def test_apply_sampling_fixed_count_exceeds_available(self):
        """Test fixed count sampling when count exceeds available files"""
        # Create DataFrame with only 5 files
        timestamps = pd.date_range("2024-01-01", periods=5, freq="h")
        df = pd.DataFrame({"timestamp": timestamps, "file_path": [f"file_{i}.json" for i in range(5)]})

        batcher = FileBatcher({"sampling": 10})  # Request 10, but only 5 available
        df_sampled = batcher.apply_sampling(df)

        assert len(df_sampled) == 5

    def test_apply_sampling_none(self):
        """Test no sampling (sampling=None)"""
        timestamps = pd.date_range("2024-01-01", periods=10, freq="h")
        df = pd.DataFrame({"timestamp": timestamps, "file_path": [f"file_{i}.json" for i in range(10)]})

        batcher = FileBatcher({"sampling": None})
        df_sampled = batcher.apply_sampling(df)

        assert len(df_sampled) == 10  # No sampling

    def test_time_window_filter_start_only(self):
        """Test time window filtering with start_time only"""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create files with different timestamps in filenames
            files = []
            for day in [10, 15, 20]:
                file_path = Path(tmpdir) / f"log-2024-03-{day}T10-00-00Z.json"
                file_path.touch()
                files.append(str(file_path))

            config = {
                "period": None,
                "start_time": "2024-03-15T00:00:00",  # Only files from 15th onwards
            }
            batcher = FileBatcher(config)
            batches = batcher.batch_files(files)

            # Should have 2 files (15th and 20th)
            assert len(batches) == 1
            assert len(batches[0]) == 2

    def test_time_window_filter_end_only(self):
        """Test time window filtering with end_time only"""
        with tempfile.TemporaryDirectory() as tmpdir:
            files = []
            for day in [10, 15, 20]:
                file_path = Path(tmpdir) / f"log-2024-03-{day}T10-00-00Z.json"
                file_path.touch()
                files.append(str(file_path))

            config = {
                "period": None,
                "end_time": "2024-03-15T23:59:59",  # Only files up to 15th
            }
            batcher = FileBatcher(config)
            batches = batcher.batch_files(files)

            # Should have 2 files (10th and 15th)
            assert len(batches) == 1
            assert len(batches[0]) == 2

    def test_time_window_filter_both(self):
        """Test time window filtering with both start_time and end_time"""
        with tempfile.TemporaryDirectory() as tmpdir:
            files = []
            for day in [10, 15, 20, 25]:
                file_path = Path(tmpdir) / f"log-2024-03-{day}T10-00-00Z.json"
                file_path.touch()
                files.append(str(file_path))

            config = {
                "period": None,
                "start_time": "2024-03-15T00:00:00",
                "end_time": "2024-03-20T23:59:59",
            }
            batcher = FileBatcher(config)
            batches = batcher.batch_files(files)

            # Should have 2 files (15th and 20th)
            assert len(batches) == 1
            assert len(batches[0]) == 2

    def test_batch_by_daily_period(self):
        """Test batching files by daily period"""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create files for different days
            files = []
            for day in [15, 15, 16, 16, 17]:
                for hour in [10, 14]:  # Two files per day
                    file_path = Path(tmpdir) / f"log-2024-03-{day}T{hour:02d}-00-00Z.json"
                    file_path.touch()
                    files.append(str(file_path))

            config = {"period": "D"}  # Daily batching
            batcher = FileBatcher(config)
            batches = batcher.batch_files(files)

            # Should have 3 batches (one per day: 15th, 16th, 17th)
            assert len(batches) == 3
            # Each batch should have 2 or 4 files
            assert all(len(batch) in [2, 4] for batch in batches)

    def test_batch_by_weekly_period(self):
        """Test batching files by weekly period"""
        with tempfile.TemporaryDirectory() as tmpdir:
            files = []
            # Create files across 3 weeks
            for day in range(1, 22):  # 21 days = 3 weeks
                file_path = Path(tmpdir) / f"log-2024-03-{day:02d}T10-00-00Z.json"
                file_path.touch()
                files.append(str(file_path))

            config = {"period": "W"}  # Weekly batching
            batcher = FileBatcher(config)
            batches = batcher.batch_files(files)

            # Should have multiple batches (weeks)
            assert len(batches) >= 3

    def test_batch_files_integration(self):
        """Integration test: batch, filter, and sample"""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create 20 files across 4 days
            files = []
            for day in [15, 16, 17, 18]:
                for hour in range(5):  # 5 files per day
                    file_path = Path(tmpdir) / f"log-2024-03-{day}T{hour:02d}-00-00Z.json"
                    file_path.touch()
                    files.append(str(file_path))

            config = {
                "period": "D",  # Daily batching
                "sampling": 0.5,  # Sample 50%
                "start_time": "2024-03-16T00:00:00",  # Skip first day
                "end_time": "2024-03-17T23:59:59",  # Skip last day
            }
            batcher = FileBatcher(config)
            batches = batcher.batch_files(files)

            # Should have 2 batches (16th and 17th)
            # Each batch should have ~2-3 files (50% of 5)
            assert len(batches) == 2
            assert all(len(batch) >= 2 for batch in batches)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
