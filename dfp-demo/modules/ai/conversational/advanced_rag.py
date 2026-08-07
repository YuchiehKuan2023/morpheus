"""
Advanced RAG — Hybrid Retrieval with Reciprocal Rank Fusion.

Combines four retrieval strategies and merges results using RRF:
1. **Dense**: Qdrant semantic vector search (existing)
2. **Sparse**: PostgreSQL full-text search (tsvector + GIN)
3. **Graph**: Neo4j entity-linked traversal
4. **Structured**: SQL exact-match filters (severity, user_id, date range)

The :class:`HybridRetriever` is used by the agent's ``semantic_search_anomalies``
tool to replace the previous dense-only + SQL-fallback approach.
"""

from __future__ import annotations

import logging
import os
import sys
from dataclasses import dataclass, field
from typing import Any

from modules.utils.db import get_db

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class RetrievalContext:
    """Controls which retrieval strategies to activate."""

    use_dense: bool = True
    use_sparse: bool = True
    use_graph: bool = False
    use_structured: bool = False
    entities: list[str] = field(default_factory=list)
    filters: dict[str, Any] = field(default_factory=dict)
    max_results: int = 10


@dataclass(slots=True)
class RankedResult:
    """A single retrieval result with an RRF score."""

    anomaly_id: str
    user_id: str = ""
    timestamp: str = ""
    severity: str = ""
    risk_score: float = 0.0
    root_cause: str = ""
    sub_category: str = ""
    classification_reasoning: str = ""
    similarity_score: float = 0.0
    rrf_score: float = 0.0
    sources: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "anomaly_id": self.anomaly_id,
            "user_id": self.user_id,
            "timestamp": self.timestamp,
            "severity": self.severity,
            "risk_score": self.risk_score,
            "root_cause": self.root_cause,
            "sub_category": self.sub_category,
            "classification_reasoning": self.classification_reasoning,
            "similarity_score": round(self.similarity_score, 4),
            "rrf_score": round(self.rrf_score, 4),
            "sources": self.sources,
        }


# ---------------------------------------------------------------------------
# Query analysis — strategy selection
# ---------------------------------------------------------------------------

# Keywords that indicate specific query types
_ENTITY_PATTERNS = {"@", "user", "username"}
_AGGREGATION_KEYWORDS = {"how many", "count", "total", "average", "distribution"}
_PATTERN_KEYWORDS = {"similar", "like", "pattern", "related to"}


def analyze_query(query: str, intent: dict[str, Any] | None = None) -> RetrievalContext:
    """
    Determine which retrieval strategies to use based on query content and intent.

    Rules:
    - Entity-specific queries (username, anomaly_id) → structured + graph
    - Pattern queries ("similar to", "like X") → dense + graph
    - Aggregation queries ("how many") → structured only
    - Default: dense + sparse (keyword + semantic coverage)
    """
    ctx = RetrievalContext()
    ql = query.lower()

    # Extract entities from intent
    if intent:
        entities_str = intent.get("entities", "")
        if isinstance(entities_str, str) and entities_str.lower() not in ("none", ""):
            import re

            ctx.entities = [e.strip() for e in re.split(r"[,;]|\band\b", entities_str) if e.strip()]

        # Extract filters from intent
        label = intent.get("label", "")
        if label in ("Aggregation Query", "Drill-Down"):
            ctx.use_structured = True
            ctx.use_dense = False
            ctx.use_sparse = False

    # Entity-specific query
    if ctx.entities or any(p in ql for p in _ENTITY_PATTERNS):
        ctx.use_structured = True
        ctx.use_graph = bool(ctx.entities)

    # Pattern/similarity query
    if any(k in ql for k in _PATTERN_KEYWORDS):
        ctx.use_dense = True
        ctx.use_graph = True

    # Aggregation query → structured only
    if any(k in ql for k in _AGGREGATION_KEYWORDS):
        ctx.use_structured = True

    # Build SQL filters from intent
    if intent:
        ctx.filters = _extract_filters(intent)

    return ctx


def _extract_filters(intent: dict[str, Any]) -> dict[str, Any]:
    """Extract SQL-compatible filters from intent analysis."""
    filters: dict[str, Any] = {}

    severity = intent.get("severity")
    if severity and isinstance(severity, str) and severity.upper() in ("CRITICAL", "HIGH", "MEDIUM", "LOW"):
        filters["severity"] = severity.upper()

    username = intent.get("username") or intent.get("user_id")
    if username and isinstance(username, str) and username.lower() != "none":
        filters["user_id"] = username

    days = intent.get("days") or intent.get("time_range")
    if days:
        try:
            filters["days"] = int(days)
        except (ValueError, TypeError):
            pass

    return filters


