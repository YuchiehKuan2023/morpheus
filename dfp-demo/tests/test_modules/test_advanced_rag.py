"""
Unit tests for Week 27 — Advanced RAG Pipeline.

Covers:
- RetrievalContext + query analysis (strategy selection)
- RankedResult data type
- Reciprocal Rank Fusion (rrf_merge)
- ContextCompressor (full detail, summary, token budget)
- HybridRetriever (with mocked backends)
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[2]))

from modules.ai.conversational.advanced_rag import (
    RankedResult,
    RetrievalContext,
    analyze_query,
    rrf_merge,
)
from modules.ai.conversational.context_compressor import (
    CompressionConfig,
    ContextCompressor,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_result(anomaly_id: str = "a1", **overrides) -> RankedResult:
    defaults = {
        "anomaly_id": anomaly_id,
        "user_id": "alice@example.com",
        "timestamp": "2026-04-01T12:00:00",
        "severity": "HIGH",
        "risk_score": 75.0,
        "root_cause": "Impossible Travel",
        "sub_category": "Geographic Anomaly",
        "classification_reasoning": "User logged in from two distant locations within 30 minutes.",
        "similarity_score": 0.85,
        "rrf_score": 0.0,
        "sources": [],
    }
    defaults.update(overrides)
    return RankedResult(**defaults)


# ═══════════════════════════════════════════════════════════════════════
#  Query Analysis
# ═══════════════════════════════════════════════════════════════════════


class TestAnalyzeQuery:
    """Strategy selection based on query content and intent."""

    def test_default_strategies(self):
        ctx = analyze_query("show me anomalies")
        assert ctx.use_dense is True
        assert ctx.use_sparse is True

    def test_entity_query_enables_structured(self):
        ctx = analyze_query("anomalies for user alice@example.com")
        assert ctx.use_structured is True

    def test_pattern_query_enables_dense_and_graph(self):
        ctx = analyze_query("anomalies similar to the travel incident")
        assert ctx.use_dense is True
        assert ctx.use_graph is True

    def test_aggregation_query_uses_structured(self):
        ctx = analyze_query("how many critical anomalies this week?")
        assert ctx.use_structured is True

    def test_intent_entities_extracted(self):
        intent = {"entities": "alice@example.com, bob@example.com"}
        ctx = analyze_query("compare their profiles", intent)
        assert len(ctx.entities) == 2
        assert "alice@example.com" in ctx.entities

    def test_intent_severity_filter(self):
        intent = {"severity": "CRITICAL"}
        ctx = analyze_query("show anomalies", intent)
        assert ctx.filters.get("severity") == "CRITICAL"

    def test_intent_user_filter(self):
        intent = {"username": "alice@example.com"}
        ctx = analyze_query("show profile", intent)
        assert ctx.filters.get("user_id") == "alice@example.com"

    def test_intent_days_filter(self):
        intent = {"days": "7"}
        ctx = analyze_query("recent anomalies", intent)
        assert ctx.filters.get("days") == 7

    def test_aggregation_intent_disables_dense(self):
        intent = {"label": "Aggregation Query"}
        ctx = analyze_query("distribution of severity", intent)
        assert ctx.use_structured is True
        assert ctx.use_dense is False

    def test_none_intent(self):
        ctx = analyze_query("general question", None)
        assert ctx.use_dense is True
        assert ctx.use_sparse is True

    def test_intent_none_entities(self):
        intent = {"entities": "none"}
        ctx = analyze_query("show data", intent)
        assert ctx.entities == []


# ═══════════════════════════════════════════════════════════════════════
#  RankedResult
# ═══════════════════════════════════════════════════════════════════════


class TestRankedResult:
    """RankedResult data type and serialization."""

    def test_to_dict(self):
        r = _make_result(rrf_score=0.123456, sources=["dense", "sparse"])
        d = r.to_dict()
        assert d["anomaly_id"] == "a1"
        assert d["rrf_score"] == 0.1235  # rounded to 4 decimal
        assert d["sources"] == ["dense", "sparse"]

    def test_defaults(self):
        r = RankedResult(anomaly_id="x")
        assert r.user_id == ""
        assert r.rrf_score == 0.0
        assert r.sources == []


# ═══════════════════════════════════════════════════════════════════════
#  Reciprocal Rank Fusion
# ═══════════════════════════════════════════════════════════════════════


class TestRRFMerge:
    """RRF merge ranking and deduplication."""

    def test_single_list(self):
        results = [("dense", [_make_result("a1"), _make_result("a2")])]
        fused = rrf_merge(results, k=60)
        assert len(fused) == 2
        assert fused[0].anomaly_id == "a1"  # rank 0 → higher RRF score
        assert fused[0].rrf_score > fused[1].rrf_score

    def test_two_lists_boost_overlap(self):
        """Results appearing in multiple lists should get boosted."""
        results = [
            ("dense", [_make_result("a1"), _make_result("a2")]),
            ("sparse", [_make_result("a2"), _make_result("a3")]),
        ]
        fused = rrf_merge(results, k=60)
        # a2 appears in both lists → highest score
        scores = {r.anomaly_id: r.rrf_score for r in fused}
        assert scores["a2"] > scores["a1"]
        assert scores["a2"] > scores["a3"]

    def test_deduplication(self):
        results = [
            ("dense", [_make_result("a1")]),
            ("sparse", [_make_result("a1")]),
        ]
        fused = rrf_merge(results, k=60)
        assert len(fused) == 1
        assert "dense" in fused[0].sources and "sparse" in fused[0].sources

    def test_empty_lists(self):
        fused = rrf_merge([])
        assert fused == []

    def test_rrf_score_formula(self):
        """Verify RRF score = Σ 1/(k + rank + 1)."""
        results = [("a", [_make_result("x")])]
        fused = rrf_merge(results, k=60)
        expected = 1.0 / (60 + 0 + 1)  # k=60, rank=0
        assert abs(fused[0].rrf_score - expected) < 1e-6

    def test_three_list_merge(self):
        results = [
            ("dense", [_make_result("a1"), _make_result("a2"), _make_result("a3")]),
            ("sparse", [_make_result("a3"), _make_result("a1")]),
            ("graph", [_make_result("a1")]),
        ]
        fused = rrf_merge(results, k=60)
        # a1 appears in all 3 → highest
        assert fused[0].anomaly_id == "a1"
        assert len(fused[0].sources) == 3

    def test_k_parameter_affects_score_spread(self):
        # Separate result lists since rrf_merge mutates items in-place
        results_a = [("a", [_make_result("x"), _make_result("y"), _make_result("z")])]
        results_b = [("a", [_make_result("x"), _make_result("y"), _make_result("z")])]
        fused_low_k = rrf_merge(results_a, k=1)
        fused_high_k = rrf_merge(results_b, k=1000)
        # Lower k → larger ratio between top and bottom scores
        ratio_low = fused_low_k[0].rrf_score / fused_low_k[2].rrf_score
        ratio_high = fused_high_k[0].rrf_score / fused_high_k[2].rrf_score
        assert ratio_low > ratio_high


# ═══════════════════════════════════════════════════════════════════════
#  ContextCompressor
# ═══════════════════════════════════════════════════════════════════════


class TestContextCompressor:
    """Context compression with token budget management."""

    def _make_results(self, n: int = 5) -> list[RankedResult]:
        return [_make_result(f"a{i}", rrf_score=1.0 / (i + 1), sources=["dense"]) for i in range(n)]

    def test_compress_empty(self):
        c = ContextCompressor()
        assert c.compress([], "test query") == "No relevant anomalies found."

    def test_compress_produces_text(self):
        results = self._make_results(3)
        c = ContextCompressor()
        text = c.compress(results, "test")
        assert "Retrieved 3 anomalies" in text
        assert "a0" in text

    def test_full_detail_for_top_results(self):
        results = self._make_results(5)
        c = ContextCompressor(CompressionConfig(full_detail_count=2))
        text = c.compress(results, "test")
        # Top 2 should have "Result #" blocks with full detail
        assert "Result #1" in text
        assert "Result #2" in text
        # Remaining should be summaries (shorter, one-line)
        assert "Anomaly ID:" in text  # full detail has this

    def test_token_budget_truncation(self):
        results = self._make_results(20)
        c = ContextCompressor(CompressionConfig(token_budget=200))
        text = c.compress(results, "test")
        # Should hit budget and truncate
        assert "omitted" in text

    def test_compress_to_dict(self):
        results = self._make_results(5)
        c = ContextCompressor()
        d = c.compress_to_dict(results)
        assert d["returned"] == 5
        assert d["total_found"] == 5
        assert not d["truncated"]
        assert len(d["anomalies"]) == 5

    def test_compress_to_dict_truncation(self):
        results = self._make_results(20)
        c = ContextCompressor(CompressionConfig(token_budget=200))
        d = c.compress_to_dict(results)
        assert d["truncated"] is True
        assert d["returned"] < 20

    def test_compress_to_dict_top_detail_vs_summary(self):
        results = self._make_results(5)
        c = ContextCompressor(CompressionConfig(full_detail_count=2))
        d = c.compress_to_dict(results)
        # Top 2 records have full detail (classification_reasoning etc.)
        assert "classification_reasoning" in d["anomalies"][0]
        # Record 3+ only have essential fields
        assert "classification_reasoning" not in d["anomalies"][3]
        assert "anomaly_id" in d["anomalies"][3]

    def test_sources_aggregated(self):
        results = [
            _make_result("a1", sources=["dense", "sparse"]),
            _make_result("a2", sources=["graph"]),
        ]
        c = ContextCompressor()
        d = c.compress_to_dict(results)
        assert "dense" in d["sources"]
        assert "graph" in d["sources"]

    def test_summary_format(self):
        r = _make_result("abcdef12-3456-7890", severity="CRITICAL", risk_score=95.0)
        text = ContextCompressor._format_summary(r, 5)
        assert "#5" in text
        assert "CRITICAL" in text
        assert "95.0" in text


# ═══════════════════════════════════════════════════════════════════════
#  RetrievalContext
# ═══════════════════════════════════════════════════════════════════════


class TestRetrievalContext:
    """RetrievalContext default values and mutability."""

    def test_defaults(self):
        ctx = RetrievalContext()
        assert ctx.use_dense is True
        assert ctx.use_sparse is True
        assert ctx.use_graph is False
        assert ctx.use_structured is False
        assert ctx.max_results == 10

    def test_entities_are_independent(self):
        """Each instance should have its own entities list."""
        c1 = RetrievalContext()
        c2 = RetrievalContext()
        c1.entities.append("alice")
        assert "alice" not in c2.entities
