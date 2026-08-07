#!/usr/bin/env python3
"""
Batch Labeler: Periodic Worker for Auto-Labeling Unlabeled Detections

Queries enriched_anomalies WHERE is_anomaly IS NULL, runs the multi-method
AnomalyValidator ensemble on each, writes labels back to PostgreSQL, and
feeds confirmed false positives into the DFP training loop.

Schedule (suggested):
  - Daily cron  OR
  - Triggered when 50+ unlabeled detections accumulate

Batch defaults:
  - 100 detections per run
  - 30-minute wall-clock timeout

Workflow per detection:
  1. Load full row from enriched_anomalies.
  2. Load prior LLM explanation (factual fields only) from llm_explanations.
  3. Run AnomalyValidator.validate(detection, llm_explanation, db_conn).
  4. Write is_anomaly / validation_confidence / validation_reasoning /
     validated_at / validated_by / dfp_retrain_status back to DB.
  5. If FALSE POSITIVE → DFPFeedbackService.add_false_positive() appends the
     event to the training JSONL and queues a retrain job when threshold hit.
  6. If TRUE ANOMALY  → dfp_retrain_status = 'excluded' (never retrain on it).

Usage:
    # Label up to 100 unlabeled detections
    python modules/ai/auto_labeling/batch_labeler.py

    # Smaller test batch
    python modules/ai/auto_labeling/batch_labeler.py --limit 5

    # Label a specific detection
    python modules/ai/auto_labeling/batch_labeler.py --detection-id <uuid>

    # Dry-run: validate but do NOT write labels or train
    python modules/ai/auto_labeling/batch_labeler.py --dry-run --limit 10

    # Show labeling statistics
    python modules/ai/auto_labeling/batch_labeler.py --stats

Reference:
    modules/ai/auto_labeling/IMPLEMENTATION_PLAN.md  (Phase 3)
    modules/ai/auto_labeling/anomaly_validator.py
    modules/ai/auto_labeling/dfp_feedback_service.py

Author: AI Intelligence Layer Team
Date: 2026-02-27
"""

import logging
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import psycopg2

from scripts.utils import severity_from_score as anomaly_score_to_severity  # noqa: E402

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

DEFAULT_BATCH_LIMIT = 100
LABEL_AUTHOR = "ai_auto_labeler"


