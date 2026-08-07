"""
Integration tests for Week 27 — Hybrid Retrieval end-to-end scenarios.

Tests the HybridRetriever with mocked Qdrant/PostgreSQL/Neo4j backends,
verifying that RRF fusion, strategy selection, and context compression
work together correctly.
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock

sys.path.insert(0, str(Path(__file__).parents[2]))

from modules.ai.conversational.advanced_rag import (
    HybridRetriever,
    RankedResult,
    RetrievalContext,
)
from modules.ai.conversational.context_compressor import ContextCompressor

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_search_result(detection_id: str, score: float = 0.8):
    """Create a mock Qdrant SearchResult."""
    from datetime import datetime

    mock = MagicMock()
    mock.detection_id = detection_id
    mock.user_id = f"user-{detection_id}@example.com"
    mock.timestamp = datetime(2026, 4, 1, 12, 0, 0)
    mock.score = score
    mock.metadata = {"severity": "HIGH", "anomaly_score": 75.0}
    return mock


# ═══════════════════════════════════════════════════════════════════════
#  HybridRetriever with mocked backends
# ═══════════════════════════════════════════════════════════════════════


class TestHybridRetrieverDenseOnly:
    """HybridRetriever with only dense search enabled."""

    def test_dense_only_returns_results(self):
        retriever = HybridRetriever()
        retriever._qdrant_ready = True

        mock_emb = MagicMock()
        mock_emb.model.encode.return_value = [0.1] * 384
        retriever._embedding_svc = mock_emb

        mock_vs = MagicMock()
        mock_vs.search_similar.return_value = [
            _make_search_result("a1", 0.9),
            _make_search_result("a2", 0.7),
        ]
        retriever._vector_store = mock_vs

        ctx = RetrievalContext(use_dense=True, use_sparse=False, use_graph=False, use_structured=False)
        results = retriever.retrieve("impossible travel", ctx)

        assert len(results) == 2
        assert results[0].anomaly_id == "a1"
        assert results[0].similarity_score == 0.9

    def test_qdrant_unavailable_returns_empty(self):
        retriever = HybridRetriever()
        retriever._qdrant_ready = False

        ctx = RetrievalContext(use_dense=True, use_sparse=False, use_graph=False, use_structured=False)
        results = retriever.retrieve("test query", ctx)
        assert results == []


class TestHybridRetrieverSparseOnly:
    """HybridRetriever with only sparse FTS search."""

    def test_sparse_returns_fts_results(self):
        sparse_results = [
            RankedResult(
                anomaly_id="b1",
                user_id="alice@example.com",
                timestamp="2026-04-01T12:00:00",
                severity="CRITICAL",
                risk_score=90.0,
                root_cause="Impossible Travel",
                sub_category="Geographic",
                classification_reasoning="Two distant locations in 10 minutes",
                similarity_score=0.73,
            ),
        ]

        retriever = HybridRetriever()
        retriever._qdrant_ready = False
        retriever._sparse_search = MagicMock(return_value=sparse_results)

        ctx = RetrievalContext(use_dense=False, use_sparse=True, use_graph=False, use_structured=False)
        results = retriever.retrieve("impossible travel critical", ctx)

        assert len(results) == 1
        assert results[0].anomaly_id == "b1"
        assert results[0].severity == "CRITICAL"


class TestHybridRetrieverMultiStrategy:
    """HybridRetriever merging dense + sparse results via RRF."""

    def test_rrf_fusion_boosts_overlap(self):
        # Sparse results
        sparse_results = [
            RankedResult(
                anomaly_id="shared-1",
                user_id="alice@co.com",
                timestamp="2026-04-01T12:00:00",
                severity="HIGH",
                risk_score=80.0,
                root_cause="Unusual Access",
            ),
            RankedResult(
                anomaly_id="sparse-only",
                user_id="bob@co.com",
                timestamp="2026-04-02T12:00:00",
                severity="MEDIUM",
                risk_score=50.0,
                root_cause="Off Hours",
            ),
        ]

        # Setup dense mock
        retriever = HybridRetriever()
        retriever._qdrant_ready = True
        mock_emb = MagicMock()
        mock_emb.model.encode.return_value = [0.1] * 384
        retriever._embedding_svc = mock_emb

        mock_vs = MagicMock()
        mock_vs.search_similar.return_value = [
            _make_search_result("shared-1", 0.85),
            _make_search_result("dense-only", 0.6),
        ]
        retriever._vector_store = mock_vs

        # Mock sparse search
        retriever._sparse_search = MagicMock(return_value=sparse_results)

        ctx = RetrievalContext(use_dense=True, use_sparse=True, use_graph=False, use_structured=False)
        results = retriever.retrieve("unusual access pattern", ctx)

        # "shared-1" should be top-ranked (appears in both dense + sparse)
        assert len(results) == 3
        assert results[0].anomaly_id == "shared-1"
        assert "dense" in results[0].sources
        assert "sparse" in results[0].sources

    def test_max_results_limit(self):
        retriever = HybridRetriever()
        retriever._qdrant_ready = True
        mock_emb = MagicMock()
        mock_emb.model.encode.return_value = [0.1] * 384
        retriever._embedding_svc = mock_emb

        mock_vs = MagicMock()
        mock_vs.search_similar.return_value = [_make_search_result(f"a{i}", 0.9 - i * 0.1) for i in range(10)]
        retriever._vector_store = mock_vs

        # Mock sparse to return empty
        retriever._sparse_search = MagicMock(return_value=[])

        ctx = RetrievalContext(use_dense=True, use_sparse=True, max_results=3)
        results = retriever.retrieve("test", ctx)
        assert len(results) <= 3


class TestHybridRetrieverGracefulDegradation:
    """Verify that backend failures don't crash the retriever."""

    def test_all_backends_unavailable(self):
        retriever = HybridRetriever()
        retriever._qdrant_ready = False
        retriever._neo4j_available = False

        # Don't mock get_db — it won't be importable in test env → sparse returns []
        ctx = RetrievalContext(use_dense=True, use_sparse=False, use_graph=False, use_structured=False)
        results = retriever.retrieve("anything", ctx)
        assert results == []

    def test_dense_exception_caught(self):
        retriever = HybridRetriever()
        retriever._qdrant_ready = True

        mock_emb = MagicMock()
        mock_emb.model.encode.side_effect = RuntimeError("GPU OOM")
        retriever._embedding_svc = mock_emb

        ctx = RetrievalContext(use_dense=True, use_sparse=False)
        results = retriever.retrieve("test", ctx)
        assert results == []


