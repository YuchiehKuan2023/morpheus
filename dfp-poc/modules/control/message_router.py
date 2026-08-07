"""
Message Router Module - NVIDIA Morpheus DFP Control Message Routing

This module provides routing logic for control messages to direct them to appropriate
pipelines (training vs inference) based on their task types.

Reference:
    - /nv-morpheus/python/morpheus_dfp/morpheus_dfp/modules/dfp_deployment.py (router_key_fn)
    - /nv-morpheus/examples/digital_fingerprinting/production/dfp_integrated_training_batch_pipeline.py

NVIDIA Alignment:
    - Follows official DFP deployment router pattern
    - Routes based on has_task("training") vs has_task("inference")
    - Supports user-specific vs generic routing logic
    - Error handling for invalid/malformed messages

Key Pattern:
    ```python
    def router_key_fn(cm: ControlMessage) -> str:
        if cm.has_task("training"):
            return "training"
        if cm.has_task("inference"):
            return "inference"
        raise ValueError("Control message does not have a valid task.")
    ```
"""

import logging
from collections.abc import Callable
from typing import Any

from modules.control.control_message import ControlMessage

logger = logging.getLogger(__name__)


class MessageRouter:
    """
    Router for directing control messages to appropriate pipeline handlers.

    This class implements the NVIDIA Morpheus DFP routing pattern where control
    messages are examined for their task types and routed to either training
    or inference pipelines.

    Architecture:
        - Routes based on task presence (has_task)
        - Supports custom routing functions
        - Validates messages before routing
        - Logs routing decisions for observability

    Reference:
        NVIDIA DFP Deployment: python/morpheus_dfp/morpheus_dfp/modules/dfp_deployment.py:208-215

    Example:
        >>> router = MessageRouter()
        >>>
        >>> # Route training message
        >>> msg = ControlMessage()
        >>> msg.add_task("training", {"epochs": 50})
        >>> route = router.route(msg)
        >>> print(route)  # "training"
        >>>
        >>> # Route inference message
        >>> msg = ControlMessage()
        >>> msg.add_task("inference", {"model_name": "DFP-alice"})
        >>> route = router.route(msg)
        >>> print(route)  # "inference"
    """

    def __init__(
        self,
        training_handler: Callable | None = None,
        inference_handler: Callable | None = None,
        custom_router_fn: Callable[[ControlMessage], str] | None = None,
    ):
        """
        Initialize message router.

        Args:
            training_handler: Optional callable to handle training messages.
                             Signature: (ControlMessage) -> Any
            inference_handler: Optional callable to handle inference messages.
                              Signature: (ControlMessage) -> Any
            custom_router_fn: Optional custom routing function.
                             Signature: (ControlMessage) -> str
                             Should return "training" or "inference"

        Example:
            >>> def handle_training(msg):
            >>>     print(f"Training for user: {msg.get_metadata('user_id')}")
            >>>
            >>> def handle_inference(msg):
            >>>     print(f"Inference for user: {msg.get_metadata('user_id')}")
            >>>
            >>> router = MessageRouter(
            >>>     training_handler=handle_training,
            >>>     inference_handler=handle_inference
            >>> )
        """
        self.training_handler = training_handler
        self.inference_handler = inference_handler
        self.custom_router_fn = custom_router_fn

        # Statistics
        self._stats: dict[str, int] = {"training_routed": 0, "inference_routed": 0, "invalid_messages": 0, "errors": 0}

        logger.info("MessageRouter initialized")

    def route(self, message: ControlMessage) -> str:
        """
        Determine the routing key for a control message.

        This is the core routing logic that follows NVIDIA's pattern:
            1. Check if message has "training" task -> route to "training"
            2. Check if message has "inference" task -> route to "inference"
            3. Otherwise -> raise ValueError

        Args:
            message: ControlMessage to route

        Returns:
            Routing key: "training" or "inference"

        Raises:
            ValueError: If message doesn't have a valid training or inference task
            TypeError: If message is not a ControlMessage instance

        Example:
            >>> router = MessageRouter()
            >>>
            >>> # Training message
            >>> msg = ControlMessage()
            >>> msg.add_task("training", {})
            >>> print(router.route(msg))  # "training"
            >>>
            >>> # Inference message
            >>> msg = ControlMessage()
            >>> msg.add_task("inference", {})
            >>> print(router.route(msg))  # "inference"
            >>>
            >>> # Invalid message
            >>> msg = ControlMessage()
            >>> try:
            >>>     router.route(msg)
            >>> except ValueError as e:
            >>>     print(f"Error: {e}")

        Reference:
            NVIDIA router_key_fn: python/morpheus_dfp/morpheus_dfp/modules/dfp_deployment.py:210-215
        """
        # Validation
        if not isinstance(message, ControlMessage):
            self._stats["errors"] += 1
            raise TypeError(f"Expected ControlMessage, got {type(message).__name__}")

        # Use custom router if provided
        if self.custom_router_fn is not None:
            return self.custom_router_fn(message)

        # Standard NVIDIA routing logic
        if message.has_task("training"):
            self._stats["training_routed"] += 1
            logger.debug(
                f"Routing message to training pipeline (user_id: {message.get_metadata('user_id', 'unknown')})"
            )
            return "training"

        if message.has_task("inference"):
            self._stats["inference_routed"] += 1
            logger.debug(
                f"Routing message to inference pipeline (user_id: {message.get_metadata('user_id', 'unknown')})"
            )
            return "inference"

        # No valid task found
        self._stats["invalid_messages"] += 1
        raise ValueError("Control message does not have a valid task. Expected 'training' or 'inference' task.")

    def process(self, message: ControlMessage) -> Any | None:
        """
        Route and process a control message using registered handlers.

        This method combines routing with handler execution. It routes the message
        and then calls the appropriate handler (training_handler or inference_handler)
        if one is registered.

        Args:
            message: ControlMessage to process

        Returns:
            Result from the handler, or None if no handler registered

        Raises:
            ValueError: If message doesn't have a valid task
            TypeError: If message is not a ControlMessage
            RuntimeError: If no handler is registered for the routed path

        Example:
            >>> def train(msg):
            >>>     return f"Training {msg.get_metadata('user_id')}"
            >>>
            >>> def infer(msg):
            >>>     return f"Inference {msg.get_metadata('user_id')}"
            >>>
            >>> router = MessageRouter(
            >>>     training_handler=train,
            >>>     inference_handler=infer
            >>> )
            >>>
            >>> msg = ControlMessage()
            >>> msg.set_metadata("user_id", "alice")
            >>> msg.add_task("training", {})
            >>>
            >>> result = router.process(msg)
            >>> print(result)  # "Training alice"
        """
        try:
            route_key = self.route(message)

            if route_key == "training":
                if self.training_handler is None:
                    raise RuntimeError("No training handler registered")
                return self.training_handler(message)

            elif route_key == "inference":
                if self.inference_handler is None:
                    raise RuntimeError("No inference handler registered")
                return self.inference_handler(message)

            else:
                raise ValueError(f"Unknown route key: {route_key}")

        except Exception as e:
            self._stats["errors"] += 1
            logger.error(f"Error processing message: {e}")
            raise

    def validate_message(self, message: ControlMessage) -> list[str]:
        """
        Validate a control message and return list of validation errors.

        Checks:
            - Message is a ControlMessage instance
            - Message has at least one task
            - Message has either training or inference task
            - Message has required metadata (user_id)

        Args:
            message: ControlMessage to validate

        Returns:
            List of validation error messages (empty if valid)

        Example:
            >>> router = MessageRouter()
            >>> msg = ControlMessage()
            >>>
            >>> errors = router.validate_message(msg)
            >>> print(errors)  # ["Message has no tasks", "Missing required metadata: user_id"]
            >>>
            >>> # Fix errors
            >>> msg.set_metadata("user_id", "alice")
            >>> msg.add_task("training", {})
            >>>
            >>> errors = router.validate_message(msg)
            >>> print(errors)  # []
        """
        errors = []

        # Type check
        if not isinstance(message, ControlMessage):
            errors.append(f"Expected ControlMessage, got {type(message).__name__}")
            return errors  # Can't continue validation

        # Check for tasks
        tasks = message.get_tasks()
        if not tasks or all(len(queue) == 0 for queue in tasks.values()):
            errors.append("Message has no tasks")

        # Check for valid task type
        has_training = message.has_task("training")
        has_inference = message.has_task("inference")
        if not has_training and not has_inference:
            errors.append("Message must have either 'training' or 'inference' task")

        # Check for required metadata
        if not message.has_metadata("user_id"):
            errors.append("Missing required metadata: user_id")

        return errors

    def route_user_specific(self, message: ControlMessage, generic_user: str = "generic_user") -> tuple[str, bool]:
        """
        Route message and determine if it's for a specific user or generic model.

        This follows the NVIDIA DFP pattern of supporting both user-specific and
        generic (fallback) models.

        Args:
            message: ControlMessage to route
            generic_user: User ID that indicates generic model (default: "generic_user")

        Returns:
            Tuple of (route_key, is_generic) where:
                - route_key: "training" or "inference"
                - is_generic: True if user_id matches generic_user, False otherwise

        Example:
            >>> router = MessageRouter()
            >>>
            >>> # Specific user
            >>> msg = ControlMessage()
            >>> msg.set_metadata("user_id", "alice")
            >>> msg.add_task("training", {})
            >>> route, is_generic = router.route_user_specific(msg)
            >>> print(route, is_generic)  # "training", False
            >>>
            >>> # Generic user
            >>> msg = ControlMessage()
            >>> msg.set_metadata("user_id", "generic_user")
            >>> msg.add_task("training", {})
            >>> route, is_generic = router.route_user_specific(msg)
            >>> print(route, is_generic)  # "training", True
        """
        route_key = self.route(message)
        user_id = message.get_metadata("user_id", generic_user)
        is_generic = user_id == generic_user

        if is_generic:
            logger.debug(f"Routing to {route_key} pipeline (generic model)")
        else:
            logger.debug(f"Routing to {route_key} pipeline (user: {user_id})")

        return route_key, is_generic

    def get_statistics(self) -> dict[str, int]:
        """
        Get routing statistics.

        Returns:
            Dictionary with routing statistics:
                - training_routed: Number of messages routed to training
                - inference_routed: Number of messages routed to inference
                - invalid_messages: Number of invalid messages
                - errors: Number of errors encountered

        Example:
            >>> router = MessageRouter()
            >>> # ... process some messages ...
            >>> stats = router.get_statistics()
            >>> print(f"Training: {stats['training_routed']}")
            >>> print(f"Inference: {stats['inference_routed']}")
        """
        return self._stats.copy()

    def reset_statistics(self):
        """
        Reset routing statistics to zero.

        Example:
            >>> router = MessageRouter()
            >>> # ... process some messages ...
            >>> router.reset_statistics()
            >>> stats = router.get_statistics()
            >>> print(stats)  # All zeros
        """
        self._stats = {"training_routed": 0, "inference_routed": 0, "invalid_messages": 0, "errors": 0}
        logger.info("Router statistics reset")


# Convenience function for simple routing
def route_message(message: ControlMessage) -> str:
    """
    Simple routing function following NVIDIA pattern.

    Args:
        message: ControlMessage to route

    Returns:
        Routing key: "training" or "inference"

    Raises:
        ValueError: If message doesn't have a valid task

    Example:
        >>> msg = ControlMessage()
        >>> msg.add_task("training", {})
        >>> route = route_message(msg)
        >>> print(route)  # "training"

    Reference:
        NVIDIA router_key_fn: python/morpheus_dfp/morpheus_dfp/modules/dfp_deployment.py:210-215
    """
    if message.has_task("training"):
        return "training"
    if message.has_task("inference"):
        return "inference"
    raise ValueError("Control message does not have a valid task.")
