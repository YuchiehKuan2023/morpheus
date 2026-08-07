"""
Tests for Control Message Module

Comprehensive test suite for NVIDIA Morpheus DFP-aligned control message functionality.

Test Coverage:
    - ControlMessage initialization and configuration
    - Task management (add, has, remove, get)
    - Metadata operations (set, get, has, list)
    - Payload handling
    - Timestamp tracking
    - Message copying
    - MessageRouter routing logic
    - Validation and error handling
    - Edge cases and malformed messages

Reference:
    NVIDIA tests: tests/morpheus/messages/test_control_message.py
"""

from datetime import datetime, timedelta

import pandas as pd
import pytest

from modules.control.control_message import (
    ControlMessage,
    ControlMessageType,
    create_inference_message,
    create_training_message,
)
from modules.control.message_router import MessageRouter, route_message

# ============================================================================
# Fixtures
# ============================================================================


@pytest.fixture
def sample_dataframe():
    """Create a sample DataFrame for testing."""
    return pd.DataFrame(
        {
            "feature1": [1, 2, 3, 4, 5],
            "feature2": [10, 20, 30, 40, 50],
            "timestamp": pd.date_range("2024-01-01", periods=5, freq="D"),
        }
    )


@pytest.fixture
def training_task_properties():
    """Training task properties."""
    return {"epochs": 50, "validation_size": 0.1, "learning_rate": 0.001}


@pytest.fixture
def inference_task_properties():
    """Inference task properties."""
    return {"model_name": "DFP-alice", "threshold": 3.0}


# ============================================================================
# TestControlMessageInitialization
# ============================================================================


class TestControlMessageInitialization:
    """Test ControlMessage initialization."""

    def test_empty_initialization(self):
        """Test creating an empty control message."""
        msg = ControlMessage()

        assert msg.task_type() == ControlMessageType.NONE
        assert msg.payload() is None
        assert msg.get_metadata() == {}
        assert msg.get_tasks() == {}
        assert msg.get_timestamps() == {}

    def test_initialization_with_dict_config(self):
        """Test initialization with dictionary configuration."""
        config = {
            "metadata": {"user_id": "alice", "batch_id": "2024-01-15"},
            "tasks": [{"type": "training", "properties": {"epochs": 50}}],
            "type": "training",
        }

        msg = ControlMessage(config)

        assert msg.task_type() == ControlMessageType.TRAINING
        assert msg.get_metadata("user_id") == "alice"
        assert msg.get_metadata("batch_id") == "2024-01-15"
        assert msg.has_task("training")

    def test_initialization_from_another_message(self):
        """Test copying from another ControlMessage."""
        original = ControlMessage()
        original.set_metadata("user_id", "bob")
        original.add_task("inference", {"model_name": "DFP-bob"})

        copy = ControlMessage(original)

        assert copy.get_metadata("user_id") == "bob"
        assert copy.has_task("inference")
        assert copy is not original

    def test_initialization_with_invalid_type(self):
        """Test initialization with invalid argument type."""
        with pytest.raises(ValueError, match="Invalid argument type"):
            ControlMessage("invalid_string")  # type: ignore[arg-type]


# ============================================================================
# TestTaskManagement
# ============================================================================


