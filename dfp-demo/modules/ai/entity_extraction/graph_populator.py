"""
Neo4j Knowledge Graph Populator

Populates Neo4j knowledge graph with entities extracted from DFP detections.
Part of the always-on (Day 1) AI capabilities.

Node Types:
- User: Email addresses, baseline behavior
- Application: Office365, Salesforce, Azure Portal
- Device: Device names (LAPTOP-USER-123, WORKSTATION-USER-456)
- Browser: Web browsers (Chrome 119.0, Safari 17.0, Firefox 120.0)
- OperatingSystem: Operating systems (Windows 11, macOS 14 Sonoma, Ubuntu 22.04)
- IPAddress: IP addresses (76.211.170.177)
- ClientApp: Auth clients (POP3, Exchange Web Services, Modern Auth Clients)
- Location: Cities and countries from baselines
- Detection: Anomaly detections with metadata

Relationships (Detection Events):
- (User)-[:GENERATED]->(Detection): User triggered detection
- (Detection)-[:ACCESSED]->(Application): Detection involved app access
- (Detection)-[:FROM_DEVICE]->(Device): Detection originated from device
- (Detection)-[:USED_BROWSER]->(Browser): Detection used browser
- (Detection)-[:ON_OS]->(OperatingSystem): Detection occurred on OS
- (Detection)-[:FROM_IP]->(IPAddress): Detection originated from IP
- (Detection)-[:VIA_CLIENT]->(ClientApp): Detection via client app
- (Detection)-[:FROM_LOCATION]->(Location): Detection occurred at location

Relationships (User Baseline - Future):
- (User)-[:TYPICALLY_USES]->(Application): Aggregated normal behavior
- (User)-[:TYPICALLY_AT]->(Location): Aggregated normal locations
- (User)-[:TYPICALLY_USES_BROWSER]->(Browser): Normal browsers
- (User)-[:TYPICALLY_ON_OS]->(OperatingSystem): Normal OS
- (User)-[:TYPICALLY_FROM_IP]->(IPAddress): Normal IPs
- (User)-[:TYPICALLY_VIA_CLIENT]->(ClientApp): Normal client apps

Architecture:
- Batch processing with UNWIND for performance (100 records/batch)
- MERGE instead of CREATE for idempotency (can run multiple times)
- Indexes on common query properties (user_id, app_name, detection_id)
- Uses monitoring.py for observability
- Connects via Neo4j Python driver (bolt protocol)

Configuration:
- Neo4j URI: Set via NEO4J_URI env var (default: neo4j://localhost:7687)
- Auth: Set via NEO4J_USER and NEO4J_PASSWORD env vars
- Database: neo4j (default)
"""

import logging
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

# Add parent directory to path for imports
sys.path.append(str(Path(__file__).parent.parent.parent))

# Load environment variables from .env
try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass  # dotenv not required if env vars already set

if TYPE_CHECKING:
    from neo4j import Driver, GraphDatabase
    from neo4j.exceptions import AuthError, ServiceUnavailable

try:
    from neo4j import GraphDatabase
    from neo4j.exceptions import AuthError, ServiceUnavailable

    NEO4J_AVAILABLE = True
except ImportError:
    NEO4J_AVAILABLE = False
    GraphDatabase = None  # type: ignore
    ServiceUnavailable = Exception  # type: ignore
    AuthError = Exception  # type: ignore
    logging.warning("Neo4j driver not installed. Install with: pip install neo4j")

from modules.ai.entity_extraction.ner_service import DetectionEntities, Entity, NERService
from modules.ai.shared.feature_bridge import FeatureBridge
from modules.ai.shared.monitoring import monitor_performance, record_detection_processed

logger = logging.getLogger(__name__)


@dataclass
class GraphStats:
    """Statistics for graph population."""

    users_created: int = 0
    apps_created: int = 0
    devices_created: int = 0
    locations_created: int = 0
    detections_created: int = 0
    relationships_created: int = 0
    batches_processed: int = 0
    errors: int = 0


