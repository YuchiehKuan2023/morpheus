"""
Test Suite for DFP Inference Modules

Comprehensive unit tests for all inference-related modules:
- DFPInference: Model loading, inference execution, z-score computation
- FilterDetections: Threshold-based anomaly filtering
- DFPPostProcessing: Metadata enrichment and formatting
- DFPSerializer: Output serialization to CSV/JSON/JSONLines

Author: Tomasz Zabek <tzabek@deloitte.co.uk>
Date: 2025-11-11
"""

import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np
import pandas as pd
import pytest
import torch

# Add modules to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from modules.control.control_message import ControlMessage
from modules.inference.dfp_inference import DFPInference, ModelCache, ModelManager
from modules.inference.filter_detections import FilterDetections
from modules.inference.postprocessing import DFPPostProcessing
from modules.inference.serialization import DFPSerializer

# ============================================================================
# Test Fixtures
# ============================================================================


@pytest.fixture
def sample_features_df():
    """Create a sample features DataFrame for testing."""
    return pd.DataFrame(
        {
            "user_id": ["user1"] * 100,
            "timestamp": pd.date_range("2025-01-01", periods=100, freq="1h"),
            "feature1": np.random.randn(100),
            "feature2": np.random.randn(100),
            "feature3": np.random.randn(100),
            "feature4": np.random.randn(100),
            "feature5": np.random.randn(100),
        }
    )


@pytest.fixture
def sample_inference_results_df():
    """Create sample inference results with z-scores."""
    np.random.seed(42)
    n_samples = 100

    # Generate mostly normal z-scores with a few anomalies
    z_scores = np.random.randn(n_samples) * 0.5
    # Inject some anomalies
    z_scores[10] = 3.5
    z_scores[20] = -3.2
    z_scores[50] = 4.1

    return pd.DataFrame(
        {
            "user_id": ["user1"] * n_samples,
            "timestamp": pd.date_range("2025-01-01", periods=n_samples, freq="1h"),
            "feature1": np.random.randn(n_samples),
            "feature2": np.random.randn(n_samples),
            "mean_abs_z": np.abs(z_scores),
            "max_abs_z": np.abs(z_scores) * 1.1,
            "z_loss": z_scores**2,
        }
    )


@pytest.fixture
def sample_control_message(sample_features_df):
    """Create a sample ControlMessage for testing."""
    msg = ControlMessage()
    msg.payload(sample_features_df)
    msg.set_metadata("user_id", "user1")
    msg.set_metadata("model_version", "1.0.0")
    # Add inference task (required by NVIDIA DFP pattern)
    msg.add_task("inference", {"model_name": "dfp-user1"})
    return msg


@pytest.fixture
def mock_model():
    """Create a mock PyTorch model."""
    model = MagicMock()
    model.eval = MagicMock()
    model.to = MagicMock(return_value=model)

    # Mock forward pass to return reconstruction
    def mock_forward(x):
        # Return same shape as input
        return x + torch.randn_like(x) * 0.1

    model.forward = mock_forward
    model.__call__ = mock_forward

    # Mock get_results to return DataFrame with z-scores (NVIDIA pattern)
    def mock_get_results(df, return_abs=False):
        """Mock AutoEncoder.get_results() method."""
        n_samples = len(df)
        results = pd.DataFrame(
            {
                "mean_abs_z": np.abs(np.random.randn(n_samples) * 2),
                "max_abs_z": np.abs(np.random.randn(n_samples) * 2.5),
                "z_loss": np.random.randn(n_samples) ** 2,
            }
        )
        return results

    model.get_results = mock_get_results

    return model


@pytest.fixture
def mock_mlflow_model(mock_model):
    """Create a mock MLflow model wrapper."""
    wrapper = MagicMock()
    wrapper.unwrap_python_model = MagicMock(return_value=mock_model)
    return wrapper


# ============================================================================
# Test ModelCache
# ============================================================================


class TestModelCache:
    """Test suite for ModelCache class."""

    def test_cache_initialization(self, mock_model):
        """Test ModelCache initialization following NVIDIA pattern."""
        cache = ModelCache(reg_model_name="dfp-user1", reg_model_version="1", model_uri="models:/dfp-user1/1")
        assert cache.reg_model_name == "dfp-user1"
        assert cache.reg_model_version == "1"
        assert cache.model_uri == "models:/dfp-user1/1"
        assert cache.load_time is not None
        assert cache._model is None  # Lazy loading

    @patch("mlflow.pytorch.load_model")
    def test_cache_load_model(self, mock_load_model, mock_model):
        """Test loading model from cache."""
        mock_load_model.return_value = mock_model

        cache = ModelCache(reg_model_name="dfp-user1", reg_model_version="1", model_uri="models:/dfp-user1/1")

        loaded_model = cache.load_model()
        assert loaded_model is mock_model
        mock_load_model.assert_called_once_with(model_uri="models:/dfp-user1/1")


