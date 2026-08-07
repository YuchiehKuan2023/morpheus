#!/usr/bin/env python3
"""
Risk Scorer — XGBoost-based composite risk scoring

Assigns a 0–100 risk score to every TRUE anomaly that has been root-cause
classified (Stage 2).  The score combines:

  • DFP signal   — anomaly_score (mean absolute z-score), feature_count
  • Classification — sub_category (9-class), severity (4-level)
  • Device context — isManaged, isCompliant, trustType, operatingSystem
  • Location       — countryOrRegion (normalised to is_foreign)
  • User history   — total_events in baseline, related_anomalies_count (graph)
  • Similarity     — number of similar past detections found

The XGBoost model is trained in risk_scorer_training.py using rule-based
risk labels derived from the above signal (bootstrapped from domain knowledge).
SHAP explanations are handled by explainer.py.

Architecture
------------
    enriched_anomalies row
        │
        ▼  feature_engineering()
    feature dict (numeric only)
        │
        ▼  RiskScorer.predict(features) → risk_score (0–100)
        │
        ▼  PersistenceService.update_classification(risk_score=, risk_factors=)

Training
--------
    python -m modules.ai.risk_scoring.risk_scorer_training
    → saves model to data/models/risk_scorer/xgboost_risk_scorer.json
    → saves scaler to data/models/risk_scorer/feature_scaler.joblib
    → saves feature_names to data/models/risk_scorer/feature_names.json

Inference (single record)
--------------------------
    scorer = RiskScorer()
    scorer.load()
    score, factors = scorer.predict(row_dict)

Inference (batch — recommended)
---------------------------------
    scorer = RiskScorer()
    scorer.load()
    results = scorer.predict_batch(rows)

Reference
---------
    modules/ai/risk_scoring/explainer.py   (SHAP explanations)
    modules/ai/enrichment/persistence_service.py  (update_classification)
    docs/implementation/PROGRESS_TRACKER.md

Author: AI Intelligence Layer Team
Date: 2026-03-10
"""

from __future__ import annotations

import json
import logging
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Any

import numpy as np

if TYPE_CHECKING:
    from sklearn.preprocessing import StandardScaler
    from xgboost import XGBRegressor

sys.path.append(str(Path(__file__).parents[3]))

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------

DEFAULT_MODEL_DIR = Path(__file__).parents[3] / "data" / "models" / "risk_scorer"

# Sub-category → base risk weight (higher = inherently higher risk)
SUB_CATEGORY_BASE_RISK: dict[str, float] = {
    "Impossible Travel": 0.90,
    "Location with Unusual Device": 0.80,
    "Unknown Device": 0.75,
    "Multi-Factor Anomaly": 0.70,
    "Unusual Location": 0.65,
    "Unusual Application": 0.55,
    "Unusual Operating System": 0.50,
    "Unusual Browser": 0.45,
    "Broad Deviation": 0.40,
}

# Severity → multiplier
SEVERITY_MULTIPLIER: dict[str, float] = {
    "CRITICAL": 1.0,
    "HIGH": 0.80,
    "MEDIUM": 0.55,
    "LOW": 0.30,
}

# High-risk countries (ISO alpha-2 or full name fragments — checked with `in`)
HIGH_RISK_COUNTRIES = {
    "Russia",
    "China",
    "North Korea",
    "Iran",
    "Belarus",
    "RU",
    "CN",
    "KP",
    "IR",
    "BY",
}


# ---------------------------------------------------------------------------
# Feature engineering
# ---------------------------------------------------------------------------


