#!/usr/bin/env python3
"""
PostgreSQL Enriched Anomalies Metrics

Validates and analyzes enriched_anomalies table after population.

Usage:
    python scripts/utils/postgres_metrics.py
"""

import json
import os
import sys

import psycopg2


def get_table_stats(cursor) -> dict:
    """Get enriched_anomalies table statistics."""
    # Total count
    cursor.execute("SELECT COUNT(*) FROM enriched_anomalies")
    total_count = cursor.fetchone()[0]

    # User distribution
    cursor.execute(
        """
        SELECT user_id, COUNT(*) as count
        FROM enriched_anomalies
        GROUP BY user_id
        ORDER BY count DESC
        LIMIT 10
        """
    )
    top_users = cursor.fetchall()

    # Anomaly score statistics
    cursor.execute(
        """
        SELECT
            MIN(anomaly_score) as min_score,
            MAX(anomaly_score) as max_score,
            AVG(anomaly_score) as avg_score,
            PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY anomaly_score) as median_score
        FROM enriched_anomalies
        """
    )
    score_stats = cursor.fetchone()

    # Timestamp range
    cursor.execute(
        """
        SELECT
            MIN(timestamp) as earliest,
            MAX(timestamp) as latest
        FROM enriched_anomalies
        """
    )
    time_range = cursor.fetchone()

    # AI enrichment coverage
    cursor.execute(
        """
        SELECT
            COUNT(CASE WHEN ai_enrichment IS NOT NULL THEN 1 END) as with_enrichment,
            COUNT(CASE WHEN ai_enrichment IS NULL THEN 1 END) as without_enrichment
        FROM enriched_anomalies
        """
    )
    enrichment_coverage = cursor.fetchone()

    # Sample enrichment to check structure
    cursor.execute(
        """
        SELECT ai_enrichment
        FROM enriched_anomalies
        WHERE ai_enrichment IS NOT NULL
        LIMIT 1
        """
    )
    sample_enrichment = cursor.fetchone()
    enrichment_keys = []
    if sample_enrichment and sample_enrichment[0]:
        enrichment_data = sample_enrichment[0]
        if isinstance(enrichment_data, str):
            enrichment_data = json.loads(enrichment_data)
        enrichment_keys = list(enrichment_data.keys()) if isinstance(enrichment_data, dict) else []

    return {
        "total_records": total_count,
        "top_users": top_users,
        "score_stats": {
            "min": float(score_stats[0]) if score_stats[0] else 0,
            "max": float(score_stats[1]) if score_stats[1] else 0,
            "avg": float(score_stats[2]) if score_stats[2] else 0,
            "median": float(score_stats[3]) if score_stats[3] else 0,
        },
        "time_range": {"earliest": time_range[0], "latest": time_range[1]},
        "enrichment_coverage": {
            "with_enrichment": enrichment_coverage[0],
            "without_enrichment": enrichment_coverage[1],
        },
        "enrichment_keys": enrichment_keys,
    }


def main():
    """Main function."""
    print("=" * 80)
    print("POSTGRESQL ENRICHED ANOMALIES METRICS")
    print("=" * 80)

    # Connect to PostgreSQL
    try:
        from modules.utils.db import get_db_params

        conn = psycopg2.connect(**get_db_params())
        cursor = conn.cursor()
        print("\n✓ Connected to PostgreSQL")

    except psycopg2.Error as e:
        print(f"\n✗ Failed to connect to PostgreSQL: {e}")
        print("\nCheck connection:")
        print(f"   Host: {os.getenv('POSTGRES_HOST', 'localhost')}")
        print(f"   Port: {os.getenv('POSTGRES_PORT', '5432')}")
        print(f"   Database: {os.getenv('POSTGRES_DB', 'dfp_ai')}")
        print(f"   User: {os.getenv('POSTGRES_USER', 'dfp_ai')}")
        sys.exit(1)

    try:
        # Get statistics
        stats = get_table_stats(cursor)

        # Display results
        print("\nTOTAL RECORDS:")
        print(f"   Enriched anomalies: {stats['total_records']:,}")

        print("\nANOMALY SCORE STATISTICS:")
        print(f"   Min:    {stats['score_stats']['min']:.2f}")
        print(f"   Max:    {stats['score_stats']['max']:.2f}")
        print(f"   Avg:    {stats['score_stats']['avg']:.2f}")
        print(f"   Median: {stats['score_stats']['median']:.2f}")

        print("\nTIME RANGE:")
        print(f"   Earliest: {stats['time_range']['earliest']}")
        print(f"   Latest:   {stats['time_range']['latest']}")
        if stats["time_range"]["earliest"] and stats["time_range"]["latest"]:
            time_span = stats["time_range"]["latest"] - stats["time_range"]["earliest"]
            print(f"   Span:     {time_span.days} days, {time_span.seconds // 3600} hours")

        print("\nAI ENRICHMENT COVERAGE:")
        total = stats["enrichment_coverage"]["with_enrichment"] + stats["enrichment_coverage"]["without_enrichment"]
        with_pct = (stats["enrichment_coverage"]["with_enrichment"] / total * 100) if total > 0 else 0
        print(f"   With AI enrichment:    {stats['enrichment_coverage']['with_enrichment']:,} ({with_pct:.1f}%)")
        print(f"   Without AI enrichment: {stats['enrichment_coverage']['without_enrichment']:,}")

        if stats["enrichment_keys"]:
            print("\nAI ENRICHMENT STRUCTURE:")
            print(f"   Keys: {', '.join(stats['enrichment_keys'])}")

        print("\nTOP 10 USERS BY DETECTION COUNT:")
        for i, (user_id, count) in enumerate(stats["top_users"], 1):
            print(f"   {i:2d}. {user_id:<40} {count:3d} detections")

        # Sample record
        cursor.execute(
            """
            SELECT anomaly_id, user_id, timestamp, anomaly_score,
                   jsonb_pretty(ai_enrichment::jsonb) as enrichment_pretty
            FROM enriched_anomalies
            WHERE ai_enrichment IS NOT NULL
            LIMIT 1
            """
        )
        sample = cursor.fetchone()

        if sample:
            print("\nSAMPLE ENRICHED RECORD:")
            print(f"   Anomaly ID:     {sample[0]}")
            print(f"   User ID:        {sample[1]}")
            print(f"   Timestamp:      {sample[2]}")
            print(f"   Anomaly Score:  {sample[3]:.2f}")
            print("\n   AI Enrichment (formatted):")
            # Indent the pretty-printed JSON
            enrichment_lines = sample[4].split("\n") if sample[4] else []
            for line in enrichment_lines[:20]:  # Show first 20 lines
                print(f"   {line}")
            if len(enrichment_lines) > 20:
                print(f"   ... ({len(enrichment_lines) - 20} more lines)")

        print("\n" + "=" * 80)
        print("Metrics retrieved successfully")
        print("=" * 80)

        print("\nPostgreSQL Connection:")
        print(f"   Host: {os.getenv('POSTGRES_HOST', 'localhost')}")
        print(f"   Database: {os.getenv('POSTGRES_DB', 'dfp_ai')}")
        print("   Table: enriched_anomalies")

    except Exception as e:
        print(f"\n✗ Error retrieving metrics: {e}")
        sys.exit(1)

    finally:
        cursor.close()
        conn.close()


if __name__ == "__main__":
    main()
