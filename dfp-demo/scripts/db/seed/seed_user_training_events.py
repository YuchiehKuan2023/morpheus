#!/usr/bin/env python3
"""
Seed user_training_events from the original JSONL training file.

Reads data/input/train/azure_ad_train.jsonl and bulk-inserts every event into
the user_training_events table with source='seed'.  Every line in the JSONL is
a distinct training event and ALL of them are inserted — including events that
share the same (user_id, event_time) because Azure AD can legitimately emit
multiple sign-ins at the exact same timestamp.

Idempotency: the script refuses to run if seed rows already exist unless
--force is supplied, which clears previous seed rows first.

Usage:
    cd dfp-demo
    python scripts/db/seed_user_training_events.py

    # Dry run (count only, no writes):
    python scripts/db/seed_user_training_events.py --dry-run

    # Re-seed after wiping existing seed rows:
    python scripts/db/seed_user_training_events.py --force

    # Custom batch size:
    python scripts/db/seed_user_training_events.py --batch-size 5000

    # Custom JSONL file:
    python scripts/db/seed_user_training_events.py --file data/input/train/my_events.jsonl

Environment variables (same as the rest of the pipeline):
    POSTGRES_HOST, POSTGRES_PORT, POSTGRES_DB, POSTGRES_USER, POSTGRES_PASSWORD

Author: AI Intelligence Layer Team
Date:   2026-03-15
"""

import argparse
import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

try:
    from dotenv import load_dotenv

    _env_path = Path(__file__).parents[3] / ".env"
    load_dotenv(_env_path, override=False)
except ImportError:
    pass

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).parents[3]  # dfp-demo/
DEFAULT_JSONL = PROJECT_ROOT / "data" / "input" / "train" / "azure_ad_train.jsonl"

from modules.utils.db import get_db_params  # noqa: E402

DB_CONFIG = get_db_params()


def _parse_event_time(event: dict) -> datetime:
    """Extract event timestamp; fall back to UTC-now on parse failure."""
    raw = event.get("time") or event.get("createdDateTime", "")
    if raw:
        try:
            return datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except (ValueError, AttributeError):
            pass
    return datetime.now(timezone.utc)


def _extract_user_id(event: dict) -> str:
    """Return userPrincipalName from properties, or 'unknown'."""
    return event.get("properties", {}).get("userPrincipalName") or event.get("userPrincipalName") or "unknown"


def _count_existing_seeds(conn) -> int:
    with conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM user_training_events WHERE source = 'seed'")
        return cur.fetchone()[0]


def seed(jsonl_path: Path, batch_size: int, dry_run: bool, force: bool) -> None:
    import psycopg2
    import psycopg2.extras

    if not jsonl_path.exists():
        logger.error(f"JSONL file not found: {jsonl_path}")
        sys.exit(1)

    logger.info(f"Source file : {jsonl_path}")
    logger.info(f"Batch size  : {batch_size}")
    logger.info(f"Dry run     : {dry_run}")
    logger.info(f"Force       : {force}")

    # Count lines first so we can display progress without loading into RAM.
    logger.info("Counting lines …")
    total_lines = sum(1 for _ in jsonl_path.open(encoding="utf-8"))
    logger.info(f"Total lines : {total_lines:,}")

    if dry_run:
        logger.info("Dry run complete — no DB changes made.")
        return

    conn = psycopg2.connect(**DB_CONFIG)
    try:
        existing = _count_existing_seeds(conn)
        logger.info(f"Existing seed rows in DB: {existing:,}")

        if existing > 0 and not force:
            logger.error(
                f"Table already contains {existing:,} seed rows. Re-run with --force to wipe them and re-seed."
            )
            sys.exit(1)

        if existing > 0 and force:
            logger.info(f"--force: deleting {existing:,} existing seed rows …")
            with conn.cursor() as cur:
                cur.execute("DELETE FROM user_training_events WHERE source = 'seed'")
            conn.commit()
            logger.info("Existing seed rows deleted.")

        inserted_total = 0
        parse_errors = 0
        batch: list[tuple] = []

        with jsonl_path.open(encoding="utf-8") as fh:
            for line_no, raw_line in enumerate(fh, start=1):
                raw_line = raw_line.strip()
                if not raw_line:
                    continue
                try:
                    event = json.loads(raw_line)
                except json.JSONDecodeError as exc:
                    logger.warning(f"  Line {line_no}: invalid JSON — {exc}")
                    parse_errors += 1
                    continue

                user_id = _extract_user_id(event)
                event_time = _parse_event_time(event)
                batch.append((user_id, event_time, psycopg2.extras.Json(event)))

                if len(batch) >= batch_size:
                    inserted_total += _flush_batch(conn, batch)
                    batch.clear()
                    pct = line_no / total_lines * 100
                    logger.info(
                        f"  Progress: {line_no:,}/{total_lines:,} lines ({pct:.1f}%) — inserted={inserted_total:,}"
                    )

        # Flush remainder.
        if batch:
            inserted_total += _flush_batch(conn, batch)

        logger.info("=" * 60)
        logger.info("Seed complete.")
        logger.info(f"  Lines processed : {total_lines:,}")
        logger.info(f"  Rows inserted   : {inserted_total:,}")
        if parse_errors:
            logger.warning(f"  Parse errors    : {parse_errors:,}  (invalid JSON lines — check JSONL file)")
        logger.info(f"  Total seed rows : {_count_existing_seeds(conn):,}")
        logger.info("=" * 60)

    finally:
        conn.close()


def _flush_batch(conn, batch: list[tuple]) -> int:
    """Bulk-insert one batch. Returns number of rows inserted."""
    import psycopg2.extras

    try:
        with conn.cursor() as cur:
            psycopg2.extras.execute_values(
                cur,
                """
                INSERT INTO user_training_events (user_id, event_time, event, source)
                VALUES %s
                """,
                batch,
                template="(%s, %s, %s, 'seed')",
                page_size=len(batch),
            )
        conn.commit()
        return len(batch)
    except Exception as exc:
        logger.error(f"Batch flush failed: {exc}", exc_info=True)
        try:
            conn.rollback()
        except Exception:
            pass
        return 0


# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Seed user_training_events from JSONL")
    parser.add_argument(
        "--file",
        default=str(DEFAULT_JSONL),
        help=f"Path to JSONL training file (default: {DEFAULT_JSONL})",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=2000,
        help="Rows per INSERT batch (default: 2000)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Count lines and exit without writing to DB",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Delete existing seed rows and re-seed from scratch",
    )
    args = parser.parse_args()

    seed(Path(args.file), args.batch_size, args.dry_run, args.force)
