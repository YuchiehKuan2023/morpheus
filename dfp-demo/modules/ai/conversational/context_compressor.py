"""
Context Compressor — Token-budget-aware formatting of retrieval results.

Takes a list of :class:`RankedResult` objects from the :class:`HybridRetriever`
and formats them into a concise context string that fits within a token budget.
Top-ranked results get full detail; lower-ranked results get one-line summaries.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from .advanced_rag import RankedResult

# ---------------------------------------------------------------------------
# Essential fields that are always preserved
# ---------------------------------------------------------------------------
_ESSENTIAL_FIELDS = {
    "anomaly_id",
    "user_id",
    "severity",
    "risk_score",
    "timestamp",
}


@dataclass(frozen=True, slots=True)
class CompressionConfig:
    """Knobs for context compression."""

    full_detail_count: int = 3  # Top-N results shown in full
    token_budget: int = 3000  # Max tokens for the entire context block
    include_reasoning: bool = True  # Include classification_reasoning for top results


class ContextCompressor:
    """
    Compress retrieval results into a token-budget-aware context string.

    Strategy:
    1. Top ``full_detail_count`` results → full structured detail.
    2. Remaining results → one-line summaries.
    3. If still over budget → drop lowest-ranked results.
    4. Essential fields (anomaly_id, user_id, severity, risk_score, timestamp)
       are never dropped.
    """

    def __init__(self, config: CompressionConfig | None = None) -> None:
        self._config = config or CompressionConfig()

    def compress(
        self,
        results: list[RankedResult],
        query: str,
        token_budget: int | None = None,
    ) -> str:
        """
        Build a context string from retrieval results within the token budget.

        Returns a formatted string suitable for injection into an LLM prompt.
        """
        budget = token_budget or self._config.token_budget

        if not results:
            return "No relevant anomalies found."

        parts: list[str] = []
        used_tokens = 0

        # Header
        header = f"Retrieved {len(results)} anomalies (query: {query[:80]})"
        header_tokens = self._estimate_tokens(header)
        parts.append(header)
        used_tokens += header_tokens

        for i, result in enumerate(results):
            if i < self._config.full_detail_count:
                text = self._format_full(result, i + 1)
            else:
                text = self._format_summary(result, i + 1)

            text_tokens = self._estimate_tokens(text)
            if used_tokens + text_tokens > budget:
                # Add truncation notice and stop
                notice = f"\n... ({len(results) - i} more results omitted due to token budget)"
                parts.append(notice)
                break

            parts.append(text)
            used_tokens += text_tokens

        return "\n".join(parts)

    def compress_to_dict(
        self,
        results: list[RankedResult],
        token_budget: int | None = None,
    ) -> dict[str, Any]:
        """
        Return a dict summary of results — suitable for tool output.
        """
        budget = token_budget or self._config.token_budget

        if not results:
            return {"returned": 0, "anomalies": [], "truncated": False}

        records: list[dict[str, Any]] = []
        used_tokens = 0
        truncated = False

        for i, result in enumerate(results):
            if i < self._config.full_detail_count:
                rec = result.to_dict()
            else:
                rec = {
                    "anomaly_id": result.anomaly_id,
                    "user_id": result.user_id,
                    "severity": result.severity,
                    "risk_score": result.risk_score,
                    "rrf_score": round(result.rrf_score, 4),
                }

            rec_tokens = self._estimate_tokens(json.dumps(rec, default=str))
            if used_tokens + rec_tokens > budget:
                truncated = True
                break

            records.append(rec)
            used_tokens += rec_tokens

        return {
            "returned": len(records),
            "total_found": len(results),
            "anomalies": records,
            "truncated": truncated,
            "sources": sorted({s for r in results for s in r.sources}),
        }

    # ------------------------------------------------------------------
    # Formatters
    # ------------------------------------------------------------------

    def _format_full(self, result: RankedResult, rank: int) -> str:
        """Full detail block for top-ranked results."""
        lines = [
            f"\n--- Result #{rank} (RRF: {result.rrf_score:.4f}, sources: {', '.join(result.sources)}) ---",
            f"Anomaly ID: {result.anomaly_id}",
            f"User: {result.user_id}",
            f"Severity: {result.severity} | Risk Score: {result.risk_score}",
            f"Timestamp: {result.timestamp}",
        ]
        if result.root_cause:
            lines.append(f"Root Cause: {result.root_cause}")
        if result.sub_category:
            lines.append(f"Sub-Category: {result.sub_category}")
        if self._config.include_reasoning and result.classification_reasoning:
            reasoning = result.classification_reasoning[:300]
            lines.append(f"Reasoning: {reasoning}")
        if result.similarity_score > 0:
            lines.append(f"Similarity: {result.similarity_score:.4f}")
        return "\n".join(lines)

    @staticmethod
    def _format_summary(result: RankedResult, rank: int) -> str:
        """One-line summary for lower-ranked results."""
        return (
            f"  #{rank}: {result.anomaly_id[:8]}… | {result.user_id} | "
            f"{result.severity} | risk={result.risk_score} | "
            f"{result.root_cause or 'Unknown'}"
        )

    @staticmethod
    def _estimate_tokens(text: str) -> int:
        """Rough token count (~4 chars per token)."""
        return len(text) // 4
