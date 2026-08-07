#!/usr/bin/env python3
"""
Similarity Search: High-Level API for Detection Similarity

Provides high-level API for finding similar detections using semantic embeddings.
Integrates embedding_service and vector_store for end-to-end similarity search.

Architecture:
    - Input: detection_id or DetectionRecord
    - Process: Generate embedding → Search Qdrant → Return similar detections
    - Cold Start: Returns empty if collection has <10 detections

Operations:
    - get_similar_detections: Find similar by detection_id
    - get_similar_to_new: Find similar to new detection
    - get_collection_stats: Get collection size and status
    - populate_from_csv: Bulk load detections from CSV

Usage:
    >>> similarity = SimilaritySearch()
    >>>
    >>> # Find similar by ID
    >>> results = similarity.get_similar_detections("detection_123", top_k=5)
    >>> for result in results:
    ...     print(result.user_id, result.score)
    >>>
    >>> # Find similar to new detection
    >>> results = similarity.get_similar_to_new(new_detection, top_k=5)
    >>>
    >>> # Populate from CSV
    >>> success, failed = similarity.populate_from_csv("data/input/ai/user_aware_anomalies.csv")

Cold Start:
    - Requires 10+ detections for meaningful results
    - Returns empty list if collection too small
    - Automatically handles empty collection gracefully

Performance:
    - Search latency: 10-50ms (depending on collection size)
    - Batch population: ~5-10ms per detection
    - Cache hit: <1ms (via embedding_service cache)

Reference:
    docs/implementation/PROGRESS_TRACKER.md (Week 4 - Vector Search)

Author: AI Intelligence Layer Team
Date: 2026-02-18
"""

import json
import logging
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

# Add parent directory to path for imports
sys.path.append(str(Path(__file__).parent.parent.parent))

from modules.ai.embeddings.embedding_service import EmbeddingService
from modules.ai.embeddings.vector_store import SearchResult, VectorStore
from modules.ai.shared.feature_bridge import DetectionRecord, FeatureBridge
from scripts.utils import severity_from_score

try:
    from modules.ai.shared.monitoring import monitor_performance

    MONITORING_AVAILABLE = True
except ImportError:
    # Fallback decorator if monitoring not available
    MONITORING_AVAILABLE = False

    def monitor_performance(component: str, operation: str | None = None):
        """Fallback decorator that does nothing."""

        def decorator(func):
            return func

        return decorator


logger = logging.getLogger(__name__)

# Cold start threshold: Minimum detections for meaningful similarity
COLD_START_THRESHOLD = 10


@dataclass
class SimilarityResult:
    """
    Enriched similarity search result.

    Combines SearchResult from vector_store with additional context.

    Attributes:
        detection_id: Unique detection identifier
        user_id: User who triggered detection
        timestamp: Detection timestamp
        similarity_score: Cosine similarity (0-1, higher = more similar)
        severity: Detection severity (CRITICAL, HIGH, MEDIUM, LOW)
        anomaly_score: DFP anomaly score
        app: Application name (e.g. "Confluence")
        device: Device display name
        browser: Browser name/version
        os: Operating system
        ip_address: Source IP address
        client_app: Client application (e.g. "IMAP4")
        location: City, Country string
        explanation: Why this detection is similar (generated on-demand)
    """

    detection_id: str
    user_id: str
    timestamp: datetime
    similarity_score: float
    severity: str
    anomaly_score: float
    app: str = ""
    device: str = ""
    browser: str = ""
    os: str = ""
    ip_address: str = ""
    client_app: str = ""
    location: str = ""
    explanation: str = ""

    @classmethod
    def from_search_result(cls, result: SearchResult) -> "SimilarityResult":
        """Convert SearchResult to SimilarityResult."""
        return cls(
            detection_id=result.detection_id,
            user_id=result.user_id,
            timestamp=result.timestamp,
            similarity_score=result.score,
            severity=result.metadata.get("severity", "UNKNOWN"),
            anomaly_score=result.metadata.get("anomaly_score", 0.0),
            app=result.metadata.get("app", ""),
            device=result.metadata.get("device", ""),
            browser=result.metadata.get("browser", ""),
            os=result.metadata.get("os", ""),
            ip_address=result.metadata.get("ip_address", ""),
            client_app=result.metadata.get("client_app", ""),
            location=result.metadata.get("location", ""),
        )