class TestTaskManagement:
    """Test task management operations."""

    def test_add_task(self, training_task_properties):
        """Test adding a task."""
        msg = ControlMessage()
        msg.add_task("training", training_task_properties)

        assert msg.has_task("training")
        assert msg.task_type() == ControlMessageType.TRAINING

    def test_add_multiple_tasks_same_type(self):
        """Test adding multiple tasks of the same type."""
        msg = ControlMessage()
        msg.add_task("training", {"epochs": 50})
        msg.add_task("training", {"epochs": 100})

        tasks = msg.get_tasks()
        assert len(tasks["training"]) == 2

    def test_add_different_task_types_raises_error(self):
        """Test that mixing task types raises ValueError."""
        msg = ControlMessage()
        msg.add_task("training", {"epochs": 50})

        with pytest.raises(ValueError, match="Cannot mix different types"):
            msg.add_task("inference", {"model_name": "test"})

    def test_has_task_returns_false_for_nonexistent(self):
        """Test has_task returns False for non-existent task."""
        msg = ControlMessage()
        assert not msg.has_task("training")
        assert not msg.has_task("inference")

    def test_remove_task(self, training_task_properties):
        """Test removing a task."""
        msg = ControlMessage()
        msg.add_task("training", training_task_properties)

        task = msg.remove_task("training")

        assert task == training_task_properties
        assert not msg.has_task("training")

    def test_remove_task_fifo_order(self):
        """Test that tasks are removed in FIFO order."""
        msg = ControlMessage()
        msg.add_task("training", {"epochs": 50})
        msg.add_task("training", {"epochs": 100})

        task1 = msg.remove_task("training")
        task2 = msg.remove_task("training")

        assert task1["epochs"] == 50
        assert task2["epochs"] == 100

    def test_remove_nonexistent_task_raises_error(self):
        """Test removing non-existent task raises ValueError."""
        msg = ControlMessage()

        with pytest.raises(ValueError, match="No task of type"):
            msg.remove_task("training")

    def test_get_tasks(self):
        """Test getting all tasks."""
        msg = ControlMessage()
        msg.add_task("training", {"epochs": 50})
        msg.add_task("training", {"epochs": 100})

        tasks = msg.get_tasks()

        assert "training" in tasks
        assert len(tasks["training"]) == 2


# ============================================================================
# TestMetadataOperations
# ============================================================================


class TestMetadataOperations:
    """Test metadata operations."""

    def test_set_metadata(self):
        """Test setting metadata."""
        msg = ControlMessage()
        msg.set_metadata("user_id", "alice")
        msg.set_metadata("batch_id", "2024-01-15")

        assert msg.get_metadata("user_id") == "alice"
        assert msg.get_metadata("batch_id") == "2024-01-15"

    def test_has_metadata(self):
        """Test checking metadata existence."""
        msg = ControlMessage()
        msg.set_metadata("user_id", "alice")

        assert msg.has_metadata("user_id")
        assert not msg.has_metadata("nonexistent")

    def test_get_metadata_with_default(self):
        """Test getting metadata with default value."""
        msg = ControlMessage()

        value = msg.get_metadata("nonexistent", "default_value")

        assert value == "default_value"

    def test_get_all_metadata(self):
        """Test getting all metadata."""
        msg = ControlMessage()
        msg.set_metadata("user_id", "alice")
        msg.set_metadata("batch_id", "2024-01-15")

        metadata = msg.get_metadata()

        assert metadata == {"user_id": "alice", "batch_id": "2024-01-15"}

    def test_list_metadata(self):
        """Test listing metadata keys."""
        msg = ControlMessage()
        msg.set_metadata("user_id", "alice")
        msg.set_metadata("batch_id", "2024-01-15")

        keys = msg.list_metadata()

        assert keys == ["batch_id", "user_id"]  # Sorted


# ============================================================================
# TestPayloadHandling
# ============================================================================


class TestPayloadHandling:
    """Test payload handling."""

    def test_set_and_get_payload(self, sample_dataframe):
        """Test setting and getting payload."""
        msg = ControlMessage()
        msg.payload(sample_dataframe)

        retrieved = msg.payload()

        assert retrieved is not None
        pd.testing.assert_frame_equal(retrieved, sample_dataframe)

    def test_payload_initially_none(self):
        """Test that payload is initially None."""
        msg = ControlMessage()

        assert msg.payload() is None


# ============================================================================
# TestTimestampTracking
# ============================================================================


class TestTimestampTracking:
    """Test timestamp tracking."""

    def test_set_and_get_timestamp(self):
        """Test setting and getting timestamp."""
        msg = ControlMessage()
        now = datetime.now()

        msg.set_timestamp("received", now)

        retrieved = msg.get_timestamp("received")

        assert retrieved == now

    def test_get_nonexistent_timestamp_returns_none(self):
        """Test getting non-existent timestamp returns None."""
        msg = ControlMessage()

        ts = msg.get_timestamp("nonexistent")

        assert ts is None

    def test_get_nonexistent_timestamp_with_fail_raises_error(self):
        """Test getting non-existent timestamp with fail_if_nonexist=True."""
        msg = ControlMessage()

        with pytest.raises(KeyError, match="not found"):
            msg.get_timestamp("nonexistent", fail_if_nonexist=True)

    def test_get_all_timestamps(self):
        """Test getting all timestamps."""
        msg = ControlMessage()
        ts1 = datetime.now()
        ts2 = ts1 + timedelta(seconds=10)

        msg.set_timestamp("received", ts1)
        msg.set_timestamp("processed", ts2)

        timestamps = msg.get_timestamps()

        assert len(timestamps) == 2
        assert timestamps["received"] == ts1
        assert timestamps["processed"] == ts2


