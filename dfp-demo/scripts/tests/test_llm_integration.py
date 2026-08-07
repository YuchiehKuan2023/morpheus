#!/usr/bin/env python3
"""
Test LLM Integration with Existing Enriched Detections

This script:
1. Loads enriched_anomalies records from database
2. Generates LLM explanations using llm_service
3. Persists explanations to llm_explanations table
4. Supports --limit flag to test on small samples first

Usage:
    # Test on 10 records first
    python scripts/tests/test_llm_integration.py --limit 10

    # Process all records
    python scripts/tests/test_llm_integration.py --limit 1000

    # Preview without saving
    python scripts/tests/test_llm_integration.py --limit 5 --dry-run

    # Process a specific detection by anomaly_id
    python scripts/tests/test_llm_integration.py --detection-id <uuid>

    # Preview a specific detection without saving
    python scripts/tests/test_llm_integration.py --detection-id <uuid> --dry-run
"""

import argparse
import logging
import os
import sys
from datetime import datetime
from pathlib import Path

import psycopg2
from dotenv import load_dotenv

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from modules.ai.llm.db_persistence import save_llm_explanation
from modules.ai.llm.llm_service import LLMService

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

# Enable DEBUG for LLM service to see detailed metrics and responses
logging.getLogger("modules.ai.llm.llm_service").setLevel(logging.DEBUG)


def load_enriched_detections(conn, limit: int = 10, detection_id: str | None = None):
    """Load enriched_anomalies from database.

    Args:
        conn: psycopg2 connection
        limit: Maximum rows when detection_id is not specified
        detection_id: If supplied, load only this specific anomaly_id (ignores limit)
    """
    if detection_id:
        query = """
            SELECT
                anomaly_id,
                user_id,
                timestamp,
                anomaly_score,
                original_event,
                raw_detection,
                ai_enrichment
            FROM enriched_anomalies
            WHERE anomaly_id = %s
              AND ai_enrichment IS NOT NULL
        """
        with conn.cursor() as cur:
            cur.execute(query, (detection_id,))
            rows = cur.fetchall()
        if not rows:
            logger.warning(f"No enriched detection found for anomaly_id={detection_id}")
    else:
        query = """
            SELECT
                anomaly_id,
                user_id,
                timestamp,
                anomaly_score,
                original_event,
                raw_detection,
                ai_enrichment
            FROM enriched_anomalies
            WHERE ai_enrichment IS NOT NULL
            ORDER BY timestamp DESC
            LIMIT %s
        """
        with conn.cursor() as cur:
            cur.execute(query, (limit,))
            rows = cur.fetchall()

    logger.info(f"Loaded {len(rows)} enriched detection(s) from database")
    return rows


def reconstruct_enriched_detection(
    anomaly_id: str,
    user_id: str,
    timestamp: datetime,
    anomaly_score: float,
    original_event: dict,
    raw_detection: dict,
    ai_enrichment: dict,
) -> dict:
    """
    Reconstruct enriched detection dict from database record.

    Args:
        anomaly_id: UUID of the anomaly
        user_id: User identifier
        timestamp: Detection timestamp
        anomaly_score: Anomaly score (redundant with raw_detection, but kept for reference)
        original_event: Original Azure AD event (JSONB column)
        raw_detection: DFP detection with z_scores, features (JSONB column)
        ai_enrichment: AI enrichment with entities, similarity, graph (JSONB column)

    Returns:
        Complete enriched detection structure for LLM service
    """
    return {
        # Top-level metadata (required by LLM service prompt builder)
        "anomaly_id": str(anomaly_id),
        "user_id": user_id,
        "timestamp": timestamp.isoformat() if isinstance(timestamp, datetime) else str(timestamp),
        "anomaly_score": anomaly_score,
        # Extract additional DFP metrics from raw_detection for convenience
        "max_abs_z": raw_detection.get("max_abs_z", 0),
        "top_features": raw_detection.get("top_features", "N/A"),
        # Full data structures (JSONB columns)
        "raw_detection": raw_detection,  # Contains z_scores, all features
        "original_event": original_event,  # Azure AD event
        "ai_enrichment": ai_enrichment,  # Entities, similarity, graph, baseline
    }


