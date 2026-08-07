#!/usr/bin/env python3
"""
Vector Store: Qdrant Integration for Semantic Search

Manages persistent vector storage in Qdrant for detection embeddings.
Stores 384-dimensional embeddings with rich metadata for similarity search.

Architecture:
    - Database: Qdrant (http://localhost:6333)
    - Collection: dfp_detections
    - Vector Dimensions: 384 (all-MiniLM-L6-v2)
    - Distance: Cosine similarity
    - Metadata: user_id, timestamp, severity, app, device, browser, os, ip_address, client_app, location

Operations:
    - insert_detection: Store single detection embedding
    - insert_batch: Store multiple detections efficiently
    - search_similar: Find top-K similar detections
    - delete_detection: Remove detection by ID
    - clear_collection: Reset collection (testing/maintenance)
    - get_collection_info: Get size and statistics

Usage:
    >>> import uuid
    >>> store = VectorStore()
    >>>
    >>> # Insert single detection (detection_id must be a PostgreSQL anomaly_id UUID)
    >>> store.insert_detection(
    ...     detection_id=str(uuid.uuid4()),
    ...     embedding=np.array([...]),  # 384 dimensions
    ...     metadata={"user_id": "user@example.com", ...}
    ... )
    >>>
    >>> # Search similar
    >>> results = store.search_similar(embedding, top_k=5)
    >>> for result in results:
    ...     print(result.detection_id, result.score)

Cold Start:
    - Creates collection automatically if not exists
    - Supports incremental insertion (no batch requirements)
    - Returns empty results gracefully when collection empty

Performance:
    - Insert: ~5-10ms per detection
    - Batch insert: ~2-5ms per detection (batch of 100)
    - Search: ~10-50ms (depends on collection size)
    - Storage: ~1.5KB per detection (vector + metadata)

Reference:
    https://qdrant.tech/documentation/
    Qdrant Python Client: https://qdrant.tech/documentation/concepts/client/

Author: AI Intelligence Layer Team
Date: 2026-02-18
"""

import logging
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

import numpy as np

# Add parent directory to path for imports
sys.path.append(str(Path(__file__).parent.parent.parent))

if TYPE_CHECKING:
    from qdrant_client import QdrantClient
    from qdrant_client.models import (
        Distance,
        FieldCondition,
        Filter,
        MatchValue,
        PointStruct,
        VectorParams,
    )

try:
    from qdrant_client import QdrantClient
    from qdrant_client.models import (
        Distance,
        FieldCondition,
        Filter,
        MatchValue,
        PointStruct,
        VectorParams,
    )

    QDRANT_AVAILABLE = True
except ImportError:
    QDRANT_AVAILABLE = False
    logging.warning("qdrant-client not installed. Install with: pip install qdrant-client")
    QdrantClient = None  # type: ignore[misc,assignment]
    Distance = None  # type: ignore[misc,assignment]
    FieldCondition = None  # type: ignore[misc,assignment]
    Filter = None  # type: ignore[misc,assignment]
    MatchValue = None  # type: ignore[misc,assignment]
    PointStruct = None  # type: ignore[misc,assignment]
    VectorParams = None  # type: ignore[misc,assignment]

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


@dataclass
class SearchResult:
    """
    Single search result from similarity query.

    Attributes:
        detection_id: Unique detection identifier
        user_id: User who triggered detection
        timestamp: Detection timestamp
        score: Similarity score (0-1, higher = more similar)
        metadata: Additional metadata (severity, apps, devices, etc.)
    """

    detection_id: str
    user_id: str
    timestamp: datetime
    score: float
    metadata: dict[str, Any]