# ============================================================================
# TestMessageCopying
# ============================================================================


class TestMessageCopying:
    """Test message copying."""

    def test_copy_creates_independent_message(self, sample_dataframe):
        """Test that copy creates independent message."""
        original = ControlMessage()
        original.set_metadata("user_id", "alice")
        original.add_task("training", {"epochs": 50})
        original.payload(sample_dataframe)

        copy = original.copy()

        # Modify copy
        copy.set_metadata("user_id", "bob")
        copy.add_task("training", {"epochs": 100})

        # Original should be unchanged
        assert original.get_metadata("user_id") == "alice"
        assert len(original.get_tasks()["training"]) == 1

    def test_copy_preserves_task_type(self):
        """Test that copy preserves task type."""
        original = ControlMessage()
        original.add_task("inference", {"model_name": "test"})

        copy = original.copy()

        assert copy.task_type() == ControlMessageType.INFERENCE


# ============================================================================
# TestConvenienceFunctions
# ============================================================================


class TestConvenienceFunctions:
    """Test convenience functions."""

    def test_create_training_message(self, sample_dataframe):
        """Test create_training_message helper."""
        msg = create_training_message("alice", sample_dataframe, {"epochs": 50})

        assert msg.get_metadata("user_id") == "alice"
        assert msg.has_task("training")
        assert msg.payload() is not None
        assert msg.has_metadata("user_id")
        assert msg.get_timestamp("created") is not None

    def test_create_inference_message(self, sample_dataframe):
        """Test create_inference_message helper."""
        msg = create_inference_message("bob", sample_dataframe, {"model_name": "DFP-bob"})

        assert msg.get_metadata("user_id") == "bob"
        assert msg.has_task("inference")
        assert msg.payload() is not None
        assert msg.has_metadata("user_id")
        assert msg.get_timestamp("created") is not None


# ============================================================================
# TestMessageRouter
# ============================================================================


