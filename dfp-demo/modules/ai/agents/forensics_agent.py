"""
ForensicsAgent — reconstructs the attack sequence for a single anomaly.

Given a trigger anomaly, the agent:
  1. Builds a 30-day event chain for the affected user from enriched_anomalies.
  2. Detects escalation: pairs of events within 2 h with an increasing anomaly_score.
  3. Queries Neo4j for connected entities (IPs, devices, apps) up to 3 hops.
  4. Calls the LLM with a tailored forensics prompt to produce a narrative.
  5. Returns a structured AgentResult with all findings.

Constructor:
    ForensicsAgent(db_url, neo4j_driver, llm_service)

Output shape (stored in agent_findings.result / AgentResult.result):
    {
        "attack_chain":              list[{ts, event_type, significance}],
        "entry_point":               str,   # event_type of the earliest event
        "lateral_movement_detected": bool,
        "entities_involved":         list[str],
        "narrative":                 str,
        "confidence":                float,
    }
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

import psycopg2
import psycopg2.extras

from modules.ai.agents.base_agent import AgentResult, AgentTask, BaseAgent
from modules.ai.agents.prompts.forensics_prompt import SYSTEM_PROMPT, build_user_prompt
from modules.ai.llm.llm_service import LLMService

logger = logging.getLogger(__name__)

# How far back to search for related events.
_LOOKBACK_DAYS = 30
# Max rows fetched from DB per user (per plan).
_MAX_CHAIN_ROWS = 50
# Two events within this window with rising score → escalation.
_ESCALATION_WINDOW_SECONDS = 2 * 3600


class ForensicsAgent(BaseAgent):
    """Forensics agent: reconstructs attack chain and produces LLM narrative."""

    TIMEOUT_SECONDS = 60  # LLM + DB + Neo4j can be slow

    def __init__(
        self,
        db_url: str,
        neo4j_driver: Any,
        llm_service: LLMService,
    ) -> None:
        """
        Args:
            db_url:        libpq connection string for PostgreSQL.
            neo4j_driver:  A neo4j.GraphDatabase driver instance (or compatible mock).
            llm_service:   Initialised LLMService for narrative generation.
        """
        self._conn = psycopg2.connect(db_url)
        self._neo4j_driver = neo4j_driver
        self._llm_service = llm_service
        logger.info("ForensicsAgent initialised")

    # ------------------------------------------------------------------
    # BaseAgent contract
    # ------------------------------------------------------------------

    @property
    def agent_type(self) -> str:
        return "forensics"

    def _execute(self, task: AgentTask) -> AgentResult:
        """Orchestrate event-chain → escalation → entities → LLM → result."""
        anomaly_data = task.anomaly_data
        user_id: str = anomaly_data.get("user_id", "")

        # 1. Build event chain
        event_chain = self._build_event_chain(user_id)

        # 2. Detect escalation and annotate chain
        lateral_movement = self._detect_escalation(event_chain)

        # 3. Query Neo4j for connected entities
        entities = self._query_neo4j_entities(user_id)

        # 4. Compute confidence
        confidence = self._score_confidence(event_chain, entities)

        # 5. Call LLM for forensic narrative
        narrative, tokens_used = self._generate_narrative(user_id, event_chain, entities, anomaly_data)

        result_payload = {
            "attack_chain": [
                {
                    "ts": e["ts"],
                    "event_type": e["event_type"],
                    "significance": e.get("significance", ""),
                }
                for e in event_chain
            ],
            "entry_point": event_chain[0]["event_type"] if event_chain else "",
            "lateral_movement_detected": lateral_movement,
            "entities_involved": entities,
            "narrative": narrative,
            "confidence": confidence,
        }

        return AgentResult(
            agent_type=self.agent_type,
            status="complete",
            result=result_payload,
            confidence=confidence,
            llm_tokens_used=tokens_used,
        )

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _build_event_chain(self, user_id: str) -> list[dict[str, Any]]:
        """
        Fetch up to _MAX_CHAIN_ROWS anomaly records for *user_id* over the
        last _LOOKBACK_DAYS days, ordered oldest → newest.

        Returns a list of dicts with keys: ts, event_type, anomaly_score, significance.
        """
        cutoff = datetime.now(timezone.utc) - timedelta(days=_LOOKBACK_DAYS)
        query = """
            SELECT timestamp, root_cause, anomaly_score
            FROM   enriched_anomalies
            WHERE  user_id = %s
              AND  timestamp >= %s
              AND  is_anomaly = TRUE
            ORDER  BY timestamp DESC
            LIMIT  %s
        """
        with self._conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(query, (user_id, cutoff, _MAX_CHAIN_ROWS))
            rows = cur.fetchall()

        # Reverse so the chain runs oldest → newest
        chain = []
        for row in reversed(rows):
            ts = row["timestamp"]
            if hasattr(ts, "isoformat"):
                ts = ts.isoformat()
            chain.append(
                {
                    "ts": ts,
                    "event_type": row["root_cause"] or "Unknown",
                    "anomaly_score": float(row["anomaly_score"] or 0.0),
                    "significance": "",
                }
            )
        return chain

    def _detect_escalation(self, event_chain: list[dict[str, Any]]) -> bool:
        """
        Sliding-window escalation detection.

        For every pair of events where the second falls within
        _ESCALATION_WINDOW_SECONDS of the first and has a strictly higher
        anomaly_score, mark both events' significance and return True.

        Returns:
            True if at least one escalating pair is found, False otherwise.
        """
        escalation_found = False
        for i in range(len(event_chain) - 1):
            a = event_chain[i]
            b = event_chain[i + 1]
            try:
                ts_a = datetime.fromisoformat(a["ts"]) if isinstance(a["ts"], str) else a["ts"]
                ts_b = datetime.fromisoformat(b["ts"]) if isinstance(b["ts"], str) else b["ts"]
                # Normalise to UTC-aware for comparison
                if ts_a.tzinfo is None:
                    ts_a = ts_a.replace(tzinfo=timezone.utc)
                if ts_b.tzinfo is None:
                    ts_b = ts_b.replace(tzinfo=timezone.utc)
            except (ValueError, AttributeError):
                continue

            delta_seconds = (ts_b - ts_a).total_seconds()
            if 0 <= delta_seconds <= _ESCALATION_WINDOW_SECONDS and b["anomaly_score"] > a["anomaly_score"]:
                escalation_found = True
                if not a["significance"]:
                    a["significance"] = "Escalation trigger"
                b["significance"] = "Score escalation (+{:.2f} in {:.0f}m)".format(
                    b["anomaly_score"] - a["anomaly_score"],
                    delta_seconds / 60,
                )

        return escalation_found

    def _query_neo4j_entities(self, user_id: str) -> list[str]:
        """
        Return up to 20 distinct entity strings connected to *user_id*
        within 3 hops in the graph.

        Format: "<Label>:<name>" e.g. "IP:10.0.0.1", "Device:LAPTOP-WIN-01"

        Falls back to [] if Neo4j is unavailable.
        """
        cypher = (
            "MATCH (u:User {id: $user_id})-[*1..3]-(e) RETURN DISTINCT labels(e)[0] + ':' + e.name AS entity LIMIT 20"
        )
        try:
            with self._neo4j_driver.session() as session:
                result = session.run(cypher, user_id=user_id)
                return [record["entity"] for record in result if record["entity"]]
        except Exception as exc:
            logger.warning("[forensics] Neo4j query failed for user=%s: %s", user_id, exc)
            return []

    @staticmethod
    def _score_confidence(event_chain: list[dict], entities: list[str]) -> float:
        """
        Heuristic confidence based on chain depth and entity richness.

        Formula (from architecture doc):
            min(1.0, 0.3 + len(chain)/50 * 0.4 + len(entities)/20 * 0.3)
        """
        return min(1.0, 0.3 + len(event_chain) / _MAX_CHAIN_ROWS * 0.4 + len(entities) / 20 * 0.3)

    def _generate_narrative(
        self,
        user_id: str,
        event_chain: list[dict],
        entities: list[str],
        anomaly: dict,
    ) -> tuple[str, int]:
        """
        Call the LLM with the forensics prompt and return (narrative, tokens_used).
        """
        user_prompt = build_user_prompt(
            user_id=user_id,
            event_chain=event_chain,
            entities=entities,
            anomaly=anomaly,
        )
        return self._llm_service.chat(SYSTEM_PROMPT, user_prompt)

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def close(self) -> None:
        """Release the DB connection."""
        self._conn.close()
        logger.info("ForensicsAgent DB connection closed")

    def __enter__(self) -> ForensicsAgent:
        return self

    def __exit__(self, *_: Any) -> None:
        self.close()
