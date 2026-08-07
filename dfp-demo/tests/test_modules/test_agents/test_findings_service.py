"""
Unit tests for modules/ai/agents/findings_service.py

The entire psycopg2 layer is mocked via conftest.py's sys.modules stub plus
explicit patch-at-use-site so FindingsService never touches a real database.

Covers:
- create_investigation() — inserts correct columns, returns UUID string
- record_finding()       — maps AgentResult fields → SQL correctly
- complete_investigation() — computes mean confidence over successful agents only
- fail_investigation()   — marks status='failed'
- get_investigation()    — calls SELECT and returns a dict (or None)
- _extract_recommendation() — static helper, no DB needed
- Context manager (__enter__/__exit__)

Author: Tomasz Zabek <tzabek@deloitte.co.uk>
Date: 2026-03-23
"""

from __future__ import annotations

import sys
import uuid
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parents[3]))

from modules.ai.agents.base_agent import AgentResult
from modules.ai.agents.findings_service import FindingsService

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_service() -> tuple[FindingsService, MagicMock, MagicMock]:
    """
    Return (service, mock_connection) without hitting Postgres.

    Patches psycopg2.connect at the import site inside findings_service so
    every test gets a fresh, independent mock connection.
    """
    mock_conn = MagicMock()
    mock_cursor = MagicMock()
    # Support `with conn.cursor(...) as cur:` context manager
    mock_conn.cursor.return_value.__enter__ = MagicMock(return_value=mock_cursor)
    mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=False)

    with patch("modules.ai.agents.findings_service.psycopg2.connect", return_value=mock_conn):
        svc = FindingsService()
    return svc, mock_conn, mock_cursor


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

ANOMALY_ID = str(uuid.uuid4())
INV_ID = str(uuid.uuid4())


@pytest.fixture
def svc_and_mocks():
    return _make_service()


@pytest.fixture
def forensics_ok():
    return AgentResult(
        agent_type="forensics",
        status="complete",
        result={"iocs": ["10.0.0.1"]},
        confidence=0.80,
        latency_ms=250,
        llm_tokens_used=512,
    )


@pytest.fixture
def investigation_ok():
    return AgentResult(
        agent_type="investigation",
        status="complete",
        result={"timeline": []},
        confidence=0.70,
        latency_ms=180,
        llm_tokens_used=400,
    )


@pytest.fixture
def remediation_ok():
    return AgentResult(
        agent_type="remediation",
        status="complete",
        result={"recommended_actions": [{"action": "Block IP 10.0.0.1"}]},
        confidence=0.90,
        latency_ms=300,
        llm_tokens_used=600,
    )


@pytest.fixture
def remediation_failed():
    return AgentResult(
        agent_type="remediation",
        status="failed",
        result={},
        confidence=0.0,
        error="LLM timeout",
    )


# ---------------------------------------------------------------------------
# create_investigation
# ---------------------------------------------------------------------------


class TestCreateInvestigation:
    def test_returns_uuid_string(self, svc_and_mocks):
        svc, mock_conn, mock_cursor = svc_and_mocks
        mock_cursor.fetchone.return_value = {"investigation_id": uuid.UUID(INV_ID)}

        result = svc.create_investigation(ANOMALY_ID, "HIGH", ["forensics", "investigation"])

        assert result == INV_ID

    def test_executes_insert_sql(self, svc_and_mocks):
        svc, mock_conn, mock_cursor = svc_and_mocks
        mock_cursor.fetchone.return_value = {"investigation_id": uuid.UUID(INV_ID)}

        svc.create_investigation(ANOMALY_ID, "CRITICAL", ["forensics"])

        sql_called = mock_cursor.execute.call_args[0][0]
        assert "INSERT INTO agent_investigations" in sql_called
        assert "RETURNING investigation_id" in sql_called

    def test_passes_correct_params(self, svc_and_mocks):
        svc, mock_conn, mock_cursor = svc_and_mocks
        mock_cursor.fetchone.return_value = {"investigation_id": uuid.UUID(INV_ID)}
        agents = ["forensics", "investigation", "remediation"]

        svc.create_investigation(ANOMALY_ID, "HIGH", agents)

        params = mock_cursor.execute.call_args[0][1]
        assert params[0] == ANOMALY_ID  # anomaly_id
        assert params[1] == "HIGH"  # severity_at_trigger
        assert params[2] == agents  # agents_invoked

    def test_commits_transaction(self, svc_and_mocks):
        svc, mock_conn, mock_cursor = svc_and_mocks
        mock_cursor.fetchone.return_value = {"investigation_id": uuid.UUID(INV_ID)}

        svc.create_investigation(ANOMALY_ID, "HIGH", [])

        mock_conn.commit.assert_called_once()