# ═══════════════════════════════════════════════════════════════════════
#  End-to-end: Retriever → Compressor
# ═══════════════════════════════════════════════════════════════════════


class TestRetrievalToCompression:
    """Full pipeline from retrieval results to compressed context."""

    def test_pipeline(self):
        results = [
            RankedResult(
                anomaly_id=f"a{i}",
                user_id=f"user{i}@co.com",
                timestamp="2026-04-01T12:00:00",
                severity="HIGH" if i < 3 else "MEDIUM",
                risk_score=90.0 - i * 10,
                root_cause="Impossible Travel",
                rrf_score=1.0 / (i + 1),
                sources=["dense", "sparse"],
            )
            for i in range(8)
        ]

        compressor = ContextCompressor()
        text = compressor.compress(results, "impossible travel detections")
        assert "Retrieved 8 anomalies" in text
        assert "Result #1" in text
        assert "a0" in text

        d = compressor.compress_to_dict(results)
        assert d["returned"] == 8
        assert d["sources"] == ["dense", "sparse"]

    def test_single_result_full_detail(self):
        results = [
            RankedResult(
                anomaly_id="only-one",
                user_id="alice@co.com",
                severity="CRITICAL",
                risk_score=95.0,
                root_cause="Credential Theft",
                classification_reasoning="Multiple failed login attempts followed by successful login from new IP.",
                rrf_score=0.5,
                sources=["dense"],
            ),
        ]
        compressor = ContextCompressor()
        text = compressor.compress(results, "credential theft")
        assert "Credential Theft" in text
        assert "Multiple failed" in text