def extract_features(row: dict[str, Any]) -> dict[str, float]:
    """
    Convert a raw enriched_anomalies row into a flat numeric feature dict.

    All features are floats.  Categorical variables are one-hot or ordinal
    encoded inline so the caller never needs to touch a sklearn encoder.

    Args:
        row: dict from enriched_anomalies (may contain nested JSONB dicts
             already deserialised by psycopg2 RealDictCursor).

    Returns:
        Flat dict of float features.  Missing values → 0.0.
    """
    feat: dict[str, float] = {}

    # ── DFP signal ──────────────────────────────────────────────────────────
    feat["anomaly_score"] = float(row.get("anomaly_score") or 0.0)
    feat["mean_abs_z"] = float(row.get("mean_abs_z") or feat["anomaly_score"])

    raw = _json(row.get("raw_detection"))
    feat["feature_count"] = float(raw.get("feature_count") or 0.0)
    feat["event_count"] = float(raw.get("event_count") or 1.0)

    # ── Classification signal ────────────────────────────────────────────────
    sub_cat = str(row.get("sub_category") or "")
    feat["sub_category_risk"] = SUB_CATEGORY_BASE_RISK.get(sub_cat, 0.40)

    severity = str(row.get("severity") or "LOW")
    feat["severity_score"] = SEVERITY_MULTIPLIER.get(severity, 0.30)

    feat["classification_confidence"] = float(row.get("classification_confidence") or 0.0)

    # ── Device context (from original_event.properties.deviceDetail) ────────
    orig = _json(row.get("original_event"))
    props = _json(orig.get("properties"))
    device = _json(props.get("deviceDetail"))

    feat["is_managed"] = 1.0 if device.get("isManaged") is True else 0.0
    feat["is_compliant"] = 1.0 if device.get("isCompliant") is True else 0.0

    trust = str(device.get("trustType") or "").lower()
    if "hybrid" in trust or "azure ad joined" in trust:
        feat["trust_score"] = 1.0
    elif "registered" in trust:
        feat["trust_score"] = 0.5
    else:
        feat["trust_score"] = 0.0  # unknown / unmanaged

    # OS risk: mobile OSes are slightly higher risk than managed workstations
    os_val = str(device.get("operatingSystem") or "").lower()
    if any(x in os_val for x in ["android", "ios"]):
        feat["os_risk"] = 0.7
    elif "windows" in os_val or "macos" in os_val:
        feat["os_risk"] = 0.3
    else:
        feat["os_risk"] = 0.5  # unknown

    # ── Location risk ────────────────────────────────────────────────────────
    loc = _json(orig.get("location"))
    country = str(loc.get("countryOrRegion") or "")
    feat["is_high_risk_country"] = 1.0 if any(c in country for c in HIGH_RISK_COUNTRIES) else 0.0
    feat["is_foreign"] = 0.0 if country in ("United States", "US", "") else 1.0

    # ── User baseline (ai_enrichment.user_baseline) ─────────────────────────
    ai = _json(row.get("ai_enrichment"))
    baseline = _json(ai.get("user_baseline"))

    total_events = int(baseline.get("total_events") or 0)
    # More training history → lower uncertainty → slightly lower risk
    feat["baseline_strength"] = min(float(total_events) / 1000.0, 1.0)
    feat["baseline_available"] = 1.0 if baseline.get("baseline_source") else 0.0

    # ── Graph context ────────────────────────────────────────────────────────
    graph = _json(ai.get("graph_context"))
    feat["related_anomalies_count"] = float(graph.get("related_anomalies_count") or 0.0)
    feat["graph_relationship_count"] = float(len(graph.get("detection_relationships") or []))

    # ── Similarity context ───────────────────────────────────────────────────
    similar = ai.get("similar_detections") or []
    feat["similar_count"] = float(len(similar))
    feat["cold_start"] = 1.0 if ai.get("cold_start") else 0.0

    # ── Validation signal ────────────────────────────────────────────────────
    feat["validation_confidence"] = float(row.get("validation_confidence") or 0.0)

    return feat


