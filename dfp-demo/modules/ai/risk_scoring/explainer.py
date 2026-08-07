#!/usr/bin/env python3
"""
SHAP Explainer — Feature importance and explanation for risk scores

Generates SHAP (SHapley Additive exPlanations) values for the XGBoost
risk scorer, translating model internals into human-readable explanations
that can be surfaced in the SOC dashboard.

Two modes:
    1. explain(row)        — single record, returns top-N feature contributions
    2. explain_batch(rows) — batch, returns list of explanation dicts

Output structure (stored in risk_factors JSONB):
    {
        "risk_score": 74.2,
        "shap_values": {
            "anomaly_score": +18.3,
            "sub_category_risk": +12.1,
            "is_managed": -8.4,
            ...
        },
        "top_drivers": [
            {"feature": "anomaly_score",       "contribution": +18.3, "value": 14.32},
            {"feature": "sub_category_risk",   "contribution": +12.1, "value": 0.90},
            {"feature": "is_high_risk_country","contribution": +9.7,  "value": 1.0}
        ],
        "top_mitigators": [
            {"feature": "is_managed",   "contribution": -8.4, "value": 1.0},
            {"feature": "is_compliant", "contribution": -5.1, "value": 1.0}
        ],
        "primary_drivers": [...],     # human-readable strings from risk_scorer
        "mitigating_factors": [...],  # human-readable strings from risk_scorer
        "raw_features": {...}
    }

Usage
-----
    explainer = RiskExplainer(scorer)
    scorer.load()
    explanation = explainer.explain(row)

Reference
---------
    modules/ai/risk_scoring/risk_scorer.py
    modules/ai/risk_scoring/risk_scorer_training.py

Author: AI Intelligence Layer Team
Date: 2026-03-10
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


class RiskExplainer:
    """
    SHAP-based explainer wrapping a trained RiskScorer.

    Initialise with a loaded RiskScorer instance.

    Args:
        scorer: Loaded RiskScorer (scorer.is_loaded must be True).
        top_n:  Number of top drivers / mitigators to surface in output.
    """

    def __init__(self, scorer: Any, top_n: int = 5) -> None:
        self.scorer = scorer
        self.top_n = top_n
        self._shap_explainer = None

    # ------------------------------------------------------------------
    # Lazy-load SHAP explainer
    # ------------------------------------------------------------------

    def _get_shap_explainer(self) -> Any:
        """Build (once) a shap.TreeExplainer backed by the XGBoost model."""
        if self._shap_explainer is None:
            try:
                import shap
            except ImportError as e:
                raise ImportError("shap not installed. Run: pip install shap") from e

            if not self.scorer.is_loaded or self.scorer._model is None:
                raise RuntimeError("RiskScorer model not loaded.")

            self._shap_explainer = shap.TreeExplainer(self.scorer._model)
            logger.info("SHAP TreeExplainer initialised.")
        return self._shap_explainer

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def explain(self, row: dict[str, Any]) -> dict[str, Any]:
        """
        Generate SHAP explanation for a single row.

        Args:
            row: Full enriched_anomalies row dict.

        Returns:
            Explanation dict — see module docstring for structure.
        """
        import numpy as np

        from modules.ai.risk_scoring.risk_scorer import extract_features

        features = extract_features(row)
        risk_score, base_factors = self.scorer.predict(row)

        X = np.array(
            [[features.get(n, 0.0) for n in self.scorer._feature_names]],
            dtype=np.float32,
        )

        explainer = self._get_shap_explainer()
        shap_values = explainer(X).values[0]  # shape: (n_features,)

        return self._build_explanation(
            features=features,
            shap_values=shap_values,
            risk_score=risk_score,
            base_factors=base_factors,
        )

    def explain_batch(self, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """
        Generate SHAP explanations for a batch of rows.

        More efficient than calling explain() in a loop because SHAP values
        are computed in a single matrix operation.

        Args:
            rows: List of enriched_anomalies row dicts.

        Returns:
            List of explanation dicts in the same order as input.
        """
        import numpy as np

        from modules.ai.risk_scoring.risk_scorer import extract_features

        if not rows:
            return []

        all_features = [extract_features(r) for r in rows]
        batch_results = self.scorer.predict_batch(rows)

        X = np.array(
            [[f.get(n, 0.0) for n in self.scorer._feature_names] for f in all_features],
            dtype=np.float32,
        )

        explainer = self._get_shap_explainer()
        all_shap = explainer(X).values  # shape: (n_rows, n_features)

        explanations = []
        for i, (row_features, (risk_score, base_factors)) in enumerate(zip(all_features, batch_results, strict=False)):
            shap_row = all_shap[i]
            exp = self._build_explanation(
                features=row_features,
                shap_values=shap_row,
                risk_score=risk_score,
                base_factors=base_factors,
            )
            explanations.append(exp)

        return explanations

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _build_explanation(
        self,
        features: dict[str, float],
        shap_values: Any,  # np.ndarray
        risk_score: float,
        base_factors: dict[str, Any],
    ) -> dict[str, Any]:
        """
        Combine SHAP values + base risk_factors into a unified explanation dict.
        """
        feature_names = self.scorer._feature_names
        shap_dict = {name: float(sv) for name, sv in zip(feature_names, shap_values, strict=False)}

        # Split into positive (drivers) and negative (mitigators) contributions
        sorted_by_abs = sorted(shap_dict.items(), key=lambda x: abs(x[1]), reverse=True)

        top_drivers = [
            {
                "feature": name,
                "contribution": round(sv, 3),
                "value": round(features.get(name, 0.0), 4),
            }
            for name, sv in sorted_by_abs
            if sv > 0
        ][: self.top_n]

        top_mitigators = [
            {
                "feature": name,
                "contribution": round(sv, 3),
                "value": round(features.get(name, 0.0), 4),
            }
            for name, sv in sorted_by_abs
            if sv < 0
        ][: self.top_n]

        return {
            "risk_score": round(risk_score, 2),
            "shap_values": {k: round(v, 3) for k, v in shap_dict.items()},
            "top_drivers": top_drivers,
            "top_mitigators": top_mitigators,
            "primary_drivers": base_factors.get("primary_drivers", []),
            "mitigating_factors": base_factors.get("mitigating_factors", []),
            "raw_features": base_factors.get("raw_features", {}),
        }