# ============================================================================
# Test ModelManager
# ============================================================================


class TestModelManager:
    """Test suite for ModelManager class."""

    def test_manager_initialization(self):
        """Test ModelManager initialization."""
        manager = ModelManager(model_name_formatter="dfp-{user_id}", cache_size_max=10, cache_timeout_sec=600.0)

        assert manager.model_name_formatter == "dfp-{user_id}"
        assert manager.cache_size_max == 10
        assert manager.cache_timeout_sec == 600.0
        assert isinstance(manager._model_cache, dict)

    def test_load_user_model_from_cache(self, mock_model):
        """Test loading model from cache."""
        manager = ModelManager()
        mock_client = MagicMock()

        # Add to cache
        cache_entry = ModelCache(reg_model_name="dfp-user1", reg_model_version="1", model_uri="models:/dfp-user1/1")
        cache_entry._model = mock_model  # Pre-load for test
        manager._model_cache["user1"] = cache_entry

        # Should return cached model
        result = manager.load_user_model(mock_client, "user1")
        assert result is not None
        assert result is cache_entry
        assert result.load_model() is mock_model

    @patch("mlflow.pytorch.load_model")
    def test_load_user_model_from_mlflow(self, mock_load_model, mock_model):
        """Test loading model from MLflow following NVIDIA pattern."""
        manager = ModelManager(model_name_formatter="dfp-{user_id}")
        mock_client = MagicMock()

        # Mock MLflow model versions with source URI
        mock_version = MagicMock()
        mock_version.version = "1"
        mock_version.source = "models:/m-uuid-12345"  # UUID-based source
        mock_client.search_model_versions.return_value = [mock_version]

        # Model will be loaded lazily by ModelCache
        mock_load_model.return_value = mock_model

        result = manager.load_user_model(mock_client, "user1")

        assert result is not None
        assert isinstance(result, ModelCache)
        assert result.model_uri == "models:/m-uuid-12345"

    @patch("mlflow.pytorch.load_model")
    def test_load_user_model_fallback(self, mock_load_model):
        """Test fallback to generic model when user model not found."""
        manager = ModelManager(model_name_formatter="dfp-{user_id}")
        mock_client = MagicMock()

        # User model not found, generic model found
        def mock_search(query):
            if "dfp-user1" in query:
                return []  # User model not found
            elif "dfp-generic_user" in query:
                mock_version = MagicMock()
                mock_version.version = "1"
                mock_version.source = "models:/m-uuid-generic"
                return [mock_version]
            return []

        mock_client.search_model_versions.side_effect = mock_search

        mock_model = MagicMock()
        mock_load_model.return_value = mock_model

        result = manager.load_user_model(mock_client, "user1", fallback_user_ids=["generic_user"])

        assert result is not None
        assert result.model_uri == "models:/m-uuid-generic"

    def test_load_user_model_failure(self):
        """Test model loading failure."""
        manager = ModelManager(model_name_formatter="dfp-{user_id}")
        mock_client = MagicMock()

        # No models found
        mock_client.search_model_versions.return_value = []

        result = manager.load_user_model(mock_client, "user1", fallback_user_ids=["generic_user"])

        assert result is None


# ============================================================================
# Test DFPInference
# ============================================================================


class TestDFPInference:
    """Test suite for DFPInference class."""

    @patch("modules.inference.dfp_inference.MlflowClient")
    def test_inference_initialization(self, mock_mlflow_client):
        """Test DFPInference initialization."""
        config = {
            "mlflow": {"tracking_uri": "http://localhost:5001", "model_name_formatter": "dfp-{user_id}"},
            "inference": {"fallback_username": "generic", "model_fetch_timeout": 1.0},
        }

        inference = DFPInference(config)
        assert inference.model_name_formatter == "dfp-{user_id}"
        assert inference.fallback_username == "generic"
        assert inference.model_fetch_timeout == 1.0

    @patch("modules.inference.dfp_inference.MlflowClient")
    def test_inference_with_valid_message(self, mock_mlflow_client, sample_control_message, mock_model):
        """Test inference with valid control message."""
        config = {"mlflow": {"tracking_uri": "http://localhost:5001", "model_name_formatter": "dfp-{user_id}"}}

        inference = DFPInference(config)

        # Mock model loading following NVIDIA pattern
        mock_cache = ModelCache(reg_model_name="dfp-user1", reg_model_version="1", model_uri="models:/m-uuid-test")
        mock_cache._model = mock_model  # Pre-load for test

        with patch.object(inference.model_manager, "load_user_model", return_value=mock_cache):
            result_msg = inference.infer(sample_control_message)

        assert result_msg is not None
        payload = result_msg.payload()
        assert payload is not None
        assert "mean_abs_z" in payload.columns

    @patch("modules.inference.dfp_inference.MlflowClient")
    def test_inference_empty_payload(self, mock_mlflow_client):
        """Test inference with empty payload."""
        config = {"mlflow": {"tracking_uri": "http://localhost:5001"}}
        inference = DFPInference(config)

        msg = ControlMessage()
        msg.payload(pd.DataFrame())
        msg.set_metadata("user_id", "user1")
        msg.add_task("inference", {"model_name": "dfp-user1"})

        # Should handle empty payload gracefully
        with pytest.raises(RuntimeError):
            result = inference.infer(msg)  # noqa: F841 - exception expected


