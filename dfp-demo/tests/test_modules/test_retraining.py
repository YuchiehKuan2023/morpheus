"""
Unit tests for the feedback loop retraining modules.

Covers:
  - ClassifierRetrainer threshold checks
  - ClassifierRetrainer force retrain (mocked training functions)
  - ClassifierRetrainer DB logging
  - DFPRetrainRunner.trigger_for_user (mocked DB)
  - DFPRetrainRunner.run_once (mocked DB)

All external I/O (Postgres, ML training) is replaced with mocks.

Author: Tomasz Zabek <tzabek@deloitte.co.uk>
Date: 2026-04-29
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# Ensure project root is on path
sys.path.insert(0, str(Path(__file__).parents[2]))


# ---------------------------------------------------------------------------
# ClassifierRetrainer tests
# ---------------------------------------------------------------------------


class TestClassifierRetrainer:
    """Tests for modules.ai.feedback.classifier_retrainer.ClassifierRetrainer."""

    @pytest.fixture
    def retrainer(self):
        from modules.ai.feedback.classifier_retrainer import ClassifierRetrainer

        return ClassifierRetrainer(db_config={"host": "localhost", "port": 5433, "database": "test"})

    @patch("modules.ai.feedback.classifier_retrainer.psycopg2")
    def test_threshold_not_met_skips_retrain(self, mock_pg, retrainer):
        """When delta < threshold, no retrain should happen."""
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_pg.connect.return_value = mock_conn
        mock_conn.cursor.return_value.__enter__ = MagicMock(return_value=mock_cursor)
        mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=False)

        # _count_classified_anomalies returns 100
        # _last_retrain_count returns 80
        # delta = 20 < 50 (threshold)
        mock_cursor.fetchone.side_effect = [(100,), (80,)]

        result = retrainer.check_and_retrain("risk_scorer")

        assert result["retrained"] is False
        assert result["delta"] == 20

    @patch("modules.ai.feedback.classifier_retrainer.psycopg2")
    def test_threshold_met_triggers_retrain(self, mock_pg, retrainer):
        """When delta >= threshold, retrain should be triggered."""
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_pg.connect.return_value = mock_conn
        mock_conn.cursor.return_value.__enter__ = MagicMock(return_value=mock_cursor)
        mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=False)

        # _count returns 200, _last returns 100, delta=100 >= 50
        # _insert_retrain_log returns log_id=1
        mock_cursor.fetchone.side_effect = [(200,), (100,), (1,)]

        with patch.object(retrainer, "_retrain_risk_scorer") as mock_train:
            mock_train.return_value = {"model_dir": "data/models/risk_scorer", "mlflow_run_id": "abc"}
            with patch.object(retrainer, "_send_notification"):
                result = retrainer.check_and_retrain("risk_scorer")

        assert result["retrained"] is True
        mock_train.assert_called_once()

    def test_invalid_classifier_returns_error(self, retrainer):
        result = retrainer.check_and_retrain("invalid_type")
        assert result.get("skipped") is True

    @patch("modules.ai.feedback.classifier_retrainer.psycopg2")
    def test_force_retrain_calls_training(self, mock_pg, retrainer):
        """force_retrain should call the training function unconditionally."""
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_pg.connect.return_value = mock_conn
        mock_conn.cursor.return_value.__enter__ = MagicMock(return_value=mock_cursor)
        mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=False)

        # _count + _insert_retrain_log
        mock_cursor.fetchone.side_effect = [(50,), (1,)]

        with patch.object(retrainer, "_retrain_risk_scorer") as mock_train:
            mock_train.return_value = {
                "model_dir": "data/models/risk_scorer",
                "mlflow_run_id": "run123",
                "n_scored": 50,
                "score_min": 10.0,
                "score_max": 90.0,
            }
            with patch.object(retrainer, "_send_notification"):
                result = retrainer.force_retrain("risk_scorer")

        assert result["retrained"] is True
        assert result["log_id"] == 1
        mock_train.assert_called_once()

    @patch("modules.ai.feedback.classifier_retrainer.psycopg2")
    def test_force_retrain_handles_failure(self, mock_pg, retrainer):
        """If training raises, the log should be marked failed."""
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_pg.connect.return_value = mock_conn
        mock_conn.cursor.return_value.__enter__ = MagicMock(return_value=mock_cursor)
        mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=False)

        mock_cursor.fetchone.side_effect = [(50,), (1,)]

        with patch.object(retrainer, "_retrain_root_cause") as mock_train:
            mock_train.side_effect = RuntimeError("torch not installed")
            result = retrainer.force_retrain("root_cause")

        assert result["retrained"] is False
        assert "torch not installed" in result["error"]

    @patch("modules.ai.feedback.classifier_retrainer.psycopg2")
    def test_check_and_retrain_all(self, mock_pg, retrainer):
        """check_and_retrain_all should check both classifiers."""
        with patch.object(retrainer, "check_and_retrain") as mock_check:
            mock_check.return_value = {"retrained": False, "delta": 10}
            results = retrainer.check_and_retrain_all()

        assert "risk_scorer" in results
        assert "root_cause" in results
        assert mock_check.call_count == 2


# ---------------------------------------------------------------------------
# DFPRetrainRunner tests
# ---------------------------------------------------------------------------


class TestDFPRetrainRunner:
    """Tests for modules.ai.feedback.dfp_retrain_runner.DFPRetrainRunner."""

    @pytest.fixture
    def runner(self):
        from modules.ai.feedback.dfp_retrain_runner import DFPRetrainRunner

        return DFPRetrainRunner(db_config={"host": "localhost", "port": 5433, "database": "test"})

    @patch("modules.ai.feedback.dfp_retrain_runner.psycopg2")
    def test_trigger_for_user_creates_job(self, mock_pg, runner):
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_pg.connect.return_value = mock_conn
        mock_conn.cursor.return_value.__enter__ = MagicMock(return_value=mock_cursor)
        mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=False)

        # No existing pending job, then returns new job_id
        mock_cursor.fetchone.side_effect = [None, ("job-123",)]

        job_id = runner.trigger_for_user("alice@example.com")
        assert job_id == "job-123"

    @patch("modules.ai.feedback.dfp_retrain_runner.psycopg2")
    def test_trigger_for_user_skips_if_pending(self, mock_pg, runner):
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_pg.connect.return_value = mock_conn
        mock_conn.cursor.return_value.__enter__ = MagicMock(return_value=mock_cursor)
        mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=False)

        # Existing pending job found
        mock_cursor.fetchone.return_value = ("existing-job",)

        job_id = runner.trigger_for_user("alice@example.com")
        assert job_id is None

    @patch("modules.ai.feedback.dfp_retrain_runner.psycopg2")
    def test_run_once_returns_zero_when_no_jobs(self, mock_pg, runner):
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_pg.connect.return_value = mock_conn
        mock_conn.cursor.return_value.__enter__ = MagicMock(return_value=mock_cursor)
        mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=False)
        mock_cursor.fetchone.return_value = None

        count = runner.run_once()
        assert count == 0