# ---------------------------------------------------------------------------
# Reciprocal Rank Fusion
# ---------------------------------------------------------------------------


def rrf_merge(
    result_lists: list[tuple[str, list[RankedResult]]],
    k: int = 60,
) -> list[RankedResult]:
    """
    Reciprocal Rank Fusion: ``score = Σ 1/(k + rank_i)``

    Merges ranked lists from different retrieval strategies.
    Results appearing in multiple lists get boosted scores.
    """
    scores: dict[str, float] = {}
    items: dict[str, RankedResult] = {}
    sources: dict[str, list[str]] = {}

    for source_name, hits in result_lists:
        for rank, hit in enumerate(hits):
            doc_id = hit.anomaly_id
            scores[doc_id] = scores.get(doc_id, 0.0) + 1.0 / (k + rank + 1)
            if doc_id not in items:
                items[doc_id] = hit
                sources[doc_id] = []
            sources[doc_id].append(source_name)

    sorted_ids = sorted(scores, key=lambda x: scores[x], reverse=True)
    results: list[RankedResult] = []
    for doc_id in sorted_ids:
        item = items[doc_id]
        item.rrf_score = scores[doc_id]
        item.sources = sources[doc_id]
        results.append(item)

    return results


# ---------------------------------------------------------------------------
# HybridRetriever
# ---------------------------------------------------------------------------


