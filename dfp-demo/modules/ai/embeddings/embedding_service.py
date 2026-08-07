#!/usr/bin/env python3
"""
Embedding Service: Semantic Vector Embeddings

Generates semantic embeddings from DFP detections using Sentence-BERT.
Converts detection features into 384-dimensional vectors for similarity search.

Architecture:
    - Model: all-MiniLM-L6-v2 (sentence-transformers)
    - Dimensions: 384
    - Input: DetectionRecord from feature_bridge
    - Output: numpy array (384,) embeddings
    - Cache: Redis for repeated detections

Text Representation:
    Combines multiple fields into natural language for embedding:
    - User ID
    - Timestamp context (day of week, hour)
    - Severity level
    - Feature descriptions (apps, devices, locations, metrics)

Usage:
    >>> service = EmbeddingService()
    >>> embedding = service.encode_detection(detection_record)
    >>> print(embedding.shape)  # (384,)
    >>>
    >>> # Batch processing
    >>> embeddings = service.encode_batch(detection_records)
    >>> print(embeddings.shape)  # (N, 384)

Cold Start:
    - Works from Day 1 (no data requirements)
    - Generates embeddings immediately for similarity search
    - Enabled when 10+ detections exist (cold start threshold)

Performance:
    - Encoding time: ~10-20ms per detection (CPU)
    - Batch encoding: ~5-10ms per detection (batch of 32)
    - Cache hit: <1ms
    - Model size: ~90MB

Reference:
    https://www.sbert.net/docs/pretrained_models.html
    all-MiniLM-L6-v2: Best quality/speed tradeoff for semantic search

Author: AI Intelligence Layer Team
Date: 2026-02-18
"""

import hashlib
import logging
import pickle
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

import numpy as np

# Add parent directory to path for imports
sys.path.append(str(Path(__file__).parent.parent.parent))

from scripts.utils import severity_from_score  # noqa: E402

if TYPE_CHECKING:
    from sentence_transformers import SentenceTransformer

try:
    from sentence_transformers import SentenceTransformer

    SENTENCE_TRANSFORMERS_AVAILABLE = True
except ImportError:
    SENTENCE_TRANSFORMERS_AVAILABLE = False
    logging.warning("sentence-transformers not installed. Install with: pip install sentence-transformers")

try:
    import redis

    REDIS_AVAILABLE = True
except ImportError:
    REDIS_AVAILABLE = False
    redis = None  # type: ignore
    logging.warning("redis not installed. Install with: pip install redis")

from modules.ai.shared.feature_bridge import DetectionRecord, FeatureBridge
from modules.ai.shared.monitoring import monitor_performance, record_cache_operation

logger = logging.getLogger(__name__)


@dataclass
class EmbeddingMetadata:
    """Metadata for embedding generation."""

    detection_id: str
    user_id: str
    timestamp: str
    model_name: str
    embedding_dim: int
    generation_time_ms: float


