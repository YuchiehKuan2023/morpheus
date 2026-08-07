"""
User Splitting Module for DFP Pipeline

This module splits incoming DataFrames by user_id, creating separate DataFrames for each user.
Follows NVIDIA Morpheus DFP architecture from:
- python/morpheus_dfp/morpheus_dfp/stages/dfp_split_users_stage.py
- python/morpheus_dfp/morpheus_dfp/modules/dfp_split_users.py

Key Features:
- Split data by user_id (username)
- Optional generic user (combines all users)
- Optional individual users (separate DataFrame per user)
- User filtering (skip_users, only_users)
- Monotonic index tracking per user
"""

import logging

import pandas as pd

logger = logging.getLogger(f"morpheus.{__name__}")


class UserSplitter:
    """
    Split DataFrames by user_id into individual user DataFrames.

    This class handles splitting a single DataFrame containing multiple users
    into separate DataFrames for each user. Supports generic user (all users combined)
    and individual user splitting, with optional user filtering.

    Parameters
    ----------
    userid_column : str
        Column name containing user IDs (default: "username")
    fallback_username : str
        Username to use for generic user (default: "generic_user")
    include_generic : bool
        Whether to include a generic user combining all data (default: False)
    include_individual : bool
        Whether to split data into individual users (default: True)
    skip_users : List[str], optional
        List of user IDs to exclude from output
    only_users : List[str], optional
        List of user IDs to include (mutually exclusive with skip_users)
    timestamp_column : str
        Column name containing timestamps for sorting (default: "timestamp")

    Examples
    --------
    >>> splitter = UserSplitter(
    ...     userid_column="username",
    ...     include_generic=False,
    ...     include_individual=True
    ... )
    >>> user_dfs = splitter.split_users(df)
    >>> for user_id, user_df in user_dfs.items():
    ...     print(f"User {user_id}: {len(user_df)} rows")
    """

    def __init__(
        self,
        userid_column: str = "username",
        fallback_username: str = "generic_user",
        include_generic: bool = False,
        include_individual: bool = True,
        skip_users: list[str] | None = None,
        only_users: list[str] | None = None,
        timestamp_column: str = "timestamp",
    ):
        self.userid_column = userid_column
        self.fallback_username = fallback_username
        self.include_generic = include_generic
        self.include_individual = include_individual
        self.skip_users = skip_users or []
        self.only_users = only_users or []
        self.timestamp_column = timestamp_column

        # Track row counts per user for monotonic indexing
        self._user_index_map: dict[str, int] = {}

        # Validation
        if self.skip_users and self.only_users:
            logger.warning(
                "Both skip_users and only_users specified. skip_users will be applied first, then only_users filter."
            )

        if not self.include_generic and not self.include_individual:
            logger.warning(
                "Neither include_generic nor include_individual is True. No user DataFrames will be generated."
            )

    def split_users(self, df: pd.DataFrame) -> dict[str, pd.DataFrame]:
        """
        Split DataFrame by user_id.

        Parameters
        ----------
        df : pd.DataFrame
            Input DataFrame with multiple users

        Returns
        -------
        Dict[str, pd.DataFrame]
            Dictionary mapping user_id to user DataFrame

        Examples
        --------
        >>> df = pd.DataFrame({
        ...     'timestamp': ['2024-01-01', '2024-01-02', '2024-01-03'],
        ...     'username': ['alice', 'bob', 'alice'],
        ...     'value': [1, 2, 3]
        ... })
        >>> splitter = UserSplitter(include_individual=True)
        >>> user_dfs = splitter.split_users(df)
        >>> list(user_dfs.keys())
        ['alice', 'bob']
        """
        if df is None or df.empty:
            logger.warning("Empty DataFrame provided to split_users")
            return {}

        # Validate required columns
        if self.userid_column not in df.columns:
            raise ValueError(
                f"userid_column '{self.userid_column}' not found in DataFrame. Available columns: {df.columns.tolist()}"
            )

        logger.info(
            f"Splitting {len(df)} rows by user_id. "
            f"include_generic={self.include_generic}, include_individual={self.include_individual}"
        )

        # Make a copy to avoid modifying original
        df_filtered = df.copy()

        # Apply user filtering
        df_filtered = self._apply_user_filters(df_filtered)

        if df_filtered.empty:
            logger.warning("All users filtered out, returning empty result")
            return {}

        # Sort by timestamp if available to ensure chronological order
        if self.timestamp_column in df_filtered.columns:
            # Ensure timestamp is datetime
            if not pd.api.types.is_datetime64_any_dtype(df_filtered[self.timestamp_column]):
                df_filtered[self.timestamp_column] = pd.to_datetime(
                    df_filtered[self.timestamp_column], utc=True, errors="coerce"
                )
            # Save original index for restoration
            saved_index_name = df_filtered.index.name
            df_filtered.index.name = "_original_idx"
            # Sort by timestamp then original index
            df_filtered = df_filtered.sort_values(by=[self.timestamp_column, "_original_idx"])
            df_filtered.index.name = saved_index_name

        # Split into user DataFrames
        split_dfs = self._split_by_user(df_filtered)

        # Reset indexes to be monotonic per user
        split_dfs = self._reset_user_indexes(split_dfs)

        if split_dfs:
            logger.info(
                f"Split complete: {len(split_dfs)} users, "
                f"rows per user: min={min(len(udf) for udf in split_dfs.values())}, "
                f"max={max(len(udf) for udf in split_dfs.values())}, "
                f"avg={sum(len(udf) for udf in split_dfs.values()) / len(split_dfs):.1f}"
            )
        else:
            logger.info("Split complete: 0 users (no data to split)")

        return split_dfs

    def _apply_user_filters(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Apply skip_users and only_users filters.

        Parameters
        ----------
        df : pd.DataFrame
            Input DataFrame

        Returns
        -------
        pd.DataFrame
            Filtered DataFrame
        """
        original_count = len(df)

        # Apply skip_users filter
        if self.skip_users:
            df = df[~df[self.userid_column].isin(self.skip_users)]
            skipped = original_count - len(df)
            if skipped > 0:
                logger.debug(f"Skipped {skipped} rows from {len(self.skip_users)} users")

        # Apply only_users filter
        if self.only_users:
            intermediate_count = len(df)
            df = df[df[self.userid_column].isin(self.only_users)]
            filtered = intermediate_count - len(df)
            if filtered > 0:
                logger.debug(f"Filtered out {filtered} rows not in only_users list")

        return df

    def _split_by_user(self, df: pd.DataFrame) -> dict[str, pd.DataFrame]:
        """
        Split DataFrame into user-specific DataFrames.

        Parameters
        ----------
        df : pd.DataFrame
            Filtered and sorted DataFrame

        Returns
        -------
        Dict[str, pd.DataFrame]
            Dictionary of user DataFrames
        """
        split_dfs: dict[str, pd.DataFrame] = {}

        # Generic user: all data combined
        if self.include_generic:
            # Make a copy for generic user
            generic_df = df.copy()
            split_dfs[self.fallback_username] = generic_df
            logger.debug(f"Created generic user '{self.fallback_username}' with {len(generic_df)} rows")

        # Individual users: split by userid_column
        if self.include_individual:
            # Group by user and create separate DataFrames
            for user_id, user_df in df.groupby(self.userid_column, sort=False):
                # Make a copy to avoid SettingWithCopyWarning
                user_df_copy = user_df.copy()
                # Convert user_id to string to satisfy type checker
                split_dfs[str(user_id)] = user_df_copy
                logger.debug(f"Created user DataFrame for '{user_id}' with {len(user_df_copy)} rows")

        return split_dfs

    def _reset_user_indexes(self, split_dfs: dict[str, pd.DataFrame]) -> dict[str, pd.DataFrame]:
        """
        Reset DataFrame indexes to be monotonic and increasing per user.

        This ensures each user's data has indexes starting from their current count
        and incrementing, maintaining consistency across multiple batches.

        Parameters
        ----------
        split_dfs : Dict[str, pd.DataFrame]
            Dictionary of user DataFrames

        Returns
        -------
        Dict[str, pd.DataFrame]
            Dictionary with reset indexes
        """
        result_dfs: dict[str, pd.DataFrame] = {}

        for user_id, user_df in split_dfs.items():
            # Get current count for this user
            current_count = self._user_index_map.get(user_id, 0)

            # Create new monotonic index
            new_index = range(current_count, current_count + len(user_df))  # noqa: F841 - kept for documentation
            user_df.index = pd.RangeIndex(start=current_count, stop=current_count + len(user_df))

            # Update tracking
            self._user_index_map[user_id] = current_count + len(user_df)

            result_dfs[user_id] = user_df

            logger.debug(f"Reset index for user '{user_id}': range [{current_count}, {current_count + len(user_df)})")

        return result_dfs

    def get_user_stats(self) -> dict[str, int]:
        """
        Get statistics about processed users.

        Returns
        -------
        Dict[str, int]
            Dictionary mapping user_id to total row count processed
        """
        return self._user_index_map.copy()

    def reset_user_tracking(self):
        """Reset the user index tracking (useful for new batches)."""
        self._user_index_map.clear()
        logger.debug("Reset user index tracking")


def split_dataframe_by_user(
    df: pd.DataFrame,
    userid_column: str = "username",
    fallback_username: str = "generic_user",
    include_generic: bool = False,
    include_individual: bool = True,
    skip_users: list[str] | None = None,
    only_users: list[str] | None = None,
    timestamp_column: str = "timestamp",
) -> dict[str, pd.DataFrame]:
    """
    Convenience function to split a DataFrame by user_id.

    This is a stateless wrapper around UserSplitter for one-time splits.

    Parameters
    ----------
    df : pd.DataFrame
        Input DataFrame with multiple users
    userid_column : str
        Column name containing user IDs (default: "username")
    fallback_username : str
        Username to use for generic user (default: "generic_user")
    include_generic : bool
        Whether to include a generic user combining all data (default: False)
    include_individual : bool
        Whether to split data into individual users (default: True)
    skip_users : List[str], optional
        List of user IDs to exclude from output
    only_users : List[str], optional
        List of user IDs to include (mutually exclusive with skip_users)
    timestamp_column : str
        Column name containing timestamps for sorting (default: "timestamp")

    Returns
    -------
    Dict[str, pd.DataFrame]
        Dictionary mapping user_id to user DataFrame

    Examples
    --------
    >>> df = pd.DataFrame({
    ...     'timestamp': ['2024-01-01', '2024-01-02'],
    ...     'username': ['alice', 'bob'],
    ...     'value': [1, 2]
    ... })
    >>> user_dfs = split_dataframe_by_user(df, include_individual=True)
    >>> list(user_dfs.keys())
    ['alice', 'bob']
    """
    splitter = UserSplitter(
        userid_column=userid_column,
        fallback_username=fallback_username,
        include_generic=include_generic,
        include_individual=include_individual,
        skip_users=skip_users,
        only_users=only_users,
        timestamp_column=timestamp_column,
    )
    return splitter.split_users(df)
