"""
Control Message Module - Simplified NVIDIA Morpheus DFP Implementation

This module provides a Python-only implementation of NVIDIA Morpheus control messages
for routing between training and inference pipelines in the DFP system.

Reference:
    - /nv-morpheus/python/morpheus/morpheus/messages/control_message.py
    - /nv-morpheus/python/morpheus/morpheus/_lib/include/morpheus/messages/control.hpp
    - /nv-morpheus/examples/digital_fingerprinting/production/

NVIDIA Alignment:
    - Follows official ControlMessage structure and API
    - Supports training/inference task routing
    - Metadata storage for user_id, timestamps, configuration
    - Task management (add_task, has_task, remove_task)
    - Payload support for DataFrame/data attachment

Note:
    This is a simplified Python-only version for PoC use. Production systems should use
    the official NVIDIA Morpheus ControlMessage with C++ bindings for performance.
"""

import logging
from collections import defaultdict, deque
from datetime import datetime
from enum import Enum
from typing import Any, Union

import pandas as pd

logger = logging.getLogger(__name__)


class ControlMessageType(Enum):
    """
    Control message type enumeration.

    Mirrors NVIDIA Morpheus ControlMessageType enum:
        - NONE: No specific type
        - INFERENCE: Inference task
        - TRAINING: Training task

    Reference: /nv-morpheus/python/morpheus/morpheus/_lib/messages/__init__.pyi
    """

    NONE = 0
    INFERENCE = 1
    TRAINING = 2