class VectorStore:
    """
    Qdrant vector database manager for detection embeddings.

    Manages persistent storage of 384-dimensional embeddings with metadata.
    Supports insertion, search, deletion, and collection management.

    Attributes:
        client: QdrantClient connection
        collection_name: Name of Qdrant collection
        vector_dim: Embedding dimensions (384)
    """

    def __init__(
        self,
        host: str = "localhost",
        port: int = 6333,
        collection_name: str = "dfp_detections",
        vector_dim: int = 384,
    ):
        """
        Initialize VectorStore with Qdrant connection.

        Args:
            host: Qdrant server host
            port: Qdrant server port
            collection_name: Name of collection to use/create
            vector_dim: Embedding dimensions (must match embedding_service)

        Raises:
            RuntimeError: If qdrant-client not installed
            ConnectionError: If cannot connect to Qdrant
        """
        if not QDRANT_AVAILABLE:
            raise RuntimeError("qdrant-client not installed. Install with: pip install qdrant-client")

        self.host = host
        self.port = port
        self.collection_name = collection_name
        self.vector_dim = vector_dim

        try:
            self.client = QdrantClient(host=host, port=port)  # type: ignore[misc]
            logger.info(f"Connected to Qdrant at {host}:{port}")

            # Initialize collection if needed
            self._ensure_collection_exists()

        except Exception as e:
            logger.error(f"Failed to connect to Qdrant: {e}")
            raise ConnectionError(
                f"Cannot connect to Qdrant at {host}:{port}. "
                f"Make sure Qdrant is running (check with services/check_services.sh)"
            ) from e

    def _ensure_collection_exists(self) -> None:
        """
        Create collection if it doesn't exist.

        Collection Schema:
            - Vectors: 384 dimensions, cosine distance
            - Metadata: user_id, timestamp, severity, app, device, browser, os, ip_address, client_app, location
        """
        try:
            collections = self.client.get_collections().collections
            collection_names = [col.name for col in collections]

            if self.collection_name not in collection_names:
                logger.info(f"Creating collection: {self.collection_name}")

                self.client.create_collection(
                    collection_name=self.collection_name,
                    vectors_config=VectorParams(  # type: ignore[misc]
                        size=self.vector_dim,
                        distance=Distance.COSINE,  # type: ignore[attr-defined]
                    ),
                )

                logger.info(f"Collection created: {self.collection_name}")
            else:
                logger.debug(f"Collection already exists: {self.collection_name}")

        except Exception as e:
            logger.error(f"Failed to ensure collection exists: {e}")
            raise

    @monitor_performance("vector_store", "insert")
    def insert_detection(self, detection_id: str, embedding: np.ndarray, metadata: dict[str, Any]) -> bool:
        """
        Insert single detection embedding into Qdrant.

        Args:
            detection_id: PostgreSQL anomaly_id UUID string.  This value is used as
                BOTH the Qdrant point ID and payload["detection_id"] so that
                anomaly_validator._similarity_check() can do a live label lookup via
                ``WHERE anomaly_id = ANY(%s::uuid[])``.
                Qdrant natively supports UUID strings as point IDs (no integer hashing).
            embedding: 384-dimensional numpy array
            metadata: Dict with user_id, timestamp, severity, app, device, browser,
                os, ip_address, client_app, location

        Returns:
            True if insertion successful, False otherwise

        Example:
            >>> metadata = {
            ...     "user_id": "user@example.com",
            ...     "timestamp": "2026-02-18T14:30:00+00:00",
            ...     "severity": "HIGH",
            ...     "anomaly_score": 4.82,
            ...     "app": "Office365",
            ...     "device": "Windows PC",
            ...     "browser": "Chrome 120",
            ...     "os": "Windows 10",
            ...     "ip_address": "203.0.113.42",
            ...     "client_app": "Browser",
            ...     "location": "London, GB",
            ... }
            >>> success = store.insert_detection(str(anomaly_id_uuid), embedding, metadata)
        """
        try:
            # Validate embedding
            if embedding.shape != (self.vector_dim,):
                logger.error(f"Invalid embedding shape: {embedding.shape}, expected ({self.vector_dim},)")
                return False

            # Convert embedding to list for Qdrant
            vector_list = embedding.tolist()

            # Prepare payload (metadata)
            payload = {
                # Standard identifiers
                "detection_id": detection_id,
                "user_id": metadata.get("user_id", "unknown"),
                "timestamp": metadata.get("timestamp", datetime.now().isoformat()),
                "severity": metadata.get("severity", "UNKNOWN"),
                "anomaly_score": float(metadata.get("anomaly_score", 0.0)),
                "max_abs_z": float(metadata.get("max_abs_z", 0.0)),
                "top_features": metadata.get("top_features", ""),
                # Original event fields (single values per detection)
                "app": metadata.get("app", ""),
                "device": metadata.get("device", ""),
                "browser": metadata.get("browser", ""),
                "os": metadata.get("os", ""),
                "ip_address": metadata.get("ip_address", ""),
                "client_app": metadata.get("client_app", ""),
                "location": metadata.get("location", ""),
            }

            # Use detection_id (anomaly_id UUID) directly as Qdrant point ID.
            # Qdrant natively supports UUID string IDs — no integer hashing needed.
            # This ensures payload["detection_id"] == point.id == PostgreSQL anomaly_id
            # so anomaly_validator can do a live label lookup without any remapping.
            point = PointStruct(  # type: ignore[misc]
                id=detection_id,
                vector=vector_list,
                payload=payload,
            )

            self.client.upsert(collection_name=self.collection_name, points=[point])

            logger.debug(f"Inserted detection: {detection_id}")
            return True

        except Exception as e:
            logger.error(f"Failed to insert detection {detection_id}: {e}")
            return False

    @monitor_performance("vector_store", "insert_batch")
    def insert_batch(self, detections: list[tuple[str, np.ndarray, dict[str, Any]]]) -> tuple[int, int]:
        """
        Insert multiple detections efficiently.

        Args:
            detections: List of (detection_id, embedding, metadata) tuples

        Returns:
            Tuple of (successful_count, failed_count)

        Example:
            >>> detections = [
            ...     ("d1", embedding1, metadata1),
            ...     ("d2", embedding2, metadata2),
            ... ]
            >>> success, failed = store.insert_batch(detections)
            >>> print(f"Inserted {success}/{len(detections)}")
        """
        if not detections:
            logger.warning("insert_batch called with empty list")
            return 0, 0

        points = []
        failed = 0

        for detection_id, embedding, metadata in detections:
            try:
                # Validate embedding
                if embedding.shape != (self.vector_dim,):
                    logger.warning(f"Invalid embedding shape for {detection_id}: {embedding.shape}")
                    failed += 1
                    continue

                # Convert to list
                vector_list = embedding.tolist()

                # Prepare payload
                payload = {
                    "detection_id": detection_id,
                    "user_id": metadata.get("user_id", "unknown"),
                    "timestamp": metadata.get("timestamp", datetime.now().isoformat()),
                    "severity": metadata.get("severity", "UNKNOWN"),
                    "anomaly_score": float(metadata.get("anomaly_score", 0.0)),
                    "max_abs_z": float(metadata.get("max_abs_z", 0.0)),
                    "top_features": metadata.get("top_features", ""),
                    # Original event fields (single values per detection)
                    "app": metadata.get("app", ""),
                    "device": metadata.get("device", ""),
                    "browser": metadata.get("browser", ""),
                    "os": metadata.get("os", ""),
                    "ip_address": metadata.get("ip_address", ""),
                    "client_app": metadata.get("client_app", ""),
                    "location": metadata.get("location", ""),
                }

                # Use UUID string directly — same as insert_detection
                point = PointStruct(  # type: ignore[misc]
                    id=detection_id,
                    vector=vector_list,
                    payload=payload,
                )

                points.append(point)

            except Exception as e:
                logger.warning(f"Failed to prepare point {detection_id}: {e}")
                failed += 1

        # Batch insert
        try:
            if points:
                self.client.upsert(collection_name=self.collection_name, points=points)

                success = len(points)
                logger.info(f"Batch inserted {success} detections ({failed} failed)")
                return success, failed
            else:
                logger.warning("No valid points to insert")
                return 0, failed

        except Exception as e:
            logger.error(f"Batch insert failed: {e}")
            return 0, len(detections)

    @monitor_performance("vector_store", "search")
    def search_similar(
        self,
        embedding: np.ndarray,
        top_k: int = 5,
        min_score: float = 0.0,
        user_filter: str | None = None,
    ) -> list[SearchResult]:
        """
        Search for similar detections by embedding.

        Args:
            embedding: Query embedding (384 dimensions)
            top_k: Number of results to return
            min_score: Minimum similarity score (0-1)
            user_filter: Optional user_id to filter results

        Returns:
            List of SearchResult objects (sorted by score descending)

        Example:
            >>> results = store.search_similar(query_embedding, top_k=5, min_score=0.7)
            >>> for result in results:
            ...     print(f"{result.user_id}: {result.score:.3f}")
        """
        try:
            # Validate embedding
            if embedding.shape != (self.vector_dim,):
                logger.error(f"Invalid embedding shape: {embedding.shape}, expected ({self.vector_dim},)")
                return []

            # Convert to list
            vector_list = embedding.tolist()

            # Prepare filter if user specified
            query_filter = None
            if user_filter and Filter is not None and FieldCondition is not None and MatchValue is not None:
                query_filter = Filter(
                    must=[FieldCondition(key="user_id", match=MatchValue(value=user_filter))]  # type: ignore[arg-type]
                )

            # Search
            search_results = self.client.query_points(  # type: ignore[attr-defined]
                collection_name=self.collection_name,
                query=vector_list,
                limit=top_k,
                score_threshold=min_score,
                query_filter=query_filter,
            ).points

            # Convert to SearchResult objects
            results = []
            for result in search_results:
                payload = result.payload  # type: ignore[attr-defined]

                search_result = SearchResult(
                    detection_id=payload.get("detection_id", "unknown"),  # type: ignore[union-attr]
                    user_id=payload.get("user_id", "unknown"),  # type: ignore[union-attr]
                    timestamp=datetime.fromisoformat(
                        payload.get("timestamp", datetime.now().isoformat())  # type: ignore[union-attr]
                    ),
                    score=result.score,
                    metadata={
                        "severity": payload.get("severity", "UNKNOWN"),  # type: ignore[union-attr]
                        "anomaly_score": payload.get("anomaly_score", 0.0),  # type: ignore[union-attr]
                        "max_abs_z": payload.get("max_abs_z", 0.0),  # type: ignore[union-attr]
                        "top_features": payload.get("top_features", ""),  # type: ignore[union-attr]
                        # Original event fields (single values per detection)
                        "app": payload.get("app", ""),  # type: ignore[union-attr]
                        "device": payload.get("device", ""),  # type: ignore[union-attr]
                        "browser": payload.get("browser", ""),  # type: ignore[union-attr]
                        "os": payload.get("os", ""),  # type: ignore[union-attr]
                        "ip_address": payload.get("ip_address", ""),  # type: ignore[union-attr]
                        "client_app": payload.get("client_app", ""),  # type: ignore[union-attr]
                        "location": payload.get("location", ""),  # type: ignore[union-attr]
                    },
                )

                results.append(search_result)

            logger.debug(f"Found {len(results)} similar detections")
            return results

        except Exception as e:
            logger.error(f"Search failed: {e}")
            return []

    def delete_detection(self, detection_id: str) -> bool:
        """
        Delete single detection from Qdrant.

        Args:
            detection_id: Unique detection identifier

        Returns:
            True if deletion successful, False otherwise
        """
        try:
            self.client.delete(
                collection_name=self.collection_name,
                points_selector=[detection_id],
            )

            logger.debug(f"Deleted detection: {detection_id}")
            return True

        except Exception as e:
            logger.error(f"Failed to delete detection {detection_id}: {e}")
            return False

    def clear_collection(self) -> bool:
        """
        Clear all vectors from collection (for testing/reset).

        Returns:
            True if successful, False otherwise

        Warning:
            This deletes ALL detections from the collection.
            Use with caution - typically only for testing.
        """
        try:
            # Delete collection
            self.client.delete_collection(collection_name=self.collection_name)
            logger.info(f"Deleted collection: {self.collection_name}")

            # Recreate empty collection
            self._ensure_collection_exists()
            logger.info(f"Recreated empty collection: {self.collection_name}")

            return True

        except Exception as e:
            logger.error(f"Failed to clear collection: {e}")
            return False

    def get_collection_info(self) -> dict[str, Any]:
        """
        Get collection statistics and info.

        Returns:
            Dict with size, vector_dim, distance metric, etc.

        Example:
            >>> info = store.get_collection_info()
            >>> print(f"Collection size: {info['points_count']}")
        """
        try:
            collection_info = self.client.get_collection(collection_name=self.collection_name)

            return {
                "name": self.collection_name,
                "points_count": collection_info.points_count,
                "vectors_count": collection_info.points_count,  # Same as points_count
                "indexed_vectors_count": getattr(collection_info, "indexed_vectors_count", 0),
                "vector_dim": self.vector_dim,
                "status": collection_info.status,
            }

        except Exception as e:
            logger.error(f"Failed to get collection info: {e}")
            return {}


