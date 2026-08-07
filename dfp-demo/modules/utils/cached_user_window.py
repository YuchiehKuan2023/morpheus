"""
Cached User Window Utility for DFP Rolling Window

This module provides a class for managing per-user data windows with caching support.
Follows NVIDIA Morpheus DFP architecture from:
- python/morpheus_dfp/morpheus_dfp/utils/cached_user_window.py

Key Features:
- Per-user DataFrame caching to disk (pickle format)
- Append new data to existing cache
- Retrieve training DataFrames with max_history constraint
- Time-based window spanning (aggregation_span)
- Cache flushing for batch mode
"""

import logging
import os
import pickle

import pandas as pd

logger = logging.getLogger(f"morpheus.{__name__}")


class CachedUserWindow:
    """
    Manages cached historical data for a single user.

    This class handles per-user data caching, including:
    - Appending new incoming data
    - Maintaining cumulative history across batches
    - Retrieving historical windows for training/inference
    - Disk-based persistence (optional)

    Parameters
    ----------
    user_id : str
        Unique identifier for the user
    cache_location : str, optional
        Path to pickle file for persistent storage (default: None for in-memory only)
    timestamp_column : str
        Name of the timestamp column for time-based operations (default: "timestamp")

    Attributes
    ----------
    user_id : str
        User identifier
    cache_location : str or None
        Path to cache file
    timestamp_column : str
        Timestamp column name
    count : int
        Number of rows in current cache (excludes rows from previous training)
    total_count : int
        Total number of rows processed (cumulative)
    last_train_count : int
        Total count at last training event
    df : pd.DataFrame or None
        Cached DataFrame

    Examples
    --------
    >>> cache = CachedUserWindow(
    ...     user_id="alice@company.com",
    ...     cache_location="/cache/alice.pkl",
    ...     timestamp_column="timestamp"
    ... )
    >>> cache.append_dataframe(new_df)
    True
    >>> train_df = cache.get_train_df(max_history=100)
    """

    def __init__(self, user_id: str, cache_location: str | None = None, timestamp_column: str = "timestamp"):
        self.user_id = user_id
        self.cache_location = cache_location
        self.timestamp_column = timestamp_column

        # Data tracking
        self.df: pd.DataFrame | None = None
        self.count = 0  # Current window size
        self.total_count = 0  # Total rows processed
        self.last_train_count = 0  # Count at last training

        # Load from cache if exists
        if self.cache_location and os.path.exists(self.cache_location):
            self.load()

    def append_dataframe(self, incoming_df: pd.DataFrame) -> bool:
        """
        Append incoming DataFrame to the cached history.

        This method:
        1. Validates incoming data doesn't precede existing history
        2. Concatenates with existing cache
        3. Sorts by timestamp
        4. Updates row counts

        Parameters
        ----------
        incoming_df : pd.DataFrame
            New data to append

        Returns
        -------
        bool
            True if append succeeded, False if incoming data preceded existing history

        Examples
        --------
        >>> cache.append_dataframe(new_df)
        True
        """
        if incoming_df is None or incoming_df.empty:
            logger.debug(f"User {self.user_id}: Empty incoming DataFrame, skipping append")
            return True

        # Ensure timestamp is datetime
        if self.timestamp_column in incoming_df.columns:
            if not pd.api.types.is_datetime64_any_dtype(incoming_df[self.timestamp_column]):
                incoming_df = incoming_df.copy()
                incoming_df[self.timestamp_column] = pd.to_datetime(
                    incoming_df[self.timestamp_column], utc=True, errors="coerce"
                )

        # First data for this user
        if self.df is None or self.df.empty:
            self.df = incoming_df.copy()
            self.count = len(incoming_df)
            self.total_count += len(incoming_df)
            logger.debug(
                f"User {self.user_id}: Initialized cache with {len(incoming_df)} rows (total: {self.total_count})"
            )
            return True

        # Check for temporal ordering (incoming should not precede existing)
        if self.timestamp_column in incoming_df.columns and self.timestamp_column in self.df.columns:
            existing_max_time = self.df[self.timestamp_column].max()
            incoming_min_time = incoming_df[self.timestamp_column].min()

            if pd.notna(existing_max_time) and pd.notna(incoming_min_time):
                if incoming_min_time < existing_max_time:
                    logger.warning(
                        f"User {self.user_id}: Incoming data precedes existing history "
                        f"(incoming_min: {incoming_min_time}, existing_max: {existing_max_time})"
                    )
                    return False

        # Append and sort
        self.df = pd.concat([self.df, incoming_df], ignore_index=True)

        if self.timestamp_column in self.df.columns:
            self.df = self.df.sort_values(by=self.timestamp_column).reset_index(drop=True)

        # Update counts
        self.count += len(incoming_df)
        self.total_count += len(incoming_df)

        logger.debug(
            f"User {self.user_id}: Appended {len(incoming_df)} rows (count: {self.count}, total: {self.total_count})"
        )

        return True

    def get_train_df(self, max_history: int | str | None = None) -> pd.DataFrame:
        """
        Get training DataFrame with optional max_history constraint.

        NVIDIA Behavior: This method ALWAYS updates last_train_count to total_count
        to mark that training data has been extracted. This is critical for
        incremental features in subsequent inference runs.

        Parameters
        ----------
        max_history : int, str, or None
            Maximum history to include:
            - int: Last N rows
            - str: Time duration (e.g., "60d", "1h") - pandas.Timedelta compatible
            - None: All cached data

        Returns
        -------
        pd.DataFrame
            Training DataFrame with row hashes added for validation

        Examples
        --------
        >>> # Get last 100 rows
        >>> df = cache.get_train_df(max_history=100)
        >>> # Get last 60 days
        >>> df = cache.get_train_df(max_history="60d")
        >>> # Get all data
        >>> df = cache.get_train_df()
        """
        if self.df is None or self.df.empty:
            return pd.DataFrame()

        result_df = self.df.copy()

        # NVIDIA behavior: ALWAYS update last_train_count when getting training data
        # This marks that training has occurred at this point in the data stream
        self.last_train_count = self.total_count

        # Apply max_history constraint
        if max_history is not None:
            if isinstance(max_history, int):
                # Integer: take last N rows
                if max_history < len(result_df):
                    result_df = result_df.tail(max_history).reset_index(drop=True)
                    logger.debug(
                        f"User {self.user_id}: Applied max_history={max_history} rows (result: {len(result_df)} rows)"
                    )

            elif isinstance(max_history, str):
                # String: time-based window
                if self.timestamp_column in result_df.columns:
                    try:
                        time_delta = pd.Timedelta(max_history)
                        max_timestamp = result_df[self.timestamp_column].max()
                        min_timestamp = max_timestamp - time_delta

                        result_df = result_df[result_df[self.timestamp_column] > min_timestamp].reset_index(drop=True)

                        logger.debug(
                            f"User {self.user_id}: Applied max_history='{max_history}' "
                            f"(window: {min_timestamp} to {max_timestamp}, result: {len(result_df)} rows)"
                        )
                    except ValueError as e:
                        logger.error(f"User {self.user_id}: Invalid max_history duration '{max_history}': {e}")

        # Add row hashes for validation (used by rolling window stage)
        if not result_df.empty:
            result_df["_row_hash"] = pd.util.hash_pandas_object(result_df, index=False)

        return result_df

    def get_spanning_df(self, max_history: int | str | None = None) -> pd.DataFrame:
        """
        Get spanning DataFrame (alias for get_train_df for compatibility).

        This method provides the same functionality as get_train_df and exists
        for API compatibility with NVIDIA Morpheus.

        Parameters
        ----------
        max_history : int, str, or None
            Maximum history constraint (see get_train_df)

        Returns
        -------
        pd.DataFrame
            Training DataFrame
        """
        return self.get_train_df(max_history=max_history)

    def flush(self):
        """
        Flush the cache (NVIDIA Module API behavior).

        Resets ALL state including last_train_count and total_count.
        Used in batch mode to clear memory after processing.

        Examples
        --------
        >>> cache.flush()  # After batch processing completes
        """
        logger.debug(
            f"User {self.user_id}: Flushing cache "
            f"(total_count: {self.total_count} -> 0, last_train_count: {self.last_train_count} -> 0)"
        )

        self.df = pd.DataFrame()  # Clear dataframe
        self.count = 0  # Reset count
        self.total_count = 0  # Reset total
        self.last_train_count = 0  # Reset training baseline

    def save(self):
        """
        Save cache to disk (pickle format).

        Saves the current state (df, count, total_count, last_train_count) to
        the cache_location file. Creates parent directories if needed.

        Examples
        --------
        >>> cache.save()  # Persists to disk
        """
        if self.cache_location is None:
            logger.debug(f"User {self.user_id}: No cache_location specified, skipping save")
            return

        try:
            # Create directory if needed
            cache_dir = os.path.dirname(self.cache_location)
            if cache_dir and not os.path.exists(cache_dir):
                os.makedirs(cache_dir, exist_ok=True)

            # Save state
            state = {
                "user_id": self.user_id,
                "df": self.df,
                "count": self.count,
                "total_count": self.total_count,
                "last_train_count": self.last_train_count,
                "timestamp_column": self.timestamp_column,
            }

            with open(self.cache_location, "wb") as f:
                pickle.dump(state, f)

            logger.debug(f"User {self.user_id}: Saved cache to {self.cache_location} (total_count: {self.total_count})")

        except Exception as e:
            logger.error(f"User {self.user_id}: Failed to save cache: {e}")

    def load(self):
        """
        Load cache from disk (pickle format).

        Restores the previous state from cache_location file.

        Examples
        --------
        >>> cache.load()  # Restores from disk
        """
        if self.cache_location is None or not os.path.exists(self.cache_location):
            logger.debug(f"User {self.user_id}: No cache file to load")
            return

        try:
            with open(self.cache_location, "rb") as f:
                state = pickle.load(f)

            self.user_id = state.get("user_id", self.user_id)
            self.df = state.get("df")
            self.count = state.get("count", 0)
            self.total_count = state.get("total_count", 0)
            self.last_train_count = state.get("last_train_count", 0)
            self.timestamp_column = state.get("timestamp_column", self.timestamp_column)

            logger.debug(
                f"User {self.user_id}: Loaded cache from {self.cache_location} (total_count: {self.total_count})"
            )

        except Exception as e:
            logger.error(f"User {self.user_id}: Failed to load cache: {e}")

    def __repr__(self) -> str:
        """String representation."""
        return (
            f"CachedUserWindow(user_id='{self.user_id}', "
            f"count={self.count}, total_count={self.total_count}, "
            f"cached_rows={len(self.df) if self.df is not None else 0})"
        )
