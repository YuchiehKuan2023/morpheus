#!/usr/bin/env python3
"""
Persistence Service: Multi-Database Storage for Enriched Anomalies

Manages persistent storage of enriched anomaly detections across multiple databases.
Ensures data consistency and graceful degradation when services are unavailable.

Architecture:
    - PostgreSQL: Source of truth for enriched detections (enriched_anomalies table)
    - Neo4j: Entity graph updates (relationships between entities and detections)
    - Qdrant: Vector storage for similarity search
    - Kafka: Event notifications for downstream consumers

Operations:
    - save_enriched_detection: Persist enriched detection to all databases
    - get_detection: Retrieve detection by ID
    - get_user_detections: Get all detections for a user
    - get_pending_validations: Get detections awaiting validation (is_anomaly IS NULL)
    - update_validation: Update Stage 1 validation (is_anomaly, confidence, reasoning)
    - update_classification: Update Stage 2 classification (root_cause, severity, etc.)

Usage:
    >>> persistence = PersistenceService()
    >>>
    >>> # Save enriched detection
    >>> result = persistence.save_enriched_detection({
    ...     "user_id": "user@example.com",
    ...     "timestamp": datetime.now(),
    ...     "anomaly_score": 15.2,
    ...     "original_event": {...},
    ...     "raw_detection": {...},
    ...     "ai_enrichment": {...}
    ... })
    >>> print(result["anomaly_id"])
    >>>
    >>> # Get pending validations
    >>> pending = persistence.get_pending_validations(limit=10)

Graceful Degradation:
    - PostgreSQL failure: Critical error (source of truth required)
    - Neo4j failure: Log warning, continue (graph updates optional)
    - Qdrant failure: Log warning, continue (search temporarily unavailable)
    - Kafka failure: Log warning, continue (notifications delayed)

Reference:
    docs/implementation/LABELING_FEEDBACK_ARCHITECTURE.md
    scripts/db/migrations/001_create_enriched_anomalies.sql

Author: AI Intelligence Layer Team
Date: 2026-02-19
"""

import json
import logging
import os
import sys
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

import psycopg2
from psycopg2.extensions import connection as Connection
from psycopg2.extras import RealDictCursor

# Add parent directory to path for imports
sys.path.append(str(Path(__file__).parent.parent.parent))

from modules.utils.db import get_db_params  # noqa: E402

try:
    from neo4j import GraphDatabase
    from neo4j.exceptions import Neo4jError

    NEO4J_AVAILABLE = True
except ImportError:
    NEO4J_AVAILABLE = False
    logging.warning("neo4j not installed. Install with: pip install neo4j")
    GraphDatabase = None  # type: ignore[misc,assignment]
    Neo4jError = Exception  # type: ignore[misc,assignment]

try:
    from qdrant_client import QdrantClient
    from qdrant_client.models import PointStruct

    QDRANT_AVAILABLE = True
except ImportError:
    QDRANT_AVAILABLE = False
    logging.warning("qdrant-client not installed. Install with: pip install qdrant-client")
    QdrantClient = None  # type: ignore[misc,assignment]
    PointStruct = None  # type: ignore[misc,assignment]

try:
    from kafka import KafkaProducer

    KAFKA_AVAILABLE = True
except ImportError:
    KAFKA_AVAILABLE = False
    logging.warning("kafka-python not installed. Install with: pip install kafka-python")
    KafkaProducer = None  # type: ignore[misc,assignment]

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


