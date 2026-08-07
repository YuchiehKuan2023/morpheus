"""
Unit tests for modules/ai/agents/forensics_agent.py

psycopg2 is stubbed at the module level by conftest.py.
ForensicsAgent is constructed with mock DB connection, mock Neo4j driver,
and mock LLMService — no real infrastructure is required.

Covers (9 test cases from plan):
    test_event_chain_empty_user       — DB returns zero rows → chain==[], status==complete
    test_event_chain_populated        — DB returns 5 rows → len==5, oldest-first order
    test_escalation_detection         — 2 events within 2h, rising score → lateral_movement==True
    test_no_escalation                — events 24h apart → lateral_movement==False
    test_neo4j_entities               — driver returns 3 records → 3 entity strings
    test_neo4j_failure                — driver.session raises → agent still completes, entities==[]
    test_llm_narrative                — llm_service.chat returns fixed string → narrative matches
    test_confidence_scoring           — 10 events + 5 entities → confidence in [0.0, 1.0]
    test_base_run_wraps_errors        — _execute raises → status==failed, error set

Author: Tomasz Zabek <tzabek@deloitte.co.uk>
Date: 2026-03-23
"""

from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).parents[3]))

from modules.ai.agents.base_agent import AgentTask
from modules.ai.agents.forensics_agent import ForensicsAgent

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

USER_ID = "alice@example.com"
ANOMALY_ID = "aaaaaaaa-0000-0000-0000-000000000001"
INV_ID = "inv-test-001"

_BASE_ANOMALY = {
    "anomaly_id": ANOMALY_ID,
    "user_id": USER_ID,
    "anomaly_score": 4.2,
    "root_cause": "Credential Stuffing",
    "severity": "HIGH",
}

_BASE_TASK = AgentTask(
    investigation_id=INV_ID,
    anomaly_id=ANOMALY_ID,
    anomaly_data=_BASE_ANOMALY,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_NOW = datetime(2026, 3, 23, 12, 0, 0, tzinfo=timezone.utc)


def _make_db_row(offset_hours: int, root_cause: str = "Credential Stuffing", score: float = 3.0) -> MagicMock:
    """Return a MagicMock that behaves like a RealDictCursor row for key access."""
    row = MagicMock()
    row.__getitem__.side_effect = lambda k: {
        "timestamp": _NOW - timedelta(hours=offset_hours),
        "root_cause": root_cause,
        "anomaly_score": score,
    }[k]
    return row


def _make_agent(
    db_rows: list,
    neo4j_records: list | None = None,
    llm_narrative: str = "The attack began with credential stuffing.",
    llm_tokens: int = 42,
) -> tuple[ForensicsAgent, MagicMock, MagicMock, MagicMock]:
    """
    Build a ForensicsAgent with fully mocked dependencies.

    Returns (agent, mock_conn, mock_neo4j_driver, mock_llm).
    """
    # --- DB mock ---
    mock_conn = MagicMock()
    mock_cursor = MagicMock()
    mock_cursor.fetchall.return_value = db_rows
    mock_conn.cursor.return_value.__enter__ = MagicMock(return_value=mock_cursor)
    mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=False)

    # --- Neo4j mock ---
    mock_driver = MagicMock()
    if neo4j_records is None:
        neo4j_records = []
    mock_session = MagicMock()
    mock_session.__enter__ = MagicMock(return_value=mock_session)
    mock_session.__exit__ = MagicMock(return_value=False)
    mock_session.run.return_value = neo4j_records
    mock_driver.session.return_value = mock_session

    # --- LLM mock ---
    mock_llm = MagicMock()
    mock_llm.chat.return_value = (llm_narrative, llm_tokens)

    with patch("modules.ai.agents.forensics_agent.psycopg2.connect", return_value=mock_conn):
        agent = ForensicsAgent(
            db_url="postgresql://mock/mock",
            neo4j_driver=mock_driver,
            llm_service=mock_llm,
        )

    return agent, mock_conn, mock_driver, mock_llm


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestForensicsAgentEventChain:
    def test_event_chain_empty_user(self):
        """DB returns zero rows → attack_chain is empty, status is complete."""
        agent, *_ = _make_agent(db_rows=[])

        result = agent.run(_BASE_TASK)

        assert result.status == "complete"
        assert result.result["attack_chain"] == []
        assert result.result["entry_point"] == ""

    def test_event_chain_populated(self):
        """DB returns 5 rows (descending) → agent reverses to chronological order."""
        # Rows as DB returns them: newest first (offset 0 = most recent)
        rows = [
            _make_db_row(offset_hours=i, score=float(i + 1))
            for i in range(5)  # offsets 0,1,2,3,4 → newest first
        ]
        agent, *_ = _make_agent(db_rows=rows)

        result = agent.run(_BASE_TASK)

        chain = result.result["attack_chain"]
        assert len(chain) == 5
        # After reversal, the oldest event (offset=4h) should come first
        ts_first = datetime.fromisoformat(chain[0]["ts"])
        ts_last = datetime.fromisoformat(chain[-1]["ts"])
        assert ts_first < ts_last, "Chain should be ordered oldest → newest"


