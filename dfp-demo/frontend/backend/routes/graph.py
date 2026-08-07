import logging
import os

from auth_utils import get_current_user
from fastapi import APIRouter, Depends, HTTPException, Query

logger = logging.getLogger(__name__)

router = APIRouter()

# ---------------------------------------------------------------------------
# Neo4j connection helpers
# ---------------------------------------------------------------------------


def _get_driver():
    """Return a connected Neo4j driver, or raise 503 if unavailable."""
    try:
        from neo4j import GraphDatabase
        from neo4j.exceptions import AuthError, ServiceUnavailable
    except ImportError as e:
        raise HTTPException(status_code=503, detail="Neo4j driver not installed") from e

    uri = os.getenv("NEO4J_URI", "bolt://localhost:7687")
    user = os.getenv("NEO4J_USER", "neo4j")
    password = os.getenv("NEO4J_PASSWORD", "")

    try:
        driver = GraphDatabase.driver(uri, auth=(user, password))
        driver.verify_connectivity()
        return driver
    except AuthError as e:
        logger.error(f"Neo4j authentication failed: {e}")
        raise HTTPException(
            status_code=503, detail="Neo4j authentication failed — check NEO4J_USER/NEO4J_PASSWORD"
        ) from e
    except ServiceUnavailable as e:
        logger.error(f"Neo4j service unavailable: {e}")
        raise HTTPException(
            status_code=503, detail="Neo4j not reachable — check NEO4J_URI and that Neo4j is running"
        ) from e
    except Exception as e:
        logger.error(f"Neo4j connection error: {e}")
        raise HTTPException(status_code=503, detail="Neo4j connection failed") from e


def _run(driver, query: str, **params) -> list[dict]:
    """Execute a Cypher query and return records as plain dicts."""
    with driver.session(database=os.getenv("NEO4J_DATABASE", "neo4j")) as session:
        result = session.run(query, **params)
        return [dict(record) for record in result]


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get("/stats")
def get_graph_stats(_user: dict = Depends(get_current_user)):
    """High-level node/relationship counts for the graph overview panel."""
    driver = _get_driver()
    try:
        rows = _run(
            driver,
            """
            MATCH (n)
            WITH labels(n)[0] AS label, count(n) AS cnt
            RETURN label, cnt
            ORDER BY cnt DESC
            """,
        )
        rel_rows = _run(
            driver,
            """
            MATCH ()-[r]->()
            RETURN type(r) AS rel_type, count(r) AS cnt
            ORDER BY cnt DESC
            """,
        )
        node_counts = {r["label"]: r["cnt"] for r in rows if r["label"]}
        rel_counts = {r["rel_type"]: r["cnt"] for r in rel_rows if r["rel_type"]}
        return {
            "node_counts": node_counts,
            "relationship_counts": rel_counts,
            "total_nodes": sum(node_counts.values()),
            "total_relationships": sum(rel_counts.values()),
        }
    finally:
        driver.close()


