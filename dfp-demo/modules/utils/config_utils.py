"""
Configuration utilities for DFP PoC.

This module provides utilities for loading, merging, and validating YAML configurations
using OmegaConf. It follows NVIDIA Morpheus configuration patterns.

Reference:
    - NVIDIA Morpheus config patterns
    - OmegaConf documentation: https://omegaconf.readthedocs.io/
"""

import os
from pathlib import Path
from typing import Any

from omegaconf import DictConfig, ListConfig, OmegaConf


class ConfigLoader:
    """Configuration loader with OmegaConf support."""

    def __init__(self, config_dir: str | Path | None = None):
        """
        Initialize the configuration loader.

        Args:
            config_dir: Directory containing configuration files.
                       If None, uses './dfp-demo/config'
        """
        if config_dir is None:
            config_dir = Path("./dfp-demo/config")

        self.config_dir = Path(config_dir)

        if not self.config_dir.exists():
            raise FileNotFoundError(f"Configuration directory not found: {self.config_dir}")

    def load(self, config_name: str, overrides: dict[str, Any] | None = None, resolve: bool = True) -> DictConfig:
        """
        Load a configuration file with optional overrides.

        Args:
            config_name: Name of the config file (without .yaml extension)
            overrides: Dictionary of configuration overrides
            resolve: Whether to resolve interpolations

        Returns:
            Loaded configuration as OmegaConf DictConfig

        Example:
            >>> loader = ConfigLoader()
            >>> config = loader.load('training_config', overrides={'training.epochs': 100})
        """
        config_path = self.config_dir / f"{config_name}.yaml"

        if not config_path.exists():
            raise FileNotFoundError(f"Configuration file not found: {config_path}")

        # Load base configuration
        config = OmegaConf.load(config_path)

        # Handle defaults (inheritance from other configs)
        if "defaults" in config and isinstance(config, DictConfig) and isinstance(config.defaults, (list, ListConfig)):
            config = self._merge_defaults(config)

        # Apply overrides
        if overrides:
            override_config = OmegaConf.create(overrides)
            merged = OmegaConf.merge(config, override_config)
            if isinstance(merged, DictConfig):
                config = merged
            else:
                raise TypeError("Config merge resulted in non-DictConfig type")

        # Resolve interpolations (e.g., ${paths.data.root})
        if resolve:
            OmegaConf.resolve(config)

        # Ensure we return DictConfig
        if isinstance(config, DictConfig):
            return config
        else:
            raise TypeError("Config is not a DictConfig")

    def _merge_defaults(self, config: DictConfig) -> DictConfig:
        """
        Merge configuration with its defaults.

        Args:
            config: Configuration with 'defaults' section

        Returns:
            Merged configuration
        """
        defaults = config.pop("defaults")
        merged_config: DictConfig = OmegaConf.create({})  # type: ignore

        # Load and merge each default config
        for default in defaults:
            if isinstance(default, str):
                default_name = default
            elif isinstance(default, dict):
                # Handle structured defaults (Hydra style)
                default_name = list(default.keys())[0]
            else:
                continue

            default_config_path = self.config_dir / f"{default_name}.yaml"
            if default_config_path.exists():
                default_config = OmegaConf.load(default_config_path)
                merge_result = OmegaConf.merge(merged_config, default_config)
                if isinstance(merge_result, DictConfig):
                    merged_config = merge_result

        # Merge the current config on top of defaults
        final_config = OmegaConf.merge(merged_config, config)

        # Ensure we return a DictConfig
        if isinstance(final_config, DictConfig):
            return final_config
        else:
            raise TypeError("Merged config is not a DictConfig")

    def load_all(self, resolve: bool = True) -> dict[str, DictConfig]:
        """
        Load all configuration files in the config directory.

        Args:
            resolve: Whether to resolve interpolations

        Returns:
            Dictionary mapping config names to loaded configs
        """
        configs = {}

        for config_file in self.config_dir.glob("*.yaml"):
            config_name = config_file.stem
            try:
                configs[config_name] = self.load(config_name, resolve=resolve)
            except Exception as e:
                print(f"Warning: Failed to load {config_name}: {e}")

        return configs

    def save(self, config: DictConfig, config_name: str, overwrite: bool = False):
        """
        Save a configuration to a YAML file.

        Args:
            config: Configuration to save
            config_name: Name of the config file (without .yaml extension)
            overwrite: Whether to overwrite existing file
        """
        config_path = self.config_dir / f"{config_name}.yaml"

        if config_path.exists() and not overwrite:
            raise FileExistsError(
                f"Configuration file already exists: {config_path}. Use overwrite=True to replace it."
            )

        with open(config_path, "w") as f:
            OmegaConf.save(config, f)


def load_config(
    config_name: str,
    config_dir: str | Path | None = None,
    overrides: dict[str, Any] | None = None,
    resolve: bool = True,
) -> DictConfig:
    """
    Convenience function to load a configuration file.

    Args:
        config_name: Name of the config file (without .yaml extension)
        config_dir: Directory containing configuration files
        overrides: Dictionary of configuration overrides
        resolve: Whether to resolve interpolations

    Returns:
        Loaded configuration as OmegaConf DictConfig

    Example:
        >>> config = load_config('training_config')
        >>> print(config.training.epochs)
        50
    """
    loader = ConfigLoader(config_dir)
    return loader.load(config_name, overrides, resolve)


def merge_configs(*configs: DictConfig) -> DictConfig:
    """
    Merge multiple configurations.

    Later configurations override earlier ones.

    Args:
        *configs: Variable number of DictConfig objects

    Returns:
        Merged configuration

    Example:
        >>> base = load_config('base_config')
        >>> training = load_config('training_config')
        >>> merged = merge_configs(base, training)
    """
    merged = OmegaConf.merge(*configs)
    if isinstance(merged, DictConfig):
        return merged
    else:
        raise TypeError("Merged config is not a DictConfig")