class PersistenceService:
    """
    Multi-database persistence service for enriched anomaly detections.

    Manages storage across PostgreSQL (source of truth), Neo4j (graph),
    Qdrant (vectors), and Kafka (events) with graceful degradation.
    """

    def __init__(
        self,
        postgres_config: dict[str, Any] | None = None,
        neo4j_config: dict[str, Any] | None = None,
        qdrant_config: dict[str, Any] | None = None,
        kafka_config: dict[str, Any] | None = None,
        enable_kafka: bool = True,
        batch_mode: bool = False,
    ):
        """
        Initialize persistence service with database connections.

        Args:
            postgres_config: PostgreSQL connection config (host, port, dbname, user, password)
            neo4j_config: Neo4j connection config (uri, user, password)
            qdrant_config: Qdrant connection config (host, port)
            kafka_config: Kafka connection config (bootstrap_servers, topic)
            enable_kafka: Whether to enable Kafka publishing (False for batch processing)
            batch_mode: If True, skip Neo4j/Qdrant writes (data pre-populated). If False, update graph/vectors (real-time mode)
        """
        # PostgreSQL (REQUIRED - source of truth)
        self.postgres_config = postgres_config or get_db_params()
        self.postgres_conn: Connection | None = None

        # Neo4j (OPTIONAL - graph enrichment)
        self.neo4j_config = neo4j_config or {
            "uri": os.getenv("NEO4J_URI", "bolt://localhost:7687"),
            "user": os.getenv("NEO4J_USER", "neo4j"),
            "password": os.getenv("NEO4J_PASSWORD", ""),
        }
        self.neo4j_driver = None

        # Qdrant (OPTIONAL - vector search)
        self.qdrant_config = qdrant_config or {
            "host": os.getenv("QDRANT_HOST", "localhost"),
            "port": int(os.getenv("QDRANT_PORT", "6333")),
        }
        self.qdrant_client = None

        # Kafka (OPTIONAL - event notifications)
        self.kafka_config = kafka_config or {
            "bootstrap_servers": os.getenv("KAFKA_BOOTSTRAP_SERVERS", "localhost:29092"),
            "topic": os.getenv("KAFKA_DETECTION_TOPIC", "dfp-detections"),
        }
        self.kafka_producer = None
        self.enable_kafka = enable_kafka
        self.batch_mode = batch_mode

        # Initialize connections
        self._connect()

    def _connect(self):
        """Establish connections to all databases"""
        # PostgreSQL (REQUIRED)
        try:
            self.postgres_conn = psycopg2.connect(**self.postgres_config)
            logger.info(f"Connected to PostgreSQL: {self.postgres_config['dbname']}@{self.postgres_config['host']}")
        except psycopg2.Error as e:
            logger.error(f"Failed to connect to PostgreSQL: {e}")
            raise RuntimeError("PostgreSQL connection required (source of truth)") from e

        # Neo4j (OPTIONAL)
        if NEO4J_AVAILABLE and GraphDatabase is not None:
            try:
                self.neo4j_driver = GraphDatabase.driver(
                    self.neo4j_config["uri"],
                    auth=(self.neo4j_config["user"], self.neo4j_config["password"]),
                )
                # Test connection
                with self.neo4j_driver.session() as session:
                    session.run("RETURN 1")
                logger.info(f"Connected to Neo4j: {self.neo4j_config['uri']}")
            except Exception as e:
                logger.warning(f"Neo4j connection failed: {e} (graph updates disabled)")
                self.neo4j_driver = None

        # Qdrant (OPTIONAL)
        if QDRANT_AVAILABLE and QdrantClient is not None:
            try:
                self.qdrant_client = QdrantClient(
                    host=self.qdrant_config["host"],
                    port=self.qdrant_config["port"],
                )
                # Test connection
                self.qdrant_client.get_collections()
                logger.info(f"Connected to Qdrant: {self.qdrant_config['host']}:{self.qdrant_config['port']}")
            except Exception as e:
                logger.warning(f"Qdrant connection failed: {e} (vector search disabled)")
                self.qdrant_client = None

        # Kafka (OPTIONAL)
        if self.enable_kafka and KAFKA_AVAILABLE and KafkaProducer is not None:
            try:
                self.kafka_producer = KafkaProducer(
                    bootstrap_servers=self.kafka_config["bootstrap_servers"],
                    value_serializer=lambda v: json.dumps(v).encode("utf-8"),
                )
                logger.info(f"Connected to Kafka: {self.kafka_config['bootstrap_servers']}")
            except Exception as e:
                logger.warning(f"Kafka connection failed: {e} (notifications disabled)")
                self.kafka_producer = None
        elif not self.enable_kafka:
            logger.info("Kafka publishing disabled (batch mode)")

    def close(self):
        """Close all database connections"""
        if self.postgres_conn:
            self.postgres_conn.close()
            logger.info("PostgreSQL connection closed")

        if self.neo4j_driver:
            self.neo4j_driver.close()
            logger.info("Neo4j connection closed")

        if self.kafka_producer:
            self.kafka_producer.close()
            logger.info("Kafka producer closed")

    def __enter__(self):
        """Context manager entry"""
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit"""
        self.close()

    def save_enriched_detection(self, enriched_detection: dict[str, Any]) -> dict[str, Any]:
        """
        Save enriched detection to all databases.

        Args:
            enriched_detection: Enriched detection data with fields:
                - user_id (str, required): User identifier
                - timestamp (datetime, required): Detection timestamp
                - anomaly_score (float, required): DFP anomaly score
                - mean_abs_z (float, optional): Mean absolute z-score
                - original_event (dict, required): Raw event data for retraining
                - raw_detection (dict, required): DFP scores and z-scores
                - ai_enrichment (dict, optional): AI-generated metadata
                    - entities (list): Extracted entities
                    - similar_detections (list): Similar past detections
                    - graph_context (dict): Neo4j graph insights

        Returns:
            dict: Result with anomaly_id and status
                {
                    "anomaly_id": "uuid-string",
                    "status": "success",
                    "postgres": "saved",
                    "neo4j": "saved" | "skipped",
                    "qdrant": "saved" | "skipped",
                    "kafka": "published" | "skipped"
                }

        Raises:
            RuntimeError: If PostgreSQL insert fails (critical error)
        """
        anomaly_id = str(uuid.uuid4())
        result = {
            "anomaly_id": anomaly_id,
            "status": "success",
            "postgres": "pending",
            "neo4j": "skipped",
            "qdrant": "skipped",
            "kafka": "skipped",
        }

        # 1. PostgreSQL (REQUIRED - source of truth)
        try:
            self._save_to_postgres(anomaly_id, enriched_detection)
            result["postgres"] = "saved"
            logger.info(f"Saved to PostgreSQL: {anomaly_id}")
        except Exception as e:
            logger.error(f"PostgreSQL insert failed: {e}")
            raise RuntimeError(f"Failed to save detection to PostgreSQL: {e}") from e

        # 2. Neo4j (OPTIONAL - graph enrichment)
        if self.neo4j_driver and enriched_detection.get("ai_enrichment", {}).get("entities") and not self.batch_mode:
            try:
                self._update_neo4j_graph(anomaly_id, enriched_detection)
                result["neo4j"] = "saved"
                logger.info(f"Updated Neo4j graph: {anomaly_id}")
            except Exception as e:
                logger.warning(f"Neo4j update failed: {e}")
        elif self.batch_mode:
            result["neo4j"] = "skipped (batch mode)"

        # 3. Qdrant (OPTIONAL - vector search)
        if self.qdrant_client and enriched_detection.get("ai_enrichment", {}).get("embedding") and not self.batch_mode:
            try:
                self._insert_to_qdrant(anomaly_id, enriched_detection)
                result["qdrant"] = "saved"
                logger.info(f"Inserted to Qdrant: {anomaly_id}")
            except Exception as e:
                logger.warning(f"Qdrant insert failed: {e}")
        elif self.batch_mode:
            result["qdrant"] = "skipped (batch mode)"

        # 4. Kafka (OPTIONAL - event notifications)
        if self.kafka_producer:
            try:
                self._publish_to_kafka(anomaly_id, enriched_detection)
                result["kafka"] = "published"
                logger.info(f"Published to Kafka: {anomaly_id}")
            except Exception as e:
                logger.warning(f"Kafka publish failed: {e}")

        return result

    def _save_to_postgres(self, anomaly_id: str, detection: dict[str, Any]):
        """Save detection to PostgreSQL enriched_anomalies table"""
        if not self.postgres_conn:
            raise RuntimeError("PostgreSQL connection not available")

        cursor = self.postgres_conn.cursor()
        try:
            # Prepare timestamp
            timestamp = detection["timestamp"]
            if isinstance(timestamp, str):
                timestamp = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))

            # Insert detection
            cursor.execute(
                """
                INSERT INTO enriched_anomalies (
                    anomaly_id, user_id, timestamp, anomaly_score, mean_abs_z,
                    original_event, raw_detection, ai_enrichment, simulated
                ) VALUES (
                    %s, %s, %s, %s, %s, %s, %s, %s, %s
                )
                """,
                (
                    anomaly_id,
                    detection["user_id"],
                    timestamp,
                    detection["anomaly_score"],
                    detection.get("mean_abs_z"),
                    json.dumps(detection["original_event"]),
                    json.dumps(detection["raw_detection"]),
                    json.dumps(detection.get("ai_enrichment")) if detection.get("ai_enrichment") else None,
                    bool(detection.get("original_event", {}).get("_simulation_session_id")),
                ),
            )

            self.postgres_conn.commit()
        except Exception:
            self.postgres_conn.rollback()
            raise
        finally:
            cursor.close()

    def _update_neo4j_graph(self, anomaly_id: str, detection: dict[str, Any]):
        """Update Neo4j graph with detection and entity relationships"""
        if not self.neo4j_driver:
            return

        entities = detection.get("ai_enrichment", {}).get("entities", [])
        if not entities:
            return

        with self.neo4j_driver.session() as session:
            # Create detection node
            session.run(
                """
                MERGE (d:Detection {id: $detection_id})
                SET d.user_id = $user_id,
                    d.timestamp = $timestamp,
                    d.anomaly_score = $anomaly_score
                """,
                detection_id=anomaly_id,
                user_id=detection["user_id"],
                timestamp=detection["timestamp"].isoformat()
                if isinstance(detection["timestamp"], datetime)
                else detection["timestamp"],
                anomaly_score=detection["anomaly_score"],
            )

            # Create relationships to entities
            for entity in entities:
                session.run(
                    """
                    MATCH (d:Detection {id: $detection_id})
                    MERGE (e:Entity {value: $entity_value, type: $entity_type})
                    MERGE (d)-[:INVOLVES]->(e)
                    """,
                    detection_id=anomaly_id,
                    entity_value=entity.get("value", entity.get("text")),
                    entity_type=entity.get("type", entity.get("label")),
                )

    def _insert_to_qdrant(self, anomaly_id: str, detection: dict[str, Any]):
        """Insert detection embedding to Qdrant.

        The point ID is set to ``anomaly_id`` (a UUID string).  Qdrant natively
        supports UUID string IDs, so no integer hashing is used.  Storing the
        UUID as BOTH the point ID and ``payload["detection_id"]`` means
        ``anomaly_validator._similarity_check()`` can retrieve labels with a
        simple ``WHERE anomaly_id = ANY(%s::uuid[])`` query without any
        remapping step.

        The payload mirrors the schema used by ``VectorStore.insert_detection``
        so similarity search results contain the same contextual fields
        regardless of which insertion path was used.
        """
        if not self.qdrant_client or PointStruct is None:
            return

        ai_enrichment = detection.get("ai_enrichment", {})
        embedding = ai_enrichment.get("embedding")
        if not embedding:
            return

        original_event = detection.get("original_event") or {}
        props = original_event.get("properties") or {}
        device_detail = props.get("deviceDetail") or {}
        loc = original_event.get("location") or {}

        # Payload mirrors VectorStore.insert_detection schema so similarity
        # search results are consistent across both insertion paths.
        payload = {
            "detection_id": anomaly_id,  # UUID — used for live label lookup
            "user_id": detection["user_id"],
            "timestamp": detection["timestamp"].isoformat()
            if isinstance(detection["timestamp"], datetime)
            else detection["timestamp"],
            "anomaly_score": detection.get("anomaly_score"),
            "severity": detection.get("severity"),
            "top_features": detection.get("top_features") or detection.get("top_features_raw") or [],
            "mean_abs_z": detection.get("mean_abs_z"),
            # Scalar fields extracted from original_event (aligned with VectorStore schema)
            "app": props.get("appDisplayName", ""),
            "device": device_detail.get("displayName", ""),
            "browser": device_detail.get("browser", ""),
            "os": device_detail.get("operatingSystem", ""),
            "ip_address": props.get("ipAddress", ""),
            "client_app": props.get("clientAppUsed", ""),
            "location": f"{loc.get('city', '')}, {loc.get('countryOrRegion', '')}",
        }

        # point ID = anomaly_id UUID string (not a hash)
        self.qdrant_client.upsert(
            collection_name="dfp_detections",
            points=[PointStruct(id=anomaly_id, vector=embedding, payload=payload)],
        )

    def _publish_to_kafka(self, anomaly_id: str, detection: dict[str, Any]):
        """Publish detection event to Kafka"""
        if not self.kafka_producer:
            return

        # Prepare event
        event = {
            "anomaly_id": anomaly_id,
            "user_id": detection["user_id"],
            "timestamp": detection["timestamp"].isoformat()
            if isinstance(detection["timestamp"], datetime)
            else detection["timestamp"],
            "anomaly_score": detection["anomaly_score"],
            "event_type": "detection_enriched",
        }

        # Publish
        self.kafka_producer.send(self.kafka_config["topic"], value=event)
        self.kafka_producer.flush()

    def get_detection(self, anomaly_id: str) -> dict[str, Any] | None:
        """
        Retrieve detection by ID.

        Args:
            anomaly_id: UUID of the detection

        Returns:
            dict: Detection data or None if not found
        """
        if not self.postgres_conn:
            raise RuntimeError("PostgreSQL connection not available")

        cursor = self.postgres_conn.cursor(cursor_factory=RealDictCursor)
        try:
            cursor.execute(
                """
                SELECT * FROM enriched_anomalies
                WHERE anomaly_id = %s
                """,
                (anomaly_id,),
            )
            result = cursor.fetchone()
            return dict(result) if result else None
        finally:
            cursor.close()

    def get_user_detections(self, user_id: str, limit: int = 100, offset: int = 0) -> list[dict[str, Any]]:
        """
        Get all detections for a user.

        Args:
            user_id: User identifier
            limit: Maximum number of results
            offset: Pagination offset

        Returns:
            list: List of detection records
        """
        if not self.postgres_conn:
            raise RuntimeError("PostgreSQL connection not available")

        cursor = self.postgres_conn.cursor(cursor_factory=RealDictCursor)
        try:
            cursor.execute(
                """
                SELECT * FROM enriched_anomalies
                WHERE user_id = %s
                ORDER BY timestamp DESC
                LIMIT %s OFFSET %s
                """,
                (user_id, limit, offset),
            )
            return [dict(row) for row in cursor.fetchall()]
        finally:
            cursor.close()

    def get_pending_validations(self, limit: int = 100) -> list[dict[str, Any]]:
        """
        Get detections awaiting Stage 1 validation (is_anomaly IS NULL).

        Args:
            limit: Maximum number of results

        Returns:
            list: List of pending detection records
        """
        if not self.postgres_conn:
            raise RuntimeError("PostgreSQL connection not available")

        cursor = self.postgres_conn.cursor(cursor_factory=RealDictCursor)
        try:
            cursor.execute(
                """
                SELECT * FROM enriched_anomalies
                WHERE is_anomaly IS NULL
                ORDER BY created_at DESC
                LIMIT %s
                """,
                (limit,),
            )
            return [dict(row) for row in cursor.fetchall()]
        finally:
            cursor.close()

    def update_validation(
        self,
        anomaly_id: str,
        is_anomaly: bool,
        confidence: float | None = None,
        reasoning: str | None = None,
        validated_by: str | None = None,
    ) -> bool:
        """
        Update Stage 1 validation (is_anomaly determination).

        Args:
            anomaly_id: UUID of the detection
            is_anomaly: True if real anomaly, False if false positive
            confidence: Validation confidence (0.0 - 1.0)
            reasoning: Explanation for validation decision
            validated_by: User or system that performed validation

        Returns:
            bool: True if update successful, False otherwise

        Note:
            The trigger_set_dfp_retrain_status trigger will automatically:
            - Set dfp_retrain_status='queued' if is_anomaly=False (false positive)
            - Set dfp_retrain_status='excluded' if is_anomaly=True (real anomaly)
        """
        if not self.postgres_conn:
            raise RuntimeError("PostgreSQL connection not available")

        cursor = self.postgres_conn.cursor()
        try:
            cursor.execute(
                """
                UPDATE enriched_anomalies
                SET is_anomaly = %s,
                    validation_confidence = %s,
                    validation_reasoning = %s,
                    validated_at = NOW(),
                    validated_by = %s
                WHERE anomaly_id = %s
                """,
                (is_anomaly, confidence, reasoning, validated_by, anomaly_id),
            )

            self.postgres_conn.commit()
            success = cursor.rowcount > 0

            if success:
                logger.info(f"Updated validation for {anomaly_id}: is_anomaly={is_anomaly}")
            else:
                logger.warning(f"Detection not found: {anomaly_id}")

            return success
        except Exception as e:
            self.postgres_conn.rollback()
            logger.error(f"Failed to update validation: {e}")
            return False
        finally:
            cursor.close()

    def update_classification(
        self,
        anomaly_id: str,
        root_cause: str,
        severity: str,
        sub_category: str | None = None,
        confidence: float | None = None,
        reasoning: str | None = None,
        risk_score: float | None = None,
        risk_factors: dict[str, Any] | None = None,
        classified_by: str | None = None,
    ) -> bool:
        """
        Update Stage 2 classification (root cause analysis).

        Args:
            anomaly_id: UUID of the detection
            root_cause: Root cause category
            severity: Severity level (CRITICAL, HIGH, MEDIUM, LOW)
            sub_category: Sub-category within root cause
            confidence: Classification confidence (0.0 - 1.0)
            reasoning: Explanation for classification
            risk_score: Risk score (0.0 - 100.0)
            risk_factors: Additional risk factors (JSONB)
            classified_by: Classifier identifier (e.g. 'distilbert', 'heuristic')

        Returns:
            bool: True if update successful, False otherwise

        Note:
            Only applicable for detections with is_anomaly=True
        """
        if not self.postgres_conn:
            raise RuntimeError("PostgreSQL connection not available")

        cursor = self.postgres_conn.cursor()
        try:
            cursor.execute(
                """
                UPDATE enriched_anomalies
                SET root_cause = %s,
                    severity = %s,
                    sub_category = %s,
                    classification_confidence = %s,
                    classification_reasoning = %s,
                    classified_at = NOW(),
                    classified_by = COALESCE(%s, classified_by),
                    risk_score = COALESCE(%s, risk_score),
                    risk_factors = COALESCE(%s, risk_factors)
                WHERE anomaly_id = %s
                """,
                (
                    root_cause,
                    severity,
                    sub_category,
                    confidence,
                    reasoning,
                    classified_by,
                    risk_score,
                    json.dumps(risk_factors) if risk_factors else None,
                    anomaly_id,
                ),
            )

            self.postgres_conn.commit()
            success = cursor.rowcount > 0

            if success:
                logger.info(f"Updated classification for {anomaly_id}: {root_cause} ({severity})")
            else:
                logger.warning(f"Detection not found: {anomaly_id}")

            return success
        except Exception as e:
            self.postgres_conn.rollback()
            logger.error(f"Failed to update classification: {e}")
            return False
        finally:
            cursor.close()

    def update_ai_enrichment(self, anomaly_id: str, ai_enrichment: dict[str, Any]) -> bool:
        """Update ai_enrichment JSONB on an existing anomaly row.

        Used by the re-orchestration service to overwrite heuristic enrichment
        with full AI-generated enrichment on existing anomalies.

        Args:
            anomaly_id: UUID of the detection
            ai_enrichment: New AI enrichment dict (entities, embedding, graph, etc.)

        Returns:
            bool: True if update successful, False otherwise
        """
        if not self.postgres_conn:
            raise RuntimeError("PostgreSQL connection not available")

        cursor = self.postgres_conn.cursor()
        try:
            cursor.execute(
                """UPDATE enriched_anomalies
                   SET ai_enrichment = %s, updated_at = NOW()
                   WHERE anomaly_id = %s""",
                (json.dumps(ai_enrichment, default=str), anomaly_id),
            )
            self.postgres_conn.commit()
            success = cursor.rowcount > 0
            if success:
                logger.info("Updated ai_enrichment for %s", anomaly_id)
            else:
                logger.warning("Detection not found for ai_enrichment update: %s", anomaly_id)
            return success
        except Exception as e:
            self.postgres_conn.rollback()
            logger.error("Failed to update ai_enrichment: %s", e)
            return False
        finally:
            cursor.close()


def main():
    """Test persistence service with sample data"""
    # Sample enriched detection
    sample_detection = {
        "user_id": "test_user@example.com",
        "timestamp": datetime.now(),
        "anomaly_score": 15.2,
        "mean_abs_z": 3.8,
        "original_event": {
            "action": "login",
            "ip": "192.168.1.100",
            "device": "Windows PC",
        },
        "raw_detection": {
            "z_scores": {"login_count": 4.2, "ip_entropy": 3.1},
            "mean_abs_z": 3.8,
        },
        "ai_enrichment": {
            "entities": [
                {"type": "IP", "value": "192.168.1.100"},
                {"type": "Device", "value": "Windows PC"},
            ],
            "similar_detections": ["det-123", "det-456"],
        },
    }

    # Test persistence
    with PersistenceService() as persistence:
        print("\n" + "=" * 70)
        print("Testing Persistence Service")
        print("=" * 70)

        # Save detection
        print("\n1. Saving enriched detection...")
        result = persistence.save_enriched_detection(sample_detection)
        print(f"   Result: {result}")

        # Retrieve detection
        print("\n2. Retrieving detection...")
        detection = persistence.get_detection(result["anomaly_id"])
        print(f"   Found: {detection is not None}")

        # Get user detections
        print("\n3. Getting user detections...")
        user_detections = persistence.get_user_detections(sample_detection["user_id"])
        print(f"   Count: {len(user_detections)}")

        # Get pending validations
        print("\n4. Getting pending validations...")
        pending = persistence.get_pending_validations(limit=5)
        print(f"   Count: {len(pending)}")

        # Update validation
        print("\n5. Updating validation (false positive)...")
        success = persistence.update_validation(
            result["anomaly_id"],
            is_anomaly=False,
            confidence=0.95,
            reasoning="User traveled to new location",
            validated_by="analyst@example.com",
        )
        print(f"   Success: {success}")

        print("\n" + "=" * 70)


if __name__ == "__main__":
    main()