@router.get("/data")
def get_graph_data(
    limit: int = Query(default=500, ge=1, le=2000),
    node_types: str | None = Query(default=None, description="Comma-separated node labels to include"),
    _user: dict = Depends(get_current_user),
):
    """
    Return full graph data suitable for react-force-graph.
    Returns { nodes: [...], links: [...] }.
    """
    driver = _get_driver()
    try:
        # Build label filter
        allowed_labels = set(node_types.split(",")) if node_types else None

        # Fetch nodes
        node_query = """
            MATCH (n)
            RETURN id(n) AS neo_id,
                   labels(n)[0] AS label,
                   properties(n) AS props
            LIMIT $limit
        """
        raw_nodes = _run(driver, node_query, limit=limit)

        nodes = []
        node_id_set = set()
        for row in raw_nodes:
            label = row.get("label") or "Unknown"
            if allowed_labels and label not in allowed_labels:
                continue
            props = dict(row.get("props") or {})
            node_id = str(row["neo_id"])
            node_id_set.add(node_id)
            # Determine display name
            name = (
                props.get("user_id")
                or props.get("name")
                or props.get("address")
                or props.get("city")
                or props.get("detection_id")
                or f"{label}:{node_id}"
            )
            nodes.append(
                {
                    # **props must come first so our explicit keys always win.
                    # Some Neo4j nodes have an "id" property (e.g. UUID) that
                    # would otherwise override the integer neo_id we want to use.
                    **{k: str(v) if not isinstance(v, (int, float, bool)) else v for k, v in props.items()},
                    "id": node_id,
                    "label": label,
                    "name": name,
                }
            )

        # Fetch relationships (only between fetched nodes)
        rel_query = """
            MATCH (a)-[r]->(b)
            WHERE id(a) IN $ids AND id(b) IN $ids
            RETURN id(a) AS source, id(b) AS target, type(r) AS rel_type,
                   properties(r) AS props
        """
        id_list = [int(nid) for nid in node_id_set]
        raw_rels = _run(driver, rel_query, ids=id_list)

        links = [
            {
                "source": str(row["source"]),
                "target": str(row["target"]),
                "type": row["rel_type"],
            }
            for row in raw_rels
        ]

        return {"nodes": nodes, "links": links}
    finally:
        driver.close()


@router.get("/node/{node_id}")
def get_node_detail(node_id: int, _user: dict = Depends(get_current_user)):
    """Return full detail for a single node by Neo4j internal ID."""
    driver = _get_driver()
    try:
        rows = _run(
            driver,
            """
            MATCH (n) WHERE id(n) = $nid
            RETURN id(n) AS neo_id, labels(n) AS labels, properties(n) AS props
            """,
            nid=node_id,
        )
        if not rows:
            raise HTTPException(status_code=404, detail="Node not found")
        row = rows[0]
        props = dict(row.get("props") or {})
        return {
            "id": str(row["neo_id"]),
            "labels": list(row["labels"]),
            "properties": {k: str(v) if not isinstance(v, (int, float, bool)) else v for k, v in props.items()},
        }
    finally:
        driver.close()


@router.get("/node/{node_id}/neighbours")
def get_node_neighbours(
    node_id: int, depth: int = Query(default=1, ge=1, le=3), _user: dict = Depends(get_current_user)
):
    """Return the ego-graph (node + its neighbours up to `depth` hops)."""
    driver = _get_driver()
    try:
        # Neo4j Cypher does NOT allow parameterized variable-length path bounds
        # (e.g. [*1..$depth] raises a syntax error).  depth is validated as
        # int 1-3 by FastAPI's Query constraint so embedding it is safe.
        node_rows = _run(
            driver,
            f"""
            MATCH (center) WHERE id(center) = $nid
            OPTIONAL MATCH (center)-[*1..{depth}]-(neighbor)
            RETURN center, COLLECT(DISTINCT neighbor) AS neighbors
            """,
            nid=node_id,
        )

        if not node_rows:
            return {"nodes": [], "links": []}

        row = node_rows[0]
        center = row["center"]
        neighbor_nodes = [n for n in (row.get("neighbors") or []) if n is not None]
        all_neo_ids = [center.id] + [n.id for n in neighbor_nodes]

        # Fetch all relationships between the gathered nodes in one query
        rel_rows = _run(
            driver,
            """
            MATCH (a)-[r]->(b)
            WHERE id(a) IN $ids AND id(b) IN $ids
            RETURN id(a) AS source, id(b) AS target, type(r) AS rel_type
            """,
            ids=all_neo_ids,
        )

        def _node_to_dict(n) -> dict:
            props = dict(dict(n).items()) if hasattr(n, "items") else {}
            lbl = list(n.labels)[0] if hasattr(n, "labels") and n.labels else "Unknown"
            name = (
                props.get("user_id")
                or props.get("name")
                or props.get("address")
                or props.get("city")
                or props.get("detection_id")
                or f"{lbl}:{n.id}"
            )
            return {
                **{k: str(v) if not isinstance(v, (int, float, bool)) else v for k, v in props.items()},
                "id": str(n.id),  # always last so it wins over any "id" prop
                "label": lbl,
                "name": name,
            }

        nodes = [_node_to_dict(center)] + [_node_to_dict(n) for n in neighbor_nodes]
        links = [
            {
                "source": str(r["source"]),
                "target": str(r["target"]),
                "type": r["rel_type"],
            }
            for r in rel_rows
        ]

        return {"nodes": nodes, "links": links}
    finally:
        driver.close()


