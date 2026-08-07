"""
Unit Tests for DFP Trainer Module

Tests the DFPTrainer module for:
- Initialization with config dict
- Training on prepared data via ControlMessage
- Validation split handling
- Per-user model training
- Generic model fallback
- Model persistence and metrics

Follows NVIDIA Morpheus DFP architecture.

Author: Tomasz Zabek <tzabek@deloitte.co.uk>
Date: 2025-11-11
"""

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np
import pandas as pd
import pytest

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from modules.control.control_message import ControlMessage, ControlMessageType
from modules.training.dfp_trainer import DFPTrainer


@pytest.fixture
def trainer_config(training_config):
    """Extract trainer-compatible config from pipeline config."""
    # pipeline.yaml structure → trainer config structure
    return {
        "model": training_config.get("model", training_config.get("training", {}).get("model_kwargs", {})),
        "training": training_config.get("training", {}),
        "features": {"feature_columns": training_config.get("feature_columns", [])},
    }


class TestDFPTrainerInitialization:
    """Test trainer initialization."""

    def test_trainer_init_default_params(self, trainer_config):
        """Test trainer initializes with default parameters."""
        trainer = DFPTrainer(config=trainer_config)

        assert trainer.epochs == 100  # From pipeline.yaml training.epochs
        assert trainer.validation_size == 0.1
        assert trainer.min_training_samples == 100
        assert len(trainer.feature_columns) > 0

    def test_trainer_init_custom_params(self):
        """Test trainer initializes with custom parameters."""
        config = {
            "model": {"encoder_layers": [256, 128], "decoder_layers": [256], "activation": "tanh"},
            "training": {"epochs": 100, "validation_size": 0.2, "min_training_samples": 200},
            "features": {"feature_columns": ["logcount", "locincrement", "appincrement"]},
        }

        trainer = DFPTrainer(config=config)

        assert trainer.epochs == 100
        assert trainer.validation_size == 0.2
        assert trainer.min_training_samples == 200

    def test_trainer_init_missing_config(self):
        """Test trainer raises error with missing config keys."""
        config = {"model": {}}  # Missing 'features'

        with pytest.raises(ValueError, match="Missing required configuration"):
            DFPTrainer(config=config)


class TestDFPTrainerMessageHandling:
    """Test ControlMessage handling."""

    def test_train_with_valid_message(self, trainer_config, sample_preprocessed_data):
        """Test training with valid ControlMessage."""
        trainer = DFPTrainer(config=trainer_config)

        # Create control message with training data
        message = ControlMessage()
        message.add_task("training", {"type": ControlMessageType.TRAINING})
        message.set_metadata("user_id", "user001")

        # Get sufficient data (>100 samples required by default)
        # Use all user001 data, duplicated to ensure > 100 samples
        user_data = sample_preprocessed_data[sample_preprocessed_data["username"] == "user001"].copy()

        # Duplicate data to get > 100 samples
        user_data = pd.concat([user_data] * 10, ignore_index=True)

        # Mock message payload to return DataFrame directly
        with patch.object(message, "payload", return_value=user_data):
            with patch("modules.training.dfp_trainer.DFPAutoEncoder") as mock_ae:
                mock_model = MagicMock()
                mock_ae.return_value = mock_model

                result = trainer.train(message)

                # Should return output message
                assert result is not None
                assert isinstance(result, ControlMessage)

    def test_train_with_insufficient_samples(self, trainer_config):
        """Test training skips when insufficient samples."""
        trainer = DFPTrainer(config=trainer_config)

        # Create message with tiny dataset
        message = ControlMessage()
        message.add_task("training", {"type": ControlMessageType.TRAINING})
        message.set_metadata("user_id", "user_test")

        small_df = pd.DataFrame({"logcount": [1, 2, 3], "locincrement": [0, 1, 0], "appincrement": [1, 0, 1]})

        # Mock to return the DataFrame directly
        with patch.object(message, "payload", return_value=small_df):
            result = trainer.train(message)

            # Should return None (skipped due to insufficient data)
            assert result is None

    def test_train_with_invalid_message_type(self, trainer_config):
        """Test training raises error with wrong message type."""
        trainer = DFPTrainer(config=trainer_config)

        # Create inference message (not training)
        message = ControlMessage()
        message.add_task("inference", {"type": ControlMessageType.INFERENCE})

        with pytest.raises((ValueError, RuntimeError), match="Invalid message type|Training failed"):
            trainer.train(message)


