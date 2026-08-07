"""
Unit tests for AnomalyForecaster retraining logic.

Covers:
  - check_and_retrain threshold logic (below / at / above threshold)
  - force_retrain success path (train → save → mlflow → log)
  - force_retrain when training fails (insufficient data)
  - force_retrain when training raises an exception
  - DB retrain log insert / complete / fail updates
  - model_dir_for path routing (global vs per-user)

All external I/O (Postgres, Prophet, MLflow, filesystem) is mocked.

Author: Tomasz Zabek <tzabek@deloitte.co.uk>
Date: 2026-05-07
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parents[2]))


class TestAnomalyForecaster:
    """Tests for modules.ai.forecasting.prophet_forecaster.AnomalyForecaster."""

    @pytest.fixture
    def forecaster(self):
        from modules.ai.forecasting.prophet_forecaster import AnomalyForecaster

        return AnomalyForecaster(db_config={"host": "localhost", "port": 5433, "database": "test"})

    # -- helper to set up the psycopg2 mock cursor --
    @staticmethod
    def _mock_pg(mock_pg):
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_pg.connect.return_value = mock_conn
        mock_conn.cursor.return_value.__enter__ = MagicMock(return_value=mock_cursor)
        mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=False)
        return mock_conn, mock_cursor

    # -----------------------------------------------------------------------
    # model_dir_for
    # -----------------------------------------------------------------------

    def test_model_dir_for_global(self):
        from modules.ai.forecasting.prophet_forecaster import MODEL_DIR, AnomalyForecaster

        assert AnomalyForecaster.model_dir_for(None) == MODEL_DIR

    def test_model_dir_for_user(self):
        from modules.ai.forecasting.prophet_forecaster import MODEL_DIR, AnomalyForecaster

        result = AnomalyForecaster.model_dir_for("alice")
        assert result == MODEL_DIR / "users" / "alice"

    # -----------------------------------------------------------------------
    # check_and_retrain — threshold NOT met
    # -----------------------------------------------------------------------

    @patch("modules.ai.forecasting.prophet_forecaster.psycopg2")
    def test_check_and_retrain_below_threshold(self, mock_pg, forecaster):
        """When delta < FORECAST_RETRAIN_THRESHOLD, no retrain should happen."""
        _, mock_cursor = self._mock_pg(mock_pg)

        # _count_total_anomalies → 150, _last_retrain_count → 100 → delta=50
        # Default threshold is 100, so 50 < 100 → skip
        mock_cursor.fetchone.side_effect = [(150,), (100,)]

        result = forecaster.check_and_retrain()

        assert result["retrained"] is False
        assert result["delta"] == 50
        assert result["current_count"] == 150
        assert result["last_count"] == 100

    # -----------------------------------------------------------------------
    # check_and_retrain — threshold met → delegates to force_retrain
    # -----------------------------------------------------------------------

    @patch("modules.ai.forecasting.prophet_forecaster.psycopg2")
    def test_check_and_retrain_above_threshold(self, mock_pg, forecaster):
        """When delta >= threshold, force_retrain should be called."""
        _, mock_cursor = self._mock_pg(mock_pg)

        # _count_total_anomalies → 300, _last_retrain_count → 100 → delta=200 >= 100
        mock_cursor.fetchone.side_effect = [(300,), (100,)]

        with patch.object(forecaster, "force_retrain") as mock_force:
            mock_force.return_value = {"retrained": True}
            result = forecaster.check_and_retrain()

        assert result["retrained"] is True
        mock_force.assert_called_once_with(anomalies_at_retrain=300)

    # -----------------------------------------------------------------------
    # check_and_retrain — first run (no previous retrain log)
    # -----------------------------------------------------------------------

    @patch("modules.ai.forecasting.prophet_forecaster.psycopg2")
    def test_check_and_retrain_first_run(self, mock_pg, forecaster):
        """First run with 200 anomalies, no prior retrain → delta=200 >= 100."""
        _, mock_cursor = self._mock_pg(mock_pg)

        # _count_total_anomalies → 200, _last_retrain_count → None row → 0
        mock_cursor.fetchone.side_effect = [(200,), None]

        with patch.object(forecaster, "force_retrain") as mock_force:
            mock_force.return_value = {"retrained": True}
            result = forecaster.check_and_retrain()

        assert result["retrained"] is True
        mock_force.assert_called_once_with(anomalies_at_retrain=200)

    # -----------------------------------------------------------------------
    # force_retrain — success path
    # -----------------------------------------------------------------------

    @patch("modules.ai.forecasting.prophet_forecaster.psycopg2")
    def test_force_retrain_success(self, mock_pg, forecaster):
        """Successful retrain: train → save → mlflow → complete log."""
        _, mock_cursor = self._mock_pg(mock_pg)

        # _count_total_anomalies → 500, _insert_retrain_log → id=42
        mock_cursor.fetchone.side_effect = [(500,), (42,)]

        train_result = {
            "trained": True,
            "training_days": 120,
            "total_anomalies": 500,
            "data_mode": "all",
            "date_range": ["2026-01-01", "2026-05-01"],
        }

        with (
            patch.object(forecaster, "train", return_value=train_result) as mock_train,
            patch.object(forecaster, "save", return_value=Path("/tmp/model.pkl")) as mock_save,
            patch.object(forecaster, "_log_to_mlflow", return_value="run-abc") as mock_mlflow,
        ):
            result = forecaster.force_retrain()

        assert result["retrained"] is True
        assert result["model_path"] == str(Path("/tmp/model.pkl"))
        assert result["mlflow_run_id"] == "run-abc"
        assert result["anomalies_at_retrain"] == 500
        mock_train.assert_called_once()
        mock_save.assert_called_once()
        mock_mlflow.assert_called_once()

    # -----------------------------------------------------------------------
    # force_retrain — training returns not trained (insufficient data)
    # -----------------------------------------------------------------------

    @patch("modules.ai.forecasting.prophet_forecaster.psycopg2")
    def test_force_retrain_insufficient_data(self, mock_pg, forecaster):
        """When train() returns trained=False, the log should be marked failed."""
        _, mock_cursor = self._mock_pg(mock_pg)

        mock_cursor.fetchone.side_effect = [(50,), (1,)]

        train_result = {"trained": False, "reason": "Only 5 days of data (need 14)", "days": 5}

        with patch.object(forecaster, "train", return_value=train_result):
            result = forecaster.force_retrain()

        assert result["trained"] is False
        assert "5 days" in result["reason"]

    # -----------------------------------------------------------------------
    # force_retrain — training raises exception
    # -----------------------------------------------------------------------

    @patch("modules.ai.forecasting.prophet_forecaster.psycopg2")
    def test_force_retrain_exception(self, mock_pg, forecaster):
        """If train() raises, the retrain log should be marked failed."""
        _, mock_cursor = self._mock_pg(mock_pg)

        mock_cursor.fetchone.side_effect = [(200,), (7,)]

        with patch.object(forecaster, "train", side_effect=RuntimeError("Prophet import failed")):
            result = forecaster.force_retrain()

        assert result["retrained"] is False
        assert "Prophet import failed" in result["error"]

    # -----------------------------------------------------------------------
    # force_retrain — explicit anomalies_at_retrain skips DB count
    # -----------------------------------------------------------------------

    @patch("modules.ai.forecasting.prophet_forecaster.psycopg2")
    def test_force_retrain_explicit_count(self, mock_pg, forecaster):
        """Passing anomalies_at_retrain should skip _count_total_anomalies."""
        _, mock_cursor = self._mock_pg(mock_pg)

        # Only _insert_retrain_log fetch (no _count_total_anomalies call)
        mock_cursor.fetchone.side_effect = [(99,)]

        with (
            patch.object(
                forecaster,
                "train",
                return_value={
                    "trained": True,
                    "training_days": 30,
                    "total_anomalies": 999,
                    "data_mode": "all",
                    "date_range": ["2026-01-01", "2026-04-01"],
                },
            ),
            patch.object(forecaster, "save", return_value=Path("/tmp/m.pkl")),
            patch.object(forecaster, "_log_to_mlflow", return_value=""),
        ):
            result = forecaster.force_retrain(anomalies_at_retrain=999)

        assert result["retrained"] is True
        assert result["anomalies_at_retrain"] == 999

    # -----------------------------------------------------------------------
    # DB log helpers — insert, complete, fail
    # -----------------------------------------------------------------------

    @patch("modules.ai.forecasting.prophet_forecaster.psycopg2")
    def test_insert_retrain_log(self, mock_pg, forecaster):
        _, mock_cursor = self._mock_pg(mock_pg)
        mock_cursor.fetchone.return_value = (42,)

        log_id = forecaster._insert_retrain_log(500)

        assert log_id == 42
        # Verify INSERT was called with 'forecast' type
        insert_sql = mock_cursor.execute.call_args[0][0]
        assert "forecast" in insert_sql
        assert mock_cursor.execute.call_args[0][1] == (500,)

    @patch("modules.ai.forecasting.prophet_forecaster.psycopg2")
    def test_complete_retrain_log(self, mock_pg, forecaster):
        _, mock_cursor = self._mock_pg(mock_pg)

        forecaster._complete_retrain_log(42, "/models/prophet.pkl", "run-xyz", 3.5)

        update_sql = mock_cursor.execute.call_args[0][0]
        assert "completed" in update_sql
        assert "mlflow_run_id" in update_sql
        assert mock_cursor.execute.call_args[0][1] == ("/models/prophet.pkl", "run-xyz", 3.5, 42)

    @patch("modules.ai.forecasting.prophet_forecaster.psycopg2")
    def test_fail_retrain_log(self, mock_pg, forecaster):
        _, mock_cursor = self._mock_pg(mock_pg)

        forecaster._fail_retrain_log(7, "boom", 1.2)

        update_sql = mock_cursor.execute.call_args[0][0]
        assert "failed" in update_sql
        assert mock_cursor.execute.call_args[0][1] == ("boom", 1.2, 7)