class EmbeddingService:
    """Generate semantic embeddings from detection records."""

    def __init__(
        self,
        model_name: str = "all-MiniLM-L6-v2",
        cache_enabled: bool = True,
        redis_host: str = "localhost",
        redis_port: int = 6379,
        redis_db: int = 1,
    ):
        """
        Initialize embedding service.

        Args:
            model_name: Sentence-BERT model name
            cache_enabled: Enable Redis caching
            redis_host: Redis host
            redis_port: Redis port
            redis_db: Redis database number (1 for embeddings)
        """
        self.model_name = model_name
        self.cache_enabled = cache_enabled
        self.model: SentenceTransformer | None = None
        self.redis_client = None

        if not SENTENCE_TRANSFORMERS_AVAILABLE:
            logger.error("sentence-transformers not available. Install with: pip install sentence-transformers")
            return

        try:
            logger.info(f"Loading sentence-transformers model: {model_name}")
            self.model = SentenceTransformer(model_name)
            embedding_dim = self.model.get_sentence_embedding_dimension() if self.model else 384
            logger.info(f"✅ Loaded model {model_name} (embedding dim: {embedding_dim})")
        except Exception as e:
            logger.error(f"Failed to load sentence-transformers model: {e}")
            self.model = None

        # Initialize Redis cache
        if cache_enabled and REDIS_AVAILABLE and redis is not None:
            try:
                self.redis_client = redis.Redis(host=redis_host, port=redis_port, db=redis_db, decode_responses=False)
                self.redis_client.ping()
                logger.info(f"✅ Connected to Redis cache at {redis_host}:{redis_port} (db={redis_db})")
            except Exception as e:
                logger.warning(f"Redis cache not available: {e}")
                self.redis_client = None

    @monitor_performance("embedding_service", "encode_detection")
    def encode_detection(
        self, detection: DetectionRecord, entities: list[dict[str, Any]] | None = None
    ) -> np.ndarray | None:
        """
        Encode a single detection into an embedding vector.

        Args:
            detection: DetectionRecord from feature_bridge
            entities: Optional list of entities from original_event (for richer context)

        Returns:
            numpy array of shape (384,) or None if encoding fails
        """
        if not self.model:
            logger.error("Model not loaded")
            return None

        # Check cache first
        cache_key = self._get_cache_key(detection)
        if self.cache_enabled and self.redis_client:
            try:
                cached = self.redis_client.get(cache_key)
                if cached:
                    record_cache_operation("embedding", hit=True)
                    return pickle.loads(cached)  # type: ignore[arg-type]
                else:
                    record_cache_operation("embedding", hit=False)
            except Exception as e:
                logger.warning(f"Cache read error: {e}")

        # Generate text representation (with entities if available)
        text = self._detection_to_text(detection, entities)

        # Encode
        try:
            embedding = self.model.encode(text, convert_to_numpy=True, show_progress_bar=False)

            # Cache result
            if self.cache_enabled and self.redis_client:
                try:
                    self.redis_client.setex(cache_key, 86400, pickle.dumps(embedding))  # 24 hour TTL
                except Exception as e:
                    logger.warning(f"Cache write error: {e}")

            return embedding
        except Exception as e:
            logger.error(f"Encoding error: {e}")
            return None

    @monitor_performance("embedding_service", "encode_batch")
    def encode_batch(self, detections: list[DetectionRecord]) -> np.ndarray | None:
        """
        Encode multiple detections into embedding vectors (batch mode).

        Args:
            detections: List of DetectionRecord objects

        Returns:
            numpy array of shape (N, 384) or None if encoding fails
        """
        if not self.model:
            logger.error("Model not loaded")
            return None

        if not detections:
            return np.array([])

        # Check cache for each detection
        embeddings = []
        uncached_indices = []
        uncached_texts = []

        for i, detection in enumerate(detections):
            cache_key = self._get_cache_key(detection)
            cached = None

            if self.cache_enabled and self.redis_client:
                try:
                    cached = self.redis_client.get(cache_key)
                    if cached:
                        record_cache_operation("embedding", hit=True)
                        embeddings.append(pickle.loads(cached))  # type: ignore[arg-type]
                    else:
                        record_cache_operation("embedding", hit=False)
                except Exception as e:
                    logger.warning(f"Cache read error: {e}")

            if not cached:
                uncached_indices.append(i)
                uncached_texts.append(self._detection_to_text(detection))
                embeddings.append(None)  # Placeholder

        # Encode uncached detections in batch
        if uncached_texts:
            try:
                uncached_embeddings = self.model.encode(
                    uncached_texts, convert_to_numpy=True, show_progress_bar=False, batch_size=32
                )

                # Fill in embeddings and cache
                for idx, embedding in zip(uncached_indices, uncached_embeddings, strict=False):
                    embeddings[idx] = embedding

                    # Cache result
                    if self.cache_enabled and self.redis_client:
                        try:
                            cache_key = self._get_cache_key(detections[idx])
                            self.redis_client.setex(cache_key, 86400, pickle.dumps(embedding))
                        except Exception as e:
                            logger.warning(f"Cache write error: {e}")

            except Exception as e:
                logger.error(f"Batch encoding error: {e}")
                return None

        return np.array(embeddings)

    def _detection_to_text(self, detection: DetectionRecord, entities: list[dict[str, Any]] | None = None) -> str:
        """
        Convert detection record to natural language representation.

        Args:
            detection: DetectionRecord
            entities: Optional list of entities from original_event (for richer context)

        Returns:
            Text representation suitable for embedding
        """
        # Parse timestamp
        try:
            dt = datetime.fromisoformat(detection.timestamp.replace("Z", "+00:00"))
            day_of_week = dt.strftime("%A")
            hour = dt.hour
            time_context = f"{day_of_week} at {hour:02d}:00"
        except Exception:
            time_context = "unknown time"

        # Severity
        severity = detection.severity.lower()

        # If entities available, use rich context from original_event
        if entities:
            # Extract entity types
            entity_map = {}
            for entity in entities:
                entity_type = entity.get("type")
                if entity_type and entity.get("text"):
                    entity_map[entity_type] = entity["text"]

            # Build richer narrative with original_event context
            parts = [f"User {detection.user_id}"]

            # Application context
            if "APPLICATION" in entity_map:
                parts.append(f"accessed {entity_map['APPLICATION']} application")

            # Device/browser/OS context
            if "DEVICE" in entity_map and "BROWSER" in entity_map and "OS" in entity_map:
                parts.append(
                    f"from {entity_map['BROWSER']} browser on {entity_map['DEVICE']} device running {entity_map['OS']}"
                )
            elif "DEVICE" in entity_map and "BROWSER" in entity_map:
                parts.append(f"from {entity_map['BROWSER']} browser on {entity_map['DEVICE']} device")
            elif "BROWSER" in entity_map and "OS" in entity_map:
                parts.append(f"from {entity_map['BROWSER']} browser on {entity_map['OS']}")
            elif "BROWSER" in entity_map:
                parts.append(f"from {entity_map['BROWSER']} browser")
            elif "DEVICE" in entity_map:
                parts.append(f"from {entity_map['DEVICE']} device")

            # Location context
            if "LOCATION" in entity_map:
                parts.append(f"in {entity_map['LOCATION']}")

            # IP address context
            if "IP_ADDRESS" in entity_map:
                parts.append(f"(IP: {entity_map['IP_ADDRESS']})")

            # Client app context (authentication method)
            if "CLIENT_APP" in entity_map:
                parts.append(f"using {entity_map['CLIENT_APP']}")

            # Time context
            parts.append(f"on {time_context}")

            # Severity context
            if "ANOMALY_SEVERITY" in entity_map:
                parts.append(f"triggered {entity_map['ANOMALY_SEVERITY']} severity anomaly")
            else:
                parts.append(f"triggered {severity} severity anomaly")

            text = " ".join(parts)

            # Add anomaly score context
            _sev = severity_from_score(detection.anomaly_score)
            if _sev == "CRITICAL":
                text += f" (critical anomaly, score {detection.anomaly_score:.1f})"
            elif _sev == "HIGH":
                text += f" (highly unusual, score {detection.anomaly_score:.1f})"
            elif _sev in ("MEDIUM", "LOW"):
                text += f" (unusual, score {detection.anomaly_score:.1f})"

        else:
            # Fallback: Use detection.parsed_features (backward compatibility)
            feature_descriptions = []
            for feature in detection.parsed_features:
                if feature.category == "app":
                    feature_descriptions.append(f"accessed {feature.value}")
                elif feature.category == "device":
                    feature_descriptions.append(f"from {feature.value}")
                elif feature.category == "location":
                    if "city" in feature.name.lower():
                        feature_descriptions.append(f"in {feature.value}")
                    elif "travel" in feature.name.lower():
                        feature_descriptions.append(f"traveled {feature.value} km/h")
                elif feature.category == "activity":
                    if isinstance(feature.value, (int, float)):
                        feature_descriptions.append(f"logged {feature.value} events")

            # Build natural language text
            parts = [
                f"User {detection.user_id}",
                f"on {time_context}",
                f"triggered {severity} severity anomaly",
            ]

            if feature_descriptions:
                parts.append(": " + ", ".join(feature_descriptions))

            text = " ".join(parts)

            # Add z-score context for severity
            _sev = severity_from_score(detection.anomaly_score)
            if _sev == "CRITICAL":
                text += f" (highly unusual, z-score {detection.anomaly_score:.1f})"
            elif _sev == "HIGH":
                text += f" (unusual, z-score {detection.anomaly_score:.1f})"

        return text

    def _get_cache_key(self, detection: DetectionRecord) -> str:
        """
        Generate cache key for detection.

        Args:
            detection: DetectionRecord

        Returns:
            Cache key string
        """
        # Hash user_id + timestamp + top_features for unique key
        content = f"{detection.user_id}_{detection.timestamp}_{detection.top_features_raw}"
        hash_digest = hashlib.md5(content.encode()).hexdigest()
        return f"embedding:{self.model_name}:{hash_digest}"

    def get_embedding_dimension(self) -> int:
        """Get embedding dimension."""
        if not self.model:
            return 384  # Default for all-MiniLM-L6-v2
        dim = self.model.get_sentence_embedding_dimension()
        return dim if dim is not None else 384


