"""
Unit tests for modules/utils/config_utils.py

Tests the ConfigLoader class and configuration utility functions.
"""

import sys
import tempfile
from pathlib import Path

import pytest
from omegaconf import DictConfig

# Add project root to Python path
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from modules.utils.config_utils import (  # noqa: E402 - imports after path setup
    ConfigLoader,
    from_dict,
    get_nested_value,
    load_config,
    merge_configs,
    set_nested_value,
    validate_config,
)


@pytest.fixture
def temp_config_dir():
    """Create a temporary directory for test configs."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


@pytest.fixture
def sample_base_config(temp_config_dir):
    """Create a sample base configuration file."""
    config_content = """
project:
  name: "test_dfp_project"
  version: "1.0.0"

environment:
  device: "cpu"
  num_workers: 4

paths:
  data_dir: "./data"
  models_dir: "./models"
"""
    config_path = temp_config_dir / "base_config.yaml"
    config_path.write_text(config_content)
    return config_path


@pytest.fixture
def sample_training_config(temp_config_dir):
    """Create a sample training configuration file."""
    config_content = """
training:
  epochs: 50
  batch_size: 32
  learning_rate: 0.001

model:
  encoder_layers: [128, 64, 32]
  latent_dim: 16
  activation: "relu"

dfp:
  userid_column: "user_id"
  timestamp_column: "timestamp"
  feature_columns:
    - "hour"
    - "dayofweek"
    - "logcount"
"""
    config_path = temp_config_dir / "pipeline.yaml"
    config_path.write_text(config_content)
    return config_path


class TestConfigLoader:
    """Test suite for the ConfigLoader class."""

    def test_init_with_valid_directory(self, temp_config_dir):
        """Test ConfigLoader initialization with valid directory."""
        loader = ConfigLoader(temp_config_dir)
        assert loader.config_dir == temp_config_dir

    def test_init_with_invalid_directory(self):
        """Test ConfigLoader initialization with non-existent directory."""
        with pytest.raises(FileNotFoundError):
            ConfigLoader("/this/path/does/not/exist")

    def test_load_basic_config(self, temp_config_dir, sample_base_config):
        """Test loading a basic configuration file."""
        loader = ConfigLoader(temp_config_dir)
        config = loader.load("base_config")

        assert isinstance(config, DictConfig)
        assert config.project.name == "test_dfp_project"
        assert config.environment.device == "cpu"
        assert config.environment.num_workers == 4

    def test_load_nonexistent_config(self, temp_config_dir):
        """Test loading a config file that doesn't exist."""
        loader = ConfigLoader(temp_config_dir)
        with pytest.raises(FileNotFoundError):
            loader.load("nonexistent_config")

    def test_load_with_overrides(self, temp_config_dir, sample_base_config):
        """Test loading config with override values."""
        loader = ConfigLoader(temp_config_dir)
        overrides = {"environment": {"device": "cuda", "num_workers": 8}}
        config = loader.load("base_config", overrides=overrides)

        assert config.environment.device == "cuda"
        assert config.environment.num_workers == 8
        assert config.project.name == "test_dfp_project"

    def test_load_all_configs(self, temp_config_dir, sample_base_config, sample_training_config):
        """Test loading all config files in directory."""
        loader = ConfigLoader(temp_config_dir)
        all_configs = loader.load_all()

        assert isinstance(all_configs, dict)
        assert "base_config" in all_configs
        assert "pipeline" in all_configs


class TestStandaloneFunctions:
    """Test suite for standalone utility functions."""

    def test_load_config_function(self, temp_config_dir, sample_base_config):
        """Test the standalone load_config function."""
        config = load_config("base_config", config_dir=temp_config_dir)

        assert isinstance(config, DictConfig)
        assert config.project.name == "test_dfp_project"

    def test_merge_configs_function(self):
        """Test merging multiple configurations."""
        config1 = from_dict({"a": 1, "b": 2, "nested": {"x": 10}})
        config2 = from_dict({"b": 3, "c": 4, "nested": {"y": 20}})

        # Ensure both are DictConfig
        assert isinstance(config1, DictConfig)
        assert isinstance(config2, DictConfig)

        merged = merge_configs(config1, config2)

        assert merged.a == 1
        assert merged.b == 3
        assert merged.c == 4

    def test_validate_config_success(self):
        """Test config validation with valid config."""
        config = from_dict({"training": {"epochs": 50, "batch_size": 32}})
        assert isinstance(config, DictConfig)

        schema = {"training": {"epochs": int, "batch_size": int}}

        assert validate_config(config, schema) is True

    def test_validate_config_missing_key(self):
        """Test config validation fails with missing key."""
        config = from_dict({"training": {"epochs": 50}})
        assert isinstance(config, DictConfig)

        schema = {"training": {"epochs": int, "batch_size": int}}

        with pytest.raises(ValueError, match="Missing required configuration key"):
            validate_config(config, schema)

    def test_from_dict_conversion(self):
        """Test converting dict to DictConfig."""
        data = {"key1": "value1", "key2": 42}
        config = from_dict(data)

        assert isinstance(config, DictConfig)
        assert config.key1 == "value1"
        assert config.key2 == 42

    def test_get_nested_value(self):
        """Test getting nested config value with dot notation."""
        config = from_dict({"level1": {"level2": {"level3": "deep_value"}}})
        assert isinstance(config, DictConfig)

        value = get_nested_value(config, "level1.level2.level3")
        assert value == "deep_value"

    def test_set_nested_value(self):
        """Test setting nested config value with dot notation."""
        config = from_dict({"level1": {"level2": {"level3": "original"}}})
        assert isinstance(config, DictConfig)

        set_nested_value(config, "level1.level2.level3", "modified")

        assert config.level1.level2.level3 == "modified"


class TestConfigInterpolation:
    """Test configuration value interpolation."""

    def test_basic_interpolation(self, temp_config_dir):
        """Test basic OmegaConf interpolation."""
        config_content = """
base_dir: "./data"
raw_dir: "${base_dir}/raw"
processed_dir: "${base_dir}/processed"
"""
        config_path = temp_config_dir / "interp_config.yaml"
        config_path.write_text(config_content)

        loader = ConfigLoader(temp_config_dir)
        config = loader.load("interp_config")

        assert config.raw_dir == "./data/raw"
        assert config.processed_dir == "./data/processed"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