# ============================================================================
# Test FilterDetections
# ============================================================================


class TestFilterDetections:
    """Test suite for FilterDetections class."""

    def test_filter_initialization(self):
        """Test FilterDetections initialization."""
        config = {
            "detection_criteria": {"field_name": "mean_abs_z", "threshold": 2.5, "filter_source": "DATAFRAME"},
            "output": {"copy_data": True},
        }

        filter_module = FilterDetections(config)
        assert filter_module.field_name == "mean_abs_z"
        assert filter_module.threshold == 2.5  # Should be 2.5 as configured
        assert filter_module.copy_data is True

    def test_filter_detections_with_threshold(self, sample_inference_results_df):
        """Test filtering detections above threshold - NVIDIA standard behavior."""
        config = {"detection_criteria": {"field_name": "mean_abs_z", "threshold": 2.0}, "output": {"copy_data": True}}

        filter_module = FilterDetections(config)

        msg = ControlMessage()
        msg.payload(sample_inference_results_df)
        msg.set_metadata("user_id", "user1")

        result_msg = filter_module.filter(msg)

        # NVIDIA standard: Returns only anomalies (or None)
        assert result_msg is not None
        result_df = result_msg.payload()
        assert result_df is not None
        # Should have fewer rows (only anomalies)
        assert len(result_df) < len(sample_inference_results_df)
        # All returned rows must be above threshold
        assert all(result_df["mean_abs_z"] >= 2.0)

    def test_filter_empty_result(self, sample_features_df):
        """Test filter returning no detections - NVIDIA standard: returns None."""
        # Create data with no anomalies
        df = sample_features_df.copy()
        df["mean_abs_z"] = 0.5  # All below threshold

        config = {"detection_criteria": {"field_name": "mean_abs_z", "threshold": 2.0}, "output": {"copy_data": True}}

        filter_module = FilterDetections(config)

        msg = ControlMessage()
        msg.payload(df)

        # NVIDIA standard: Returns None if no detections
        result_msg = filter_module.filter(msg)
        assert result_msg is None

    def test_filter_statistics(self, sample_inference_results_df):
        """Test filter statistics tracking."""
        config = {"detection_criteria": {"field_name": "mean_abs_z", "threshold": 2.0}}

        filter_module = FilterDetections(config)

        msg = ControlMessage()
        msg.payload(sample_inference_results_df)

        filter_module.filter(msg)
        stats = filter_module.get_statistics()

        assert "total_processed" in stats
        assert "total_anomalies" in stats
        assert "anomaly_rate" in stats
        assert stats["total_processed"] > 0


# ============================================================================
# Test DFPPostProcessing
# ============================================================================


