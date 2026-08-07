"""
Anomaly-score compression for DFP.

DFP's encoder produces z-scores — per-feature reconstruction errors normalised
by a running standard deviation.  Under benign conditions these stay below 2.0;
genuine anomalies land in the 2–25 range; extreme outliers (e.g. geographic
"impossible-travel" events) can reach values in the millions or higher because
the denominator (σ) is tiny for a rarely-seen feature value.

Storing or displaying raw astronomical z-scores:
  • corrupts dashboard aggregates (AVG, MAX)
  • confuses LLMs that see anomaly_score=9.07 alongside a feature z=1 000 000

``compress_score`` maps any non-negative z-score into a bounded range while
preserving *strict monotonic ordering*, so relative severity is never inverted.

Compression rules
-----------------
score < 8.0  →  stored unchanged (pass-through)
score ≥ 8.0  →  8.0 + 8.0 × log10(1 + score) / 15.0   (hard clip: 15.99)

Key reference points:
  score=8.01   → 8.51      score=10    → 8.56
  score=25     → 8.75      score=100   → 9.07
  score=1 000  → 9.60      score=1e6   → 11.20
  score=1e9    → 12.80     score=1e12  → 14.40
  score≥1e15+  → 15.99     (hard clip, never reached in practice)

Invariants preserved *after* compression (compress is strictly monotone):
  compress(mean_abs_z)  ≤  compress(max_abs_z)        ← mean ≤ max
  compress(max_abs_z)  ==  compress(top_feature_z)    ← max IS the top feature
  relative ranking within feature_details             ← fully preserved

Gap note
--------
There is a deliberate gap in the output range: no stored value can fall in
(7.99, 8.51).  Scores just below 8.0 store as-is; scores just above 8.0 store
as ≥ 8.51.  This gap is an accepted trade-off for simplicity — the function
remains monotone on both sides of the boundary.
"""

import math

_COMPRESS_THRESHOLD: float = 8.0
_LOG_NORM: float = 15.0
_STORE_CAP: float = 15.99


def compress_score(score: float) -> float:
    """Return a storage-safe z-score, compressing astronomical values.

    Apply this function consistently to *all* z-score-derived fields that will
    be stored in the database, published to Kafka, or shown to an LLM:
      • anomaly_score  (mean of per-feature z-scores above threshold)
      • max_abs_z      (max of per-feature z-scores)
      • individual feature z_score entries in the features array

    Because the function is strictly monotone, every relative ordering between
    these values is preserved after compression.

    Parameters
    ----------
    score:
        Raw z-score (non-negative float).  Negative values are clamped to 0.

    Returns
    -------
    float
        Compressed z-score, rounded to 4 decimal places.
    """
    score = max(score, 0.0)
    if score < _COMPRESS_THRESHOLD:
        return round(score, 4)
    return round(
        min(
            8.0 + 8.0 * math.log10(1.0 + score) / _LOG_NORM,
            _STORE_CAP,
        ),
        4,
    )