def validate_config(config: DictConfig, schema: dict[str, Any]) -> bool:
    """
    Validate configuration against a schema.

    Args:
        config: Configuration to validate
        schema: Schema defining required fields and types

    Returns:
        True if valid, raises ValueError if invalid

    Raises:
        ValueError: If configuration is invalid

    Example:
        >>> schema = {'training': {'epochs': int, 'batch_size': int}}
        >>> validate_config(config, schema)
        True
    """

    def _validate_recursive(cfg: Any, sch: dict[str, Any], path: str = ""):
        for key, expected_type in sch.items():
            current_path = f"{path}.{key}" if path else key

            # Check if key exists
            if key not in cfg:
                raise ValueError(f"Missing required configuration key: {current_path}")

            value = cfg[key]

            # Handle nested dictionaries
            if isinstance(expected_type, dict):
                if not isinstance(value, (dict, DictConfig)):
                    raise ValueError(f"Expected dict for {current_path}, got {type(value).__name__}")
                _validate_recursive(value, expected_type, current_path)

            # Handle type checking
            elif not isinstance(value, expected_type):
                raise ValueError(f"Expected {expected_type.__name__} for {current_path}, got {type(value).__name__}")

    _validate_recursive(config, schema)
    return True


def substitute_env_vars(config: DictConfig) -> DictConfig:
    """
    Substitute environment variables in configuration.

    Replaces strings like ${ENV_VAR_NAME} with the value of the environment variable.

    Args:
        config: Configuration to process

    Returns:
        Configuration with environment variables substituted

    Example:
        >>> os.environ['DATA_PATH'] = '/data'
        >>> config = OmegaConf.create({'path': '${ENV:DATA_PATH}/raw'})
        >>> config = substitute_env_vars(config)
        >>> print(config.path)
        /data/raw
    """
    # Ensure config is DictConfig
    if not isinstance(config, DictConfig):
        raise TypeError("Config must be a DictConfig")

    # Register custom resolvers for environment variables
    OmegaConf.register_new_resolver(
        "env", lambda var_name, default=None: os.environ.get(var_name, default), replace=True
    )

    OmegaConf.register_new_resolver(
        "ENV", lambda var_name, default=None: os.environ.get(var_name, default), replace=True
    )

    # Resolve all interpolations
    OmegaConf.resolve(config)

    return config


def to_dict(config: DictConfig | ListConfig) -> dict | list:
    """
    Convert OmegaConf config to plain Python dict/list.

    Args:
        config: OmegaConf configuration

    Returns:
        Plain Python dict or list

    Example:
        >>> config = load_config('training_config')
        >>> python_dict = to_dict(config)
        >>> type(python_dict)
        <class 'dict'>
    """
    result = OmegaConf.to_container(config, resolve=True)
    # to_container can return various types, ensure we return dict or list
    if isinstance(result, (dict, list)):
        return result
    else:
        # If it's a primitive type, wrap it appropriately
        if isinstance(config, DictConfig):
            return {}
        else:
            return []


def from_dict(data: dict | list) -> DictConfig | ListConfig:
    """
    Convert plain Python dict/list to OmegaConf config.

    Args:
        data: Plain Python dict or list

    Returns:
        OmegaConf configuration

    Example:
        >>> data = {'training': {'epochs': 100}}
        >>> config = from_dict(data)
        >>> type(config)
        <class 'omegaconf.dictconfig.DictConfig'>
    """
    return OmegaConf.create(data)


def print_config(config: DictConfig, resolve: bool = True):
    """
    Pretty print configuration to console.

    Args:
        config: Configuration to print
        resolve: Whether to resolve interpolations before printing
    """
    if resolve:
        OmegaConf.resolve(config)

    print(OmegaConf.to_yaml(config))


def get_nested_value(config: DictConfig, key_path: str, default: Any = None) -> Any:
    """
    Get a nested value from configuration using dot notation.

    Args:
        config: Configuration object
        key_path: Dot-separated path (e.g., "training.model.encoder_layers")
        default: Default value if key not found

    Returns:
        Value at key_path or default

    Example:
        >>> config = load_config('training_config')
        >>> epochs = get_nested_value(config, 'training.epochs', default=50)
    """
    try:
        return OmegaConf.select(config, key_path, default=default)
    except Exception:
        return default


def set_nested_value(config: DictConfig, key_path: str, value: Any):
    """
    Set a nested value in configuration using dot notation.

    Args:
        config: Configuration object
        key_path: Dot-separated path (e.g., "training.model.encoder_layers")
        value: Value to set

    Example:
        >>> config = load_config('training_config')
        >>> set_nested_value(config, 'training.epochs', 100)
    """
    OmegaConf.update(config, key_path, value)


# Configuration validation schemas
TRAINING_CONFIG_SCHEMA = {
    "pipeline": {"name": str, "type": str},
    "training": {"epochs": int, "batch_size": int, "learning_rate": float},
    "model": {"encoder_layers": list, "latent_dim": int},
    "dfp": {"userid_column": str, "timestamp_column": str, "feature_columns": list},
    "data": {"raw_dir": str, "train_data": str},
    "mlflow": {"tracking_uri": str, "experiment_name": str},
}

INFERENCE_CONFIG_SCHEMA = {
    "pipeline": {"name": str, "type": str},
    "inference": {"batch_size": int, "anomaly_threshold": dict},
    "dfp": {"userid_column": str, "timestamp_column": str, "feature_columns": list},
    "data": {"raw_dir": str, "inference_data": str},
    "mlflow": {"tracking_uri": str, "experiment_name": str},
}
