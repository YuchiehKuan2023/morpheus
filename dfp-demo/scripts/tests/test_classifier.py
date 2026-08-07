#!/usr/bin/env python3
"""
Probe the trained DistilBERT root-cause classifier.

Three test tiers:
  1. CLEAR      — single dominant signal; model should be high-confidence
  2. AMBIGUOUS  — conflicting signals; tests priority logic
  3. EDGE       — noisy, minimal, or unexpected inputs

Usage:
    python scripts/tests/test_classifier.py
    python scripts/tests/test_classifier.py --verbose   # show per-class probability table
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from modules.ai.root_cause.classifier import RootCauseClassifier

MODEL_DIR = "data/models/root_cause"

# ---------------------------------------------------------------------------
# Test cases: (description, top_features, anomaly_score, expected_sub_category)
# expected=None means "no assertion — just observe"
# ---------------------------------------------------------------------------
TEST_CASES = [
    # ── TIER 1: Clear single-signal ──────────────────────────────────────
    (
        "CLEAR | Impossible travel (speed + location)",
        "travel_speed_kmph=15200 (z=18.3), locationCity=Tokyo (z=22.1), locationCountry=Japan (z=19.5)",
        14.5,
        "Impossible Travel",
    ),
    (
        "CLEAR | Multi-factor (app + device + location)",
        "appDisplayName=Workday (z=9.1), deviceDetaildisplayName=TEST-WORKSTATION-X (z=8.4), locationCity=Lagos (z=12.0)",
        8.3,
        "Multi-Factor Anomaly",
    ),
    (
        "CLEAR | Location with unusual device (no travel speed)",
        "locationCity=Mumbai (z=7.3), locationCountry=India (z=8.2), deviceDetaildisplayName=TEST-WORKSTATION-X (z=6.1)",
        5.1,
        "Location with Unusual Device",
    ),
    (
        "CLEAR | Unknown device (UNKNOWN- prefix)",
        "deviceDetaildisplayName=UNKNOWN-LAPTOP-999 (z=6.5)",
        3.2,
        "Unknown Device",
    ),
    (
        "CLEAR | Unusual application only",
        "appDisplayName=Salesforce (z=4.8)",
        2.6,
        "Unusual Application",
    ),
    (
        "CLEAR | Unusual location only",
        "locationCity=Nairobi (z=6.9), locationCountry=Kenya (z=9.3)",
        3.8,
        "Unusual Location",
    ),
    (
        "CLEAR | Unusual browser only",
        "deviceDetailbrowser=Brave 1.60 (z=5.1)",
        2.9,
        "Unusual Browser",
    ),
    (
        "CLEAR | Unusual OS only",
        "deviceDetailoperatingSystem=ChromeOS 120 (z=4.0)",
        3.1,
        "Unusual Operating System",
    ),
    (
        "CLEAR | Broad deviation (high logcount, no other signals)",
        "logCount=1200 (z=3.1)",
        3.5,
        "Broad Deviation",
    ),
    # ── TIER 2: Ambiguous / conflicting signals ───────────────────────────
    (
        "AMBIGUOUS | Travel speed + app anomaly — travel should win",
        "travel_speed_kmph=8400 (z=14.1), appDisplayName=Workday (z=6.3), locationCity=Seoul (z=15.0)",
        13.2,
        "Impossible Travel",  # travel_speed is the dominant override
    ),
    (
        "AMBIGUOUS | App + browser (not device or location) — Multi-Factor or App?",
        "appDisplayName=ServiceNow (z=4.8), deviceDetailbrowser=Opera 105.0 (z=4.8)",
        4.0,
        None,  # heuristic says Multi-Factor (app+device), observe what model says
    ),
    (
        "AMBIGUOUS | Device (UNKNOWN) + location — which wins?",
        "deviceDetaildisplayName=UNKNOWN-LAPTOP-999 (z=5.4), locationCity=São Paulo (z=7.1), locationCountry=Brazil (z=8.0)",
        5.8,
        None,  # heuristic: Location with Unusual Device (device+location); observe model
    ),
    (
        "AMBIGUOUS | Low score impossible travel (borderline MEDIUM)",
        "travel_speed_kmph=3200 (z=6.1), locationCity=Berlin (z=9.0)",
        5.2,
        "Impossible Travel",  # travel_speed always wins regardless of score
    ),
    # ── TIER 3: Edge cases ────────────────────────────────────────────────
    (
        "EDGE | Empty top_features, high score",
        "",
        7.5,
        None,  # model has no signal — observe what it falls back to
    ),
    (
        "EDGE | Completely novel feature name (not in training)",
        "someNewFeature=UNUSUAL-VALUE-XYZ (z=9.9)",
        4.0,
        None,  # no training signal for this feature name
    ),
    (
        "EDGE | All 9 feature types simultaneously",
        (
            "travel_speed_kmph=12000 (z=17.0), appDisplayName=Workday (z=8.1), "
            "deviceDetaildisplayName=UNKNOWN-LAPTOP-999 (z=6.2), locationCity=Sydney (z=15.0), "
            "deviceDetailbrowser=Brave 1.60 (z=4.1), deviceDetailoperatingSystem=ChromeOS 120 (z=3.8), "
            "logCount=950 (z=3.3)"
        ),
        15.0,
        None,  # most dominant signal should win — probably Impossible Travel
    ),
    (
        "EDGE | Typical score, very short feature string",
        "locationCity=Oslo (z=3.1)",
        2.6,
        "Unusual Location",
    ),
]


def run(verbose: bool) -> int:
    clf = RootCauseClassifier()
    clf.load(MODEL_DIR)

    passed = 0
    failed = 0
    observed = 0

    col_w = 52
    print(f"\n{'─' * 90}")
    print(f"  {'Test Case':<{col_w}}  {'Predicted':<28}  {'Conf':>5}  {'Result'}")
    print(f"{'─' * 90}")

    for desc, top_features, score, expected in TEST_CASES:
        result = clf.predict(
            anomaly_id="test-000",
            top_features=top_features,
            anomaly_score=score,
        )

        pred = result.sub_category
        conf = result.confidence

        if expected is None:
            status = "OBSERVE"
            observed += 1
        elif pred == expected:
            status = "PASS ✓"
            passed += 1
        else:
            status = f"FAIL ✗  (expected: {expected})"
            failed += 1

        # Truncate description for table width
        disp = desc[:col_w] if len(desc) <= col_w else desc[: col_w - 1] + "…"
        print(f"  {disp:<{col_w}}  {pred:<28}  {conf:>5.2f}  {status}")

        if verbose:
            # Print per-class probability table
            sorted_scores = sorted(result.raw_scores.items(), key=lambda x: -x[1])
            for label, p in sorted_scores:
                bar = "█" * int(p * 30)
                marker = " ◄" if label == pred else ""
                print(f"      {label:<32}  {p:.4f}  {bar}{marker}")
            print()

    print(f"{'─' * 90}")
    total_asserted = passed + failed
    print(
        f"\n  Results: {passed}/{total_asserted} assertions passed"
        f"{'  ✓ ALL PASS' if failed == 0 else f'  ✗ {failed} FAILED'}"
        f"  |  {observed} observed (no assertion)\n"
    )

    return 1 if failed > 0 else 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Probe the trained root-cause classifier")
    parser.add_argument("--verbose", action="store_true", help="Show per-class probability table for each test")
    args = parser.parse_args()
    sys.exit(run(args.verbose))