class SimilaritySearch:
    """
    High-level API for semantic similarity search.

    Integrates embedding generation and vector search for finding similar detections.
    Handles cold start, caching, and error recovery.

    Attributes:
        embedding_service: EmbeddingService instance for generating embeddings
        vector_store: VectorStore instance for Qdrant operations
        bridge: FeatureBridge instance for loading detections
        cold_start_threshold: Minimum detections required (default: 10)
    """

    def __init__(
        self,
        embedding_service: EmbeddingService | None = None,
        vector_store: VectorStore | None = None,
        cold_start_threshold: int = COLD_START_THRESHOLD,
    ):
        """
        Initialize SimilaritySearch with services.

        Args:
            embedding_service: Optional EmbeddingService instance (creates new if None)
            vector_store: Optional VectorStore instance (creates new if None)
            cold_start_threshold: Minimum detections for meaningful results

        Raises:
            RuntimeError: If services cannot be initialized
        """
        self.cold_start_threshold = cold_start_threshold

        try:
            self.embedding_service = embedding_service or EmbeddingService()
            self.vector_store = vector_store or VectorStore()
            self.bridge = FeatureBridge()

            logger.info("SimilaritySearch initialized successfully")

        except Exception as e:
            logger.error(f"Failed to initialize SimilaritySearch: {e}")
            raise RuntimeError(
                "Cannot initialize SimilaritySearch. Make sure Qdrant is running (check services/check_services.sh)"
            ) from e

    def _normalize_timestamp(self, timestamp: datetime | str) -> str:
        """
        Normalize timestamp to consistent string format.

        Args:
            timestamp: datetime object or ISO string

        Returns:
            Normalized timestamp string (no timezone suffix)
        """
        # Convert to ISO string
        if isinstance(timestamp, datetime):
            timestamp_str = timestamp.isoformat()
        else:
            timestamp_str = str(timestamp)

        # Remove timezone suffixes for consistency
        timestamp_str = timestamp_str.replace("+00:00", "").replace("Z", "")

        return timestamp_str

    def _is_cold_start(self) -> bool:
        """
        Check if collection is in cold start (too few detections).

        Returns:
            True if collection has fewer than cold_start_threshold detections
        """
        try:
            info = self.vector_store.get_collection_info()
            points_count = info.get("points_count", 0)

            if points_count < self.cold_start_threshold:
                logger.info(f"Cold start: {points_count} detections (need {self.cold_start_threshold})")
                return True

            return False

        except Exception as e:
            logger.error(f"Failed to check cold start status: {e}")
            return True  # Assume cold start on error

    @monitor_performance("similarity_search", "get_similar")
    def get_similar_detections(
        self,
        detection_id: str,
        top_k: int = 5,
        min_similarity: float = 0.5,
        user_filter: str | None = None,
    ) -> list[SimilarityResult]:
        """
        Find detections similar to a given detection_id.

        Args:
            detection_id: ID of detection to find similar to
            top_k: Number of results to return (default: 5)
            min_similarity: Minimum similarity score 0-1 (default: 0.5)
            user_filter: Optional user_id to filter results

        Returns:
            List of SimilarityResult objects (sorted by similarity descending)
            Empty list if cold start or detection not found

        Example:
            >>> results = similarity.get_similar_detections("d123", top_k=5)
            >>> for result in results:
            ...     print(f"{result.user_id}: {result.similarity_score:.3f}")
        """
        # Check cold start
        if self._is_cold_start():
            logger.info("Cold start - returning empty results")
            return []

        try:
            # Search by detection_id (this would require storing detection embeddings)
            # For now, this is a placeholder - in production, you'd either:
            # 1. Store detection_id → embedding mapping in Redis
            # 2. Re-generate embedding from stored detection data
            # 3. Use Qdrant's scroll + filter to find by ID

            # Placeholder: Return empty for now
            logger.warning(
                "get_similar_detections by ID not fully implemented yet. "
                "Use get_similar_to_new() with DetectionRecord instead."
            )
            return []

        except Exception as e:
            logger.error(f"Failed to get similar detections: {e}")
            return []

    @monitor_performance("similarity_search", "get_similar_new")
    def get_similar_to_new(
        self,
        detection: DetectionRecord,
        top_k: int = 5,
        min_similarity: float = 0.5,
        user_filter: str | None = None,
        exclude_self: bool = True,
    ) -> list[SimilarityResult]:
        """
        Find detections similar to a new detection.

        Args:
            detection: DetectionRecord to find similar to
            top_k: Number of results to return (default: 5)
            min_similarity: Minimum similarity score 0-1 (default: 0.5)
            user_filter: Optional user_id to filter results
            exclude_self: Exclude detection itself from results (default: True)

        Returns:
            List of SimilarityResult objects (sorted by similarity descending)
            Empty list if cold start or encoding fails

        Example:
            >>> results = similarity.get_similar_to_new(new_detection, top_k=5)
            >>> for result in results:
            ...     print(f"{result.user_id}: {result.similarity_score:.3f}")
        """
        # Check cold start
        if self._is_cold_start():
            logger.info("Cold start - returning empty results")
            return []

        try:
            # Generate embedding for detection
            embedding = self.embedding_service.encode_detection(detection)

            if embedding is None:
                logger.error("Failed to generate embedding for detection")
                return []

            # Search for similar detections
            # Request top_k + 1 to account for potential self-match
            search_limit = top_k + 1 if exclude_self else top_k

            search_results = self.vector_store.search_similar(
                embedding=embedding,
                top_k=search_limit,
                min_score=min_similarity,
                user_filter=user_filter,
            )

            # Convert to SimilarityResult
            results = []
            # Normalize timestamp for consistent detection_id comparison
            timestamp_normalized = self._normalize_timestamp(detection.timestamp)
            detection_id = f"{detection.user_id}_{timestamp_normalized}"

            for result in search_results:
                # Skip self if requested
                if exclude_self and result.detection_id == detection_id:
                    continue

                similarity_result = SimilarityResult.from_search_result(result)
                results.append(similarity_result)

                # Stop if we have enough results
                if len(results) >= top_k:
                    break

            logger.info(f"Found {len(results)} similar detections (min_similarity={min_similarity})")

            return results

        except Exception as e:
            logger.error(f"Failed to get similar detections: {e}")
            return []

    @monitor_performance("similarity_search", "populate")
    def populate_from_csv(
        self,
        csv_path: str,
        limit: int | None = None,
        batch_size: int = 100,
        skip_existing: bool = False,
    ) -> tuple[int, int]:
        """
        Populate vector store from CSV file.

        Args:
            csv_path: Path to CSV file (synthetic_paired_detections.csv format)
            limit: Optional limit on detections to load (None = all)
            batch_size: Batch size for insertion (default: 100)
            skip_existing: Skip detections already in store (not implemented)

        Returns:
            Tuple of (successful_count, failed_count)

        Example:
            >>> success, failed = similarity.populate_from_csv(
            ...     "data/input/ai/synthetic_paired_detections.csv",
            ...     limit=1000
            ... )
            >>> print(f"Inserted {success}/{success+failed} detections")
        """
        try:
            # Load detections from CSV
            logger.info(f"Loading detections from {csv_path}")
            detections = self.bridge.load_detections(csv_path, limit=limit)

            if not detections:
                logger.warning("No detections loaded from CSV")
                return 0, 0

            logger.info(f"Loaded {len(detections)} detections")

            # Process in batches
            total_success = 0
            total_failed = 0

            for i in range(0, len(detections), batch_size):
                batch = detections[i : i + batch_size]

                # Prepare batch data
                batch_data = []

                for detection in batch:
                    # Generate embedding
                    embedding = self.embedding_service.encode_detection(detection)

                    if embedding is None:
                        total_failed += 1
                        continue

                    # Prepare metadata
                    # Normalize timestamp for consistent detection_id
                    timestamp_normalized = self._normalize_timestamp(detection.timestamp)
                    detection_id = f"{detection.user_id}_{timestamp_normalized}"

                    metadata = {
                        "user_id": detection.user_id,
                        "timestamp": detection.timestamp,
                        "severity": detection.severity,
                        "anomaly_score": detection.anomaly_score,
                        "max_abs_z": detection.max_abs_z,
                        "apps": detection.entities.get("apps", []),
                        "devices": detection.entities.get("devices", []),
                        "locations": detection.entities.get("locations", []),
                        "top_features": detection.top_features_raw,
                    }

                    batch_data.append((detection_id, embedding, metadata))

                # Insert batch
                if batch_data:
                    success, failed = self.vector_store.insert_batch(batch_data)
                    total_success += success
                    total_failed += failed

                    logger.info(f"Batch {i // batch_size + 1}: {success} success, {failed} failed")

            logger.info(f"Population complete: {total_success} success, {total_failed} failed")

            return total_success, total_failed

        except Exception as e:
            logger.error(f"Failed to populate from CSV: {e}")
            return 0, 0

    @monitor_performance("similarity_search", "populate_from_jsonl")
    def populate_from_jsonl(self, jsonl_path: str, limit: int | None = None, batch_size: int = 100) -> tuple[int, int]:
        """
        Populate Qdrant collection from JSONL with paired records (original_event + detection).
        Uses original_event fields for richer metadata.

        Args:
            jsonl_path: Path to JSONL file with paired records
            limit: Optional limit on number of records to process
            batch_size: Number of detections to process per batch (default: 100)

        Returns:
            Tuple of (success_count, failed_count)

        Example:
            >>> similarity = SimilaritySearch()
            >>> success, failed = similarity.populate_from_jsonl(
            ...     "data/input/ai/synthetic_paired_detections.jsonl",
            ...     limit=1000
            ... )
            >>> print(f"Loaded {success} detections")
        """
        try:
            import json

            logger.info(f"Populating from JSONL: {jsonl_path}")

            # Read JSONL file
            records = []
            with open(jsonl_path) as f:
                for i, line in enumerate(f):
                    if limit and i >= limit:
                        break
                    try:
                        record = json.loads(line.strip())
                        records.append(record)
                    except json.JSONDecodeError as e:
                        logger.warning(f"Skipping invalid JSON line {i + 1}: {e}")

            logger.info(f"Loaded {len(records)} paired records")

            # Process in batches
            total_success = 0
            total_failed = 0

            for i in range(0, len(records), batch_size):
                batch = records[i : i + batch_size]

                # Prepare batch data
                batch_data = []

                for record in batch:
                    try:
                        # Extract original_event and detection
                        original_event = record.get("original_event", {})
                        detection_dict = record.get("detection", {})

                        # Convert detection dict to DetectionRecord
                        detection = self.bridge.dict_to_detection(detection_dict)

                        # Extract entities from original_event (for embedding context)
                        entities = self._extract_entities_from_original_event(original_event, detection)

                        # Generate embedding with entities
                        embedding = self.embedding_service.encode_detection(detection, entities=entities)

                        if embedding is None:
                            total_failed += 1
                            continue

                        # Prepare metadata with original_event fields
                        # Normalize timestamp for consistent detection_id
                        timestamp_normalized = self._normalize_timestamp(detection.timestamp)
                        detection_id = f"{detection.user_id}_{timestamp_normalized}"

                        metadata = {
                            # Standard fields
                            "user_id": detection.user_id,
                            "timestamp": detection.timestamp,
                            "severity": detection.severity,
                            "anomaly_score": detection.anomaly_score,
                            "max_abs_z": detection.max_abs_z,
                            "top_features": detection.top_features_raw,
                            # NEW: Original event fields (single values for filtering)
                            "app": original_event.get("properties", {}).get("appDisplayName", ""),
                            "device": original_event.get("properties", {})
                            .get("deviceDetail", {})
                            .get("displayName", ""),
                            "browser": original_event.get("properties", {}).get("deviceDetail", {}).get("browser", ""),
                            "os": original_event.get("properties", {})
                            .get("deviceDetail", {})
                            .get("operatingSystem", ""),
                            "ip_address": original_event.get("properties", {}).get("ipAddress", ""),
                            "client_app": original_event.get("properties", {}).get("clientAppUsed", ""),
                            "location": f"{original_event.get('location', {}).get('city', '')}, {original_event.get('location', {}).get('countryOrRegion', '')}",
                            # Legacy fields (for backward compatibility)
                            "apps": detection.entities.get("apps", []),
                            "devices": detection.entities.get("devices", []),
                            "locations": detection.entities.get("locations", []),
                        }

                        batch_data.append((detection_id, embedding, metadata))

                    except Exception as e:
                        logger.warning(f"Failed to process record: {e}")
                        total_failed += 1

                # Insert batch
                if batch_data:
                    success, failed = self.vector_store.insert_batch(batch_data)
                    total_success += success
                    total_failed += failed

                    logger.info(f"Batch {i // batch_size + 1}: {success} success, {failed} failed")

            logger.info(f"Population complete: {total_success} success, {total_failed} failed")

            return total_success, total_failed

        except Exception as e:
            logger.error(f"Failed to populate from JSONL: {e}")
            return 0, 0

    def populate_from_postgres(
        self,
        db_conn,
        limit: int | None = None,
        batch_size: int = 100,
        user_filter: str | None = None,
    ) -> tuple[int, int]:
        """
        Populate Qdrant from PostgreSQL enriched_anomalies.

        Identical logic to populate_from_jsonl() but reads records directly from
        the database instead of a file.  Each row supplies the same two fields
        that the JSONL file contains:

            original_event  — raw Azure AD event (same as JSONL ``original_event``)
            raw_detection   — DFP detection dict  (same as JSONL ``detection``)

        The critical difference from populate_from_jsonl is that the database row
        also has ``anomaly_id`` (a real UUID assigned at enrichment time), so that
        becomes the Qdrant point ID.  This lets anomaly_validator._similarity_check()
        resolve labels with::

            SELECT anomaly_id, is_anomaly
            FROM enriched_anomalies
            WHERE anomaly_id = ANY(%s::uuid[])

        Args:
            db_conn: psycopg2 connection (caller owns lifecycle)
            limit: Max rows to process (None = all)
            batch_size: Qdrant upsert batch size (default: 100)
            user_filter: Optional user_id to restrict rows

        Returns:
            Tuple of (successful_count, failed_count)
        """
        try:
            import psycopg2.extras

            logger.info("Populating from PostgreSQL enriched_anomalies")

            # ── Fetch rows ────────────────────────────────────────────────────
            base_sql = """
                SELECT anomaly_id, original_event, raw_detection
                FROM enriched_anomalies
                WHERE original_event IS NOT NULL
                  AND raw_detection  IS NOT NULL
            """
            params: list = []
            if user_filter:
                base_sql += " AND user_id = %s"
                params.append(user_filter)
            base_sql += " ORDER BY timestamp DESC"
            if limit:
                base_sql += " LIMIT %s"
                params.append(limit)

            with db_conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(base_sql, params or None)
                rows = cur.fetchall()

            if not rows:
                logger.info("No rows found in enriched_anomalies")
                return 0, 0

            logger.info(f"Loaded {len(rows)} rows from enriched_anomalies")

            # ── Process in batches (identical to populate_from_jsonl) ─────────
            total_success = 0
            total_failed = 0

            for i in range(0, len(rows), batch_size):
                batch = rows[i : i + batch_size]
                batch_data = []

                for row in batch:
                    try:
                        # Same fields as JSONL paired record
                        original_event = row["original_event"] or {}
                        detection_dict = row["raw_detection"] or {}

                        # Convert detection dict to DetectionRecord
                        detection = self.bridge.dict_to_detection(detection_dict)

                        # Extract entities from original_event (for embedding context)
                        entities = self._extract_entities_from_original_event(original_event, detection)

                        # Generate embedding with entities
                        embedding = self.embedding_service.encode_detection(detection, entities=entities)

                        if embedding is None:
                            total_failed += 1
                            continue

                        # Use the real anomaly_id as Qdrant point ID so that
                        # anomaly_validator label lookup works correctly.
                        detection_id = str(row["anomaly_id"])

                        metadata = {
                            # Standard fields
                            "user_id": detection.user_id,
                            "timestamp": detection.timestamp,
                            "severity": detection.severity,
                            "anomaly_score": detection.anomaly_score,
                            "max_abs_z": detection.max_abs_z,
                            "top_features": detection.top_features_raw,
                            # Original event fields (single values for filtering)
                            "app": original_event.get("properties", {}).get("appDisplayName", ""),
                            "device": original_event.get("properties", {})
                            .get("deviceDetail", {})
                            .get("displayName", ""),
                            "browser": original_event.get("properties", {}).get("deviceDetail", {}).get("browser", ""),
                            "os": original_event.get("properties", {})
                            .get("deviceDetail", {})
                            .get("operatingSystem", ""),
                            "ip_address": original_event.get("properties", {}).get("ipAddress", ""),
                            "client_app": original_event.get("properties", {}).get("clientAppUsed", ""),
                            "location": f"{original_event.get('location', {}).get('city', '')}, {original_event.get('location', {}).get('countryOrRegion', '')}",
                        }

                        batch_data.append((detection_id, embedding, metadata))

                    except Exception as e:
                        logger.warning(f"Failed to process row: {e}")
                        total_failed += 1

                # Insert batch
                if batch_data:
                    success, failed = self.vector_store.insert_batch(batch_data)
                    total_success += success
                    total_failed += failed
                    logger.info(f"Batch {i // batch_size + 1}: {success} success, {failed} failed")

            logger.info(f"Population complete: {total_success} success, {total_failed} failed")
            return total_success, total_failed

        except Exception as e:
            logger.error(f"Failed to populate from postgres: {e}")
            return 0, 0

    def _extract_entities_from_original_event(
        self, original_event: dict[str, Any], detection: DetectionRecord
    ) -> list[dict[str, Any]]:
        """
        Extract entities from original_event (Azure AD structure).
        Mirrors enrichment_service._extract_entities_from_event() logic.

        Args:
            original_event: Azure AD event dict
            detection: DetectionRecord for anomaly context

        Returns:
            List of entity dicts
        """
        entities = []

        # APPLICATION
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

        # DEVICE
        device_name = original_event.get("properties", {}).get("deviceDetail", {}).get("displayName")
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

        # BROWSER
        browser = original_event.get("properties", {}).get("deviceDetail", {}).get("browser")
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

        # OPERATING SYSTEM
        os = original_event.get("properties", {}).get("deviceDetail", {}).get("operatingSystem")
        if os:
            entities.append(
                {
                    "type": "OS",
                    "text": os,
                    "confidence": 1.0,
                    "category": "device",
                    "source_feature": "properties.deviceDetail.operatingSystem",
                }
            )

        # LOCATION
        city = original_event.get("location", {}).get("city")
        country = original_event.get("location", {}).get("countryOrRegion")
        if city and country:
            entities.append(
                {
                    "type": "LOCATION",
                    "text": f"{city}, {country}",
                    "confidence": 1.0,
                    "category": "location",
                    "source_feature": "location.city,countryOrRegion",
                }
            )

        # IP_ADDRESS
        ip_address = original_event.get("properties", {}).get("ipAddress")
        if ip_address:
            entities.append(
                {
                    "type": "IP_ADDRESS",
                    "text": ip_address,
                    "confidence": 1.0,
                    "category": "network",
                    "source_feature": "properties.ipAddress",
                }
            )

        # CLIENT_APP
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

        # ANOMALY_SEVERITY (from detection)
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

        return entities

    def update_similar_detections(
        self,
        db_conn,
        top_k: int = 5,
        min_similarity: float = 0.5,
        batch_size: int = 100,
        user_filter: str | None = None,
    ) -> tuple[int, int]:
        """
        Phase 2: Update similar_detections in enriched_anomalies using stored embeddings.

        Must be called AFTER populate_from_postgres() so all points exist in Qdrant.
        Reads ai_enrichment['embedding'] from PostgreSQL — no re-encoding needed since
        enrichment_service already computed and stored these vectors.

        For each row:
          1. Read stored embedding from ai_enrichment['embedding']
          2. Call vector_store.search_similar() — Qdrant already has all points
          3. Exclude self-match (point.id == anomaly_id)
          4. Write results back with jsonb_set() — only similar_detections is touched,
             all other ai_enrichment fields (entities, embedding, graph_context, etc.)
             are left exactly as enrichment_service wrote them.

        Because point.id == anomaly_id == enriched_anomalies.anomaly_id, every
        detection_id in similar_detections is a real UUID that anomaly_validator
        can resolve with::

            SELECT anomaly_id, is_anomaly
            FROM enriched_anomalies
            WHERE anomaly_id = ANY(%s::uuid[])

        Args:
            db_conn: psycopg2 connection (caller owns lifecycle)
            top_k: Number of similar detections per record (default: 5)
            min_similarity: Minimum similarity score 0-1 (default: 0.5)
            batch_size: Commit/log frequency (default: 100)
            user_filter: Optional user_id to restrict rows

        Returns:
            Tuple of (updated_count, failed_count)
        """
        import numpy as np

        try:
            import psycopg2.extras

            logger.info("Phase 2: Updating similar_detections in enriched_anomalies")

            base_sql = """
                SELECT anomaly_id, ai_enrichment
                FROM enriched_anomalies
                WHERE ai_enrichment IS NOT NULL
                  AND ai_enrichment ? 'embedding'
            """
            params: list = []
            if user_filter:
                base_sql += " AND user_id = %s"
                params.append(user_filter)
            base_sql += " ORDER BY timestamp DESC"

            with db_conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(base_sql, params or None)
                rows = cur.fetchall()

            if not rows:
                logger.info("No rows with embeddings found")
                return 0, 0

            logger.info(f"Updating similar_detections for {len(rows)} records")

            total_updated = 0
            total_failed = 0

            for i, row in enumerate(rows):
                try:
                    anomaly_id = str(row["anomaly_id"])
                    embedding_list = row["ai_enrichment"].get("embedding")

                    if not embedding_list:
                        total_failed += 1
                        continue

                    # Use stored embedding — identical to what would be re-encoded
                    embedding_arr = np.array(embedding_list, dtype=np.float32)

                    # Request top_k + 1 so we have room to drop the self-match
                    search_results = self.vector_store.search_similar(
                        embedding=embedding_arr,
                        top_k=top_k + 1,
                        min_score=min_similarity,
                    )

                    similar_detections = []
                    for result in search_results:
                        if result.detection_id == anomaly_id:
                            continue  # exclude self

                        ts = result.timestamp
                        ts_str = ts.isoformat() if hasattr(ts, "isoformat") else str(ts)

                        similar_detections.append(
                            {
                                "detection_id": result.detection_id,
                                "user_id": result.user_id,
                                "timestamp": ts_str,
                                "similarity_score": float(result.score),
                                "severity": result.metadata.get("severity", "UNKNOWN"),
                                "anomaly_score": float(result.metadata.get("anomaly_score", 0.0)),
                                "app": result.metadata.get("app", ""),
                                "device": result.metadata.get("device", ""),
                                "browser": result.metadata.get("browser", ""),
                                "os": result.metadata.get("os", ""),
                                "ip_address": result.metadata.get("ip_address", ""),
                                "client_app": result.metadata.get("client_app", ""),
                                "location": result.metadata.get("location", ""),
                            }
                        )

                        if len(similar_detections) >= top_k:
                            break

                    # Surgical update — only similar_detections key is written
                    with db_conn.cursor() as cur:
                        cur.execute(
                            """
                            UPDATE enriched_anomalies
                            SET ai_enrichment = jsonb_set(
                                ai_enrichment,
                                '{similar_detections}',
                                %s::jsonb
                            )
                            WHERE anomaly_id = %s
                            """,
                            (json.dumps(similar_detections), anomaly_id),
                        )
                    db_conn.commit()
                    total_updated += 1

                    if (i + 1) % batch_size == 0:
                        logger.info(f"Progress: {i + 1}/{len(rows)} records updated")

                except Exception as e:
                    logger.warning(f"Failed to update similar_detections for {row.get('anomaly_id')}: {e}")
                    db_conn.rollback()
                    total_failed += 1

            logger.info(f"Phase 2 complete: {total_updated} updated, {total_failed} failed")
            return total_updated, total_failed

        except Exception as e:
            logger.error(f"Failed to update similar_detections: {e}")
            return 0, 0

    def get_collection_stats(self) -> dict[str, Any]:
        """
        Get collection statistics.

        Returns:
            Dict with collection info (points_count, status, etc.)

        Example:
            >>> stats = similarity.get_collection_stats()
            >>> print(f"Collection size: {stats['points_count']}")
            >>> print(f"Status: {stats['status']}")
            >>> print(f"Cold start: {stats['is_cold_start']}")
        """
        try:
            info = self.vector_store.get_collection_info()

            # Add cold start flag
            info["is_cold_start"] = self._is_cold_start()
            info["cold_start_threshold"] = self.cold_start_threshold

            return info

        except Exception as e:
            logger.error(f"Failed to get collection stats: {e}")
            return {}

    def clear_collection(self) -> bool:
        """
        Clear all vectors from collection.

        Returns:
            True if successful, False otherwise

        Warning:
            This deletes ALL detections from the collection.
            Use with caution - typically only for testing.
        """
        try:
            logger.warning("Clearing collection - this deletes all data")
            return self.vector_store.clear_collection()

        except Exception as e:
            logger.error(f"Failed to clear collection: {e}")
            return False