class TestForensicsAgentEscalation:
    def test_escalation_detection(self):
        """Two events within 2h with rising score → lateral_movement_detected==True."""
        # DB returns ORDER BY timestamp DESC: newest row first, oldest row second.
        # After _build_event_chain reverses, chain is oldest→newest with rising score.
        rows = [
            _make_db_row(offset_hours=1, score=4.5),  # newer — returned first by DESC
            _make_db_row(offset_hours=2, score=3.0),  # older — returned second by DESC
        ]
        agent, *_ = _make_agent(db_rows=rows)

        result = agent.run(_BASE_TASK)

        assert result.result["lateral_movement_detected"] is True

    def test_no_escalation(self):
        """Events spread >2h apart → lateral_movement_detected==False."""
        # DB returns ORDER BY timestamp DESC: newest row first, oldest row second.
        rows = [
            _make_db_row(offset_hours=1, score=4.5),  # newer — returned first by DESC
            _make_db_row(offset_hours=25, score=3.0),  # older — returned second by DESC; gap > 2h window
        ]
        agent, *_ = _make_agent(db_rows=rows)

        result = agent.run(_BASE_TASK)

        assert result.result["lateral_movement_detected"] is False


class TestForensicsAgentNeo4j:
    def test_neo4j_entities(self):
        """Neo4j returns 3 records → entities_involved has 3 strings."""
        neo4j_records = [
            {"entity": "IP:10.0.0.1"},
            {"entity": "Device:LAPTOP-WIN-01"},
            {"entity": "App:SharePoint"},
        ]
        agent, *_ = _make_agent(db_rows=[], neo4j_records=neo4j_records)

        result = agent.run(_BASE_TASK)

        assert result.result["entities_involved"] == [
            "IP:10.0.0.1",
            "Device:LAPTOP-WIN-01",
            "App:SharePoint",
        ]

    def test_neo4j_failure(self):
        """Driver.session raises → agent still completes with entities_involved==[]."""
        agent, _, mock_driver, _ = _make_agent(db_rows=[])
        mock_driver.session.side_effect = RuntimeError("Neo4j unavailable")

        result = agent.run(_BASE_TASK)

        assert result.status == "complete"
        assert result.result["entities_involved"] == []


class TestForensicsAgentLLM:
    def test_llm_narrative(self):
        """LLM chat() return value is stored verbatim in result["narrative"]."""
        narrative = "The attacker exploited stolen credentials to access SharePoint."
        agent, *_ = _make_agent(db_rows=[], llm_narrative=narrative, llm_tokens=88)

        result = agent.run(_BASE_TASK)

        assert result.result["narrative"] == narrative
        assert result.llm_tokens_used == 88


class TestForensicsAgentConfidence:
    def test_confidence_scoring(self):
        """10 events + 5 entities → confidence is within [0.0, 1.0]."""
        rows = [_make_db_row(offset_hours=i) for i in range(10)]
        neo4j_records = [{"entity": f"IP:10.0.0.{i}"} for i in range(5)]
        agent, *_ = _make_agent(db_rows=rows, neo4j_records=neo4j_records)

        result = agent.run(_BASE_TASK)

        confidence = result.confidence
        assert 0.0 <= confidence <= 1.0

    def test_confidence_formula(self):
        """Verify the exact formula: min(1.0, 0.3 + chain/50*0.4 + entities/20*0.3)."""
        # 10 events, 5 entities
        # 0.3 + 10/50*0.4 + 5/20*0.3 = 0.3 + 0.08 + 0.075 = 0.455
        rows = [_make_db_row(offset_hours=i) for i in range(10)]
        neo4j_records = [{"entity": f"IP:10.0.0.{i}"} for i in range(5)]
        agent, *_ = _make_agent(db_rows=rows, neo4j_records=neo4j_records)

        result = agent.run(_BASE_TASK)

        assert abs(result.confidence - 0.455) < 0.001


class TestForensicsAgentErrorHandling:
    def test_base_run_wraps_errors(self):
        """If _execute raises, BaseAgent.run catches it → status==failed, error set."""
        agent, *_ = _make_agent(db_rows=[])

        with patch.object(agent, "_execute", side_effect=RuntimeError("DB exploded")):
            result = agent.run(_BASE_TASK)

        assert result.status == "failed"
        assert result.error is not None
        assert "DB exploded" in result.error
        assert result.result == {}