def compute_heuristic_risk_score(row: dict[str, Any]) -> float:
    """
    Rule-based risk score (0–100) used as training labels for XGBoost.

    This is the ground-truth label generator for the bootstrapped model.
    It is NOT used at inference time once the model is trained.

    Formula:
        score = base_risk × severity_mult × context_boost × 100
        clamped to [0, 100]

    Context boosts:
        • Unmanaged device     → +20%
        • Non-compliant device → +15%
        • High-risk country    → +25%
        • No baseline          → +10%
        • High anomaly_score   → proportional
    """
    feat = extract_features(row)

    base = feat["sub_category_risk"] * feat["severity_score"]

    # Scale by normalised anomaly score (cap at score=20 → 1.0, matching realistic max)
    score_factor = min(feat["anomaly_score"] / 20.0, 1.0)
    base = base * (0.5 + 0.5 * score_factor)

    # Context multipliers
    multiplier = 1.0
    if feat["is_managed"] == 0.0:
        multiplier += 0.20
    if feat["is_compliant"] == 0.0:
        multiplier += 0.15
    if feat["is_high_risk_country"] == 1.0:
        multiplier += 0.25
    if feat["baseline_available"] == 0.0:
        multiplier += 0.10
    if feat["related_anomalies_count"] > 2:
        multiplier += 0.15
    if feat["cold_start"] == 1.0:
        multiplier += 0.05

    raw = base * multiplier * 100.0
    return float(min(max(raw, 0.0), 100.0))


def _json(val: Any) -> dict:
    """Safely coerce a value to dict — handles None, str (JSON), dict."""
    if val is None:
        return {}
    if isinstance(val, dict):
        return val
    if isinstance(val, str):
        try:
            parsed = json.loads(val)
            return parsed if isinstance(parsed, dict) else {}
        except (json.JSONDecodeError, ValueError):
            return {}
    return {}


# ---------------------------------------------------------------------------
# Risk Scorer class
# ---------------------------------------------------------------------------


