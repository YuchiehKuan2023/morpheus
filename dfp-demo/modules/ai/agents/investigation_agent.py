"""
InvestigationAgent — finds similar historical detections and identifies attack patterns.

Given a trigger anomaly, the agent:
  1. Confirms the anomaly exists in PostgreSQL (anomaly_id == Qdrant point ID).
  2. Retrieves the stored embedding from Qdrant and runs a KNN similarity search.
  3. Fetches matching PostgreSQL rows for enrichment (timestamp, user, root_cause).
  4. Analyses patterns: dominant root cause and /24 subnet recurrence.
  5. Calls the LLM with an investigation prompt to produce a pattern-analysis narrative.
  6. Returns a structured AgentResult.

Constructor:
    InvestigationAgent(db_url, qdrant_client, llm_service)

Output shape (stored in agent_findings.result / AgentResult.result):
    {
        "similar_detections": [{"anomaly_id", "similarity", "date", "user_id", "root_cause"}],
        "recurrence_detected": bool,
        "recurrence_count":    int,
        "first_seen":          str,   # ISO-8601 timestamp of oldest similar hit
        "dominant_root_cause": str,
        "pattern_analysis":    str,   # LLM narrative
        "confidence":          float,
    }
"""

from __future__ import annotations

import logging
from collections import Counter
from typing import Any

import psycopg2
import psycopg2.extras

from modules.ai.agents.base_agent import AgentResult, AgentTask, BaseAgent
from modules.ai.agents.prompts.investigation_prompt import SYSTEM_PROMPT, build_user_prompt
from modules.ai.llm.llm_service import LLMService

logger = logging.getLogger(__name__)

# Qdrant collection — must match VectorStore default (modules/ai/embeddings/vector_store.py).
_QDRANT_COLLECTION = "dfp_detections"

# Return top-10 nearest neighbours (excluding the query point itself).
_KNN_LIMIT = 10

# /24 subnet hits needed to flag recurrence.
_RECURRENCE_THRESHOLD = 3


