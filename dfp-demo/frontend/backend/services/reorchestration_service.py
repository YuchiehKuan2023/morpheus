"""
Re-orchestration Service — run the full AI pipeline on an existing unprocessed anomaly.

Reuses the same modules as the AI orchestrator (enrichment, LLM explanation,
batch labeling, classification, agent dispatch) but operates on an anomaly
that already exists in enriched_anomalies rather than consuming from Kafka.

The caller receives a session_id that can be used to poll progress via SSE
(the same simulation_sessions table and StageTracker are reused).

Flow:
    1. Validate anomaly exists and is unprocessed (processed = FALSE)
    2. Create a simulation_sessions row for tracking
    3. Spawn a background thread that runs the pipeline steps sequentially
    4. Spawn a StageTracker that polls DB for each step's completion
    5. Return session_id to the caller immediately
"""

import json
import logging
import os
import threading
import uuid
from datetime import datetime, timezone

import psycopg2
import psycopg2.extras

from modules.utils.db import get_db_params

logger = logging.getLogger(__name__)


def reorchestrate_anomaly(anomaly_id: str) -> dict:
    """Kick off full AI pipeline on an existing unprocessed anomaly.

    Returns:
        {"session_id": str, "anomaly_id": str}

    Raises:
        ValueError: if anomaly not found or already processed.
    """
    db_params = get_db_params()
    conn = psycopg2.connect(**db_params)

    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                """SELECT anomaly_id, user_id, anomaly_score, original_event,
                          raw_detection, ai_enrichment, processed, validated_by
                   FROM enriched_anomalies WHERE anomaly_id = %s""",
                (anomaly_id,),
            )
            row = cur.fetchone()
    finally:
        conn.close()

    if not row:
        raise LookupError(f"Anomaly {anomaly_id} not found")
    if row["processed"]:
        raise ValueError(f"Anomaly {anomaly_id} is already processed")

    # Create a simulation_sessions tracking row
    session_id = uuid.uuid4()
    user_id = row["user_id"]
    now = datetime.now(timezone.utc)

    conn = psycopg2.connect(**db_params)
    try:
        with conn.cursor() as cur:
            cur.execute(
                """INSERT INTO simulation_sessions
                   (session_id, run_id, user_id, event_type, stage,
                    anomaly_id, anomaly_score, sent_at, updated_at)
                   VALUES (%s, %s, %s, 'reorchestration', 'detected',
                           %s, %s, %s, %s)""",
                (
                    str(session_id),
                    str(uuid.uuid4()),  # unique run_id for this one-off
                    user_id,
                    anomaly_id,
                    row["anomaly_score"],
                    now,
                    now,
                ),
            )
        conn.commit()
    finally:
        conn.close()

    # Spawn the pipeline worker thread
    worker = threading.Thread(
        target=_run_pipeline,
        args=(anomaly_id, dict(row), db_params),
        daemon=True,
        name=f"reorch-{anomaly_id[:8]}",
    )
    worker.start()

    # Spawn StageTracker with skip_detection=True (anomaly already exists)
    from simulation.stage_tracker import StageTracker

    tracker = StageTracker(
        session_id=session_id,
        user_id=user_id,
        sent_at=now,
        db_params=db_params,
        skip_detection=True,
        anomaly_id=anomaly_id,
    )
    tracker.start()

    return {"session_id": str(session_id), "anomaly_id": anomaly_id}


def _run_pipeline(anomaly_id: str, row: dict, db_params: dict) -> None:
    """Execute the full AI pipeline steps sequentially (background thread)."""
    try:
        _run_pipeline_inner(anomaly_id, row, db_params)
    except Exception:
        logger.exception("Re-orchestration pipeline failed for %s", anomaly_id)


