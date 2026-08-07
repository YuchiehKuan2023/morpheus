"""
Unit Tests for Geographic Feature Engineering Module

Tests the geographic_features.py module following NVIDIA DFP patterns.
Validates haversine distance calculations, travel feature computation,
and impossible travel detection.

Test Coverage:
    - haversine_distance(): Distance calculation accuracy
    - calculate_travel_features(): Per-user travel feature computation
    - detect_impossible_travel(): Rule-based velocity filter
    - get_travel_statistics(): Statistical aggregation
    - Edge cases: First event, same location, zero time delta

Author: Tomasz Zabek <tzabek@deloitte.co.uk>
Date: 25 November 2025
"""

import pandas as pd
import pytest

from modules.preprocessing.geographic_features import (
    calculate_travel_features,
    detect_impossible_travel,
    get_travel_statistics,
    haversine_distance,
)


class TestHaversineDistance:
    """Test haversine distance calculation accuracy."""

    def test_london_to_paris(self):
        """Test London to Paris distance (~344 km)."""
        # London: 51.5074°N, 0.1278°W
        # Paris: 48.8566°N, 2.3522°E
        distance = haversine_distance(51.5074, -0.1278, 48.8566, 2.3522)

        # Expected: 344 km (±10 km tolerance for spherical approximation)
        assert 334 < distance < 354, f"Expected ~344 km, got {distance:.1f} km"

    def test_london_to_tokyo(self):
        """Test London to Tokyo distance (~9,561 km)."""
        # London: 51.5074°N, 0.1278°W
        # Tokyo: 35.6762°N, 139.6503°E
        distance = haversine_distance(51.5074, -0.1278, 35.6762, 139.6503)

        # Expected: 9,561 km (±100 km tolerance)
        assert 9461 < distance < 9661, f"Expected ~9,561 km, got {distance:.1f} km"

    def test_new_york_to_sydney(self):
        """Test New York to Sydney distance (~16,000 km)."""
        # New York: 40.7128°N, 74.0060°W
        # Sydney: 33.8688°S, 151.2093°E
        distance = haversine_distance(40.7128, -74.0060, -33.8688, 151.2093)

        # Expected: ~16,000 km (±200 km tolerance)
        assert 15800 < distance < 16200, f"Expected ~16,000 km, got {distance:.1f} km"

    def test_same_location(self):
        """Test distance between same coordinates (should be 0)."""
        distance = haversine_distance(51.5074, -0.1278, 51.5074, -0.1278)

        # Expected: 0 km (±0.1 km numerical precision)
        assert distance < 0.1, f"Expected ~0 km, got {distance:.1f} km"

    def test_short_distance(self):
        """Test short distance (London to Heathrow Airport ~25 km)."""
        # London: 51.5074°N, 0.1278°W
        # Heathrow: 51.4700°N, 0.4543°W
        distance = haversine_distance(51.5074, -0.1278, 51.4700, -0.4543)

        # Expected: ~25 km (±5 km tolerance)
        assert 20 < distance < 30, f"Expected ~25 km, got {distance:.1f} km"

    def test_equator_crossing(self):
        """Test distance crossing equator."""
        # Singapore: 1.3521°N, 103.8198°E
        # Jakarta: 6.2088°S, 106.8456°E
        distance = haversine_distance(1.3521, 103.8198, -6.2088, 106.8456)

        # Expected: ~890 km
        assert 850 < distance < 930, f"Expected ~890 km, got {distance:.1f} km"

    def test_invalid_latitude_too_high(self):
        """Test validation for latitude > 90."""
        with pytest.raises(ValueError, match="Latitude must be between -90 and 90"):
            haversine_distance(91.0, 0.0, 0.0, 0.0)

    def test_invalid_latitude_too_low(self):
        """Test validation for latitude < -90."""
        with pytest.raises(ValueError, match="Latitude must be between -90 and 90"):
            haversine_distance(-91.0, 0.0, 0.0, 0.0)

    def test_invalid_longitude_too_high(self):
        """Test validation for longitude > 180."""
        with pytest.raises(ValueError, match="Longitude must be between -180 and 180"):
            haversine_distance(0.0, 181.0, 0.0, 0.0)

    def test_invalid_longitude_too_low(self):
        """Test validation for longitude < -180."""
        with pytest.raises(ValueError, match="Longitude must be between -180 and 180"):
            haversine_distance(0.0, -181.0, 0.0, 0.0)


