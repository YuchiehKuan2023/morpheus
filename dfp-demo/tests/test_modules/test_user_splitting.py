"""
Unit Tests for User Splitting Module

Tests the UserSplitter class and user splitting functionality.
"""

import pandas as pd
import pytest

from modules.preprocessing import UserSplitter, split_dataframe_by_user


@pytest.fixture
def sample_multi_user_data():
    """Create sample data with multiple users."""
    data = {
        "timestamp": pd.to_datetime(
            [
                "2024-01-01 10:00:00",
                "2024-01-01 11:00:00",
                "2024-01-01 12:00:00",
                "2024-01-01 10:30:00",
                "2024-01-01 11:30:00",
                "2024-01-01 13:00:00",
            ],
            utc=True,
        ),
        "username": [
            "alice@company.com",
            "bob@company.com",
            "alice@company.com",
            "charlie@company.com",
            "alice@company.com",
            "bob@company.com",
        ],
        "action": ["login", "login", "logout", "login", "read", "logout"],
        "value": [1, 2, 3, 4, 5, 6],
    }
    return pd.DataFrame(data)


class TestUserSplitter:
    """Test UserSplitter class"""

    def test_initialization_defaults(self):
        """Test UserSplitter initialization with defaults"""
        splitter = UserSplitter()

        assert splitter.userid_column == "username"
        assert splitter.fallback_username == "generic_user"
        assert splitter.include_generic is False
        assert splitter.include_individual is True
        assert splitter.skip_users == []
        assert splitter.only_users == []
        assert splitter.timestamp_column == "timestamp"
        assert len(splitter._user_index_map) == 0

    def test_initialization_custom(self):
        """Test UserSplitter initialization with custom parameters"""
        splitter = UserSplitter(
            userid_column="user_id",
            fallback_username="generic",
            include_generic=True,
            include_individual=False,
            skip_users=["user1", "user2"],
            only_users=["user3"],
            timestamp_column="event_time",
        )

        assert splitter.userid_column == "user_id"
        assert splitter.fallback_username == "generic"
        assert splitter.include_generic is True
        assert splitter.include_individual is False
        assert splitter.skip_users == ["user1", "user2"]
        assert splitter.only_users == ["user3"]
        assert splitter.timestamp_column == "event_time"

    def test_split_individual_users(self, sample_multi_user_data):
        """Test splitting into individual users"""
        splitter = UserSplitter(include_generic=False, include_individual=True)
        user_dfs = splitter.split_users(sample_multi_user_data)

        # Should have 3 individual users
        assert len(user_dfs) == 3
        assert "alice@company.com" in user_dfs
        assert "bob@company.com" in user_dfs
        assert "charlie@company.com" in user_dfs

        # Check row counts
        assert len(user_dfs["alice@company.com"]) == 3
        assert len(user_dfs["bob@company.com"]) == 2
        assert len(user_dfs["charlie@company.com"]) == 1

    def test_split_generic_only(self, sample_multi_user_data):
        """Test splitting into generic user only"""
        splitter = UserSplitter(include_generic=True, include_individual=False)
        user_dfs = splitter.split_users(sample_multi_user_data)

        # Should have only generic user
        assert len(user_dfs) == 1
        assert "generic_user" in user_dfs
        assert len(user_dfs["generic_user"]) == 6

    def test_split_both_generic_and_individual(self, sample_multi_user_data):
        """Test splitting into both generic and individual users"""
        splitter = UserSplitter(include_generic=True, include_individual=True)
        user_dfs = splitter.split_users(sample_multi_user_data)

        # Should have generic + 3 individual users
        assert len(user_dfs) == 4
        assert "generic_user" in user_dfs
        assert "alice@company.com" in user_dfs
        assert "bob@company.com" in user_dfs
        assert "charlie@company.com" in user_dfs

        # Generic user should have all rows
        assert len(user_dfs["generic_user"]) == 6

    def test_skip_users(self, sample_multi_user_data):
        """Test skip_users filtering"""
        splitter = UserSplitter(include_individual=True, skip_users=["bob@company.com"])
        user_dfs = splitter.split_users(sample_multi_user_data)

        # Should have 2 users (bob skipped)
        assert len(user_dfs) == 2
        assert "alice@company.com" in user_dfs
        assert "charlie@company.com" in user_dfs
        assert "bob@company.com" not in user_dfs

    def test_only_users(self, sample_multi_user_data):
        """Test only_users filtering"""
        splitter = UserSplitter(include_individual=True, only_users=["alice@company.com", "bob@company.com"])
        user_dfs = splitter.split_users(sample_multi_user_data)

        # Should have only 2 users
        assert len(user_dfs) == 2
        assert "alice@company.com" in user_dfs
        assert "bob@company.com" in user_dfs
        assert "charlie@company.com" not in user_dfs

    def test_monotonic_indexes(self, sample_multi_user_data):
        """Test that indexes are monotonic and increasing"""
        splitter = UserSplitter(include_individual=True)
        user_dfs = splitter.split_users(sample_multi_user_data)

        # Check alice's indexes start at 0
        alice_df = user_dfs["alice@company.com"]
        assert alice_df.index.tolist() == [0, 1, 2]

        # Check bob's indexes start at 0
        bob_df = user_dfs["bob@company.com"]
        assert bob_df.index.tolist() == [0, 1]

        # Split again with same splitter
        user_dfs_2 = splitter.split_users(sample_multi_user_data)

        # Indexes should continue from previous count
        alice_df_2 = user_dfs_2["alice@company.com"]
        assert alice_df_2.index.tolist() == [3, 4, 5]  # Continues from 3

        bob_df_2 = user_dfs_2["bob@company.com"]
        assert bob_df_2.index.tolist() == [2, 3]  # Continues from 2

    def test_timestamp_sorting(self):
        """Test that data is sorted by timestamp"""
        # Create out-of-order data
        data = {
            "timestamp": pd.to_datetime(
                [
                    "2024-01-01 12:00:00",  # Later
                    "2024-01-01 10:00:00",  # Earlier
                    "2024-01-01 11:00:00",  # Middle
                ],
                utc=True,
            ),
            "username": ["alice", "alice", "alice"],
            "value": [3, 1, 2],
        }
        df = pd.DataFrame(data)

        splitter = UserSplitter(include_individual=True)
        user_dfs = splitter.split_users(df)

        alice_df = user_dfs["alice"]
        # Should be sorted by timestamp
        assert alice_df["value"].tolist() == [1, 2, 3]
        assert alice_df["timestamp"].is_monotonic_increasing

    def test_empty_dataframe(self):
        """Test handling of empty DataFrame"""
        empty_df = pd.DataFrame(columns=["timestamp", "username", "value"])

        splitter = UserSplitter(include_individual=True)
        user_dfs = splitter.split_users(empty_df)

        assert len(user_dfs) == 0

    def test_none_dataframe(self):
        """Test handling of None DataFrame"""
        splitter = UserSplitter(include_individual=True)
        # Type ignore since we're testing error handling
        user_dfs = splitter.split_users(None)  # type: ignore

        assert len(user_dfs) == 0

    def test_missing_userid_column(self, sample_multi_user_data):
        """Test error when userid_column not in DataFrame"""
        splitter = UserSplitter(userid_column="nonexistent_column")

        with pytest.raises(ValueError, match="userid_column 'nonexistent_column' not found"):
            splitter.split_users(sample_multi_user_data)

    def test_user_stats_tracking(self, sample_multi_user_data):
        """Test get_user_stats method"""
        splitter = UserSplitter(include_individual=True)
        splitter.split_users(sample_multi_user_data)

        stats = splitter.get_user_stats()
        assert stats["alice@company.com"] == 3
        assert stats["bob@company.com"] == 2
        assert stats["charlie@company.com"] == 1

    def test_reset_user_tracking(self, sample_multi_user_data):
        """Test reset_user_tracking method"""
        splitter = UserSplitter(include_individual=True)

        # First split
        user_dfs_1 = splitter.split_users(sample_multi_user_data)
        assert user_dfs_1["alice@company.com"].index[0] == 0

        # Reset tracking
        splitter.reset_user_tracking()

        # Second split should start from 0 again
        user_dfs_2 = splitter.split_users(sample_multi_user_data)
        assert user_dfs_2["alice@company.com"].index[0] == 0

    def test_generic_with_skip_users(self, sample_multi_user_data):
        """Test that skip_users affects generic user"""
        splitter = UserSplitter(include_generic=True, include_individual=False, skip_users=["bob@company.com"])
        user_dfs = splitter.split_users(sample_multi_user_data)

        # Generic user should exclude bob's rows
        generic_df = user_dfs["generic_user"]
        assert len(generic_df) == 4  # 6 total - 2 bob rows
        assert "bob@company.com" not in generic_df["username"].values

    def test_custom_fallback_username(self, sample_multi_user_data):
        """Test custom fallback_username"""
        splitter = UserSplitter(include_generic=True, include_individual=False, fallback_username="all_users")
        user_dfs = splitter.split_users(sample_multi_user_data)

        assert "all_users" in user_dfs
        assert len(user_dfs["all_users"]) == 6

    def test_single_user_dataframe(self):
        """Test with DataFrame containing only one user"""
        data = {
            "timestamp": pd.to_datetime(["2024-01-01", "2024-01-02"], utc=True),
            "username": ["alice", "alice"],
            "value": [1, 2],
        }
        df = pd.DataFrame(data)

        splitter = UserSplitter(include_individual=True)
        user_dfs = splitter.split_users(df)

        assert len(user_dfs) == 1
        assert "alice" in user_dfs
        assert len(user_dfs["alice"]) == 2

    def test_filter_all_users_out(self, sample_multi_user_data):
        """Test when all users are filtered out"""
        splitter = UserSplitter(include_individual=True, only_users=["nonexistent_user"])
        user_dfs = splitter.split_users(sample_multi_user_data)

        assert len(user_dfs) == 0