class RiskScorer:
    """
    XGBoost-based risk scorer for classified anomaly detections.

    Usage:
        scorer = RiskScorer()
        scorer.load()                          # load trained model
        score, factors = scorer.predict(row)   # single record
        results = scorer.predict_batch(rows)   # batch
    """

    def __init__(self, model_dir: str | Path = DEFAULT_MODEL_DIR) -> None:
        self.model_dir = Path(model_dir)
        self._model: XGBRegressor | None = None
        self._scaler: StandardScaler | None = None
        self._feature_names: list[str] = []
        self.is_loaded = False

    # ------------------------------------------------------------------
    # Load / save
    # ------------------------------------------------------------------

    def load(self) -> RiskScorer:
        """Load trained XGBoost model from model_dir."""
        try:
            import xgboost as xgb
        except ImportError as e:
            raise ImportError("xgboost not installed. Run: pip install xgboost") from e

        model_path = self.model_dir / "xgboost_risk_scorer.json"
        names_path = self.model_dir / "feature_names.json"

        if not model_path.exists():
            raise FileNotFoundError(
                f"Risk scorer model not found at {model_path}. "
                "Run: python -m modules.ai.risk_scoring.risk_scorer_training"
            )

        self._model = xgb.XGBRegressor()
        self._model.load_model(str(model_path))

        if names_path.exists():
            with open(names_path) as f:
                self._feature_names = json.load(f)
        else:
            # Fall back to a stable ordering derived from extract_features
            self._feature_names = list(extract_features(_DUMMY_ROW).keys())

        # Load scaler if present (absent for models trained before scaler was introduced).
        # N.B. XGBoost trees are scale-invariant, so the scaler provides no predictive
        # benefit; it is saved purely so the artifact set matches the module docstring
        # and for consistency with sklearn-pipeline conventions.
        scaler_path = self.model_dir / "feature_scaler.joblib"
        if scaler_path.exists():
            import joblib

            self._scaler = joblib.load(scaler_path)
            logger.debug(f"Feature scaler loaded from {scaler_path}")

        self.is_loaded = True
        logger.info(f"RiskScorer loaded from {self.model_dir} ({len(self._feature_names)} features)")
        return self

    def save(self, model_dir: str | Path | None = None) -> Path:
        """Save model and feature names to model_dir."""
        if self._model is None:
            raise RuntimeError("No model loaded to save.")

        save_dir = Path(model_dir or self.model_dir)
        save_dir.mkdir(parents=True, exist_ok=True)

        self._model.save_model(str(save_dir / "xgboost_risk_scorer.json"))
        with open(save_dir / "feature_names.json", "w") as f:
            json.dump(self._feature_names, f, indent=2)

        if self._scaler is not None:
            import joblib

            joblib.dump(self._scaler, save_dir / "feature_scaler.joblib")

        logger.info(f"RiskScorer saved to {save_dir}")
        return save_dir

    # ------------------------------------------------------------------
    # Inference
    # ------------------------------------------------------------------

    def predict(self, row: dict[str, Any]) -> tuple[float, dict[str, Any]]:
        """
        Predict risk score for a single enriched_anomalies row.

        Args:
            row: Full row dict from enriched_anomalies.

        Returns:
            (risk_score, risk_factors)
            risk_score:   float 0–100
            risk_factors: dict with raw features + score breakdown for UI display
        """
        if not self.is_loaded or self._model is None:
            raise RuntimeError("Model not loaded. Call scorer.load() first.")

        features = extract_features(row)
        X = self._features_to_array([features])

        raw = float(self._model.predict(X)[0])
        risk_score = float(min(max(raw, 0.0), 100.0))

        risk_factors = self._build_risk_factors(features, risk_score)
        return risk_score, risk_factors

    def predict_batch(
        self,
        rows: list[dict[str, Any]],
    ) -> list[tuple[float, dict[str, Any]]]:
        """
        Predict risk scores for a list of enriched_anomalies rows.

        Args:
            rows: List of row dicts.

        Returns:
            List of (risk_score, risk_factors) tuples in the same order.
        """
        if not self.is_loaded or self._model is None:
            raise RuntimeError("Model not loaded. Call scorer.load() first.")

        all_features = [extract_features(r) for r in rows]
        X = self._features_to_array(all_features)

        raw_scores = self._model.predict(X)

        results = []
        for _i, (feat, raw) in enumerate(zip(all_features, raw_scores, strict=False)):
            score = float(min(max(float(raw), 0.0), 100.0))
            factors = self._build_risk_factors(feat, score)
            results.append((score, factors))

        return results

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _features_to_array(self, feature_dicts: list[dict[str, float]]) -> np.ndarray:
        """Convert list of feature dicts to (n, p) numpy array in canonical order.

        Applies the feature scaler when one was saved alongside the model.
        Models trained before the scaler was introduced work unchanged
        (scale-invariance of tree splits means predictions are identical).
        """
        names = self._feature_names or list(feature_dicts[0].keys())
        X = np.array([[fd.get(n, 0.0) for n in names] for fd in feature_dicts], dtype=np.float32)
        if self._scaler is not None:
            X = self._scaler.transform(X).astype(np.float32)
        return X

    @staticmethod
    def _build_risk_factors(features: dict[str, float], risk_score: float) -> dict[str, Any]:
        """
        Build a human-readable risk_factors dict for storage in JSONB.

        Structure matches what the frontend risk-factors panel expects.
        """
        factors: dict[str, Any] = {
            "risk_score": round(risk_score, 2),
            "primary_drivers": [],
            "mitigating_factors": [],
            "raw_features": {k: round(v, 4) for k, v in features.items()},
        }

        # Surface the key drivers as named strings for the UI
        if features.get("is_high_risk_country", 0) > 0.5:
            factors["primary_drivers"].append("High-risk country")
        if features.get("is_managed", 1) < 0.5:
            factors["primary_drivers"].append("Unmanaged device")
        if features.get("is_compliant", 1) < 0.5:
            factors["primary_drivers"].append("Non-compliant device")
        if features.get("anomaly_score", 0) > 5.0:  # CRITICAL threshold
            factors["primary_drivers"].append(f"High anomaly score ({features['anomaly_score']:.1f})")
        if features.get("related_anomalies_count", 0) > 2:
            factors["primary_drivers"].append(f"Repeated anomalies ({int(features['related_anomalies_count'])} prior)")
        if features.get("sub_category_risk", 0) >= 0.75:
            factors["primary_drivers"].append("High-risk anomaly category")

        if features.get("is_managed", 0) > 0.5:
            factors["mitigating_factors"].append("Managed device")
        if features.get("is_compliant", 0) > 0.5:
            factors["mitigating_factors"].append("Compliant device")
        if features.get("baseline_available", 0) > 0.5:
            factors["mitigating_factors"].append("Established user baseline")
        if features.get("validation_confidence", 0) > 0.8:
            factors["mitigating_factors"].append(
                f"High validation confidence ({features['validation_confidence']:.0%})"
            )

        return factors


