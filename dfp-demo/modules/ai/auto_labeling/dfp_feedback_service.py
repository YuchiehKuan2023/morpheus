#!/usr/bin/env python3
"""
DFP Feedback Service: False-Positive Training Loop

When the anomaly validator marks a detection as a FALSE POSITIVE the event
represents legitimate user behaviour that was incorrectly flagged.  This service:

  1. Persists the clean event to the ``user_training_events`` PostgreSQL table
     (source='feedback') so it normalises future baselines.
     The original JSONL file (data/input/train/azure_ad_train.jsonl) is now
     a read-only seed that was imported once via scripts/db/seed_user_training_events.py.
  2. Tracks how many new clean events have been persisted per user (in-memory
     counter backed by the dfp_retrain_jobs table for persistence across restarts).
  3. Queues a dfp_retrain_jobs row when the per-user RETRAIN_THRESHOLD is reached,
     so the MLflow pipeline can pick it up and retrain the user's DFP model.

Retraining export:
  Use ``export_user_events(user_id, window_days=90)`` to retrieve all events
  for a user (seed + feedback) within a look-back window for model retraining.

Usage (standalone):
    python modules/ai/auto_labeling/dfp_feedback_service.py \\
        --anomaly-id dac29e6a-4afb-45f4-a556-bb62e751f4be

    python modules/ai/auto_labeling/dfp_feedback_service.py --status

Reference:
    docs/implementation/LABELING_FEEDBACK_ARCHITECTURE.md
    modules/ai/auto_labeling/IMPLEMENTATION_PLAN.md  (Phase 2)

Author: AI Intelligence Layer Team
Date: 2026-02-27
"""

import json
import logging
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

# ── env ───────────────────────────────────────────────────────────────────────
try:
    from dotenv import load_dotenv

    _env_path = Path(__file__).parents[3] / ".env"
    load_dotenv(_env_path, override=False)
except ImportError:
    pass

# ── project root on sys.path ──────────────────────────────────────────────────
PROJECT_ROOT = Path(__file__).parents[3]
sys.path.insert(0, str(PROJECT_ROOT))

from modules.utils.db import get_db_params  # noqa: E402

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

# ── configuration ─────────────────────────────────────────────────────────────
DB_CONFIG = get_db_params()

# Number of new clean events per user that triggers a retrain job.
RETRAIN_THRESHOLD = int(os.getenv("DFP_RETRAIN_THRESHOLD", "300"))

# Default training file path.
# PROJECT_ROOT = Path(__file__).parents[3] resolves to the dfp-demo/ directory,
# so data/ is a direct child — no "dfp-demo" segment needed.
DEFAULT_TRAIN_FILE = PROJECT_ROOT / "data" / "input" / "train" / "azure_ad_train.jsonl"


