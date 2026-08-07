# SPDX-FileCopyrightText: Copyright (c) 2021-2025, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""
FFT Time-Series Stage Module.

This module implements a pipeline stage for FFT-based burst anomaly detection,
following NVIDIA's TimeSeriesStage pattern with ControlMessage architecture.

Key Features:
    - Processes ControlMessages with per-user event data
    - Generates time-series signals (location/event_count/velocity)
    - Applies FFT anomaly detection (fftAD)
    - Attaches anomaly metadata to ControlMessage
    - Configurable signal type and thresholds

Pipeline Integration:
    Input: ControlMessage from DFPInference
    Processing: FFT burst detection (experimental time-series analysis)
    Output: ControlMessage with FFT anomaly metadata

Reference:
    nv-morpheus/python/morpheus/morpheus/stages/postprocess/timeseries_stage.py

Author: Tomasz Zabek <tzabek@deloitte.co.uk>
Date: 2025-12-01
"""

import logging
from typing import Any

import numpy as np
import pandas as pd

from modules.control.control_message import ControlMessage
from modules.inference.fft_timeseries import (
    create_event_count_signal,
    create_location_change_signal,
    create_velocity_signal,
    fftAD,
    get_fft_statistics,
)

# Try to import CuPy for GPU acceleration, fallback to NumPy
try:
    import cupy as cp  # pyright: ignore[reportMissingImports]

    GPU_AVAILABLE = True
except ImportError:
    import numpy as cp

    GPU_AVAILABLE = False

logger = logging.getLogger(__name__)


class FFTTimeSeriesStage:
    """
    FFT Time-Series Burst Detection Stage.

    This stage detects temporal burst patterns using Fast Fourier Transform (FFT)
    anomaly detection. It operates on per-user time-series signals and flags
    sudden spikes/bursts in activity.

    Use Cases:
        - Credential spray attacks: 20+ login attempts in 2 minutes
        - Rapid location hopping: 5+ location changes in 10 minutes
        - Event bursts: Sudden spike in any activity pattern

    Architecture:
        - Input: ControlMessage with user events (DataFrame payload)
        - Processing: Generate signal → Apply FFT → Detect bursts
        - Output: ControlMessage with FFT metadata attached

    Metadata Added:
        - fft_anomaly_indices: List of anomaly indices in user DataFrame
        - fft_anomaly_count: Number of anomalies detected
        - fft_signal_type: Type of signal analyzed
        - fft_statistics: Detection statistics

    Configuration:
        signal_type: Type of signal to analyze
            - "event_count": Event count histogram (default)
            - "location": Location change binary signal
            - "velocity": Travel speed sequence
        window: Time window for event_count binning (e.g., "1H", "30T")
        percentile: Frequency filtering percentile (0-100, default: 90)
        z_threshold: Z-score threshold for anomalies (default: 8)
        min_history: Minimum signal length to run FFT (default: 10)

    Reference:
        NVIDIA TimeSeriesStage pattern with per-user ControlMessage processing
    """

    def __init__(self, config: dict[str, Any]):
        """
        Initialize FFT Time-Series Stage.

        Args:
            config: Configuration dictionary with keys:
                - signal_type: Signal type ("event_count", "location", "velocity")
                - window: Time window for event_count (default: "1H")
                - percentile: Frequency filtering percentile (default: 90)
                - z_threshold: Z-score threshold (default: 8)
                - min_history: Minimum signal length (default: 10)
                - user_col: User identifier column (default: "username")
                - timestamp_col: Timestamp column (default: "timestamp")
                - location_col: Location column (default: "location")
                - speed_col: Speed column (default: "travel_speed_kmph")

        Raises:
            ValueError: If invalid configuration provided
        """
        self.signal_type = config.get("signal_type", "event_count")
        self.window = config.get("window", "1H")
        self.percentile = config.get("percentile", 90)
        self.z_threshold = config.get("z_threshold", 8)
        self.min_history = config.get("min_history", 10)

        # Column names
        self.user_col = config.get("user_col", "username")
        self.timestamp_col = config.get("timestamp_col", "timestamp")
        self.location_col = config.get("location_col", "location")
        self.speed_col = config.get("speed_col", "travel_speed_kmph")

        # Validate configuration
        self._validate_config()

        logger.info(
            f"FFT Stage initialized: signal_type={self.signal_type}, "
            f"window={self.window}, percentile={self.percentile}, "
            f"z_threshold={self.z_threshold}, min_history={self.min_history}"
        )

    def _validate_config(self):
        """Validate configuration parameters."""
        valid_signal_types = ["event_count", "location", "velocity"]
        if self.signal_type not in valid_signal_types:
            raise ValueError(f"Invalid signal_type '{self.signal_type}'. Must be one of: {valid_signal_types}")

        if not 0 <= self.percentile <= 100:
            raise ValueError(f"Invalid percentile {self.percentile}. Must be between 0 and 100.")

        if self.z_threshold < 0:
            raise ValueError(f"Invalid z_threshold {self.z_threshold}. Must be >= 0.")

        if self.min_history < 1:
            raise ValueError(f"Invalid min_history {self.min_history}. Must be >= 1.")

    def process(self, control_message: ControlMessage) -> ControlMessage | None:
        """
        Process ControlMessage and detect FFT anomalies.

        Processing Steps:
            1. Extract user DataFrame from ControlMessage
            2. Generate time-series signal based on signal_type
            3. Apply FFT anomaly detection
            4. Map anomaly indices back to DataFrame rows
            5. Attach metadata to ControlMessage

        Args:
            control_message: Input ControlMessage with user events

        Returns:
            ControlMessage with FFT metadata attached, or None if insufficient data

        Notes:
            - Returns original message if signal too short (< min_history)
            - Attaches empty anomaly list if no bursts detected
            - Preserves original DataFrame payload
        """
        try:
            # Extract DataFrame from ControlMessage
            df = control_message.payload()

            if df is None or df.empty:
                logger.debug("Empty DataFrame in ControlMessage, skipping FFT")
                return control_message

            # Get user_id from metadata
            user_id = control_message.get_metadata("user_id", "unknown")

            # Generate signal
            signal_dict = self._generate_signal(df)

            if str(user_id) not in signal_dict:
                logger.debug(f"No signal generated for user {user_id}, skipping FFT")
                return control_message

            signal = signal_dict[str(user_id)]

            # Check minimum history requirement
            if len(signal) < self.min_history:
                logger.debug(f"Signal too short for user {user_id}: {len(signal)} < {self.min_history}, skipping FFT")
                return control_message

            # Convert to CuPy/NumPy
            signal_cp = cp.asarray(signal)

            # Apply FFT anomaly detection
            anomaly_indices_cp = fftAD(signal_cp, percentile=self.percentile, zthresh=self.z_threshold)

            # Convert back to NumPy
            if GPU_AVAILABLE:
                try:
                    import cupy  # pyright: ignore[reportMissingImports]

                    if isinstance(anomaly_indices_cp, cupy.ndarray):
                        anomaly_indices = cupy.asnumpy(anomaly_indices_cp)  # type: ignore[attr-defined]
                    else:
                        anomaly_indices = anomaly_indices_cp
                except ImportError:
                    anomaly_indices = anomaly_indices_cp
            else:
                anomaly_indices = anomaly_indices_cp

            # Map signal indices to DataFrame row indices
            df_anomaly_indices = self._map_signal_to_df_indices(df, anomaly_indices)

            # Calculate statistics
            stats = get_fft_statistics(signal, anomaly_indices)

            # Attach metadata to ControlMessage
            control_message.set_metadata("fft_anomaly_indices", df_anomaly_indices.tolist())
            control_message.set_metadata("fft_anomaly_count", len(df_anomaly_indices))
            control_message.set_metadata("fft_signal_type", self.signal_type)
            control_message.set_metadata("fft_statistics", stats)

            logger.info(
                f"FFT processed user {user_id}: "
                f"signal_length={stats['signal_length']}, "
                f"anomalies={stats['anomaly_count']} ({stats['anomaly_rate']:.1f}%)"
            )

            return control_message

        except Exception as e:
            logger.error(f"FFT processing failed: {e}", exc_info=True)
            # Return original message on error (graceful degradation)
            return control_message

    def _generate_signal(self, df: pd.DataFrame) -> dict[str, np.ndarray]:
        """
        Generate time-series signal based on signal_type.

        Args:
            df: User events DataFrame

        Returns:
            Dictionary mapping user_id → signal array

        Raises:
            ValueError: If signal_type not recognized
        """
        if self.signal_type == "event_count":
            return create_event_count_signal(
                df, user_col=self.user_col, timestamp_col=self.timestamp_col, window=self.window
            )

        elif self.signal_type == "location":
            return create_location_change_signal(df, user_col=self.user_col, location_col=self.location_col)

        elif self.signal_type == "velocity":
            return create_velocity_signal(df, user_col=self.user_col, speed_col=self.speed_col)

        else:
            raise ValueError(f"Unknown signal_type: {self.signal_type}")

    def _map_signal_to_df_indices(self, df: pd.DataFrame, signal_anomaly_indices: np.ndarray) -> np.ndarray:
        """
        Map signal anomaly indices back to DataFrame row indices.

        For event_count signals, anomalies are time bins, not individual rows.
        This method maps time bin anomalies back to the original DataFrame rows
        that fall within those bins.

        For location/velocity signals, indices map 1:1 to DataFrame rows.

        Args:
            df: Original DataFrame
            signal_anomaly_indices: Anomaly indices in the signal

        Returns:
            Array of DataFrame row indices corresponding to anomalies
        """
        if self.signal_type == "event_count":
            # For event_count, we need to map time bins to DataFrame rows
            # This is a simplified approach: return indices of all rows
            # A more sophisticated approach would map bins to specific rows
            # For now, we'll mark all rows as potential anomalies if any bin is anomalous
            if len(signal_anomaly_indices) > 0:
                logger.debug(
                    f"Event count signal has {len(signal_anomaly_indices)} anomalous bins, marking all {len(df)} rows"
                )
                return np.arange(len(df))
            else:
                return np.array([], dtype=int)

        else:
            # For location/velocity, indices map directly to DataFrame rows
            # Filter out indices beyond DataFrame length
            valid_indices = signal_anomaly_indices[signal_anomaly_indices < len(df)]

            if len(valid_indices) < len(signal_anomaly_indices):
                logger.warning(
                    f"Some signal indices out of bounds: {len(signal_anomaly_indices)} signal, {len(df)} rows"
                )

            return valid_indices
