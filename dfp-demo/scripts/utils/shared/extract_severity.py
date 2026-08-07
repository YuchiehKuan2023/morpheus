#!/usr/bin/env python3
"""
Canonical DFP anomaly-score → severity mapping.

Single source of truth used by all modules and scripts.

Severity bands (aligned with feature_bridge.DetectionRecord):
    anomaly_score > 5.0                → CRITICAL
    3.0 <= anomaly_score <= 5.0        → HIGH
    2.5 <= anomaly_score < 3.0        → MEDIUM
    2.0 < anomaly_score < 2.5         → LOW
    anomaly_score <= 2.0              → NONE  (below DFP detection threshold; not stored in practice)

Detection threshold is 2.0 — scores at or below this are never produced by DFP.
"""


def severity_from_score(anomaly_score: float) -> str:
    """Return the severity band for a DFP mean-absolute-z-score.

    Args:
        anomaly_score: DFP mean absolute z-score (detection threshold 2.0).

    Returns:
        One of "CRITICAL", "HIGH", "MEDIUM", "LOW", or "NONE".
    """
    if anomaly_score > 5.0:
        return "CRITICAL"
    if anomaly_score >= 3.0:
        return "HIGH"
    if anomaly_score >= 2.5:
        return "MEDIUM"
    if anomaly_score > 2.0:
        return "LOW"
    return "NONE"  # below detection threshold; should not appear in stored detections