# ─────────────────────────────────────────────────────────────────────────────
class DFPFeedbackService:
    """
    Manages the false-positive feedback loop for DFP model improvement.

    Thread-safety note: in-memory counters are per-process.  The canonical
    source of truth for how many events have been added since the last
    completed retrain job is the dfp_retrain_jobs table; the in-memory dict
    is a write-through cache to avoid a DB round-trip on every append.
    """

    def __init__(
        self,
        train_file: str | Path | None = None,
        retrain_threshold: int = RETRAIN_THRESHOLD,
        db_config: dict | None = None,
    ) -> None:
        self.train_file = Path(train_file or DEFAULT_TRAIN_FILE)
        self.retrain_threshold = retrain_threshold
        self.db_config = db_config or DB_CONFIG

        # In-memory write-through counters: {user_id: count_since_last_retrain}
        self._pending_counts: dict[str, int] = {}
        # Accumulate false_positive_ids per user until threshold
        self._pending_fp_ids: dict[str, list[str]] = {}

        logger.info("DFPFeedbackService initialized")
        logger.info(f"   Train file       : {self.train_file}")
        logger.info(f"   Retrain threshold: {self.retrain_threshold}")

    # ──────────────────────────────────────────────────────────────────────────
    # Public API
    # ──────────────────────────────────────────────────────────────────────────

    def add_false_positive(self, detection: dict, db_conn=None) -> bool:
        """
        Record a false positive: append to training file and check threshold.

        Args:
            detection : Row dict from enriched_anomalies (or equivalent mapping
                        with keys: anomaly_id, user_id, timestamp, original_event).
            db_conn   : Optional live psycopg2 connection.  When supplied the
                        threshold check and job creation are committed immediately.
                        When None the caller is responsible for providing a
                        connection via check_and_trigger_retrain() later.

        Returns:
            True if a retrain job was queued as a result of this call.
        """
        anomaly_id = str(detection.get("anomaly_id", ""))
        user_id = str(detection.get("user_id", "unknown"))

        logger.info(f"Adding false positive to training: {anomaly_id} (user={user_id})")

        # 1. Build clean training record from the original Azure AD event.
        training_record = self._build_training_record(detection)
        if not training_record:
            logger.warning(f"   Could not build training record for {anomaly_id} — skipping")
            return False

        # 2. Persist clean event to the user_training_events table.
        anomaly_score = detection.get("anomaly_score")
        persisted = self._persist_to_db(
            training_record,
            user_id,
            db_conn,
            anomaly_score=anomaly_score,
            anomaly_id=anomaly_id,
        )
        if not persisted:
            return False

        # 3. Update in-memory counter.
        self._pending_counts[user_id] = self._pending_counts.get(user_id, 0) + 1
        if user_id not in self._pending_fp_ids:
            self._pending_fp_ids[user_id] = []
        self._pending_fp_ids[user_id].append(anomaly_id)

        count = self._pending_counts[user_id]
        logger.info(f"   User {user_id}: {count}/{self.retrain_threshold} new clean events")

        # 4. Check threshold.
        triggered = False
        if count >= self.retrain_threshold:
            triggered = self._trigger_retrain_job(user_id, db_conn)
            if triggered:
                # Reset counters for this user.
                self._pending_counts[user_id] = 0
                self._pending_fp_ids[user_id] = []

        return triggered

    def check_and_trigger_retrain(self, user_id: str, db_conn) -> bool:
        """
        Manually check threshold for a user and trigger if met.

        Useful when the caller already has the connection and wants to batch
        the commit with other writes in the same transaction.
        """
        count = self._pending_counts.get(user_id, 0)
        if count >= self.retrain_threshold:
            triggered = self._trigger_retrain_job(user_id, db_conn)
            if triggered:
                self._pending_counts[user_id] = 0
                self._pending_fp_ids[user_id] = []
            return triggered
        return False

    def get_pending_counts(self) -> dict[str, int]:
        """Return a snapshot of per-user pending event counts."""
        return dict(self._pending_counts)

    def load_pending_counts_from_db(self, db_conn) -> None:
        """
        Restore in-memory counters from the DB after a restart.

        Sub-threshold counts (0 < n < RETRAIN_THRESHOLD) are never persisted —
        they live only in memory — so they are lost on restart.  This is an
        acceptable trade-off: at most RETRAIN_THRESHOLD-1 events need to be
        re-accumulated after a restart.

        Critically, this method does NOT restore counts for users who already
        have a pending or running job.  Doing so would cause the next added
        false positive to immediately trigger a second job (because the pending
        job's new_clean_events already equals the threshold).  Instead those
        users start fresh at 0 and new accumulation begins only after the
        in-flight job is picked up and completed by the MLflow runner.
        """
        import psycopg2.extras

        try:
            with db_conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                # Identify users that currently have an in-flight retrain job.
                cur.execute(
                    """
                    SELECT DISTINCT user_id
                    FROM dfp_retrain_jobs
                    WHERE status IN ('pending', 'running')
                    """
                )
                users_with_inflight_jobs = [row["user_id"] for row in cur.fetchall()]
                # For users with in-flight jobs, ensure local counters are reset
                # so we do not double-trigger retrain jobs after a restart.
                for uid in users_with_inflight_jobs:
                    self._pending_counts.pop(uid, None)
                    # Also clear any locally-tracked false-positive IDs for safety.
                    if hasattr(self, "_pending_fp_ids"):
                        self._pending_fp_ids.pop(uid, None)
            logger.info(f"Reset pending counts for {len(users_with_inflight_jobs)} user(s) with in-flight retrain jobs")
        except Exception as exc:
            logger.warning(f"Could not load pending counts from DB: {exc}")

    # ──────────────────────────────────────────────────────────────────────────
    # Private helpers
    # ──────────────────────────────────────────────────────────────────────────

    def _build_training_record(self, detection: dict) -> dict | None:
        """
        Convert an enriched_anomalies row to the DFP JSONL training format.

        Returns the original Azure AD event verbatim (full training schema),
        with a ``_dfp_feedback`` metadata block appended.  No field
        reconstruction — the original_event stored at detection time already
        contains the complete training-format payload.
        """
        try:
            # original_event may be a dict (psycopg2 returns JSONB as dict) or a JSON string.
            original_event = detection.get("original_event") or {}
            if isinstance(original_event, str):
                original_event = json.loads(original_event)

            if not original_event:
                logger.warning(
                    f"   original_event is empty for {detection.get('anomaly_id')} — cannot build training record"
                )
                return None

            # Work on a shallow copy so we don't mutate the detection dict.
            record = dict(original_event)

            # Append audit metadata (ignored by DFP training, useful for debugging).
            record["_dfp_feedback"] = {
                "source_anomaly_id": str(detection.get("anomaly_id", "")),
                "label": "false_positive",
                "added_at": datetime.now(timezone.utc).isoformat(),
            }
            return record

        except Exception as exc:
            logger.error(f"   Error building training record: {exc}", exc_info=True)
            return None

    def _persist_to_db(self, record: dict, user_id: str, db_conn=None, anomaly_score=None, anomaly_id=None) -> bool:
        """
        Insert a training record into the user_training_events table.

        Opens its own connection when *db_conn* is None (mirrors the pattern
        used by _trigger_retrain_job which receives db_conn from the caller, but
        here db_conn is optional so we fall back to self.db_config).

        Args:
            record  : Full event dict (original_event + _dfp_feedback metadata).
            user_id : Azure AD user principal name / user_id string.
            db_conn : Optional live psycopg2 connection.  When None, a short-lived
                      connection is opened and closed within this call.

        Returns:
            True on successful INSERT, False on any error.
        """
        import psycopg2
        import psycopg2.extras

        # Extract event_time from the record's "time" field; fall back to NOW().
        event_time_str = record.get("time") or record.get("createdDateTime")
        try:
            if event_time_str:
                if isinstance(event_time_str, datetime):
                    # Use the provided datetime directly, defaulting to UTC if naive.
                    event_time = (
                        event_time_str
                        if event_time_str.tzinfo is not None
                        else event_time_str.replace(tzinfo=timezone.utc)
                    )
                else:
                    # Coerce to string before replace / fromisoformat to avoid TypeError.
                    event_time = datetime.fromisoformat(str(event_time_str).replace("Z", "+00:00"))
            else:
                event_time = datetime.now(timezone.utc)
        except (ValueError, AttributeError, TypeError):
            event_time = datetime.now(timezone.utc)

        own_conn = db_conn is None
        conn = None
        try:
            conn = psycopg2.connect(**self.db_config) if own_conn else db_conn
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO user_training_events (user_id, event_time, event, source, anomaly_score, anomaly_id)
                    VALUES (%s, %s, %s, 'feedback', %s, %s)
                    """,
                    (user_id, event_time, psycopg2.extras.Json(record), anomaly_score, anomaly_id),
                )
            if own_conn:
                conn.commit()
            logger.debug(f"   Persisted feedback event for user={user_id} at {event_time.isoformat()}")
            return True
        except Exception as exc:
            logger.error(f"   Failed to persist training event to DB: {exc}", exc_info=True)
            if own_conn and conn is not None:
                try:
                    conn.rollback()
                except Exception:
                    pass
            return False
        finally:
            if own_conn and conn is not None:
                try:
                    conn.close()
                except Exception:
                    pass

    def _append_to_jsonl(self, record: dict) -> bool:
        """
        Deprecated: kept for backward compatibility only.

        New code should use _persist_to_db().  This method still works for
        quick ad-hoc exports but is no longer called by add_false_positive().
        """
        try:
            self.train_file.parent.mkdir(parents=True, exist_ok=True)
            line = json.dumps(record, default=str, ensure_ascii=False)
            with self.train_file.open("a", encoding="utf-8") as fh:
                fh.write(line + "\n")
            logger.debug(f"   Appended record to {self.train_file}")
            return True
        except Exception as exc:
            logger.error(f"   Failed to append to JSONL: {exc}", exc_info=True)
            return False

    def export_user_events(self, user_id: str, window_days: int = 90, db_conn=None) -> list[dict]:
        """
        Return all training events for *user_id* within the look-back window.

        Queries the user_training_events table (both seed and feedback rows)
        ordered chronologically.  Used by the retraining pipeline to build the
        per-user training dataset without touching the raw JSONL file.

        Args:
            user_id     : Azure AD user principal name / user_id string.
            window_days : How many days back to go.  Default 90.
                          Pass 0 for the full history (no time filter).
            db_conn     : Optional live psycopg2 connection.

        Returns:
            List of event dicts, oldest-first. Empty list on error.
        """
        import psycopg2

        own_conn = db_conn is None
        conn = None
        try:
            conn = psycopg2.connect(**self.db_config) if own_conn else db_conn
            with conn.cursor() as cur:
                if window_days > 0:
                    cur.execute(
                        """
                        SELECT event FROM user_training_events
                        WHERE user_id = %s
                          AND event_time > NOW() - (%s * INTERVAL '1 day')
                        ORDER BY event_time ASC
                        """,
                        (user_id, window_days),
                    )
                else:
                    cur.execute(
                        """
                        SELECT event FROM user_training_events
                        WHERE user_id = %s
                        ORDER BY event_time ASC
                        """,
                        (user_id,),
                    )
                rows = cur.fetchall()
            logger.info(f"export_user_events: {len(rows)} events for user={user_id} (window={window_days}d)")
            return [row[0] for row in rows]
        except Exception as exc:
            logger.error(f"   export_user_events failed for user={user_id}: {exc}", exc_info=True)
            return []
        finally:
            if own_conn and conn is not None:
                try:
                    conn.close()
                except Exception:
                    pass

    def _trigger_retrain_job(self, user_id: str, db_conn) -> bool:
        """
        Insert a dfp_retrain_jobs row with status='pending'.

        Returns True on success, False on failure.  If db_conn is None
        the job is logged as a warning but not persisted (the caller
        should supply a connection for production use).
        """
        fp_ids = list(self._pending_fp_ids.get(user_id, []))
        count = self._pending_counts.get(user_id, 0)

        if db_conn is None:
            logger.warning(
                f"Retrain threshold reached for user={user_id} "
                f"({count} events) but no db_conn provided — job NOT persisted."
            )
            return False

        try:
            with db_conn.cursor() as cur:
                # Guard: skip if a pending or running job already exists for this
                # user.  This prevents duplicate jobs if the threshold is reached
                # concurrently or after a restart where sub-threshold counts were
                # inadvertently restored.
                cur.execute(
                    """
                    SELECT job_id FROM dfp_retrain_jobs
                    WHERE user_id = %s AND status IN ('pending', 'running')
                    LIMIT 1
                    """,
                    (user_id,),
                )
                existing = cur.fetchone()
                if existing:
                    logger.info(
                        f"Skipping retrain job for user={user_id} — "
                        f"job {existing[0]} is already pending/running. "
                        "New events will accumulate after that job completes."
                    )
                    # Reset counters so we don't re-check on every subsequent FP.
                    self._pending_counts[user_id] = 0
                    self._pending_fp_ids[user_id] = []
                    return False

                cur.execute(
                    """
                    INSERT INTO dfp_retrain_jobs
                        (user_id, false_positive_ids, new_clean_events, status, created_at, updated_at)
                    VALUES
                        (%s, %s::uuid[], %s, 'pending', NOW(), NOW())
                    RETURNING job_id
                    """,
                    (user_id, fp_ids, count),
                )
                job_id = cur.fetchone()[0]
            db_conn.commit()

            logger.info(f"Retrain job queued for user={user_id} | job_id={job_id} | new_clean_events={count}")
            return True

        except Exception as exc:
            logger.error(
                f"   Failed to create retrain job for user={user_id}: {exc}",
                exc_info=True,
            )
            try:
                db_conn.rollback()
            except Exception:
                pass
            return False


# ─────────────────────────────────────────────────────────────────────────────
# CLI
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse

    import psycopg2
    import psycopg2.extras

    parser = argparse.ArgumentParser(description="DFP Feedback Service — manual operations")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--anomaly-id", help="Mark a specific detection as false positive and add to training")
    group.add_argument("--status", action="store_true", help="Show pending retrain jobs from DB")
    group.add_argument(
        "--dry-run-count",
        type=int,
        metavar="N",
        help="Simulate adding N false positives for a user (dry run — no DB writes)",
    )
    parser.add_argument("--user-id", help="User ID (required for --dry-run-count)")
    args = parser.parse_args()

    conn = psycopg2.connect(**DB_CONFIG)

    service = DFPFeedbackService()

    if args.status:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                """
                SELECT job_id, user_id, status, new_clean_events,
                       false_positive_ids, created_at, started_at, completed_at
                FROM dfp_retrain_jobs
                ORDER BY created_at DESC
                LIMIT 50
                """
            )
            rows = cur.fetchall()
        if not rows:
            print("No retrain jobs found.")
        else:
            print(f"\n{'=' * 80}")
            print(f"  DFP Retrain Jobs ({len(rows)} rows)")
            print(f"{'=' * 80}")
            for row in rows:
                fp_count = len(row["false_positive_ids"] or [])
                print(
                    f"  [{row['status'].upper():10s}] "
                    f"user={row['user_id']:35s} "
                    f"new_events={row['new_clean_events']:4d}  "
                    f"fp_ids={fp_count:3d}  "
                    f"created={str(row['created_at'])[:19]}"
                )
            print(f"{'=' * 80}\n")

    elif args.anomaly_id:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                "SELECT * FROM enriched_anomalies WHERE anomaly_id = %s",
                (args.anomaly_id,),
            )
            detection = cur.fetchone()

        if not detection:
            print(f"Detection not found: {args.anomaly_id}")
            sys.exit(1)

        detection = dict(detection)
        triggered = service.add_false_positive(detection, db_conn=conn)
        print(f"\nFalse positive recorded for anomaly_id={args.anomaly_id}")
        print(f"   User: {detection['user_id']}")
        print(f"   Retrain triggered: {triggered}")
        print(f"   Pending counts: {service.get_pending_counts()}")

    elif args.dry_run_count:
        if not args.user_id:
            print("--user-id is required for --dry-run-count")
            sys.exit(1)
        user_id = args.user_id
        threshold = service.retrain_threshold
        print(f"\nDry-run: simulating {args.dry_run_count} FP events for user={user_id}")
        print(f"   Threshold: {threshold}")
        # Directly manipulate counters without DB or file writes.
        for i in range(1, args.dry_run_count + 1):
            service._pending_counts[user_id] = service._pending_counts.get(user_id, 0) + 1
            if user_id not in service._pending_fp_ids:
                service._pending_fp_ids[user_id] = []
            service._pending_fp_ids[user_id].append(f"fake-uuid-{i:04d}")
            count = service._pending_counts[user_id]
            if count % 50 == 0 or count == threshold:
                print(f"   → {count}/{threshold}")
            if count >= threshold:
                print(f"   Would trigger retrain job at event #{i}")
                service._pending_counts[user_id] = 0
                service._pending_fp_ids[user_id] = []
        final = service._pending_counts.get(user_id, 0)
        print(f"\n   Final pending count for {user_id}: {final}")

    conn.close()