class TestMessageRouter:
    """Test MessageRouter functionality."""

    def test_route_training_message(self):
        """Test routing training message."""
        router = MessageRouter()
        msg = ControlMessage()
        msg.add_task("training", {})

        route = router.route(msg)

        assert route == "training"

    def test_route_inference_message(self):
        """Test routing inference message."""
        router = MessageRouter()
        msg = ControlMessage()
        msg.add_task("inference", {})

        route = router.route(msg)

        assert route == "inference"

    def test_route_invalid_message_raises_error(self):
        """Test routing message without valid task raises ValueError."""
        router = MessageRouter()
        msg = ControlMessage()

        with pytest.raises(ValueError, match="does not have a valid task"):
            router.route(msg)

    def test_route_with_non_control_message_raises_error(self):
        """Test routing non-ControlMessage raises TypeError."""
        router = MessageRouter()

        with pytest.raises(TypeError, match="Expected ControlMessage"):
            router.route("not_a_message")  # type: ignore[arg-type]

    def test_process_with_handlers(self):
        """Test processing message with registered handlers."""
        results = []

        def training_handler(msg):
            results.append("training")
            return "training_result"

        def inference_handler(msg):
            results.append("inference")
            return "inference_result"

        router = MessageRouter(training_handler=training_handler, inference_handler=inference_handler)

        # Process training message
        msg = ControlMessage()
        msg.add_task("training", {})
        result = router.process(msg)

        assert result == "training_result"
        assert "training" in results

        # Process inference message
        msg = ControlMessage()
        msg.add_task("inference", {})
        result = router.process(msg)

        assert result == "inference_result"
        assert "inference" in results

    def test_process_without_handler_raises_error(self):
        """Test processing without registered handler raises RuntimeError."""
        router = MessageRouter()
        msg = ControlMessage()
        msg.add_task("training", {})

        with pytest.raises(RuntimeError, match="No training handler"):
            router.process(msg)

    def test_validate_message(self):
        """Test message validation."""
        router = MessageRouter()

        # Valid message
        msg = ControlMessage()
        msg.set_metadata("user_id", "alice")
        msg.add_task("training", {})

        errors = router.validate_message(msg)

        assert len(errors) == 0

    def test_validate_message_without_tasks(self):
        """Test validating message without tasks."""
        router = MessageRouter()
        msg = ControlMessage()
        msg.set_metadata("user_id", "alice")

        errors = router.validate_message(msg)

        assert "Message has no tasks" in errors

    def test_validate_message_without_user_id(self):
        """Test validating message without user_id."""
        router = MessageRouter()
        msg = ControlMessage()
        msg.add_task("training", {})

        errors = router.validate_message(msg)

        assert any("user_id" in err for err in errors)

    def test_route_user_specific(self):
        """Test routing with user-specific check."""
        router = MessageRouter()

        # Specific user
        msg = ControlMessage()
        msg.set_metadata("user_id", "alice")
        msg.add_task("training", {})

        route, is_generic = router.route_user_specific(msg)

        assert route == "training"
        assert not is_generic

        # Generic user
        msg = ControlMessage()
        msg.set_metadata("user_id", "generic_user")
        msg.add_task("inference", {})

        route, is_generic = router.route_user_specific(msg)

        assert route == "inference"
        assert is_generic

    def test_router_statistics(self):
        """Test router statistics tracking."""
        router = MessageRouter()

        # Route some messages
        msg1 = ControlMessage()
        msg1.add_task("training", {})
        router.route(msg1)

        msg2 = ControlMessage()
        msg2.add_task("inference", {})
        router.route(msg2)

        msg3 = ControlMessage()
        msg3.add_task("training", {})
        router.route(msg3)

        stats = router.get_statistics()

        assert stats["training_routed"] == 2
        assert stats["inference_routed"] == 1
        assert stats["invalid_messages"] == 0

    def test_reset_statistics(self):
        """Test resetting router statistics."""
        router = MessageRouter()

        msg = ControlMessage()
        msg.add_task("training", {})
        router.route(msg)

        router.reset_statistics()

        stats = router.get_statistics()

        assert stats["training_routed"] == 0


# ============================================================================
# TestRoutingFunction
# ============================================================================


class TestRoutingFunction:
    """Test standalone routing function."""

    def test_route_message_training(self):
        """Test route_message function for training."""
        msg = ControlMessage()
        msg.add_task("training", {})

        route = route_message(msg)

        assert route == "training"

    def test_route_message_inference(self):
        """Test route_message function for inference."""
        msg = ControlMessage()
        msg.add_task("inference", {})

        route = route_message(msg)

        assert route == "inference"

    def test_route_message_invalid(self):
        """Test route_message function with invalid message."""
        msg = ControlMessage()

        with pytest.raises(ValueError, match="does not have a valid task"):
            route_message(msg)


# ============================================================================
# TestEdgeCases
# ============================================================================


class TestEdgeCases:
    """Test edge cases and error handling."""

    def test_config_with_invalid_message_type(self):
        """Test configuration with invalid message type."""
        msg = ControlMessage()

        with pytest.raises(ValueError, match="Invalid ControlMessageType"):
            msg.config({"type": "invalid_type"})

    def test_message_with_empty_payload(self):
        """Test message with empty DataFrame payload."""
        msg = ControlMessage()
        empty_df = pd.DataFrame()

        msg.payload(empty_df)

        retrieved = msg.payload()

        assert retrieved is not None
        assert len(retrieved) == 0

    def test_message_repr(self):
        """Test message string representation."""
        msg = ControlMessage()
        msg.set_metadata("user_id", "alice")
        msg.add_task("training", {})

        repr_str = repr(msg)

        assert "ControlMessage" in repr_str
        assert "TRAINING" in repr_str
        assert "user_id" in repr_str

    def test_router_with_custom_routing_function(self):
        """Test router with custom routing function."""

        def custom_router(msg):
            return "custom_route"

        router = MessageRouter(custom_router_fn=custom_router)
        msg = ControlMessage()

        route = router.route(msg)

        assert route == "custom_route"

    def test_message_with_none_metadata_value(self):
        """Test setting None as metadata value."""
        msg = ControlMessage()
        msg.set_metadata("optional_field", None)

        value = msg.get_metadata("optional_field")

        assert value is None
        assert msg.has_metadata("optional_field")
