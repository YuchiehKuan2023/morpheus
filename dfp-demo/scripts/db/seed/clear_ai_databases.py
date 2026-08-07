#!/usr/bin/env python3
"""
Clear AI Databases

Clears all AI-related databases:
- PostgreSQL: enriched_anomalies table
- Neo4j: All nodes and relationships
- Qdrant: dfp_detections collection

Usage:
    python scripts/utils/clear_ai_databases.py --confirm
"""

import argparse
import os
import sys
from pathlib import Path

# Add project root (dfp-demo/) to path
sys.path.append(str(Path(__file__).parents[3]))

# Load environment variables from .env
try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass  # dotenv not required if env vars already set

try:
    import psycopg2

    POSTGRES_AVAILABLE = True
except ImportError:
    POSTGRES_AVAILABLE = False
    psycopg2 = None  # type: ignore
    print("Warning: psycopg2 not available")

try:
    from neo4j import GraphDatabase

    NEO4J_AVAILABLE = True
except ImportError:
    NEO4J_AVAILABLE = False
    GraphDatabase = None  # type: ignore
    print("Warning: neo4j not available")

try:
    from qdrant_client import QdrantClient

    QDRANT_AVAILABLE = True
except ImportError:
    QDRANT_AVAILABLE = False
    QdrantClient = None  # type: ignore
    print("Warning: qdrant-client not available")


def clear_postgresql():
    """Clear PostgreSQL enriched_anomalies table."""
    if not POSTGRES_AVAILABLE or psycopg2 is None:
        print("PostgreSQL driver not available")
        return False

    try:
        from modules.utils.db import get_db_params

        conn = psycopg2.connect(**get_db_params())
        cursor = conn.cursor()

        # Get count before
        cursor.execute("SELECT COUNT(*) FROM enriched_anomalies")
        result = cursor.fetchone()
        count_before = result[0] if result else 0

        # Truncate table
        cursor.execute("TRUNCATE TABLE enriched_anomalies RESTART IDENTITY CASCADE")
        conn.commit()

        # Get count after
        cursor.execute("SELECT COUNT(*) FROM enriched_anomalies")
        result = cursor.fetchone()
        count_after = result[0] if result else 0

        cursor.close()
        conn.close()

        print(f"PostgreSQL: Deleted {count_before} records (now {count_after})")
        return True

    except Exception as e:
        print(f"PostgreSQL error: {e}")
        return False


def clear_neo4j():
    """Clear Neo4j graph database."""
    if not NEO4J_AVAILABLE or GraphDatabase is None:
        print("Neo4j driver not available")
        return False

    try:
        driver = GraphDatabase.driver(
            os.getenv("NEO4J_URI", "bolt://localhost:7687"),
            auth=(os.getenv("NEO4J_USER", "neo4j"), os.getenv("NEO4J_PASSWORD", "")),
        )

        with driver.session() as session:
            # Get count before
            result = session.run("MATCH (n) RETURN count(n) as count")
            record = result.single()
            count_before = record["count"] if record else 0

            # Delete all nodes and relationships
            session.run("MATCH (n) DETACH DELETE n")

            # Get count after
            result = session.run("MATCH (n) RETURN count(n) as count")
            record = result.single()
            count_after = record["count"] if record else 0

        driver.close()

        print(f"Neo4j: Deleted {count_before} nodes (now {count_after})")
        return True

    except Exception as e:
        print(f"Neo4j error: {e}")
        return False


def clear_qdrant():
    """Clear Qdrant vector collection."""
    if not QDRANT_AVAILABLE or QdrantClient is None:
        print("Qdrant client not available")
        return False

    try:
        client = QdrantClient(host="localhost", port=6333)

        # Get count before
        try:
            collection_info = client.get_collection("dfp_detections")
            count_before = collection_info.points_count
        except Exception:
            count_before = 0

        # Delete collection
        try:
            client.delete_collection("dfp_detections")
            print(f"Qdrant: Deleted collection with {count_before} vectors")
        except Exception:
            print("Qdrant: No collection to delete (was empty)")

        # Recreate collection
        from qdrant_client.models import Distance, VectorParams

        client.create_collection(
            collection_name="dfp_detections",
            vectors_config=VectorParams(size=384, distance=Distance.COSINE),
        )
        print("Qdrant: Recreated collection (empty)")

        return True

    except Exception as e:
        print(f"Qdrant error: {e}")
        return False


def main():
    parser = argparse.ArgumentParser(description="Clear all AI databases")
    parser.add_argument("--confirm", action="store_true", help="Confirm deletion (required for safety)")
    args = parser.parse_args()

    if not args.confirm:
        print("\nWARNING: This will DELETE ALL DATA from AI databases!")
        print("   - PostgreSQL: enriched_anomalies table")
        print("   - Neo4j: All nodes and relationships")
        print("   - Qdrant: dfp_detections collection")
        print("\nAdd --confirm flag to proceed")
        sys.exit(1)

    print("\n" + "=" * 60)
    print("CLEARING AI DATABASES")
    print("=" * 60)

    results = []

    print("\n1. Clearing PostgreSQL...")
    results.append(clear_postgresql())

    print("\n2. Clearing Neo4j...")
    results.append(clear_neo4j())

    print("\n3. Clearing Qdrant...")
    results.append(clear_qdrant())

    print("\n" + "=" * 60)
    success_count = sum(results)
    total_count = len(results)

    if success_count == total_count:
        print(f"SUCCESS: All {total_count} databases cleared")
    else:
        print(f"PARTIAL: {success_count}/{total_count} databases cleared")

    print("=" * 60 + "\n")


if __name__ == "__main__":
    main()