class TestSplitDataframeByUser:
    """Test split_dataframe_by_user convenience function"""

    def test_basic_split(self, sample_multi_user_data):
        """Test basic split functionality"""
        user_dfs = split_dataframe_by_user(sample_multi_user_data, include_individual=True)

        assert len(user_dfs) == 3
        assert "alice@company.com" in user_dfs
        assert "bob@company.com" in user_dfs
        assert "charlie@company.com" in user_dfs

    def test_with_generic_user(self, sample_multi_user_data):
        """Test split with generic user"""
        user_dfs = split_dataframe_by_user(
            sample_multi_user_data, include_generic=True, include_individual=True, fallback_username="generic"
        )

        assert len(user_dfs) == 4
        assert "generic" in user_dfs
        assert len(user_dfs["generic"]) == 6

    def test_with_filters(self, sample_multi_user_data):
        """Test split with user filters"""
        user_dfs = split_dataframe_by_user(
            sample_multi_user_data, include_individual=True, skip_users=["charlie@company.com"]
        )

        assert len(user_dfs) == 2
        assert "charlie@company.com" not in user_dfs

    def test_stateless_behavior(self, sample_multi_user_data):
        """Test that function is stateless (indexes always start at 0)"""
        # First call
        user_dfs_1 = split_dataframe_by_user(sample_multi_user_data, include_individual=True)

        # Second call
        user_dfs_2 = split_dataframe_by_user(sample_multi_user_data, include_individual=True)

        # Both should start at index 0 (stateless)
        assert user_dfs_1["alice@company.com"].index[0] == 0
        assert user_dfs_2["alice@company.com"].index[0] == 0


