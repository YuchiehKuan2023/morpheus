"""
Unit tests for mlflow_utils.py module.
Tests MLflowManager and MLflow integration utilities.
"""

import sys
from pathlib import Path
from unittest.mock import Mock, patch

import pytest

# Add project root to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from modules.utils.mlflow_utils import MLflowManager


class TestMLflowManager:
    """Test MLflowManager class."""

    @patch("modules.utils.mlflow_utils.mlflow")
    @patch("modules.utils.mlflow_utils.MlflowClient")
    def test_init_default(self, mock_client, mock_mlflow):
        """Test MLflowManager initialization with defaults."""
        manager = MLflowManager()

        assert manager.tracking_uri == "http://localhost:5001"
        assert manager.experiment_name is None  # No experiment name by default
        mock_mlflow.set_tracking_uri.assert_called_once()

    @patch("modules.utils.mlflow_utils.mlflow")
    def test_init_custom_uri(self, mock_mlflow):
        """Test MLflowManager initialization with custom URI."""
        custom_uri = "http://custom:5001"
        manager = MLflowManager(tracking_uri=custom_uri)

        assert manager.tracking_uri == custom_uri
        mock_mlflow.set_tracking_uri.assert_called_with(custom_uri)

    @patch("modules.utils.mlflow_utils.mlflow")
    @patch("modules.utils.mlflow_utils.MlflowClient")
    def test_get_or_create_experiment_exists(self, mock_client_class, mock_mlflow):
        """Test getting existing experiment."""
        # Mock experiment exists
        mock_client = Mock()
        mock_client.get_experiment_by_name.return_value = Mock(experiment_id="123")
        mock_client_class.return_value = mock_client

        manager = MLflowManager(experiment_name="test_exp")
        exp_id = manager._get_or_create_experiment("test_exp")

        assert exp_id == "123"
        mock_client.get_experiment_by_name.assert_called_with("test_exp")

    @patch("modules.utils.mlflow_utils.mlflow")
    @patch("modules.utils.mlflow_utils.MlflowClient")
    def test_get_or_create_experiment_creates(self, mock_client_class, mock_mlflow):
        """Test creating new experiment."""
        # Mock experiment doesn't exist
        mock_client = Mock()
        mock_client.get_experiment_by_name.return_value = None
        mock_client.create_experiment.return_value = "456"
        mock_client_class.return_value = mock_client

        manager = MLflowManager()
        exp_id = manager._get_or_create_experiment("new_exp")

        assert exp_id == "456"
        mock_client.create_experiment.assert_called_once()

    @patch("modules.utils.mlflow_utils.mlflow")
    @patch("modules.utils.mlflow_utils.MlflowClient")
    def test_start_run(self, mock_client, mock_mlflow):
        """Test starting an MLflow run."""
        mock_run = Mock()
        mock_run.info.run_id = "run123"
        mock_mlflow.start_run.return_value = mock_run

        manager = MLflowManager()

        run = manager.start_run(run_name="test_run")
        assert run is not None
        assert run.info.run_id == "run123"

        mock_mlflow.start_run.assert_called_once()

    @patch("modules.utils.mlflow_utils.mlflow")
    @patch("modules.utils.mlflow_utils.MlflowClient")
    def test_log_params(self, mock_client, mock_mlflow):
        """Test logging parameters."""
        manager = MLflowManager()
        params = {"learning_rate": 0.001, "batch_size": 32}

        manager.log_params(params)

        mock_mlflow.log_params.assert_called_once_with(params)

    @patch("modules.utils.mlflow_utils.mlflow")
    @patch("modules.utils.mlflow_utils.MlflowClient")
    def test_log_metrics(self, mock_client, mock_mlflow):
        """Test logging metrics."""
        manager = MLflowManager()
        metrics = {"loss": 0.5, "accuracy": 0.95}

        manager.log_metrics(metrics)

        mock_mlflow.log_metrics.assert_called_once()

    @patch("modules.utils.mlflow_utils.mlflow_pytorch")
    @patch("modules.utils.mlflow_utils.mlflow")
    @patch("modules.utils.mlflow_utils.MlflowClient")
    def test_log_model(self, mock_client, mock_mlflow, mock_pytorch):
        """Test logging a model."""
        # Create a proper mock model
        import torch

        mock_model = torch.nn.Linear(10, 2)

        manager = MLflowManager()
        manager.log_model(mock_model, "test_model")

        # Should call mlflow.pytorch.log_model
        mock_pytorch.log_model.assert_called_once()

    @patch("modules.utils.mlflow_utils.mlflow_pytorch")
    @patch("modules.utils.mlflow_utils.mlflow")
    @patch("modules.utils.mlflow_utils.MlflowClient")
    def test_load_model_for_user_exists(self, mock_client, mock_mlflow, mock_pytorch):
        """Test loading model for specific user."""
        mock_model = Mock()
        mock_pytorch.load_model.return_value = mock_model

        manager = MLflowManager()
        model = manager.load_model_for_user("user123", "test_model")

        assert model is not None

    @patch("modules.utils.mlflow_utils.mlflow_pytorch")
    @patch("modules.utils.mlflow_utils.mlflow")
    @patch("modules.utils.mlflow_utils.MlflowClient")
    def test_load_model_for_user_fallback(self, mock_client, mock_mlflow, mock_pytorch):
        """Test loading model falls back to generic when user model not found."""
        from mlflow.exceptions import MlflowException

        # First call fails (user model), second succeeds (generic)
        mock_model = Mock()
        mock_pytorch.load_model.side_effect = [MlflowException("Not found"), mock_model]

        manager = MLflowManager()
        model = manager.load_model_for_user("user123", "test_model")

        # Should have tried twice (user then generic)
        assert mock_pytorch.load_model.call_count == 2
        assert model is not None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
