"""
Pytest Configuration and Shared Fixtures

Provides reusable fixtures for all test modules, including:
- Sample data generators (training/inference)
- Configuration objects (base/training/inference)
- Mock MLflow client
- Temporary directories
- Sample DataFrames with proper schema

Follows NVIDIA Morpheus DFP testing patterns.

Author: Tomasz Zabek <tzabek@deloitte.co.uk>
Date: 2025-11-11
"""

import sys
import tempfile
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, Mock

import numpy as np
import pandas as pd
import pytest
import yaml

# ---------------------------------------------------------------------------
# CI stubs for optional runtime dependencies
#
# psycopg2 is not installed in the CI test environment (no Postgres available).
# Stub it out before any source module is imported so that module-level
# ``import psycopg2`` statements (e.g. in labeling_worker, batch_labeler,
# ai_orchestrator) don't cause collection/import errors.
# The stubs are plain MagicMock objects — they satisfy attribute lookups and
# callable checks but will raise if actually called, which is the desired
# behaviour for unit tests that mock the DB layer explicitly.
# ---------------------------------------------------------------------------
for _mod_name in ("psycopg2", "psycopg2.extras", "psycopg2.extensions", "psycopg2.pool"):
    if _mod_name not in sys.modules:
        sys.modules[_mod_name] = MagicMock()


# ============================================================================
# Directory and Path Fixtures
# ============================================================================


@pytest.fixture(scope="session")
def project_root() -> Path:
    """Get the project root directory."""
    return Path(__file__).parent.parent


@pytest.fixture(scope="session")
def config_dir(project_root: Path) -> Path:
    """Get the config directory."""
    return project_root / "config"


@pytest.fixture(scope="session")
def data_dir(project_root: Path) -> Path:
    """Get the data directory."""
    return project_root / "data"