class TestCalculateTravelFeatures:
    """Test travel feature calculation."""

    def test_single_user_two_events(self):
        """Test basic two-event scenario."""
        df = pd.DataFrame(
            {
                "username": ["alice@contoso.com", "alice@contoso.com"],
                "timestamp": ["2025-11-25 10:00:00", "2025-11-25 10:15:00"],
                "location_geoCoordinates_latitude": [51.5074, 35.6762],
                "location_geoCoordinates_longitude": [-0.1278, 139.6503],
            }
        )

        result = calculate_travel_features(df)

        # First event: no previous location
        assert result["distance_km"].iloc[0] == 0.0
        assert result["ts_delta_hour"].iloc[0] == 0.0
        assert result["travel_speed_kmph"].iloc[0] == 0.0

        # Second event: London to Tokyo in 15 minutes
        assert 9461 < result["distance_km"].iloc[1] < 9661  # ~9,561 km
        assert 0.24 < result["ts_delta_hour"].iloc[1] < 0.26  # ~0.25 hours (15 min)
        assert 38000 < result["travel_speed_kmph"].iloc[1] < 39000  # ~38,244 km/h

    def test_multiple_users(self):
        """Test per-user calculation with multiple users."""
        df = pd.DataFrame(
            {
                "username": ["alice@contoso.com", "alice@contoso.com", "bob@contoso.com", "bob@contoso.com"],
                "timestamp": [
                    "2025-11-25 10:00:00",
                    "2025-11-25 11:30:00",
                    "2025-11-25 10:00:00",
                    "2025-11-25 10:30:00",
                ],
                "location_geoCoordinates_latitude": [
                    51.5074,
                    48.8566,  # Alice: London → Paris
                    40.7128,
                    -33.8688,
                ],  # Bob: NY → Sydney
                "location_geoCoordinates_longitude": [-0.1278, 2.3522, -74.0060, 151.2093],
            }
        )

        result = calculate_travel_features(df)

        # Alice second event: London → Paris in 1.5 hours (~98 km/h, normal train)
        alice_row = result[
            (result["username"] == "alice@contoso.com") & (result["timestamp"] == "2025-11-25 11:30:00")
        ].iloc[0]
        assert 334 < alice_row["distance_km"] < 354  # ~344 km
        assert 1.4 < alice_row["ts_delta_hour"] < 1.6  # ~1.5 hours
        assert 95 < alice_row["travel_speed_kmph"] < 240  # ~98 km/h

        # Bob second event: NY → Sydney in 0.5 hours (~32,000 km/h, impossible)
        bob_row = result[
            (result["username"] == "bob@contoso.com") & (result["timestamp"] == "2025-11-25 10:30:00")
        ].iloc[0]
        assert 15800 < bob_row["distance_km"] < 16200  # ~16,000 km
        assert 0.4 < bob_row["ts_delta_hour"] < 0.6  # ~0.5 hours
        assert 30000 < bob_row["travel_speed_kmph"] < 34000  # ~32,000 km/h

    def test_same_location(self):
        """Test events from same location (zero distance)."""
        df = pd.DataFrame(
            {
                "username": ["alice@contoso.com", "alice@contoso.com"],
                "timestamp": ["2025-11-25 10:00:00", "2025-11-25 10:30:00"],
                "location_geoCoordinates_latitude": [51.5074, 51.5074],
                "location_geoCoordinates_longitude": [-0.1278, -0.1278],
            }
        )

        result = calculate_travel_features(df)

        # Second event: same location → zero distance, zero speed
        assert result["distance_km"].iloc[1] < 0.1  # ~0 km
        assert result["travel_speed_kmph"].iloc[1] == 0.0  # 0 km/h

    def test_zero_time_delta(self):
        """Test events with same timestamp (zero time delta)."""
        df = pd.DataFrame(
            {
                "username": ["alice@contoso.com", "alice@contoso.com"],
                "timestamp": ["2025-11-25 10:00:00", "2025-11-25 10:00:00"],
                "location_geoCoordinates_latitude": [51.5074, 48.8566],
                "location_geoCoordinates_longitude": [-0.1278, 2.3522],
            }
        )

        result = calculate_travel_features(df)

        # Second event: same timestamp → zero time delta, zero speed
        assert result["ts_delta_hour"].iloc[1] == 0.0
        assert result["travel_speed_kmph"].iloc[1] == 0.0  # Avoid division by zero

    def test_missing_columns(self):
        """Test error handling for missing columns."""
        df = pd.DataFrame(
            {
                "username": ["alice@contoso.com"],
                "timestamp": ["2025-11-25 10:00:00"],
                # Missing: latitude, longitude
            }
        )

        with pytest.raises(ValueError, match="Missing required columns"):
            calculate_travel_features(df)

    def test_empty_dataframe(self):
        """Test handling of empty DataFrame."""
        df = pd.DataFrame(
            {
                "username": [],
                "timestamp": [],
                "location_geoCoordinates_latitude": [],
                "location_geoCoordinates_longitude": [],
            }
        )

        result = calculate_travel_features(df)

        assert len(result) == 0
        assert "distance_km" in result.columns
        assert "travel_speed_kmph" in result.columns

    def test_single_event_per_user(self):
        """Test user with only one event (no travel features)."""
        df = pd.DataFrame(
            {
                "username": ["alice@contoso.com"],
                "timestamp": ["2025-11-25 10:00:00"],
                "location_geoCoordinates_latitude": [51.5074],
                "location_geoCoordinates_longitude": [-0.1278],
            }
        )

        result = calculate_travel_features(df)

        assert result["distance_km"].iloc[0] == 0.0
        assert result["ts_delta_hour"].iloc[0] == 0.0
        assert result["travel_speed_kmph"].iloc[0] == 0.0