class ControlMessage:
    """
    Control Message for coordinating data processing tasks in DFP pipeline.

    This class contains configuration information, task definitions, metadata, and
    an optional payload (DataFrame). It provides methods for accessing and modifying
    these elements to route data through training or inference pipelines.

    Architecture:
        - config: Configuration dictionary with metadata
        - tasks: Task queue per task type (training, inference)
        - payload: Optional DataFrame for data attachment
        - timestamps: Timestamp tracking for processing events
        - type: Message type (TRAINING, INFERENCE, NONE)

    Reference:
        - NVIDIA ControlMessage: python/morpheus/morpheus/messages/control_message.py
        - DFP Deployment Router: python/morpheus_dfp/morpheus_dfp/modules/dfp_deployment.py

    Example:
        >>> # Training message
        >>> msg = ControlMessage()
        >>> msg.set_metadata("user_id", "alice")
        >>> msg.add_task("training", {"epochs": 50, "validation_size": 0.1})
        >>> msg.payload(training_df)
        >>>
        >>> # Inference message
        >>> msg = ControlMessage()
        >>> msg.set_metadata("user_id", "alice")
        >>> msg.add_task("inference", {"model_name": "DFP-alice"})
        >>> msg.payload(inference_df)
        >>>
        >>> # Router check
        >>> if msg.has_task("training"):
        >>>     route_to_training_pipeline(msg)
        >>> elif msg.has_task("inference"):
        >>>     route_to_inference_pipeline(msg)
    """

    def __init__(self, config: Union[dict, "ControlMessage"] | None = None):
        """
        Initialize a ControlMessage.

        Args:
            config: Optional configuration dictionary or another ControlMessage to copy.
                   If dict, can contain:
                       - "metadata": Dictionary of metadata key-value pairs
                       - "tasks": List of task dictionaries with "type" and "properties"
                       - "type": String or ControlMessageType enum ("training"/"inference")
                   If ControlMessage, copies configuration from that message.

        Example:
            >>> # Empty message
            >>> msg = ControlMessage()
            >>>
            >>> # With configuration
            >>> msg = ControlMessage({
            >>>     "metadata": {"user_id": "alice", "batch_id": "2024-01-15"},
            >>>     "tasks": [
            >>>         {"type": "training", "properties": {"epochs": 50}}
            >>>     ]
            >>> })
            >>>
            >>> # Copy from another message
            >>> msg2 = ControlMessage(msg)
        """
        self._config: dict[str, Any] = {"metadata": {}}
        self._payload: pd.DataFrame | None = None
        self._tasks: dict[str, deque] = defaultdict(deque)
        self._timestamps: dict[str, datetime] = {}
        self._type: ControlMessageType = ControlMessageType.NONE

        if isinstance(config, dict):
            self.config(config)
        elif isinstance(config, ControlMessage):
            self._copy_from(config)
        elif config is not None:
            raise ValueError(f"Invalid argument type {type(config)}. Must be a dict or ControlMessage instance.")

    def config(self, config: dict | None = None) -> dict:
        """
        Get or set the configuration for this control message.

        Args:
            config: Optional configuration dictionary to set. If None, returns current config.
                   If provided, updates internal configuration with:
                       - type: Message type (training/inference)
                       - tasks: List of tasks to add
                       - metadata: Metadata dictionary to merge

        Returns:
            Current configuration dictionary

        Example:
            >>> msg = ControlMessage()
            >>>
            >>> # Set configuration
            >>> msg.config({
            >>>     "type": "training",
            >>>     "metadata": {"user_id": "alice"},
            >>>     "tasks": [{"type": "training", "properties": {"epochs": 50}}]
            >>> })
            >>>
            >>> # Get configuration
            >>> cfg = msg.config()
            >>> print(cfg["metadata"]["user_id"])  # "alice"
        """
        if config is not None:
            # Set message type if provided
            if "type" in config:
                msg_type = config["type"]
                if isinstance(msg_type, str):
                    try:
                        self._type = ControlMessageType[msg_type.upper()]
                    except KeyError as e:
                        valid_types = ", ".join([t.name for t in ControlMessageType])
                        raise ValueError(f"Invalid ControlMessageType: {msg_type}. Valid types: {valid_types}") from e
                elif isinstance(msg_type, ControlMessageType):
                    self._type = msg_type

            # Add tasks if provided
            if "tasks" in config:
                for task in config["tasks"]:
                    self.add_task(task["type"], task["properties"])

            # Merge metadata if provided
            if "metadata" in config:
                self._config["metadata"].update(config["metadata"])

        return self._config

    def add_task(self, task_type: str, task: dict):
        """
        Add a task to the control message.

        Tasks are queued by type and can be processed sequentially. Common task types
        in DFP are "training" and "inference".

        Args:
            task_type: Type of task ("training", "inference", etc.)
            task: Task properties dictionary with configuration for the task

        Raises:
            ValueError: If mixing different ControlMessageType tasks in same message

        Example:
            >>> msg = ControlMessage()
            >>>
            >>> # Add training task
            >>> msg.add_task("training", {
            >>>     "epochs": 50,
            >>>     "validation_size": 0.1,
            >>>     "learning_rate": 0.01
            >>> })
            >>>
            >>> # Add inference task
            >>> msg.add_task("inference", {
            >>>     "model_name": "DFP-alice",
            >>>     "threshold": 3.0
            >>> })

        Reference:
            NVIDIA add_task: python/morpheus/morpheus/messages/control_message.py:87-105
        """
        # Check if this task type maps to a ControlMessageType
        task_type_lower = task_type.lower()
        if task_type_lower in ["training", "inference"]:
            cm_type = ControlMessageType[task_type_lower.upper()]

            # Ensure we don't mix types
            if self._type == ControlMessageType.NONE:
                self._type = cm_type
            elif self._type != cm_type:
                raise ValueError(
                    f"Cannot mix different types of tasks on the same control message. "
                    f"Current type: {self._type.name}, attempted to add: {cm_type.name}"
                )

        self._tasks[task_type].append(task)
        logger.debug(f"Added task '{task_type}' to control message")

    def has_task(self, task_type: str) -> bool:
        """
        Check if the control message has at least one task of the given type.

        Args:
            task_type: Type of task to check for ("training", "inference", etc.)

        Returns:
            True if at least one task of this type exists, False otherwise

        Example:
            >>> msg = ControlMessage()
            >>> msg.add_task("training", {"epochs": 50})
            >>>
            >>> if msg.has_task("training"):
            >>>     print("Has training task")  # This will print
            >>>
            >>> if msg.has_task("inference"):
            >>>     print("Has inference task")  # This won't print

        Reference:
            NVIDIA has_task: python/morpheus/morpheus/messages/control_message.py:87-90
        """
        tasks = self._tasks.get(task_type, [])
        return len(tasks) > 0

    def remove_task(self, task_type: str) -> dict:
        """
        Remove and return a task of the given type from the control message.

        Tasks are stored in a queue (FIFO), so this removes the first task of the
        specified type.

        Args:
            task_type: Type of task to remove ("training", "inference", etc.)

        Returns:
            The task properties dictionary that was removed

        Raises:
            ValueError: If no task of this type exists

        Example:
            >>> msg = ControlMessage()
            >>> msg.add_task("training", {"epochs": 50})
            >>>
            >>> # Process and remove task
            >>> task = msg.remove_task("training")
            >>> print(task)  # {"epochs": 50}
            >>>
            >>> # Try to remove again - will raise ValueError
            >>> try:
            >>>     msg.remove_task("training")
            >>> except ValueError as e:
            >>>     print(f"Error: {e}")

        Reference:
            NVIDIA remove_task: python/morpheus/morpheus/messages/control_message.py:106-112
        """
        if task_type not in self._tasks or len(self._tasks[task_type]) == 0:
            raise ValueError(f"No task of type '{task_type}' found in control message")

        task = self._tasks[task_type].popleft()
        logger.debug(f"Removed task '{task_type}' from control message")
        return task

    def get_tasks(self) -> dict[str, deque]:
        """
        Get all tasks in the control message.

        Returns:
            Dictionary mapping task types to deques of task properties

        Example:
            >>> msg = ControlMessage()
            >>> msg.add_task("training", {"epochs": 50})
            >>> msg.add_task("training", {"epochs": 100})
            >>>
            >>> tasks = msg.get_tasks()
            >>> print(len(tasks["training"]))  # 2

        Reference:
            NVIDIA get_tasks: python/morpheus/morpheus/messages/control_message.py:113-115
        """
        return self._tasks

    def set_metadata(self, key: str, value: Any):
        """
        Set a metadata key-value pair for the control message.

        Metadata is used to store contextual information like user_id, batch_id,
        timestamps, model names, etc.

        Args:
            key: Metadata key
            value: Metadata value (any JSON-serializable type)

        Example:
            >>> msg = ControlMessage()
            >>> msg.set_metadata("user_id", "alice")
            >>> msg.set_metadata("batch_id", "2024-01-15")
            >>> msg.set_metadata("model_version", "v1.0")

        Reference:
            NVIDIA set_metadata: python/morpheus/morpheus/messages/control_message.py:116-118
        """
        self._config["metadata"][key] = value
        logger.debug(f"Set metadata '{key}' = {value}")

    def has_metadata(self, key: str) -> bool:
        """
        Check if a metadata key exists in the control message.

        Args:
            key: Metadata key to check

        Returns:
            True if the key exists, False otherwise

        Example:
            >>> msg = ControlMessage()
            >>> msg.set_metadata("user_id", "alice")
            >>>
            >>> print(msg.has_metadata("user_id"))  # True
            >>> print(msg.has_metadata("batch_id"))  # False

        Reference:
            NVIDIA has_metadata: python/morpheus/morpheus/messages/control_message.py:119-121
        """
        return key in self._config["metadata"]

    def get_metadata(self, key: str | None = None, default_value: Any = None) -> Any:
        """
        Get a metadata value by key, or all metadata if key is None.

        Args:
            key: Metadata key to retrieve. If None, returns entire metadata dict.
            default_value: Value to return if key doesn't exist. Ignored if key is None.

        Returns:
            Metadata value, default_value if key not found, or entire metadata dict

        Example:
            >>> msg = ControlMessage()
            >>> msg.set_metadata("user_id", "alice")
            >>> msg.set_metadata("batch_id", "2024-01-15")
            >>>
            >>> # Get specific key
            >>> print(msg.get_metadata("user_id"))  # "alice"
            >>>
            >>> # Get with default
            >>> print(msg.get_metadata("missing", "default"))  # "default"
            >>>
            >>> # Get all metadata
            >>> all_meta = msg.get_metadata()
            >>> print(all_meta)  # {"user_id": "alice", "batch_id": "2024-01-15"}

        Reference:
            NVIDIA get_metadata: python/morpheus/morpheus/messages/control_message.py:122-140
        """
        if key is None:
            return self._config["metadata"]

        return self._config["metadata"].get(key, default_value)

    def list_metadata(self) -> list[str]:
        """
        List all metadata keys in the control message.

        Returns:
            Sorted list of metadata keys

        Example:
            >>> msg = ControlMessage()
            >>> msg.set_metadata("user_id", "alice")
            >>> msg.set_metadata("batch_id", "2024-01-15")
            >>>
            >>> keys = msg.list_metadata()
            >>> print(keys)  # ["batch_id", "user_id"]

        Reference:
            NVIDIA list_metadata: python/morpheus/morpheus/messages/control_message.py:138-140
        """
        return sorted(self._config["metadata"].keys())

    def payload(self, payload: pd.DataFrame | None = None) -> pd.DataFrame | None:
        """
        Get or set the payload DataFrame for this control message.

        The payload is typically a DataFrame containing the data to be processed
        by the training or inference pipeline.

        Args:
            payload: Optional DataFrame to set as payload. If None, returns current payload.

        Returns:
            Current payload DataFrame (may be None)

        Example:
            >>> msg = ControlMessage()
            >>>
            >>> # Set payload
            >>> df = pd.DataFrame({"feature1": [1, 2, 3], "feature2": [4, 5, 6]})
            >>> msg.payload(df)
            >>>
            >>> # Get payload
            >>> retrieved_df = msg.payload()
            >>> print(retrieved_df.shape)  # (3, 2)

        Reference:
            NVIDIA payload: python/morpheus/morpheus/messages/control_message.py:141-149
        """
        if payload is not None:
            self._payload = payload
            logger.debug(f"Set payload with shape {payload.shape}")

        return self._payload

    def task_type(self, new_task_type: ControlMessageType | None = None) -> ControlMessageType:
        """
        Get or set the task type for this control message.

        Args:
            new_task_type: Optional ControlMessageType to set. If None, returns current type.

        Returns:
            Current ControlMessageType

        Example:
            >>> msg = ControlMessage()
            >>>
            >>> # Set task type
            >>> msg.task_type(ControlMessageType.TRAINING)
            >>>
            >>> # Get task type
            >>> msg_type = msg.task_type()
            >>> print(msg_type)  # ControlMessageType.TRAINING

        Reference:
            NVIDIA task_type: python/morpheus/morpheus/messages/control_message.py:157-165
        """
        if new_task_type is not None:
            self._type = new_task_type

        return self._type

    def set_timestamp(self, key: str, timestamp: datetime):
        """
        Set a timestamp for a given key.

        Timestamps are used to track processing events (e.g., received, processed,
        training_start, training_end, etc.).

        Args:
            key: Timestamp key
            timestamp: datetime object

        Example:
            >>> msg = ControlMessage()
            >>> msg.set_timestamp("received", datetime.now())
            >>> msg.set_timestamp("training_start", datetime.now())

        Reference:
            NVIDIA set_timestamp: python/morpheus/morpheus/messages/control_message.py:165-167
        """
        self._timestamps[key] = timestamp
        logger.debug(f"Set timestamp '{key}' = {timestamp}")

    def get_timestamp(self, key: str, fail_if_nonexist: bool = False) -> datetime | None:
        """
        Get a timestamp for a given key.

        Args:
            key: Timestamp key
            fail_if_nonexist: If True, raises KeyError if key doesn't exist

        Returns:
            datetime object if found, None if not found and fail_if_nonexist is False

        Raises:
            KeyError: If key not found and fail_if_nonexist is True

        Example:
            >>> msg = ControlMessage()
            >>> msg.set_timestamp("received", datetime.now())
            >>>
            >>> # Get existing timestamp
            >>> ts = msg.get_timestamp("received")
            >>> print(ts)
            >>>
            >>> # Get missing timestamp (returns None)
            >>> ts = msg.get_timestamp("missing")
            >>> print(ts)  # None
            >>>
            >>> # Get missing timestamp (raises KeyError)
            >>> try:
            >>>     ts = msg.get_timestamp("missing", fail_if_nonexist=True)
            >>> except KeyError as e:
            >>>     print(f"Error: {e}")

        Reference:
            NVIDIA get_timestamp: python/morpheus/morpheus/messages/control_message.py:168-175
        """
        if fail_if_nonexist and key not in self._timestamps:
            raise KeyError(f"Timestamp key '{key}' not found in control message")

        return self._timestamps.get(key)

    def get_timestamps(self) -> dict[str, datetime]:
        """
        Get all timestamps in the control message.

        Returns:
            Dictionary mapping timestamp keys to datetime objects

        Example:
            >>> msg = ControlMessage()
            >>> msg.set_timestamp("received", datetime.now())
            >>> msg.set_timestamp("processed", datetime.now())
            >>>
            >>> timestamps = msg.get_timestamps()
            >>> print(timestamps.keys())  # dict_keys(['received', 'processed'])

        Reference:
            NVIDIA get_timestamps: python/morpheus/morpheus/messages/control_message.py:176-178
        """
        return self._timestamps.copy()

    def copy(self) -> "ControlMessage":
        """
        Create a deep copy of this control message.

        Returns:
            New ControlMessage instance with copied configuration

        Example:
            >>> msg = ControlMessage()
            >>> msg.set_metadata("user_id", "alice")
            >>> msg.add_task("training", {"epochs": 50})
            >>>
            >>> # Copy message
            >>> msg2 = msg.copy()
            >>> msg2.set_metadata("user_id", "bob")
            >>>
            >>> # Original unchanged
            >>> print(msg.get_metadata("user_id"))  # "alice"
            >>> print(msg2.get_metadata("user_id"))  # "bob"

        Reference:
            NVIDIA copy: python/morpheus/morpheus/messages/control_message.py:62-63
        """
        new_msg = ControlMessage()
        new_msg._copy_from(self)
        return new_msg

    def _copy_from(self, src: "ControlMessage"):
        """
        Internal method to copy configuration from another message.

        Args:
            src: Source ControlMessage to copy from

        Reference:
            NVIDIA _copy_impl: python/morpheus/morpheus/messages/control_message.py:198-211
        """
        self._type = src._type
        self._config = {"metadata": src._config["metadata"].copy()}
        self._payload = src._payload  # Shallow copy of DataFrame reference

        # Deep copy tasks
        for task_type, task_queue in src._tasks.items():
            self._tasks[task_type] = deque(task_queue)

        # Copy timestamps
        self._timestamps = src._timestamps.copy()

    def __repr__(self) -> str:
        """String representation of the control message."""
        return (
            f"ControlMessage(type={self._type.name}, "
            f"tasks={list(self._tasks.keys())}, "
            f"metadata_keys={list(self._config['metadata'].keys())}, "
            f"has_payload={self._payload is not None})"
        )


