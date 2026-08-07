#!/usr/bin/env python3
"""
Neo4j Knowledge Graph Metrics

Display comprehensive metrics about the populated Neo4j knowledge graph.
Shows node counts, relationship counts, top users, apps, devices, locations, browsers, OS, IPs, and client apps.
"""

import sys
from pathlib import Path

# Add project root (dfp-demo/) to path
sys.path.append(str(Path(__file__).parents[3]))

from modules.ai.entity_extraction.graph_populator import GraphPopulator


def main():
    print("=" * 80)
    print("NEO4J KNOWLEDGE GRAPH METRICS")
    print("=" * 80)

    with GraphPopulator() as populator:
        if not populator.driver:
            print("Neo4j not available")
            print("   Check services: ./services/check_services.sh")
            sys.exit(1)

        stats = populator.get_graph_stats()

        print("\nNODE COUNTS:")
        print(f"   Users:             {stats['nodes']['users']:>6,}")
        print(f"   Applications:      {stats['nodes']['applications']:>6,}")
        print(f"   Devices:           {stats['nodes']['devices']:>6,}")
        print(f"   Browsers:          {stats['nodes']['browsers']:>6,}")
        print(f"   Operating Systems: {stats['nodes']['operating_systems']:>6,}")
        print(f"   IP Addresses:      {stats['nodes']['ip_addresses']:>6,}")
        print(f"   Client Apps:       {stats['nodes']['client_apps']:>6,}")
        print(f"   Locations:         {stats['nodes']['locations']:>6,}")
        print(f"   Detections:        {stats['nodes']['detections']:>6,}")
        print(f"   {'─' * 32}")
        print(f"   TOTAL:             {stats['nodes']['total']:>6,}")

        print("\nRELATIONSHIP COUNTS:")
        print(f"   User → Detection (GENERATED):    {stats['relationships']['generated']:>6,}")
        print(f"   Detection → App (ACCESSED):      {stats['relationships']['accessed']:>6,}")
        print(f"   Detection → Device (FROM_DEVICE):{stats['relationships']['from_device']:>6,}")
        print(f"   Detection → Browser (USED_BROWSER):{stats['relationships']['used_browser']:>6,}")
        print(f"   Detection → OS (ON_OS):          {stats['relationships']['on_os']:>6,}")
        print(f"   Detection → IP (FROM_IP):        {stats['relationships']['from_ip']:>6,}")
        print(f"   Detection → Client (VIA_CLIENT): {stats['relationships']['via_client']:>6,}")
        print(f"   Detection → Location (FROM_LOCATION):{stats['relationships']['from_location']:>6,}")
        print(f"   {'─' * 45}")
        print(f"   TOTAL:                           {stats['relationships']['total']:>6,}")

        # Calculate averages
        if stats["nodes"]["detections"] > 0:
            avg_rels_per_detection = stats["relationships"]["total"] / stats["nodes"]["detections"]
            print("\nAVERAGES:")
            print(f"   Relationships per detection: {avg_rels_per_detection:.2f}")
            if stats["nodes"]["users"] > 0:
                avg_detections_per_user = stats["nodes"]["detections"] / stats["nodes"]["users"]
                print(f"   Detections per user:         {avg_detections_per_user:.1f}")

        # Query for additional metrics
        with populator.driver.session(database=populator.database) as session:
            # Most active users
            print("\nTOP 5 USERS BY DETECTIONS:")
            result = session.run(
                """
                MATCH (u:User)-[:GENERATED]->(d:Detection)
                RETURN u.user_id as user, count(d) as detections
                ORDER BY detections DESC
                LIMIT 5
            """
            )
            for i, record in enumerate(result, 1):
                print(f"   {i}. {record['user']}: {record['detections']} detections")

            # Most accessed applications
            print("\nTOP APPLICATIONS:")
            result = session.run(
                """
                MATCH (d:Detection)-[:ACCESSED]->(a:Application)
                RETURN a.name as app, count(d) as accesses
                ORDER BY accesses DESC
            """
            )
            for i, record in enumerate(result, 1):
                print(f"   {i}. {record['app']}: {record['accesses']} accesses")

            # Most common devices
            print("\nTOP 5 DEVICES:")
            result = session.run(
                """
                MATCH (d:Detection)-[:FROM_DEVICE]->(dev:Device)
                RETURN dev.name as device, count(d) as usage
                ORDER BY usage DESC
                LIMIT 5
            """
            )
            for i, record in enumerate(result, 1):
                print(f"   {i}. {record['device']}: {record['usage']} usages")

            # Most common locations
            print("\nTOP LOCATIONS:")
            result = session.run(
                """
                MATCH (d:Detection)-[:FROM_LOCATION]->(l:Location)
                RETURN l.city as location, count(d) as visits
                ORDER BY visits DESC
            """
            )
            for i, record in enumerate(result, 1):
                print(f"   {i}. {record['location']}: {record['visits']} detections")

            # Most common browsers
            print("\nTOP 5 BROWSERS:")
            result = session.run(
                """
                MATCH (d:Detection)-[:USED_BROWSER]->(b:Browser)
                RETURN b.name as browser, count(d) as usage
                ORDER BY usage DESC
                LIMIT 5
            """
            )
            for i, record in enumerate(result, 1):
                print(f"   {i}. {record['browser']}: {record['usage']} usages")

            # Most common operating systems
            print("\nTOP 5 OPERATING SYSTEMS:")
            result = session.run(
                """
                MATCH (d:Detection)-[:ON_OS]->(os:OperatingSystem)
                RETURN os.name as os, count(d) as usage
                ORDER BY usage DESC
                LIMIT 5
            """
            )
            for i, record in enumerate(result, 1):
                print(f"   {i}. {record['os']}: {record['usage']} usages")

            # Most common client apps
            print("\nTOP 5 CLIENT APPS:")
            result = session.run(
                """
                MATCH (d:Detection)-[:VIA_CLIENT]->(ca:ClientApp)
                RETURN ca.name as client_app, count(d) as usage
                ORDER BY usage DESC
                LIMIT 5
            """
            )
            for i, record in enumerate(result, 1):
                print(f"   {i}. {record['client_app']}: {record['usage']} usages")

            # Legacy auth detection (security concern)
            print("\nLEGACY AUTH USAGE (Security Risk):")
            result = session.run(
                """
                MATCH (d:Detection)-[:VIA_CLIENT]->(ca:ClientApp)
                WHERE ca.name IN ['POP3', 'IMAP4', 'SMTP']
                RETURN ca.name as client_app, count(d) as detections
                ORDER BY detections DESC
            """
            )
            legacy_found = False
            for record in result:
                legacy_found = True
                print(f"   ⚠️  {record['client_app']}: {record['detections']} detections")
            if not legacy_found:
                print("   ✅ No legacy auth methods detected")

            # Detection type distribution
            print("\nDETECTION COVERAGE (Entity Extraction):")
            result = session.run(
                """
                MATCH (d:Detection)
                WITH d,
                     exists((d)-[:ACCESSED]->()) as has_app,
                     exists((d)-[:FROM_DEVICE]->()) as has_device,
                     exists((d)-[:USED_BROWSER]->()) as has_browser,
                     exists((d)-[:ON_OS]->()) as has_os,
                     exists((d)-[:FROM_IP]->()) as has_ip,
                     exists((d)-[:VIA_CLIENT]->()) as has_client,
                     exists((d)-[:FROM_LOCATION]->()) as has_location
                RETURN
                    sum(case when has_app then 1 else 0 end) as with_app,
                    sum(case when has_device then 1 else 0 end) as with_device,
                    sum(case when has_browser then 1 else 0 end) as with_browser,
                    sum(case when has_os then 1 else 0 end) as with_os,
                    sum(case when has_ip then 1 else 0 end) as with_ip,
                    sum(case when has_client then 1 else 0 end) as with_client,
                    sum(case when has_location then 1 else 0 end) as with_location,
                    count(d) as total
            """
            )
            record = result.single()
            if record:
                total = record["total"]
                print(f"   App info:      {record['with_app']:>4} ({record['with_app'] / total * 100:.1f}%)")
                print(f"   Device info:   {record['with_device']:>4} ({record['with_device'] / total * 100:.1f}%)")
                print(f"   Browser info:  {record['with_browser']:>4} ({record['with_browser'] / total * 100:.1f}%)")
                print(f"   OS info:       {record['with_os']:>4} ({record['with_os'] / total * 100:.1f}%)")
                print(f"   IP info:       {record['with_ip']:>4} ({record['with_ip'] / total * 100:.1f}%)")
                print(f"   Client info:   {record['with_client']:>4} ({record['with_client'] / total * 100:.1f}%)")
                print(f"   Location info: {record['with_location']:>4} ({record['with_location'] / total * 100:.1f}%)")

    print("\n" + "=" * 80)
    print("Metrics retrieved successfully")
    print("=" * 80)
    print("\nNeo4j Browser: http://localhost:7474")
    print("Example queries:")
    print("  - MATCH (u:User)-[:GENERATED]->(d:Detection) RETURN u, d LIMIT 25")
    print("  - MATCH (d:Detection)-[:VIA_CLIENT]->(ca:ClientApp) WHERE ca.name = 'POP3' RETURN d, ca")
    print("  - MATCH path = (u:User)-[:GENERATED]->(d:Detection)-[:USED_BROWSER]->(b:Browser)")
    print("    RETURN u.user_id, b.name, count(*) as usage ORDER BY usage DESC")
    print("  - MATCH (d:Detection)-[:ON_OS]->(os:OperatingSystem) RETURN os.name, count(d) ORDER BY count(d) DESC")


if __name__ == "__main__":
    main()
