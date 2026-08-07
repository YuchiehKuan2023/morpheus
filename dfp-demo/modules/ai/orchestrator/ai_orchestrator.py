"""
AI Orchestrator — real-time AI intelligence layer for the DFP pipeline.

Consumes two Kafka topics produced by the inference pipeline and runs the
full AI processing chain on each event, in a separate process so it never
blocks the inference loop.

Topic layout
------------
dfp-detections  → anomaly path: enrich → persist → Stage 1 validation → Stage 2 classification + risk score
dfp-clean-events → clean path: persist to user_training_events table (source='clean') for DFP baseline improvement

Usage
-----
    from modules.ai.orchestrator.ai_orchestrator import AIOrchestrator

    orchestrator = AIOrchestrator(
        enrichment_service=enrichment_svc,
        persistence_service=persistence_svc,
        batch_labeler=batch_labeler,          # provides label_single()
        labeling_worker_module=labeling_worker,  # provides classify_single()
        kafka_bootstrap="127.0.0.1:29092",
        anomaly_topic="dfp-detections",
        clean_topic="dfp-clean-events",
    )
    orchestrator.run()   # blocks; KeyboardInterrupt → graceful shutdown

Author: Tomasz Zabek <tzabek@deloitte.co.uk>
"""

from __future__ import annotations

import logging
import threading
from datetime import datetime, timezone
from typing import Any

from modules.ai.orchestrator.event_router import RoutedEvent
from modules.ai.shared.feature_bridge import FeatureBridge
from modules.io.kafka_consumer import DFPKafkaConsumer
from modules.io.kafka_producer import DFPKafkaProducer

logger = logging.getLogger(__name__)