# ============================================================================
# Test Script — syncs Qdrant from PostgreSQL enriched_anomalies
# ============================================================================
if __name__ == "__main__":
    """
    Populate Qdrant from PostgreSQL enriched_anomalies.

    Reads rows that already have an embedding stored in ai_enrichment.embedding
    and upserts them into Qdrant using the real anomaly_id as the point ID.
    This is the correct approach: detection_id == anomaly_id UUID so that
    anomaly_validator._similarity_check() can do a live label lookup via
    ``WHERE anomaly_id = ANY(%s::uuid[])``.

    Usage:
        python -m modules.ai.embeddings.vector_store [--limit N] [--user USER]

    Options:
        --limit N     Max rows to sync (default: 100)
        --user USER   Restrict to a specific user_id
    """
    import argparse
    import time

    import psycopg2
    import psycopg2.extras
    from dotenv import load_dotenv

    load_dotenv(Path(__file__).parents[3] / ".env", override=False)

    parser = argparse.ArgumentParser(description="Sync enriched_anomalies → Qdrant")
    parser.add_argument("--limit", type=int, default=100, help="Max rows to process (default: 100)")
    parser.add_argument("--user", help="Restrict to a specific user_id")
    args = parser.parse_args()

    print("\n" + "=" * 60)
    print("Vector Store — Sync from PostgreSQL")
    print("=" * 60)

    # ── 1. Connect to services ────────────────────────────────────────────────
    print("\n1. Connecting to services...")
    try:
        store = VectorStore()
        print(f"   ✓ Qdrant  {store.host}:{store.port}  collection={store.collection_name}")
    except Exception as e:
        print(f"   ✗ Qdrant connection failed: {e}")
        sys.exit(1)

    try:
        from modules.utils.db import get_db_params

        conn = psycopg2.connect(**get_db_params())
        p = get_db_params()
        print(f"   ✓ PostgreSQL  {p['host']}:{p['port']}")
    except Exception as e:
        print(f"   ✗ PostgreSQL connection failed: {e}")
        sys.exit(1)

    # ── 2. Collection stats before ────────────────────────────────────────────
    print("\n2. Collection info (before)...")
    info_before = store.get_collection_info()
    print(f"   Points : {info_before.get('points_count', 0)}")
    print(f"   Status : {info_before.get('status', 'unknown')}")

    # ── 3. Load rows with embeddings from PostgreSQL ──────────────────────────
    print("\n3. Loading rows from enriched_anomalies (with embedding)...")
    with conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            if args.user:
                cur.execute(
                    """
                    SELECT anomaly_id, user_id, timestamp, anomaly_score, mean_abs_z,
                           severity, ai_enrichment, original_event
                    FROM enriched_anomalies
                    WHERE ai_enrichment IS NOT NULL
                      AND ai_enrichment ? 'embedding'
                      AND user_id = %s
                    ORDER BY timestamp DESC
                    LIMIT %s
                    """,
                    (args.user, args.limit),
                )
            else:
                cur.execute(
                    """
                    SELECT anomaly_id, user_id, timestamp, anomaly_score, mean_abs_z,
                           severity, ai_enrichment, original_event
                    FROM enriched_anomalies
                    WHERE ai_enrichment IS NOT NULL
                      AND ai_enrichment ? 'embedding'
                    ORDER BY timestamp DESC
                    LIMIT %s
                    """,
                    (args.limit,),
                )
            rows = cur.fetchall()

    print(f"   ✓ Found {len(rows)} rows with embeddings")
    if not rows:
        print("   No rows to process. Run the enrichment pipeline first.")
        conn.close()
        sys.exit(0)

    # ── 4. Single insertion test (first row) ──────────────────────────────────
    print("\n4. Testing single insertion (first row)...")
    start_time = time.time()

    first = rows[0]
    first_embedding = np.array(first["ai_enrichment"]["embedding"], dtype=np.float32)
    first_orig = first.get("original_event") or {}
    first_props = first_orig.get("properties") or {}
    first_device = first_props.get("deviceDetail") or {}
    first_loc = first_orig.get("location") or {}

    metadata = {
        "user_id": first["user_id"],
        "timestamp": first["timestamp"].isoformat()
        if hasattr(first["timestamp"], "isoformat")
        else str(first["timestamp"]),
        "severity": first["severity"] or "UNKNOWN",
        "anomaly_score": float(first["anomaly_score"] or 0.0),
        "mean_abs_z": float(first["mean_abs_z"] or 0.0),
        "app": first_props.get("appDisplayName", ""),
        "device": first_device.get("displayName", ""),
        "browser": first_device.get("browser", ""),
        "os": first_device.get("operatingSystem", ""),
        "ip_address": first_props.get("ipAddress", ""),
        "client_app": first_props.get("clientAppUsed", ""),
        "location": f"{first_loc.get('city', '')}, {first_loc.get('countryOrRegion', '')}",
    }

    # anomaly_id IS the detection_id — no UUID generation needed
    detection_id = str(first["anomaly_id"])
    success = store.insert_detection(detection_id, first_embedding, metadata)

    elapsed = (time.time() - start_time) * 1000
    if success:
        print(f"   ✓ Inserted in {elapsed:.2f}ms")
        print(f"   anomaly_id : {detection_id}")
        print(f"   user_id    : {first['user_id']}")
        print(f"   severity   : {first['severity']}")
    else:
        print("   ✗ Insertion failed")

    # ── 5. Batch insertion (remaining rows) ───────────────────────────────────
    print("\n5. Batch inserting remaining rows...")
    start_time = time.time()

    batch_data = []
    for row in rows[1:]:
        embedding_vec = row["ai_enrichment"].get("embedding")
        if not embedding_vec:
            continue
        embedding_arr = np.array(embedding_vec, dtype=np.float32)
        row_orig = row.get("original_event") or {}
        row_props = row_orig.get("properties") or {}
        row_device = row_props.get("deviceDetail") or {}
        row_loc = row_orig.get("location") or {}
        meta = {
            "user_id": row["user_id"],
            "timestamp": row["timestamp"].isoformat()
            if hasattr(row["timestamp"], "isoformat")
            else str(row["timestamp"]),
            "severity": row["severity"] or "UNKNOWN",
            "anomaly_score": float(row["anomaly_score"] or 0.0),
            "mean_abs_z": float(row["mean_abs_z"] or 0.0),
            "app": row_props.get("appDisplayName", ""),
            "device": row_device.get("displayName", ""),
            "browser": row_device.get("browser", ""),
            "os": row_device.get("operatingSystem", ""),
            "ip_address": row_props.get("ipAddress", ""),
            "client_app": row_props.get("clientAppUsed", ""),
            "location": f"{row_loc.get('city', '')}, {row_loc.get('countryOrRegion', '')}",
        }
        batch_data.append((str(row["anomaly_id"]), embedding_arr, meta))

    inserted, failed = store.insert_batch(batch_data)
    elapsed = (time.time() - start_time) * 1000
    print(f"   ✓ Inserted {inserted} detections in {elapsed:.0f}ms ({elapsed / max(inserted, 1):.2f}ms each)")
    if failed:
        print(f"   ✗ Failed: {failed}")

    # ── 6. Collection stats after ─────────────────────────────────────────────
    print("\n6. Collection info (after)...")
    info_after = store.get_collection_info()
    print(f"   Points  : {info_after.get('points_count', 0)}")
    print(f"   Vectors : {info_after.get('vectors_count', 0)}")
    print(f"   Status  : {info_after.get('status', 'unknown')}")

    # ── 7. Similarity search smoke-test ───────────────────────────────────────
    print("\n7. Similarity search (top-5 for first row)...")
    start_time = time.time()
    results = store.search_similar(first_embedding, top_k=5, min_score=0.5)
    elapsed = (time.time() - start_time) * 1000
    print(f"   ✓ {len(results)} results in {elapsed:.2f}ms")
    print("   " + "-" * 56)
    for i, r in enumerate(results, 1):
        print(f"   {i}. {r.user_id[:30]:<30} score={r.score:.3f}  severity={r.metadata['severity']}")

    # ── 8. Summary ────────────────────────────────────────────────────────────
    conn.close()
    total = 1 + inserted
    print("\n" + "=" * 60)
    print(f"Sync complete — {total} detection(s) upserted into Qdrant")
    print(f"Collection : {store.collection_name}")
    print(f"Points     : {info_after.get('points_count', 0)}")
    print("=" * 60)
