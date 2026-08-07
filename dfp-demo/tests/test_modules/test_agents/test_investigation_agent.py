"""
Unit tests for InvestigationAgent (Step 19.1).

All DB and Qdrant calls are mocked so no real infrastructure is needed.

Test classes:
    TestInvestigationAgentNoVector   — DB lookup failure path
    TestInvestigationAgentKNN        — happy-path KNN similarity results
    TestInvestigationAgentRecurrence — /24 subnet recurrence detection
    TestInvestigationAgentQdrantFail — Qdrant retrieve failure
    TestInvestigationAgentConfidence — confidence formula bounds
"""

from __future__ import annotations

import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# Ensure project root is on sys.path so `modules.*` imports resolve reliably.
_ROOT = Path(__file__).parents[3]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from modules.ai.agents.base_agent import AgentTask  # noqa: E402
from modules.ai.agents.investigation_agent import InvestigationAgent  # noqa: E402

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_DB_URL = "postgresql://test:test@localhost:5432/test"
_ANOMALY_ID = str(uuid.uuid4())


def _make_agent(db_rows=None, qdrant_retrieve=None, qdrant_search=None, llm_response=None):
    """Build an InvestigationAgent with fully mocked dependencies."""
    qdrant_client = MagicMock()

    # Default: retrieve returns empty list (not found)
    if qdrant_retrieve is not None:
        qdrant_client.retrieve.return_value = qdrant_retrieve
    else:
        qdrant_client.retrieve.return_value = []

    mock_qp = MagicMock()
    mock_qp.points = qdrant_search if qdrant_search is not None else []
    qdrant_client.query_points.return_value = mock_qp

    llm_service = MagicMock()
    llm_service.chat.return_value = (
        llm_response if llm_response is not None else "Pattern: isolated incident.",
        42,
    )

    agent = InvestigationAgent(
        db_url=_DB_URL,
        qdrant_client=qdrant_client,
        llm_service=llm_service,
    )
    return agent, qdrant_client, llm_service


def _make_task(anomaly_id: str = _ANOMALY_ID) -> AgentTask:
    return AgentTask(
        investigation_id=str(uuid.uuid4()),
        anomaly_id=anomaly_id,
        anomaly_data={"anomaly_id": anomaly_id, "user_id": "user@example.com"},
    )


def _make_pg_row(anomaly_id: str, ip: str = "10.0.1.5") -> tuple:
    """Return a fake Qdrant search result object."""
    r = MagicMock()
    r.id = anomaly_id
    r.score = 0.92
    r.payload = {"ip_address": ip}
    return r


# ---------------------------------------------------------------------------
# TestInvestigationAgentNoVector
# ---------------------------------------------------------------------------


class TestInvestigationAgentNoVector:
    """Agent returns status='failed' when the anomaly_id does not exist in DB."""

    def test_no_vector_id(self):
        agent, _, _ = _make_agent()
        task = _make_task()

        # DB returns no row for the anomaly.
        with patch("psycopg2.connect") as mock_conn:
            mock_cur = MagicMock()
            mock_cur.fetchone.return_value = None
            mock_conn.return_value.__enter__.return_value.cursor.return_value.__enter__.return_value = mock_cur

            result = agent.run(task)

        assert result.status == "failed"
        assert result.confidence == 0.0
        assert task.anomaly_id in (result.error or "")


# ---------------------------------------------------------------------------
# TestInvestigationAgentKNN
# ---------------------------------------------------------------------------


class TestInvestigationAgentKNN:
    """Happy-path: Qdrant returns two matching neighbours."""

    def _make_qdrant_retrieve(self):
        point = MagicMock()
        point.vector = [0.1] * 384
        return [point]

    def _make_qdrant_search(self, neighbour_ids: list[str], ips: list[str]):
        results = []
        for aid, ip in zip(neighbour_ids, ips, strict=False):
            r = MagicMock()
            r.id = aid
            r.score = 0.88
            r.payload = {"ip_address": ip}
            results.append(r)
        return results

    def _make_pg_records(self, anomaly_ids: list[str]):
        rows = []
        for aid in anomaly_ids:
            rows.append(
                {
                    "anomaly_id": aid,
                    "timestamp": datetime(2024, 3, 1, 10, 0, tzinfo=timezone.utc),
                    "user_id": "alice@example.com",
                    "root_cause": "Brute Force",
                }
            )
        return rows

    def test_qdrant_returns_matches(self):
        neighbour_ids = [str(uuid.uuid4()), str(uuid.uuid4())]

        agent, qdrant, _ = _make_agent(
            qdrant_retrieve=self._make_qdrant_retrieve(),
            qdrant_search=self._make_qdrant_search(neighbour_ids, ["192.168.1.5", "10.0.2.9"]),
        )
        task = _make_task()

        pg_rows_return = self._make_pg_records(neighbour_ids)

        with patch("psycopg2.connect") as mock_conn:
            mock_cur = MagicMock()
            # First call: _fetch_vector_id → returns DB row
            # Second call: _fetch_pg_records → returns neighbour rows
            mock_cur.fetchone.return_value = (_ANOMALY_ID,)
            mock_cur.fetchall.return_value = pg_rows_return
            mock_conn.return_value.__enter__.return_value.cursor.return_value.__enter__.return_value = mock_cur

            result = agent.run(task)

        assert result.status == "complete"
        assert len(result.result["similar_detections"]) == 2
        assert result.result["dominant_root_cause"] == "Brute Force"
        assert result.confidence > 0.0