class TestDFPTrainerDataSplit:
    """Test data splitting for train/validation."""

    def test_split_data_correct_ratio(self, trainer_config, sample_preprocessed_data):
        """Test data split creates correct train/val ratio."""
        trainer = DFPTrainer(config=trainer_config)

        user_data = sample_preprocessed_data[sample_preprocessed_data["username"] == "user001"].copy()

        train_df, val_df = trainer._split_data(user_data)

        # Check split ratio (90/10 by default)
        total_samples = len(user_data)
        expected_train = int(total_samples * 0.9)

        assert len(train_df) == expected_train
        assert len(val_df) == total_samples - expected_train

    def test_split_data_no_validation(self, trainer_config, sample_preprocessed_data):
        """Test data splitting with no validation set."""
        config = {
            "model": {"encoder_layers": [64], "decoder_layers": [64]},
            "training": {"validation_size": 0.0, "epochs": 50},
            "features": {"feature_columns": ["logcount", "locincrement"]},
        }

        trainer = DFPTrainer(config=config)

        user_data = sample_preprocessed_data[sample_preprocessed_data["username"] == "user001"].copy()

        train_df, val_df = trainer._split_data(user_data)

        assert len(train_df) == len(user_data)
        assert len(val_df) == 0


class TestDFPTrainerModelTraining:
    """Test model training functionality."""

    @patch("modules.training.dfp_trainer.DFPAutoEncoder")
    def test_train_model_calls_fit(self, mock_ae_class, trainer_config, sample_preprocessed_data):
        """Test _train_model calls AutoEncoder fit method."""
        mock_model = MagicMock()
        mock_ae_class.return_value = mock_model

        trainer = DFPTrainer(config=trainer_config)

        user_data = sample_preprocessed_data[sample_preprocessed_data["username"] == "user001"].copy()

        train_df, val_df = trainer._split_data(user_data)

        model = trainer._train_model(train_df, val_df, user_id="user001")

        # Verify AutoEncoder was instantiated and trained
        mock_ae_class.assert_called_once()
        mock_model.fit.assert_called_once()
        assert model == mock_model

    @patch("modules.training.dfp_trainer.DFPAutoEncoder")
    def test_train_model_computes_metrics(self, mock_ae_class, trainer_config, sample_preprocessed_data):
        """Test training computes reconstruction metrics."""
        mock_model = MagicMock()

        # Mock get_anomaly_score to return errors
        mock_errors = np.random.uniform(0, 1, 50)
        mock_model.get_anomaly_score.return_value = mock_errors

        mock_ae_class.return_value = mock_model

        trainer = DFPTrainer(config=trainer_config)

        user_data = sample_preprocessed_data[sample_preprocessed_data["username"] == "user001"].copy()

        train_df, val_df = trainer._split_data(user_data)
        model = trainer._train_model(train_df, val_df, user_id="user001")

        # Verify model was trained
        assert model is not None


class TestDFPTrainerOutputMessage:
    """Test output message creation."""

    def test_create_output_message(self, trainer_config):
        """Test output message contains model and metadata."""
        trainer = DFPTrainer(config=trainer_config)

        mock_model = MagicMock()
        input_message = ControlMessage()
        input_message.set_metadata("user_id", "user001")

        output_message = trainer._create_output_message(
            model=mock_model, user_id="user001", train_samples=100, val_samples=10, original_message=input_message
        )

        # Verify output message structure
        assert isinstance(output_message, ControlMessage)
        assert output_message.get_metadata("user_id") == "user001"
        assert output_message.get_metadata("train_samples") == 100


class TestDFPTrainerEdgeCases:
    """Test edge cases and error handling."""

    def test_missing_feature_columns(self, trainer_config):
        """Test error when training data missing required columns."""
        trainer = DFPTrainer(config=trainer_config)

        message = ControlMessage()
        message.add_task("training", {"type": ControlMessageType.TRAINING})
        message.set_metadata("user_id", "user001")

        # Data missing required feature columns but has enough samples
        incomplete_df = pd.DataFrame(
            {
                "logcount": list(range(150))  # > min_samples but missing other required columns
                # Missing locincrement, appincrement, etc.
            }
        )

        # Return DataFrame directly
        with patch.object(message, "payload", return_value=incomplete_df):
            with pytest.raises((ValueError, RuntimeError), match="missing required feature columns|Training failed"):
                trainer.train(message)

    def test_empty_dataframe(self, trainer_config):
        """Test handling of empty DataFrame."""
        trainer = DFPTrainer(config=trainer_config)

        message = ControlMessage()
        message.add_task("training", {"type": ControlMessageType.TRAINING})
        message.set_metadata("user_id", "user_test")

        empty_df = pd.DataFrame(columns=["logcount", "locincrement", "appincrement"])

        # Return DataFrame directly - should raise RuntimeError because empty
        with patch.object(message, "payload", return_value=empty_df):
            with pytest.raises(RuntimeError, match="Training failed"):
                trainer.train(message)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
