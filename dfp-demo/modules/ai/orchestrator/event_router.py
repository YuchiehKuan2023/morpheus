"""
Event router for the AI orchestrator.

Deserialises raw Kafka messages from dfp-detections and dfp-clean-events
into a typed RoutedEvent dataclass that both consumer threads work with.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

logger = logging.getLogger(__name__)


class EventType(str, Enum):
    ANOMALY = "anomaly"
    CLEAN = "clean"


@dataclass
class RoutedEvent:
    """
    Normalised event produced by the inference pipeline.

    Attributes:
        event_type:      ANOMALY (from dfp-detections) or CLEAN (from dfp-clean-events).
        user_id:         Azure AD username.
        original_event:  Raw pre-preprocessing row dict (all Azure AD columns).
        detection:       Full detection_record dict — present for ANOMALY only.
        anomaly_score:   mean_abs_z value — present for ANOMALY only.
    """

    event_type: EventType
    user_id: str
    original_event: dict[str, Any]
    detection: dict[str, Any] | None = None
    anomaly_score: float | None = None
    features: list[dict[str, Any]] = field(default_factory=list)

    # ------------------------------------------------------------------ #
    # Factory methods                                                      #
    # ------------------------------------------------------------------ #

    @classmethod
    def from_anomaly_message(cls, msg: dict[str, Any]) -> RoutedEvent:
        """Build a RoutedEvent from a dfp-detections Kafka message."""
        user_id = str(msg.get("user_id", ""))
        original_event = msg.get("original_event")
        if not isinstance(original_event, dict) or not original_event:
            # Fall back to the full message so no event context is lost
            original_event = dict(msg)
        return cls(
            event_type=EventType.ANOMALY,
            user_id=user_id,
            original_event=original_event,
            detection=msg,
            anomaly_score=float(msg.get("anomaly_score", 0.0)),
            features=msg.get("features") or [],
        )

    @classmethod
    def from_clean_message(cls, msg: dict[str, Any]) -> RoutedEvent:
        """Build a RoutedEvent from a dfp-clean-events Kafka message.

        The value on dfp-clean-events is the raw Azure AD event dict produced
        by the inference pipeline before any schema transforms.  The user
        field in that dict is ``identity`` (mapped to ``username`` only inside
        the inference DataFrame).  Fall back chain mirrors the logic used in
        inference_pipeline._build_raw_events_by_user.
        """
        user_id = str(
            msg.get("identity")
            or msg.get("username")
            or msg.get("user_id")
            or msg.get("properties", {}).get("userPrincipalName")
            or ""
        )
        return cls(
            event_type=EventType.CLEAN,
            user_id=user_id,
            original_event=msg,
        )

    # ------------------------------------------------------------------ #
    # Helpers                                                              #
    # ------------------------------------------------------------------ #

    @property
    def is_anomaly(self) -> bool:
        return self.event_type == EventType.ANOMALY

    def __repr__(self) -> str:
        score_str = f", score={self.anomaly_score:.2f}" if self.anomaly_score is not None else ""
        return f"RoutedEvent(type={self.event_type.value}, user={self.user_id!r}{score_str})"
