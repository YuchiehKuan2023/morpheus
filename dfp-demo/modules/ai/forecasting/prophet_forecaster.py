"""
Prophet Forecaster — time-series anomaly rate prediction.

Trains a Facebook Prophet model on historical anomaly counts (daily
aggregation) from enriched_anomalies.  Produces forward forecasts with
confidence intervals that power the dashboard chart and capacity-planning
features.

Retraining
----------
The forecaster is designed to plug into the existing feedback loop
(``scripts/run_retrain_runner.py``).  When enough *new* anomalies
accumulate (controlled by ``FORECAST_RETRAIN_THRESHOLD``), the runner
calls ``check_and_retrain()``, which rebuilds the Prophet model from
the latest DB data and persists it to disk + MLflow.

Usage (standalone)
------------------
    from modules.ai.forecasting.prophet_forecaster import AnomalyForecaster

    fc = AnomalyForecaster()
    fc.train()                        # train from DB data
    result = fc.predict(periods=30)   # 30-day forecast
    fc.save()                         # persist to disk

Author: Tomasz Zabek <tzabek@deloitte.co.uk>
Date: 2026-05-07
"""

from __future__ import annotations

import json
import logging
import os
import pickle
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(PROJECT_ROOT))

from modules.utils.db import get_db_params  # noqa: E402

try:
    from dotenv import load_dotenv

    load_dotenv(PROJECT_ROOT / ".env", override=False)
except ImportError:
    pass

import psycopg2  # noqa: E402
import psycopg2.extras  # noqa: E402

logger = logging.getLogger(__name__)

# ── Configuration ─────────────────────────────────────────────────────────────
DB_CONFIG: dict[str, Any] = get_db_params()
MODEL_DIR = PROJECT_ROOT / "data" / "models" / "forecast"
MODEL_PATH = MODEL_DIR / "prophet_model.pkl"
META_PATH = MODEL_DIR / "forecast_meta.json"

# Minimum training rows (days with data) for a meaningful model
MIN_TRAINING_DAYS = 14

# How many new anomalies must accumulate before retraining (used by runner)
FORECAST_RETRAIN_THRESHOLD = int(os.getenv("FORECAST_RETRAIN_THRESHOLD", "100"))

# Whether to use only real anomalies (non-heuristic_midband) or all
# When real anomaly count < REAL_ONLY_THRESHOLD, use all data;
# once above, switch to real-only for better signal
REAL_ONLY_THRESHOLD = int(os.getenv("FORECAST_REAL_ONLY_THRESHOLD", "500"))


