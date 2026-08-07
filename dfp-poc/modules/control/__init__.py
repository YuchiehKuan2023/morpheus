"""
Control Module - NVIDIA Morpheus DFP Control Message System

This module provides control message functionality for routing data processing tasks
between training and inference pipelines in the Digital Fingerprinting system.

Exports:
    - ControlMessage: Main control message class for task coordination
    - ControlMessageType: Enum for message types (NONE, TRAINING, INFERENCE)
    - MessageRouter: Router for directing messages to appropriate pipelines
    - create_training_message: Convenience function for training messages
    - create_inference_message: Convenience function for inference messages
    - route_message: Simple routing function

Reference:
    NVIDIA Morpheus Control Messages:
        - python/morpheus/morpheus/messages/control_message.py
        - python/morpheus_dfp/morpheus_dfp/modules/dfp_deployment.py
"""

from modules.control.control_message import (
    ControlMessage,
    ControlMessageType,
    create_inference_message,
    create_training_message,
)
from modules.control.message_router import MessageRouter, route_message

__all__ = [
    "ControlMessage",
    "ControlMessageType",
    "MessageRouter",
    "create_training_message",
    "create_inference_message",
    "route_message",
]