class GraphPopulator:
    """Populate Neo4j knowledge graph with detection entities."""

    def __init__(
        self,
        uri: str | None = None,
        user: str | None = None,
        password: str | None = None,
        database: str = "neo4j",
    ):
        """
        Initialize graph populator.

        Args:
            uri: Neo4j connection URI
            user: Neo4j username
            password: Neo4j password
            database: Neo4j database name
        """
        # Use provided params or fall back to environment variables
        self.uri = uri or os.getenv("NEO4J_URI", "bolt://localhost:7687")
        self.user = user or os.getenv("NEO4J_USER", "neo4j")
        self.password = password or os.getenv("NEO4J_PASSWORD", "")
        self.database = database
        self.driver: Driver | None = None

        if not NEO4J_AVAILABLE:
            logger.error("Neo4j driver not available. Install with: pip install neo4j")
            return

        if GraphDatabase is None:
            logger.error("Neo4j GraphDatabase is not available")
            return

        try:
            self.driver = GraphDatabase.driver(self.uri, auth=(self.user, self.password))
            # Test connection
            self.driver.verify_connectivity()
            logger.info(f"Connected to Neo4j at {self.uri}")
        except ServiceUnavailable:
            logger.error(
                f"Neo4j not available at {uri}. Check that Neo4j is running (try: ./services/check_services.sh)"
            )
            self.driver = None
        except AuthError:
            logger.error(
                f"Neo4j authentication failed. Check NEO4J_USER and NEO4J_PASSWORD environment variables or credentials in {uri}"
            )
            self.driver = None
        except Exception as e:
            logger.error(f"Failed to connect to Neo4j: {e}")
            self.driver = None

    def close(self):
        """Close Neo4j connection."""
        if self.driver:
            self.driver.close()
            logger.info("Neo4j connection closed")

    def __enter__(self):
        """Context manager entry."""
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit."""
        self.close()

    @monitor_performance("graph_populator", "create_indexes")
    def create_indexes(self):
        """Create indexes for common query patterns."""
        if not self.driver:
            logger.error("No Neo4j connection available")
            return

        indexes = [
            "CREATE INDEX user_id_index IF NOT EXISTS FOR (u:User) ON (u.user_id)",
            "CREATE INDEX app_name_index IF NOT EXISTS FOR (a:Application) ON (a.name)",
            "CREATE INDEX device_name_index IF NOT EXISTS FOR (d:Device) ON (d.name)",
            "CREATE INDEX browser_name_index IF NOT EXISTS FOR (b:Browser) ON (b.name)",
            "CREATE INDEX os_name_index IF NOT EXISTS FOR (os:OperatingSystem) ON (os.name)",
            "CREATE INDEX ip_address_index IF NOT EXISTS FOR (ip:IPAddress) ON (ip.address)",
            "CREATE INDEX client_app_name_index IF NOT EXISTS FOR (ca:ClientApp) ON (ca.name)",
            "CREATE INDEX location_city_index IF NOT EXISTS FOR (l:Location) ON (l.city)",
            "CREATE INDEX detection_id_index IF NOT EXISTS FOR (det:Detection) ON (det.detection_id)",
            "CREATE INDEX detection_timestamp_index IF NOT EXISTS FOR (det:Detection) ON (det.timestamp)",
        ]

        with self.driver.session(database=self.database) as session:
            for index_query in indexes:
                try:
                    session.run(index_query)  # type: ignore[arg-type]
                    logger.debug(f"Created index: {index_query[:50]}...")
                except Exception as e:
                    logger.warning(f"Index creation warning: {e}")

        logger.info("Indexes created successfully")

    @monitor_performance("graph_populator", "clear_graph")
    def clear_graph(self):
        """Clear all nodes and relationships (for testing/reset)."""
        if not self.driver:
            logger.error("No Neo4j connection available")
            return

        with self.driver.session(database=self.database) as session:
            session.run("MATCH (n) DETACH DELETE n")

        logger.info("Graph cleared")

    @monitor_performance("graph_populator", "populate_detection")
    def populate_detection(self, detection_entities: DetectionEntities) -> dict[str, int]:
        """
        Populate graph with a single detection and its entities.

        Args:
            detection_entities: DetectionEntities from NER service

        Returns:
            Dict with counts of created/merged nodes and relationships
        """
        if not self.driver:
            return {"error": 1}

        stats = {"nodes": 0, "relationships": 0}

        with self.driver.session(database=self.database) as session:
            # Create/merge User node
            session.run(
                """
                MERGE (u:User {user_id: $user_id})
                ON CREATE SET u.created_at = datetime()
                """,
                user_id=detection_entities.user_id,
            )
            stats["nodes"] += 1

            # Create/merge Detection node
            session.run(
                """
                MERGE (det:Detection {detection_id: $detection_id})
                ON CREATE SET
                    det.timestamp = datetime($timestamp),
                    det.user_id = $user_id,
                    det.created_at = datetime()
                """,
                detection_id=detection_entities.detection_id,
                timestamp=detection_entities.timestamp,
                user_id=detection_entities.user_id,
            )
            stats["nodes"] += 1

            # Create User -> Detection relationship
            session.run(
                """
                MATCH (u:User {user_id: $user_id})
                MATCH (det:Detection {detection_id: $detection_id})
                MERGE (u)-[:GENERATED]->(det)
                """,
                user_id=detection_entities.user_id,
                detection_id=detection_entities.detection_id,
            )
            stats["relationships"] += 1

            # Process entities by category
            for entity in detection_entities.entities:
                if entity.category == "app":
                    # Create/merge Application node
                    session.run(
                        """
                        MERGE (a:Application {name: $name})
                        ON CREATE SET
                            a.type = $type,
                            a.created_at = datetime()
                        """,
                        name=entity.text,
                        type=entity.type,
                    )
                    stats["nodes"] += 1

                    # Create Detection -> Application relationship
                    session.run(
                        """
                        MATCH (det:Detection {detection_id: $detection_id})
                        MATCH (a:Application {name: $app_name})
                        MERGE (det)-[r:ACCESSED]->(a)
                        ON CREATE SET r.confidence = $confidence
                        """,
                        detection_id=detection_entities.detection_id,
                        app_name=entity.text,
                        confidence=entity.confidence,
                    )
                    stats["relationships"] += 1

                elif entity.category == "device":
                    # Create/merge Device node
                    session.run(
                        """
                        MERGE (d:Device {name: $name})
                        ON CREATE SET
                            d.type = $type,
                            d.created_at = datetime()
                        """,
                        name=entity.text,
                        type=entity.type,
                    )
                    stats["nodes"] += 1

                    # Create Detection -> Device relationship
                    session.run(
                        """
                        MATCH (det:Detection {detection_id: $detection_id})
                        MATCH (d:Device {name: $device_name})
                        MERGE (det)-[r:FROM_DEVICE]->(d)
                        ON CREATE SET r.confidence = $confidence
                        """,
                        detection_id=detection_entities.detection_id,
                        device_name=entity.text,
                        confidence=entity.confidence,
                    )
                    stats["relationships"] += 1

                elif entity.category == "location":
                    # Create/merge Location node
                    session.run(
                        """
                        MERGE (l:Location {city: $city})
                        ON CREATE SET
                            l.type = $type,
                            l.created_at = datetime()
                        """,
                        city=entity.text,
                        type=entity.type,
                    )
                    stats["nodes"] += 1

                    # Create Detection -> Location relationship
                    session.run(
                        """
                        MATCH (det:Detection {detection_id: $detection_id})
                        MATCH (l:Location {city: $city})
                        MERGE (det)-[r:FROM_LOCATION]->(l)
                        ON CREATE SET r.confidence = $confidence
                        """,
                        detection_id=detection_entities.detection_id,
                        city=entity.text,
                        confidence=entity.confidence,
                    )
                    stats["relationships"] += 1

                elif entity.category == "browser":
                    # Create/merge Browser node
                    session.run(
                        """
                        MERGE (b:Browser {name: $name})
                        ON CREATE SET
                            b.type = $type,
                            b.created_at = datetime()
                        """,
                        name=entity.text,
                        type=entity.type,
                    )
                    stats["nodes"] += 1

                    # Create Detection -> Browser relationship
                    session.run(
                        """
                        MATCH (det:Detection {detection_id: $detection_id})
                        MATCH (b:Browser {name: $browser_name})
                        MERGE (det)-[r:USED_BROWSER]->(b)
                        ON CREATE SET r.confidence = $confidence
                        """,
                        detection_id=detection_entities.detection_id,
                        browser_name=entity.text,
                        confidence=entity.confidence,
                    )
                    stats["relationships"] += 1

                elif entity.category == "os":
                    # Create/merge OperatingSystem node
                    session.run(
                        """
                        MERGE (os:OperatingSystem {name: $name})
                        ON CREATE SET
                            os.type = $type,
                            os.created_at = datetime()
                        """,
                        name=entity.text,
                        type=entity.type,
                    )
                    stats["nodes"] += 1

                    # Create Detection -> OperatingSystem relationship
                    session.run(
                        """
                        MATCH (det:Detection {detection_id: $detection_id})
                        MATCH (os:OperatingSystem {name: $os_name})
                        MERGE (det)-[r:ON_OS]->(os)
                        ON CREATE SET r.confidence = $confidence
                        """,
                        detection_id=detection_entities.detection_id,
                        os_name=entity.text,
                        confidence=entity.confidence,
                    )
                    stats["relationships"] += 1

                elif entity.category == "ip":
                    # Create/merge IPAddress node
                    session.run(
                        """
                        MERGE (ip:IPAddress {address: $address})
                        ON CREATE SET
                            ip.type = $type,
                            ip.created_at = datetime()
                        """,
                        address=entity.text,
                        type=entity.type,
                    )
                    stats["nodes"] += 1

                    # Create Detection -> IPAddress relationship
                    session.run(
                        """
                        MATCH (det:Detection {detection_id: $detection_id})
                        MATCH (ip:IPAddress {address: $ip_address})
                        MERGE (det)-[r:FROM_IP]->(ip)
                        ON CREATE SET r.confidence = $confidence
                        """,
                        detection_id=detection_entities.detection_id,
                        ip_address=entity.text,
                        confidence=entity.confidence,
                    )
                    stats["relationships"] += 1

                elif entity.category == "client_app":
                    # Create/merge ClientApp node
                    session.run(
                        """
                        MERGE (ca:ClientApp {name: $name})
                        ON CREATE SET
                            ca.type = $type,
                            ca.created_at = datetime()
                        """,
                        name=entity.text,
                        type=entity.type,
                    )
                    stats["nodes"] += 1

                    # Create Detection -> ClientApp relationship
                    session.run(
                        """
                        MATCH (det:Detection {detection_id: $detection_id})
                        MATCH (ca:ClientApp {name: $client_app_name})
                        MERGE (det)-[r:VIA_CLIENT]->(ca)
                        ON CREATE SET r.confidence = $confidence
                        """,
                        detection_id=detection_entities.detection_id,
                        client_app_name=entity.text,
                        confidence=entity.confidence,
                    )
                    stats["relationships"] += 1

        record_detection_processed("graph_populator", "success")
        return stats

    @monitor_performance("graph_populator", "populate_batch")
    def populate_batch(self, detection_entities_list: list[DetectionEntities]) -> GraphStats:
        """
        Populate graph with multiple detections (batch processing).

        Args:
            detection_entities_list: List of DetectionEntities

        Returns:
            GraphStats with creation counts
        """
        if not self.driver:
            logger.error("No Neo4j connection available")
            return GraphStats(errors=len(detection_entities_list))

        stats = GraphStats()

        for detection_entities in detection_entities_list:
            try:
                result = self.populate_detection(detection_entities)
                if "error" in result:
                    stats.errors += 1
                else:
                    stats.detections_created += 1
                    # Note: These are cumulative, not exact due to MERGE deduplication
                    stats.relationships_created += result.get("relationships", 0)
            except Exception as e:
                logger.error(f"Error populating detection {detection_entities.detection_id}: {e}")
                stats.errors += 1
                record_detection_processed("graph_populator", "error")

        stats.batches_processed = 1
        logger.info(
            f"Batch complete: {stats.detections_created} detections, "
            f"{stats.relationships_created} relationships, {stats.errors} errors"
        )

        return stats

    def populate_from_jsonl(self, jsonl_path: str, limit: int | None = None) -> GraphStats:
        """
        Populate graph from JSONL file with paired records (original_event + detection).
        More accurate than CSV approach (100% vs 50% app coverage).

        Args:
            jsonl_path: Path to JSONL file with paired records
            limit: Optional limit on number of records to process

        Returns:
            GraphStats with creation counts

        Example:
            >>> with GraphPopulator() as populator:
            ...     stats = populator.populate_from_jsonl(
            ...         "data/input/ai/synthetic_paired_detections.jsonl",
            ...         limit=1000
            ...     )
            ...     print(f"Created {stats.detections_created} detections")
        """
        import json

        if not self.driver:
            logger.error("No Neo4j connection available")
            return GraphStats(errors=1)

        logger.info(f"Populating from JSONL: {jsonl_path}")

        # Read JSONL file
        records = []
        with open(jsonl_path) as f:
            for i, line in enumerate(f):
                if limit and i >= limit:
                    break
                try:
                    record = json.loads(line.strip())
                    records.append(record)
                except json.JSONDecodeError as e:
                    logger.warning(f"Skipping invalid JSON line {i + 1}: {e}")

        logger.info(f"Loaded {len(records)} paired records")

        # Extract entities from original_event (direct extraction, 100% accurate)
        detection_entities_list = []

        for record in records:
            try:
                original_event = record.get("original_event", {})
                detection_dict = record.get("detection", {})

                # Create DetectionEntities from original_event
                detection_entities = self._extract_detection_entities_from_event(original_event, detection_dict)
                detection_entities_list.append(detection_entities)

            except Exception as e:
                logger.warning(f"Failed to extract entities from record: {e}")

        logger.info(f"Extracted entities from {len(detection_entities_list)} records")

        # Populate graph
        return self.populate_batch(detection_entities_list)

    def _extract_detection_entities_from_event(
        self, original_event: dict[str, Any], detection_dict: dict[str, Any]
    ) -> DetectionEntities:
        """
        Extract DetectionEntities from original_event (Azure AD structure).
        Direct extraction for 100% accuracy (bypasses ner_service pattern matching).

        Args:
            original_event: Azure AD event dict
            detection_dict: Detection dict with metadata

        Returns:
            DetectionEntities object
        """
        entities = []

        # APPLICATION
        app_name = original_event.get("properties", {}).get("appDisplayName")
        if app_name:
            entities.append(
                Entity(
                    type="APPLICATION",
                    text=app_name,
                    confidence=1.0,
                    source_feature="original_event.properties.appDisplayName",
                    category="app",
                )
            )

        # DEVICE (without browser - browser now separate)
        device_name = original_event.get("properties", {}).get("deviceDetail", {}).get("displayName")
        if device_name:
            entities.append(
                Entity(
                    type="DEVICE",
                    text=device_name,
                    confidence=1.0,
                    source_feature="original_event.properties.deviceDetail.displayName",
                    category="device",
                )
            )

        # BROWSER (now separate node)
        browser = original_event.get("properties", {}).get("deviceDetail", {}).get("browser")
        if browser:
            entities.append(
                Entity(
                    type="BROWSER",
                    text=browser,
                    confidence=1.0,
                    source_feature="original_event.properties.deviceDetail.browser",
                    category="browser",
                )
            )

        # OPERATING SYSTEM
        os = original_event.get("properties", {}).get("deviceDetail", {}).get("operatingSystem")
        if os:
            entities.append(
                Entity(
                    type="OPERATING_SYSTEM",
                    text=os,
                    confidence=1.0,
                    source_feature="original_event.properties.deviceDetail.operatingSystem",
                    category="os",
                )
            )

        # IP ADDRESS
        ip_address = original_event.get("properties", {}).get("ipAddress")
        if ip_address:
            entities.append(
                Entity(
                    type="IP_ADDRESS",
                    text=ip_address,
                    confidence=1.0,
                    source_feature="original_event.properties.ipAddress",
                    category="ip",
                )
            )

        # CLIENT APP
        client_app = original_event.get("properties", {}).get("clientAppUsed")
        if client_app:
            entities.append(
                Entity(
                    type="CLIENT_APP",
                    text=client_app,
                    confidence=1.0,
                    source_feature="original_event.properties.clientAppUsed",
                    category="client_app",
                )
            )

        # LOCATION
        city = original_event.get("location", {}).get("city")
        country = original_event.get("location", {}).get("countryOrRegion")
        if city and country:
            location_name = f"{city}, {country}"
            entities.append(
                Entity(
                    type="LOCATION",
                    text=location_name,
                    confidence=1.0,
                    source_feature="original_event.location",
                    category="location",
                )
            )

        # Create DetectionEntities
        # Generate unique detection_id if not present (use user_id + timestamp)
        user_id = detection_dict.get("user_id", "")
        timestamp = detection_dict.get("timestamp", "")
        detection_id = detection_dict.get("detection_id", "")
        if not detection_id and user_id and timestamp:
            # Create unique ID from user_id and timestamp
            detection_id = f"{user_id}_{timestamp.replace(':', '_').replace('.', '_')}"

        return DetectionEntities(
            detection_id=detection_id,
            user_id=user_id,
            timestamp=timestamp,
            entities=entities,
        )

    def get_graph_stats(self) -> dict[str, Any]:
        """
        Get current graph statistics.

        Returns:
            Dict with node and relationship counts
        """
        if not self.driver:
            return {"error": "No Neo4j connection"}

        with self.driver.session(database=self.database) as session:
            # Count nodes
            user_result = session.run("MATCH (u:User) RETURN count(u) as count").single()
            app_result = session.run("MATCH (a:Application) RETURN count(a) as count").single()
            device_result = session.run("MATCH (d:Device) RETURN count(d) as count").single()
            browser_result = session.run("MATCH (b:Browser) RETURN count(b) as count").single()
            os_result = session.run("MATCH (os:OperatingSystem) RETURN count(os) as count").single()
            ip_result = session.run("MATCH (ip:IPAddress) RETURN count(ip) as count").single()
            client_app_result = session.run("MATCH (ca:ClientApp) RETURN count(ca) as count").single()
            location_result = session.run("MATCH (l:Location) RETURN count(l) as count").single()
            detection_result = session.run("MATCH (det:Detection) RETURN count(det) as count").single()

            user_count = user_result["count"] if user_result else 0
            app_count = app_result["count"] if app_result else 0
            device_count = device_result["count"] if device_result else 0
            browser_count = browser_result["count"] if browser_result else 0
            os_count = os_result["count"] if os_result else 0
            ip_count = ip_result["count"] if ip_result else 0
            client_app_count = client_app_result["count"] if client_app_result else 0
            location_count = location_result["count"] if location_result else 0
            detection_count = detection_result["count"] if detection_result else 0

            # Count relationships
            generated_result = session.run("MATCH ()-[r:GENERATED]->() RETURN count(r) as count").single()
            accessed_result = session.run("MATCH ()-[r:ACCESSED]->() RETURN count(r) as count").single()
            from_device_result = session.run("MATCH ()-[r:FROM_DEVICE]->() RETURN count(r) as count").single()
            used_browser_result = session.run("MATCH ()-[r:USED_BROWSER]->() RETURN count(r) as count").single()
            on_os_result = session.run("MATCH ()-[r:ON_OS]->() RETURN count(r) as count").single()
            from_ip_result = session.run("MATCH ()-[r:FROM_IP]->() RETURN count(r) as count").single()
            via_client_result = session.run("MATCH ()-[r:VIA_CLIENT]->() RETURN count(r) as count").single()
            from_location_result = session.run("MATCH ()-[r:FROM_LOCATION]->() RETURN count(r) as count").single()

            generated_count = generated_result["count"] if generated_result else 0
            accessed_count = accessed_result["count"] if accessed_result else 0
            from_device_count = from_device_result["count"] if from_device_result else 0
            used_browser_count = used_browser_result["count"] if used_browser_result else 0
            on_os_count = on_os_result["count"] if on_os_result else 0
            from_ip_count = from_ip_result["count"] if from_ip_result else 0
            via_client_count = via_client_result["count"] if via_client_result else 0
            from_location_count = from_location_result["count"] if from_location_result else 0

            total_nodes = (
                user_count
                + app_count
                + device_count
                + browser_count
                + os_count
                + ip_count
                + client_app_count
                + location_count
                + detection_count
            )
            total_relationships = (
                generated_count
                + accessed_count
                + from_device_count
                + used_browser_count
                + on_os_count
                + from_ip_count
                + via_client_count
                + from_location_count
            )

            return {
                "nodes": {
                    "users": user_count,
                    "applications": app_count,
                    "devices": device_count,
                    "browsers": browser_count,
                    "operating_systems": os_count,
                    "ip_addresses": ip_count,
                    "client_apps": client_app_count,
                    "locations": location_count,
                    "detections": detection_count,
                    "total": total_nodes,
                },
                "relationships": {
                    "generated": generated_count,
                    "accessed": accessed_count,
                    "from_device": from_device_count,
                    "used_browser": used_browser_count,
                    "on_os": on_os_count,
                    "from_ip": from_ip_count,
                    "via_client": via_client_count,
                    "from_location": from_location_count,
                    "total": total_relationships,
                },
            }


# ============================================================================
# TEST SCRIPT
# ============================================================================

if __name__ == "__main__":
    import argparse
    import time

    parser = argparse.ArgumentParser(description="Populate Neo4j knowledge graph with detection entities")
    parser.add_argument("--clear", action="store_true", help="Clear existing graph before populating (destructive)")
    parser.add_argument("--limit", type=int, default=None, help="Limit number of detections to process (default: all)")
    parser.add_argument("--jsonl", type=str, help="Path to paired JSONL file (alternative to CSV)")
    args = parser.parse_args()

    print("=" * 80)
    print("NEO4J GRAPH POPULATION")
    print("=" * 80)

    # Connect to Neo4j
    print("\n1. Connecting to Neo4j...")
    with GraphPopulator() as populator:
        if not populator.driver:
            print("Neo4j not available")
            print("   Check services: ./services/check_services.sh")
            print("   Set credentials via: NEO4J_USER and NEO4J_PASSWORD environment variables")
            sys.exit(1)

        print("Connected to Neo4j")

        # Clear graph (optional)
        if args.clear:
            print("\n2. Clearing existing graph...")
            populator.clear_graph()
            print("Graph cleared")
        else:
            print("\n2. Skipping graph clear (use --clear to clear existing data)")

        # Create indexes
        print("\n3. Creating indexes...")
        populator.create_indexes()
        print("Indexes created")

        # Populate from JSONL or CSV
        if args.jsonl:
            print(f"\n4. Populating from JSONL: {args.jsonl}...")
            jsonl_path = Path(args.jsonl)

            if not jsonl_path.exists():
                print(f"JSONL file not found: {jsonl_path}")
                sys.exit(1)

            start_time = time.time()
            stats = populator.populate_from_jsonl(str(jsonl_path), limit=args.limit)
            duration = time.time() - start_time

            records_processed = stats.detections_created + stats.errors

            print(f"Populated graph in {duration:.2f}s")
            print(f"   Detections: {stats.detections_created}")
            print(f"   Users: {stats.users_created}")
            print(f"   Applications: {stats.apps_created}")
            print(f"   Devices: {stats.devices_created}")
            print(f"   Locations: {stats.locations_created}")
            print(f"   Relationships: {stats.relationships_created}")
            print(f"   Errors: {stats.errors}")
            if records_processed > 0:
                print(f"   Performance: {duration / records_processed * 1000:.1f}ms per detection")

        else:
            # Original CSV flow
            print("\n4. Initializing services for CSV processing...")
            bridge = FeatureBridge()
            ner = NERService()

            if not ner.nlp:
                print("spaCy not available - using pattern matching only")

            # Load detections
            csv_path = Path("data/input/ai/user_aware_anomalies.csv")

            if not csv_path.exists():
                print(f"\nCSV file not found: {csv_path}")
                sys.exit(1)

            print(f"\n5. Loading detections from {csv_path}...")
            detections = bridge.load_detections(str(csv_path), limit=args.limit)
            print(f"Loaded {len(detections)} detections")

            # Extract entities
            print("\n6. Extracting entities...")
            start_time = time.time()
            detection_entities_list = ner.extract_batch(detections)
            duration = time.time() - start_time
            print(f"Extracted entities from {len(detection_entities_list)} detections in {duration:.2f}s")

            # Populate graph
            print(f"\n7. Populating graph with {len(detection_entities_list)} detections...")
            start_time = time.time()
            stats = populator.populate_batch(detection_entities_list)
            duration = time.time() - start_time

            print(f"Populated graph in {duration:.2f}s")
            print(f"   Detections: {stats.detections_created}")
            print(f"   Relationships: {stats.relationships_created}")
            print(f"   Errors: {stats.errors}")
            print(f"   Performance: {duration / len(detection_entities_list) * 1000:.1f}ms per detection")

        # Get stats
        print("\n5. Graph statistics:")
        graph_stats = populator.get_graph_stats()

        print("   Nodes:")
        print(f"      Users: {graph_stats['nodes']['users']}")
        print(f"      Applications: {graph_stats['nodes']['applications']}")
        print(f"      Devices: {graph_stats['nodes']['devices']}")
        print(f"      Browsers: {graph_stats['nodes']['browsers']}")
        print(f"      Operating Systems: {graph_stats['nodes']['operating_systems']}")
        print(f"      IP Addresses: {graph_stats['nodes']['ip_addresses']}")
        print(f"      Client Apps: {graph_stats['nodes']['client_apps']}")
        print(f"      Locations: {graph_stats['nodes']['locations']}")
        print(f"      Detections: {graph_stats['nodes']['detections']}")
        print(f"      Total: {graph_stats['nodes']['total']}")

        print("   Relationships:")
        print(f"      User -> Detection (GENERATED): {graph_stats['relationships']['generated']}")
        print(f"      Detection -> App (ACCESSED): {graph_stats['relationships']['accessed']}")
        print(f"      Detection -> Device (FROM_DEVICE): {graph_stats['relationships']['from_device']}")
        print(f"      Detection -> Browser (USED_BROWSER): {graph_stats['relationships']['used_browser']}")
        print(f"      Detection -> OS (ON_OS): {graph_stats['relationships']['on_os']}")
        print(f"      Detection -> IP (FROM_IP): {graph_stats['relationships']['from_ip']}")
        print(f"      Detection -> Client (VIA_CLIENT): {graph_stats['relationships']['via_client']}")
        print(f"      Detection -> Location (FROM_LOCATION): {graph_stats['relationships']['from_location']}")
        print(f"      Total: {graph_stats['relationships']['total']}")

    print("\n" + "=" * 80)
    print("Neo4j graph population complete")
    print("=" * 80)
    print("\nNext: Query the graph in Neo4j Browser at http://localhost:7474")
    print("Example queries:")
    print("  - MATCH (u:User)-[:GENERATED]->(d:Detection) RETURN u, d LIMIT 25")
    print("  - MATCH (d:Detection)-[:ACCESSED]->(a:Application) RETURN d, a LIMIT 25")
    print("  - MATCH (d:Detection)-[:USED_BROWSER]->(b:Browser) RETURN d, b LIMIT 25")
    print("  - MATCH (d:Detection)-[:VIA_CLIENT]->(ca:ClientApp) WHERE ca.name = 'POP3' RETURN d, ca")
    print("  - MATCH (u:User)-[:GENERATED]->(d:Detection)-[:FROM_LOCATION]->(l:Location) RETURN u, d, l")