class AnomalyForecaster:
    """Prophet-based anomaly rate forecaster."""

    def __init__(self, db_config: dict | None = None) -> None:
        self.db_config = db_config or DB_CONFIG
        self._model = None
        self._meta: dict[str, Any] = {}

    @staticmethod
    def model_dir_for(user_id: str | None = None) -> Path:
        """Return the model directory for a given scope.

        Global model  → ``data/models/forecast/``
        Per-user model → ``data/models/forecast/users/{user_id}/``
        """
        if user_id:
            return MODEL_DIR / "users" / user_id
        return MODEL_DIR

    # ──────────────────────────────────────────────────────────────────────────
    # Training
    # ──────────────────────────────────────────────────────────────────────────

    def train(self, user_id: str | None = None) -> dict[str, Any]:
        """Train Prophet on daily anomaly counts from the database.

        Parameters
        ----------
        user_id : str | None
            If provided, train a per-user model.  Otherwise, platform-wide.

        Returns
        -------
        dict with training metadata (rows, date range, mape, etc.)
        """
        from prophet import Prophet

        df = self._load_daily_counts(user_id)

        if len(df) < MIN_TRAINING_DAYS:
            msg = f"Only {len(df)} days of data (need {MIN_TRAINING_DAYS})"
            logger.warning(msg)
            return {"trained": False, "reason": msg, "days": len(df)}

        model = Prophet(
            yearly_seasonality=False,  # type: ignore[arg-type]  # Prophet accepts bool
            weekly_seasonality=True,  # type: ignore[arg-type]
            daily_seasonality=False,  # type: ignore[arg-type]
            changepoint_prior_scale=0.1,
            interval_width=0.90,
        )
        model.fit(df)

        self._model = model
        self._meta = {
            "trained_at": datetime.now(timezone.utc).isoformat(),
            "user_id": user_id,
            "training_days": len(df),
            "date_range": [str(df["ds"].min().date()), str(df["ds"].max().date())],
            "total_anomalies": int(df["y"].sum()),
            "data_mode": self._data_mode(),
        }

        logger.info(
            "Prophet model trained: %d days, %d anomalies, mode=%s",
            len(df),
            int(df["y"].sum()),
            self._meta["data_mode"],
        )
        return {"trained": True, **self._meta}

    # ──────────────────────────────────────────────────────────────────────────
    # Prediction
    # ──────────────────────────────────────────────────────────────────────────

    def predict(self, periods: int = 30) -> dict[str, Any]:
        """Generate forward forecast.

        Parameters
        ----------
        periods : int
            Number of future days to forecast.

        Returns
        -------
        dict with keys:
            historical  — list of {date, count}
            forecast    — list of {date, yhat, yhat_lower, yhat_upper}
            meta        — training metadata
        """
        if self._model is None:
            self.load()
        if self._model is None:
            return {"error": "No trained model available"}

        future = self._model.make_future_dataframe(periods=periods, freq="D")
        prediction = self._model.predict(future)

        # Split into historical and forecast periods
        training_end = pd.Timestamp(self._meta["date_range"][1])

        historical = self._load_daily_counts(self._meta.get("user_id"))

        hist_records = [
            {"date": row["ds"].strftime("%Y-%m-%d"), "count": int(row["y"])} for _, row in historical.iterrows()
        ]

        forecast_df = prediction[prediction["ds"] > training_end]
        forecast_records = [
            {
                "date": row["ds"].strftime("%Y-%m-%d"),
                "yhat": round(max(0, row["yhat"]), 1),
                "yhat_lower": round(max(0, row["yhat_lower"]), 1),
                "yhat_upper": round(max(0, row["yhat_upper"]), 1),
            }
            for _, row in forecast_df.iterrows()
        ]

        return {
            "historical": hist_records,
            "forecast": forecast_records,
            "meta": self._meta,
        }

    # ──────────────────────────────────────────────────────────────────────────
    # Persistence
    # ──────────────────────────────────────────────────────────────────────────

    def save(self, model_dir: Path | None = None) -> Path:
        """Serialize model + metadata to disk."""
        d = model_dir or MODEL_DIR
        d.mkdir(parents=True, exist_ok=True)

        pkl_path = d / "prophet_model.pkl"
        meta_path = d / "forecast_meta.json"

        with open(pkl_path, "wb") as f:
            pickle.dump(self._model, f)
        with open(meta_path, "w") as f:
            json.dump(self._meta, f, indent=2)

        logger.info("Forecast model saved to %s", d)
        return pkl_path

    def load(self, model_dir: Path | None = None) -> bool:
        """Load model + metadata from disk.

        If ``forecast_meta.json`` is missing or corrupt, essential metadata
        (``date_range``, ``training_days``, ``total_anomalies``) is
        reconstructed from the Prophet model's training history so that
        ``predict()`` never hits a ``KeyError``.
        """
        d = model_dir or MODEL_DIR
        pkl_path = d / "prophet_model.pkl"
        meta_path = d / "forecast_meta.json"

        if not pkl_path.exists():
            logger.warning("No forecast model found at %s", pkl_path)
            return False

        with open(pkl_path, "rb") as f:
            self._model = pickle.load(f)  # noqa: S301

        if meta_path.exists():
            try:
                with open(meta_path) as f:
                    self._meta = json.load(f)
            except (json.JSONDecodeError, OSError):
                logger.warning("Corrupt forecast_meta.json — will reconstruct from model history")
                self._meta = {}

        # Ensure required keys exist; reconstruct from model history if needed
        if "date_range" not in self._meta:
            self._meta = self._reconstruct_meta()
            logger.info("Reconstructed forecast metadata from model history")

        logger.info("Forecast model loaded from %s", d)
        return True

    def _reconstruct_meta(self) -> dict[str, Any]:
        """Derive essential metadata from the Prophet model's training history."""
        history = getattr(self._model, "history", None)
        if history is not None and not history.empty:
            ds = history["ds"]
            y = history["y"]
            return {
                "trained_at": "unknown",
                "user_id": None,
                "training_days": len(history),
                "date_range": [str(ds.min().date()), str(ds.max().date())],
                "total_anomalies": int(y.sum()),
                "data_mode": "unknown",
            }
        # Absolute fallback — should never happen with a valid model
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        return {
            "trained_at": "unknown",
            "user_id": None,
            "training_days": 0,
            "date_range": [today, today],
            "total_anomalies": 0,
            "data_mode": "unknown",
        }

    # ──────────────────────────────────────────────────────────────────────────
    # Retraining support (used by ClassifierRetrainer / run_retrain_runner)
    # ──────────────────────────────────────────────────────────────────────────

    def check_and_retrain(self) -> dict[str, Any]:
        """Check if enough new anomalies have accumulated and retrain if so.

        Follows the same pattern as ClassifierRetrainer.check_and_retrain().
        """
        current_count = self._count_total_anomalies()
        last_count = self._last_retrain_count()
        delta = current_count - last_count

        logger.info(
            "Forecast retrain check: current=%d, last=%d, delta=%d, threshold=%d",
            current_count,
            last_count,
            delta,
            FORECAST_RETRAIN_THRESHOLD,
        )

        if delta < FORECAST_RETRAIN_THRESHOLD:
            return {
                "retrained": False,
                "current_count": current_count,
                "last_count": last_count,
                "delta": delta,
                "threshold": FORECAST_RETRAIN_THRESHOLD,
            }

        return self.force_retrain(anomalies_at_retrain=current_count)

    def force_retrain(self, anomalies_at_retrain: int | None = None) -> dict[str, Any]:
        """Retrain unconditionally. Persists model to disk + MLflow and logs to DB."""
        if anomalies_at_retrain is None:
            anomalies_at_retrain = self._count_total_anomalies()

        log_id = self._insert_retrain_log(anomalies_at_retrain)
        started_at = datetime.now(timezone.utc)

        try:
            result = self.train()
            if not result.get("trained"):
                self._fail_retrain_log(log_id, result.get("reason", "unknown"), 0.0)
                return result

            model_path = self.save()
            duration = (datetime.now(timezone.utc) - started_at).total_seconds()

            mlflow_run_id = self._log_to_mlflow(result, duration)
            self._complete_retrain_log(log_id, str(model_path), mlflow_run_id, duration)

            logger.info("Forecast model retrained in %.1fs (%d anomalies)", duration, anomalies_at_retrain)
            return {
                "retrained": True,
                "model_path": str(model_path),
                "mlflow_run_id": mlflow_run_id,
                "duration_seconds": duration,
                "anomalies_at_retrain": anomalies_at_retrain,
                **result,
            }

        except Exception as e:
            duration = (datetime.now(timezone.utc) - started_at).total_seconds()
            self._fail_retrain_log(log_id, str(e)[:2000], duration)
            logger.exception("Forecast retrain failed")
            return {"retrained": False, "error": str(e)}

    # ──────────────────────────────────────────────────────────────────────────
    # Private helpers
    # ──────────────────────────────────────────────────────────────────────────

    def _data_mode(self) -> str:
        """Determine whether to use all data or real-only."""
        real_count = self._count_real_anomalies()
        return "real_only" if real_count >= REAL_ONLY_THRESHOLD else "all"

    def _load_daily_counts(self, user_id: str | None = None) -> pd.DataFrame:
        """Load daily anomaly counts from DB in Prophet format (ds, y)."""
        mode = self._data_mode()

        where_clauses = []
        params: list[Any] = []

        if mode == "real_only":
            where_clauses.append("(validated_by IS NULL OR validated_by != 'heuristic_midband')")

        if user_id:
            where_clauses.append("user_id = %s")
            params.append(user_id)

        where_sql = ("WHERE " + " AND ".join(where_clauses)) if where_clauses else ""

        query = f"""
            SELECT DATE(timestamp) AS ds, COUNT(*) AS y
            FROM enriched_anomalies
            {where_sql}
            GROUP BY DATE(timestamp)
            ORDER BY ds
        """

        conn = psycopg2.connect(**self.db_config)
        try:
            df = pd.read_sql(query, conn, params=params or None)
            df["ds"] = pd.to_datetime(df["ds"])
            return df
        finally:
            conn.close()

    def _count_total_anomalies(self) -> int:
        conn = psycopg2.connect(**self.db_config)
        try:
            with conn.cursor() as cur:
                cur.execute("SELECT COUNT(*) FROM enriched_anomalies")
                return cur.fetchone()[0]
        finally:
            conn.close()

    def _count_real_anomalies(self) -> int:
        conn = psycopg2.connect(**self.db_config)
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT COUNT(*) FROM enriched_anomalies "
                    "WHERE validated_by IS NULL OR validated_by != 'heuristic_midband'"
                )
                return cur.fetchone()[0]
        finally:
            conn.close()

    def _last_retrain_count(self) -> int:
        """Get anomaly count from the last successful forecast retrain."""
        conn = psycopg2.connect(**self.db_config)
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT anomalies_at_retrain
                    FROM classifier_retrain_log
                    WHERE classifier_type = 'forecast'
                      AND status = 'completed'
                    ORDER BY created_at DESC
                    LIMIT 1
                    """
                )
                row = cur.fetchone()
                return row[0] if row else 0
        finally:
            conn.close()

    def _insert_retrain_log(self, anomalies_at_retrain: int) -> int:
        conn = psycopg2.connect(**self.db_config)
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO classifier_retrain_log
                        (classifier_type, anomalies_at_retrain, status, started_at)
                    VALUES ('forecast', %s, 'running', NOW())
                    RETURNING id
                    """,
                    (anomalies_at_retrain,),
                )
                log_id = cur.fetchone()[0]
            conn.commit()
            return log_id
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def _complete_retrain_log(self, log_id: int, model_path: str, mlflow_run_id: str, duration: float) -> None:
        conn = psycopg2.connect(**self.db_config)
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE classifier_retrain_log
                    SET status = 'completed',
                        completed_at = NOW(),
                        model_path = %s,
                        mlflow_run_id = %s,
                        duration_seconds = %s
                    WHERE id = %s
                    """,
                    (model_path, mlflow_run_id, duration, log_id),
                )
            conn.commit()
        except Exception:
            conn.rollback()
            logger.exception("Failed to mark forecast retrain log %d as completed", log_id)
        finally:
            conn.close()

    @staticmethod
    def _log_to_mlflow(result: dict[str, Any], duration: float) -> str:
        """Log training params + metrics to MLflow. Returns run ID or empty string."""
        try:
            import mlflow

            mlflow.set_tracking_uri(os.getenv("MLFLOW_TRACKING_URI", "http://localhost:5001"))
            mlflow.set_experiment("forecast")
            with mlflow.start_run(run_name=f"prophet_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}"):
                mlflow.log_params(
                    {
                        "model": "prophet",
                        "data_mode": result.get("data_mode", "unknown"),
                        "training_days": result.get("training_days", 0),
                        "weekly_seasonality": True,
                        "changepoint_prior_scale": 0.1,
                        "interval_width": 0.90,
                    }
                )
                mlflow.log_metrics(
                    {
                        "total_anomalies": result.get("total_anomalies", 0),
                        "training_days": result.get("training_days", 0),
                        "duration_seconds": round(duration, 2),
                    }
                )
                return mlflow.active_run().info.run_id  # type: ignore[union-attr]
        except Exception:
            logger.debug("MLflow logging skipped (unavailable or failed)", exc_info=True)
            return ""

    def _fail_retrain_log(self, log_id: int, error_message: str, duration: float) -> None:
        conn = psycopg2.connect(**self.db_config)
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE classifier_retrain_log
                    SET status = 'failed',
                        completed_at = NOW(),
                        error_message = %s,
                        duration_seconds = %s
                    WHERE id = %s
                    """,
                    (error_message, duration, log_id),
                )
            conn.commit()
        except Exception:
            conn.rollback()
            logger.exception("Failed to mark forecast retrain log %d as failed", log_id)
        finally:
            conn.close()
