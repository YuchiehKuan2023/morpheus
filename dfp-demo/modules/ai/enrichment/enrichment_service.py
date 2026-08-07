#!/usr/bin/env python3
"""
Enrichment Service: AI-Powered Detection Enrichment Orchestrator

Orchestrates all AI modules to enrich DFP detections with intelligent context.
Integrates entity extraction, embeddings, similarity search, and graph queries
into a single enriched detection record ready for persistence and analysis.

Architecture:
    Input: DetectionRecord from feature_bridge (or CSV)
    Processing Pipeline:
        1. Entity Extraction (NER) → Extract apps, devices, IPs, locations
        2. Embedding Generation → Convert to 384-dim semantic vector
        3. Similarity Search → Find 5 most similar past detections
        4. Graph Context → Query Neo4j for entity relationships
    Output: EnrichedDetection with all AI metadata

Operations:
    - enrich_detection: Enrich single detection
    - enrich_batch: Enrich multiple detections efficiently
    - enrich_from_csv: Load and enrich detections from CSV file

Usage:
    >>> enrichment = EnrichmentService()
    >>>
    >>> # Enrich single detection
    >>> detection = DetectionRecord(...)
    >>> enriched = enrichment.enrich_detection(detection)
    >>> print(enriched["ai_enrichment"]["entities"])
    >>>
    >>> # Enrich from CSV and save to PostgreSQL
    >>> results = enrichment.enrich_from_csv(
    ...     "data/output/synthetic_detections.csv",
    ...     limit=100,
    ...     save_to_db=True
    ... )

Cold Start Handling:
    - Day 1 (0 detections in Qdrant): Returns empty similar_detections
    - Day 2+ (>10 detections): Returns top-5 similar detections
    - Graph queries: Returns empty if Neo4j unavailable
    - Embeddings: Returns None if model unavailable

Performance:
    - Single detection: ~100-150ms (NER=30ms, Embedding=15ms, Search=10ms, Graph=50ms)
    - Batch (100): ~50-80ms per detection (batching benefits)
    - Memory: ~500MB (SentenceTransformer model)

Reference:
    docs/implementation/PROGRESS_TRACKER.md (Week 5-6: Enrichment Service)
    modules/ai/ (entity_extraction, embeddings, shared)

Author: AI Intelligence Layer Team
Date: 2026-02-19
"""

import json
import logging
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

# Add parent directory to path for imports
sys.path.append(str(Path(__file__).parent.parent.parent))

from modules.ai.embeddings.embedding_service import EmbeddingService
from modules.ai.embeddings.similarity_search import SimilaritySearch
from modules.ai.enrichment.persistence_service import PersistenceService
from modules.ai.entity_extraction.ner_service import NERService
from modules.ai.shared.feature_bridge import DetectionRecord, FeatureBridge
from modules.ai.shared.monitoring import monitor_performance, record_detection_processed
from scripts.utils import severity_from_score

try:
    from neo4j import GraphDatabase

    NEO4J_AVAILABLE = True
except ImportError:
    NEO4J_AVAILABLE = False
    logging.warning("neo4j not installed. Install with: pip install neo4j")
    GraphDatabase = None  # type: ignore[misc,assignment]

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