def process_detections(
    conn,
    llm_service: LLMService,
    limit: int = 10,
    dry_run: bool = False,
    detection_id: str | None = None,
    print_prompt: bool = False,
):
    """Process enriched detections and generate LLM explanations."""
    rows = load_enriched_detections(conn, limit, detection_id=detection_id)

    success_count = 0
    error_count = 0

    for row in rows:
        anomaly_id, user_id, timestamp, anomaly_score, original_event, raw_detection, ai_enrichment = row

        try:
            # Reconstruct enriched detection
            enriched = reconstruct_enriched_detection(
                anomaly_id=anomaly_id,
                user_id=user_id,
                timestamp=timestamp,
                anomaly_score=anomaly_score,
                original_event=original_event,
                raw_detection=raw_detection,
                ai_enrichment=ai_enrichment,
            )

            # Optionally save the full prompt to a file before calling the LLM
            if print_prompt:
                try:
                    rag_context = llm_service.rag_pipeline.assemble_context(enriched)
                    user_prompt = llm_service._build_prompt(enriched, rag_context)
                    system_prompt = llm_service._get_system_prompt()
                    sep = "=" * 80

                    full_output = "\n".join(
                        [
                            "",
                            sep,
                            f"SYSTEM PROMPT  [{anomaly_id}]",
                            sep,
                            system_prompt,
                            "",
                            sep,
                            f"USER PROMPT  [{anomaly_id}]",
                            sep,
                            user_prompt,
                            sep,
                            "",
                        ]
                    )

                    # Write to file (avoids terminal scroll buffer truncation)
                    prompt_file = (
                        Path(__file__).resolve().parent.parent.parent
                        / "data"
                        / "output"
                        / "prompts"
                        / f"{anomaly_id}.txt"
                    )
                    prompt_file.parent.mkdir(parents=True, exist_ok=True)
                    logger.info(f"Writing prompt to {prompt_file} ...")
                    prompt_file.write_text(full_output, encoding="utf-8")
                    logger.info(f"Prompt saved ({len(full_output)} chars) → {prompt_file}")
                except Exception as prompt_err:
                    logger.error(f"Failed to save prompt for {anomaly_id}: {prompt_err}", exc_info=True)

            # Generate explanation
            logger.info(f"Generating explanation for anomaly {anomaly_id} ({user_id})")
            explanation = llm_service.generate_explanation(enriched)

            if dry_run:
                logger.info("[DRY RUN] Would save explanation:")
                logger.info(f"  Classification: {explanation.get('anomaly_classification')}")
                logger.info(f"  Severity: {explanation.get('severity_level')}")
                logger.info(f"  Summary: {explanation.get('summary', '')[:100]}...")
            else:
                # Save to database (detection_id in llm_explanations references anomaly_id)
                save_llm_explanation(conn, anomaly_id, explanation, enriched)
                logger.info(f"Saved explanation for {anomaly_id}")

            success_count += 1

        except Exception as e:
            logger.error(f"Failed to process anomaly {anomaly_id}: {e}")
            error_count += 1

    logger.info("\nProcessing complete:")
    logger.info(f"  Success: {success_count}")
    logger.info(f"  Errors: {error_count}")


def main():
    parser = argparse.ArgumentParser(description="Test LLM integration with existing enriched detections")
    parser.add_argument(
        "--limit",
        type=int,
        default=10,
        help="Number of detections to process when --detection-id is not set (default: 10)",
    )
    parser.add_argument(
        "--detection-id",
        metavar="UUID",
        help="Process a specific detection by anomaly_id (overrides --limit)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Generate explanations but don't save to database",
    )
    parser.add_argument(
        "--print-prompt",
        action="store_true",
        help="Print the full system + user prompt to stdout before each LLM call",
    )
    args = parser.parse_args()

    # Load environment variables (.env is the single source of truth for LLM_PROVIDER)
    load_dotenv()

    # Initialize LLM service — reads LLM_PROVIDER from .env automatically
    provider_label = os.getenv("LLM_PROVIDER", "groq")
    logger.info(f"Initializing LLM service (provider={provider_label})...")
    llm_service = LLMService()

    # Connect to database
    logger.info("Connecting to database...")
    from modules.utils.db import get_db_params

    conn = psycopg2.connect(**get_db_params())

    try:
        # Process detections
        if args.detection_id:
            logger.info(f"Processing detection {args.detection_id} (dry_run={args.dry_run})...")
        else:
            logger.info(f"Processing {args.limit} detections (dry_run={args.dry_run})...")
        process_detections(
            conn=conn,
            llm_service=llm_service,
            limit=args.limit,
            dry_run=args.dry_run,
            detection_id=args.detection_id,
            print_prompt=args.print_prompt,
        )

        if not args.dry_run:
            conn.commit()
            logger.info("Changes committed to database")

    except Exception as e:
        logger.error(f"Processing failed: {e}")
        conn.rollback()
        raise

    finally:
        conn.close()
        logger.info("Database connection closed")


if __name__ == "__main__":
    main()
