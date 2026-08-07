"""
Rolling Window Module for DFP Pipeline

This module manages rolling time windows of user data, emitting only when history requirements are met.
Follows NVIDIA Morpheus DFP architecture from:
- python/morpheus_dfp/morpheus_dfp/stages/dfp_rolling_window_stage.py
- python/morpheus_dfp/morpheus_dfp/modules/dfp_rolling_window.py

Key Features:
- Per-user rolling windows with min_history/min_increment requirements
- Disk-based caching to reduce memory usage
- Time-based (str) or count-based (int) max_history
- Row hashing for overlap validation
- Cache flushing for batch mode operations
"""

import logging
import os
from contextlib import contextmanager

import pandas as pd

from modules.utils.cached_user_window import CachedUserWindow

logger = logging.getLogger(f"morpheus.{__name__}")


class RollingWindow:
    """
    Manage rolling time windows for per-user data.

    This class maintains a moving window of historical data for each user,
    emitting messages only when configured history requirements are met:
    - min_history: Minimum number of rows required
    - min_increment: Minimum new rows since last emission
    - max_history: Maximum history to include (int=count, str=duration)

    Data is cached to disk to reduce memory usage between batches.

    Parameters
    ----------
    min_history : int
        Minimum number of rows required before emitting. Set to 1 to disable.
    min_increment : int
        Minimum new rows required since last emission. Set to 0 to disable.
    max_history : int, str, or None
        Maximum history to include:
        - int: Last N rows
        - str: Time duration (e.g., "60d", "1h")
        - None: All history
    cache_dir : str
        Directory for caching user data (default: "./.cache/dfp/rolling-user-data")
    timestamp_column : str
        Name of timestamp column for time-based operations (default: "timestamp")
    cache_mode : str
        Cache mode: "batch" flushes after emission, "aggregate" keeps history (default: "batch")
    cache_to_disk : bool
        Enable disk persistence (default: True). If False, cache stays in memory only

    Examples
    --------
    >>> # Training configuration
    >>> rw = RollingWindow(
    ...     min_history=300,
    ...     min_increment=300,
    ...     max_history="60d",
    ...     cache_dir="./.cache/dfp"
    ... )
    >>>
    >>> # Inference configuration
    >>> rw = RollingWindow(
    ...     min_history=1,
    ...     min_increment=0,
    ...     max_history="1d",
    ...     cache_dir="./.cache/dfp"
    ... )
    >>>
    >>> # Process user data
    >>> result = rw.build_window(user_id="alice", incoming_df=df)
    >>> if result is not None:
    ...     print(f"Window ready with {len(result)} rows")
    """

    def __init__(
        self,
        min_history: int = 1,
        min_increment: int = 0,
        max_history: int | str | None = None,
        cache_dir: str = "./.cache/dfp",
        timestamp_column: str = "timestamp",
        cache_mode: str = "batch",
        cache_to_disk: bool = True,
    ):
        self.min_history = min_history
        self.min_increment = min_increment
        self.max_history = max_history
        self.timestamp_column = timestamp_column
        self.cache_mode = cache_mode
        self.cache_to_disk = cache_to_disk

        # Setup cache directory
        self.cache_dir = os.path.join(cache_dir, "rolling-user-data")
        if not os.path.exists(self.cache_dir):
            os.makedirs(self.cache_dir, exist_ok=True)
            logger.info(f"Created rolling window cache directory: {self.cache_dir}")

        # User cache map
        self._user_cache_map: dict[str, CachedUserWindow] = {}

        logger.info(
            f"Initialized RollingWindow: min_history={min_history}, "
            f"min_increment={min_increment}, max_history={max_history}, "
            f"cache_mode={cache_mode}"
        )

    @contextmanager
    def _get_user_cache(self, user_id: str):
        """
        Get or create user cache with context management.

        Parameters
        ----------
        user_id : str
            User identifier

        Yields
        ------
        CachedUserWindow
            User cache instance
        """
        # Determine cache location (conditional based on cache_to_disk)
        cache_location = os.path.join(self.cache_dir, f"{user_id}.pkl") if self.cache_to_disk else None

        # Get or create cache
        user_cache = self._user_cache_map.get(user_id)

        if user_cache is None:
            user_cache = CachedUserWindow(
                user_id=user_id, cache_location=cache_location, timestamp_column=self.timestamp_column
            )
            self._user_cache_map[user_id] = user_cache
            logger.debug(f"Created new cache for user '{user_id}'")

        yield user_cache

    def build_window(self, user_id: str, incoming_df: pd.DataFrame) -> pd.DataFrame | None:
        """
        Build rolling window for a user.

        This method:
        1. Appends incoming data to user's cache
        2. Checks if history requirements are met
        3. Returns windowed DataFrame if ready, None otherwise
        4. Handles cache flushing based on cache_mode

        Parameters
        ----------
        user_id : str
            User identifier
        incoming_df : pd.DataFrame
            New data for this user

        Returns
        -------
        pd.DataFrame or None
            Windowed DataFrame if requirements met, None otherwise

        Examples
        --------
        >>> result = rw.build_window("alice", new_df)
        >>> if result is not None:
        ...     print(f"Window ready: {len(result)} rows")
        """
        if incoming_df is None or incoming_df.empty:
            logger.debug(f"User {user_id}: Empty incoming DataFrame")
            return None

        with self._get_user_cache(user_id) as user_cache:
            print(f"DEBUG: build_window called for {user_id}")
            print(f"  - cache_mode: {self.cache_mode}")
            print(f"  - min_history: {self.min_history}")
            print(f"  - min_increment: {self.min_increment}")
            print(f"  - max_history: {self.max_history}")

            # Append incoming data
            append_result = user_cache.append_dataframe(incoming_df)
            print(f"DEBUG: append_dataframe returned: {append_result}")
            if not append_result:
                logger.warning(
                    f"User {user_id}: Incoming data preceded existing history. "
                    "Consider deleting rolling window cache and restarting."
                )
                return None

            # CRITICAL FIX: Calculate geographic features on cached data BEFORE saving
            # This ensures the cache contains complete geographic features just like training
            # The cache now has the new event appended, so we can calculate distances
            if self.cache_to_disk:
                try:
                    from modules.preprocessing.geographic_features import calculate_travel_features

                    # Get full DataFrame from cache
                    cache_df = user_cache.df

                    # Check if we have a valid DataFrame with coordinates
                    if cache_df is not None and not cache_df.empty:
                        has_coords = (
                            "location_geoCoordinates_latitude" in cache_df.columns
                            and "location_geoCoordinates_longitude" in cache_df.columns
                        )

                        if has_coords:
                            # Calculate geographic features on FULL cache (including new event)
                            cache_df_with_geo = calculate_travel_features(
                                cache_df, user_col="username", timestamp_col="timestamp"
                            )

                            # Update cache with geographic features
                            user_cache.df = cache_df_with_geo
                            logger.debug(f"User {user_id}: calculated geographic features for cache")
                except Exception as e:
                    logger.warning(f"User {user_id}: failed to calculate geographic features: {e}")

            # Save immediately after append (NVIDIA pattern - save BEFORE mode logic)
            # Now saves WITH geographic features calculated above
            if self.cache_to_disk:
                user_cache.save()

            # Check min_history requirement
            print(f"DEBUG: user_cache.count={user_cache.count}, min_history={self.min_history}")
            if user_cache.count < self.min_history:
                print(f"DEBUG: ❌ FAILING MIN_HISTORY CHECK ({user_cache.count} < {self.min_history})")
                logger.debug(
                    f"User {user_id}: Not enough history (count={user_cache.count}, min_history={self.min_history})"
                )
                return None

            print(f"DEBUG: ✅ PASSED MIN_HISTORY CHECK ({user_cache.count} >= {self.min_history})")

            # Handle cache modes
            if self.cache_mode == "batch":
                # NVIDIA Module API batch mode for continuous streaming:
                # - get_spanning_df() returns window (updates last_train_count in memory)
                # - flush() clears memory (total_count=0, last_train_count=0)
                # - Delete from map to force reload from disk next event
                # - Disk preserves last_train_count from training
                df_window = user_cache.get_spanning_df(max_history=None)

                # Flush clears in-memory state
                user_cache.flush()

                # Remove from cache map to force reload from disk on next event
                # This simulates NVIDIA's separate process per event pattern
                if self.cache_to_disk and user_id in self._user_cache_map:
                    del self._user_cache_map[user_id]

                logger.debug(
                    f"User {user_id}: Batch mode - returning {len(df_window)} rows, "
                    f"flushed cache and removed from map (will reload from disk)"
                )

            else:
                # Aggregate mode: check min_increment, apply max_history
                new_count = user_cache.total_count - user_cache.last_train_count
                print(f"DEBUG: User {user_id} aggregate mode:")
                print(f"  - total_count: {user_cache.total_count}")
                print(f"  - last_train_count: {user_cache.last_train_count}")
                print(f"  - new_count (total - last): {new_count}")
                print(f"  - min_increment required: {self.min_increment}")
                print(f"  - Passes check? {new_count >= self.min_increment}")

                if new_count < self.min_increment:
                    print(f"DEBUG: ❌ FAILING MIN_INCREMENT CHECK ({new_count} < {self.min_increment})")
                    logger.debug(
                        f"User {user_id}: Not enough new data since last emission "
                        f"(new={new_count}, min_increment={self.min_increment})"
                    )
                    return None

                print(f"DEBUG: ✅ PASSED MIN_INCREMENT CHECK ({new_count} >= {self.min_increment})")

                # Get spanning DataFrame with max_history constraint
                print(f"DEBUG: Calling get_spanning_df(max_history={self.max_history})")
                df_window = user_cache.get_spanning_df(max_history=self.max_history)
                print(f"DEBUG: get_spanning_df returned: {len(df_window) if df_window is not None else 'None'} rows")

                # Note: Overlap validation not applicable when max_history limits window
                # The window may not contain all incoming data when truncated

                # NVIDIA AGGREGATE MODE (Training):
                # get_spanning_df() updates last_train_count to mark training milestone.
                # This is CORRECT for training - it sets the baseline for future incremental features.
                # Cache is preserved (no flush) so history accumulates across training iterations.
                #
                # CRITICAL FOR SEPARATE PROCESSES:
                # NVIDIA's integrated pipeline keeps this in memory, but for separate training/inference
                # processes, we must save AFTER get_spanning_df() updates last_train_count.
                # This ensures inference (batch mode) can reload the trained last_train_count.
                if self.cache_to_disk:
                    user_cache.save()
                    logger.debug(
                        f"User {user_id}: Saved updated cache with last_train_count={user_cache.last_train_count}"
                    )

                logger.debug(
                    f"User {user_id}: Aggregate mode - returning {len(df_window)} rows (max_history={self.max_history})"
                )

            # NVIDIA COMPLIANCE: Apply max_history constraint at the stage level
            # This happens AFTER cache mode logic for batch mode (aggregate already applies it)
            # This allows batch mode to return full history from cache while still constraining
            # the final window for feature calculation
            if self.cache_mode == "batch" and self.max_history is not None and not df_window.empty:
                if isinstance(self.max_history, int):
                    # Integer: keep last N rows
                    if len(df_window) > self.max_history:
                        original_len = len(df_window)
                        df_window = df_window.tail(self.max_history).reset_index(drop=True)
                        logger.debug(
                            f"User {user_id}: Applied max_history={self.max_history} rows "
                            f"(kept last {len(df_window)} of {original_len} rows)"
                        )
                elif isinstance(self.max_history, str):
                    # String: time-based window
                    if self.timestamp_column in df_window.columns:
                        try:
                            time_delta = pd.Timedelta(self.max_history)
                            max_timestamp = df_window[self.timestamp_column].max()
                            min_timestamp = max_timestamp - time_delta

                            original_len = len(df_window)
                            df_window = df_window[df_window[self.timestamp_column] > min_timestamp].reset_index(
                                drop=True
                            )

                            logger.debug(
                                f"User {user_id}: Applied max_history='{self.max_history}' "
                                f"(window: {min_timestamp} to {max_timestamp}, "
                                f"kept {len(df_window)} of {original_len} rows)"
                            )
                        except ValueError as e:
                            logger.error(f"User {user_id}: Invalid max_history duration '{self.max_history}': {e}")

            # Return window without _row_hash column
            if "_row_hash" in df_window.columns:
                df_window = df_window.drop(columns=["_row_hash"])

            logger.info(
                f"User {user_id}: Window ready - {len(df_window)} rows "
                f"(count={user_cache.count}, total={user_cache.total_count})"
            )

            return df_window

    def _validate_window_overlap(self, incoming_df: pd.DataFrame, df_window: pd.DataFrame) -> bool:
        """
        Validate that incoming data doesn't overlap with window history.

        Uses row hashing to ensure incoming data is fully contained in the window.

        Parameters
        ----------
        incoming_df : pd.DataFrame
            Incoming data
        df_window : pd.DataFrame
            Window DataFrame (includes _row_hash column)

        Returns
        -------
        bool
            True if valid (no overlap), False otherwise
        """
        if incoming_df.empty or df_window.empty:
            return True

        if "_row_hash" not in df_window.columns:
            logger.warning("Window DataFrame missing _row_hash column, skipping overlap validation")
            return True

        try:
            # Hash first and last rows of incoming data
            incoming_hash = pd.util.hash_pandas_object(incoming_df.iloc[[0, -1]], index=False)

            # Find first row in window
            match_first = df_window[df_window["_row_hash"] == incoming_hash.iloc[0]]
            if len(match_first) == 0:
                logger.error("Invalid rolling window: first row of incoming data not found in window")
                return False

            first_row_idx = match_first.index[0]
            if not isinstance(first_row_idx, int):
                first_row_idx = first_row_idx.item()

            # Find last row in window
            match_last = df_window[df_window["_row_hash"] == incoming_hash.iloc[-1]]
            if len(match_last) == 0:
                logger.error("Invalid rolling window: last row of incoming data not found in window")
                return False

            last_row_idx = match_last.index[-1]
            if not isinstance(last_row_idx, int):
                last_row_idx = last_row_idx.item()

            # Validate count
            found_count = (last_row_idx - first_row_idx) + 1

            if found_count != len(incoming_df):
                logger.error(
                    f"Invalid rolling window: expected {len(incoming_df)} rows, found {found_count} rows in window"
                )
                return False

            return True

        except Exception as e:
            logger.error(f"Error validating window overlap: {e}")
            return False

    def get_user_stats(self) -> dict[str, dict[str, int]]:
        """
        Get statistics for all cached users.

        Returns
        -------
        Dict[str, Dict[str, int]]
            Dictionary mapping user_id to statistics:
            - count: Current window size
            - total_count: Total rows processed
            - last_train_count: Count at last training
            - cached_rows: Rows in cache

        Examples
        --------
        >>> stats = rw.get_user_stats()
        >>> for user_id, user_stats in stats.items():
        ...     print(f"{user_id}: {user_stats['total_count']} total rows")
        """
        stats = {}
        for user_id, cache in self._user_cache_map.items():
            stats[user_id] = {
                "count": cache.count,
                "total_count": cache.total_count,
                "last_train_count": cache.last_train_count,
                "cached_rows": len(cache.df) if cache.df is not None else 0,
            }
        return stats

    def clear_cache(self, user_id: str | None = None):
        """
        Clear cache for specific user or all users.

        Parameters
        ----------
        user_id : str, optional
            User to clear (default: None clears all users)

        Examples
        --------
        >>> rw.clear_cache("alice")  # Clear alice's cache
        >>> rw.clear_cache()  # Clear all caches
        """
        if user_id is not None:
            # Clear specific user
            if user_id in self._user_cache_map:
                del self._user_cache_map[user_id]
                logger.info(f"Cleared cache for user '{user_id}'")

            # Remove cache file
            cache_file = os.path.join(self.cache_dir, f"{user_id}.pkl")
            if os.path.exists(cache_file):
                os.remove(cache_file)
                logger.debug(f"Removed cache file: {cache_file}")

        else:
            # Clear all users
            self._user_cache_map.clear()
            logger.info("Cleared all user caches")

            # Remove all cache files
            if os.path.exists(self.cache_dir):
                for filename in os.listdir(self.cache_dir):
                    if filename.endswith(".pkl"):
                        filepath = os.path.join(self.cache_dir, filename)
                        os.remove(filepath)
                        logger.debug(f"Removed cache file: {filepath}")

    def __repr__(self) -> str:
        """String representation."""
        return (
            f"RollingWindow(min_history={self.min_history}, "
            f"min_increment={self.min_increment}, max_history={self.max_history}, "
            f"cache_mode='{self.cache_mode}', users_cached={len(self._user_cache_map)})"
        )