class EnrichmentService:
    """
    Orchestrates AI modules to enrich DFP detections.

    Integrates NER, embeddings, similarity search, and graph queries
    into a unified enrichment pipeline.
    """

    def __init__(
        self,
        ner_service: NERService | None = None,
        embedding_service: EmbeddingService | None = None,
        similarity_search: SimilaritySearch | None = None,
        persistence_service: PersistenceService | None = None,
        llm_service: Any | None = None,  # Optional LLMService instance
        neo4j_uri: str | None = None,
        neo4j_user: str | None = None,
        neo4j_password: str | None = None,
        enable_llm_explanations: bool = False,  # Feature flag for LLM
    ):
        """
        Initialize enrichment service with AI modules.

        Args:
            ner_service: Optional NERService instance (creates new if None)
            embedding_service: Optional EmbeddingService instance (creates new if None)
            similarity_search: Optional SimilaritySearch instance (creates new if None)
            persistence_service: Optional PersistenceService instance (creates new if None)
            llm_service: Optional LLMService instance (for explanations)
            neo4j_uri: Neo4j connection URI
            neo4j_user: Neo4j username
            neo4j_password: Neo4j password
            enable_llm_explanations: Enable automatic LLM explanation generation
        """
        # Initialize AI modules
        self.ner_service = ner_service or NERService()
        self.embedding_service = embedding_service or EmbeddingService()
        self.similarity_search = similarity_search or SimilaritySearch(embedding_service=self.embedding_service)
        self.persistence_service = persistence_service  # Optional
        self.llm_service = llm_service  # Optional (for Phase 1 completion)
        self.enable_llm_explanations = enable_llm_explanations
        self.bridge = FeatureBridge()

        # Neo4j connection (optional)
        self.neo4j_driver = None
        if NEO4J_AVAILABLE and GraphDatabase is not None:
            try:
                # Use provided params or fall back to environment variables
                uri = neo4j_uri or os.getenv("NEO4J_URI", "bolt://localhost:7687")
                user = neo4j_user or os.getenv("NEO4J_USER", "neo4j")
                password = neo4j_password or os.getenv("NEO4J_PASSWORD", "")

                self.neo4j_driver = GraphDatabase.driver(
                    uri,
                    auth=(user, password),
                )
                # Test connection
                with self.neo4j_driver.session() as session:
                    session.run("RETURN 1")
                logger.info(f"Connected to Neo4j: {uri}")
            except Exception as e:
                logger.warning(f"Neo4j connection failed: {e} (graph queries disabled)")
                self.neo4j_driver = None

        logger.info("EnrichmentService initialized successfully")

    def close(self):
        """Close connections"""
        if self.neo4j_driver:
            self.neo4j_driver.close()
            logger.info("Neo4j connection closed")

        if self.persistence_service:
            self.persistence_service.close()
            logger.info("Persistence service closed")

    def __enter__(self):
        """Context manager entry"""
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit"""
        self.close()

    @monitor_performance("enrichment_service", "enrich_detection")
    def enrich_detection(
        self,
        detection: DetectionRecord,
        original_event: dict[str, Any],
        include_similar: bool = True,
        include_graph: bool = True,
        top_k_similar: int = 5,
    ) -> dict[str, Any]:
        """
        Enrich a single detection with AI-generated metadata.

        This matches the real-time inference flow:
            Original Event → DFP → Detection (score > 2.0) → Enrichment

        Args:
            detection: DetectionRecord from DFP inference
            original_event: The actual Azure AD SignInLog event that triggered detection
            include_similar: Include similarity search results (default: True)
            include_graph: Include graph context from Neo4j (default: True)
            top_k_similar: Number of similar detections to find (default: 5)

        Returns:
            dict: Enriched detection with structure:
                {
                    "user_id": str,
                    "timestamp": datetime,
                    "anomaly_score": float,
                    "mean_abs_z": float,
                    "original_event": dict,  # Azure AD event (NO DFP metadata)
                    "raw_detection": dict,   # DFP scores and features
                    "ai_enrichment": {
                        "entities": list[dict],  # Extracted entities
                        "embedding": list[float],  # 384-dim vector
                        "similar_detections": list[dict],  # Top-K similar
                        "graph_context": dict,  # Neo4j relationships
                        "enriched_at": str,  # ISO timestamp
                        "cold_start": bool  # True if no similar detections available
                    }
                }

        Raises:
            RuntimeError: If enrichment fails critically
        """
        try:
            # Initialize enriched detection
            # original_event is passed through unchanged (no DFP metadata added)
            enriched = {
                "user_id": detection.user_id,
                "timestamp": detection.timestamp,
                "anomaly_score": detection.anomaly_score,
                "mean_abs_z": detection.max_abs_z,
                "original_event": original_event,  # Azure AD event as-is
                "raw_detection": self._detection_to_raw(detection),
                "ai_enrichment": {
                    "entities": [],
                    "embedding": None,
                    "similar_detections": [],
                    "graph_context": {},
                    "enriched_at": datetime.now().isoformat(),
                    "cold_start": False,
                },
            }

            # 1. Entity Extraction (from original_event + detection)
            #    Uses BOTH data sources:
            #    - original_event: Business context (apps, devices, locations)
            #    - detection: Anomaly context (severity, scores)
            entities = []  # Initialize for use in embedding generation
            try:
                entities = self._extract_entities_from_event(original_event, detection)
                enriched["ai_enrichment"]["entities"] = entities
                record_detection_processed("entity_extraction", status="success")
                logger.debug(f"Extracted {len(entities)} entities from original_event: {[e['type'] for e in entities]}")
            except Exception as e:
                logger.warning(f"Entity extraction failed: {e}")
                record_detection_processed("entity_extraction", status="error")

            # 2. Embedding Generation (with entities for richer context)
            try:
                embedding = self.embedding_service.encode_detection(detection, entities=entities)
                if embedding is not None:
                    enriched["ai_enrichment"]["embedding"] = embedding.tolist()
                    record_detection_processed("embedding_generation", status="success")
                    logger.debug(f"Generated embedding with original_event context: {len(embedding)} dims")
                else:
                    logger.warning("Failed to generate embedding")
                    record_detection_processed("embedding_generation", status="error")
            except Exception as e:
                logger.warning(f"Embedding generation failed: {e}")
                record_detection_processed("embedding_generation", status="error")

            # 3. Similarity Search (if embedding available)
            if include_similar and enriched["ai_enrichment"]["embedding"]:
                try:
                    similar_results = self.similarity_search.get_similar_to_new(
                        detection, top_k=top_k_similar, min_similarity=0.5
                    )

                    if similar_results:
                        enriched["ai_enrichment"]["similar_detections"] = [
                            {
                                "detection_id": result.detection_id,
                                "user_id": result.user_id,
                                "timestamp": result.timestamp
                                if isinstance(result.timestamp, str)
                                else result.timestamp.isoformat(),
                                "similarity_score": result.similarity_score,
                                "anomaly_score": result.anomaly_score,
                            }
                            for result in similar_results
                        ]
                        record_detection_processed("similarity_search", status="success")
                        logger.debug(f"Found {len(similar_results)} similar detections")
                    else:
                        enriched["ai_enrichment"]["cold_start"] = True
                        logger.debug("Cold start: No similar detections available")
                        record_detection_processed("similarity_search", status="success")

                except Exception as e:
                    logger.warning(f"Similarity search failed: {e}")
                    record_detection_processed("similarity_search", status="error")

            # 4. User Baseline (load from training profiles)
            if include_graph:
                try:
                    user_baseline = self._load_user_baseline(detection.user_id)
                    enriched["ai_enrichment"]["user_baseline"] = user_baseline
                    record_detection_processed("baseline_load", status="success")
                    logger.debug(f"Loaded user baseline: {user_baseline.get('total_events', 0)} training events")
                except Exception as e:
                    logger.warning(f"User baseline load failed: {e}")
                    enriched["ai_enrichment"]["user_baseline"] = {"baseline_available": False}
                    record_detection_processed("baseline_load", status="error")

            # 5. Graph Context (if Neo4j available, regardless of baseline)
            if include_graph and self.neo4j_driver:
                try:
                    graph_context = self._get_graph_context(
                        detection.user_id,
                        enriched["ai_enrichment"]["entities"],
                        enriched["ai_enrichment"]["user_baseline"],
                    )
                    enriched["ai_enrichment"]["graph_context"] = graph_context
                    record_detection_processed("graph_query", status="success")
                    logger.debug(
                        f"Retrieved graph context with {len(graph_context.get('detection_relationships', []))} relationships"
                    )
                except Exception as e:
                    logger.warning(f"Graph query failed: {e}")
                    record_detection_processed("graph_query", status="error")

            logger.info(f"Enriched detection: {detection.user_id} @ {detection.timestamp}")
            return enriched

        except Exception as e:
            logger.error(f"Enrichment failed: {e}")
            raise RuntimeError(f"Failed to enrich detection: {e}") from e

    def generate_llm_explanation(
        self,
        enriched_detection: dict[str, Any],
        conn: Any,
        detection_id: str | None = None,
    ) -> dict[str, Any] | None:
        """
        Generate LLM explanation for enriched detection and optionally persist to database.

        This method:
        1. Calls llm_service.generate_explanation() with enriched detection
        2. Saves explanation to llm_explanations table using db_persistence
        3. Returns the generated explanation

        Args:
            enriched_detection: Complete enriched detection dict from enrich_detection()
            conn: Database connection (psycopg2 connection)
            detection_id: Optional detection UUID for database persistence

        Returns:
            Generated explanation dict, or None if LLM not enabled or failed

        Raises:
            Non-fatal: Logs errors but doesn't raise exceptions
        """
        if not self.enable_llm_explanations:
            logger.debug("LLM explanations disabled via feature flag")
            return None

        if not self.llm_service:
            logger.warning("LLM service not configured, skipping explanation generation")
            return None

        try:
            # Generate explanation using LLM service
            logger.info(f"Generating LLM explanation for {enriched_detection['raw_detection']['user_id']}")
            explanation = self.llm_service.generate_explanation(enriched_detection)

            # Persist to database if detection_id provided
            if detection_id and conn:
                from modules.ai.llm.db_persistence import save_llm_explanation

                save_llm_explanation(conn, detection_id, explanation, enriched_detection)
                logger.info(f"Saved LLM explanation to database (detection_id={detection_id})")

            return explanation

        except Exception as e:
            logger.error(f"LLM explanation generation failed (non-fatal): {e}")
            return None

    # NOTE: _detection_to_original_event() method removed
    # Original event is now passed as parameter to enrich_detection()
    # This matches real-time inference flow: Event → DFP → Detection → Enrichment

    def _detection_to_raw(self, detection: DetectionRecord) -> dict[str, Any]:
        """
        Convert DetectionRecord to raw_detection format.

        This must match EXACTLY the structure from user_aware_anomalies.csv:
        - user_id, timestamp, anomaly_score, max_abs_z, threshold, anomaly_source,
          event_count, feature_count, top_features
        """
        return {
            "user_id": detection.user_id,
            "timestamp": detection.timestamp,
            "anomaly_score": detection.anomaly_score,
            "max_abs_z": detection.max_abs_z,
            "threshold": detection.threshold,
            "anomaly_source": detection.anomaly_source,
            "event_count": detection.event_count,
            "feature_count": detection.feature_count,
            "top_features": detection.top_features_raw,
            "features": detection.features_list,
        }

    def _extract_entities_from_event(
        self, original_event: dict[str, Any], detection: DetectionRecord
    ) -> list[dict[str, Any]]:
        """
        Extract entities directly from original Azure AD event structure.

        This uses BOTH original_event (for business context) AND detection (for anomaly context):
        - original_event: WHO/WHAT/WHERE/WHEN (user, app, device, location, IP)
        - detection: HOW UNUSUAL (anomaly scores, z-scores)

        Args:
            original_event: Azure AD SignInLog event with properties, location, etc.
            detection: DFP detection with anomaly scores and z-scores

        Returns:
            List of entity dicts with type, text, confidence, category, source_feature
        """
        entities = []

        # Extract app (Application accessed)
        app_name = original_event.get("properties", {}).get("appDisplayName")
        if app_name:
            entities.append(
                {
                    "type": "APPLICATION",
                    "text": app_name,
                    "confidence": 1.0,
                    "category": "app",
                    "source_feature": "properties.appDisplayName",
                }
            )

        # Extract device (Device used)
        device_detail = original_event.get("properties", {}).get("deviceDetail", {})
        device_name = device_detail.get("displayName")
        if device_name:
            entities.append(
                {
                    "type": "DEVICE",
                    "text": device_name,
                    "confidence": 1.0,
                    "category": "device",
                    "source_feature": "properties.deviceDetail.displayName",
                }
            )

        # Extract browser
        browser = device_detail.get("browser")
        if browser:
            entities.append(
                {
                    "type": "BROWSER",
                    "text": browser,
                    "confidence": 1.0,
                    "category": "device",
                    "source_feature": "properties.deviceDetail.browser",
                }
            )

        # Extract operating system
        operating_system = device_detail.get("operatingSystem")
        if operating_system:
            entities.append(
                {
                    "type": "OS",
                    "text": operating_system,
                    "confidence": 1.0,
                    "category": "device",
                    "source_feature": "properties.deviceDetail.operatingSystem",
                }
            )

        # Extract location (City, Country)
        location = original_event.get("location", {})
        city = location.get("city")
        country = location.get("countryOrRegion")
        if city and country:
            location_text = f"{city}, {country}"
            entities.append(
                {
                    "type": "LOCATION",
                    "text": location_text,
                    "confidence": 1.0,
                    "category": "location",
                    "source_feature": "location.city+countryOrRegion",
                }
            )
        elif city:
            entities.append(
                {
                    "type": "LOCATION",
                    "text": city,
                    "confidence": 0.9,
                    "category": "location",
                    "source_feature": "location.city",
                }
            )
        elif country:
            entities.append(
                {
                    "type": "LOCATION",
                    "text": country,
                    "confidence": 0.8,
                    "category": "location",
                    "source_feature": "location.countryOrRegion",
                }
            )

        # Extract IP address
        ip_address = original_event.get("properties", {}).get("ipAddress")
        if ip_address:
            entities.append(
                {
                    "type": "IP_ADDRESS",
                    "text": ip_address,
                    "confidence": 1.0,
                    "category": "ip",
                    "source_feature": "properties.ipAddress",
                }
            )

        # Extract client app (authentication method)
        client_app = original_event.get("properties", {}).get("clientAppUsed")
        if client_app:
            entities.append(
                {
                    "type": "CLIENT_APP",
                    "text": client_app,
                    "confidence": 1.0,
                    "category": "network",
                    "source_feature": "properties.clientAppUsed",
                }
            )

        # Extract anomaly metadata from detection (statistical context)
        # Add anomaly severity as an entity for context
        severity = severity_from_score(detection.anomaly_score)

        entities.append(
            {
                "type": "ANOMALY_SEVERITY",
                "text": severity,
                "confidence": 1.0,
                "category": "anomaly",
                "source_feature": "detection.anomaly_score",
            }
        )

        logger.debug(f"Extracted {len(entities)} entities from original_event: {[e['type'] for e in entities]}")

        return entities

    def _entities_to_dict(self, detection_entities: Any) -> list[dict[str, Any]]:
        """Convert DetectionEntities to list of dicts"""
        entities = []

        # DetectionEntities has a single 'entities' list
        # Each Entity has: type, text, confidence, category
        for entity in detection_entities.entities:
            entities.append(
                {
                    "type": entity.type,
                    "text": entity.text,
                    "confidence": entity.confidence,
                    "category": entity.category,
                    "source_feature": entity.source_feature,
                }
            )

        return entities

    def _load_user_baseline(self, user_id: str) -> dict[str, Any]:
        """
        Load user's CLEAN behavioral baseline from training data.

        CRITICAL: This baseline comes from TRAINING data (normal behavior),
        NOT from Detection nodes (which contain anomalies).

        Returns structured baseline with nested {count, most_common, all} format
        for all entity types per MODULE_ALIGNMENT_ANALYSIS.md.

        Returns:
            dict with structure:
            {
                "username": "user@example.com",
                "total_events": 1629,
                "first_event": "2025-12-08T00:07:08Z",
                "last_event": "2026-02-15T17:39:49Z",
                "apps": {"count": 5, "most_common": [["Office365", 450]], "all": [...]},
                "devices": {...},
                "browsers": {...},
                "operating_systems": {...},
                "locations": {...},
                "ips": {...},
                "client_apps": {...},
                "baseline_strength": "strong|moderate|weak"
            }
        """
        try:
            from scripts.utils.shared.extract_user_profile import extract_user_profile

            # Build the profile live from the DB so it always reflects the most
            # recent seed + feedback events, including any new devices or locations
            # added via the false-positive loop.
            profile = extract_user_profile(user_id, source="db")

            # Total training events = baseline strength
            total_events = profile["total_events"]
            baseline_strength = "strong" if total_events > 1000 else "moderate" if total_events > 500 else "weak"

            # Build complete structured baseline per MODULE_ALIGNMENT_ANALYSIS.md
            user_baseline = {
                "username": user_id,
                "total_events": total_events,
                "first_event": profile.get("first_event"),
                "last_event": profile.get("last_event"),
                "apps": profile["apps"],
                "devices": profile["devices"],
                "browsers": profile["browsers"],
                "operating_systems": profile["operating_systems"],
                "locations": profile["locations"],
                "ips": profile["ips"],
                "client_apps": profile["client_apps"],
                "baseline_strength": baseline_strength,
                "baseline_source": "db",
                "activity_hours_utc": profile.get("activity_hours_utc"),
                "active_days_of_week": profile.get("active_days_of_week"),
            }

            logger.debug(
                f"Loaded baseline for {user_id}: {total_events} events, "
                f"{profile['apps']['count']} apps, {profile['devices']['count']} devices, "
                f"strength={baseline_strength}"
            )

            return user_baseline

        except Exception as e:
            logger.warning(f"Failed to load training baseline for {user_id}: {e}")
            return {"baseline_available": False}

    def _get_graph_context(
        self, user_id: str, entities: list[dict[str, Any]], user_baseline: dict[str, Any]
    ) -> dict[str, Any]:
        """
        Query Neo4j knowledge graph for detection patterns and relationships.

        IMPORTANT: This returns ONLY Neo4j graph data, NOT user_baseline data.
        user_baseline is stored separately and contains training profile data.

        Args:
            user_id: User identifier
            entities: Extracted entities from this detection
            user_baseline: User's behavioral baseline (used for comparison, not copied)

        Returns:
            dict with Neo4j graph context:
            {
                "detection_relationships": [
                    "(Detection)-[:ACCESSED]->(Application:HubSpot)",
                    "(Detection)-[:FROM_DEVICE]->(Device:LAPTOP-999)",
                    "(Detection)-[:USED_BROWSER]->(Browser:Chrome)",
                    "(Detection)-[:ON_OS]->(OperatingSystem:Linux)",
                    "(Detection)-[:FROM_LOCATION]->(Location:Tokyo)",
                    "(Detection)-[:FROM_IP]->(IPAddress:203.0.113.42)",
                    "(Detection)-[:VIA_CLIENT]->(ClientApp:Mobile App)",
                    ...
                ],
                "related_anomalies_count": 3,
                "recent_detections": 51,
                "detected_applications": ["HubSpot", "Jira", ...],           # From past detections
                "detected_devices": ["UNKNOWN-LAPTOP-999", ...],             # From past detections
                "detected_locations": ["Tokyo", "Dubai", ...],               # From past detections
                "detected_browsers": ["Chrome", "Firefox", ...],             # From past detections
                "detected_operating_systems": ["Linux", "Android", ...],     # From past detections
                "detected_ips": ["203.0.113.42", ...],                       # From past detections
                "detected_client_apps": ["Mobile App", "Legacy Client", ...] # From past detections
            }
        """
        graph_context = {}

        # Build detection relationship strings for THIS detection
        # These represent the relationships that will be created in Neo4j
        detection_relationships = []
        for entity in entities:
            entity_type = entity["type"]
            entity_text = entity["text"]

            if entity_type == "APPLICATION":
                detection_relationships.append(f"(Detection)-[:ACCESSED]->(Application:{entity_text})")
            elif entity_type == "DEVICE":
                detection_relationships.append(f"(Detection)-[:FROM_DEVICE]->(Device:{entity_text})")
            elif entity_type == "BROWSER":
                detection_relationships.append(f"(Detection)-[:USED_BROWSER]->(Browser:{entity_text})")
            elif entity_type == "OS":
                detection_relationships.append(f"(Detection)-[:ON_OS]->(OperatingSystem:{entity_text})")
            elif entity_type == "LOCATION":
                detection_relationships.append(f"(Detection)-[:FROM_LOCATION]->(Location:{entity_text})")
            elif entity_type == "IP_ADDRESS":
                detection_relationships.append(f"(Detection)-[:FROM_IP]->(IPAddress:{entity_text})")
            elif entity_type == "CLIENT_APP":
                detection_relationships.append(f"(Detection)-[:VIA_CLIENT]->(ClientApp:{entity_text})")

        graph_context["detection_relationships"] = detection_relationships

        # Query Neo4j for actual graph patterns from past detections
        related_anomalies_count = 0
        recent_detections_count = 0
        detected_applications = []
        detected_devices = []
        detected_locations = []
        detected_browsers = []
        detected_operating_systems = []
        detected_ips = []
        detected_client_apps = []

        if self.neo4j_driver:
            try:
                with self.neo4j_driver.session() as session:
                    # 1. Get recent anomaly count (last 7 days)
                    anomalies_result = session.run(
                        """
                        MATCH (u:User {user_id: $user_id})-[:GENERATED]->(d:Detection)
                        WHERE d.timestamp > datetime() - duration({days: 7})
                        RETURN count(*) as recent_anomalies
                        """,
                        user_id=user_id,
                    )
                    anomalies_record = anomalies_result.single()
                    related_anomalies_count = anomalies_record["recent_anomalies"] if anomalies_record else 0

                    # 2. Get total detection count for this user
                    total_result = session.run(
                        """
                        MATCH (u:User {user_id: $user_id})-[:GENERATED]->(d:Detection)
                        RETURN count(*) as total_detections
                        """,
                        user_id=user_id,
                    )
                    total_record = total_result.single()
                    recent_detections_count = total_record["total_detections"] if total_record else 0

                    # 3. Get applications from recent detections (not baseline)
                    apps_result = session.run(
                        """
                        MATCH (u:User {user_id: $user_id})-[:GENERATED]->(d:Detection)-[:ACCESSED]->(a:Application)
                        RETURN DISTINCT a.name as app_name
                        LIMIT 10
                        """,
                        user_id=user_id,
                    )
                    detected_applications = [record["app_name"] for record in apps_result if record["app_name"]]

                    # 4. Get devices from recent detections
                    devices_result = session.run(
                        """
                        MATCH (u:User {user_id: $user_id})-[:GENERATED]->(d:Detection)-[:FROM_DEVICE]->(dev:Device)
                        RETURN DISTINCT dev.name as device_name
                        LIMIT 5
                        """,
                        user_id=user_id,
                    )
                    detected_devices = [record["device_name"] for record in devices_result if record["device_name"]]

                    # 5. Get locations from recent detections
                    locations_result = session.run(
                        """
                        MATCH (u:User {user_id: $user_id})-[:GENERATED]->(d:Detection)-[:FROM_LOCATION]->(l:Location)
                        RETURN DISTINCT l.city as location_name
                        LIMIT 10
                        """,
                        user_id=user_id,
                    )
                    detected_locations = [
                        record["location_name"] for record in locations_result if record["location_name"]
                    ]

                    # 6. Get browsers from recent detections
                    browsers_result = session.run(
                        """
                        MATCH (u:User {user_id: $user_id})-[:GENERATED]->(d:Detection)-[:USED_BROWSER]->(b:Browser)
                        RETURN DISTINCT b.name as browser_name
                        LIMIT 5
                        """,
                        user_id=user_id,
                    )
                    detected_browsers = [record["browser_name"] for record in browsers_result if record["browser_name"]]

                    # 7. Get operating systems from recent detections
                    os_result = session.run(
                        """
                        MATCH (u:User {user_id: $user_id})-[:GENERATED]->(d:Detection)-[:ON_OS]->(os:OperatingSystem)
                        RETURN DISTINCT os.name as os_name
                        LIMIT 5
                        """,
                        user_id=user_id,
                    )
                    detected_operating_systems = [record["os_name"] for record in os_result if record["os_name"]]

                    # 8. Get IP addresses from recent detections
                    ips_result = session.run(
                        """
                        MATCH (u:User {user_id: $user_id})-[:GENERATED]->(d:Detection)-[:FROM_IP]->(ip:IPAddress)
                        RETURN DISTINCT ip.address as ip_address
                        LIMIT 10
                        """,
                        user_id=user_id,
                    )
                    detected_ips = [record["ip_address"] for record in ips_result if record["ip_address"]]

                    # 9. Get client apps from recent detections
                    client_apps_result = session.run(
                        """
                        MATCH (u:User {user_id: $user_id})-[:GENERATED]->(d:Detection)-[:VIA_CLIENT]->(ca:ClientApp)
                        RETURN DISTINCT ca.name as client_app_name
                        LIMIT 5
                        """,
                        user_id=user_id,
                    )
                    detected_client_apps = [
                        record["client_app_name"] for record in client_apps_result if record["client_app_name"]
                    ]

            except Exception as e:
                logger.warning("Neo4j graph context query failed for user %s: %s", user_id, e)

        # Populate graph context with Neo4j data (all 7 entity types)
        graph_context["related_anomalies_count"] = related_anomalies_count
        graph_context["recent_detections"] = recent_detections_count
        graph_context["detected_applications"] = detected_applications
        graph_context["detected_devices"] = detected_devices
        graph_context["detected_locations"] = detected_locations
        graph_context["detected_browsers"] = detected_browsers
        graph_context["detected_operating_systems"] = detected_operating_systems
        graph_context["detected_ips"] = detected_ips
        graph_context["detected_client_apps"] = detected_client_apps

        return graph_context

    @monitor_performance("enrichment_service", "enrich_batch")
    def enrich_batch(
        self,
        paired_records: list[tuple[dict[str, Any], DetectionRecord]],
        save_to_db: bool = False,
        batch_size: int = 100,
        include_similar: bool = True,
    ) -> list[dict[str, Any]]:
        """
        Enrich multiple paired (event, detection) records efficiently.

        Args:
            paired_records: List of (original_event, detection) tuples
            save_to_db: Save enriched detections to PostgreSQL (default: False)
            batch_size: Batch size for processing (default: 100)
            include_similar: Run similarity search (default: True). Set False when
                             Qdrant is not yet populated — similarity_search.py
                             --postgres will backfill similar_detections afterwards.

        Returns:
            list: List of enriched detection dicts

        Example:
            >>> paired = [(event1, detection1), (event2, detection2), ...]
            >>> enriched = enrichment.enrich_batch(paired, save_to_db=True)
            >>> print(f"Enriched {len(enriched)} detections")
        """
        enriched_detections = []
        failed_count = 0

        logger.info(f"Enriching {len(paired_records)} paired records (batch_size={batch_size})")

        for i, (original_event, detection) in enumerate(paired_records):
            try:
                enriched = self.enrich_detection(detection, original_event, include_similar=include_similar)
                enriched_detections.append(enriched)

                # Save to database if requested
                if save_to_db and self.persistence_service:
                    try:
                        self.persistence_service.save_enriched_detection(enriched)
                    except Exception as e:
                        logger.error(f"Failed to save detection to database: {e}")
                        failed_count += 1

                # Progress logging
                if (i + 1) % batch_size == 0:
                    logger.info(f"Progress: {i + 1}/{len(paired_records)} paired records enriched")

            except Exception as e:
                logger.error(f"Failed to enrich paired record {i}: {e}")
                failed_count += 1

        logger.info(f"Batch enrichment complete: {len(enriched_detections)} successful, {failed_count} failed")

        return enriched_detections

    def enrich_from_jsonl(
        self,
        jsonl_path: str,
        limit: int | None = None,
        save_to_db: bool = False,
        batch_size: int = 100,
        include_similar: bool = True,
    ) -> dict[str, Any]:
        """
        Load paired (event, detection) records from JSONL and enrich them.

        Expected format: {"original_event": {...}, "detection": {...}}

        Args:
            jsonl_path: Path to JSONL file (synthetic_paired_detections.jsonl format)
            limit: Optional limit on records to process (None = all)
            save_to_db: Save enriched detections to PostgreSQL (default: False)
            batch_size: Batch size for processing (default: 100)
            include_similar: Run similarity search (default: True). Set False when
                             Qdrant is not yet populated.

        Returns:
            dict: Results summary with counts and timing

        Example:
            >>> results = enrichment.enrich_from_jsonl(
            ...     "data/input/ai/synthetic_paired_detections.jsonl",
            ...     limit=100,
            ...     save_to_db=True
            ... )
            >>> print(f"Enriched {results['successful']} detections")
        """
        logger.info(f"Loading paired records from {jsonl_path}")

        try:
            # Load paired records
            paired_records = []
            with open(jsonl_path) as f:
                for i, line in enumerate(f):
                    if limit and i >= limit:
                        break

                    paired = json.loads(line)
                    original_event = paired["original_event"]
                    detection_dict = paired["detection"]

                    # Convert detection dict to DetectionRecord
                    detection = self.bridge.dict_to_detection(detection_dict)
                    paired_records.append((original_event, detection))

            logger.info(f"Loaded {len(paired_records)} paired records")

            # Enrich batch
            start_time = datetime.now()
            enriched = self.enrich_batch(
                paired_records, save_to_db=save_to_db, batch_size=batch_size, include_similar=include_similar
            )
            elapsed = (datetime.now() - start_time).total_seconds()

            # Results summary
            results = {
                "total_loaded": len(paired_records),
                "successful": len(enriched),
                "failed": len(paired_records) - len(enriched),
                "elapsed_seconds": elapsed,
                "avg_per_detection_ms": (elapsed / len(enriched) * 1000) if enriched else 0,
                "saved_to_db": save_to_db,
            }

            logger.info(f"Enrichment complete: {json.dumps(results, indent=2)}")
            return results

        except Exception as e:
            logger.error(f"Failed to enrich from JSONL: {e}")
            raise

    def get_enrichment_status(self) -> dict[str, Any]:
        """
        Get status of enrichment service and dependencies.

        Returns:
            dict: Status information for all services
        """
        status: dict[str, Any] = {
            "enrichment_service": "operational",
            "ner_service": "operational" if self.ner_service else "unavailable",
            "embedding_service": "operational" if self.embedding_service.model else "unavailable",
            "similarity_search": "operational" if self.similarity_search else "unavailable",
            "neo4j": "operational" if self.neo4j_driver else "unavailable",
            "persistence_service": "operational" if self.persistence_service else "unavailable",
        }

        # Check cold start status
        try:
            cold_start = self.similarity_search._is_cold_start()
            qdrant_info = self.similarity_search.vector_store.get_collection_info()
            status["cold_start"] = cold_start
            status["qdrant_detections"] = qdrant_info.get("points_count", 0)
        except Exception:
            status["cold_start"] = True
            status["qdrant_detections"] = 0

        return status


def main():
    """Test enrichment service with sample JSONL"""
    import argparse

    parser = argparse.ArgumentParser(description="Test EnrichmentService")
    parser.add_argument(
        "--jsonl",
        default="data/input/ai/synthetic_paired_detections.jsonl",
        help="Path to JSONL file with paired (event, detection) records",
    )
    parser.add_argument("--limit", type=int, default=10, help="Limit records to process")
    parser.add_argument("--save", action="store_true", help="Save enriched detections to database")
    parser.add_argument(
        "--no-similarity",
        action="store_true",
        help="Skip similarity search (use when Qdrant not yet populated; "
        "run similarity_search.py --postgres afterwards to backfill similar_detections)",
    )
    args = parser.parse_args()

    # Initialize services (batch mode: disable Kafka, skip Neo4j/Qdrant writes)
    persistence = PersistenceService(enable_kafka=False, batch_mode=True) if args.save else None

    with EnrichmentService(persistence_service=persistence) as enrichment:
        print("\n" + "=" * 70)
        print("Testing Enrichment Service (Real Inference Flow)")
        print("=" * 70)

        # Get status
        print("\n1. Checking service status...")
        status = enrichment.get_enrichment_status()
        print(f"   Status: {json.dumps(status, indent=2)}")

        # Enrich from JSONL
        include_similar = not args.no_similarity
        if not include_similar:
            print("   ℹ Similarity search disabled (--no-similarity). Run similarity_search.py --postgres afterwards.")
        print(f"\n2. Enriching paired records from JSONL (limit={args.limit})...")
        results = enrichment.enrich_from_jsonl(
            args.jsonl, limit=args.limit, save_to_db=args.save, batch_size=10, include_similar=include_similar
        )
        print(f"   Results: {json.dumps(results, indent=2)}")

        print("\n" + "=" * 70)


if __name__ == "__main__":
    main()
