"""
Logging utilities for DFP PoC.

This module provides structured logging setup, log context managers,
and performance timing decorators following NVIDIA Morpheus patterns.

Features:
    - Structured logging with colorlog and structlog
    - Performance timing decorators
    - Context managers for logging
    - Log level management
    - Custom log formatters
"""

import functools
import logging
import logging.config
import sys
import time
from collections.abc import Callable
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import colorlog
import yaml

# Custom log levels
TRACE = 5
VERBOSE = 15
NOTICE = 25
SUCCESS = 35

# Add custom log levels to logging module
logging.addLevelName(TRACE, "TRACE")
logging.addLevelName(VERBOSE, "VERBOSE")
logging.addLevelName(NOTICE, "NOTICE")
logging.addLevelName(SUCCESS, "SUCCESS")


def setup_logging(config_path: str | None = None, level: str | None = None, log_dir: str | None = None):
    """
    Set up logging configuration.

    Args:
        config_path: Path to logging configuration YAML file
        level: Override logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL)
        log_dir: Override log directory

    Example:
        >>> setup_logging(config_path='config/logging.yaml', level='DEBUG')
        >>> logger = logging.getLogger('dfp.training')
        >>> logger.info("Training started")
    """
    # Default config path
    if config_path is None:
        config_path_str = "./dfp-poc/config/logging.yaml"
    else:
        config_path_str = config_path

    config_path_obj = Path(config_path_str)

    # Load logging configuration
    if config_path_obj.exists():
        with open(config_path_obj) as f:
            config = yaml.safe_load(f)

        # Override log directory if specified
        if log_dir:
            for _handler_name, handler_config in config.get("handlers", {}).items():
                if "filename" in handler_config:
                    filename = Path(handler_config["filename"]).name
                    handler_config["filename"] = str(Path(log_dir) / filename)

        # Create log directories
        for handler_config in config.get("handlers", {}).values():
            if "filename" in handler_config:
                log_file = Path(handler_config["filename"])
                log_file.parent.mkdir(parents=True, exist_ok=True)

        # Apply logging configuration
        logging.config.dictConfig(config)

    else:
        # Fallback to basic configuration
        logging.basicConfig(
            level=level or "INFO",
            format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
        logging.warning(f"Logging config not found at {config_path_obj}, using basic config")

    # Override level if specified
    if level:
        logging.getLogger().setLevel(level)


def get_logger(name: str, level: str | None = None) -> logging.Logger:
    """
    Get or create a logger with the specified name.

    Args:
        name: Logger name (typically module name)
        level: Logging level (optional)

    Returns:
        Configured logger instance

    Example:
        >>> logger = get_logger('dfp.training')
        >>> logger.info("Training started")
    """
    logger = logging.getLogger(name)

    if level:
        logger.setLevel(level)

    return logger


def set_level(logger_name: str, level: str):
    """
    Set logging level for a specific logger.

    Args:
        logger_name: Name of the logger
        level: Logging level string

    Example:
        >>> set_level('dfp.training', 'DEBUG')
    """
    logger = logging.getLogger(logger_name)
    logger.setLevel(level)


@contextmanager
def log_context(logger: logging.Logger, message: str, level: str = "INFO"):
    """
    Context manager for logging entry and exit of code blocks.

    Args:
        logger: Logger instance
        message: Message to log
        level: Logging level

    Example:
        >>> logger = get_logger('dfp.training')
        >>> with log_context(logger, "Training model"):
        ...     # Training code here
        ...     pass
        # Logs: "Starting: Training model" and "Finished: Training model"
    """
    log_func = getattr(logger, level.lower())
    log_func(f"Starting: {message}")

    try:
        yield
    except Exception as e:
        logger.error(f"Error during: {message} - {str(e)}")
        raise
    finally:
        log_func(f"Finished: {message}")


@contextmanager
def log_time(logger: logging.Logger, message: str, level: str = "INFO", min_time: float = 0.0):
    """
    Context manager for logging execution time.

    Args:
        logger: Logger instance
        message: Message to log
        level: Logging level
        min_time: Minimum time (seconds) to log (0 to log all)

    Example:
        >>> logger = get_logger('dfp.training')
        >>> with log_time(logger, "Model training", min_time=1.0):
        ...     # Training code here
        ...     time.sleep(2)
        # Logs: "Model training completed in 2.00 seconds"
    """
    start_time = time.time()
    log_func = getattr(logger, level.lower())

    try:
        yield
    finally:
        elapsed = time.time() - start_time
        if elapsed >= min_time:
            log_func(f"{message} completed in {elapsed:.2f} seconds")


def timing_decorator(logger: logging.Logger | None = None, level: str = "INFO", min_time: float = 0.0):
    """
    Decorator for logging function execution time.

    Args:
        logger: Logger instance (uses function's module logger if None)
        level: Logging level
        min_time: Minimum time (seconds) to log

    Returns:
        Decorated function

    Example:
        >>> @timing_decorator(min_time=0.1)
        ... def train_model():
        ...     time.sleep(1)
        ...     return "done"
        >>> result = train_model()
        # Logs: "train_model completed in 1.00 seconds"
    """

    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            # Get logger
            nonlocal logger
            if logger is None:
                logger = logging.getLogger(func.__module__)

            log_func = getattr(logger, level.lower())

            # Time execution
            start_time = time.time()
            try:
                result = func(*args, **kwargs)
                return result
            finally:
                elapsed = time.time() - start_time
                if elapsed >= min_time:
                    log_func(f"{func.__name__} completed in {elapsed:.2f} seconds")

        return wrapper

    return decorator


def log_exception(logger: logging.Logger, exc_info: bool = True):
    """
    Decorator for logging exceptions raised by a function.

    Args:
        logger: Logger instance
        exc_info: Whether to log exception traceback

    Returns:
        Decorated function

    Example:
        >>> logger = get_logger('dfp.training')
        >>> @log_exception(logger)
        ... def train_model():
        ...     raise ValueError("Training failed")
        >>> train_model()  # Logs exception and re-raises
    """

    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            try:
                return func(*args, **kwargs)
            except Exception as e:
                logger.error(f"Exception in {func.__name__}: {str(e)}", exc_info=exc_info)
                raise

        return wrapper

    return decorator


def log_function_call(
    logger: logging.Logger | None = None, level: str = "DEBUG", log_args: bool = False, log_result: bool = False
):
    """
    Decorator for logging function calls with arguments and results.

    Args:
        logger: Logger instance
        level: Logging level
        log_args: Whether to log function arguments
        log_result: Whether to log function return value

    Returns:
        Decorated function

    Example:
        >>> @log_function_call(log_args=True, log_result=True)
        ... def add(a, b):
        ...     return a + b
        >>> result = add(2, 3)
        # Logs: "Calling add(a=2, b=3)" and "add returned 5"
    """

    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            # Get logger
            nonlocal logger
            if logger is None:
                logger = logging.getLogger(func.__module__)

            log_func = getattr(logger, level.lower())

            # Log function call
            if log_args:
                args_str = ", ".join([repr(a) for a in args])
                kwargs_str = ", ".join([f"{k}={repr(v)}" for k, v in kwargs.items()])
                params_str = ", ".join(filter(None, [args_str, kwargs_str]))
                log_func(f"Calling {func.__name__}({params_str})")
            else:
                log_func(f"Calling {func.__name__}")

            # Execute function
            result = func(*args, **kwargs)

            # Log result
            if log_result:
                log_func(f"{func.__name__} returned {repr(result)}")

            return result

        return wrapper

    return decorator


class PerformanceLogger:
    """
    Logger for tracking performance metrics.

    Example:
        >>> perf_logger = PerformanceLogger('dfp.performance')
        >>> perf_logger.start('training')
        >>> time.sleep(1)
        >>> perf_logger.end('training')
        >>> perf_logger.log_metrics()
    """

    def __init__(self, logger_name: str = "dfp.performance"):
        """
        Initialize performance logger.

        Args:
            logger_name: Name of the logger
        """
        self.logger = get_logger(logger_name)
        self.timers: dict[str, float] = {}
        self.metrics: dict[str, Any] = {}

    def start(self, name: str):
        """Start a named timer."""
        self.timers[name] = time.time()

    def end(self, name: str) -> float:
        """
        End a named timer and return elapsed time.

        Returns:
            Elapsed time in seconds
        """
        if name not in self.timers:
            self.logger.warning(f"Timer '{name}' was not started")
            return 0.0

        elapsed = time.time() - self.timers[name]
        self.metrics[f"{name}_time"] = elapsed
        del self.timers[name]

        return elapsed

    def log_metric(self, name: str, value: Any):
        """Log a custom metric."""
        self.metrics[name] = value

    def log_metrics(self, clear: bool = True):
        """
        Log all collected metrics.

        Args:
            clear: Whether to clear metrics after logging
        """
        if self.metrics:
            metrics_str = ", ".join([f"{k}={v}" for k, v in self.metrics.items()])
            self.logger.info(f"Performance metrics: {metrics_str}")

            if clear:
                self.metrics.clear()

    def get_metrics(self) -> dict[str, Any]:
        """Get all collected metrics."""
        return self.metrics.copy()


def create_file_handler(
    filename: str,
    level: str = "INFO",
    formatter: logging.Formatter | None = None,
    max_bytes: int = 10 * 1024 * 1024,  # 10 MB
    backup_count: int = 5,
) -> logging.Handler:
    """
    Create a rotating file handler.

    Args:
        filename: Log file path
        level: Logging level
        formatter: Log formatter (uses default if None)
        max_bytes: Maximum file size before rotation
        backup_count: Number of backup files to keep

    Returns:
        Configured file handler

    Example:
        >>> handler = create_file_handler('data/logs/app.log', level='DEBUG')
        >>> logger = get_logger('myapp')
        >>> logger.addHandler(handler)
    """
    from logging.handlers import RotatingFileHandler

    # Create log directory
    log_path = Path(filename)
    log_path.parent.mkdir(parents=True, exist_ok=True)

    # Create handler
    handler = RotatingFileHandler(filename, maxBytes=max_bytes, backupCount=backup_count, encoding="utf8")

    handler.setLevel(level)

    # Set formatter
    if formatter is None:
        formatter = logging.Formatter(
            "%(asctime)s - %(name)s - %(levelname)s - %(filename)s:%(lineno)d - %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )

    handler.setFormatter(formatter)

    return handler


def create_console_handler(level: str = "INFO", use_color: bool = True) -> logging.Handler:
    """
    Create a console handler with optional color support.

    Args:
        level: Logging level
        use_color: Whether to use colored output

    Returns:
        Configured console handler

    Example:
        >>> handler = create_console_handler(level='DEBUG', use_color=True)
        >>> logger = get_logger('myapp')
        >>> logger.addHandler(handler)
    """
    handler = logging.StreamHandler(sys.stdout)
    handler.setLevel(level)

    if use_color:
        formatter = colorlog.ColoredFormatter(
            "%(log_color)s%(asctime)s - %(name)s - %(levelname)s%(reset)s - %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
            log_colors={
                "TRACE": "cyan",
                "DEBUG": "cyan",
                "VERBOSE": "cyan",
                "INFO": "green",
                "NOTICE": "green",
                "WARNING": "yellow",
                "SUCCESS": "green,bold",
                "ERROR": "red",
                "CRITICAL": "red,bold",
            },
        )
    else:
        formatter = logging.Formatter(
            "%(asctime)s - %(name)s - %(levelname)s - %(message)s", datefmt="%Y-%m-%d %H:%M:%S"
        )

    handler.setFormatter(formatter)

    return handler


def suppress_logger(logger_name: str, level: str = "WARNING"):
    """
    Suppress a verbose third-party logger.

    Args:
        logger_name: Name of the logger to suppress
        level: Minimum level to log (suppresses below this)

    Example:
        >>> suppress_logger('urllib3', level='WARNING')
        >>> suppress_logger('boto3', level='ERROR')
    """
    logger = logging.getLogger(logger_name)
    logger.setLevel(level)


# Convenience functions for common loggers
def get_training_logger() -> logging.Logger:
    """Get the training pipeline logger."""
    return get_logger("dfp.training")


def get_inference_logger() -> logging.Logger:
    """Get the inference pipeline logger."""
    return get_logger("dfp.inference")


def get_preprocessing_logger() -> logging.Logger:
    """Get the preprocessing logger."""
    return get_logger("dfp.preprocessing")


def get_mlflow_logger() -> logging.Logger:
    """Get the MLflow logger."""
    return get_logger("dfp.mlflow")


def get_control_logger() -> logging.Logger:
    """Get the control message logger."""
    return get_logger("dfp.control")
