"""Forecast endpoints — anomaly trend + Prophet forward prediction."""

import logging
import sys
from pathlib import Path

from auth_utils import get_current_user
from db import get_db
from fastapi import APIRouter, Depends, HTTPException, Query

# Ensure project root is importable
sys.path.append(str(Path(__file__).resolve().parents[3]))

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("")
def get_forecast(
    periods: int = Query(default=30, ge=7, le=90, description="Days to forecast"),
    user_id: str | None = Query(default=None, description="Per-user forecast (optional)"),
    _user: dict = Depends(get_current_user),
):
    """Return historical anomaly counts + Prophet forward forecast with confidence intervals."""
    from modules.ai.forecasting.prophet_forecaster import AnomalyForecaster

    try:
        fc = AnomalyForecaster()
        model_dir = AnomalyForecaster.model_dir_for(user_id)

        if not fc.load(model_dir=model_dir):
            # No saved model for this scope — train on the fly (first request bootstraps)
            result = fc.train(user_id=user_id)
            if not result.get("trained"):
                return {
                    "historical": [],
                    "forecast": [],
                    "meta": {"error": result.get("reason", "Insufficient data")},
                }
            fc.save(model_dir=model_dir)

        prediction = fc.predict(periods=periods)
        return prediction
    except Exception as e:
        logger.exception("Forecast generation failed")
        raise HTTPException(status_code=500, detail="Forecast generation failed") from e


@router.post("/retrain")
def trigger_retrain(
    force: bool = Query(default=False, description="Force retrain regardless of threshold"),
    _user: dict = Depends(get_current_user),
):
    """Manually trigger forecast model retraining."""
    from modules.ai.forecasting.prophet_forecaster import AnomalyForecaster

    try:
        fc = AnomalyForecaster()
        if force:
            result = fc.force_retrain()
        else:
            result = fc.check_and_retrain()
        return result
    except Exception as e:
        logger.exception("Forecast retrain failed")
        raise HTTPException(status_code=500, detail="Forecast retrain failed") from e


@router.get("/summary")
def get_forecast_summary(_user: dict = Depends(get_current_user)):
    """Return lightweight summary: data availability, model status, real vs synthetic counts."""
    try:
        from modules.ai.forecasting.prophet_forecaster import REAL_ONLY_THRESHOLD

        with get_db() as conn:
            import psycopg2.extras

            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute("""
                    SELECT
                        COUNT(*) AS total,
                        COUNT(*) FILTER (
                            WHERE validated_by IS NULL OR validated_by != 'heuristic_midband'
                        ) AS real_count,
                        COUNT(*) FILTER (
                            WHERE validated_by = 'heuristic_midband'
                        ) AS synthetic_count,
                        MIN(timestamp) AS earliest,
                        MAX(timestamp) AS latest,
                        COUNT(DISTINCT user_id) AS user_count
                    FROM enriched_anomalies
                """)
                stats = dict(cur.fetchone())

                # Model status
                cur.execute("""
                    SELECT status, started_at, completed_at, anomalies_at_retrain, duration_seconds
                    FROM classifier_retrain_log
                    WHERE classifier_type = 'forecast'
                    ORDER BY created_at DESC
                    LIMIT 1
                """)
                last_retrain = cur.fetchone()

        return {
            "data": {
                "total_anomalies": stats["total"],
                "real_anomalies": stats["real_count"],
                "synthetic_anomalies": stats["synthetic_count"],
                "earliest": stats["earliest"].isoformat() if stats["earliest"] else None,
                "latest": stats["latest"].isoformat() if stats["latest"] else None,
                "user_count": stats["user_count"],
                "ready_for_real_only": stats["real_count"] >= REAL_ONLY_THRESHOLD,
            },
            "model": dict(last_retrain) if last_retrain else None,
        }
    except Exception as e:
        logger.exception("Forecast summary failed")
        raise HTTPException(status_code=500, detail="Database error") from e