# ============================================================================
# TEST SCRIPT
# ============================================================================

if __name__ == "__main__":
    import time

    print("=" * 80)
    print("EMBEDDING SERVICE TEST")
    print("=" * 80)

    # Initialize services
    print("\n1. Initializing services...")
    bridge = FeatureBridge()
    service = EmbeddingService()

    if not service.model:
        print("❌ Embedding model not available")
        print("   Install with: pip install sentence-transformers")
        sys.exit(1)

    print(f"✅ Loaded model: {service.model_name}")
    print(f"   Embedding dimension: {service.get_embedding_dimension()}")
    print(f"   Redis cache: {'enabled' if service.redis_client else 'disabled'}")

    # Load detections
    csv_path = Path("data/input/ai/user_aware_anomalies.csv")

    if not csv_path.exists():
        print(f"\n❌ CSV file not found: {csv_path}")
        sys.exit(1)

    print(f"\n2. Loading detections from {csv_path}...")
    detections = bridge.load_detections(str(csv_path), limit=100)  # Test with 100
    print(f"✅ Loaded {len(detections)} detections")

    # Test single encoding
    print("\n3. Testing single detection encoding...")
    test_detection = detections[0]
    print(f"   Detection: {test_detection.user_id} at {test_detection.timestamp}")
    print(f"   Text: {service._detection_to_text(test_detection)[:100]}...")

    start_time = time.time()
    embedding = service.encode_detection(test_detection)
    duration = time.time() - start_time

    if embedding is not None:
        print(f"✅ Generated embedding in {duration * 1000:.2f}ms")
        print(f"   Shape: {embedding.shape}")
        print(f"   Type: {embedding.dtype}")
        print(f"   Range: [{embedding.min():.3f}, {embedding.max():.3f}]")
        print(f"   Norm: {np.linalg.norm(embedding):.3f}")
    else:
        print("❌ Encoding failed")
        sys.exit(1)

    # Test cache hit
    print("\n4. Testing cache (re-encode same detection)...")
    start_time = time.time()
    cached_embedding = service.encode_detection(test_detection)
    cache_duration = time.time() - start_time

    if cached_embedding is not None and np.allclose(embedding, cached_embedding):
        print(f"✅ Cache hit in {cache_duration * 1000:.2f}ms ({duration / cache_duration:.1f}x faster)")
    else:
        print("⚠️  Cache miss (Redis may not be available)")

    # Test batch encoding
    print(f"\n5. Testing batch encoding ({len(detections)} detections)...")
    start_time = time.time()
    batch_embeddings = service.encode_batch(detections)
    batch_duration = time.time() - start_time

    if batch_embeddings is not None:
        print(f"✅ Generated {len(batch_embeddings)} embeddings in {batch_duration:.2f}s")
        print(f"   Performance: {batch_duration / len(detections) * 1000:.2f}ms per detection")
        print(f"   Shape: {batch_embeddings.shape}")
        print(f"   Memory: {batch_embeddings.nbytes / 1024:.1f} KB")
    else:
        print("❌ Batch encoding failed")
        sys.exit(1)

    # Test similarity
    print("\n6. Testing embedding similarity...")
    if batch_embeddings is not None and len(batch_embeddings) > 1:
        # Normalize embeddings for cosine similarity
        norms = np.linalg.norm(batch_embeddings, axis=1, keepdims=True)
        normalized = batch_embeddings / norms

        # Compute similarity matrix (first 5 detections)
        sample_size = min(5, len(normalized))
        similarity_matrix = np.dot(normalized[:sample_size], normalized[:sample_size].T)

        print(f"   Similarity matrix ({sample_size}x{sample_size}):")
        for i in range(sample_size):
            row = "   " + " ".join(f"{similarity_matrix[i][j]:.3f}" for j in range(sample_size))
            print(row)

        # Find most similar pair (excluding self-similarity)
        np.fill_diagonal(similarity_matrix, 0)
        i, j = np.unravel_index(similarity_matrix.argmax(), similarity_matrix.shape)
        max_sim = similarity_matrix[i, j]

        print("\n   Most similar pair:")
        print(f"   Detection {i}: {detections[i].user_id} ({detections[i].severity})")
        print(f"   Detection {j}: {detections[j].user_id} ({detections[j].severity})")
        print(f"   Similarity: {max_sim:.3f}")

    print("\n" + "=" * 80)
    print("✅ Embedding service test passed")
    print("=" * 80)
    print("\nNext: Implement vector_store.py for Qdrant storage")
    print("Then: similarity_search.py for finding similar detections")