# ---------------------------------------------------------------------------
# Dummy row for feature name extraction (no model needed)
# ---------------------------------------------------------------------------

_DUMMY_ROW: dict[str, Any] = {
    "anomaly_score": 0.0,
    "mean_abs_z": 0.0,
    "raw_detection": {"feature_count": 0, "event_count": 1},
    "sub_category": "",
    "severity": "LOW",
    "classification_confidence": 0.0,
    "original_event": {
        "location": {"countryOrRegion": ""},
        "properties": {
            "deviceDetail": {
                "isManaged": False,
                "isCompliant": False,
                "trustType": "",
                "operatingSystem": "",
            }
        },
    },
    "ai_enrichment": {
        "user_baseline": {"total_events": 0, "baseline_source": None},
        "graph_context": {"related_anomalies_count": 0, "detection_relationships": []},
        "similar_detections": [],
        "cold_start": True,
    },
    "validation_confidence": 0.0,
}

# Canonical feature order (derived once at import time — stable across runs)
FEATURE_NAMES: list[str] = list(extract_features(_DUMMY_ROW).keys())


# ---------------------------------------------------------------------------
# CLI — score a detection by anomaly_id
# ---------------------------------------------------------------------------


def main() -> None:
    import argparse

    import psycopg2
    import psycopg2.extras
    from dotenv import load_dotenv

    load_dotenv(Path(__file__).parents[3] / ".env", override=False)

    parser = argparse.ArgumentParser(description="Score a detection by anomaly_id")
    parser.add_argument("--anomaly-id", required=True, help="UUID from enriched_anomalies")
    parser.add_argument("--model-dir", default=str(DEFAULT_MODEL_DIR))
    parser.add_argument("--heuristic", action="store_true", help="Use heuristic scorer (no model needed)")
    args = parser.parse_args()

    from modules.utils.db import get_db_params

    db_config = get_db_params()

    conn = psycopg2.connect(**db_config)
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                "SELECT * FROM enriched_anomalies WHERE anomaly_id = %s",
                (args.anomaly_id,),
            )
            row = cur.fetchone()
    finally:
        conn.close()

    if not row:
        print(f"Detection not found: {args.anomaly_id}")
        return

    row = dict(row)

    if args.heuristic:
        score = compute_heuristic_risk_score(row)
        features = extract_features(row)
        factors = RiskScorer._build_risk_factors(features, score)
        print(f"\nHeuristic risk score: {score:.1f}/100")
    else:
        scorer = RiskScorer(model_dir=args.model_dir)
        scorer.load()
        score, factors = scorer.predict(row)
        print(f"\nXGBoost risk score: {score:.1f}/100")

    print(f"Primary drivers:     {factors['primary_drivers']}")
    print(f"Mitigating factors:  {factors['mitigating_factors']}")
    print("\nRaw features:")
    for k, v in factors["raw_features"].items():
        print(f"  {k:<35} {v:.4f}")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    main()