# ---------------------------------------------------------------------------
# record_finding
# ---------------------------------------------------------------------------


class TestRecordFinding:
    def test_executes_insert_sql(self, svc_and_mocks, forensics_ok):
        svc, mock_conn, mock_cursor = svc_and_mocks

        svc.record_finding(INV_ID, forensics_ok)

        sql_called = mock_cursor.execute.call_args[0][0]
        assert "INSERT INTO agent_findings" in sql_called

    def test_passes_agent_type_and_status(self, svc_and_mocks, forensics_ok):
        svc, mock_conn, mock_cursor = svc_and_mocks

        svc.record_finding(INV_ID, forensics_ok)

        params = mock_cursor.execute.call_args[0][1]
        assert params[0] == INV_ID  # investigation_id
        assert params[1] == "forensics"  # agent_type
        assert params[2] == "complete"  # status

    def test_result_wrapped_in_json_adapter(self, svc_and_mocks, forensics_ok):
        svc, mock_conn, mock_cursor = svc_and_mocks

        with patch("modules.ai.agents.findings_service.psycopg2.extras.Json", side_effect=lambda x: x):
            svc.record_finding(INV_ID, forensics_ok)

        params = mock_cursor.execute.call_args[0][1]
        result_param = params[3]  # result (JSONB)
        # psycopg2.extras.Json passes the dict through; psycopg2 handles serialisation
        assert result_param == forensics_ok.result

    def test_latency_and_tokens_passed(self, svc_and_mocks, forensics_ok):
        svc, mock_conn, mock_cursor = svc_and_mocks

        svc.record_finding(INV_ID, forensics_ok)

        params = mock_cursor.execute.call_args[0][1]
        assert params[4] == 512  # llm_tokens_used
        assert params[5] == 250  # latency_ms

    def test_commits_transaction(self, svc_and_mocks, forensics_ok):
        svc, mock_conn, mock_cursor = svc_and_mocks

        svc.record_finding(INV_ID, forensics_ok)

        mock_conn.commit.assert_called_once()


# ---------------------------------------------------------------------------
# complete_investigation
# ---------------------------------------------------------------------------


class TestCompleteInvestigation:
    def test_confidence_is_mean_of_successful_only(
        self, svc_and_mocks, forensics_ok, investigation_ok, remediation_failed
    ):
        svc, mock_conn, mock_cursor = svc_and_mocks
        # forensics=0.80, investigation=0.70 → mean=0.75 (remediation failed → excluded)
        svc.complete_investigation(INV_ID, [forensics_ok, investigation_ok, remediation_failed])

        params = mock_cursor.execute.call_args[0][1]
        confidence = params[0]
        assert abs(confidence - 0.75) < 0.001

    def test_all_failed_gives_zero_confidence(self, svc_and_mocks, remediation_failed):
        svc, mock_conn, mock_cursor = svc_and_mocks
        failed1 = AgentResult(agent_type="forensics", status="failed", result={}, confidence=0.0)
        failed2 = AgentResult(agent_type="investigation", status="failed", result={}, confidence=0.0)

        svc.complete_investigation(INV_ID, [failed1, failed2, remediation_failed])

        params = mock_cursor.execute.call_args[0][1]
        assert params[0] == 0.0

    def test_overall_recommendation_from_remediation(
        self, svc_and_mocks, forensics_ok, investigation_ok, remediation_ok
    ):
        svc, mock_conn, mock_cursor = svc_and_mocks

        svc.complete_investigation(INV_ID, [forensics_ok, investigation_ok, remediation_ok])

        params = mock_cursor.execute.call_args[0][1]
        recommendation = params[1]
        assert recommendation == "Block IP 10.0.0.1"

    def test_recommendation_fallback_when_no_remediation(self, svc_and_mocks, forensics_ok):
        svc, mock_conn, mock_cursor = svc_and_mocks

        svc.complete_investigation(INV_ID, [forensics_ok])

        params = mock_cursor.execute.call_args[0][1]
        recommendation = params[1]
        assert recommendation == "Manual SOC review required."

    def test_raw_report_keyed_by_agent_type(self, svc_and_mocks, forensics_ok, investigation_ok, remediation_ok):
        svc, mock_conn, mock_cursor = svc_and_mocks

        with patch("modules.ai.agents.findings_service.psycopg2.extras.Json", side_effect=lambda x: x):
            svc.complete_investigation(INV_ID, [forensics_ok, investigation_ok, remediation_ok])

        params = mock_cursor.execute.call_args[0][1]
        raw = params[2]  # raw_report — dict passed through Json adapter
        assert set(raw.keys()) == {"forensics", "investigation", "remediation"}

    def test_executes_update_sql(self, svc_and_mocks, forensics_ok):
        svc, mock_conn, mock_cursor = svc_and_mocks

        svc.complete_investigation(INV_ID, [forensics_ok])

        sql = mock_cursor.execute.call_args[0][0]
        assert "UPDATE agent_investigations" in sql
        assert "status = 'complete'" in sql

    def test_commits_transaction(self, svc_and_mocks, forensics_ok):
        svc, mock_conn, mock_cursor = svc_and_mocks

        svc.complete_investigation(INV_ID, [forensics_ok])

        mock_conn.commit.assert_called_once()