# ============================================================================
# Test Script
# ============================================================================
if __name__ == "__main__":
    """
    Populate Qdrant with detection embeddings.

    Supports three sources:
        --postgres  Read from enriched_anomalies (recommended — anomaly_id is used as
                    Qdrant point ID so anomaly_validator label lookup works correctly)
        --jsonl     Read from a paired JSONL file (point IDs are user_id+timestamp strings)
        --csv       Read from a CSV file (legacy, point IDs are user_id+timestamp strings)

    Examples:
        # Populate from PostgreSQL (step 3 of standard pipeline)
        python modules/ai/embeddings/similarity_search.py --postgres

        # Populate from PostgreSQL, limit rows and filter by user
        python modules/ai/embeddings/similarity_search.py --postgres --limit 500 --user alice@example.com

        # Populate from JSONL (paired records)
        python modules/ai/embeddings/similarity_search.py --jsonl data/input/ai/synthetic_paired_detections.jsonl

        # Populate from CSV (legacy)
        python modules/ai/embeddings/similarity_search.py --csv data/input/ai/user_aware_anomalies.csv
    """
    import argparse
    import time

    import psycopg2
    from dotenv import load_dotenv

    load_dotenv(Path(__file__).parents[3] / ".env", override=False)

    parser = argparse.ArgumentParser(description="Populate Qdrant with detection embeddings")
    parser.add_argument("--csv", type=str, help="Path to CSV file (legacy format)")
    parser.add_argument("--jsonl", type=str, help="Path to paired JSONL file")
    parser.add_argument(
        "--postgres", action="store_true", help="Populate from PostgreSQL enriched_anomalies (recommended)"
    )
    parser.add_argument("--user", type=str, default=None, help="Filter by user_id (only with --postgres)")
    parser.add_argument("--limit", type=int, default=None, help="Limit number of records to process")
    parser.add_argument("--batch-size", type=int, default=100, help="Batch size for processing (default: 100)")
    args = parser.parse_args()

    print("\n" + "=" * 80)
    print("QDRANT VECTOR STORE POPULATION")
    print("=" * 80)

    # Validate arguments
    if not args.csv and not args.jsonl and not args.postgres:
        print("\n   ✗ Must specify one of: --postgres, --jsonl, --csv")
        parser.print_help()
        sys.exit(1)

    if sum([bool(args.csv), bool(args.jsonl), bool(args.postgres)]) > 1:
        print("\n   ✗ Cannot combine --postgres, --jsonl and --csv")
        sys.exit(1)

    # Initialize
    print("\n1. Initializing SimilaritySearch...")
    try:
        similarity = SimilaritySearch()
        print("   ✓ SimilaritySearch initialized")
        print(f"   ✓ Cold start threshold: {similarity.cold_start_threshold}")

    except Exception as e:
        print(f"\n   ✗ Failed to initialize: {e}")
        print("\n   Make sure Qdrant is running:")
        print("   Check: services/check_services.sh")
        sys.exit(1)

    # Get initial stats
    print("\n2. Collection stats (before)...")
    stats_before = similarity.get_collection_stats()
    print(f"   Points: {stats_before.get('points_count', 0)}")
    print(f"   Status: {stats_before.get('status', 'unknown')}")
    print(f"   Cold start: {stats_before.get('is_cold_start', True)}")

    # Populate from PostgreSQL, JSONL, or CSV
    if args.postgres:
        print("\n3. Populating from PostgreSQL enriched_anomalies...")
        try:
            from modules.utils.db import get_db_params

            conn = psycopg2.connect(**get_db_params())
            p = get_db_params()
            print(f"   ✓ PostgreSQL  {p['host']}:{p['port']}")
        except Exception as e:
            print(f"   ✗ PostgreSQL: {e}")
            sys.exit(1)

        # ── Phase 1: Insert embeddings into Qdrant ──────────────────────────
        start_time = time.time()
        success, failed = similarity.populate_from_postgres(
            db_conn=conn,
            limit=args.limit,
            batch_size=args.batch_size,
            user_filter=args.user,
        )
        elapsed = time.time() - start_time

        print(f"\n   Phase 1 done in {elapsed:.1f}s")
        print(f"   Inserted : {success}")
        print(f"   Failed   : {failed}")
        if success:
            print(f"   Rate     : {success / max(elapsed, 0.001):.1f} detections/sec")

        # ── Phase 2: Update similar_detections in PostgreSQL ─────────────────
        print("\n3b. Phase 2: Writing similar_detections back to enriched_anomalies...")
        print("    (reads stored embeddings — no re-encoding, self-match excluded)")
        p2_start = time.time()
        updated, update_failed = similarity.update_similar_detections(
            db_conn=conn,
            batch_size=args.batch_size,
            user_filter=args.user,
        )
        p2_elapsed = time.time() - p2_start
        conn.close()

        print(f"   Phase 2 done in {p2_elapsed:.1f}s")
        print(f"   Updated  : {updated}")
        print(f"   Failed   : {update_failed}")

    elif args.jsonl:
        print(f"\n3. Populating from JSONL: {args.jsonl}...")
        jsonl_path = Path(args.jsonl)

        if not jsonl_path.exists():
            print(f"\n   ✗ JSONL file not found: {jsonl_path}")
            sys.exit(1)

        start_time = time.time()
        success, failed = similarity.populate_from_jsonl(
            str(jsonl_path),
            limit=args.limit,
            batch_size=args.batch_size,
        )
        elapsed = time.time() - start_time

    else:  # CSV
        print(f"\n3. Populating from CSV: {args.csv}...")
        csv_path = Path(args.csv)

        if not csv_path.exists():
            print(f"\n   ✗ CSV file not found: {csv_path}")
            sys.exit(1)

        start_time = time.time()
        success, failed = similarity.populate_from_csv(
            str(csv_path),
            limit=args.limit,
            batch_size=args.batch_size,
        )
        elapsed = time.time() - start_time

    if not args.postgres:  # Phase 1 summary already printed inside the postgres branch
        print(f"\n   ✓ Populated in {elapsed:.1f}s")
        print(f"   Success: {success}")
        print(f"   Failed: {failed}")
        print(f"   Rate: {success / max(elapsed, 0.001):.1f} detections/sec")
        print(f"   Average: {(elapsed * 1000) / max(success, 1):.2f}ms per detection")

    # Get final stats
    print("\n4. Collection stats (after)...")
    stats_after = similarity.get_collection_stats()
    print(f"   Points: {stats_after.get('points_count', 0)}")
    print(f"   Vectors: {stats_after.get('vectors_count', 0)}")
    print(f"   Indexed: {stats_after.get('indexed_vectors_count', 0)}")
    print(f"   Status: {stats_after.get('status', 'unknown')}")
    print(f"   Cold start: {stats_after.get('is_cold_start', True)}")

    # Summary
    print("\n" + "=" * 80)
    print("POPULATION COMPLETE")
    print("=" * 80)
    print(f"\nCollection: {similarity.vector_store.collection_name}")
    print(f"Total detections: {stats_after.get('points_count', 0)}")
    print(f"Vector dimensions: {similarity.vector_store.vector_dim}")
    print(f"Cold start threshold: {similarity.cold_start_threshold}")
    print(f"Cold start status: {stats_after.get('is_cold_start', True)}")
    print("\nVector store ready for similarity search!")
    print("=" * 80)
