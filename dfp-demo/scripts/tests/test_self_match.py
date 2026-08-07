#!/usr/bin/env python3
"""
Test script to diagnose self-match bug in similarity search.

Tests whether detections find themselves as most similar despite exclude_self=True.
"""

import json
import sys
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from modules.ai.embeddings.similarity_search import SimilaritySearch
from modules.ai.shared.feature_bridge import FeatureBridge


def test_self_match(jsonl_path: str, num_tests: int = 10):
    """
    Test if exclude_self works correctly.

    Args:
        jsonl_path: Path to paired detections JSONL
        num_tests: Number of detections to test
    """
    print("=" * 80)
    print("SELF-MATCH BUG TEST")
    print("=" * 80)
    print()

    # Initialize services
    similarity = SimilaritySearch()
    bridge = FeatureBridge()

    # Load test detections
    test_records = []
    with open(jsonl_path) as f:
        for i, line in enumerate(f):
            if i >= num_tests:
                break
            record = json.loads(line)
            detection = bridge.dict_to_detection(record["detection"])
            test_records.append((record, detection))

    print(f"Testing {len(test_records)} detections for self-matches...\n")

    # Test each detection
    self_matches = []
    no_self_matches = []

    for i, (_record, detection) in enumerate(test_records, 1):
        # Construct detection_id the SAME way similarity_search.py does
        timestamp_str = (
            detection.timestamp.isoformat() if hasattr(detection.timestamp, "isoformat") else str(detection.timestamp)
        )
        timestamp_normalized = timestamp_str.replace("+00:00", "").replace("Z", "")
        expected_detection_id = f"{detection.user_id}_{timestamp_normalized}"

        # Get similar detections (with exclude_self=True)
        similar_results = similarity.get_similar_to_new(detection, top_k=5, min_similarity=0.5, exclude_self=True)

        # Check if detection found itself
        found_self = False
        for result in similar_results:
            if result.detection_id == expected_detection_id:
                found_self = True
                self_matches.append(
                    {
                        "index": i,
                        "detection_id": expected_detection_id,
                        "user_id": detection.user_id,
                        "timestamp": timestamp_str,
                        "timestamp_normalized": timestamp_normalized,
                        "similarity_score": result.similarity_score,
                        "result_detection_id": result.detection_id,
                    }
                )
                break

        if not found_self:
            no_self_matches.append(
                {
                    "index": i,
                    "detection_id": expected_detection_id,
                    "user_id": detection.user_id,
                    "timestamp_normalized": timestamp_normalized,
                }
            )

        # Progress indicator
        status = "❌ SELF-MATCH" if found_self else "✅ OK"
        print(f"  {i:2d}. {detection.user_id[:30]:30s} | {status}")

    # Summary
    print()
    print("=" * 80)
    print("RESULTS")
    print("=" * 80)
    print()
    print(f"Total tested:       {len(test_records)}")
    print(f"Self-matches:       {len(self_matches)} ({len(self_matches) / len(test_records) * 100:.1f}%)")
    print(f"Correctly excluded: {len(no_self_matches)} ({len(no_self_matches) / len(test_records) * 100:.1f}%)")
    print()

    # Show self-match details
    if self_matches:
        print("=" * 80)
        print("SELF-MATCH DETAILS (BUG CASES)")
        print("=" * 80)
        print()
        for match in self_matches[:5]:  # Show first 5
            print(f"Detection #{match['index']}:")
            print(f"  User:                {match['user_id']}")
            print(f"  Timestamp (raw):     {match['timestamp']}")
            print(f"  Timestamp (norm):    {match['timestamp_normalized']}")
            print(f"  Expected ID:         {match['detection_id']}")
            print(f"  Result ID:           {match['result_detection_id']}")
            print(f"  Similarity:          {match['similarity_score']:.4f}")
            print(f"  IDs Match:           {match['detection_id'] == match['result_detection_id']}")
            print()

        if len(self_matches) > 5:
            print(f"  ... and {len(self_matches) - 5} more self-matches\n")

    # Show correct exclusions
    if no_self_matches:
        print("=" * 80)
        print("CORRECTLY EXCLUDED (first 3 examples)")
        print("=" * 80)
        print()
        for match in no_self_matches[:3]:
            print(f"Detection #{match['index']}:")
            print(f"  User:          {match['user_id']}")
            print(f"  Detection ID:  {match['detection_id']}")
            print("  Status:        ✅ Self excluded from results")
            print()

    print("=" * 80)
    print()

    if self_matches:
        print("❌ BUG CONFIRMED: exclude_self is NOT working")
        print(f"   {len(self_matches)}/{len(test_records)} detections found themselves in results")
        print()
        print("Next steps:")
        print("  1. Check if detection_id formats match between storage and search")
        print("  2. Verify timestamp normalization is applied consistently")
        print("  3. Add debug logging to similarity_search.py line 315-317")
    else:
        print("✅ BUG FIXED: exclude_self is working correctly")
        print("   All detections properly excluded themselves from results")

    print()


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Test self-match bug in similarity search")
    parser.add_argument(
        "--jsonl",
        default="data/input/ai/synthetic_paired_detections.jsonl",
        help="Path to paired detections JSONL (default: data/input/ai/synthetic_paired_detections.jsonl)",
    )
    parser.add_argument("--num-tests", type=int, default=20, help="Number of detections to test (default: 20)")

    args = parser.parse_args()

    test_self_match(args.jsonl, args.num_tests)
