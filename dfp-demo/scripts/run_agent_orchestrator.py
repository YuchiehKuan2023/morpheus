#!/usr/bin/env python3
"""
Agent Orchestrator Entrypoint
==============================

Starts the multi-agent investigation coordinator.

The AgentOrchestrator consumes anomaly tasks from the ``dfp-agent-tasks``
Kafka topic (published by AIOrchestrator for HIGH/CRITICAL anomalies and
high-risk MEDIUM anomalies) and coordinates:

    ForensicsAgent      — attack chain reconstruction + LLM narrative
    InvestigationAgent  — KNN similarity search + recurrence detection
    RemediationAgent    — rule-based response actions + LLM rationale

ForensicsAgent and InvestigationAgent run concurrently (ThreadPoolExecutor);
RemediationAgent runs after both complete.

Usage
-----
    # From the dfp-demo directory:
    python scripts/run_agent_orchestrator.py

    # With explicit overrides:
    KAFKA_BOOTSTRAP_SERVERS=127.0.0.1:29092 \
        python scripts/run_agent_orchestrator.py

Prerequisites
-------------
    - Kafka RUNNING         : docker-compose up -d kafka
    - PostgreSQL RUNNING    : docker-compose up -d postgres
    - Neo4j RUNNING         : docker-compose up -d neo4j
    - Qdrant RUNNING        : docker-compose up -d qdrant
    - AI Orchestrator       : producing to dfp-agent-tasks

Environment variables (all optional — defaults shown)
------------------------------------------------------
    KAFKA_BOOTSTRAP_SERVERS   127.0.0.1:29092
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
Date: 2026-03-24
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
logger = logging.getLogger("run_agent_orchestrator")

# ---------------------------------------------------------------------------
# Late imports (after sys.path + env are set)
# ---------------------------------------------------------------------------
from modules.ai.agents.agent_orchestrator import AgentOrchestrator  # noqa: E402
from modules.ai.llm.llm_service import LLMService  # noqa: E402


def _build_db_url() -> str:
    from modules.utils.db import get_db_url

    return get_db_url()


def main() -> None:
    kafka_bootstrap = os.getenv("KAFKA_BOOTSTRAP_SERVERS", "127.0.0.1:29092")

    logger.info("Initialising services…")

    # Neo4j driver
    try:
        import neo4j

        neo4j_uri = os.getenv("NEO4J_URI", "bolt://localhost:7687")
        neo4j_user = os.getenv("NEO4J_USER", "neo4j")
        neo4j_password = os.getenv("NEO4J_PASSWORD", "")
        neo4j_driver = neo4j.GraphDatabase.driver(neo4j_uri, auth=(neo4j_user, neo4j_password))
        logger.info(f"  Neo4j           : {neo4j_uri}")
    except Exception as exc:
        logger.error("Failed to connect to Neo4j: %s", exc)
        sys.exit(1)

    # Qdrant client
    try:
        from qdrant_client import QdrantClient

        qdrant_host = os.getenv("QDRANT_HOST", "localhost")
        qdrant_port = int(os.getenv("QDRANT_PORT", "6333"))
        qdrant_client = QdrantClient(host=qdrant_host, port=qdrant_port)
        logger.info(f"  Qdrant          : {qdrant_host}:{qdrant_port}")
    except Exception as exc:
        logger.error("Failed to connect to Qdrant: %s", exc)
        sys.exit(1)

    # LLM service — uses LLM_AGENT_MODEL (separate daily budget from AI Orchestrator)
    llm_service = LLMService(model_name=os.getenv("LLM_AGENT_MODEL", "Phi-4"))
    logger.info("  LLMService      : ready")

    # PostgreSQL URL
    db_url = _build_db_url()
    logger.info(f"  PostgreSQL      : {os.getenv('POSTGRES_HOST', 'localhost')}:{os.getenv('POSTGRES_PORT', '5432')}")

    logger.info("  kafka_bootstrap : %s", kafka_bootstrap)
    logger.info("Services ready.")

    orchestrator = AgentOrchestrator(
        db_url=db_url,
        neo4j_driver=neo4j_driver,
        qdrant_client=qdrant_client,
        llm_service=llm_service,
        kafka_bootstrap=kafka_bootstrap,
    )

    # start() blocks until KeyboardInterrupt → graceful shutdown
    try:
        orchestrator.start()
    except KeyboardInterrupt:
        logger.info("KeyboardInterrupt received; shutting down orchestrator...")
    finally:
        try:
            neo4j_driver.close()
            logger.info("Neo4j driver closed.")
        except Exception as exc:
            logger.warning("Failed to close Neo4j driver cleanly: %s", exc)


if __name__ == "__main__":
    main()
