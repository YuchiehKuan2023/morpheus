"""
Classifier Retrainer — retrains XGBoost risk scorer and DistilBERT root
cause classifier when enough new classified anomalies have accumulated.

Threshold logic:
    For each classifier type, the retrainer checks the number of classified
    anomalies that exist *now* vs. the count recorded at the last successful
    retrain.  If the delta exceeds RETRAIN_THRESHOLD, a retrain is triggered.

Both classifiers already have standalone training functions that load data
from the DB, train, save the model, and optionally log to MLflow.  This
module simply orchestrates calling them and recording the results.

Author: Tomasz Zabek <tzabek@deloitte.co.uk>
Date: 2026-04-29
"""

from __future__ import annotations

import logging
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# ── project root ──────────────────────────────────────────────────────────────
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

# ── configuration ─────────────────────────────────────────────────────────────
DB_CONFIG: dict[str, Any] = get_db_params()

# Retrain when this many *new* classified anomalies accumulate since last run
RETRAIN_THRESHOLD = int(os.getenv("CLASSIFIER_RETRAIN_THRESHOLD", "50"))

# Model directories (match existing conventions)
RISK_SCORER_MODEL_DIR = PROJECT_ROOT / "data" / "models" / "risk_scorer"
ROOT_CAUSE_MODEL_DIR = PROJECT_ROOT / "data" / "models" / "root_cause"

VALID_CLASSIFIERS = ("risk_scorer", "root_cause")