def process_user_windows(
    user_dfs: dict[str, pd.DataFrame],
    min_history: int = 1,
    min_increment: int = 0,
    max_history: int | str | None = None,
    cache_dir: str = "./.cache/dfp",
    timestamp_column: str = "timestamp",
    cache_mode: str = "batch",
) -> dict[str, pd.DataFrame]:
    """
    Convenience function to process multiple users through rolling windows.

    This is a stateless wrapper that creates a RollingWindow instance and
    processes all users in one call.

    Parameters
    ----------
    user_dfs : Dict[str, pd.DataFrame]
        Dictionary mapping user_id to DataFrame
    min_history : int
        Minimum history requirement (default: 1)
    min_increment : int
        Minimum increment requirement (default: 0)
    max_history : int, str, or None
        Maximum history constraint (default: None)
    cache_dir : str
        Cache directory (default: "./.cache/dfp")
    timestamp_column : str
        Timestamp column name (default: "timestamp")
    cache_mode : str
        Cache mode: "batch" or "aggregate" (default: "batch")

    Returns
    -------
    Dict[str, pd.DataFrame]
        Dictionary mapping user_id to windowed DataFrame (only users with ready windows)

    Examples
    --------
    >>> user_dfs = {
    ...     "alice": df_alice,
    ...     "bob": df_bob
    ... }
    >>> windowed_dfs = process_user_windows(
    ...     user_dfs,
    ...     min_history=100,
    ...     max_history="60d"
    ... )
    >>> for user_id, df in windowed_dfs.items():
    ...     print(f"{user_id}: {len(df)} rows ready")
    """
    rw = RollingWindow(
        min_history=min_history,
        min_increment=min_increment,
        max_history=max_history,
        cache_dir=cache_dir,
        timestamp_column=timestamp_column,
        cache_mode=cache_mode,
    )

    result_dfs = {}

    for user_id, user_df in user_dfs.items():
        windowed_df = rw.build_window(user_id, user_df)
        if windowed_df is not None:
            result_dfs[user_id] = windowed_df

    return result_dfs