def _run_pipeline_inner(anomaly_id: str, row: dict, db_params: dict) -> None:
    original_event = row["original_event"] or {}
    raw_detection = row["raw_detection"] or {}

    # Step 1: Enrichment (NER, embeddings, similarity, graph context)
    from modules.ai.enrichment.enrichment_service import EnrichmentService
    from modules.ai.enrichment.persistence_service import PersistenceService
    from modules.ai.llm.llm_service import LLMService
    from modules.ai.shared.feature_bridge import FeatureBridge

    bridge = FeatureBridge()
    detection_record = bridge.dict_to_detection(raw_detection)

    llm_svc = LLMService(
        model_name=os.getenv("LLM_ORCHESTRATOR_MODEL", "Meta-Llama-3.1-405B-Instruct"),
        fallback_model=os.getenv("LLM_ORCHESTRATOR_FALLBACK", "gpt-4o"),
    )
    enrichment_svc = EnrichmentService(
        llm_service=llm_svc,
        enable_llm_explanations=True,
    )
    enriched = enrichment_svc.enrich_detection(
        detection=detection_record,
        original_event=original_event,
    )

    if enriched is None:
        logger.warning("[reorch] Enrichment returned None for %s", anomaly_id)
        return

    # Update ai_enrichment JSONB on the existing row (not INSERT)
    persistence_svc = PersistenceService()
    try:
        ai_enrichment = enriched.get("ai_enrichment", {})
        persistence_svc.update_ai_enrichment(anomaly_id, ai_enrichment)
    finally:
        persistence_svc.close()

    # Step 2: LLM explanation
    conn = psycopg2.connect(**db_params)
    try:
        enrichment_svc.generate_llm_explanation(
            enriched_detection=enriched,
            conn=conn,
            detection_id=anomaly_id,
        )
        logger.info("[reorch] LLM explanation generated for %s", anomaly_id)
    except Exception as exc:
        logger.warning("[reorch] LLM explanation failed for %s: %s", anomaly_id, exc)
    finally:
        conn.close()

    # Step 3: Stage 1 validation (label_single)
    from modules.ai.auto_labeling.batch_labeler import BatchLabeler

    labeler = BatchLabeler()
    labeling_result = None
    try:
        labeling_result = labeler.label_single(anomaly_id)
        logger.info("[reorch] Stage 1 labeling done for %s: %s", anomaly_id, labeling_result)
    except Exception as exc:
        logger.warning("[reorch] Stage 1 labeling failed for %s: %s", anomaly_id, exc)

    # If false positive — add to training events for DFP feedback loop
    if labeling_result and labeling_result.get("false_positive", 0) > 0:
        try:
            from modules.ai.auto_labeling.dfp_feedback_service import DFPFeedbackService

            feedback_svc = DFPFeedbackService()
            feedback_svc.add_false_positive(
                {
                    "anomaly_id": anomaly_id,
                    "user_id": row["user_id"],
                    "original_event": original_event,
                    "anomaly_score": row.get("anomaly_score"),
                },
            )
            logger.info("[reorch] False positive added to training events for %s", anomaly_id)
        except Exception as exc:
            logger.warning("[reorch] Failed to add FP to training events for %s: %s", anomaly_id, exc)

    # Step 4: Stage 2 classification + risk score
    from modules.ai.root_cause.labeling_worker import classify_single

    try:
        classification = classify_single(anomaly_id)
        logger.info("[reorch] Stage 2 classification done for %s", anomaly_id)
    except Exception as exc:
        logger.warning("[reorch] Stage 2 classification failed for %s: %s", anomaly_id, exc)
        classification = None

    # Step 5: Agent dispatch via Kafka
    _anomaly_score = float(row.get("anomaly_score") or 0.0)
    if _anomaly_score > 5.0:
        severity = "CRITICAL"
    elif _anomaly_score >= 3.0:
        severity = "HIGH"
    elif _anomaly_score >= 2.5:
        severity = "MEDIUM"
    else:
        severity = "LOW"

    risk_score = 0.0
    conn = psycopg2.connect(**db_params)
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT risk_score FROM enriched_anomalies WHERE anomaly_id = %s",
                (anomaly_id,),
            )
            r = cur.fetchone()
            if r and r[0] is not None:
                risk_score = float(r[0])
    finally:
        conn.close()

    try:
        from confluent_kafka import Producer

        bootstrap = os.getenv("KAFKA_BOOTSTRAP_SERVERS", "127.0.0.1:29092")
        producer = Producer({"bootstrap.servers": bootstrap})
        payload = json.dumps(
            {
                "anomaly_id": anomaly_id,
                "severity": severity,
                "risk_score": risk_score,
                "root_cause": (classification or {}).get("root_cause", "Unknown"),
            }
        ).encode()
        producer.produce(
            topic="dfp-agent-tasks",
            key=anomaly_id.encode(),
            value=payload,
        )
        producer.flush(timeout=5)
        logger.info("[reorch] Agent task published for %s", anomaly_id)
    except Exception as exc:
        logger.warning("[reorch] Agent task publish failed for %s: %s", anomaly_id, exc)
