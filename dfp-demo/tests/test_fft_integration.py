"""
Integration Test for FFT in Inference Pipeline

Tests FFT burst detection integrated with the full DFP pipeline.
Verifies that credential spray attacks are detected via FFT analysis.

Author: Tomasz Zabek <tzabek@deloitte.co.uk>
Date: 2025-12-01
"""

import tempfile
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd
import pytest

from modules.control.control_message import ControlMessage
from modules.inference.fft_stage import FFTTimeSeriesStage
from modules.preprocessing.rolling_window import RollingWindow


class TestFFTIntegration:
    """Integration tests for FFT in the inference pipeline."""

    @pytest.fixture
    def temp_cache(self):
        """Create temporary cache directory."""
        with tempfile.TemporaryDirectory() as tmpdir:
            yield tmpdir

    @pytest.fixture
    def fft_stage(self):
        """Create FFT stage with test parameters."""
        return FFTTimeSeriesStage(
            {
                "signal_type": "event_count",
                "window": "10s",  # Very fine-grained window for testing
                "percentile": 70,  # Lower threshold for testing
                "z_threshold": 1.5,  # Lower threshold for testing
                "min_history": 5,
                "user_col": "username",
                "timestamp_col": "timestamp",
                "location_col": "location",
                "speed_col": "travel_speed_kmph",
            }
        )

    @pytest.fixture
    def rolling_window(self, temp_cache):
        """Create rolling window module."""
        return RollingWindow(
            cache_dir=temp_cache,
            timestamp_column="timestamp",
            cache_mode="batch",
            cache_to_disk=True,
            min_history=1,
            min_increment=0,
            max_history="1h",
        )

    def test_fft_detects_credential_spray(self, fft_stage, rolling_window):
        """
        Test that FFT detects credential spray attack pattern.

        Scenario:
            1. Normal login activity (5 events over 10 minutes)
            2. Credential spray burst (30 events in 2 minutes)
            3. Return to normal (5 events over 10 minutes)

        Expected: FFT detects anomalies during burst period
        """
        user_id = "attacker@company.com"
        base_time = datetime(2025, 1, 1, 10, 0, 0)

        # Generate normal baseline activity
        normal_before = []
        for i in range(5):
            event_time = base_time + timedelta(minutes=i * 2)
            normal_before.append(
                {
                    "username": user_id,
                    "timestamp": event_time,
                    "appDisplayName": "Office365",
                    "location": "New York, US",
                }
            )

        # Generate credential spray burst (50 logins in 1 minute = extreme burst)
        burst_start = base_time + timedelta(minutes=20)
        burst = []
        for i in range(50):
            event_time = burst_start + timedelta(seconds=i * 1.2)  # Every 1.2 seconds
            burst.append(
                {
                    "username": user_id,
                    "timestamp": event_time,
                    "appDisplayName": "Office365",
                    "location": "New York, US",
                }
            )

        # Generate normal activity after attack
        normal_after = []
        after_start = burst_start + timedelta(minutes=10)
        for i in range(5):
            event_time = after_start + timedelta(minutes=i * 2)
            normal_after.append(
                {
                    "username": user_id,
                    "timestamp": event_time,
                    "appDisplayName": "Office365",
                    "location": "New York, US",
                }
            )

        # Combine all events
        all_events = normal_before + burst + normal_after
        events_df = pd.DataFrame(all_events)

        # Build rolling window (accumulate all events)
        windowed_df = rolling_window.build_window(user_id=user_id, incoming_df=events_df)

        assert windowed_df is not None, "Rolling window should return data"
        assert len(windowed_df) >= 50, f"Expected at least 50 events, got {len(windowed_df)}"

        # Create ControlMessage for FFT processing
        msg = ControlMessage()
        msg.set_metadata("user_id", user_id)
        msg.payload(windowed_df)

        # Process through FFT stage
        result_msg = fft_stage.process(msg)

        # Verify FFT added detection metadata
        assert result_msg is not None, "FFT stage should return message"

        fft_anomaly_indices = result_msg.get_metadata("fft_anomaly_indices")
        fft_anomaly_count = result_msg.get_metadata("fft_anomaly_count")
        fft_stats = result_msg.get_metadata("fft_statistics")

        assert fft_anomaly_indices is not None, "FFT should detect anomalies"
        assert fft_anomaly_count > 0, f"FFT should detect burst, got {fft_anomaly_count} anomalies"
        assert fft_stats is not None, "FFT should provide statistics"

        # Verify statistics are meaningful
        assert fft_stats["signal_length"] >= 10, f"Signal too short: {fft_stats['signal_length']}"
        assert fft_stats["anomaly_count"] > 0, "No anomalies detected in burst pattern"
        assert 0 <= fft_stats["anomaly_rate"] <= 100

        print(
            f"\nFFT detected {fft_stats['anomaly_count']} anomalies "
            f"({fft_stats['anomaly_rate']:.1f}%) in credential spray burst"
        )
        print(
            f"Signal length: {fft_stats['signal_length']}, Mean: {fft_stats['signal_mean']:.2f}, Std: {fft_stats['signal_std']:.2f}"
        )

    def test_fft_no_false_positives_on_normal_traffic(self, fft_stage, rolling_window):
        """
        Test that FFT does not trigger on normal, steady traffic.

        Scenario:
            - Consistent login activity (1 event every 2 minutes for 1 hour)

        Expected: FFT detects no anomalies (or very few)
        """
        user_id = "normal_user@company.com"
        base_time = datetime(2025, 1, 1, 10, 0, 0)

        # Generate steady normal activity
        events = []
        for i in range(30):
            event_time = base_time + timedelta(minutes=i * 2)
            events.append(
                {
                    "username": user_id,
                    "timestamp": event_time,
                    "appDisplayName": "Office365",
                    "location": "London, UK",
                }
            )

        events_df = pd.DataFrame(events)

        # Build rolling window
        windowed_df = rolling_window.build_window(user_id=user_id, incoming_df=events_df)

        assert windowed_df is not None
        assert len(windowed_df) == 30

        # Create ControlMessage
        msg = ControlMessage()
        msg.set_metadata("user_id", user_id)
        msg.payload(windowed_df)

        # Process through FFT stage
        result_msg = fft_stage.process(msg)

        assert result_msg is not None

        fft_anomaly_count = result_msg.get_metadata("fft_anomaly_count")
        fft_stats = result_msg.get_metadata("fft_statistics")

        # Normal traffic should have few or no anomalies
        anomaly_count = fft_anomaly_count if fft_anomaly_count is not None else 0
        anomaly_pct = fft_stats.get("anomaly_rate", 0) if fft_stats else 0

        assert anomaly_pct < 10, f"Normal traffic should have <10% anomalies, got {anomaly_pct:.1f}%"

        print(f"\nFFT correctly identified normal traffic: {anomaly_count} anomalies ({anomaly_pct:.1f}%)")

    def test_fft_with_insufficient_data(self, fft_stage):
        """
        Test FFT handles cases with insufficient history gracefully.

        Scenario:
            - Only 3 events (below min_history threshold of 5)

        Expected: FFT skips processing, returns original message
        """
        user_id = "new_user@company.com"
        base_time = datetime(2025, 1, 1, 10, 0, 0)

        # Generate insufficient data
        events = []
        for i in range(3):
            event_time = base_time + timedelta(minutes=i)
            events.append(
                {
                    "username": user_id,
                    "timestamp": event_time,
                    "appDisplayName": "Office365",
                }
            )

        events_df = pd.DataFrame(events)

        # Create ControlMessage
        msg = ControlMessage()
        msg.set_metadata("user_id", user_id)
        msg.payload(events_df)

        # Process through FFT stage
        result_msg = fft_stage.process(msg)

        # Should return message unchanged (no FFT metadata)
        assert result_msg is not None
        fft_anomaly_count = result_msg.get_metadata("fft_anomaly_count")

        # No anomalies should be detected (insufficient history)
        assert fft_anomaly_count is None or fft_anomaly_count == 0

        print("\nFFT correctly skipped processing for insufficient data")

    def test_fft_configuration_loading(self):
        """Test FFT configuration is properly loaded from pipeline.yaml."""
        config_path = Path("config/pipeline.yaml")

        if not config_path.exists():
            pytest.skip("pipeline.yaml not found")

        import yaml

        with open(config_path) as f:
            config = yaml.safe_load(f)

        fft_config = config.get("fft", {})

        # Verify FFT configuration exists
        assert "enabled" in fft_config, "FFT config must have 'enabled' flag"
        assert "signal_type" in fft_config, "FFT config must have 'signal_type'"
        assert "window" in fft_config, "FFT config must have 'window'"
        assert "percentile" in fft_config, "FFT config must have 'percentile'"
        assert "z_threshold" in fft_config, "FFT config must have 'z_threshold'"

        # Verify valid values
        assert fft_config["signal_type"] in ["event_count", "location", "velocity"]
        assert 0 <= fft_config["percentile"] <= 100
        assert fft_config["z_threshold"] > 0

        print("\nFFT configuration valid:")
        print(f"   - Enabled: {fft_config['enabled']}")
        print(f"   - Signal: {fft_config['signal_type']}")
        print(f"   - Window: {fft_config['window']}")
        print(f"   - Percentile: {fft_config['percentile']}")
        print(f"   - Z-threshold: {fft_config['z_threshold']}")

    @pytest.mark.skipif(not Path("config/pipeline.yaml").exists(), reason="Requires pipeline configuration")
    def test_fft_stage_initialization_from_config(self):
        """Test FFT stage can be initialized from pipeline config."""
        import yaml

        config_path = Path("config/pipeline.yaml")
        with open(config_path) as f:
            config = yaml.safe_load(f)

        fft_config = config.get("fft", {})

        # Initialize FFT stage with production config
        stage = FFTTimeSeriesStage(
            {
                "signal_type": fft_config.get("signal_type", "event_count"),
                "window": fft_config.get("window", "1H"),
                "percentile": fft_config.get("percentile", 90),
                "z_threshold": fft_config.get("z_threshold", 8),
                "min_history": fft_config.get("min_history", 10),
                "user_col": "username",
                "timestamp_col": "timestamp",
                "location_col": "location",
                "speed_col": "travel_speed_kmph",
            }
        )

        assert stage is not None
        assert stage.signal_type == fft_config["signal_type"]
        assert stage.percentile == fft_config["percentile"]
        assert stage.z_threshold == fft_config["z_threshold"]

        print("\nFFT stage successfully initialized from production config")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