# ---------------------------------------------------------------------------
# TestInvestigationAgentRecurrence
# ---------------------------------------------------------------------------


class TestInvestigationAgentRecurrence:
    """Recurrence detection based on /24 subnet grouping."""

    def _retrieve_point(self):
        point = MagicMock()
        point.vector = [0.2] * 384
        return [point]

    def _search_results(self, ids: list[str], ips: list[str]):
        hits = []
        for aid, ip in zip(ids, ips, strict=False):
            r = MagicMock()
            r.id = aid
            r.score = 0.85
            r.payload = {"ip_address": ip}
            hits.append(r)
        return hits

    def test_recurrence_detected(self):
        """Three or more hits sharing a /24 subnet → recurrence_detected=True."""
        n_ids = [str(uuid.uuid4()) for _ in range(3)]
        # All from 192.168.5.x → same /24
        ips = ["192.168.5.10", "192.168.5.20", "192.168.5.30"]

        agent, _, _ = _make_agent(
            qdrant_retrieve=self._retrieve_point(),
            qdrant_search=self._search_results(n_ids, ips),
        )
        task = _make_task()

        pg_rows = [
            {
                "anomaly_id": aid,
                "timestamp": datetime(2024, 4, 1, tzinfo=timezone.utc),
                "user_id": "bob@example.com",
                "root_cause": "Account Takeover",
            }
            for aid in n_ids
        ]

        with patch("psycopg2.connect") as mock_conn:
            mock_cur = MagicMock()
            mock_cur.fetchone.return_value = (_ANOMALY_ID,)
            mock_cur.fetchall.return_value = pg_rows
            mock_conn.return_value.__enter__.return_value.cursor.return_value.__enter__.return_value = mock_cur

            result = agent.run(task)

        assert result.result["recurrence_detected"] is True

    def test_no_recurrence(self):
        """Hits from distinct /24 subnets → recurrence_detected=False."""
        n_ids = [str(uuid.uuid4()) for _ in range(3)]
        # All from different subnets
        ips = ["10.0.1.5", "172.16.0.7", "192.168.99.4"]

        agent, _, _ = _make_agent(
            qdrant_retrieve=self._retrieve_point(),
            qdrant_search=self._search_results(n_ids, ips),
        )
        task = _make_task()

        pg_rows = [
            {
                "anomaly_id": aid,
                "timestamp": datetime(2024, 4, 1, tzinfo=timezone.utc),
                "user_id": "carol@example.com",
                "root_cause": "Credential Stuffing",
            }
            for aid in n_ids
        ]

        with patch("psycopg2.connect") as mock_conn:
            mock_cur = MagicMock()
            mock_cur.fetchone.return_value = (_ANOMALY_ID,)
            mock_cur.fetchall.return_value = pg_rows
            mock_conn.return_value.__enter__.return_value.cursor.return_value.__enter__.return_value = mock_cur

            result = agent.run(task)

        assert result.result["recurrence_detected"] is False


# ---------------------------------------------------------------------------
# TestInvestigationAgentQdrantFail
# ---------------------------------------------------------------------------


class TestInvestigationAgentQdrantFail:
    """Qdrant retrieve failure → agent gracefully returns an empty result."""

    def test_qdrant_failure(self):
        agent, qdrant_client, _ = _make_agent()

        # Qdrant raises on retrieve — simulates connection error.
        qdrant_client.retrieve.side_effect = ConnectionError("Qdrant unavailable")
        task = _make_task()

        with patch("psycopg2.connect") as mock_conn:
            mock_cur = MagicMock()
            mock_cur.fetchone.return_value = (_ANOMALY_ID,)
            mock_conn.return_value.__enter__.return_value.cursor.return_value.__enter__.return_value = mock_cur

            result = agent.run(task)

        # Agent should not crash; it may return complete with empty list or failed.
        assert result.status in ("complete", "failed")
        if result.status == "complete":
            assert result.result["similar_detections"] == []


# ---------------------------------------------------------------------------
# TestInvestigationAgentConfidence
# ---------------------------------------------------------------------------


class TestInvestigationAgentConfidence:
    """Confidence stays within [0.0, 1.0] and formula behaves as specified."""

    def test_confidence_range(self):
        """No matches → minimum confidence of 0.4."""
        agent, qdrant_client, _ = _make_agent()

        # DB exists, Qdrant retrieve succeeds but search returns only query self.
        retrieve_point = MagicMock()
        retrieve_point.vector = [0.1] * 384
        qdrant_client.retrieve.return_value = [retrieve_point]
        mock_qp = MagicMock()
        mock_qp.points = []  # no neighbours
        qdrant_client.query_points.return_value = mock_qp

        task = _make_task()

        with patch("psycopg2.connect") as mock_conn:
            mock_cur = MagicMock()
            mock_cur.fetchone.return_value = (_ANOMALY_ID,)
            mock_cur.fetchall.return_value = []
            mock_conn.return_value.__enter__.return_value.cursor.return_value.__enter__.return_value = mock_cur

            result = agent.run(task)

        assert result.status == "complete"
        assert 0.0 <= result.confidence <= 1.0
        # With 0 similar and no recurrence: 0.4 + 0 + 0 = 0.4
        assert pytest.approx(result.confidence, abs=1e-6) == 0.4