class TestDFPPostProcessing:
    """Test suite for DFPPostProcessing class."""

    def test_postprocessing_initialization(self):
        """Test DFPPostProcessing initialization."""
        config = {"timestamp_column_name": "timestamp", "replace_nan": True}

        postproc = DFPPostProcessing(config)
        assert postproc.timestamp_column_name == "timestamp"
        assert postproc.replace_nan is True

    def test_postprocessing_add_metadata(self, sample_inference_results_df):
        """Test adding metadata to detections."""
        config = {"timestamp_column_name": "timestamp", "replace_nan": True}

        postproc = DFPPostProcessing(config)

        msg = ControlMessage()
        msg.payload(sample_inference_results_df)
        msg.set_metadata("user_id", "user1")
        msg.set_metadata("model_version", "v1.0")

        result_msg = postproc.process(msg)
        assert result_msg is not None
        result_df = result_msg.payload()
        assert result_df is not None

        # Check metadata columns added
        assert "user_id" in result_df.columns
        assert "model_version" in result_df.columns
        assert all(result_df["user_id"] == "user1")

    def test_postprocessing_format_timestamp(self, sample_inference_results_df):
        """Test timestamp formatting to ISO 8601."""
        config = {"timestamp_column_name": "timestamp"}

        postproc = DFPPostProcessing(config)

        msg = ControlMessage()
        msg.payload(sample_inference_results_df)
        msg.set_metadata("user_id", "user1")

        result_msg = postproc.process(msg)
        assert result_msg is not None
        result_df = result_msg.payload()
        assert result_df is not None

        # Check event_time column exists and is formatted
        assert "event_time" in result_df.columns
        # Verify ISO 8601 format (contains 'T' and timezone info)
        assert "T" in result_df["event_time"].iloc[0]

    def test_postprocessing_replace_nan(self):
        """Test NaN replacement."""
        df = pd.DataFrame(
            {
                "timestamp": pd.date_range("2025-01-01", periods=10, freq="1h"),
                "value1": [1, np.nan, 3, np.nan, 5, 6, 7, 8, 9, 10],
                "value2": [np.nan, 2, 3, 4, 5, np.nan, 7, 8, 9, 10],
            }
        )

        config = {"timestamp_column_name": "timestamp", "replace_nan": True}

        postproc = DFPPostProcessing(config)

        msg = ControlMessage()
        msg.payload(df)
        msg.set_metadata("user_id", "user1")

        result_msg = postproc.process(msg)
        assert result_msg is not None
        result_df = result_msg.payload()
        assert result_df is not None

        # Check NaNs are replaced
        assert not result_df["value1"].isna().any()
        assert not result_df["value2"].isna().any()

    def test_postprocessing_statistics(self, sample_inference_results_df):
        """Test postprocessing statistics tracking."""
        config = {}
        postproc = DFPPostProcessing(config)

        msg = ControlMessage()
        msg.payload(sample_inference_results_df)
        msg.set_metadata("user_id", "user1")

        postproc.process(msg)
        stats = postproc.get_statistics()

        assert "total_processed" in stats
        assert "total_events" in stats
        assert stats["total_processed"] > 0


# ============================================================================
# Test DFPSerializer
# ============================================================================


class TestDFPSerializer:
    """Test suite for DFPSerializer class."""

    def test_serializer_initialization(self, tmp_path):
        """Test DFPSerializer initialization."""
        config = {"output_dir": str(tmp_path), "file_format": "csv", "output_filename": "detections"}

        serializer = DFPSerializer(config)
        assert serializer.output_dir == tmp_path
        assert serializer.file_format == "csv"
        assert serializer.output_filename == "detections"

    def test_serialize_to_csv(self, tmp_path, sample_inference_results_df):
        """Test serialization to CSV format."""
        config = {"output_dir": str(tmp_path), "file_format": "csv", "output_filename": "detections", "overwrite": True}

        serializer = DFPSerializer(config)

        msg = ControlMessage()
        msg.payload(sample_inference_results_df)
        msg.set_metadata("user_id", "user1")

        result_msg = serializer.serialize(msg)  # noqa: F841 - test validates side effect

        # Check file was created
        output_file = tmp_path / "detections.csv"
        assert output_file.exists()

        # Verify content
        df_read = pd.read_csv(output_file)
        assert len(df_read) == len(sample_inference_results_df)

    def test_serialize_to_json(self, tmp_path, sample_inference_results_df):
        """Test serialization to JSON format."""
        config = {
            "output_dir": str(tmp_path),
            "file_format": "json",
            "output_filename": "detections",
            "overwrite": True,
            "json_lines": False,  # Output as JSON array, not JSONLines
        }

        serializer = DFPSerializer(config)

        msg = ControlMessage()
        msg.payload(sample_inference_results_df)

        result_msg = serializer.serialize(msg)  # noqa: F841 - test validates side effect

        # Check file was created
        output_file = tmp_path / "detections.json"
        assert output_file.exists()

        # Verify content
        with open(output_file) as f:
            data = json.load(f)
        assert len(data) == len(sample_inference_results_df)

    def test_serialize_to_jsonlines(self, tmp_path, sample_inference_results_df):
        """Test serialization to JSON Lines format."""
        config = {
            "output_dir": str(tmp_path),
            "file_format": "jsonlines",
            "output_filename": "detections",
            "overwrite": True,
        }

        serializer = DFPSerializer(config)

        msg = ControlMessage()
        msg.payload(sample_inference_results_df)

        result_msg = serializer.serialize(msg)  # noqa: F841 - test validates side effect

        # Check file was created
        output_file = tmp_path / "detections.jsonl"
        assert output_file.exists()

        # Verify content (each line is valid JSON)
        with open(output_file) as f:
            lines = f.readlines()
        assert len(lines) == len(sample_inference_results_df)

        # Check first line is valid JSON
        first_record = json.loads(lines[0])
        assert isinstance(first_record, dict)

    def test_serialize_append_mode(self, tmp_path, sample_inference_results_df):
        """Test appending to existing file."""
        config = {
            "output_dir": str(tmp_path),
            "file_format": "csv",
            "output_filename": "detections",
            "overwrite": False,
        }

        serializer = DFPSerializer(config)

        msg = ControlMessage()
        msg.payload(sample_inference_results_df)

        # Write twice
        serializer.serialize(msg)
        serializer.serialize(msg)

        # Check file has double the rows
        output_file = tmp_path / "detections.csv"
        df_read = pd.read_csv(output_file)
        assert len(df_read) == len(sample_inference_results_df) * 2

    def test_serialize_column_filtering(self, tmp_path, sample_inference_results_df):
        """Test serialization with column filtering."""
        config = {
            "output_dir": str(tmp_path),
            "file_format": "csv",
            "output_filename": "detections",
            "include_columns": ["timestamp", "mean_abs_z", "user_id"],
        }

        serializer = DFPSerializer(config)

        msg = ControlMessage()
        msg.payload(sample_inference_results_df)

        serializer.serialize(msg)

        # Check only specified columns are written
        output_file = tmp_path / "detections.csv"
        df_read = pd.read_csv(output_file)
        assert set(df_read.columns) == {"timestamp", "mean_abs_z", "user_id"}

    def test_serialize_statistics(self, tmp_path, sample_inference_results_df):
        """Test serializer statistics tracking."""
        config = {"output_dir": str(tmp_path), "file_format": "csv"}

        serializer = DFPSerializer(config)

        msg = ControlMessage()
        msg.payload(sample_inference_results_df)

        serializer.serialize(msg)
        stats = serializer.get_statistics()

        assert "total_messages" in stats
        assert "total_rows" in stats
        assert "file_format" in stats
        assert stats["total_messages"] > 0
        assert stats["total_rows"] > 0


