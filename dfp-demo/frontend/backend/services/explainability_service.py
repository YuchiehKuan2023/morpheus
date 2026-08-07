"""
Explainability Service — reads SHAP, computes LIME + confidence for an anomaly

Wraps the three explainability modules (SHAP from DB, LIME on-demand,
ConfidenceScorer) into a single `get_explanation(anomaly_id, conn)` call
that the anomalies route can call with a live DB connection.

Output shape (returned as plain dict, serialised to JSON by FastAPI):
{
    "anomaly_id": "...",
    "shap": {
        "base_value": float | null,
        "prediction": float | null,
        "shap_used": bool,
        "top_drivers": [{"feature": str, "label": str, "contribution": float, "value": float}],
        "top_mitigators": [{"feature": str, "label": str, "contribution": float, "value": float}],
        "shap_values": {feature_name: float, ...}
    },
    "lime": {
        "lime_weights": [{"feature": str, "label": str, "weight": float, "value": float}]
    },
    "confidence": {
        "confidence": float,
        "components": {"risk": float, "dfp": float, "llm": float}
    }
}
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path
from typing import Any

import psycopg2.extras

sys.path.append(str(Path(__file__).resolve().parents[3]))

logger = logging.getLogger(__name__)

# Human-readable feature labels (mirrors lime_explainer.FEATURE_LABELS)
_FEATURE_LABELS: dict[str, str] = {
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


def _label(feature: str) -> str:
    return _FEATURE_LABELS.get(feature, feature.replace("_", " ").title())


def _enrich_shap(risk_factors: dict) -> dict:
    """Annotate SHAP driver/mitigator entries with human-readable labels."""
    if not risk_factors:
        return {}

    def _annotate(entries: list) -> list:
        result = []
        for e in entries or []:
            result.append(
                {
                    **e,
                    "label": _label(e.get("feature", "")),
                }
            )
        return result

    return {
        "base_value": risk_factors.get("base_value"),
        "prediction": risk_factors.get("risk_score"),
        "shap_used": bool(risk_factors.get("shap_used", False)),
        "top_drivers": _annotate(risk_factors.get("top_drivers") or []),
        "top_mitigators": _annotate(risk_factors.get("top_mitigators") or []),
        "shap_values": risk_factors.get("shap_values") or {},
    }


def get_explanation(anomaly_id: str, conn) -> dict[str, Any]:
    """
    Fetch SHAP data from DB, compute LIME + confidence on the fly.

    Args:
        anomaly_id: UUID string.
        conn:       Open psycopg2 connection (managed by caller via get_db()).

    Returns:
        Explanation dict (see module docstring).

    Raises:
        ValueError: if anomaly not found.
    """
    # ── 1. Fetch the anomaly row ────────────────────────────────────────────
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(
            """
            SELECT
                ea.anomaly_id,
                ea.anomaly_score,
                ea.mean_abs_z,
                ea.risk_score,
                ea.risk_factors,
                ea.sub_category,
                ea.severity,
                ea.classification_confidence,
                ea.validation_confidence,
                ea.raw_detection,
                ea.original_event,
                ea.ai_enrichment,
                le.confidence_score AS llm_confidence
            FROM enriched_anomalies ea
            LEFT JOIN LATERAL (
                SELECT confidence_score
                FROM llm_explanations
                WHERE detection_id = ea.anomaly_id
                ORDER BY version DESC, created_at DESC
                LIMIT 1
            ) le ON true
            WHERE ea.anomaly_id = %s
            """,
            (anomaly_id,),
        )
        row = cur.fetchone()

    if row is None:
        raise ValueError(f"Anomaly {anomaly_id} not found")

    row = dict(row)

    # ── 2. SHAP — from risk_factors if pre-computed, else on-demand ─────────
    risk_factors = row.get("risk_factors") or {}
    if risk_factors.get("top_drivers") or risk_factors.get("top_mitigators"):
        shap_data = _enrich_shap(risk_factors)
    else:
        shap_data = {}
        try:
            from modules.ai.risk_scoring.explainer import RiskExplainer
            from modules.ai.risk_scoring.risk_scorer import RiskScorer

            scorer = RiskScorer()
            scorer.load()
            exp = RiskExplainer(scorer).explain(row)
            shap_data = _enrich_shap({**risk_factors, **exp, "shap_used": True})
        except Exception as exc:
            logger.warning("On-demand SHAP failed (non-fatal): %s", exc)
            shap_data = _enrich_shap(risk_factors)

    # ── 3. LIME — computed on-demand ────────────────────────────────────────
    lime_data: dict = {"lime_weights": []}
    try:
        from modules.ai.explainability.lime_explainer import LimeExplainer

        lime_data = LimeExplainer().explain(row, conn)
    except Exception as exc:
        logger.warning("LIME explanation failed (non-fatal): %s", exc)

    # ── 4. Confidence score ─────────────────────────────────────────────────
    from modules.ai.explainability.confidence_scorer import ConfidenceScorer

    risk_score = float(row.get("risk_score") or 0.0)
    dfp_score = float(row.get("mean_abs_z") or row.get("anomaly_score") or 0.0)
    llm_conf = row.get("llm_confidence")
    llm_conf = float(llm_conf) if llm_conf is not None else None

    confidence_data = ConfidenceScorer().score(
        risk_score=risk_score,
        dfp_anomaly_score=dfp_score,
        llm_confidence=llm_conf,
    )

    return {
        "anomaly_id": str(row["anomaly_id"]),
        "shap": shap_data,
        "lime": lime_data,
        "confidence": confidence_data,
    }
