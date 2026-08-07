"""
DFP Retrain Runner — polls dfp_retrain_jobs and executes retraining.

Reuses the existing DFPTrainingPipeline (pipelines/training_pipeline.py) with
no modifications to pipeline.yaml.  For each pending job the runner:

  1. Exports user events from user_training_events → temp JSONL
  2. Generates a control message matching train.json format
  3. Calls DFPPipeline.run_training() with the temp control message
  4. Records the new MLflow model version in the job row
  5. Cleans up temp files
  6. Inserts a notification for the assigned analyst

Architecture:
    This runner is designed to run as a background process (started by
    start_services.sh).  It polls every POLL_INTERVAL_SECONDS for pending
    jobs and processes them sequentially (one at a time).

Author: Tomasz Zabek <tzabek@deloitte.co.uk>
Date: 2026-04-29
"""

from __future__ import annotations

import json
import logging
import os
import signal
import sys
import time
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

POLL_INTERVAL_SECONDS = int(os.getenv("RETRAIN_POLL_INTERVAL", "60"))
RETRAIN_JSONL_DIR = PROJECT_ROOT / "data" / "input" / "train"
RETRAIN_CTRL_DIR = PROJECT_ROOT / "control_messages"
DEFAULT_CONFIG_PATH = str(PROJECT_ROOT / "config" / "pipeline.yaml")
DEFAULT_CACHE_DIR = ".cache/demo"
DEFAULT_MLFLOW_URI = os.getenv("MLFLOW_TRACKING_URI", "http://localhost:5001")


