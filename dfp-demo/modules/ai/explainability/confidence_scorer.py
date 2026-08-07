#!/usr/bin/env python3
"""
Confidence Scorer — Ensemble trust signal for anomaly detections

Combines three independent signals into a single confidence score (0–1)
that reflects how certain the AI pipeline is about an anomaly detection:

    1. XGBoost risk score  (40% weight) — model certainty via high score
    2. DFP anomaly score   (35% weight) — raw signal strength from DFP autoencoder
    3. LLM confidence      (25% weight) — LLM self-reported confidence in explanation

Formula
-------
    confidence = 0.4 * (risk_score / 100)
               + 0.35 * normalize(dfp_anomaly_score)
               + 0.25 * llm_confidence

    Where normalize(dfp_anomaly_score) = min(1.0, dfp_anomaly_score / 8.0)
    (DFP anomaly_score is mean_abs_z; practical max ~8.0)

Output structure
----------------
{
    "confidence": 0.78,
    "components": {
        "risk":  0.312,   # 0.4 * (risk_score / 100)
        "dfp":   0.263,   # 0.35 * normalized_dfp
        "llm":   0.213    # 0.25 * llm_confidence
    }
}

Usage
-----
    scorer = ConfidenceScorer()
    result = scorer.score(risk_score=74.2, dfp_anomaly_score=5.3, llm_confidence=0.82)

Reference
---------
    modules/ai/explainability/lime_explainer.py
    frontend/backend/services/explainability_service.py

Author: AI Intelligence Layer Team
Date: 2026-04-20
"""

from __future__ import annotations

_DFP_MAX_SCORE = 8.0  # practical ceiling for mean_abs_z normalization
_W_RISK = 0.40
_W_DFP = 0.35
_W_LLM = 0.25


class ConfidenceScorer:
    """Stateless confidence scorer — no model loading required."""

    def score(
        self,
        risk_score: float,
        dfp_anomaly_score: float,
        llm_confidence: float | None,
    ) -> dict:
        """
        Compute ensemble confidence score.

        Args:
            risk_score:        XGBoost risk score, 0–100.
            dfp_anomaly_score: DFP mean_abs_z value, typically 2.5–8.0.
            llm_confidence:    LLM self-reported confidence, 0–1.
                                If None, LLM weight is redistributed to risk.

        Returns:
            dict with ``confidence`` (0–1) and ``components``.
        """
        risk_norm = max(0.0, min(1.0, risk_score / 100.0))
        dfp_norm = max(0.0, min(1.0, dfp_anomaly_score / _DFP_MAX_SCORE))

        if llm_confidence is None:
            # Redistribute LLM weight to risk when LLM data is unavailable
            w_risk = _W_RISK + _W_LLM
            w_dfp = _W_DFP
            w_llm = 0.0
            llm_norm = 0.0
        else:
            w_risk = _W_RISK
            w_dfp = _W_DFP
            w_llm = _W_LLM
            llm_norm = max(0.0, min(1.0, float(llm_confidence)))

        component_risk = round(w_risk * risk_norm, 4)
        component_dfp = round(w_dfp * dfp_norm, 4)
        component_llm = round(w_llm * llm_norm, 4)

        confidence = round(min(1.0, component_risk + component_dfp + component_llm), 4)

        return {
            "confidence": confidence,
            "components": {
                "risk": component_risk,
                "dfp": component_dfp,
                "llm": component_llm,
            },
        }