class AIOrchestrator:
    """
    Dual-thread AI orchestrator.

    Thread A (anomaly): dfp-detections → enrich → persist → label → classify
    Thread B (clean):   dfp-clean-events → persist to user_training_events (source='clean')
    """

    def __init__(
        self,
        enrichment_service: Any,
        persistence_service: Any,
        batch_labeler: Any,
        labeling_worker_module: Any,
        kafka_bootstrap: str = "127.0.0.1:29092",
        anomaly_topic: str = "dfp-detections",
        clean_topic: str = "dfp-clean-events",
        agent_task_topic: str = "dfp-agent-tasks",
        anomaly_group_id: str = "ai-orchestrator-anomalies",
        clean_group_id: str = "ai-orchestrator-clean",
    ) -> None:
        """
        Args:
            enrichment_service:   Initialised EnrichmentService instance.
            persistence_service:  Initialised PersistenceService instance.
            batch_labeler:        Initialised BatchLabeler instance (must have label_single()).
            labeling_worker_module: The labeling_worker module (must have classify_single()).
            kafka_bootstrap:      Kafka broker address.
            anomaly_topic:        Topic carrying anomaly detection_records (dfp-detections).
            clean_topic:          Topic carrying raw clean events (dfp-clean-events).
            agent_task_topic:     Topic for multi-agent task dispatch (dfp-agent-tasks).
            anomaly_group_id:     Consumer group for anomaly topic.
            clean_group_id:       Consumer group for clean topic.
        """
        self.enrichment_service = enrichment_service
        self.persistence_service = persistence_service
        self.batch_labeler = batch_labeler
        self.labeling_worker = labeling_worker_module
        self.kafka_bootstrap = kafka_bootstrap
        self.anomaly_topic = anomaly_topic
        self.clean_topic = clean_topic
        self.anomaly_group_id = anomaly_group_id
        self.clean_group_id = clean_group_id

        self._bridge = FeatureBridge()
        self._stop_event = threading.Event()

        # Producer for multi-agent task dispatch (Phase D)
        self._agent_producer = DFPKafkaProducer(
            bootstrap_servers=kafka_bootstrap,
            topic=agent_task_topic,
        )

        # Counters (informational only — no locking needed for reads)
        self._anomaly_processed = 0
        self._anomaly_errors = 0
        self._clean_processed = 0
        self._clean_errors = 0

    # ---------------------------------------------------------------------- #
    # Public entry point                                                       #
    # ---------------------------------------------------------------------- #

    def run(self) -> None:
        """Start both consumer threads and block until KeyboardInterrupt."""
        logger.info("=" * 70)
        logger.info("AI ORCHESTRATOR starting")
        logger.info(f"  Anomaly topic : {self.anomaly_topic}  (group={self.anomaly_group_id})")
        logger.info(f"  Clean topic   : {self.clean_topic}  (group={self.clean_group_id})")
        logger.info("  Clean storage : user_training_events (source='clean')")
        logger.info("=" * 70)

        anomaly_thread = threading.Thread(
            target=self._consume_anomalies,
            name="orchestrator-anomalies",
            daemon=True,
        )
        clean_thread = threading.Thread(
            target=self._consume_clean_events,
            name="orchestrator-clean",
            daemon=True,
        )

        anomaly_thread.start()
        clean_thread.start()
        logger.info("Both consumer threads started. Press Ctrl+C to stop.")

        try:
            anomaly_thread.join()
            clean_thread.join()
        except KeyboardInterrupt:
            logger.info("\nKeyboardInterrupt received — shutting down gracefully...")
            self._stop_event.set()
            anomaly_thread.join(timeout=10)
            clean_thread.join(timeout=10)
        finally:
            self._agent_producer.close()

        logger.info("AI ORCHESTRATOR stopped.")
        logger.info(f"  Anomalies processed: {self._anomaly_processed}  errors: {self._anomaly_errors}")
        logger.info(f"  Clean events processed: {self._clean_processed}  errors: {self._clean_errors}")

    # ---------------------------------------------------------------------- #
    # Anomaly consumer thread                                                  #
    # ---------------------------------------------------------------------- #

    def _consume_anomalies(self) -> None:
        """
        Thread A: consume dfp-detections, run full AI pipeline per event.

        Steps:
          1. Deserialise → RoutedEvent
          2. enrich_detection (NER, embeddings, graph, LLM)
          3. save_enriched_detection (PostgreSQL + Neo4j + Qdrant)
          4. batch_labeler.label_single(anomaly_id)   — Stage 1 validation
          5. labeling_worker.classify_single(anomaly_id) — Stage 2 + risk score
        """
        consumer = DFPKafkaConsumer(
            bootstrap_servers=self.kafka_bootstrap,
            topic=self.anomaly_topic,
            group_id=self.anomaly_group_id,
            auto_offset_reset="latest",
        )
        logger.info(f"[anomaly-thread] Consuming from '{self.anomaly_topic}'")

        try:
            while not self._stop_event.is_set():
                messages = consumer.consume_batch(batch_size=10, timeout=1.0)
                for msg in messages:
                    try:
                        self._handle_anomaly(msg)
                        self._anomaly_processed += 1
                    except Exception as exc:
                        self._anomaly_errors += 1
                        user = msg.get("user_id", "?") if isinstance(msg, dict) else "?"
                        logger.error(
                            f"[anomaly-thread] Failed to process anomaly for user={user!r}: {exc}",
                            exc_info=True,
                        )
        finally:
            consumer.close()
            logger.info("[anomaly-thread] Consumer closed")

    def _handle_anomaly(self, msg: dict[str, Any]) -> None:
        """Process one anomaly message end-to-end."""
        event = RoutedEvent.from_anomaly_message(msg)
        logger.debug(f"[anomaly] Processing {event}")

        # Step 2: enrich
        detection_record = self._bridge.dict_to_detection(msg)
        enriched = self.enrichment_service.enrich_detection(
            detection=detection_record,
            original_event=event.original_event,
        )
        if enriched is None:
            logger.warning(f"[anomaly] Enrichment returned None for user={event.user_id!r} — skipping persist")
            return

        # Step 3: persist → returns dict with anomaly_id
        saved = self.persistence_service.save_enriched_detection(enriched)
        anomaly_id: str | None = None
        if isinstance(saved, dict):
            anomaly_id = saved.get("anomaly_id") or enriched.get("anomaly_id")

        if not anomaly_id:
            logger.warning(f"[anomaly] No anomaly_id after persist for user={event.user_id!r} — skipping labeling")
            return

        logger.info(f"[anomaly] Persisted anomaly_id={anomaly_id!r} for user={event.user_id!r}")

        # Signal the stage tracker as soon as the anomaly row exists in DB so
        # the tracker transitions 'sent' → 'detected' without waiting for
        # DETECTION_TIMEOUT.  The tracker then continues polling for LLM /
        # Stage 1 / Stage 2 completion as normal.
        session_id = event.original_event.get("_simulation_session_id")
        if session_id:
            try:
                with self.persistence_service.postgres_conn.cursor() as _cur:
                    _cur.execute(
                        """
                        UPDATE simulation_sessions
                        SET stage = 'detected',
                            anomaly_id = %s,
                            updated_at = NOW()
                        WHERE session_id = %s
                          AND stage NOT IN ('clean', 'failed', 'complete', 'detected',
                                            'enriched', 'classified', 'agent_running')
                        """,
                        (anomaly_id, session_id),
                    )
                self.persistence_service.postgres_conn.commit()
                logger.info("[anomaly] Signalled simulation_session %s → detected", session_id)
            except Exception as exc:
                logger.warning("[anomaly] Could not signal simulation_session %s: %s", session_id, exc)
                try:
                    self.persistence_service.postgres_conn.rollback()
                except Exception:
                    pass

        # Step 3b: LLM explanation (descriptive narrative) — must run BEFORE label_single
        # so the anomaly validator can read it from llm_explanations as input context.
        # Uses the persistence service's live PostgreSQL connection (single-threaded consumer).
        try:
            self.enrichment_service.generate_llm_explanation(
                enriched_detection=enriched,
                conn=self.persistence_service.postgres_conn,
                detection_id=anomaly_id,
            )
            logger.debug(f"[anomaly] LLM explanation generated for {anomaly_id!r}")
        except Exception as exc:
            logger.warning(f"[anomaly] LLM explanation failed for {anomaly_id!r}: {exc}")

        # Step 4: Stage 1 validation (label_single added in todo Step 6)
        labeling_result: dict | None = None
        if hasattr(self.batch_labeler, "label_single"):
            try:
                labeling_result = self.batch_labeler.label_single(anomaly_id)
                logger.debug(f"[anomaly] Stage 1 labeling done for {anomaly_id!r}: {labeling_result}")
            except Exception as exc:
                logger.warning(f"[anomaly] Stage 1 labeling failed for {anomaly_id!r}: {exc}")

        # Step 5: Stage 2 classification + risk score — runs for ALL above-threshold
        # detections regardless of Stage 1 verdict.  The Stage 1 verdict is informational;
        # human analysts need the full picture (root cause, risk score, SHAP) even for
        # events labelled as false positive or uncertain.
        classification: dict | None = None
        if hasattr(self.labeling_worker, "classify_single"):
            try:
                classification = self.labeling_worker.classify_single(anomaly_id)
                logger.debug(f"[anomaly] Stage 2 classification done for {anomaly_id!r}")
            except Exception as exc:
                logger.warning(f"[anomaly] Stage 2 classification failed for {anomaly_id!r}: {exc}")

        # Step 6: Multi-Agent dispatch (Phase D)
        # severity is derived from anomaly_score (same thresholds as anomaly_score_to_severity).
        # risk_score is written to DB by classify_single — not present in `enriched` — so we
        # fetch it back; fall back to 0.0 if classification was skipped or risk model absent.
        # root_cause comes from the classify_single return value.
        _anomaly_score = float(enriched.get("anomaly_score") or 0.0)

        if _anomaly_score > 5.0:
            severity = "CRITICAL"
        elif _anomaly_score >= 3.0:
            severity = "HIGH"
        elif _anomaly_score >= 2.5:
            severity = "MEDIUM"
        else:
            severity = "LOW"

        risk_score = 0.0

        try:
            with self.persistence_service.postgres_conn.cursor() as _cur:
                _cur.execute(
                    "SELECT risk_score FROM enriched_anomalies WHERE anomaly_id = %s",
                    (anomaly_id,),
                )
                _row = _cur.fetchone()
                if _row and _row[0] is not None:
                    risk_score = float(_row[0])
        except Exception as _exc:
            logger.debug("[anomaly] Could not fetch risk_score for %s: %s", anomaly_id, _exc)

        # Dispatch gate: ALL severities dispatch to the agent orchestrator.
        # Every above-threshold anomaly warrants a full investigation — a low
        # score for one user is not the same as a low score for another.
        # (Mirrors AgentOrchestrator._decide_agents policy.)

        try:
            self._agent_producer.produce(
                value={
                    "anomaly_id": anomaly_id,
                    "severity": severity,
                    "risk_score": risk_score,
                    "root_cause": (classification or {}).get("root_cause", "Unknown"),
                },
                key=anomaly_id,
            )
            logger.info(
                "[anomaly] Agent task published: anomaly_id=%s severity=%s risk_score=%.1f",
                anomaly_id,
                severity,
                risk_score,
            )
        except Exception as exc:
            logger.warning("[anomaly] Agent task publish failed for %s: %s", anomaly_id, exc)
            return

        # Mark the anomaly as fully processed only after confirmed agent dispatch.
        # If the publish above failed we intentionally leave processed=FALSE so the
        # anomaly remains eligible for re-orchestration from the UI.
        try:
            with self.persistence_service.postgres_conn.cursor() as _cur:
                _cur.execute(
                    "UPDATE enriched_anomalies SET processed = TRUE WHERE anomaly_id = %s",
                    (anomaly_id,),
                )
            self.persistence_service.postgres_conn.commit()
        except Exception as _exc:
            logger.warning("[anomaly] Could not mark processed for %s: %s", anomaly_id, _exc)
            try:
                self.persistence_service.postgres_conn.rollback()
            except Exception:
                pass

    # ---------------------------------------------------------------------- #
    # Clean-event consumer thread                                              #
    # ---------------------------------------------------------------------- #

    def _consume_clean_events(self) -> None:
        """
        Thread B: consume dfp-clean-events, persist to user_training_events.

        Lightweight path — no enrichment.  Each event is inserted into
        user_training_events (source='clean') so it can strengthen the user's
        autoencoder baseline on the next DFP retrain.  A dedicated postgres
        connection is opened for this thread to avoid shared-state issues with
        the anomaly thread's PersistenceService connection.
        """
        consumer = DFPKafkaConsumer(
            bootstrap_servers=self.kafka_bootstrap,
            topic=self.clean_topic,
            group_id=self.clean_group_id,
            auto_offset_reset="latest",
        )
        logger.info(f"[clean-thread] Consuming from '{self.clean_topic}'")

        import psycopg2

        db_config = self.persistence_service.postgres_config
        clean_conn = psycopg2.connect(**db_config)
        logger.info("[clean-thread] Dedicated postgres connection opened")

        try:
            while not self._stop_event.is_set():
                messages = consumer.consume_batch(batch_size=50, timeout=1.0)
                for msg in messages:
                    try:
                        self._handle_clean_event(msg, clean_conn)
                        self._clean_processed += 1
                    except Exception as exc:
                        self._clean_errors += 1
                        try:
                            clean_conn.rollback()
                        except Exception:
                            pass
                        user = (
                            (msg.get("identity") or msg.get("username") or msg.get("user_id", "?"))
                            if isinstance(msg, dict)
                            else "?"
                        )
                        logger.error(
                            f"[clean-thread] Failed to process clean event for user={user!r}: {exc}",
                            exc_info=True,
                        )
        finally:
            consumer.close()
            logger.info("[clean-thread] Consumer closed")
            try:
                clean_conn.close()
            except Exception:
                pass
            logger.info("[clean-thread] Postgres connection closed")

    def _handle_clean_event(self, msg: dict[str, Any], db_conn) -> None:
        """Persist one clean event to the user_training_events table (source='clean')."""
        import psycopg2.extras

        # Strip Kafka consumer metadata injected by consume_batch() so we store
        # only the original Azure AD event payload in the JSONB column.
        _KAFKA_META = {"_kafka_offset", "_kafka_partition", "_kafka_timestamp"}
        clean_msg = {k: v for k, v in msg.items() if k not in _KAFKA_META}

        event = RoutedEvent.from_clean_message(clean_msg)
        logger.debug(f"[clean] Persisting training record for user={event.user_id!r}")

        # DFP score injected by the inference pipeline (mean_abs_z, below threshold).
        # None when the field is absent (e.g. events pre-dating this change).
        dfp_score: float | None = None
        raw_score = event.original_event.get("_dfp_score")
        if raw_score is not None:
            try:
                dfp_score = float(raw_score)
            except (TypeError, ValueError):
                pass

        # Extract event_time from the raw message; fall back to now.
        event_time_str = event.original_event.get("time") or event.original_event.get("createdDateTime")
        try:
            if event_time_str:
                if isinstance(event_time_str, datetime):
                    event_time = (
                        event_time_str
                        if event_time_str.tzinfo is not None
                        else event_time_str.replace(tzinfo=timezone.utc)
                    )
                else:
                    event_time = datetime.fromisoformat(str(event_time_str).replace("Z", "+00:00"))
            else:
                event_time = datetime.now(timezone.utc)
        except (ValueError, AttributeError, TypeError):
            event_time = datetime.now(timezone.utc)

        with db_conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO user_training_events (user_id, event_time, event, source, anomaly_score)
                VALUES (%s, %s, %s, 'clean', %s)
                """,
                (event.user_id, event_time, psycopg2.extras.Json(event.original_event), dfp_score),
            )
        db_conn.commit()
        logger.debug(
            "[clean] Persisted user_training_events for user=%r at %s (score=%s)",
            event.user_id,
            event_time.isoformat(),
            f"{dfp_score:.4f}" if dfp_score is not None else "n/a",
        )

        # Signal the stage tracker immediately so it doesn't have to wait for
        # DETECTION_TIMEOUT to expire before marking the session clean.
        # _simulation_session_id is injected by SimulationScheduler into the
        # original event before publishing to dfp-events; the inference pipeline
        # forwards it verbatim on dfp-clean-events.
        session_id = event.original_event.get("_simulation_session_id")
        if session_id:
            try:
                with db_conn.cursor() as cur:
                    cur.execute(
                        """
                        UPDATE simulation_sessions
                        SET stage = 'clean',
                            anomaly_score = %s,
                            updated_at = NOW(),
                            completed_at = NOW()
                        WHERE session_id = %s
                          AND stage NOT IN ('clean', 'failed', 'complete')
                        """,
                        (dfp_score, session_id),
                    )
                db_conn.commit()
                logger.info(
                    "[clean] Marked simulation_session %s as clean (score=%s)",
                    session_id,
                    f"{dfp_score:.4f}" if dfp_score is not None else "n/a",
                )
            except Exception as exc:
                logger.warning("[clean] Could not update simulation_session %s: %s", session_id, exc)
                try:
                    db_conn.rollback()
                except Exception:
                    pass