class TestDetectImpossibleTravel:
    """Test impossible travel detection."""

    def test_impossible_travel_detected(self):
        """Test detection of impossible travel (London → Tokyo in 15 min)."""
        df = pd.DataFrame(
            {
                "username": ["alice@contoso.com", "alice@contoso.com"],
                "timestamp": ["2025-11-25 10:00:00", "2025-11-25 10:15:00"],
                "location_geoCoordinates_latitude": [51.5074, 35.6762],
                "location_geoCoordinates_longitude": [-0.1278, 139.6503],
            }
        )

        df = calculate_travel_features(df)
        df = detect_impossible_travel(df)

        # First event: no travel
        assert df["impossible_travel"].iloc[0] == False  # noqa: E712 - explicit False check for clarity

        # Second event: impossible travel (38,244 km/h > 800 km/h threshold)
        assert df["impossible_travel"].iloc[1] == True  # noqa: E712 - explicit True check for clarity

    def test_normal_travel_not_flagged(self):
        """Test normal travel is not flagged (London → Paris by train)."""
        df = pd.DataFrame(
            {
                "username": ["alice@contoso.com", "alice@contoso.com"],
                "timestamp": ["2025-11-25 08:00:00", "2025-11-25 11:30:00"],
                "location_geoCoordinates_latitude": [51.5074, 48.8566],
                "location_geoCoordinates_longitude": [-0.1278, 2.3522],
            }
        )

        df = calculate_travel_features(df)
        df = detect_impossible_travel(df)

        # Both events: normal travel (~98 km/h < 800 km/h threshold)
        assert df["impossible_travel"].iloc[0] == False  # noqa: E712 - explicit False check for clarity
        assert df["impossible_travel"].iloc[1] == False  # noqa: E712 - explicit False check for clarity

    def test_fast_travel_below_threshold(self):
        """Test fast travel below threshold (high-speed rail, 350 km/h)."""
        # Beijing to Shanghai: ~1,200 km in 3.5 hours = ~343 km/h (high-speed rail)
        df = pd.DataFrame(
            {
                "username": ["alice@contoso.com", "alice@contoso.com"],
                "timestamp": ["2025-11-25 08:00:00", "2025-11-25 11:30:00"],
                "location_geoCoordinates_latitude": [39.9042, 31.2304],  # Beijing → Shanghai
                "location_geoCoordinates_longitude": [116.4074, 121.4737],
                "distance_km": [0.0, 1200.0],
                "ts_delta_hour": [0.0, 3.5],
                "travel_speed_kmph": [0.0, 343.0],
            }
        )

        df = detect_impossible_travel(df)

        # 343 km/h < 800 km/h threshold → not flagged
        assert df["impossible_travel"].iloc[1] == False  # noqa: E712 - explicit False check for clarity

    def test_short_distance_ignored(self):
        """Test short distance travel ignored even if high speed."""
        # 100 km in 5 minutes = 1,200 km/h (but distance < 500 km threshold)
        df = pd.DataFrame(
            {
                "username": ["alice@contoso.com", "alice@contoso.com"],
                "timestamp": ["2025-11-25 10:00:00", "2025-11-25 10:05:00"],
                "location_geoCoordinates_latitude": [51.5074, 51.5074],
                "location_geoCoordinates_longitude": [-0.1278, 0.8],
                "distance_km": [0.0, 100.0],
                "ts_delta_hour": [0.0, 0.083],
                "travel_speed_kmph": [0.0, 1200.0],
            }
        )

        df = detect_impossible_travel(df, distance_threshold=500)

        # High speed but short distance → not flagged (data quality issue, not security)
        assert df["impossible_travel"].iloc[1] == False  # noqa: E712 - explicit False check for clarity

    def test_custom_threshold(self):
        """Test custom speed threshold."""
        df = pd.DataFrame(
            {
                "username": ["alice@contoso.com", "alice@contoso.com"],
                "timestamp": ["2025-11-25 10:00:00", "2025-11-25 11:00:00"],
                "location_geoCoordinates_latitude": [51.5074, 48.8566],
                "location_geoCoordinates_longitude": [-0.1278, 2.3522],
                "distance_km": [0.0, 344.0],
                "ts_delta_hour": [0.0, 1.0],
                "travel_speed_kmph": [0.0, 344.0],
            }
        )

        # Default threshold (800 km/h): not flagged
        df1 = detect_impossible_travel(df.copy(), speed_threshold=800)
        assert df1["impossible_travel"].iloc[1] == False  # noqa: E712 - explicit False check for clarity

        # Low threshold (300 km/h) with distance_threshold=0: flagged
        # Note: distance_threshold=0 allows testing speed independently
        df2 = detect_impossible_travel(df.copy(), speed_threshold=300, distance_threshold=0)
        assert df2["impossible_travel"].iloc[1] == True  # noqa: E712 - explicit True check for clarity

    def test_missing_travel_features(self):
        """Test handling of missing travel feature columns."""
        df = pd.DataFrame(
            {
                "username": ["alice@contoso.com"],
                "timestamp": ["2025-11-25 10:00:00"],
                # Missing: distance_km, travel_speed_kmph
            }
        )

        result = detect_impossible_travel(df)

        # Should add impossible_travel column with False values
        assert "impossible_travel" in result.columns
        assert result["impossible_travel"].iloc[0] == False  # noqa: E712 - explicit False check for clarity


