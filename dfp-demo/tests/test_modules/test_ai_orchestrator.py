"""
Integration tests for the AI Orchestrator pipeline.

Covers:
  - RoutedEvent.from_anomaly_message / from_clean_message
  - labeling_worker.classify_single (mocked DB + ML model)
  - BatchLabeler.label_single (delegates to BatchLabeler.run)
  - AIOrchestrator._handle_anomaly end-to-end (all services mocked)
  - AIOrchestrator._handle_clean_event JSONL append

All external I/O (Postgres, Kafka, ML models) is replaced with mocks or
temp files so the suite runs offline without any infrastructure.

Author: Tomasz Zabek <tzabek@deloitte.co.uk>
Date: 2026-03-11
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# Ensure project root is on path
sys.path.insert(0, str(Path(__file__).parents[2]))

from modules.ai.orchestrator.event_router import EventType, RoutedEvent

# ---------------------------------------------------------------------------
# Sample payloads
# ---------------------------------------------------------------------------

ANOMALY_MSG: dict = {
    "user_id": "alice@example.com",
    "timestamp": "2026-03-11T09:00:00Z",
    "anomaly_score": 4.2,
    "top_features": "login_hour,bytes_sent,country_code",
    "features": [
        {"name": "login_hour", "z_score": 3.8},
        {"name": "bytes_sent", "z_score": 2.1},
    ],
    "original_event": {
        "username": "alice@example.com",
        "ip_address": "203.0.113.42",
        "action": "file_download",
    },
}

CLEAN_MSG: dict = {
    "username": "bob@example.com",
    "ip_address": "10.0.0.1",
    "action": "login",
    "timestamp": "2026-03-11T09:05:00Z",
}

ANOMALY_ID = "aaaabbbb-cccc-dddd-eeee-ffffffffffff"

# ============================================================================
# RoutedEvent tests
# ============================================================================


class TestRoutedEvent:
    def test_from_anomaly_message_fields(self):
        event = RoutedEvent.from_anomaly_message(ANOMALY_MSG)

        assert event.event_type == EventType.ANOMALY
        assert event.user_id == "alice@example.com"
        assert event.anomaly_score == pytest.approx(4.2)
        assert len(event.features) == 2
        assert event.original_event["action"] == "file_download"

    def test_from_anomaly_message_is_anomaly(self):
        event = RoutedEvent.from_anomaly_message(ANOMALY_MSG)
        assert event.is_anomaly is True

    def test_from_clean_message_fields(self):
        event = RoutedEvent.from_clean_message(CLEAN_MSG)

        assert event.event_type == EventType.CLEAN
        assert event.user_id == "bob@example.com"
        assert event.is_anomaly is False
        assert event.original_event["action"] == "login"

    def test_from_clean_message_fallback_user_id(self):
        msg = {"user_id": "carol@example.com", "action": "logout"}
        event = RoutedEvent.from_clean_message(msg)
        assert event.user_id == "carol@example.com"

    def test_from_anomaly_missing_original_event_defaults_to_full_msg(self):
        """When original_event is absent, the full msg becomes original_event."""
        msg = dict(ANOMALY_MSG)
        del msg["original_event"]
        event = RoutedEvent.from_anomaly_message(msg)
        assert event.original_event["user_id"] == "alice@example.com"


# ============================================================================
# classify_single (labeling_worker)
# ============================================================================


class TestClassifySingle:
    """classify_single fetches one DB row, runs the DistilBERT model, writes back."""

    def _make_clf_result(self):
        result = MagicMock()
        result.anomaly_id = ANOMALY_ID
        result.root_cause = "Compromised Credential"
        result.sub_category = "brute_force"
        result.confidence = 0.88
        result.reasoning = "High login_hour z-score"
        return result

    @patch("modules.ai.root_cause.labeling_worker.psycopg2.connect")
    @patch("modules.ai.root_cause.labeling_worker.PersistenceService")
    @patch("modules.ai.root_cause.labeling_worker.RootCauseClassifier")
    def test_not_found_returns_none(self, mock_clf_cls, mock_ps_cls, mock_connect):
        # DB returns nothing for this anomaly_id
        mock_cursor = MagicMock()
        mock_cursor.__enter__ = lambda s: s
        mock_cursor.__exit__ = MagicMock(return_value=False)
        mock_cursor.fetchone.return_value = None
        mock_conn = MagicMock()
        mock_conn.cursor.return_value = mock_cursor
        mock_connect.return_value = mock_conn

        from modules.ai.root_cause import labeling_worker

        result = labeling_worker.classify_single("nonexistent-id")
        assert result is None

    @patch("modules.ai.root_cause.labeling_worker._get_risk_scorer", return_value=None)
    @patch("modules.ai.root_cause.labeling_worker.fetch_full_rows", return_value=[])
    @patch("modules.ai.root_cause.labeling_worker.psycopg2.connect")
    @patch("modules.ai.root_cause.labeling_worker.PersistenceService")
    @patch("modules.ai.root_cause.labeling_worker.RootCauseClassifier")
    def test_successful_classify(self, mock_clf_cls, mock_ps_cls, mock_connect, mock_ffr, mock_scorer):
        # DB row
        mock_cursor = MagicMock()
        mock_cursor.__enter__ = lambda s: s
        mock_cursor.__exit__ = MagicMock(return_value=False)
        mock_cursor.fetchone.return_value = {
            "anomaly_id": ANOMALY_ID,
            "top_features": "login_hour",
            "anomaly_score": 4.2,
        }
        mock_conn = MagicMock()
        mock_conn.cursor.return_value = mock_cursor
        mock_connect.return_value = mock_conn

        # Classifier
        clf_result = self._make_clf_result()
        mock_clf_instance = MagicMock()
        mock_clf_instance.predict_batch.return_value = [clf_result]
        mock_clf_cls.return_value = mock_clf_instance

        # PersistenceService context manager
        mock_ps_instance = MagicMock()
        mock_ps_instance.__enter__ = lambda s: s
        mock_ps_instance.__exit__ = MagicMock(return_value=False)
        mock_ps_instance.update_classification.return_value = True
        mock_ps_cls.return_value = mock_ps_instance

        # write_classifications uses persistence.update_classification internally
        with patch(
            "modules.ai.root_cause.labeling_worker.write_classifications",
            return_value=(1, 0),
        ):
            from modules.ai.root_cause import labeling_worker

            result = labeling_worker.classify_single(ANOMALY_ID)

        assert result is not None
        assert result["anomaly_id"] == ANOMALY_ID
        assert result["root_cause"] == "Compromised Credential"
        assert result["n_classified"] == 1
        assert result["n_failed"] == 0


# ============================================================================
# BatchLabeler.label_single
# ============================================================================


class TestBatchLabelerLabelSingle:
    """label_single opens its own DB connection and delegates to run()."""

    @patch("modules.ai.auto_labeling.batch_labeler.psycopg2")
    def test_label_single_calls_run_with_connection(self, mock_psycopg2):
        mock_conn = MagicMock()
        mock_psycopg2.connect.return_value = mock_conn

        from modules.ai.auto_labeling.batch_labeler import BatchLabeler

        labeler = BatchLabeler()
        expected_stats = {
            "total": 1,
            "labeled": 1,
            "true_anomaly": 1,
            "false_positive": 0,
            "uncertain": 0,
            "errors": 0,
            "retrain_jobs_triggered": 0,
            "elapsed_seconds": 0.01,
        }
        labeler.run = MagicMock(return_value=expected_stats)

        result = labeler.label_single(ANOMALY_ID)

        labeler.run.assert_called_once_with(mock_conn, detection_id=ANOMALY_ID)
        mock_conn.close.assert_called_once()
        assert result == expected_stats

    @patch("modules.ai.auto_labeling.batch_labeler.psycopg2")
    def test_label_single_closes_conn_on_exception(self, mock_psycopg2):
        mock_conn = MagicMock()
        mock_psycopg2.connect.return_value = mock_conn

        from modules.ai.auto_labeling.batch_labeler import BatchLabeler

        labeler = BatchLabeler()
        labeler.run = MagicMock(side_effect=RuntimeError("DB timeout"))

        with pytest.raises(RuntimeError, match="DB timeout"):
            labeler.label_single(ANOMALY_ID)

        mock_conn.close.assert_called_once()


# ============================================================================
# AIOrchestrator._handle_anomaly
# ============================================================================


class TestAIOrchestratorHandleAnomaly:
    """Wire the full anomaly path through mocked services."""

    def _make_orchestrator(self, enrichment_svc, persistence_svc, labeler, lw_mod):
        from modules.ai.orchestrator.ai_orchestrator import AIOrchestrator

        return AIOrchestrator(
            enrichment_service=enrichment_svc,
            persistence_service=persistence_svc,
            batch_labeler=labeler,
            labeling_worker_module=lw_mod,
            kafka_bootstrap="127.0.0.1:29092",
        )

    @patch("modules.ai.orchestrator.ai_orchestrator.FeatureBridge")
    def test_handle_anomaly_full_pipeline(self, mock_bridge_cls):
        enrichment_svc = MagicMock()
        persistence_svc = MagicMock()
        batch_labeler = MagicMock()
        lw_mod = MagicMock()

        # FeatureBridge.dict_to_detection returns a DetectionRecord mock
        mock_bridge = MagicMock()
        mock_bridge.dict_to_detection.return_value = MagicMock()
        mock_bridge_cls.return_value = mock_bridge

        enrichment_svc.enrich_detection.return_value = {
            "user_id": "alice@example.com",
            "anomaly_id": ANOMALY_ID,
        }
        persistence_svc.save_enriched_detection.return_value = {"anomaly_id": ANOMALY_ID}
        batch_labeler.label_single.return_value = {"total": 1, "labeled": 1}
        lw_mod.classify_single.return_value = {"anomaly_id": ANOMALY_ID, "root_cause": "Compromised Credential"}

        orch = self._make_orchestrator(enrichment_svc, persistence_svc, batch_labeler, lw_mod)
        orch._handle_anomaly(ANOMALY_MSG)

        enrichment_svc.enrich_detection.assert_called_once()
        persistence_svc.save_enriched_detection.assert_called_once()
        batch_labeler.label_single.assert_called_once_with(ANOMALY_ID)
        lw_mod.classify_single.assert_called_once_with(ANOMALY_ID)

    @patch("modules.ai.orchestrator.ai_orchestrator.FeatureBridge")
    def test_handle_anomaly_skips_labeling_when_no_anomaly_id(self, mock_bridge_cls):
        enrichment_svc = MagicMock()
        persistence_svc = MagicMock()
        batch_labeler = MagicMock()
        lw_mod = MagicMock()

        mock_bridge = MagicMock()
        mock_bridge.dict_to_detection.return_value = MagicMock()
        mock_bridge_cls.return_value = mock_bridge

        enrichment_svc.enrich_detection.return_value = {"user_id": "alice@example.com"}
        persistence_svc.save_enriched_detection.return_value = {}  # no anomaly_id

        orch = self._make_orchestrator(enrichment_svc, persistence_svc, batch_labeler, lw_mod)
        orch._handle_anomaly(ANOMALY_MSG)

        batch_labeler.label_single.assert_not_called()
        lw_mod.classify_single.assert_not_called()

    @patch("modules.ai.orchestrator.ai_orchestrator.FeatureBridge")
    def test_handle_anomaly_enrichment_none_skips_persist(self, mock_bridge_cls):
        enrichment_svc = MagicMock()
        persistence_svc = MagicMock()

        mock_bridge = MagicMock()
        mock_bridge.dict_to_detection.return_value = MagicMock()
        mock_bridge_cls.return_value = mock_bridge

        enrichment_svc.enrich_detection.return_value = None  # enrichment failed

        orch = self._make_orchestrator(enrichment_svc, persistence_svc, MagicMock(), MagicMock())
        orch._handle_anomaly(ANOMALY_MSG)

        persistence_svc.save_enriched_detection.assert_not_called()


# ============================================================================
# AIOrchestrator — multi-agent dispatch (Step 6)
# ============================================================================

# Anomaly scores mapped to severity:
#   > 5.0  → CRITICAL,  >= 3.0 → HIGH,  >= 2.5 → MEDIUM,  else → LOW
# Dispatch fires when: CRITICAL | HIGH | (MEDIUM and risk_score >= 60)

CRITICAL_MSG = {**ANOMALY_MSG, "anomaly_score": 5.5}  # → CRITICAL
HIGH_MSG = {**ANOMALY_MSG, "anomaly_score": 3.8}  # → HIGH
MEDIUM_HI_MSG = {**ANOMALY_MSG, "anomaly_score": 2.7}  # → MEDIUM  (risk_score set per test)
LOW_MSG = {**ANOMALY_MSG, "anomaly_score": 1.5}  # → LOW


class TestAIOrchestratorAgentDispatch:
    """Agent task should be produced for ALL severities — every above-threshold
    anomaly warrants a full investigation."""

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _make_orchestrator(self, enrichment_svc, persistence_svc, lw_mod=None):
        from modules.ai.orchestrator.ai_orchestrator import AIOrchestrator

        return AIOrchestrator(
            enrichment_service=enrichment_svc,
            persistence_service=persistence_svc,
            batch_labeler=MagicMock(),
            labeling_worker_module=lw_mod or MagicMock(),
            kafka_bootstrap="127.0.0.1:29092",
        )

    def _base_mocks(self, anomaly_msg, risk_score=0.0, root_cause="Compromised Credential"):
        """Return (enrichment_svc, persistence_svc, lw_mod) configured for a given anomaly."""
        enrichment_svc = MagicMock()
        persistence_svc = MagicMock()
        lw_mod = MagicMock()

        enrichment_svc.enrich_detection.return_value = {
            "user_id": anomaly_msg.get("user_id", "alice@example.com"),
            "anomaly_score": anomaly_msg["anomaly_score"],
        }
        persistence_svc.save_enriched_detection.return_value = {"anomaly_id": ANOMALY_ID}

        # Simulate the DB SELECT for risk_score in Step 6
        mock_cursor = MagicMock()
        mock_cursor.__enter__ = lambda s: s
        mock_cursor.__exit__ = MagicMock(return_value=False)
        mock_cursor.fetchone.return_value = (risk_score,)
        persistence_svc.postgres_conn.cursor.return_value = mock_cursor

        lw_mod.classify_single.return_value = {
            "anomaly_id": ANOMALY_ID,
            "root_cause": root_cause,
        }

        return enrichment_svc, persistence_svc, lw_mod

    # ------------------------------------------------------------------
    # Dispatch fires
    # ------------------------------------------------------------------

    @patch("modules.ai.orchestrator.ai_orchestrator.FeatureBridge")
    def test_critical_anomaly_produces_agent_task(self, mock_bridge_cls):
        mock_bridge_cls.return_value.dict_to_detection.return_value = MagicMock()
        enrichment_svc, persistence_svc, lw_mod = self._base_mocks(CRITICAL_MSG, risk_score=0.0)

        orch = self._make_orchestrator(enrichment_svc, persistence_svc, lw_mod)
        orch._agent_producer = MagicMock()
        orch._handle_anomaly(CRITICAL_MSG)

        orch._agent_producer.produce.assert_called_once()
        payload = orch._agent_producer.produce.call_args[1]["value"]
        assert payload["severity"] == "CRITICAL"
        assert payload["anomaly_id"] == ANOMALY_ID

    @patch("modules.ai.orchestrator.ai_orchestrator.FeatureBridge")
    def test_high_anomaly_produces_agent_task(self, mock_bridge_cls):
        mock_bridge_cls.return_value.dict_to_detection.return_value = MagicMock()
        enrichment_svc, persistence_svc, lw_mod = self._base_mocks(HIGH_MSG, risk_score=45.0)

        orch = self._make_orchestrator(enrichment_svc, persistence_svc, lw_mod)
        orch._agent_producer = MagicMock()
        orch._handle_anomaly(HIGH_MSG)

        orch._agent_producer.produce.assert_called_once()
        payload = orch._agent_producer.produce.call_args[1]["value"]
        assert payload["severity"] == "HIGH"

    @patch("modules.ai.orchestrator.ai_orchestrator.FeatureBridge")
    def test_medium_high_risk_produces_agent_task(self, mock_bridge_cls):
        """MEDIUM severity + risk_score >= 60 → dispatch fires."""
        mock_bridge_cls.return_value.dict_to_detection.return_value = MagicMock()
        enrichment_svc, persistence_svc, lw_mod = self._base_mocks(MEDIUM_HI_MSG, risk_score=75.0)

        orch = self._make_orchestrator(enrichment_svc, persistence_svc, lw_mod)
        orch._agent_producer = MagicMock()
        orch._handle_anomaly(MEDIUM_HI_MSG)

        orch._agent_producer.produce.assert_called_once()
        payload = orch._agent_producer.produce.call_args[1]["value"]
        assert payload["severity"] == "MEDIUM"
        assert payload["risk_score"] >= 60

    # ------------------------------------------------------------------
    # Dispatch suppressed
    # ------------------------------------------------------------------

    @patch("modules.ai.orchestrator.ai_orchestrator.FeatureBridge")
    def test_medium_low_risk_still_dispatches(self, mock_bridge_cls):
        """MEDIUM severity + low risk_score still dispatches (all anomalies get agents)."""
        mock_bridge_cls.return_value.dict_to_detection.return_value = MagicMock()
        enrichment_svc, persistence_svc, lw_mod = self._base_mocks(MEDIUM_HI_MSG, risk_score=42.0)

        orch = self._make_orchestrator(enrichment_svc, persistence_svc, lw_mod)
        orch._agent_producer = MagicMock()
        orch._handle_anomaly(MEDIUM_HI_MSG)

        orch._agent_producer.produce.assert_called_once()

    @patch("modules.ai.orchestrator.ai_orchestrator.FeatureBridge")
    def test_low_anomaly_still_dispatches(self, mock_bridge_cls):
        """LOW severity still dispatches (all anomalies get agents)."""
        mock_bridge_cls.return_value.dict_to_detection.return_value = MagicMock()
        enrichment_svc, persistence_svc, lw_mod = self._base_mocks(LOW_MSG, risk_score=90.0)

        orch = self._make_orchestrator(enrichment_svc, persistence_svc, lw_mod)
        orch._agent_producer = MagicMock()
        orch._handle_anomaly(LOW_MSG)

        orch._agent_producer.produce.assert_called_once()

    @patch("modules.ai.orchestrator.ai_orchestrator.FeatureBridge")
    def test_medium_at_risk_score_boundary_60_produces(self, mock_bridge_cls):
        """Edge: risk_score exactly 60 → dispatch fires (>= 60)."""
        mock_bridge_cls.return_value.dict_to_detection.return_value = MagicMock()
        enrichment_svc, persistence_svc, lw_mod = self._base_mocks(MEDIUM_HI_MSG, risk_score=60.0)

        orch = self._make_orchestrator(enrichment_svc, persistence_svc, lw_mod)
        orch._agent_producer = MagicMock()
        orch._handle_anomaly(MEDIUM_HI_MSG)

        orch._agent_producer.produce.assert_called_once()

    @patch("modules.ai.orchestrator.ai_orchestrator.FeatureBridge")
    def test_medium_below_old_boundary_still_dispatches(self, mock_bridge_cls):
        """Edge: risk_score 59.9 still dispatches (no gating anymore)."""
        mock_bridge_cls.return_value.dict_to_detection.return_value = MagicMock()
        enrichment_svc, persistence_svc, lw_mod = self._base_mocks(MEDIUM_HI_MSG, risk_score=59.9)

        orch = self._make_orchestrator(enrichment_svc, persistence_svc, lw_mod)
        orch._agent_producer = MagicMock()
        orch._handle_anomaly(MEDIUM_HI_MSG)

        orch._agent_producer.produce.assert_called_once()

    # ------------------------------------------------------------------
    # Payload content
    # ------------------------------------------------------------------

    @patch("modules.ai.orchestrator.ai_orchestrator.FeatureBridge")
    def test_payload_contains_root_cause_from_classify_single(self, mock_bridge_cls):
        mock_bridge_cls.return_value.dict_to_detection.return_value = MagicMock()
        enrichment_svc, persistence_svc, lw_mod = self._base_mocks(
            CRITICAL_MSG, risk_score=0.0, root_cause="Data Exfiltration"
        )

        orch = self._make_orchestrator(enrichment_svc, persistence_svc, lw_mod)
        orch._agent_producer = MagicMock()
        orch._handle_anomaly(CRITICAL_MSG)

        payload = orch._agent_producer.produce.call_args[1]["value"]
        assert payload["root_cause"] == "Data Exfiltration"

    @patch("modules.ai.orchestrator.ai_orchestrator.FeatureBridge")
    def test_payload_root_cause_fallback_when_classification_none(self, mock_bridge_cls):
        """If classify_single fails, root_cause defaults to 'Unknown'."""
        mock_bridge_cls.return_value.dict_to_detection.return_value = MagicMock()
        enrichment_svc, persistence_svc, _ = self._base_mocks(CRITICAL_MSG, risk_score=0.0)

        lw_mod = MagicMock()
        lw_mod.classify_single.return_value = None  # classification failed

        orch = self._make_orchestrator(enrichment_svc, persistence_svc, lw_mod)
        orch._agent_producer = MagicMock()
        orch._handle_anomaly(CRITICAL_MSG)

        payload = orch._agent_producer.produce.call_args[1]["value"]
        assert payload["root_cause"] == "Unknown"

    @patch("modules.ai.orchestrator.ai_orchestrator.FeatureBridge")
    def test_risk_score_fetched_from_db_not_enriched(self, mock_bridge_cls):
        """risk_score in the payload comes from the DB read, not from enriched dict."""
        mock_bridge_cls.return_value.dict_to_detection.return_value = MagicMock()
        enrichment_svc, persistence_svc, lw_mod = self._base_mocks(HIGH_MSG, risk_score=82.5)

        orch = self._make_orchestrator(enrichment_svc, persistence_svc, lw_mod)
        orch._agent_producer = MagicMock()
        orch._handle_anomaly(HIGH_MSG)

        payload = orch._agent_producer.produce.call_args[1]["value"]
        assert payload["risk_score"] == pytest.approx(82.5)

    @patch("modules.ai.orchestrator.ai_orchestrator.FeatureBridge")
    def test_produce_keyed_by_anomaly_id(self, mock_bridge_cls):
        mock_bridge_cls.return_value.dict_to_detection.return_value = MagicMock()
        enrichment_svc, persistence_svc, lw_mod = self._base_mocks(CRITICAL_MSG)

        orch = self._make_orchestrator(enrichment_svc, persistence_svc, lw_mod)
        orch._agent_producer = MagicMock()
        orch._handle_anomaly(CRITICAL_MSG)

        assert orch._agent_producer.produce.call_args[1]["key"] == ANOMALY_ID


# ============================================================================
# AIOrchestrator._handle_clean_event (DB insert)
# ============================================================================


class TestAIOrchestratorHandleCleanEvent:
    """_handle_clean_event inserts into user_training_events via a psycopg2 connection."""

    def _make_mock_conn(self):
        mock_cursor = MagicMock()
        mock_cursor.__enter__ = lambda s: s
        mock_cursor.__exit__ = MagicMock(return_value=False)
        mock_conn = MagicMock()
        mock_conn.cursor.return_value = mock_cursor
        return mock_conn, mock_cursor

    @patch("modules.ai.orchestrator.ai_orchestrator.FeatureBridge")
    def test_clean_event_inserted_to_db(self, mock_bridge_cls):
        from modules.ai.orchestrator.ai_orchestrator import AIOrchestrator

        orch = AIOrchestrator(
            enrichment_service=MagicMock(),
            persistence_service=MagicMock(),
            batch_labeler=MagicMock(),
            labeling_worker_module=MagicMock(),
            kafka_bootstrap="127.0.0.1:29092",
        )
        mock_conn, mock_cursor = self._make_mock_conn()

        orch._handle_clean_event(CLEAN_MSG, mock_conn)

        mock_cursor.execute.assert_called_once()
        sql = mock_cursor.execute.call_args[0][0]
        assert "INSERT INTO user_training_events" in sql
        assert "'clean'" in sql
        mock_conn.commit.assert_called_once()

    @patch("modules.ai.orchestrator.ai_orchestrator.FeatureBridge")
    def test_clean_event_user_id_extracted(self, mock_bridge_cls):
        """user_id from 'username' field is passed as first execute parameter."""
        from modules.ai.orchestrator.ai_orchestrator import AIOrchestrator

        orch = AIOrchestrator(
            enrichment_service=MagicMock(),
            persistence_service=MagicMock(),
            batch_labeler=MagicMock(),
            labeling_worker_module=MagicMock(),
            kafka_bootstrap="127.0.0.1:29092",
        )
        mock_conn, mock_cursor = self._make_mock_conn()

        orch._handle_clean_event(CLEAN_MSG, mock_conn)

        params = mock_cursor.execute.call_args[0][1]
        assert params[0] == "bob@example.com"  # user_id

    @patch("modules.ai.orchestrator.ai_orchestrator.FeatureBridge")
    def test_clean_events_multiple_calls_commit_each(self, mock_bridge_cls):
        """Each event is committed individually (no batching in _handle_clean_event)."""
        from modules.ai.orchestrator.ai_orchestrator import AIOrchestrator

        orch = AIOrchestrator(
            enrichment_service=MagicMock(),
            persistence_service=MagicMock(),
            batch_labeler=MagicMock(),
            labeling_worker_module=MagicMock(),
            kafka_bootstrap="127.0.0.1:29092",
        )
        mock_conn, mock_cursor = self._make_mock_conn()

        for i in range(5):
            msg = {**CLEAN_MSG, "username": f"user{i}@example.com"}
            orch._handle_clean_event(msg, mock_conn)

        assert mock_cursor.execute.call_count == 5
        assert mock_conn.commit.call_count == 5