@router.get("/user/{user_id}/subgraph")
def get_user_subgraph(user_id: str, _user: dict = Depends(get_current_user)):
    """Return all detections and their connected entities for a given user."""
    driver = _get_driver()
    try:
        rows = _run(
            driver,
            """
            MATCH (u:User {user_id: $uid})-[:GENERATED]->(det:Detection)
            OPTIONAL MATCH (det)-[r]->(entity)
            WITH u, det, COLLECT(DISTINCT entity) AS entities,
                 COLLECT(DISTINCT {source: id(det),
                                    target: id(entity),
                                    type: type(r)}) AS rels
            RETURN u, det, entities, rels
            """,
            uid=user_id,
        )

        if not rows:
            raise HTTPException(status_code=404, detail=f"User '{user_id}' not found in graph")

        node_map: dict[str, dict] = {}
        all_links: list[dict] = []

        def _add_node(n, label_hint: str = "Unknown"):
            nid = str(n.id)
            if nid in node_map:
                return
            props = dict(n) if hasattr(n, "items") else {}
            lbl = list(n.labels)[0] if hasattr(n, "labels") and n.labels else label_hint
            name = (
                props.get("user_id")
                or props.get("name")
                or props.get("address")
                or props.get("city")
                or props.get("detection_id")
                or f"{lbl}:{nid}"
            )
            node_map[nid] = {
                "id": nid,
                "label": lbl,
                "name": name,
                **{
                    k: str(v) if not isinstance(v, (int, float, bool)) else v
                    for k, v in props.items()
                    if k not in ("id",)
                },
            }

        for row in rows:
            _add_node(row["u"], "User")
            _add_node(row["det"], "Detection")
            # Edge User → Detection
            all_links.append(
                {
                    "source": str(row["u"].id),
                    "target": str(row["det"].id),
                    "type": "GENERATED",
                }
            )
            for entity in row["entities"] or []:
                if entity is not None:
                    _add_node(entity)
            for rel in row["rels"] or []:
                if rel and rel.get("source") and rel.get("target"):
                    all_links.append(
                        {
                            "source": str(rel["source"]),
                            "target": str(rel["target"]),
                            "type": rel["type"],
                        }
                    )

        # Deduplicate links
        seen_links: set[tuple] = set()
        unique_links = []
        for lnk in all_links:
            key = (lnk["source"], lnk["target"], lnk["type"])
            if key not in seen_links:
                seen_links.add(key)
                unique_links.append(lnk)

        return {"nodes": list(node_map.values()), "links": unique_links}
    finally:
        driver.close()


@router.get("/anomaly-clusters")
def get_anomaly_clusters(
    min_detections: int = Query(default=3, ge=1, le=50),
    limit: int = Query(default=10, ge=1, le=100),
    _user: dict = Depends(get_current_user),
):
    """
    Return users with the most detections — useful for spotting clusters.
    Each item has the user node plus a count of connected Detection nodes.
    """
    driver = _get_driver()
    try:
        rows = _run(
            driver,
            """
            MATCH (u:User)-[:GENERATED]->(det:Detection)
            WITH u, COUNT(det) AS detection_count
            WHERE detection_count >= $min_det
            RETURN id(u) AS user_neo_id,
                   u.user_id AS user_id,
                   detection_count
            ORDER BY detection_count DESC
            LIMIT $limit
            """,
            min_det=min_detections,
            limit=limit,
        )
        return [
            {
                "user_neo_id": str(r["user_neo_id"]),
                "user_id": r["user_id"],
                "detection_count": r["detection_count"],
            }
            for r in rows
        ]
    finally:
        driver.close()