@pytest.fixture
def temp_dir():
    """Create a temporary directory for test outputs."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


@pytest.fixture
def temp_cache_dir(temp_dir: Path) -> Path:
    """Create a temporary cache directory."""
    cache_dir = temp_dir / "cache"
    cache_dir.mkdir(parents=True, exist_ok=True)
    return cache_dir


@pytest.fixture
def temp_output_dir(temp_dir: Path) -> Path:
    """Create a temporary output directory."""
    output_dir = temp_dir / "output"
    output_dir.mkdir(parents=True, exist_ok=True)
    return output_dir


# ============================================================================
# Configuration Fixtures
# ============================================================================


@pytest.fixture(scope="session")
def base_config(config_dir: Path) -> dict[str, Any]:
    """Load base configuration."""
    config_path = config_dir / "base_config.yaml"
    if not config_path.exists():
        pytest.skip(f"Base config not found: {config_path}")

    with open(config_path) as f:
        return yaml.safe_load(f)


@pytest.fixture(scope="session")
def training_config(config_dir: Path) -> dict[str, Any]:
    """Load training configuration."""
    config_path = config_dir / "pipeline.yaml"
    if not config_path.exists():
        pytest.skip(f"Training config not found: {config_path}")

    with open(config_path) as f:
        return yaml.safe_load(f)


@pytest.fixture(scope="session")
def inference_config(config_dir: Path) -> dict[str, Any]:
    """Load inference configuration."""
    config_path = config_dir / "inference_config.yaml"
    if not config_path.exists():
        pytest.skip(f"Inference config not found: {config_path}")

    with open(config_path) as f:
        return yaml.safe_load(f)


@pytest.fixture(scope="session")
def mlflow_config(config_dir: Path) -> dict[str, Any]:
    """Load MLflow configuration."""
    config_path = config_dir / "mlflow.yaml"
    if not config_path.exists():
        pytest.skip(f"MLflow config not found: {config_path}")

    with open(config_path) as f:
        return yaml.safe_load(f)


@pytest.fixture(scope="session")
def feature_schema(config_dir: Path) -> dict[str, Any]:
    """Load feature schema."""
    schema_path = config_dir / "feature_schema.yaml"
    if not schema_path.exists():
        pytest.skip(f"Feature schema not found: {schema_path}")

    with open(schema_path) as f:
        return yaml.safe_load(f)


@pytest.fixture
def minimal_training_config(temp_dir: Path) -> dict[str, Any]:
    """Create a minimal training configuration for testing."""
    config = {
        "pipeline": {"name": "dfp_training_test", "type": "training"},
        "dfp": {
            "userid_column": "username",
            "timestamp_column": "timestamp",
            "feature_columns": ["logcount", "locincrement"],
            "preprocessing": {"schema_file": "config/feature_schema.yaml", "fill_missing": True, "normalize": True},
            "rolling_window": {"min_history": 50, "mode": "aggregate", "window_size": "24H", "slide_interval": "12H"},
            "data_prep": {
                "feature_columns": [],
                "exclude_columns": ["username", "timestamp", "_batch_id", "_row_hash"],
            },
        },
        "model": {
            "encoder_layers": [128, 64],
            "decoder_layers": [128],
            "activation": "relu",
            "swap_probability": 0.15,
            "lr": 0.001,
            "lr_decay": 0.99,
            "batch_size": 32,
            "verbose": False,
        },
        "training": {
            "epochs": 5,
            "min_training_samples": 50,
            "validation_size": 0.1,
            "train_data_strategy": "aggregate",
        },
        "data": {"file_batch_period": "D", "sampling": 1},
        "mlflow": {
            "tracking_uri": "http://localhost:5001",
            "experiment_name": "dfp/training/test",
            "model_name_template": "DFP-{user_id}",
            "register_model": False,
        },
    }

    config_path = temp_dir / "pipeline.yaml"
    with open(config_path, "w") as f:
        yaml.dump(config, f)

    return config


@pytest.fixture
def minimal_inference_config(temp_dir: Path) -> dict[str, Any]:
    """Create a minimal inference configuration for testing."""
    config = {
        "pipeline": {"name": "dfp_inference_test", "type": "inference"},
        "dfp": {
            "userid_column": "username",
            "timestamp_column": "timestamp",
            "feature_columns": ["logcount", "locincrement"],
            "preprocessing": {"schema_file": "config/feature_schema.yaml", "fill_missing": True, "normalize": True},
            "rolling_window": {"min_history": 50, "mode": "aggregate", "window_size": "24H"},
            "data_prep": {
                "feature_columns": [],
                "exclude_columns": ["username", "timestamp", "_batch_id", "_row_hash"],
            },
        },
        "inference": {"fallback_username": "generic_user", "timestamp_column": "timestamp"},
        "detection": {"threshold": 3.0, "filter_source": "mean_abs_z"},
        "output": {"format": "json", "destination": "file"},
        "mlflow": {
            "tracking_uri": "http://localhost:5001",
            "experiment_name": "dfp/inference/test",
            "model_name_template": "DFP-{user_id}",
        },
    }

    config_path = temp_dir / "inference_config.yaml"
    with open(config_path, "w") as f:
        yaml.dump(config, f)

    return config


# ============================================================================
# Sample Data Fixtures
# ============================================================================


@pytest.fixture
def sample_users() -> list[str]:
    """Generate sample user IDs."""
    return [f"user{i:03d}" for i in range(1, 6)]  # user001 to user005


@pytest.fixture
def sample_cities() -> list[str]:
    """Generate sample UK cities."""
    return ["London", "Manchester", "Birmingham", "Leeds", "Glasgow"]


@pytest.fixture
def sample_timestamp() -> datetime:
    """Generate a base timestamp for testing."""
    return datetime(2025, 1, 1, 9, 0, 0)


@pytest.fixture
def sample_events(sample_users: list[str], sample_cities: list[str], sample_timestamp: datetime) -> pd.DataFrame:
    """
    Generate sample event data for testing.

    Returns a DataFrame with 100 events across 5 users.
    """
    np.random.seed(42)

    events = []
    for _ in range(100):
        user = np.random.choice(sample_users)
        city = np.random.choice(sample_cities)

        event = {
            "username": user,
            "timestamp": sample_timestamp.isoformat(),
            "city": city,
            "country": "United Kingdom",
            "logcount": np.random.randint(1, 20),
            "locincrement": np.random.randint(0, 5),
            "appincrement": np.random.randint(0, 3),
            "new_city_counter": np.random.randint(0, 2),
            "new_country_counter": 0,
        }

        events.append(event)
        sample_timestamp += timedelta(minutes=np.random.randint(5, 30))

    df = pd.DataFrame(events)
    df["timestamp"] = pd.to_datetime(df["timestamp"])
    return df


@pytest.fixture
def sample_training_data(sample_events: pd.DataFrame, temp_dir: Path) -> Path:
    """
    Create sample training data file.

    Saves sample events to a JSON file in temp directory.
    """
    data_file = temp_dir / "training_data.json"
    sample_events.to_json(data_file, orient="records", date_format="iso")
    return data_file


@pytest.fixture
def sample_inference_data(sample_events: pd.DataFrame, temp_dir: Path) -> Path:
    """
    Create sample inference data file.

    Uses a subset of events for inference testing.
    """
    data_file = temp_dir / "inference_data.json"
    # Use last 20 events for inference
    sample_events.tail(20).to_json(data_file, orient="records", date_format="iso")
    return data_file


@pytest.fixture
def sample_preprocessed_data(sample_events: pd.DataFrame) -> pd.DataFrame:
    """
    Generate sample preprocessed data with derived features.

    Simulates output from DFPPreprocessing stage with NVIDIA DFP Azure AD schema.
    Includes all 9 required feature columns from pipeline.yaml:
    - appDisplayName, clientAppUsed, deviceDetailbrowser
    - deviceDetaildisplayName, deviceDetailoperatingSystem, statusfailureReason
    - appincrement, locincrement, logcount
    """
    df = sample_events.copy()

    # NVIDIA DFP Azure AD feature columns (columns_ae_azure.txt)
    # These are required by pipeline.yaml
    import numpy as np

    np.random.seed(42)

    # Add Azure AD specific columns with realistic values
    apps = ["Office 365", "SharePoint", "Teams", "OneDrive", "Exchange"]
    clients = ["Browser", "Mobile App", "Desktop App", "Sync Client"]
    browsers = ["Chrome", "Firefox", "Safari", "Edge", "Unknown"]
    os_types = ["Windows 10", "MacOS", "iOS", "Android", "Windows 11"]
    failure_reasons = [None, "InvalidPassword", "AccountLocked", "MFARequired", "ConditionalAccessBlocked"]

    df["appDisplayName"] = np.random.choice(apps, size=len(df))
    df["clientAppUsed"] = np.random.choice(clients, size=len(df))
    df["deviceDetailbrowser"] = np.random.choice(browsers, size=len(df))
    df["deviceDetaildisplayName"] = [f"DEVICE-{i % 10:03d}" for i in range(len(df))]
    df["deviceDetailoperatingSystem"] = np.random.choice(os_types, size=len(df))
    df["statusfailureReason"] = np.random.choice(failure_reasons, size=len(df))

    # Ensure numeric columns exist (sample_events already has these)
    # appincrement, locincrement, logcount already in sample_events

    # Add derived time features (optional, used in some tests)
    df["hour_of_day"] = pd.to_datetime(df["timestamp"]).dt.hour
    df["day_of_week"] = pd.to_datetime(df["timestamp"]).dt.dayofweek
    df["is_weekend"] = df["day_of_week"].isin([5, 6]).astype(int)

    # Add travel_speed_kmph feature (required by trainer config)
    df["travel_speed_kmph"] = 0.0  # Default to 0 (no travel)

    # Add row identifiers (internal use)
    df["_batch_id"] = 0
    df["_row_hash"] = [f"hash_{i}" for i in range(len(df))]

    return df


@pytest.fixture
def sample_windowed_data(sample_preprocessed_data: pd.DataFrame) -> dict[str, pd.DataFrame]:
    """
    Generate sample windowed data per user.

    Simulates output from RollingWindow stage.
    """
    windowed = {}
    for user in sample_preprocessed_data["username"].unique():
        user_data = sample_preprocessed_data[sample_preprocessed_data["username"] == user].copy()
        windowed[user] = user_data

    return windowed


# ============================================================================
# Mock Fixtures
# ============================================================================


@pytest.fixture
def mock_mlflow_client():
    """Create a mock MLflow tracking client."""
    mock_client = MagicMock()

    # Mock experiment
    mock_client.get_experiment_by_name.return_value = Mock(experiment_id="1")
    mock_client.create_experiment.return_value = "1"

    # Mock run
    mock_run = Mock()
    mock_run.info.run_id = "test_run_123"
    mock_client.create_run.return_value = mock_run

    # Mock model registration
    mock_client.log_param = Mock()
    mock_client.log_metric = Mock()
    mock_client.log_artifact = Mock()

    return mock_client


@pytest.fixture
def mock_mlflow_manager(mock_mlflow_client):
    """Create a mock MLflowManager."""
    mock_manager = MagicMock()
    mock_manager.tracking_uri = "http://localhost:5001"
    mock_manager.experiment_name = "dfp/test"
    mock_manager.client = mock_mlflow_client

    # Mock model loading
    mock_manager.load_model.return_value = MagicMock()

    return mock_manager


@pytest.fixture
def mock_dfencoder_model():
    """Create a mock dfencoder AutoEncoder model."""
    mock_model = MagicMock()

    # Mock fit method
    mock_model.fit.return_value = None

    # Mock predict method (reconstruction)
    def mock_predict(X):
        # Return reconstructed data with slight noise
        return X + np.random.normal(0, 0.1, X.shape)

    mock_model.predict = mock_predict

    # Mock get_anomaly_score method
    def mock_get_anomaly_score(X):
        # Return random reconstruction errors
        return np.random.uniform(0, 1, len(X))

    mock_model.get_anomaly_score = mock_get_anomaly_score

    return mock_model


# ============================================================================
# Module-Specific Fixtures
# ============================================================================


@pytest.fixture
def sample_file_list(temp_dir: Path, sample_events: pd.DataFrame) -> list[Path]:
    """
    Create a list of sample data files.

    Simulates file batcher input with multiple files.
    """
    files = []
    chunk_size = 25

    for i in range(4):
        file_path = temp_dir / f"data_batch_{i}.json"
        start_idx = i * chunk_size
        end_idx = start_idx + chunk_size

        chunk = sample_events.iloc[start_idx:end_idx]
        chunk.to_json(file_path, orient="records", date_format="iso")
        files.append(file_path)

    return files


@pytest.fixture
def sample_user_splits(sample_preprocessed_data: pd.DataFrame) -> dict[str, pd.DataFrame]:
    """
    Generate sample user splits.

    Simulates output from UserSplitter stage.
    """
    splits = {}
    for user in sample_preprocessed_data["username"].unique():
        user_data = sample_preprocessed_data[sample_preprocessed_data["username"] == user].copy()
        splits[user] = user_data

    return splits


# ============================================================================
# Utility Fixtures
# ============================================================================


@pytest.fixture
def capture_logs(caplog):
    """Capture log messages for testing."""
    import logging

    caplog.set_level(logging.INFO)
    return caplog


@pytest.fixture
def suppress_warnings():
    """Suppress warnings during tests."""
    import warnings

    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        yield


# ============================================================================
# Pytest Configuration
# ============================================================================


def pytest_configure(config):
    """Configure pytest with custom markers."""
    config.addinivalue_line("markers", "slow: marks tests as slow (deselect with '-m \"not slow\"')")
    config.addinivalue_line("markers", "integration: marks tests as integration tests")
    config.addinivalue_line("markers", "unit: marks tests as unit tests")
    config.addinivalue_line("markers", "requires_mlflow: marks tests that require MLflow server")
    config.addinivalue_line("markers", "requires_data: marks tests that require real data files")


def pytest_collection_modifyitems(config, items):
    """Modify test collection to add markers based on location."""
    for item in items:
        # Add unit marker to test_modules tests
        if "test_modules" in str(item.fspath):
            item.add_marker(pytest.mark.unit)

        # Add integration marker to pipeline tests
        if "test_training_pipeline" in str(item.fspath) or "test_inference_pipeline" in str(item.fspath):
            item.add_marker(pytest.mark.integration)
