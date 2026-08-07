"""
Utility modules for DFP PoC.

This package contains utility functions and classes for configuration management,
logging, environment detection, and MLflow integration.
"""

from .cached_user_window import CachedUserWindow
from .config_utils import (
    INFERENCE_CONFIG_SCHEMA,
    TRAINING_CONFIG_SCHEMA,
    ConfigLoader,
    from_dict,
    get_nested_value,
    load_config,
    merge_configs,
    print_config,
    set_nested_value,
    substitute_env_vars,
    to_dict,
    validate_config,
)
from .environment_utils import (
    check_memory_available,
    check_system_requirements,
    get_cpu_info,
    get_device,
    get_device_count,
    get_device_memory,
    get_device_name,
    get_memory_info,
    get_platform_info,
    get_pytorch_info,
    is_apple_silicon,
    is_arm_architecture,
    optimize_for_device,
    print_system_info,
)
from .logging_utils import (
    PerformanceLogger,
    get_control_logger,
    get_inference_logger,
    get_logger,
    get_mlflow_logger,
    get_preprocessing_logger,
    get_training_logger,
    log_context,
    log_exception,
    log_time,
    setup_logging,
    timing_decorator,
)
from .mlflow_utils import (
    MLflowManager,
    init_mlflow,
    log_baseline_statistics,
    log_inference_summary,
    log_model_metadata,
    log_training_summary,
)

__all__ = [
    # Config utilities
    "ConfigLoader",
    "load_config",
    "merge_configs",
    "validate_config",
    "substitute_env_vars",
    "to_dict",
    "from_dict",
    "print_config",
    "get_nested_value",
    "set_nested_value",
    "TRAINING_CONFIG_SCHEMA",
    "INFERENCE_CONFIG_SCHEMA",
    # Environment utilities
    "get_device",
    "get_device_count",
    "get_device_name",
    "get_device_memory",
    "get_platform_info",
    "is_arm_architecture",
    "is_apple_silicon",
    "get_cpu_info",
    "get_memory_info",
    "check_memory_available",
    "get_pytorch_info",
    "print_system_info",
    "optimize_for_device",
    "check_system_requirements",
    # Logging utilities
    "setup_logging",
    "get_logger",
    "log_context",
    "log_time",
    "timing_decorator",
    "log_exception",
    "PerformanceLogger",
    "get_training_logger",
    "get_inference_logger",
    "get_preprocessing_logger",
    "get_mlflow_logger",
    "get_control_logger",
    # MLflow utilities
    "MLflowManager",
    "init_mlflow",
    "log_model_metadata",
    "log_baseline_statistics",
    "log_training_summary",
    "log_inference_summary",
    # Cached user window
    "CachedUserWindow",
]