class TestEdgeCases:
    """Test edge cases and error conditions"""

    def test_neither_generic_nor_individual(self, sample_multi_user_data):
        """Test when neither include_generic nor include_individual is True"""
        splitter = UserSplitter(include_generic=False, include_individual=False)
        user_dfs = splitter.split_users(sample_multi_user_data)

        # Should return empty dict
        assert len(user_dfs) == 0

    def test_both_skip_and_only_users(self, sample_multi_user_data):
        """Test when both skip_users and only_users are specified"""
        # Should apply skip first, then only
        splitter = UserSplitter(
            include_individual=True, skip_users=["bob@company.com"], only_users=["alice@company.com", "bob@company.com"]
        )
        user_dfs = splitter.split_users(sample_multi_user_data)

        # Only alice should remain (bob skipped before only filter)
        assert len(user_dfs) == 1
        assert "alice@company.com" in user_dfs

    def test_missing_timestamp_column(self, sample_multi_user_data):
        """Test with DataFrame missing timestamp column"""
        df = sample_multi_user_data.drop(columns=["timestamp"])

        splitter = UserSplitter(include_individual=True, timestamp_column="timestamp")
        # Should still work, just without sorting
        user_dfs = splitter.split_users(df)

        assert len(user_dfs) == 3

    def test_string_timestamps(self):
        """Test that string timestamps are converted to datetime"""
        data = {
            "timestamp": ["2024-01-01 12:00:00", "2024-01-01 10:00:00"],
            "username": ["alice", "alice"],
            "value": [2, 1],
        }
        df = pd.DataFrame(data)

        splitter = UserSplitter(include_individual=True)
        user_dfs = splitter.split_users(df)

        alice_df = user_dfs["alice"]
        # Should be sorted by converted timestamp
        assert alice_df["value"].tolist() == [1, 2]

    def test_large_user_count(self):
        """Test with many users"""
        num_users = 100
        rows_per_user = 10

        data = {
            "timestamp": pd.to_datetime(
                [f"2024-01-{(i % 30) + 1:02d} {(i % 24):02d}:00:00" for i in range(rows_per_user * num_users)], utc=True
            ),
            "username": [f"user_{i // rows_per_user}" for i in range(rows_per_user * num_users)],
            "value": list(range(rows_per_user * num_users)),
        }
        df = pd.DataFrame(data)

        splitter = UserSplitter(include_individual=True)
        user_dfs = splitter.split_users(df)

        assert len(user_dfs) == num_users
        for i in range(num_users):
            assert f"user_{i}" in user_dfs
            assert len(user_dfs[f"user_{i}"]) == rows_per_user

    def test_unicode_usernames(self):
        """Test with unicode characters in usernames"""
        data = {
            "timestamp": pd.to_datetime(["2024-01-01", "2024-01-02"], utc=True),
            "username": ["用户α", "用户β"],
            "value": [1, 2],
        }
        df = pd.DataFrame(data)

        splitter = UserSplitter(include_individual=True)
        user_dfs = splitter.split_users(df)

        assert len(user_dfs) == 2
        assert "用户α" in user_dfs
        assert "用户β" in user_dfs
