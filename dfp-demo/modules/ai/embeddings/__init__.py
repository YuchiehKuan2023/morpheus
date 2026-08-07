"""
Embeddings Module: Semantic Vector Search

Generates semantic embeddings and enables similarity search across detections.

Components:
- embedding_service.py: Sentence-BERT embedding generation
- vector_store.py: Qdrant vector database integration
- similarity_search.py: API for finding similar detections

Usage:
    from modules.ai.embeddings import SimilaritySearch

    # High-level API (recommended)
    similarity = SimilaritySearch()
    results = similarity.get_similar_to_new(detection, top_k=5)

    # Or use components directly
    from modules.ai.embeddings import EmbeddingService, VectorStore

    # Generate embeddings
    service = EmbeddingService()
    embedding = service.encode_detection(detection_record)

    # Store and search
    store = VectorStore()
    store.insert_detection(detection_id, embedding, metadata)
    results = store.search_similar(query_embedding, top_k=5)

Author: AI Intelligence Layer Team
Date: 2026-02-18
"""

from .embedding_service import EmbeddingMetadata, EmbeddingService
from .similarity_search import SimilarityResult, SimilaritySearch
from .vector_store import SearchResult, VectorStore

__all__ = [
    "EmbeddingService",
    "EmbeddingMetadata",
    "VectorStore",
    "SearchResult",
    "SimilaritySearch",
    "SimilarityResult",
]