# ─────────────────────────────────────────────────────────────────────────────
class BatchLabeler:
    """
    Orchestrates bulk auto-labeling via the AnomalyValidator ensemble.
    """

    def __init__(
        self,
        batch_limit: int = DEFAULT_BATCH_LIMIT,
        dry_run: bool = False,
    ) -> None:
        self.batch_limit = batch_limit
        self.dry_run = dry_run

        # Lazy-loaded services.
        self._validator = None
        self._feedback_service = None

        logger.info("BatchLabeler initialized")
        logger.info(f"   Batch limit : {self.batch_limit}")
        logger.info(f"   Dry run     : {self.dry_run}")

    # ──────────────────────────────────────────────────────────────────────────
    # Lazy service accessors
    # ──────────────────────────────────────────────────────────────────────────

    @property
    def validator(self):
        if self._validator is None:
            from modules.ai.auto_labeling.anomaly_validator import AnomalyValidator

            self._validator = AnomalyValidator()
            logger.info("   AnomalyValidator loaded")
        return self._validator

    @property
    def feedback_service(self):
        if self._feedback_service is None:
            from modules.ai.auto_labeling.dfp_feedback_service import DFPFeedbackService

            self._feedback_service = DFPFeedbackService()
            logger.info("   DFPFeedbackService loaded")
        return self._feedback_service

    # ──────────────────────────────────────────────────────────────────────────
    # Single-record helper (used by AI Orchestrator)
    # ──────────────────────────────────────────────────────────────────────────

    def label_single(self, anomaly_id: str) -> dict:
        """Validate a single detection, opening its own DB connection.

        Convenience wrapper around :meth:`run` for use by the AI Orchestrator
        immediately after a new anomaly is persisted to enriched_anomalies.

        Args:
            anomaly_id: UUID of the enriched_anomaly row to validate.

        Returns:
            Summary dict from run(): ``{total, labeled, true_anomaly,
            false_positive, uncertain, errors, retrain_jobs_triggered,
            elapsed_seconds}``.
        """
        conn = psycopg2.connect(**DB_CONFIG)
        try:
            return self.run(conn, detection_id=anomaly_id)
        finally:
            conn.close()

    # ──────────────────────────────────────────────────────────────────────────
    # Main entry point
    # ──────────────────────────────────────────────────────────────────────────

    def run(self, db_conn, detection_id: str | None = None) -> dict:
        """
        Process a batch of unlabeled detections.

        Args:
            db_conn       : Live psycopg2 connection (caller owns lifecycle).
            detection_id  : If supplied, label only this specific detection.

        Returns:
            Summary dict: {total, labeled, true_anomaly, false_positive,
                           uncertain, errors, retrain_jobs_triggered,
                           elapsed_seconds}
        """

        t0 = time.time()

        stats = {
            "total": 0,
            "labeled": 0,
            "true_anomaly": 0,
            "false_positive": 0,
            "uncertain": 0,
            "errors": 0,
            "retrain_jobs_triggered": 0,
            "elapsed_seconds": 0.0,
        }

        # 1. Fetch unlabeled detections.
        detections = self._fetch_unlabeled(db_conn, detection_id)
        stats["total"] = len(detections)
        logger.info(f"\n{'=' * 80}")
        logger.info(f"BatchLabeler run: {stats['total']} detection(s) to process")
        logger.info(f"   dry_run={self.dry_run}")
        logger.info(f"{'=' * 80}")

        if not detections:
            logger.info("   Nothing to label — all detections already labeled.")
            stats["elapsed_seconds"] = round(time.time() - t0, 2)
            return stats

        # 2. Load pending feedback counts from DB (resume after restart).
        if not self.dry_run:
            self.feedback_service.load_pending_counts_from_db(db_conn)

        # 3. Process each detection.
        for i, detection in enumerate(detections, 1):
            anomaly_id = str(detection.get("anomaly_id", ""))
            user_id = str(detection.get("user_id", ""))
            logger.info(f"\n[{i}/{stats['total']}] Detection {anomaly_id}  user={user_id}")

            try:
                # 3a. Load prior LLM explanation (factual only — no verdict fields).
                llm_explanation = self._fetch_llm_explanation(db_conn, anomaly_id)

                # 3b. Validate.
                result = self.validator.validate(
                    dict(detection),
                    llm_explanation=llm_explanation,
                    db_conn=db_conn,
                )

                is_anomaly: bool | None = result.get("is_anomaly")
                confidence: float = result.get("confidence", 0.0)
                reasoning: str = result.get("reasoning", "")
                weighted_score: float = result.get("weighted_score", 0.0)

                # 3c. Map to enriched_anomalies columns.
                if is_anomaly is True:
                    dfp_retrain_status = "excluded"
                    stats["true_anomaly"] += 1
                    label_str = "TRUE ANOMALY"
                elif is_anomaly is False:
                    dfp_retrain_status = "queued"
                    stats["false_positive"] += 1
                    label_str = "FALSE POSITIVE"
                else:
                    dfp_retrain_status = "pending"  # uncertain — re-check later
                    stats["uncertain"] += 1
                    label_str = "UNCERTAIN"

                logger.info(f"   ➤ {label_str} | confidence={confidence:.2f} | weighted_score={weighted_score:.2f}")

                if self.dry_run:
                    logger.info("   [DRY RUN] Skipping DB write and training append")
                    stats["labeled"] += 1
                    continue

                # 3d. Persist label.
                self._write_label(
                    db_conn=db_conn,
                    anomaly_id=anomaly_id,
                    is_anomaly=is_anomaly,
                    confidence=confidence,
                    reasoning=reasoning,
                    dfp_retrain_status=dfp_retrain_status,
                    anomaly_score=float(detection.get("anomaly_score") or 0.0),
                )

                # 3e. False positive → feedback loop.
                if is_anomaly is False:
                    triggered = self.feedback_service.add_false_positive(dict(detection), db_conn=db_conn)
                    if triggered:
                        stats["retrain_jobs_triggered"] += 1
                    else:
                        # _trigger_retrain_job commits when the retrain threshold
                        # is reached (triggered=True).  When it isn't, the
                        # user_training_events INSERT from _persist_to_db is left
                        # uncommitted on the shared connection.  Commit here so the
                        # INSERT isn't silently rolled back when label_single()
                        # closes the connection.
                        db_conn.commit()

                stats["labeled"] += 1

            except KeyboardInterrupt:
                logger.warning("   Interrupted by user — stopping batch.")
                break
            except Exception as exc:
                logger.error(f"   Error processing {anomaly_id}: {exc}", exc_info=True)
                stats["errors"] += 1

        stats["elapsed_seconds"] = round(time.time() - t0, 2)
        self._print_summary(stats)
        return stats

    # ──────────────────────────────────────────────────────────────────────────
    # DB helpers
    # ──────────────────────────────────────────────────────────────────────────

    def _fetch_unlabeled(self, db_conn, detection_id: str | None) -> list[dict]:
        """Return unlabeled detections from enriched_anomalies."""
        import psycopg2.extras

        with db_conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            if detection_id:
                cur.execute(
                    "SELECT * FROM enriched_anomalies WHERE anomaly_id = %s",
                    (detection_id,),
                )
            else:
                cur.execute(
                    """
                    SELECT *
                    FROM enriched_anomalies
                    WHERE is_anomaly IS NULL
                    ORDER BY timestamp DESC
                    LIMIT %s
                    """,
                    (self.batch_limit,),
                )
            return [dict(row) for row in cur.fetchall()]

    def _fetch_llm_explanation(self, db_conn, anomaly_id: str) -> dict | None:
        """
        Load factual-only fields from llm_explanations for the anomaly.

        Verdict fields (anomaly_classification, severity_level, confidence_score,
        risk_assessment) are deliberately excluded to prevent confirmation bias.
        """
        import psycopg2.extras

        try:
            with db_conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(
                    """
                    SELECT context_analysis, pattern_analysis, evidence_summary,
                           entities_referenced, user_baseline_used, reasoning_process
                    FROM llm_explanations
                    WHERE detection_id = %s
                    ORDER BY version DESC
                    LIMIT 1
                    """,
                    (anomaly_id,),
                )
                row = cur.fetchone()
                return dict(row) if row else None
        except Exception as exc:
            logger.debug(f"   Could not load LLM explanation for {anomaly_id}: {exc}")
            return None

    def _write_label(
        self,
        db_conn,
        anomaly_id: str,
        is_anomaly: bool | None,
        confidence: float,
        reasoning: str,
        dfp_retrain_status: str,
        anomaly_score: float = 0.0,
    ) -> None:
        """Write validation result back to enriched_anomalies."""
        severity = anomaly_score_to_severity(anomaly_score)
        with db_conn.cursor() as cur:
            cur.execute(
                """
                UPDATE enriched_anomalies
                SET
                    is_anomaly            = %s,
                    validation_confidence = %s,
                    validation_reasoning  = %s,
                    validated_at          = %s,
                    validated_by          = %s,
                    dfp_retrain_status    = %s,
                    severity              = COALESCE(severity, %s),
                    updated_at            = NOW()
                WHERE anomaly_id = %s
                """,
                (
                    is_anomaly,
                    confidence,
                    reasoning[:4000] if reasoning else None,  # guard column width
                    datetime.now(timezone.utc),
                    LABEL_AUTHOR,
                    dfp_retrain_status,
                    severity,
                    anomaly_id,
                ),
            )
        db_conn.commit()
        logger.debug(f"   Label written for {anomaly_id}")

    # ──────────────────────────────────────────────────────────────────────────
    # Reporting
    # ──────────────────────────────────────────────────────────────────────────

    @staticmethod
    def _print_summary(stats: dict) -> None:
        logger.info(f"\n{'=' * 80}")
        logger.info("Batch Labeler Summary")
        logger.info(f"{'=' * 80}")
        logger.info(f"   Total processed      : {stats['total']}")
        logger.info(f"   Successfully labeled : {stats['labeled']}")
        logger.info(f"   ├─ TRUE ANOMALY      : {stats['true_anomaly']}")
        logger.info(f"   ├─ FALSE POSITIVE    : {stats['false_positive']}")
        logger.info(f"   └─ UNCERTAIN         : {stats['uncertain']}")
        logger.info(f"   Errors               : {stats['errors']}")
        logger.info(f"   Retrain jobs queued  : {stats['retrain_jobs_triggered']}")
        logger.info(f"   Elapsed              : {stats['elapsed_seconds']}s")
        logger.info(f"{'=' * 80}\n")

    @staticmethod
    def print_db_stats(db_conn) -> None:
        """Print labeling progress from enriched_anomalies."""
        import psycopg2.extras

        with db_conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                """
                SELECT
                    COUNT(*)                                   AS total,
                    COUNT(*) FILTER (WHERE is_anomaly IS NULL) AS unlabeled,
                    COUNT(*) FILTER (WHERE is_anomaly = TRUE)  AS true_anomaly,
                    COUNT(*) FILTER (WHERE is_anomaly = FALSE) AS false_positive,
                    AVG(validation_confidence)
                        FILTER (WHERE validation_confidence IS NOT NULL)
                                                               AS avg_confidence,
                    COUNT(*) FILTER (WHERE validated_by = 'ai_auto_labeler')
                                                               AS ai_labeled,
                    COUNT(*) FILTER (WHERE validated_by LIKE 'analyst%')
                                                               AS analyst_labeled
                FROM enriched_anomalies
                """
            )
            row = cur.fetchone()

        print(f"\n{'=' * 60}")
        print("  enriched_anomalies — Labeling Progress")
        print(f"{'=' * 60}")
        print(f"  Total detections     : {row['total']}")
        print(f"  ├─ Unlabeled         : {row['unlabeled']}")
        print(f"  ├─ TRUE ANOMALY      : {row['true_anomaly']}")
        print(f"  ├─ FALSE POSITIVE    : {row['false_positive']}")
        print(f"  ├─ AI labeled        : {row['ai_labeled']}")
        print(f"  └─ Analyst labeled   : {row['analyst_labeled']}")
        avg_conf = row["avg_confidence"]
        print(f"  Avg confidence       : {avg_conf:.3f}" if avg_conf else "  Avg confidence       : N/A")
        print(f"{'=' * 60}\n")

        # Pending retrain jobs
        with db_conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                """
                SELECT status, COUNT(*) AS n, SUM(new_clean_events) AS total_events
                FROM dfp_retrain_jobs
                GROUP BY status
                ORDER BY status
                """
            )
            jobs = cur.fetchall()

        if jobs:
            print("  dfp_retrain_jobs")
            print(f"{'─' * 40}")
            for j in jobs:
                print(f"  [{j['status']:10s}] {j['n']:3d} job(s)  events={j['total_events'] or 0}")
            print()


# ─────────────────────────────────────────────────────────────────────────────
# CLI
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse

    import psycopg2

    parser = argparse.ArgumentParser(description="Batch Labeler — auto-label unlabeled anomaly detections")
    parser.add_argument(
        "--limit",
        type=int,
        default=DEFAULT_BATCH_LIMIT,
        help=f"Maximum detections per run (default: {DEFAULT_BATCH_LIMIT})",
    )
    parser.add_argument(
        "--detection-id",
        metavar="UUID",
        help="Label a specific detection by ID",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Run validation but skip DB writes and training appends",
    )
    parser.add_argument(
        "--stats",
        action="store_true",
        help="Print labeling statistics and exit",
    )
    args = parser.parse_args()
    # LLM provider is read from LLM_PROVIDER in .env — no CLI override needed

    conn = psycopg2.connect(**DB_CONFIG)

    try:
        if args.stats:
            BatchLabeler.print_db_stats(conn)
            sys.exit(0)

        labeler = BatchLabeler(
            batch_limit=args.limit,
            dry_run=args.dry_run,
        )

        summary = labeler.run(
            db_conn=conn,
            detection_id=args.detection_id,
        )

        sys.exit(0 if summary["errors"] == 0 else 1)

    finally:
        conn.close()
