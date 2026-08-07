#!/usr/bin/env python3
"""
Risk Scorer Training — XGBoost model training with heuristic labels

Loads all classified TRUE anomalies from enriched_anomalies, generates
heuristic risk labels via compute_heuristic_risk_score(), trains an XGBoost
regressor, and saves the model to data/models/risk_scorer/.

Also runs the full scoring pass: writes risk_score + risk_factors (with SHAP
values) back to every classified TRUE anomaly row via update_classification().

Workflow
--------
    1. Load classified TRUE anomalies from PostgreSQL
    2. Extract features via extract_features()
    3. Generate heuristic labels via compute_heuristic_risk_score()
    4. Train XGBoost (80/20 split, early stopping, MLflow logging)
    5. Save model + feature names to data/models/risk_scorer/
    6. Score all rows → write risk_score + risk_factors (SHAP) back to DB

Usage
-----
    # Full train + score pass
    python -m modules.ai.risk_scoring.risk_scorer_training

    # Dry run — train and print metrics, skip DB writes
    python -m modules.ai.risk_scoring.risk_scorer_training --dry-run

    # Score only (skip training, use existing model)
    python -m modules.ai.risk_scoring.risk_scorer_training --score-only

    # Limit training data
    python -m modules.ai.risk_scoring.risk_scorer_training --limit 500

Reference
---------
    modules/ai/risk_scoring/risk_scorer.py   (RiskScorer, extract_features, heuristic labels)
    modules/ai/risk_scoring/explainer.py     (RiskExplainer — SHAP values)
    modules/ai/enrichment/persistence_service.py  (update_classification)

Author: AI Intelligence Layer Team
Date: 2026-03-10
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import psycopg2
import psycopg2.extras

sys.path.append(str(Path(__file__).parents[3]))

from modules.ai.risk_scoring.risk_scorer import (  # noqa: E402
    DEFAULT_MODEL_DIR,
    FEATURE_NAMES,
    RiskScorer,
    compute_heuristic_risk_score,
    extract_features,
)
from modules.utils.db import get_db_params  # noqa: E402

# Load .env
try:
    from dotenv import load_dotenv

    load_dotenv(Path(__file__).parents[3] / ".env", override=False)
except ImportError:
    pass

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

DB_CONFIG: dict[str, Any] = get_db_params()


# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------


def load_classified_rows(limit: int | None = None) -> list[dict[str, Any]]:
    """
    Load all classified TRUE anomaly rows for training.

    Returns rows that have: is_anomaly=TRUE, classified_at IS NOT NULL.
    """
    query = """
        SELECT
            anomaly_id::text,
            anomaly_score,
            mean_abs_z,
            sub_category,
            severity,
            classification_confidence,
            validation_confidence,
            original_event,
            raw_detection,
            ai_enrichment
        FROM enriched_anomalies
        WHERE is_anomaly = TRUE
          AND classified_at IS NOT NULL
        ORDER BY anomaly_score DESC
    """
    if limit:
        query += f" LIMIT {int(limit)}"

    conn = psycopg2.connect(**DB_CONFIG)
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(query)
            rows = [dict(r) for r in cur.fetchall()]
    finally:
        conn.close()

    logger.info(f"Loaded {len(rows)} classified TRUE anomaly rows.")
    return rows


def write_risk_scores(
    results: list[tuple[str, float, dict[str, Any]]],
) -> tuple[int, int]:
    """
    Write (anomaly_id, risk_score, risk_factors) tuples back to DB.

    Args:
        results: List of (anomaly_id, risk_score, risk_factors) tuples.

    Returns:
        (n_success, n_failed)
    """
    from modules.ai.enrichment.persistence_service import PersistenceService

    n_success = 0
    n_failed = 0

    with PersistenceService(batch_mode=True, enable_kafka=False) as persistence:
        for anomaly_id, risk_score, risk_factors in results:
            # We need the current root_cause + severity to pass to update_classification
            # (the method requires them even on a partial update).
            # Fetch them in the same connection.
            try:
                if persistence.postgres_conn is None:
                    raise RuntimeError("DB connection unavailable")
                with persistence.postgres_conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                    cur.execute(
                        "SELECT root_cause, severity, sub_category, classification_confidence, "
                        "classification_reasoning, classified_by "
                        "FROM enriched_anomalies WHERE anomaly_id = %s",
                        (anomaly_id,),
                    )
                    current = dict(cur.fetchone() or {})

                ok = persistence.update_classification(
                    anomaly_id=anomaly_id,
                    root_cause=current.get("root_cause", ""),
                    severity=current.get("severity", "LOW"),
                    sub_category=current.get("sub_category"),
                    confidence=current.get("classification_confidence"),
                    reasoning=current.get("classification_reasoning"),
                    classified_by=current.get("classified_by"),
                    risk_score=risk_score,
                    risk_factors=risk_factors,
                )
                if ok:
                    n_success += 1
                else:
                    n_failed += 1
            except Exception as exc:
                logger.warning(f"Failed to write risk score for {anomaly_id}: {exc}")
                n_failed += 1

    return n_success, n_failed


# ---------------------------------------------------------------------------
# Training
# ---------------------------------------------------------------------------


def train(
    rows: list[dict[str, Any]],
    model_dir: Path = DEFAULT_MODEL_DIR,
    dry_run: bool = False,
) -> RiskScorer:
    """
    Train XGBoost risk scorer on heuristic-labelled rows.

    Args:
        rows:      Classified enriched_anomalies rows.
        model_dir: Where to save the trained model.
        dry_run:   If True, skip saving the model.

    Returns:
        Trained RiskScorer instance.
    """
    try:
        import xgboost as xgb
    except ImportError as e:
        raise ImportError("xgboost not installed. Run: pip install xgboost") from e

    import joblib
    from sklearn.metrics import mean_absolute_error, r2_score
    from sklearn.model_selection import train_test_split
    from sklearn.preprocessing import StandardScaler

    logger.info("Extracting features and generating heuristic labels…")
    all_features = [extract_features(r) for r in rows]
    labels = np.array([compute_heuristic_risk_score(r) for r in rows], dtype=np.float32)

    X = np.array(
        [[f.get(n, 0.0) for n in FEATURE_NAMES] for f in all_features],
        dtype=np.float32,
    )

    logger.info(f"Dataset: {X.shape[0]} rows × {X.shape[1]} features")
    logger.info(f"Label range: {labels.min():.1f}–{labels.max():.1f}  mean={labels.mean():.1f}")

    X_train, X_val, y_train, y_val = train_test_split(X, labels, test_size=0.20, random_state=42)

    # Fit scaler on training split only — prevents data leakage from validation set.
    # XGBoost trees are scale-invariant (split thresholds shift to match), so this
    # has no predictive effect; the artifact is saved for docstring / sklearn-pipeline
    # consistency and so that future sklearn-wrapping code works out of the box.
    scaler = StandardScaler()
    X_train = scaler.fit_transform(X_train).astype(np.float32)
    X_val = scaler.transform(X_val).astype(np.float32)

    dtrain = xgb.DMatrix(X_train, label=y_train, feature_names=FEATURE_NAMES)
    dval = xgb.DMatrix(X_val, label=y_val, feature_names=FEATURE_NAMES)

    params = {
        "objective": "reg:squarederror",
        "eval_metric": "rmse",
        "max_depth": 6,
        "learning_rate": 0.05,
        "n_estimators": 500,
        "subsample": 0.8,
        "colsample_bytree": 0.8,
        "min_child_weight": 3,
        "reg_alpha": 0.1,
        "reg_lambda": 1.0,
        "seed": 42,
        "verbosity": 0,
    }

    logger.info("Training XGBoost…")

    booster = xgb.train(
        params,
        dtrain,
        num_boost_round=500,
        evals=[(dtrain, "train"), (dval, "val")],
        early_stopping_rounds=30,
        verbose_eval=50,
    )

    # Evaluate
    y_pred_val = booster.predict(dval)
    mae = float(mean_absolute_error(y_val, y_pred_val))
    r2 = float(r2_score(y_val, y_pred_val))

    logger.info(f"Validation MAE: {mae:.2f}  R²: {r2:.4f}")

    _mlflow_log(params, mae, r2)

    scorer = RiskScorer(model_dir=model_dir)

    if not dry_run:
        # Save first, then reload via the sklearn API path — this is what SHAP requires.
        # XGBRegressor.load_model() sets internal fitted state; the _Booster-hack does not.
        model_dir.mkdir(parents=True, exist_ok=True)
        booster.save_model(str(model_dir / "xgboost_risk_scorer.json"))
        with open(model_dir / "feature_names.json", "w") as f:
            json.dump(FEATURE_NAMES, f, indent=2)
        joblib.dump(scaler, model_dir / "feature_scaler.joblib")
        logger.info(f"Model saved to {model_dir}")
        scorer.load()  # reloads model + scaler via RiskScorer.load() — SHAP-compatible
    else:
        # dry_run: SHAP is skipped anyway, so a lightweight wrapper is fine.
        scorer._model = xgb.XGBRegressor()
        scorer._model._Booster = booster  # type: ignore[attr-defined]
        scorer._scaler = scaler
        scorer._feature_names = list(FEATURE_NAMES)
        scorer.is_loaded = True

    return scorer


def _mlflow_log(params: dict[str, Any], mae: float, r2: float) -> None:
    """Log params + metrics to MLflow. No-op if MLflow is unavailable or fails."""
    try:
        import mlflow

        mlflow.set_tracking_uri(os.getenv("MLFLOW_TRACKING_URI", "http://localhost:5001"))
        mlflow.set_experiment("risk_scorer")
        with mlflow.start_run(run_name=f"risk_scorer_{datetime.now(tz=timezone.utc).strftime('%Y%m%d_%H%M%S')}"):
            mlflow.log_params(params)
            mlflow.log_metrics({"val_mae": mae, "val_r2": r2})
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def run(
    limit: int | None = None,
    model_dir: Path = DEFAULT_MODEL_DIR,
    dry_run: bool = False,
    score_only: bool = False,
    use_shap: bool = True,
) -> dict[str, Any]:
    t0 = datetime.now(tz=timezone.utc)

    # 1. Load data
    rows = load_classified_rows(limit=limit)
    if not rows:
        logger.error("No classified rows found. Run labeling_worker first.")
        return {"error": "no_data"}

    # 2. Train (or load existing model)
    if score_only:
        logger.info("--score-only: loading existing model…")
        scorer = RiskScorer(model_dir=model_dir)
        scorer.load()
    else:
        scorer = train(rows, model_dir=model_dir, dry_run=dry_run)

    # 3. Score all rows
    logger.info(f"Scoring {len(rows)} rows…")

    scored: list[tuple[Any, float, dict[str, Any]]] = []

    if use_shap and not dry_run:
        try:
            from modules.ai.risk_scoring.explainer import RiskExplainer

            explainer = RiskExplainer(scorer)
            explanations = explainer.explain_batch(rows)
            scored = [(r["anomaly_id"], exp["risk_score"], exp) for r, exp in zip(rows, explanations, strict=False)]
            logger.info("SHAP explanations computed.")
        except Exception:
            import traceback

            logger.warning(f"SHAP failed — falling back to basic risk_factors.\n{traceback.format_exc()}")
            use_shap = False

    if not use_shap or dry_run:
        batch_results = scorer.predict_batch(rows)
        scored = [(r["anomaly_id"], score, factors) for r, (score, factors) in zip(rows, batch_results, strict=False)]

    # Score stats
    scores = [s for _, s, _ in scored]
    logger.info(
        f"Score distribution: min={min(scores):.1f}  max={max(scores):.1f}  mean={sum(scores) / len(scores):.1f}"
    )

    bands = {"0-25": 0, "25-50": 0, "50-75": 0, "75-100": 0}
    for s in scores:
        if s < 25:
            bands["0-25"] += 1
        elif s < 50:
            bands["25-50"] += 1
        elif s < 75:
            bands["50-75"] += 1
        else:
            bands["75-100"] += 1
    logger.info(f"Risk bands: {bands}")

    # 4. Write to DB
    n_success = n_failed = 0
    if not dry_run:
        logger.info("Writing risk scores to DB…")
        n_success, n_failed = write_risk_scores(scored)
        logger.info(f"Written: {n_success} success, {n_failed} failed.")
    else:
        logger.info("[DRY RUN] Skipping DB writes.")
        n_success = len(scored)

    elapsed = (datetime.now(tz=timezone.utc) - t0).total_seconds()

    summary = {
        "n_rows": len(rows),
        "n_scored": len(scored),
        "n_written": n_success,
        "n_failed": n_failed,
        "score_min": round(min(scores), 2),
        "score_max": round(max(scores), 2),
        "score_mean": round(sum(scores) / len(scores), 2),
        "risk_bands": bands,
        "elapsed_seconds": round(elapsed, 1),
        "shap_used": use_shap and not dry_run,
    }

    print("\n" + "=" * 60)
    print("Risk Scorer — Run Summary")
    print("=" * 60)
    for k, v in summary.items():
        print(f"  {k:<25} {v}")
    print("=" * 60)

    return summary


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Train XGBoost risk scorer and score all classified anomalies")
    parser.add_argument("--dry-run", action="store_true", help="Train but skip DB writes")
    parser.add_argument("--score-only", action="store_true", help="Skip training, use existing model")
    parser.add_argument("--no-shap", action="store_true", help="Skip SHAP, use basic risk_factors")
    parser.add_argument("--limit", type=int, default=None, help="Limit training rows")
    parser.add_argument("--model-dir", default=str(DEFAULT_MODEL_DIR))
    args = parser.parse_args()

    run(
        limit=args.limit,
        model_dir=Path(args.model_dir),
        dry_run=args.dry_run,
        score_only=args.score_only,
        use_shap=not args.no_shap,
    )