# Convenience function for simple use cases
def create_training_message(user_id: str, payload: pd.DataFrame, task_properties: dict | None = None) -> ControlMessage:
    """
    Create a training control message.

    Convenience function for creating a training message with common settings.

    Args:
        user_id: User identifier
        payload: Training data DataFrame
        task_properties: Optional training task properties (epochs, validation_size, etc.)

    Returns:
        ControlMessage configured for training

    Example:
        >>> df = pd.DataFrame({"feature1": [1, 2, 3]})
        >>> msg = create_training_message("alice", df, {"epochs": 50})
    """
    if task_properties is None:
        task_properties = {}

    msg = ControlMessage()
    msg.set_metadata("user_id", user_id)
    msg.set_timestamp("created", datetime.now())
    msg.add_task("training", task_properties)
    msg.payload(payload)

    return msg


def create_inference_message(
    user_id: str, payload: pd.DataFrame, task_properties: dict | None = None
) -> ControlMessage:
    """
    Create an inference control message.

    Convenience function for creating an inference message with common settings.

    Args:
        user_id: User identifier
        payload: Inference data DataFrame
        task_properties: Optional inference task properties (model_name, threshold, etc.)

    Returns:
        ControlMessage configured for inference

    Example:
        >>> df = pd.DataFrame({"feature1": [1, 2, 3]})
        >>> msg = create_inference_message("alice", df, {"model_name": "DFP-alice"})
    """
    if task_properties is None:
        task_properties = {}

    msg = ControlMessage()
    msg.set_metadata("user_id", user_id)
    msg.set_timestamp("created", datetime.now())
    msg.add_task("inference", task_properties)
    msg.payload(payload)

    return msg
