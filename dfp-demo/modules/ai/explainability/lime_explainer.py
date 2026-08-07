#!/usr/bin/env python3
"""
LIME Explainer — Local Interpretable Model-Agnostic Explanations

Generates local linear approximations for individual XGBoost risk score
predictions, helping analysts understand *why* a specific anomaly was
scored the way it was.

Uses lime.lime_tabular.LimeTabularExplainer on the risk scorer feature space.
Generates 5 most-influential feature explanations with 200 perturbed samples
(~0.3 s per call on a modern laptop).

Output structure
----------------
{
    "lime_weights": [
        {"feature": "anomaly_score", "weight": 0.23, "value": 14.32},
        {"feature": "sub_category_risk", "weight": -0.11, "value": 0.90},
        ...
    ]
}

Usage
-----
    explainer = LimeExplainer()
    result = explainer.explain(row_dict, db_conn)

Reference
---------
    modules/ai/risk_scoring/risk_scorer.py  — extract_features()
    modules/ai/explainability/confidence_scorer.py

Author: AI Intelligence Layer Team
Date: 2026-04-20
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

import numpy as np
import psycopg2.extras

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)

# Feature names in the same order as extract_features() returns them.
FEATURE_NAMES = [
    "anomaly_score",
    "mean_abs_z",
    "feature_count",
    "event_count",
    "sub_category_risk",
    "severity_score",
    "classification_confidence",
    "is_managed",
    "is_compliant",
    "trust_score",
    "os_risk",
    "is_high_risk_country",
    "is_foreign",
    "baseline_strength",
    "baseline_available",
    "related_anomalies_count",
    "graph_relationship_count",
    "similar_count",
    "cold_start",
    "validation_confidence",
]

# Human-readable labels for display
FEATURE_LABELS: dict[str, str] = {
    "anomaly_score": "DFP Anomaly Score",
    "mean_abs_z": "Mean Absolute Z-Score",
    "feature_count": "Anomalous Feature Count",
    "event_count": "Event Count",
    "sub_category_risk": "Root Cause Risk Weight",
    "severity_score": "Severity Score",
    "classification_confidence": "Classification Confidence",
    "is_managed": "Managed Device",
    "is_compliant": "Compliant Device",
    "trust_score": "Device Trust Level",
    "os_risk": "Operating System Risk",
    "is_high_risk_country": "High-Risk Country",
    "is_foreign": "Foreign Location",
    "baseline_strength": "Baseline Strength",
    "baseline_available": "Baseline Available",
    "related_anomalies_count": "Related Anomalies",
    "graph_relationship_count": "Graph Relationships",
    "similar_count": "Similar Past Incidents",
    "cold_start": "Cold Start",
    "validation_confidence": "Validation Confidence",
}

_N_TRAINING_SAMPLES = 200  # rows to load from DB for feature distribution
_N_SAMPLES = 500  # perturbation samples for LIME (higher = more stable)
_N_FEATURES = 5  # top features to return


def _row_to_feature_vector(features: dict[str, float]) -> np.ndarray:
    """Convert a flat feature dict to a numpy vector in FEATURE_NAMES order."""
    return np.array([features.get(f, 0.0) for f in FEATURE_NAMES], dtype=np.float32)


def _load_training_matrix(conn: Any) -> np.ndarray:
    """
    Load a sample of enriched_anomalies rows and extract their feature vectors
    to provide LIME with realistic feature distribution statistics.
    """
    from modules.ai.risk_scoring.risk_scorer import extract_features

    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(
            """
            SELECT
                anomaly_score, mean_abs_z, raw_detection, original_event,
                ai_enrichment, sub_category, severity, classification_confidence,
                validation_confidence
            FROM enriched_anomalies
            WHERE is_anomaly = true
            ORDER BY created_at DESC
            LIMIT %s
            """,
            (_N_TRAINING_SAMPLES,),
        )
        rows = cur.fetchall()

    if not rows:
        # Fallback: return a zero matrix — LIME will still work, just with
        # less accurate feature perturbation distributions.
        logger.warning("No training rows found; using zero matrix for LIME distribution")
        return np.zeros((_N_TRAINING_SAMPLES, len(FEATURE_NAMES)), dtype=np.float32)

    vectors = [_row_to_feature_vector(extract_features(dict(r))) for r in rows]
    return np.array(vectors, dtype=np.float32)


class LimeExplainer:
    """
    Wraps lime.lime_tabular.LimeTabularExplainer for the DFP risk scorer.

    Thread-safety: each LimeExplainer instance is independent; share instances
    only if `training_data` is identical (i.e. same DB snapshot).
    """

    def __init__(self) -> None:
        self._lime_explainer = None  # lazy-loaded on first explain() call
        self._training_data: np.ndarray | None = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def explain(
        self,
        row: dict[str, Any],
        conn: Any,
    ) -> dict[str, Any]:
        """
        Generate a LIME explanation for a single anomaly row.

        Args:
            row:  Raw enriched_anomalies row dict (with JSONB fields already
                  deserialised by psycopg2 RealDictCursor).
            conn: Live psycopg2 connection (used for training-data sampling on
                  first call; kept open by caller).

        Returns:
            dict with ``lime_weights`` list.
        """
        try:
            from lime import lime_tabular

            from modules.ai.risk_scoring.risk_scorer import RiskScorer, extract_features
        except ImportError as exc:
            logger.warning("LIME or risk_scorer not available: %s — returning empty weights", exc)
            return {"lime_weights": []}

        # Lazy load training matrix and LIME explainer
        if self._lime_explainer is None:
            self._training_data = _load_training_matrix(conn)
            self._lime_explainer = lime_tabular.LimeTabularExplainer(
                training_data=self._training_data,
                feature_names=FEATURE_NAMES,
                mode="regression",
                discretize_continuous=True,
                random_state=42,
            )

        # Predict function: XGBoost risk scorer
        scorer = RiskScorer()
        try:
            scorer.load()
        except Exception as exc:
            logger.warning("Risk scorer model not loaded: %s — returning empty weights", exc)
            return {"lime_weights": []}

        def predict_fn(X: np.ndarray) -> np.ndarray:
            results = []
            for vec in X:
                feat_dict = dict(zip(FEATURE_NAMES, vec.tolist(), strict=False))
                score, _ = scorer.predict(feat_dict)
                results.append(score)
            return np.array(results, dtype=np.float32)

        # Feature vector for this row
        features = extract_features(row)
        instance = _row_to_feature_vector(features)

        explanation = self._lime_explainer.explain_instance(
            data_row=instance,
            predict_fn=predict_fn,
            num_features=_N_FEATURES,
            num_samples=_N_SAMPLES,
        )

        lime_weights = []
        for feat_name, weight in explanation.as_list():
            # LIME returns feature names with range conditions like
            # "anomaly_score > 5.00" or "0.65 < trust_score <= 0.80".
            # Match against known feature names to handle all formats.
            base_name = next(
                (fn for fn in FEATURE_NAMES if fn in feat_name),
                feat_name.split(" ")[0].strip(),
            )
            feature_value = features.get(base_name, 0.0)
            lime_weights.append(
                {
                    "feature": base_name,
                    "label": FEATURE_LABELS.get(base_name, base_name),
                    "weight": round(float(weight), 4),
                    "value": round(float(feature_value), 4),
                }
            )

        return {"lime_weights": lime_weights}