class HybridRetriever:
    """
    Combines sparse + dense + graph + structured retrieval with
    Reciprocal Rank Fusion.

    Each strategy is optional and gracefully degrades — if Qdrant is
    unavailable, the dense leg is skipped; if Neo4j is down, the graph
    leg is skipped.  At minimum, PostgreSQL FTS always works.
    """

    def __init__(self) -> None:
        self._qdrant_ready: bool | None = None
        self._embedding_svc: Any = None
        self._vector_store: Any = None
        self._neo4j_available: bool | None = None

    # ------------------------------------------------------------------
    # Public entry point
    # ------------------------------------------------------------------

    def retrieve(
        self,
        query: str,
        context: RetrievalContext | None = None,
    ) -> list[RankedResult]:
        """
        Multi-strategy retrieval with RRF merge.

        Returns up to ``context.max_results`` anomaly records ranked by
        combined relevance across all active retrieval strategies.
        """
        if context is None:
            context = RetrievalContext()

        result_lists: list[tuple[str, list[RankedResult]]] = []

        # Strategy 1: Dense (Qdrant semantic search)
        if context.use_dense:
            dense_hits = self._dense_search(query, limit=context.max_results)
            if dense_hits:
                result_lists.append(("dense", dense_hits))

        # Strategy 2: Sparse (PostgreSQL full-text search)
        if context.use_sparse:
            sparse_hits = self._sparse_search(query, limit=context.max_results)
            if sparse_hits:
                result_lists.append(("sparse", sparse_hits))

        # Strategy 3: Graph (Neo4j entity-linked traversal)
        if context.use_graph and context.entities:
            graph_hits = self._graph_search(context.entities, limit=context.max_results)
            if graph_hits:
                result_lists.append(("graph", graph_hits))

        # Strategy 4: Structured (SQL exact-match filters)
        if context.use_structured and context.filters:
            struct_hits = self._structured_search(context.filters, limit=context.max_results)
            if struct_hits:
                result_lists.append(("structured", struct_hits))

        if not result_lists:
            return []

        fused = rrf_merge(result_lists)
        return fused[: context.max_results]

    # ------------------------------------------------------------------
    # Strategy 1: Dense retrieval (Qdrant)
    # ------------------------------------------------------------------

    def _dense_search(self, query: str, limit: int = 10) -> list[RankedResult]:
        if not self._ensure_qdrant():
            return []

        try:
            query_embedding = self._embedding_svc.model.encode(
                query,
                convert_to_numpy=True,
                show_progress_bar=False,
            )
            hits = self._vector_store.search_similar(
                embedding=query_embedding,
                top_k=limit,
                min_score=0.25,
            )
        except Exception as exc:
            logger.warning("Dense search failed: %s", exc)
            return []

        results: list[RankedResult] = []
        for hit in hits:
            results.append(
                RankedResult(
                    anomaly_id=hit.detection_id,
                    user_id=hit.user_id,
                    timestamp=hit.timestamp.isoformat() if hit.timestamp else "",
                    severity=hit.metadata.get("severity", ""),
                    risk_score=hit.metadata.get("anomaly_score", 0.0),
                    similarity_score=hit.score,
                )
            )
        return results

    def _ensure_qdrant(self) -> bool:
        if self._qdrant_ready is not None:
            return self._qdrant_ready
        try:
            project_root = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
            if project_root not in sys.path:
                sys.path.insert(0, project_root)

            from modules.ai.embeddings.embedding_service import EmbeddingService
            from modules.ai.embeddings.vector_store import VectorStore

            self._embedding_svc = EmbeddingService()
            self._vector_store = VectorStore()
            self._qdrant_ready = True
        except Exception as exc:
            logger.warning("Qdrant unavailable: %s", exc)
            self._qdrant_ready = False
        return self._qdrant_ready

    # ------------------------------------------------------------------
    # Strategy 2: Sparse retrieval (PostgreSQL FTS)
    # ------------------------------------------------------------------

    def _sparse_search(self, query: str, limit: int = 10) -> list[RankedResult]:
        try:
            import psycopg2.extras
        except ImportError:
            logger.warning("psycopg2 not available for sparse search")
            return []

        try:
            with get_db() as conn:
                with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                    # Use plainto_tsquery for safe query parsing (no syntax errors)
                    cur.execute(
                        """
                        SELECT
                            ea.anomaly_id::text AS anomaly_id,
                            ea.user_id,
                            ea.timestamp,
                            ea.severity,
                            ROUND(ea.risk_score::numeric, 2)    AS risk_score,
                            ea.root_cause,
                            ea.sub_category,
                            ea.classification_reasoning,
                            ts_rank(ea.search_vector, plainto_tsquery('english', %s)) AS fts_rank
                        FROM enriched_anomalies ea
                        WHERE ea.search_vector @@ plainto_tsquery('english', %s)
                        ORDER BY fts_rank DESC, ea.risk_score DESC NULLS LAST
                        LIMIT %s
                        """,
                        (query, query, limit),
                    )
                    rows = cur.fetchall()
        except Exception as exc:
            logger.warning("Sparse FTS search failed: %s", exc)
            return []

        results: list[RankedResult] = []
        for row in rows:
            results.append(
                RankedResult(
                    anomaly_id=row["anomaly_id"],
                    user_id=row.get("user_id", ""),
                    timestamp=row["timestamp"].isoformat() if row.get("timestamp") else "",
                    severity=row.get("severity", ""),
                    risk_score=float(row.get("risk_score") or 0),
                    root_cause=row.get("root_cause", ""),
                    sub_category=row.get("sub_category", ""),
                    classification_reasoning=row.get("classification_reasoning", ""),
                    similarity_score=float(row.get("fts_rank", 0)),
                )
            )
        return results

    # ------------------------------------------------------------------
    # Strategy 3: Graph retrieval (Neo4j)
    # ------------------------------------------------------------------

    def _graph_search(self, entities: list[str], limit: int = 10) -> list[RankedResult]:
        if not self._ensure_neo4j():
            return []

        try:
            from neo4j import GraphDatabase
        except ImportError:
            return []

        uri = os.getenv("NEO4J_URI", "bolt://localhost:7687")
        user = os.getenv("NEO4J_USER", "neo4j")
        password = os.getenv("NEO4J_PASSWORD", "")
        database = os.getenv("NEO4J_DATABASE", "neo4j")

        try:
            driver = GraphDatabase.driver(uri, auth=(user, password))
            try:
                with driver.session(database=database) as session:
                    # Find detections connected to any of the specified entities
                    result = session.run(
                        """
                        MATCH (e)-[]-(d:Detection)-[:GENERATED]-(u:User)
                        WHERE e.name IN $entities OR e.user_id IN $entities
                           OR u.user_id IN $entities
                        RETURN DISTINCT
                            d.detection_id AS anomaly_id,
                            u.user_id      AS user_id,
                            d.timestamp    AS timestamp
                        LIMIT $limit
                        """,
                        entities=entities,
                        limit=limit,
                    )
                    records = [dict(r) for r in result]
            finally:
                driver.close()
        except Exception as exc:
            logger.warning("Graph search failed: %s", exc)
            return []

        # Hydrate from PostgreSQL for full details
        if not records:
            return []

        return self._hydrate_from_db([r["anomaly_id"] for r in records if r.get("anomaly_id")])

    def _ensure_neo4j(self) -> bool:
        if self._neo4j_available is not None:
            return self._neo4j_available
        try:
            from neo4j import GraphDatabase

            uri = os.getenv("NEO4J_URI", "bolt://localhost:7687")
            user = os.getenv("NEO4J_USER", "neo4j")
            password = os.getenv("NEO4J_PASSWORD", "")
            driver = GraphDatabase.driver(uri, auth=(user, password))
            driver.verify_connectivity()
            driver.close()
            self._neo4j_available = True
        except Exception as exc:
            logger.warning("Neo4j unavailable for graph search: %s", exc)
            self._neo4j_available = False
        return self._neo4j_available

    # ------------------------------------------------------------------
    # Strategy 4: Structured retrieval (SQL filters)
    # ------------------------------------------------------------------

    def _structured_search(self, filters: dict[str, Any], limit: int = 10) -> list[RankedResult]:
        try:
            import psycopg2.extras
        except ImportError:
            return []

        conditions: list[str] = []
        params: list[Any] = []

        if "severity" in filters:
            conditions.append("ea.severity = %s")
            params.append(filters["severity"])

        if "user_id" in filters:
            conditions.append("ea.user_id = %s")
            params.append(filters["user_id"])

        if "days" in filters:
            conditions.append(f"ea.timestamp >= NOW() - INTERVAL '{int(filters['days'])} days'")

        if "root_cause" in filters:
            conditions.append("ea.root_cause ILIKE %s")
            params.append(f"%{filters['root_cause']}%")

        if not conditions:
            return []

        where_clause = "WHERE " + " AND ".join(conditions)
        params.append(limit)

        try:
            with get_db() as conn:
                with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                    cur.execute(
                        f"""
                        SELECT
                            ea.anomaly_id::text AS anomaly_id,
                            ea.user_id,
                            ea.timestamp,
                            ea.severity,
                            ROUND(ea.risk_score::numeric, 2) AS risk_score,
                            ea.root_cause,
                            ea.sub_category,
                            ea.classification_reasoning
                        FROM enriched_anomalies ea
                        {where_clause}
                        ORDER BY ea.risk_score DESC NULLS LAST, ea.timestamp DESC
                        LIMIT %s
                        """,
                        params,
                    )
                    rows = cur.fetchall()
        except Exception as exc:
            logger.warning("Structured search failed: %s", exc)
            return []

        results: list[RankedResult] = []
        for row in rows:
            results.append(
                RankedResult(
                    anomaly_id=row["anomaly_id"],
                    user_id=row.get("user_id", ""),
                    timestamp=row["timestamp"].isoformat() if row.get("timestamp") else "",
                    severity=row.get("severity", ""),
                    risk_score=float(row.get("risk_score") or 0),
                    root_cause=row.get("root_cause", ""),
                    sub_category=row.get("sub_category", ""),
                    classification_reasoning=row.get("classification_reasoning", ""),
                )
            )
        return results

    # ------------------------------------------------------------------
    # Hydration helper
    # ------------------------------------------------------------------

    def _hydrate_from_db(self, anomaly_ids: list[str]) -> list[RankedResult]:
        """Fetch full anomaly records from PostgreSQL by ID list."""
        if not anomaly_ids:
            return []

        try:
            import psycopg2.extras
        except ImportError:
            return []

        try:
            with get_db() as conn:
                with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                    cur.execute(
                        """
                        SELECT
                            ea.anomaly_id::text AS anomaly_id,
                            ea.user_id,
                            ea.timestamp,
                            ea.severity,
                            ROUND(ea.risk_score::numeric, 2) AS risk_score,
                            ea.root_cause,
                            ea.sub_category,
                            ea.classification_reasoning
                        FROM enriched_anomalies ea
                        WHERE ea.anomaly_id::text = ANY(%s)
                        """,
                        (anomaly_ids,),
                    )
                    rows = cur.fetchall()
        except Exception as exc:
            logger.warning("Hydration query failed: %s", exc)
            return []

        return [
            RankedResult(
                anomaly_id=row["anomaly_id"],
                user_id=row.get("user_id", ""),
                timestamp=row["timestamp"].isoformat() if row.get("timestamp") else "",
                severity=row.get("severity", ""),
                risk_score=float(row.get("risk_score") or 0),
                root_cause=row.get("root_cause", ""),
                sub_category=row.get("sub_category", ""),
                classification_reasoning=row.get("classification_reasoning", ""),
            )
            for row in rows
        ]
