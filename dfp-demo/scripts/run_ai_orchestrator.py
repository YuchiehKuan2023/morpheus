#!/usr/bin/env python3
"""
AI Orchestrator Entrypoint
==========================

Starts the dual-thread real-time AI intelligence layer:

    Thread A — anomaly path
      dfp-detections → enrich → persist → Stage 1 validation → Stage 2 + risk score

    Thread B — clean path
      dfp-clean-events → persist to user_training_events (source='clean')

Usage
-----
    # From the dfp-demo directory:
    python scripts/run_ai_orchestrator.py

    # With explicit topic/bootstrap overrides:
    KAFKA_BOOTSTRAP_SERVERS=127.0.0.1:29092 \
    ANOMALY_TOPIC=dfp-detections \
    CLEAN_TOPIC=dfp-clean-events \
        python scripts/run_ai_orchestrator.py

    # Custom group IDs (useful for running multiple orchestrator instances):
    ANOMALY_GROUP_ID=orchestrator-a CLEAN_GROUP_ID=orchestrator-b \
        python scripts/run_ai_orchestrator.py

Prerequisites
-------------
    - Kafka RUNNING         : docker-compose up -d kafka
    - PostgreSQL RUNNING    : docker-compose up -d postgres
    - inference_pipeline    : producing to dfp-detections + dfp-clean-events
    - DistilBERT model      : data/models/root_cause/  (for classify_single)
    - Risk scorer model     : data/models/risk_scorer/ (optional — skipped if absent)

Environment variables (all optional — defaults shown)
------------------------------------------------------
    KAFKA_BOOTSTRAP_SERVERS   127.0.0.1:29092
    ANOMALY_TOPIC             dfp-detections
    CLEAN_TOPIC               dfp-clean-events
    ANOMALY_GROUP_ID          ai-orchestrator-anomalies
    CLEAN_GROUP_ID            ai-orchestrator-clean
    POSTGRES_HOST             localhost
    POSTGRES_PORT             5432
    POSTGRES_DB               dfp_ai
    POSTGRES_USER             dfp_ai
    POSTGRES_PASSWORD         (required — set in .env)
    NEO4J_URI                 bolt://localhost:7687
    NEO4J_USER                neo4j
    NEO4J_PASSWORD            (required — set in .env)
    QDRANT_HOST               localhost
    QDRANT_PORT               6333

Author: AI Intelligence Layer Team
Date: 2026-03-11
"""

from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# Ensure project root is on sys.path and .env is loaded before any imports
# ---------------------------------------------------------------------------
PROJECT_ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

try:
    from dotenv import load_dotenv

    load_dotenv(PROJECT_ROOT / ".env", override=False)
except ImportError:
    pass  # dotenv optional — env vars can be set externally

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(name)-35s  %(levelname)-8s  %(message)s",
)
logger = logging.getLogger("run_ai_orchestrator")

# ---------------------------------------------------------------------------
# Late imports (after sys.path + env are set)
# ---------------------------------------------------------------------------
import modules.ai.root_cause.labeling_worker as labeling_worker_mod  # noqa: E402
from modules.ai.auto_labeling.batch_labeler import BatchLabeler  # noqa: E402
from modules.ai.enrichment.enrichment_service import EnrichmentService  # noqa: E402
from modules.ai.enrichment.persistence_service import PersistenceService  # noqa: E402
from modules.ai.llm.llm_service import LLMService  # noqa: E402
from modules.ai.orchestrator.ai_orchestrator import AIOrchestrator  # noqa: E402


def main() -> None:
    kafka_bootstrap = os.getenv("KAFKA_BOOTSTRAP_SERVERS", "127.0.0.1:29092")
    anomaly_topic = os.getenv("ANOMALY_TOPIC", "dfp-detections")
    clean_topic = os.getenv("CLEAN_TOPIC", "dfp-clean-events")
    anomaly_group_id = os.getenv("ANOMALY_GROUP_ID", "ai-orchestrator-anomalies")
    clean_group_id = os.getenv("CLEAN_GROUP_ID", "ai-orchestrator-clean")

    logger.info("Initialising services…")

    # PersistenceService: opened here; stays alive for the orchestrator lifetime.
    # batch_mode=False → writes Neo4j + Qdrant as well as PostgreSQL (real-time mode).
    persistence_svc = PersistenceService(
        enable_kafka=False,  # orchestrator does not re-publish detections
        batch_mode=False,
    )

    # EnrichmentService: shares the same PersistenceService so DB connections
    # are not duplicated.
    llm_svc = LLMService(
        model_name=os.getenv("LLM_ORCHESTRATOR_MODEL", "Meta-Llama-3.1-405B-Instruct"),
        fallback_model=os.getenv("LLM_ORCHESTRATOR_FALLBACK", "gpt-4o"),
    )
    enrichment_svc = EnrichmentService(
        persistence_service=persistence_svc,
        llm_service=llm_svc,
        enable_llm_explanations=True,
    )

    # BatchLabeler: Stage 1 AnomalyValidator orchestration.
    batch_labeler = BatchLabeler()

    logger.info("Services ready.")
    logger.info(f"  kafka_bootstrap : {kafka_bootstrap}")
    logger.info(f"  anomaly_topic   : {anomaly_topic}")
    logger.info(f"  clean_topic     : {clean_topic}")
    logger.info(f"  anomaly_group   : {anomaly_group_id}")
    logger.info(f"  clean_group     : {clean_group_id}")

    orchestrator = AIOrchestrator(
        enrichment_service=enrichment_svc,
        persistence_service=persistence_svc,
        batch_labeler=batch_labeler,
        labeling_worker_module=labeling_worker_mod,
        kafka_bootstrap=kafka_bootstrap,
        anomaly_topic=anomaly_topic,
        clean_topic=clean_topic,
        anomaly_group_id=anomaly_group_id,
        clean_group_id=clean_group_id,
    )

    # run() blocks until KeyboardInterrupt → graceful shutdown.
    orchestrator.run()


if __name__ == "__main__":
    main()
