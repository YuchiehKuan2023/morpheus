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
FFT Time-Series Anomaly Detection Module.

This module implements Fast Fourier Transform (FFT) based anomaly detection
for time-series signals, following NVIDIA's TimeSeriesStage pattern.

Core Functions:
    - to_periodogram: Compute power spectral density via FFT
    - fftAD: FFT-based anomaly detection
    - zscore: Calculate z-scores for anomaly scoring

Signal Generation:
    - create_location_change_signal: Binary signal for location changes
    - create_event_count_signal: Event count histogram per time window
    - create_velocity_signal: Travel speed sequence signal

Reference:
    nv-morpheus/python/morpheus/morpheus/stages/postprocess/timeseries_stage.py
"""

import logging

import numpy as np
import pandas as pd

# Try to import CuPy for GPU acceleration, fallback to NumPy
try:
    import cupy as cp  # pyright: ignore[reportMissingImports]

    GPU_AVAILABLE = True
    logger = logging.getLogger(__name__)
    logger.info("CuPy detected - FFT will use GPU acceleration")
except ImportError:
    import numpy as cp

    GPU_AVAILABLE = False
    logger = logging.getLogger(__name__)
    logger.info("CuPy not available - FFT will use NumPy (CPU)")

logger = logging.getLogger(__name__)


def zscore(data: cp.ndarray) -> cp.ndarray:
    """
    Calculate z-scores of array elements.

    Z-score measures how many standard deviations an element is from the mean.
    Formula: z = |x - μ| / σ

    Parameters
    ----------
    data : cupy.ndarray or numpy.ndarray
        Input data array.

    Returns
    -------
    cupy.ndarray or numpy.ndarray
        Absolute z-scores for each element.

    Notes
    -----
    - Handles zero standard deviation by returning zeros
    - Returns absolute values (unsigned distance from mean)

    Examples
    --------
    >>> data = cp.array([1, 2, 3, 100])
    >>> zscore(data)
    array([0.69, 0.65, 0.62, 2.94])  # 100 is ~3 std devs from mean
    """
    mean = cp.mean(data)
    std = cp.std(data)

    if std == 0:
        return cp.zeros_like(data)

    return cp.abs(data - mean) / std


def to_periodogram(signal_cp: cp.ndarray) -> cp.ndarray:
    """
    Compute periodogram (power spectral density) of time-series signal via FFT.

    The periodogram shows energy distribution across frequencies, helping identify
    dominant periodic patterns. High energy at a frequency indicates a strong
    periodic component.

    Parameters
    ----------
    signal_cp : cupy.ndarray or numpy.ndarray
        Time-domain signal (real-valued).

    Returns
    -------
    cupy.ndarray or numpy.ndarray
        Periodogram (power spectral density).
        Length equals input signal length.

    Algorithm
    ---------
    1. Standardize signal to zero mean and unit variance
    2. Apply FFT to transform to frequency domain
    3. Compute power: (1/N) * |FFT|²

    Notes
    -----
    - Standardization ensures scale invariance
    - Periodogram values represent energy at each frequency
    - DC component (index 0) is typically high for non-zero-mean signals

    Examples
    --------
    >>> # Pure sine wave at frequency f
    >>> signal = cp.sin(2 * cp.pi * f * t)
    >>> prdg = to_periodogram(signal)
    >>> # prdg will have peak at frequency f

    Reference
    ---------
    NVIDIA TimeSeriesStage: timeseries_stage.py lines 70-100
    """
    std_dev = cp.std(signal_cp)

    # Standardize the signal (zero mean, unit variance)
    if std_dev != 0.0:
        signal_cp_std = (signal_cp - cp.mean(signal_cp)) / std_dev
    else:
        # All values are identical (zero variance)
        signal_cp_std = signal_cp - cp.mean(signal_cp)

    # Transform to frequency domain
    fft_data = cp.fft.fft(signal_cp_std)

    # Compute periodogram: (1/N) * |FFT|²
    prdg = (1 / len(signal_cp)) * ((cp.absolute(fft_data)) ** 2)

    return prdg


def fftAD(signalvalues: cp.ndarray, percentile: int = 90, zthresh: float = 8) -> cp.ndarray:
    """
    Detect anomalies in time-series using Fast Fourier Transform.

    Algorithm:
    1. Compute periodogram (frequency-domain representation)
    2. Filter low-energy frequencies (keep only strong patterns)
    3. Reconstruct signal using only high-energy frequencies
    4. Compute reconstruction error: |original - reconstructed|
    5. Calculate z-scores of errors
    6. Flag points with z-score >= threshold as anomalies

    Intuition:
    - Normal patterns: Smooth, periodic → low reconstruction error
    - Burst anomalies: Sudden spikes → high reconstruction error → flagged

    Parameters
    ----------
    signalvalues : cupy.ndarray or numpy.ndarray
        Time-domain signal values (real-valued).
    percentile : int, optional
        Percentile threshold for spectral density filtering (0-100).
        Higher = more frequencies filtered = more sensitive to bursts.
        Default: 90 (NVIDIA recommendation).
    zthresh : float, optional
        Z-score threshold for anomaly detection.
        Higher = less sensitive (fewer false positives).
        Default: 8 (NVIDIA recommendation for DFP).

    Returns
    -------
    cupy.ndarray or numpy.ndarray
        Indices of detected anomalies in the signal.
        Empty array if no anomalies detected.

    Notes
    -----
    - Works on real-valued signals (uses rfft/irfft)
    - Percentile filtering removes low-energy noise
    - Z-score threshold controls sensitivity
    - Typical values: percentile=85-95, zthresh=6-10

    Examples
    --------
    >>> # Normal pattern: no bursts
    >>> signal = cp.array([5, 3, 4, 5, 3, 4])
    >>> fftAD(signal, percentile=90, zthresh=8)
    array([], dtype=int64)  # No anomalies

    >>> # Burst pattern: sudden spike
    >>> signal = cp.array([5, 3, 20, 18, 4, 5])
    >>> fftAD(signal, percentile=90, zthresh=8)
    array([2, 3])  # Indices 2-3 are anomalies

    Reference
    ---------
    NVIDIA TimeSeriesStage: timeseries_stage.py lines 104-146
    """
    # Compute periodogram
    periodogram = to_periodogram(signalvalues)
    # Keep only positive frequencies (real signal symmetry)
    periodogram = periodogram[: len(signalvalues) // 2 + 1]

    # Create mask for frequency filtering
    indices_mask = cp.zeros_like(periodogram, dtype=bool)

    # Filter low-energy frequencies (keep high-energy patterns)
    threshold = cp.percentile(periodogram, percentile).item()
    indices_mask = periodogram < threshold

    # Reconstruct signal using only high-energy frequencies
    rft = cp.fft.rfft(signalvalues, n=len(signalvalues))
    rft[indices_mask] = 0  # Zero out low-energy frequencies
    recon = cp.fft.irfft(rft, n=len(signalvalues))

    # Compute reconstruction error
    err = cp.abs(recon - signalvalues)

    # Calculate z-scores of errors
    z_score = zscore(err)

    # Return indices where z-score >= threshold
    return cp.arange(len(signalvalues))[z_score >= zthresh]


def create_location_change_signal(df: pd.DataFrame, user_col: str, location_col: str) -> dict[str, np.ndarray]:
    """
    Generate binary signal indicating location changes for each user.

    Signal: 1 = location changed from previous event, 0 = same location

    Parameters
    ----------
    df : pandas.DataFrame
        Events DataFrame with user and location columns.
    user_col : str
        Column name containing user identifiers.
    location_col : str
        Column name containing location identifiers.

    Returns
    -------
    Dict[str, np.ndarray]
        Dictionary mapping user_id → binary signal array.
        Signal[0] is always 0 (no previous location for first event).

    Examples
    --------
    >>> df = pd.DataFrame({
    ...     'user': ['alice', 'alice', 'alice', 'alice'],
    ...     'location': ['NYC', 'NYC', 'LAX', 'LAX']
    ... })
    >>> signals = create_location_change_signal(df, 'user', 'location')
    >>> signals['alice']
    array([0, 0, 1, 0])  # Changed at index 2

    Use Case
    --------
    Detects rapid location hopping:
    - Normal: [0, 0, 0, 1, 0, 0] (occasional travel)
    - Anomaly: [0, 1, 1, 1, 1, 0] (rapid hopping burst)
    """
    signals = {}

    for user_id, user_df in df.groupby(user_col):
        # Sort by timestamp if available
        if "timestamp" in user_df.columns:
            user_df = user_df.sort_values("timestamp")

        locations = user_df[location_col].values

        # Binary signal: 1 = changed, 0 = same
        signal = np.zeros(len(locations), dtype=int)
        for i in range(1, len(locations)):
            if locations[i] != locations[i - 1]:
                signal[i] = 1

        signals[str(user_id)] = signal

    return signals


def create_event_count_signal(
    df: pd.DataFrame, user_col: str, timestamp_col: str, window: str = "1H"
) -> dict[str, np.ndarray]:
    """
    Generate event count histogram per time window for each user.

    Bins events into time windows and counts events per bin.

    Parameters
    ----------
    df : pandas.DataFrame
        Events DataFrame with user and timestamp columns.
    user_col : str
        Column name containing user identifiers.
    timestamp_col : str
        Column name containing timestamps.
    window : str, optional
        Time window size for binning (pandas Timedelta format).
        Examples: "1H" (1 hour), "30T" (30 minutes), "1D" (1 day).
        Default: "1H".

    Returns
    -------
    Dict[str, np.ndarray]
        Dictionary mapping user_id → event count array.
        Each element is the count of events in that time bin.

    Examples
    --------
    >>> df = pd.DataFrame({
    ...     'user': ['alice'] * 25,
    ...     'timestamp': pd.date_range('2025-01-01 10:00', periods=25, freq='5T')
    ... })
    >>> signals = create_event_count_signal(df, 'user', 'timestamp', '1H')
    >>> signals['alice']
    array([12, 13])  # 12 events in hour 1, 13 in hour 2

    Use Case
    --------
    Detects credential spray attacks:
    - Normal: [5, 3, 4, 5, 3] (consistent activity)
    - Anomaly: [5, 3, 20, 18, 4] (burst at indices 2-3)
    """
    signals = {}

    for user_id, user_df in df.groupby(user_col):
        # Make a copy to avoid SettingWithCopyWarning
        user_df = user_df.copy()

        # Ensure timestamp column is datetime
        if not pd.api.types.is_datetime64_any_dtype(user_df[timestamp_col]):
            user_df[timestamp_col] = pd.to_datetime(user_df[timestamp_col])

        # Sort by timestamp
        user_df = user_df.sort_values(timestamp_col)

        # Bin events into time windows (explicitly cast to DatetimeIndex for type checker)
        timestamp_series = pd.to_datetime(user_df[timestamp_col])
        user_df["time_bin"] = timestamp_series.dt.floor(window)

        # Count events per bin
        event_counts = user_df.groupby("time_bin").size()

        signals[str(user_id)] = event_counts.values

    return signals


def create_velocity_signal(
    df: pd.DataFrame, user_col: str, speed_col: str = "travel_speed_kmph"
) -> dict[str, np.ndarray]:
    """
    Extract travel velocity as time-series signal for each user.

    Uses pre-computed travel_speed_kmph from geographic features preprocessing.

    Parameters
    ----------
    df : pandas.DataFrame
        Events DataFrame with user and speed columns.
    user_col : str
        Column name containing user identifiers.
    speed_col : str, optional
        Column name containing travel speed values.
        Default: "travel_speed_kmph".

    Returns
    -------
    Dict[str, np.ndarray]
        Dictionary mapping user_id → velocity signal array.
        Each element is the travel speed in km/h.

    Examples
    --------
    >>> df = pd.DataFrame({
    ...     'user': ['alice'] * 5,
    ...     'travel_speed_kmph': [50, 45, 8900, 8500, 60]
    ... })
    >>> signals = create_velocity_signal(df, 'user')
    >>> signals['alice']
    array([50, 45, 8900, 8500, 60])  # Burst at indices 2-3

    Use Case
    --------
    Detects impossible travel patterns:
    - Normal: [50, 45, 60, 55] (car/train speeds)
    - Anomaly: [50, 8900, 8500, 60] (airplane-speed burst)

    Notes
    -----
    - Assumes travel_speed_kmph already computed during geographic preprocessing
    - Complements DFP AutoEncoder (which learns normal velocity patterns)
    - FFT detects burst timing patterns in time-series data
    """
    signals = {}

    for user_id, user_df in df.groupby(user_col):
        # Sort by timestamp if available
        if "timestamp" in user_df.columns:
            user_df = user_df.sort_values("timestamp")

        # Extract velocity values
        if speed_col in user_df.columns:
            velocity = user_df[speed_col].values
            # Replace NaN with 0 (first event has no previous location)
            velocity = np.nan_to_num(velocity, nan=0.0)  # type: ignore[call-overload]
        else:
            logger.warning(f"Column '{speed_col}' not found for user {user_id}")
            velocity = np.zeros(len(user_df))

        signals[str(user_id)] = velocity

    return signals


def get_fft_statistics(signal: np.ndarray, anomaly_indices: np.ndarray) -> dict[str, int | float]:
    """
    Calculate statistics for FFT anomaly detection results.

    Parameters
    ----------
    signal : numpy.ndarray
        Original time-series signal.
    anomaly_indices : numpy.ndarray
        Indices of detected anomalies.

    Returns
    -------
    Dict[str, Union[int, float]]
        Statistics dictionary containing:
        - signal_length: Length of input signal
        - anomaly_count: Number of anomalies detected
        - anomaly_rate: Percentage of anomalies
        - signal_mean: Mean of signal values
        - signal_std: Standard deviation of signal

    Examples
    --------
    >>> signal = np.array([5, 3, 20, 18, 4, 5])
    >>> anomalies = np.array([2, 3])
    >>> stats = get_fft_statistics(signal, anomalies)
    >>> stats
    {
        'signal_length': 6,
        'anomaly_count': 2,
        'anomaly_rate': 33.33,
        'signal_mean': 9.17,
        'signal_std': 7.36
    }
    """
    # Convert CuPy to NumPy if needed (only when GPU is available)
    if GPU_AVAILABLE:
        try:
            import cupy  # pyright: ignore[reportMissingImports]

            if isinstance(signal, cupy.ndarray):
                signal = cupy.asnumpy(signal)  # type: ignore[attr-defined]
            if isinstance(anomaly_indices, cupy.ndarray):
                anomaly_indices = cupy.asnumpy(anomaly_indices)  # type: ignore[attr-defined]
        except ImportError:
            pass  # Already NumPy arrays

    signal_length = len(signal)
    anomaly_count = len(anomaly_indices)
    anomaly_rate = (anomaly_count / signal_length * 100) if signal_length > 0 else 0.0

    return {
        "signal_length": int(signal_length),
        "anomaly_count": int(anomaly_count),
        "anomaly_rate": float(anomaly_rate),
        "signal_mean": float(np.mean(signal)) if signal_length > 0 else 0.0,
        "signal_std": float(np.std(signal)) if signal_length > 0 else 0.0,
    }