class TestGetTravelStatistics:
    """Test travel statistics computation."""

    def test_basic_statistics(self):
        """Test basic statistical aggregation."""
        df = pd.DataFrame(
            {
                "username": ["alice", "alice", "alice", "alice"],
                "timestamp": ["2025-11-25 08:00", "2025-11-25 09:00", "2025-11-25 10:00", "2025-11-25 11:00"],
                "location_geoCoordinates_latitude": [51.5074, 51.5074, 48.8566, 48.8566],
                "location_geoCoordinates_longitude": [-0.1278, -0.1278, 2.3522, 2.3522],
            }
        )

        df = calculate_travel_features(df)
        df = detect_impossible_travel(df)
        stats = get_travel_statistics(df)

        # Verify expected keys
        assert "mean_speed" in stats
        assert "max_speed" in stats
        assert "impossible_rate" in stats

        # One travel event (London to Paris, ~344 km/h)
        assert stats["max_distance"] > 300
        assert stats["impossible_rate"] == 0.0

    def test_impossible_travel_rate(self):
        """Test impossible travel rate calculation."""
        df = pd.DataFrame(
            {
                "username": ["alice", "alice", "alice"],
                "timestamp": ["2025-11-25 10:00", "2025-11-25 10:15", "2025-11-25 10:30"],
                "location_geoCoordinates_latitude": [51.5074, 35.6762, 51.5074],
                "location_geoCoordinates_longitude": [-0.1278, 139.6503, -0.1278],
            }
        )

        df = calculate_travel_features(df)
        df = detect_impossible_travel(df)
        stats = get_travel_statistics(df)

        # 2 out of 3 events have impossible travel (66.67%)
        assert 60 < stats["impossible_rate"] < 70

    def test_empty_dataframe(self):
        """Test statistics with empty DataFrame."""
        df = pd.DataFrame({"username": [], "travel_speed_kmph": [], "distance_km": []})

        stats = get_travel_statistics(df)

        # All statistics should be 0
        assert stats["mean_speed"] == 0.0
        assert stats["max_speed"] == 0.0
        assert stats["impossible_rate"] == 0.0

    def test_no_travel_events(self):
        """Test statistics with only zero-speed events."""
        df = pd.DataFrame(
            {
                "username": ["alice", "alice"],
                "timestamp": ["2025-11-25 10:00", "2025-11-25 10:30"],
                "location_geoCoordinates_latitude": [51.5074, 51.5074],
                "location_geoCoordinates_longitude": [-0.1278, -0.1278],
            }
        )

        df = calculate_travel_features(df)
        stats = get_travel_statistics(df)

        # No travel → all zero
        assert stats["mean_speed"] == 0.0
        assert stats["max_speed"] == 0.0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