# ---------------------------------------------------------------------------
# fail_investigation
# ---------------------------------------------------------------------------


class TestFailInvestigation:
    def test_executes_update_sql(self, svc_and_mocks):
        svc, mock_conn, mock_cursor = svc_and_mocks

        svc.fail_investigation(INV_ID, "all agents timed out")

        sql = mock_cursor.execute.call_args[0][0]
        assert "UPDATE agent_investigations" in sql
        assert "status = 'failed'" in sql

    def test_investigation_id_in_params(self, svc_and_mocks):
        svc, mock_conn, mock_cursor = svc_and_mocks

        svc.fail_investigation(INV_ID)

        params = mock_cursor.execute.call_args[0][1]
        assert params[-1] == INV_ID

    def test_commits_transaction(self, svc_and_mocks):
        svc, mock_conn, mock_cursor = svc_and_mocks

        svc.fail_investigation(INV_ID)

        mock_conn.commit.assert_called_once()


# ---------------------------------------------------------------------------
# get_investigation
# ---------------------------------------------------------------------------


class TestGetInvestigation:
    def test_returns_dict_when_row_found(self, svc_and_mocks):
        svc, mock_conn, mock_cursor = svc_and_mocks
        mock_cursor.fetchone.return_value = {
            "investigation_id": INV_ID,
            "anomaly_id": ANOMALY_ID,
            "triggered_at": None,
            "completed_at": None,
            "status": "complete",
            "severity_at_trigger": "HIGH",
            "agents_invoked": ["forensics"],
            "confidence_score": 0.8,
            "overall_recommendation": "Block IP",
            "raw_report": {},
            "findings": [],
        }

        result = svc.get_investigation(ANOMALY_ID)

        assert result is not None
        assert result["investigation_id"] == INV_ID
        assert result["status"] == "complete"

    def test_returns_none_when_no_row(self, svc_and_mocks):
        svc, mock_conn, mock_cursor = svc_and_mocks
        mock_cursor.fetchone.return_value = None

        result = svc.get_investigation(ANOMALY_ID)

        assert result is None

    def test_selects_by_anomaly_id(self, svc_and_mocks):
        svc, mock_conn, mock_cursor = svc_and_mocks
        mock_cursor.fetchone.return_value = None

        svc.get_investigation(ANOMALY_ID)

        params = mock_cursor.execute.call_args[0][1]
        assert params[0] == ANOMALY_ID


# ---------------------------------------------------------------------------
# _extract_recommendation (static helper)
# ---------------------------------------------------------------------------


class TestExtractRecommendation:
    def test_pulls_first_action_from_remediation(self, remediation_ok):
        rec = FindingsService._extract_recommendation([remediation_ok])
        assert rec == "Block IP 10.0.0.1"

    def test_skips_failed_remediation(self, remediation_failed):
        rec = FindingsService._extract_recommendation([remediation_failed])
        assert rec == "Manual SOC review required."

    def test_fallback_when_no_remediation_agent(self, forensics_ok):
        rec = FindingsService._extract_recommendation([forensics_ok])
        assert rec == "Manual SOC review required."

    def test_fallback_on_empty_actions_list(self):
        r = AgentResult(
            agent_type="remediation",
            status="complete",
            result={"recommended_actions": []},
        )
        rec = FindingsService._extract_recommendation([r])
        assert rec == "Manual SOC review required."

    def test_empty_list(self):
        assert FindingsService._extract_recommendation([]) == "Manual SOC review required."


# ---------------------------------------------------------------------------
# Context manager
# ---------------------------------------------------------------------------


class TestContextManager:
    def test_enter_returns_self(self, svc_and_mocks):
        svc, *_ = svc_and_mocks
        assert svc.__enter__() is svc

    def test_exit_closes_connection(self, svc_and_mocks):
        svc, mock_conn, _ = svc_and_mocks
        with svc:
            pass
        mock_conn.close.assert_called_once()