class InvestigationAgent(BaseAgent):
    """Investigation agent: KNN similarity search + LLM pattern analysis."""

    TIMEOUT_SECONDS = 60

    def __init__(
        self,
        db_url: str,
        qdrant_client: Any,
        llm_service: LLMService,
    ) -> None:
        self._db_url = db_url
        self._qdrant_client = qdrant_client
        self._llm_service = llm_service

    @property
    def agent_type(self) -> str:
        return "investigation"

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _fetch_vector_id(self, anomaly_id: str) -> str | None:
        """Confirm anomaly exists in DB; return the anomaly_id as the Qdrant point ID.

        The Qdrant point ID is the PostgreSQL anomaly_id UUID (see vector_store.py).
        This method verifies the row exists before attempting a Qdrant lookup.
        """
        sql = "SELECT anomaly_id FROM enriched_anomalies WHERE anomaly_id = %s"
        with psycopg2.connect(self._db_url) as conn:
            with conn.cursor() as cur:
                cur.execute(sql, (anomaly_id,))
                row = cur.fetchone()
        return str(row[0]) if row else None

    def _qdrant_knn(self, vector_id: str) -> list[dict[str, Any]]:
        """Retrieve the stored embedding for *vector_id* then return the top-K
        nearest neighbours, excluding the query point itself.

        Each item in the returned list has:
            "anomaly_id":  str  — Qdrant point ID (= PG anomaly_id)
            "similarity":  float
            "ip_address":  str  — from Qdrant payload (may be empty)
        """
        # Retrieve the query vector from Qdrant.
        points = self._qdrant_client.retrieve(
            collection_name=_QDRANT_COLLECTION,
            ids=[vector_id],
            with_vectors=True,
            with_payload=False,
        )
        if not points:
            logger.warning("[investigation] No Qdrant point for vector_id=%s", vector_id)
            return []

        query_vector = points[0].vector

        # KNN search — fetch one extra so we can drop the query point itself.
        # qdrant-client >= 1.8 replaced .search() with .query_points().
        results = self._qdrant_client.query_points(
            collection_name=_QDRANT_COLLECTION,
            query=query_vector,
            limit=_KNN_LIMIT + 1,
            with_payload=True,
        ).points

        neighbours: list[dict[str, Any]] = []
        for r in results:
            point_id = str(r.id)
            if point_id == vector_id:
                continue  # exclude self
            ip_address = (r.payload or {}).get("ip_address", "")
            neighbours.append(
                {
                    "anomaly_id": point_id,
                    "similarity": float(r.score),
                    "ip_address": ip_address,
                }
            )
            if len(neighbours) >= _KNN_LIMIT:
                break

        return neighbours

    def _fetch_pg_records(self, anomaly_ids: list[str]) -> list[dict[str, Any]]:
        """Batch-fetch enriched_anomalies rows for the given anomaly IDs."""
        if not anomaly_ids:
            return []
        placeholders = ", ".join(["%s"] * len(anomaly_ids))
        sql = (
            f"SELECT anomaly_id, timestamp, user_id, root_cause "
            f"FROM enriched_anomalies WHERE anomaly_id IN ({placeholders})"
        )
        with psycopg2.connect(self._db_url) as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(sql, anomaly_ids)
                rows = cur.fetchall()
        return [dict(r) for r in rows]

    def _analyse_patterns(
        self,
        knn_hits: list[dict[str, Any]],
        pg_records: list[dict[str, Any]],
    ) -> tuple[str, bool, int, str]:
        """Analyse similar-detection patterns.

        Returns:
            dominant_root_cause: most common root_cause label
            recurrence_detected: True if ≥3 hits share a /24 subnet
            recurrence_count:    total number of similar hits
            first_seen:          ISO timestamp of the oldest similar hit
        """
        if not pg_records:
            return "Unknown", False, 0, ""

        # Index PG records by anomaly_id for O(1) lookups.
        pg_by_id: dict[str, dict] = {str(r["anomaly_id"]): r for r in pg_records}

        # Build enriched list preserving KNN similarity order.
        enriched: list[dict[str, Any]] = []
        for hit in knn_hits:
            aid = hit["anomaly_id"]
            pg = pg_by_id.get(aid, {})
            enriched.append(
                {
                    "anomaly_id": aid,
                    "ip_address": hit.get("ip_address", ""),
                    "timestamp": pg.get("timestamp"),
                    "user_id": str(pg.get("user_id", "")),
                    "root_cause": str(pg.get("root_cause") or "Unknown"),
                }
            )

        # Dominant root cause.
        root_causes = [e["root_cause"] for e in enriched]
        dominant_root_cause = Counter(root_causes).most_common(1)[0][0]

        # /24 subnet recurrence check using Qdrant payload ip_address.
        subnet_counts: Counter = Counter()
        for e in enriched:
            ip = e["ip_address"]
            if ip:
                parts = ip.split(".")
                if len(parts) == 4:
                    subnet = ".".join(parts[:3])
                    subnet_counts[subnet] += 1
        recurrence_detected = any(count >= _RECURRENCE_THRESHOLD for count in subnet_counts.values())

        # Oldest timestamp across all similar hits.
        timestamps = [e["timestamp"] for e in enriched if e["timestamp"] is not None]
        first_seen = ""
        if timestamps:
            earliest = min(timestamps)
            first_seen = earliest.isoformat() if hasattr(earliest, "isoformat") else str(earliest)

        return dominant_root_cause, recurrence_detected, len(enriched), first_seen

    def _score_confidence(
        self,
        similar: list[dict[str, Any]],
        recurrence: bool,
    ) -> float:
        """Confidence grows with the number of matches and the recurrence signal."""
        return min(
            1.0,
            0.4 + len(similar) / 10 * 0.4 + (0.2 if recurrence else 0.0),
        )

    # ------------------------------------------------------------------
    # Main execution
    # ------------------------------------------------------------------

    def _execute(self, task: AgentTask) -> AgentResult:
        anomaly_id = task.anomaly_id

        # 1. Confirm existence in DB (also produces the Qdrant point ID).
        vector_id = self._fetch_vector_id(anomaly_id)
        if vector_id is None:
            logger.warning("[investigation] No DB row for anomaly_id=%s", anomaly_id)
            return AgentResult(
                agent_type="investigation",
                status="failed",
                result={},
                confidence=0.0,
                error=f"anomaly_id {anomaly_id} not found in DB",
            )

        # 2. KNN similarity search via Qdrant.
        knn_hits = self._qdrant_knn(vector_id)

        # 3. Enrich with PostgreSQL records.
        neighbour_ids = [h["anomaly_id"] for h in knn_hits]
        pg_records = self._fetch_pg_records(neighbour_ids)

        # 4. Pattern analysis.
        dominant_root_cause, recurrence_detected, recurrence_count, first_seen = self._analyse_patterns(
            knn_hits, pg_records
        )

        # Build similar_detections list (output format).
        pg_by_id = {str(r["anomaly_id"]): r for r in pg_records}
        similar_detections: list[dict[str, Any]] = []
        for hit in knn_hits:
            aid = hit["anomaly_id"]
            pg = pg_by_id.get(aid, {})
            ts = pg.get("timestamp")
            similar_detections.append(
                {
                    "anomaly_id": aid,
                    "similarity": hit["similarity"],
                    "date": (ts.isoformat() if ts and hasattr(ts, "isoformat") else str(ts or "")),
                    "user_id": str(pg.get("user_id", "")),
                    "root_cause": str(pg.get("root_cause") or "Unknown"),
                }
            )

        # 5. LLM pattern-analysis narrative.
        pattern_analysis = ""
        llm_tokens = 0
        try:
            user_prompt = build_user_prompt(
                similar_detections=similar_detections,
                dominant_root_cause=dominant_root_cause,
                recurrence_count=recurrence_count,
            )
            pattern_analysis, llm_tokens = self._llm_service.chat(SYSTEM_PROMPT, user_prompt)
        except Exception:
            logger.exception("[investigation] LLM call failed")

        # 6. Confidence score.
        confidence = self._score_confidence(similar_detections, recurrence_detected)

        result: dict[str, Any] = {
            "similar_detections": similar_detections,
            "recurrence_detected": recurrence_detected,
            "recurrence_count": recurrence_count,
            "first_seen": first_seen,
            "dominant_root_cause": dominant_root_cause,
            "pattern_analysis": pattern_analysis,
            "confidence": confidence,
        }

        return AgentResult(
            agent_type="investigation",
            status="complete",
            result=result,
            confidence=confidence,
            llm_tokens_used=llm_tokens,
        )