class ClassifierRetrainer:
    """Checks thresholds and retrains XGBoost / DistilBERT classifiers."""

    def __init__(self, db_config: dict | None = None) -> None:
        self.db_config = db_config or DB_CONFIG

    # ──────────────────────────────────────────────────────────────────────────
    # Public API
    # ──────────────────────────────────────────────────────────────────────────

    def check_and_retrain_all(self) -> dict[str, Any]:
        """Check both classifiers and retrain any that exceed the threshold.

        Returns a summary dict: ``{"risk_scorer": {...}, "root_cause": {...}}``.
        """
        results: dict[str, Any] = {}
        for clf_type in VALID_CLASSIFIERS:
            results[clf_type] = self.check_and_retrain(clf_type)
        return results

    def check_and_retrain(self, classifier_type: str) -> dict[str, Any]:
        """Check threshold for a single classifier and retrain if needed."""
        if classifier_type not in VALID_CLASSIFIERS:
            return {"skipped": True, "reason": f"unknown classifier: {classifier_type}"}

        current_count = self._count_classified_anomalies()
        last_count = self._last_retrain_count(classifier_type)
        delta = current_count - last_count

        logger.info(
            f"[{classifier_type}] classified anomalies: {current_count} "
            f"(last retrain at {last_count}, delta={delta}, threshold={RETRAIN_THRESHOLD})"
        )

        if delta < RETRAIN_THRESHOLD:
            return {
                "retrained": False,
                "current_count": current_count,
                "last_count": last_count,
                "delta": delta,
                "threshold": RETRAIN_THRESHOLD,
            }

        return self.force_retrain(classifier_type, anomalies_at_retrain=current_count)

    def force_retrain(
        self,
        classifier_type: str,
        anomalies_at_retrain: int | None = None,
    ) -> dict[str, Any]:
        """Retrain a classifier unconditionally. Returns result summary."""
        if classifier_type not in VALID_CLASSIFIERS:
            return {"error": f"unknown classifier: {classifier_type}"}

        if anomalies_at_retrain is None:
            anomalies_at_retrain = self._count_classified_anomalies()

        log_id = self._insert_retrain_log(classifier_type, anomalies_at_retrain)
        started_at = datetime.now(timezone.utc)

        try:
            if classifier_type == "risk_scorer":
                result = self._retrain_risk_scorer()
            else:
                result = self._retrain_root_cause()

            duration = (datetime.now(timezone.utc) - started_at).total_seconds()
            self._complete_retrain_log(
                log_id,
                model_path=result.get("model_dir", result.get("model_path", "")),
                mlflow_run_id=result.get("mlflow_run_id", ""),
                duration=duration,
            )
            self._send_notification(classifier_type, result)

            logger.info(f"[{classifier_type}] retrain completed in {duration:.1f}s")
            return {"retrained": True, "log_id": log_id, "duration": duration, **result}

        except Exception as exc:
            duration = (datetime.now(timezone.utc) - started_at).total_seconds()
            self._fail_retrain_log(log_id, str(exc), duration)
            logger.exception(f"[{classifier_type}] retrain failed: {exc}")
            return {"retrained": False, "error": str(exc), "log_id": log_id}

    # ──────────────────────────────────────────────────────────────────────────
    # Actual retraining — delegates to existing training modules
    # ──────────────────────────────────────────────────────────────────────────

    def _retrain_risk_scorer(self) -> dict[str, Any]:
        """Retrain XGBoost risk scorer using existing training pipeline."""
        from modules.ai.risk_scoring.risk_scorer_training import run as risk_scorer_run

        logger.info("Starting XGBoost risk scorer retraining…")
        result = risk_scorer_run(
            model_dir=RISK_SCORER_MODEL_DIR,
            dry_run=False,
            score_only=False,
            use_shap=True,
        )

        if result.get("error"):
            raise RuntimeError(f"Risk scorer training failed: {result['error']}")

        result["model_dir"] = str(RISK_SCORER_MODEL_DIR)
        return result

    def _retrain_root_cause(self) -> dict[str, Any]:
        """Retrain DistilBERT root cause classifier using existing training pipeline."""
        from modules.ai.root_cause.training import train as root_cause_train

        logger.info("Starting DistilBERT root cause classifier retraining…")
        result = root_cause_train(
            model_dir=str(ROOT_CAUSE_MODEL_DIR),
            dry_run=False,
            no_mlflow=False,
        )

        result["model_dir"] = str(ROOT_CAUSE_MODEL_DIR)
        return result

    # ──────────────────────────────────────────────────────────────────────────
    # DB helpers
    # ──────────────────────────────────────────────────────────────────────────

    def _count_classified_anomalies(self) -> int:
        """Count total classified TRUE anomalies in enriched_anomalies."""
        conn = psycopg2.connect(**self.db_config)
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT COUNT(*) FROM enriched_anomalies WHERE is_anomaly = TRUE AND classified_at IS NOT NULL"
                )
                return cur.fetchone()[0]
        finally:
            conn.close()

    def _last_retrain_count(self, classifier_type: str) -> int:
        """Get the anomalies_at_retrain from the most recent successful retrain."""
        conn = psycopg2.connect(**self.db_config)
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT anomalies_at_retrain
                    FROM classifier_retrain_log
                    WHERE classifier_type = %s AND status = 'completed'
                    ORDER BY created_at DESC
                    LIMIT 1
                    """,
                    (classifier_type,),
                )
                row = cur.fetchone()
                return row[0] if row else 0
        finally:
            conn.close()

    def _insert_retrain_log(self, classifier_type: str, anomalies_at_retrain: int) -> int:
        """Insert a running entry into classifier_retrain_log. Returns log id."""
        conn = psycopg2.connect(**self.db_config)
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO classifier_retrain_log
                        (classifier_type, anomalies_at_retrain, status, started_at)
                    VALUES (%s, %s, 'running', NOW())
                    RETURNING id
                    """,
                    (classifier_type, anomalies_at_retrain),
                )
                log_id = cur.fetchone()[0]
            conn.commit()
            return log_id
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def _complete_retrain_log(
        self,
        log_id: int,
        model_path: str,
        mlflow_run_id: str,
        duration: float,
    ) -> None:
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
            logger.exception(f"Failed to mark retrain log {log_id} as completed")
        finally:
            conn.close()

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
                    (error_message[:2000], duration, log_id),
                )
            conn.commit()
        except Exception:
            conn.rollback()
            logger.exception(f"Failed to mark retrain log {log_id} as failed")
        finally:
            conn.close()

    # ──────────────────────────────────────────────────────────────────────────
    # Notifications
    # ──────────────────────────────────────────────────────────────────────────

    def _send_notification(self, classifier_type: str, result: dict) -> None:
        """Insert a notification for analysts about classifier retraining."""
        label = "Risk Scorer (XGBoost)" if classifier_type == "risk_scorer" else "Root Cause (DistilBERT)"

        # Build a concise summary
        if classifier_type == "risk_scorer":
            detail = (
                f"Scored {result.get('n_scored', '?')} anomalies. "
                f"Score range: {result.get('score_min', '?')}–{result.get('score_max', '?')}."
            )
        else:
            detail = (
                f"Best val accuracy: {result.get('best_val_accuracy', '?')}, "
                f"F1-macro: {result.get('best_val_f1_macro', '?')}."
            )

        conn = psycopg2.connect(**self.db_config)
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO analyst_notifications (type, title, message)
                    VALUES ('retrain_complete', %s, %s)
                    """,
                    (
                        f"{label} retrained",
                        f"{label} classifier has been retrained. {detail} "
                        f"Future predictions will use the updated model.",
                    ),
                )
            conn.commit()
        except Exception:
            conn.rollback()
            logger.debug(f"Could not send retrain notification for {classifier_type}")
        finally:
            conn.close()


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import argparse

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-8s %(name)s — %(message)s",
    )

    parser = argparse.ArgumentParser(description="Retrain classifiers (risk scorer / root cause)")
    parser.add_argument(
        "--classifier",
        choices=["risk_scorer", "root_cause", "all"],
        default="all",
        help="Which classifier to retrain (default: all)",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Retrain even if threshold not met",
    )
    parser.add_argument(
        "--threshold",
        type=int,
        default=None,
        help=f"Override retrain threshold (default: {RETRAIN_THRESHOLD})",
    )
    args = parser.parse_args()

    if args.threshold is not None:
        RETRAIN_THRESHOLD = args.threshold  # type: ignore[assignment]

    retrainer = ClassifierRetrainer()

    if args.force:
        if args.classifier == "all":
            for clf in VALID_CLASSIFIERS:
                print(f"\n{'=' * 60}\nForce retraining: {clf}\n{'=' * 60}")
                result = retrainer.force_retrain(clf)
                print(f"Result: {result}")
        else:
            result = retrainer.force_retrain(args.classifier)
            print(f"Result: {result}")
    else:
        if args.classifier == "all":
            results = retrainer.check_and_retrain_all()
            for clf, res in results.items():
                print(f"\n{clf}: {res}")
        else:
            result = retrainer.check_and_retrain(args.classifier)
            print(f"Result: {result}")