# ============================================================================
# Integration Tests
# ============================================================================


class TestInferenceIntegration:
    """Integration tests for inference workflow."""

    @patch("modules.inference.dfp_inference.MlflowClient")
    def test_full_inference_workflow(self, mock_mlflow_client, tmp_path, sample_features_df, mock_model):
        """Test complete inference workflow: infer → filter → postprocess → serialize."""
        # Setup
        inference_config = {
            "mlflow": {"tracking_uri": "http://localhost:5001", "model_name_formatter": "dfp-{user_id}"}
        }

        filter_config = {"detection_criteria": {"field_name": "mean_abs_z", "threshold": 1.5}}

        postproc_config = {"timestamp_column_name": "timestamp"}

        serialize_config = {"output_dir": str(tmp_path), "file_format": "csv", "output_filename": "results"}

        # Create pipeline components
        inference = DFPInference(inference_config)
        filter_module = FilterDetections(filter_config)
        postproc = DFPPostProcessing(postproc_config)
        serializer = DFPSerializer(serialize_config)

        # Create input message with inference task
        msg = ControlMessage()
        msg.payload(sample_features_df)
        msg.set_metadata("user_id", "user1")
        msg.set_metadata("model_version", "v1.0")
        msg.add_task("inference", {"model_name": "dfp-user1"})

        # Run workflow
        mock_cache = ModelCache(reg_model_name="dfp-user1", reg_model_version="1", model_uri="models:/m-uuid-test")
        mock_cache._model = mock_model  # Pre-load for test

        with patch.object(inference.model_manager, "load_user_model", return_value=mock_cache):
            inference_msg = inference.infer(msg)

            if inference_msg is not None:
                # Add synthetic z-scores for testing
                df = inference_msg.payload()
                if df is not None:
                    df["mean_abs_z"] = np.random.randn(len(df)).clip(0, 5)
                    inference_msg.payload(df)

                    filtered_msg = filter_module.filter(inference_msg)

                    if filtered_msg is not None:
                        postproc_msg = postproc.process(filtered_msg)
                        if postproc_msg is not None:
                            serializer.serialize(postproc_msg)

        # Verify output file exists
        output_file = tmp_path / "results.csv"
        assert output_file.exists()

        # Verify statistics
        assert filter_module.get_statistics()["total_processed"] > 0
        assert postproc.get_statistics()["total_processed"] > 0
        assert serializer.get_statistics()["total_messages"] > 0


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
