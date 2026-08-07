#!/usr/bin/env python3
"""
Qdrant Vector Database Metrics

Display comprehensive metrics about the populated Qdrant collection.
Shows vector counts, detection_id formats, timestamp formats, and identifies self-match issues.

Usage:
    python scripts/utils/qdrant_metrics.py
"""

import sys
from pathlib import Path

from qdrant_client import QdrantClient

# Add project root (dfp-demo/) to path
sys.path.append(str(Path(__file__).parents[3]))


def check_self_match_format_mismatch(client, collection_name="dfp_detections", sample_size=20):
    """
    Check for detection_id format inconsistencies that cause self-matches.

    Returns dict with:
        - has_timezone_in_storage: bool
        - sample_detection_ids: list
        - format_issues: list
    """
    points = client.scroll(collection_name=collection_name, limit=sample_size, with_payload=True, with_vectors=False)[0]

    issues = []
    sample_ids = []
    has_timezone = False

    for point in points:
        detection_id = point.payload.get("detection_id", "N/A")
        sample_ids.append(detection_id)

        # Check if detection_id contains timezone suffix
        if "+00:00" in str(detection_id) or detection_id.endswith("Z"):
            has_timezone = True
            issues.append(
                {
                    "detection_id": detection_id,
                    "issue": "Contains timezone suffix (+00:00 or Z)",
                    "expected": detection_id.replace("+00:00", "").replace("Z", ""),
                }
            )

    return {
        "has_timezone_in_storage": has_timezone,
        "sample_detection_ids": sample_ids[:5],  # First 5 for display
        "format_issues": issues,
    }


def main():
    print("=" * 80)
    print("QDRANT VECTOR DATABASE METRICS")
    print("=" * 80)

    try:
        client = QdrantClient(host="localhost", port=6333)

        # Check if collection exists
        try:
            collection_info = client.get_collection(collection_name="dfp_detections")
        except Exception as e:
            print("\nCollection 'dfp_detections' not found")
            print(f"   Error: {e}")
            print(
                "\n   Run: python modules/ai/embeddings/similarity_search.py --jsonl data/input/detections.jsonl --limit 1000"
            )
            sys.exit(1)

        # Collection stats
        points_count = collection_info.points_count or 0

        # Get vector config (handle both dict and direct access)
        vector_config = collection_info.config.params.vectors
        vector_size = "N/A"
        vector_distance = "N/A"

        if isinstance(vector_config, dict):
            # Multi-vector mode, get the first/default vector
            if vector_config:
                first_vector = list(vector_config.values())[0]
                vector_size = getattr(first_vector, "size", "N/A")
                vector_distance = getattr(first_vector, "distance", "N/A")
        else:
            # Single vector mode
            vector_size = getattr(vector_config, "size", "N/A")
            vector_distance = getattr(vector_config, "distance", "N/A")

        print("\nCOLLECTION INFO:")
        print("   Name:         dfp_detections")
        print(f"   Points:       {points_count:>6,}")
        print(f"   Vector dim:   {vector_size}")
        print(f"   Distance:     {vector_distance}")

        if points_count == 0:
            print("\nCollection is empty")
            print(
                "   Run: python modules/ai/embeddings/similarity_search.py --jsonl data/input/detections.jsonl --limit 1000"
            )
            sys.exit(0)

        # Sample detection_ids and check for format issues
        print("\n" + "=" * 80)
        print("DETECTION_ID FORMAT ANALYSIS (Self-Match Bug Check)")
        print("=" * 80)

        format_check = check_self_match_format_mismatch(client, sample_size=20)

        print("\nSAMPLE DETECTION_IDs (first 5):")
        for i, det_id in enumerate(format_check["sample_detection_ids"], 1):
            print(f"   {i}. {det_id}")

        print("\nFORMAT ANALYSIS:")
        print(f"   Timezone in storage: {'YES' if format_check['has_timezone_in_storage'] else 'NO'}")

        if format_check["format_issues"]:
            print(f"\nFOUND {len(format_check['format_issues'])} FORMAT ISSUES:")
            print("\n   These detection_ids contain timezone suffixes that will cause self-match bugs")
            print("   when exclude_self comparison fails due to format mismatch:\n")

            for issue in format_check["format_issues"][:5]:  # Show first 5
                print(f"   STORED:   {issue['detection_id']}")
                print(f"   EXPECTED: {issue['expected']}")
                print()

            if len(format_check["format_issues"]) > 5:
                print(f"   ... and {len(format_check['format_issues']) - 5} more")

            print("\n   ACTION REQUIRED:")
            print("   1. Clear Qdrant: DELETE FROM qdrant_client.delete_collection('dfp_detections')")
            print("   2. Verify timestamp normalization in similarity_search.py:")
            print("      - populate_from_jsonl() lines 505-508")
            print("      - populate_from_csv() lines 395-398")
            print("      - get_similar_to_new() lines 309-312")
            print("   3. Re-populate: python modules/ai/embeddings/similarity_search.py --jsonl ... --limit 1000")
        else:
            print("   All detection_ids use normalized format (no timezone suffixes)")
            print("   exclude_self comparison should work correctly")

        # User distribution
        print("\n" + "=" * 80)
        print("USER DISTRIBUTION (top 10)")
        print("=" * 80)

        # Get all points and count by user
        # Ensure limit is an int (points_count defaults to 0 if None)
        limit_value = points_count if points_count > 0 else 1
        all_points = client.scroll(
            collection_name="dfp_detections", limit=limit_value, with_payload=True, with_vectors=False
        )[0]

        user_counts = {}
        for point in all_points:
            if point.payload:
                user_id = point.payload.get("user_id", "unknown")
                user_counts[user_id] = user_counts.get(user_id, 0) + 1

        top_users = sorted(user_counts.items(), key=lambda x: x[1], reverse=True)[:10]

        print()
        for i, (user_id, count) in enumerate(top_users, 1):
            print(f"   {i:2}. {user_id[:50]:50} {count:>5} vectors")

        # Timestamp format check
        print("\n" + "=" * 80)
        print("TIMESTAMP FORMAT SAMPLES")
        print("=" * 80)

        print("\nFirst 5 timestamps from payloads:")
        sample_points = client.scroll(collection_name="dfp_detections", limit=5, with_payload=True, with_vectors=False)[
            0
        ]

        for i, point in enumerate(sample_points, 1):
            if point.payload:
                timestamp = point.payload.get("timestamp", "N/A")
                user_id = point.payload.get("user_id", "N/A")
                print(f"   {i}. {user_id[:40]:40} | {timestamp}")
            else:
                print(f"   {i}. No payload")

        print("\n" + "=" * 80)
        print("SUMMARY")
        print("=" * 80)

        if format_check["format_issues"]:
            print("\nCRITICAL: Self-match bug detected")
            print(f"   {len(format_check['format_issues'])} detection_ids have timezone suffixes")
            print("   This causes exclude_self to fail, resulting in detections finding themselves")
            print("\n   Next steps:")
            print("   1. Clear Qdrant collection")
            print("   2. Verify timestamp normalization in similarity_search.py")
            print("   3. Re-populate with normalized timestamps")
        else:
            print("\nQdrant populated successfully")
            print(f"   {points_count:,} detection vectors ready for similarity search")
            print("   All detection_ids use normalized format")
            print("   exclude_self should work correctly")

        print("\n" + "=" * 80)

    except Exception as e:
        print("\nError connecting to Qdrant")
        print(f"   {e}")
        print("\n   Check services: ./services/check_services.sh")
        sys.exit(1)


if __name__ == "__main__":
    main()