class DFPRetrainRunner:
    """Polls dfp_retrain_jobs and executes DFP retraining via the standard pipeline."""

    def __init__(
        self,
        config_path: str = DEFAULT_CONFIG_PATH,
        db_config: dict | None = None,
        cache_dir: str = DEFAULT_CACHE_DIR,
        mlflow_uri: str = DEFAULT_MLFLOW_URI,
    ) -> None:
        self.config_path = config_path
        self.db_config = db_config or DB_CONFIG
        self.cache_dir = cache_dir
        self.mlflow_uri = mlflow_uri
        self._running = False

        logger.info("DFPRetrainRunner initialized")
        logger.info(f"  config    : {self.config_path}")
        logger.info(f"  poll      : every {POLL_INTERVAL_SECONDS}s")
        logger.info(f"  mlflow    : {self.mlflow_uri}")

    # ──────────────────────────────────────────────────────────────────────────
    # Public API
    # ──────────────────────────────────────────────────────────────────────────

    def poll_and_run(self) -> None:
        """Main loop — poll for pending jobs and process them sequentially."""
        self._running = True

        def _handle_signal(signum: int, frame: Any) -> None:
            logger.info("Received signal %d — stopping after current job", signum)
            self._running = False

        signal.signal(signal.SIGINT, _handle_signal)
        signal.signal(signal.SIGTERM, _handle_signal)

        logger.info("DFPRetrainRunner: polling loop started")
        while self._running:
            try:
                job = self._fetch_next_pending_job()
                if job:
                    self._run_single_job(job)
                else:
                    time.sleep(POLL_INTERVAL_SECONDS)
            except KeyboardInterrupt:
                logger.info("DFPRetrainRunner: stopped by KeyboardInterrupt")
                break
            except Exception:
                logger.exception("DFPRetrainRunner: unexpected error in poll loop")
                time.sleep(POLL_INTERVAL_SECONDS)

        logger.info("DFPRetrainRunner: polling loop exited")

    def run_once(self) -> int:
        """Single pass — process all pending jobs, return count processed."""
        count = 0
        while self.process_next_job():
            count += 1
        logger.info(f"DFPRetrainRunner: run_once completed — {count} job(s) processed")
        return count

    def process_next_job(self) -> bool:
        """Fetch and run the next pending DFP job. Returns True if a job was processed."""
        job = self._fetch_next_pending_job()
        if not job:
            return False
        self._run_single_job(job)
        return True

    def trigger_for_user(self, user_id: str) -> str | None:
        """Manually create a pending retrain job for a user. Returns job_id or None."""
        conn = psycopg2.connect(**self.db_config)
        try:
            with conn.cursor() as cur:
                # Guard: don't create if one is already pending/running
                cur.execute(
                    "SELECT job_id FROM dfp_retrain_jobs WHERE user_id = %s AND retrain_type = 'dfp' AND status IN ('pending', 'running')",
                    (user_id,),
                )
                if cur.fetchone():
                    logger.info(f"Retrain job already pending/running for {user_id}")
                    return None

                cur.execute(
                    """
                    INSERT INTO dfp_retrain_jobs (user_id, new_clean_events, status, retrain_type)
                    VALUES (%s, 0, 'pending', 'dfp')
                    RETURNING job_id::text
                    """,
                    (user_id,),
                )
                job_id = cur.fetchone()[0]
            conn.commit()
            logger.info(f"Created manual retrain job {job_id} for {user_id}")
            return job_id
        except Exception:
            conn.rollback()
            logger.exception(f"Failed to create retrain job for {user_id}")
            return None
        finally:
            conn.close()

    # ──────────────────────────────────────────────────────────────────────────
    # Job lifecycle
    # ──────────────────────────────────────────────────────────────────────────

    def _fetch_next_pending_job(self) -> dict | None:
        """Fetch the oldest pending DFP retrain job (SELECT FOR UPDATE SKIP LOCKED)."""
        conn = psycopg2.connect(**self.db_config)
        try:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(
                    """
                    SELECT job_id::text, user_id, new_clean_events, false_positive_ids
                    FROM dfp_retrain_jobs
                    WHERE status = 'pending' AND retrain_type = 'dfp'
                    ORDER BY created_at ASC
                    LIMIT 1
                    FOR UPDATE SKIP LOCKED
                    """
                )
                row = cur.fetchone()
                if not row:
                    return None

                # Transition to running
                cur.execute(
                    "UPDATE dfp_retrain_jobs SET status = 'running', started_at = NOW() WHERE job_id = %s::uuid",
                    (row["job_id"],),
                )
            conn.commit()
            logger.info(f"Picked up retrain job {row['job_id']} for user {row['user_id']}")
            return dict(row)
        except Exception:
            conn.rollback()
            logger.exception("Failed to fetch pending retrain job")
            return None
        finally:
            conn.close()

    def _run_single_job(self, job: dict) -> None:
        """Execute a single retrain job end-to-end."""
        job_id = job["job_id"]
        user_id = job["user_id"]
        jsonl_path: Path | None = None
        ctrl_path: Path | None = None

        try:
            # 1. Export events from DB → temp JSONL
            jsonl_path = self._export_to_jsonl(user_id, job_id)
            if not jsonl_path or not jsonl_path.exists():
                self._fail_job(job_id, "No events exported for user")
                return

            with open(jsonl_path, "r", encoding="utf-8") as jsonl_file:  # noqa: UP015
                event_count = sum(1 for _ in jsonl_file)
            logger.info(f"Exported {event_count} events for {user_id} → {jsonl_path}")

            # 2. Generate control message
            ctrl_path = self._build_control_message(user_id, job_id, jsonl_path)
            logger.info(f"Control message → {ctrl_path}")

            # 3. Run DFP training pipeline (same as initial training)
            result = self._run_pipeline(str(ctrl_path))

            if not result.get("success"):
                self._fail_job(job_id, result.get("error", "Pipeline returned failure"))
                return

            # 4. Extract model version from result
            training_stats = result.get("training", {})
            new_model_version = str(training_stats.get("model_version", ""))
            mlflow_run_id = str(training_stats.get("mlflow_run_id", ""))

            # 5. Mark job completed
            self._complete_job(
                job_id,
                new_model_version=new_model_version,
                mlflow_run_id=mlflow_run_id,
                total_events=event_count,
            )

            # 6. Send notification
            self._send_notification(user_id, new_model_version)

            logger.info(
                f"Retrain job {job_id} completed: user={user_id}, "
                f"events={event_count}, model_version={new_model_version}"
            )

        except Exception as exc:
            logger.exception(f"Retrain job {job_id} failed: {exc}")
            self._fail_job(job_id, str(exc))

        finally:
            # 7. Clean up temp files
            for path in (jsonl_path, ctrl_path):
                if path and path.exists():
                    try:
                        path.unlink()
                        logger.debug(f"Cleaned up {path}")
                    except OSError:
                        pass

    # ──────────────────────────────────────────────────────────────────────────
    # Export + control message
    # ──────────────────────────────────────────────────────────────────────────

    def _export_to_jsonl(self, user_id: str, job_id: str) -> Path | None:
        """Export user events from user_training_events to a temp JSONL file."""
        from modules.ai.auto_labeling.dfp_feedback_service import DFPFeedbackService

        svc = DFPFeedbackService(db_config=self.db_config)
        # Use 60-day window to match pipeline.yaml max_history
        events = svc.export_user_events(user_id, window_days=60)
        if not events:
            logger.warning(f"No events found for user {user_id}")
            return None

        RETRAIN_JSONL_DIR.mkdir(parents=True, exist_ok=True)
        # Sanitise user_id for filename (replace @ and other special chars)
        safe_user = user_id.replace("@", "_at_").replace(".", "_")
        jsonl_path = RETRAIN_JSONL_DIR / f"retrain_{safe_user}_{job_id[:8]}.jsonl"

        with open(jsonl_path, "w") as f:
            for event in events:
                f.write(json.dumps(event, default=str) + "\n")

        return jsonl_path

    def _build_control_message(self, user_id: str, job_id: str, jsonl_path: Path) -> Path:
        """Generate a control message JSON matching the train.json format."""
        ctrl_msg = {
            "tasks": [
                {
                    "type": "training",
                    "properties": {
                        "data_path": str(jsonl_path),
                        "cache_dir": self.cache_dir,
                        "timestamp_column": "timestamp",
                        "userid_column": "username",
                        "model_name_formatter": "DFP-{user_id}",
                        "cache_mode": "aggregate",
                        "min_history": 300,
                        "min_increment": 0,  # Force retrain even if < 300 new events
                        "max_history": "60d",
                        "epochs": 100,
                        "mlflow_uri": self.mlflow_uri,
                        "experiment_name": "dfp/retrain",
                    },
                }
            ],
            "metadata": {
                "retrain_job_id": job_id,
                "user_id": user_id,
                "triggered_at": datetime.now(timezone.utc).isoformat(),
            },
        }

        RETRAIN_CTRL_DIR.mkdir(parents=True, exist_ok=True)
        safe_user = user_id.replace("@", "_at_").replace(".", "_")
        ctrl_path = RETRAIN_CTRL_DIR / f"retrain_{safe_user}_{job_id[:8]}.json"

        with open(ctrl_path, "w") as f:
            json.dump(ctrl_msg, f, indent=2)

        return ctrl_path

    # ──────────────────────────────────────────────────────────────────────────
    # Pipeline execution
    # ──────────────────────────────────────────────────────────────────────────

    def _run_pipeline(self, ctrl_msg_path: str) -> dict[str, Any]:
        """Run the DFP training pipeline using the standard DFPPipeline class."""
        from pipelines.pipeline import DFPPipeline

        pipeline = DFPPipeline(
            config_path=self.config_path,
            cache_dir=self.cache_dir,
            mlflow_uri=self.mlflow_uri,
            log_level="INFO",
        )
        return pipeline.run_training(ctrl_msg_path)

    # ──────────────────────────────────────────────────────────────────────────
    # Job status updates
    # ──────────────────────────────────────────────────────────────────────────

    def _complete_job(
        self,
        job_id: str,
        new_model_version: str,
        mlflow_run_id: str,
        total_events: int,
    ) -> None:
        conn = psycopg2.connect(**self.db_config)
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE dfp_retrain_jobs
                    SET status = 'completed',
                        completed_at = NOW(),
                        new_model_version = %s,
                        mlflow_run_id = %s,
                        total_training_events = %s
                    WHERE job_id = %s::uuid
                    """,
                    (new_model_version, mlflow_run_id, total_events, job_id),
                )
            conn.commit()
        except Exception:
            conn.rollback()
            logger.exception(f"Failed to mark job {job_id} as completed")
        finally:
            conn.close()

    def _fail_job(self, job_id: str, error_message: str) -> None:
        conn = psycopg2.connect(**self.db_config)
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE dfp_retrain_jobs
                    SET status = 'failed',
                        completed_at = NOW(),
                        error_message = %s
                    WHERE job_id = %s::uuid
                    """,
                    (error_message[:2000], job_id),
                )
            conn.commit()
        except Exception:
            conn.rollback()
            logger.exception(f"Failed to mark job {job_id} as failed")
        finally:
            conn.close()

    # ──────────────────────────────────────────────────────────────────────────
    # Notifications
    # ──────────────────────────────────────────────────────────────────────────

    def _send_notification(self, user_id: str, model_version: str) -> None:
        """Insert a notification for analysts watching this user's anomalies."""
        conn = psycopg2.connect(**self.db_config)
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO analyst_notifications (type, title, message)
                    VALUES ('retrain_complete', %s, %s)
                    """,
                    (
                        f"Model retrained for {user_id}",
                        f"DFP model for {user_id} has been retrained (version {model_version}). "
                        f"Future detections will use the updated behavioural profile.",
                    ),
                )
            conn.commit()
        except Exception:
            conn.rollback()
            logger.debug(f"Could not send retrain notification for {user_id}")
        finally:
            conn.close()
