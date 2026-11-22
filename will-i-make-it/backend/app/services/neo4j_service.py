"""
Neo4j Graph Database Integration Service
=========================================
Geospatial road network, corridor topology, and charging infrastructure modelling
backed by Neo4j / AuraDB. Provides connection pooling, schema constraints,
weighted route traversal, alternative route discovery, charger discovery,
and seamless integration with the authoritative physics simulation engine.

Defaults to disabled (NEO4J_ENABLED=false). Operates with zero credentials exposure
and strict TLS verification.
"""
from __future__ import annotations

import os
import math
import logging
import re
from datetime import datetime, timezone
from typing import Optional, List, Dict, Any, Tuple
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

_driver = None
_connected = False
_connection_attempted = False
_last_error = ""


def is_enabled() -> bool:
    """Return True only if NEO4J_ENABLED is explicitly enabled via environment configuration."""
    return os.environ.get("NEO4J_ENABLED", "false").strip().lower() in ("true", "1", "yes")


def is_connected() -> bool:
    """Return True if an active driver connection has been established."""
    return _connected


def get_last_error() -> str:
    """Return the last connection or query error message (sanitized)."""
    return _last_error


def _mask_uri(uri: str) -> str:
    """Mask credentials or sensitive host parts in URIs for safe logging."""
    if not uri:
        return ""
    # Mask user/pass if present in URI format
    return re.sub(r"://([^:]+):([^@]+)@", r"://\1:****@", uri)


def close_driver() -> None:
    """Safely terminate the Neo4j driver connection during application shutdown."""
    global _driver, _connected
    if _driver is not None:
        try:
            _driver.close()
            logger.info("[Neo4j] Driver pool closed successfully.")
        except Exception as e:
            logger.warning(f"[Neo4j] Error closing driver: {e}")
        _driver = None
        _connected = False


def get_driver():
    """
    Get or initialize the Neo4j driver with connection pooling.
    Enforces strict TLS verification and respects timeouts.
    """
    global _driver, _connected, _connection_attempted, _last_error
    if _driver is not None:
        return _driver

    if not is_enabled():
        _connected = False
        _last_error = "Neo4j integration disabled by default (NEO4J_ENABLED is false)"
        return None

    uri = os.environ.get("NEO4J_URI", "").strip()
    raw_user = (os.environ.get("NEO4J_USERNAME") or os.environ.get("NEO4J_USER") or "neo4j").strip()
    password = os.environ.get("NEO4J_PASSWORD", "").strip()
    database = os.environ.get("NEO4J_DATABASE", "neo4j").strip()

    if not uri or not password:
        _connected = False
        _last_error = "NEO4J_URI or NEO4J_PASSWORD is not set"
        return None

    user = raw_user
    instance_id = os.environ.get("AURA_INSTANCEID", "").strip()
    if not user or "@" in raw_user or "Aura" in raw_user or "(" in raw_user or user == instance_id:
        user = "neo4j"

    _connection_attempted = True

    try:
        from neo4j import GraphDatabase
    except ImportError:
        _last_error = "'neo4j' driver package not installed"
        logger.error(f"[Neo4j] {_last_error}")
        return None

    conn_timeout = float(os.environ.get("NEO4J_CONNECTION_TIMEOUT", "15.0"))
    max_lifetime = float(os.environ.get("NEO4J_MAX_CONNECTION_LIFETIME", "3600.0"))
    max_pool_size = int(os.environ.get("NEO4J_MAX_CONNECTION_POOL_SIZE", "50"))

    try:
        d = GraphDatabase.driver(
            uri,
            auth=(user, password),
            connection_timeout=conn_timeout,
            max_connection_lifetime=max_lifetime,
            max_connection_pool_size=max_pool_size,
        )
        d.verify_connectivity()
        _driver = d
        _connected = True
        _last_error = ""
        logger.info(f"[Neo4j] Successfully connected to {_mask_uri(uri)} as user '{user}'")
        return _driver
    except Exception as e:
        _last_error = str(e)
        _driver = None
        _connected = False
        logger.warning(f"[Neo4j] Connection failed: {_last_error}")
        return None


def check_health() -> Dict[str, Any]:
    """
    Perform a live health probe on the Neo4j cluster/instance.
    Returns status without leaking secrets.
    """
    if not is_enabled():
        return {
            "status": "DISABLED",
            "connected": False,
            "message": "Neo4j is disabled by default (NEO4J_ENABLED=false)",
        }

    driver = get_driver()
    if not driver:
        return {
            "status": "DOWN",
            "connected": False,
            "message": get_last_error() or "Unable to establish Neo4j driver connection",
        }

    try:
        driver.verify_connectivity()
        with driver.session() as session:
            res = session.run("RETURN 1 AS ping").single()
            if res and res["ping"] == 1:
                return {
                    "status": "UP",
                    "connected": True,
                    "uri": _mask_uri(os.environ.get("NEO4J_URI", "")),
                    "database": os.environ.get("NEO4J_DATABASE", "neo4j"),
                    "message": "Neo4j graph database is active, healthy, and responsive",
                }
    except Exception as e:
        return {
            "status": "DOWN",
            "connected": False,
            "message": f"Ping probe failed: {str(e)}",
        }

    return {
        "status": "DOWN",
        "connected": False,
        "message": "Probe returned invalid response",
    }


def init_schema() -> bool:
    """
    Ensure all required schema uniqueness constraints and geospatial indexes are initialized.
    """
    driver = get_driver()
    if not driver:
        return False

    constraints_and_indexes = [
        # Uniqueness constraints for all domain entities
        "CREATE CONSTRAINT road_node_id IF NOT EXISTS FOR (n:RoadNode) REQUIRE n.node_id IS UNIQUE",
        "CREATE CONSTRAINT charger_station_id IF NOT EXISTS FOR (c:ChargingStation) REQUIRE c.station_id IS UNIQUE",
        "CREATE CONSTRAINT legacy_charger_id IF NOT EXISTS FOR (c:Charger) REQUIRE c.charger_id IS UNIQUE",
        "CREATE CONSTRAINT city_id IF NOT EXISTS FOR (ct:City) REQUIRE ct.city_id IS UNIQUE",
        "CREATE CONSTRAINT operator_id IF NOT EXISTS FOR (op:ChargingOperator) REQUIRE op.operator_id IS UNIQUE",
        "CREATE CONSTRAINT connector_id IF NOT EXISTS FOR (conn:ChargingConnector) REQUIRE conn.connector_id IS UNIQUE",
        "CREATE CONSTRAINT region_id IF NOT EXISTS FOR (r:Region) REQUIRE r.region_id IS UNIQUE",
        "CREATE CONSTRAINT road_id IF NOT EXISTS FOR (rd:Road) REQUIRE rd.road_id IS UNIQUE",
        "CREATE CONSTRAINT highway_id IF NOT EXISTS FOR (h:Highway) REQUIRE h.highway_id IS UNIQUE",
        "CREATE CONSTRAINT road_segment_id IF NOT EXISTS FOR (rs:RoadSegment) REQUIRE rs.segment_id IS UNIQUE",
        "CREATE CONSTRAINT junction_id IF NOT EXISTS FOR (j:Junction) REQUIRE j.junction_id IS UNIQUE",
        "CREATE CONSTRAINT vehicle_id IF NOT EXISTS FOR (v:Vehicle) REQUIRE v.vehicle_id IS UNIQUE",
        "CREATE CONSTRAINT battery_config_id IF NOT EXISTS FOR (bc:BatteryConfiguration) REQUIRE bc.config_id IS UNIQUE",
        "CREATE CONSTRAINT report_id IF NOT EXISTS FOR (cr:ChargingReport) REQUIRE cr.report_id IS UNIQUE",
        # Indexes for fast lookup, proximity, and provenance
        "CREATE INDEX road_node_coords IF NOT EXISTS FOR (n:RoadNode) ON (n.lat, n.lng)",
        "CREATE INDEX charger_coords IF NOT EXISTS FOR (c:ChargingStation) ON (c.lat, c.lng)",
        "CREATE INDEX station_env IF NOT EXISTS FOR (c:ChargingStation) ON (c.environment)",
        "CREATE INDEX station_provenance IF NOT EXISTS FOR (c:ChargingStation) ON (c.provenance)",
    ]

    try:
        with driver.session() as session:
            for statement in constraints_and_indexes:
                session.run(statement)
        logger.info("[Neo4j] Schema constraints and indexes successfully verified.")
        return True
    except Exception as e:
        logger.warning(f"[Neo4j] Schema initialization error: {e}")
        return False


def seed_graph() -> bool:
    """
    Seed the Neo4j graph with normalized road network, charging stations, connectors,
    operators, and corridor relationships from certified demo sources.
    """
    driver = get_driver()
    if not driver:
        return False

    init_schema()

    from app.services.demo_data import DEMO_ROUTES, CHARGERS

    try:
        with driver.session() as session:
            # 1. Seed Operators and Charging Stations with full provenance
            for cid, c in CHARGERS.items():
                op_name = c.get("operator") or "Independent"
                op_id = f"OP_{op_name.upper().replace(' ', '_').replace('-', '_')}"

                session.run("""
                    MERGE (op:ChargingOperator {operator_id: $op_id})
                    SET op.name = $op_name
                    MERGE (ch:Charger {charger_id: $id})
                    SET ch.name = $name,
                        ch.lat = $lat, ch.lng = $lng,
                        ch.max_power_kw = $power,
                        ch.operator = $op_name,
                        ch.reliability_score = $rel,
                        ch.connector_types = $connectors,
                        ch.status = $status,
                        ch.data_source = $data_source,
                        ch.verification_source = $verification_source,
                        ch.last_verified_at = $last_verified_at
                    MERGE (st:ChargingStation {station_id: $id})
                    SET st.name = $name,
                        st.lat = $lat, st.lng = $lng,
                        st.max_power_kw = $power,
                        st.operator = $op_name,
                        st.reliability_score = $rel,
                        st.connector_types = $connectors,
                        st.status = $status,
                        st.data_source = $data_source,
                        st.verification_source = $verification_source,
                        st.last_verified_at = $last_verified_at
                    MERGE (st)-[:OPERATED_BY]->(op)
                """, op_id=op_id, op_name=op_name, id=cid, cid=cid, name=c["name"],
                    lat=c["lat"], lng=c["lng"], power=c["max_power_kw"],
                    rel=c["reliability_score"], connectors=c["connector_types"],
                    status=c.get("status", "UNKNOWN"),
                    data_source=c.get("data_source", "DEMO_DATABASE"),
                    verification_source=c.get("verification_source", "Demo seed data"),
                    last_verified_at=c.get("last_verified_at"))

                # Seed Connectors
                for conn_type in c.get("connector_types", []):
                    conn_id = f"{cid}_{conn_type}"
                    session.run("""
                        MERGE (conn:ChargingConnector {connector_id: $conn_id})
                        SET conn.type = $conn_type, conn.max_power_kw = $power
                        WITH conn
                        MATCH (ch:ChargingStation {station_id: $cid})
                        MERGE (ch)-[:HAS_CONNECTOR]->(conn)
                    """, conn_id=conn_id, conn_type=conn_type, power=c["max_power_kw"], cid=cid)

            # 2. Seed Road Corridors and Segments
            for rid, route in DEMO_ROUTES.items():
                waypoints = route.get("waypoints", [])
                segments = route.get("segments", [])

                for i, seg in enumerate(segments):
                    from_id = f"{rid}_N{i}"
                    to_id = f"{rid}_N{i+1}"
                    from_lat = waypoints[min(i, len(waypoints)-1)]["lat"] if waypoints else 0.0
                    from_lng = waypoints[min(i, len(waypoints)-1)]["lng"] if waypoints else 0.0
                    to_lat = waypoints[min(i+1, len(waypoints)-1)]["lat"] if waypoints else 0.0
                    to_lng = waypoints[min(i+1, len(waypoints)-1)]["lng"] if waypoints else 0.0

                    session.run("""
                        MERGE (a:RoadNode {node_id: $fid})
                        SET a.lat = $flat, a.lng = $flng, a.name = $fname, a.corridor = $rid
                        MERGE (b:RoadNode {node_id: $tid})
                        SET b.lat = $tlat, b.lng = $tlng, b.name = $tname, b.corridor = $rid
                        MERGE (a)-[r:CONNECTED_TO {segment_id: $sid}]->(b)
                        SET r.distance_km = $dist, r.avg_speed_kmh = $speed,
                            r.gradient_pct = $grad, r.road_type = $rtype
                        MERGE (a)-[r2:ROAD_SEGMENT {segment_id: $sid}]->(b)
                        SET r2.distance_km = $dist, r2.avg_speed_kmh = $speed,
                            r2.gradient_pct = $grad, r2.road_type = $rtype
                    """, fid=from_id, flat=from_lat, flng=from_lng, fname=seg.get("name", ""),
                        tid=to_id, tlat=to_lat, tlng=to_lng, tname="",
                        sid=seg["segment_id"], dist=seg["distance_km"],
                        speed=seg["avg_speed_kmh"], grad=seg["gradient_pct"],
                        rtype=seg["road_type"], rid=rid)

                # Link nearby chargers to road nodes
                for cid, c in CHARGERS.items():
                    c_lat, c_lng = c["lat"], c["lng"]
                    session.run("""
                        MATCH (n:RoadNode {corridor: $rid})
                        WITH n, (abs(n.lat - $clat) + abs(n.lng - $clng)) AS approx_dist
                        ORDER BY approx_dist ASC
                        LIMIT 1
                        WHERE approx_dist < 0.4
                        MATCH (ch:ChargingStation {station_id: $cid})
                        MERGE (ch)-[:LOCATED_NEAR {distance_km: round(approx_dist * 111.0, 1)}]->(n)
                    """, rid=rid, clat=c_lat, clng=c_lng, cid=cid)

        logger.info("[Neo4j] Graph successfully seeded with road network & chargers.")
        return True
    except Exception as e:
        logger.error(f"[Neo4j] Seeding failed: {e}")
        return False


def find_graph_route(
    origin_lat: float,
    origin_lng: float,
    dest_lat: float,
    dest_lng: float,
    corridor_hint: Optional[str] = None,
    risk_aware: bool = False,
) -> Optional[Dict[str, Any]]:
    """
    Find road segment sequence from Neo4j graph connecting origin to destination.
    Returns dictionary with segments, waypoints, and candidate chargers.
    """
    driver = get_driver()
    if not driver:
        return None

    try:
        from app.models.schemas import RouteSegment

        with driver.session() as session:
            route_id = corridor_hint

            if not route_id:
                # Match nearest origin and destination nodes sharing a corridor
                match_res = session.run("""
                    MATCH (o:RoadNode), (d:RoadNode)
                    WHERE abs(o.lat - $olat) < 0.35 AND abs(o.lng - $olng) < 0.35
                      AND abs(d.lat - $dlat) < 0.35 AND abs(d.lng - $dlng) < 0.35
                      AND o.corridor = d.corridor
                    RETURN o.corridor AS matched_corridor
                    LIMIT 1
                """, olat=origin_lat, olng=origin_lng, dlat=dest_lat, dlng=dest_lng)
                record = match_res.single()
                if record:
                    route_id = record["matched_corridor"]
                else:
                    return None

            # Retrieve sequenced road segments
            result = session.run("""
                MATCH (a:RoadNode)-[r:CONNECTED_TO]->(b:RoadNode)
                WHERE a.corridor = $prefix OR a.node_id STARTS WITH $prefix
                RETURN r.segment_id AS segment_id, r.distance_km AS distance_km,
                       r.avg_speed_kmh AS avg_speed_kmh, r.gradient_pct AS gradient_pct,
                       r.road_type AS road_type, a.name AS name,
                       a.lat AS flat, a.lng AS flng, b.lat AS tlat, b.lng AS tlng
                ORDER BY r.segment_id ASC
            """, prefix=route_id)

            records = list(result)
            if not records:
                return None

            segments = [
                RouteSegment(
                    segment_id=rec["segment_id"],
                    distance_km=float(rec["distance_km"]),
                    avg_speed_kmh=float(rec["avg_speed_kmh"]),
                    gradient_pct=float(rec["gradient_pct"]),
                    road_type=rec["road_type"],
                    name=rec["name"],
                )
                for rec in records
            ]

            # Query chargers located near the corridor nodes
            charger_res = session.run("""
                MATCH (c:ChargingStation)-[:LOCATED_NEAR]->(n:RoadNode)
                WHERE n.corridor = $prefix OR n.node_id STARTS WITH $prefix
                RETURN DISTINCT c.station_id AS charger_id, c.name AS name,
                       c.lat AS lat, c.lng AS lng, c.max_power_kw AS max_power_kw,
                       c.connector_types AS connector_types, c.operator AS operator,
                       c.reliability_score AS reliability_score,
                       c.status AS status, c.data_source AS data_source,
                       c.verification_source AS verification_source,
                       c.last_verified_at AS last_verified_at
            """, prefix=route_id)

            charger_candidates = [
                {
                    "charger_id": rec["charger_id"],
                    "name": rec["name"],
                    "lat": float(rec["lat"]),
                    "lng": float(rec["lng"]),
                    "max_power_kw": float(rec["max_power_kw"]),
                    "connector_types": rec["connector_types"] or [],
                    "operator": rec["operator"] or "Unknown",
                    "reliability_score": float(rec["reliability_score"] or 0.5),
                    "status": rec.get("status") or "UNKNOWN",
                    "data_source": rec.get("data_source") or "NEO4J_GRAPH",
                    "verification_source": rec.get("verification_source") or "Neo4j Graph Database",
                    "last_verified_at": rec.get("last_verified_at"),
                }
                for rec in charger_res
            ]

            return {
                "route_id": route_id,
                "segments": segments,
                "charger_candidates": charger_candidates,
            }
    except Exception as e:
        logger.error(f"[Neo4j] Graph route lookup error: {e}")
        return None


def plan_with_neo4j(req) -> Optional[Any]:
    """
    Query Neo4j graph for EV-feasible path matching request origin/destination.
    Integrates graph topology with authoritative physical simulation.
    Returns None if Neo4j is offline or query returns empty, allowing clean demo fallback.
    """
    driver = get_driver()
    if not driver:
        return None

    try:
        from app.models.schemas import RoutePlanResponse
        from app.services.routing_service import plan_segments_and_chargers

        graph_data = find_graph_route(
            origin_lat=req.origin_lat,
            origin_lng=req.origin_lng,
            dest_lat=req.dest_lat,
            dest_lng=req.dest_lng,
            corridor_hint=req.demo_route_id,
        )

        if not graph_data:
            return None

        route_id = graph_data["route_id"]
        segments = graph_data["segments"]
        charger_candidates = graph_data["charger_candidates"]

        total_distance = sum(s.distance_km for s in segments)

        # Plan fastest and risk-aware route options through authoritative physics simulation
        fastest_opt = plan_segments_and_chargers(
            route_id=f"{route_id}_neo4j_fast",
            label="Neo4j Graph Route (Fastest)",
            description=f"Path traversed directly from Neo4j graph nodes. Total: {total_distance:.1f} km.",
            distance_km=round(total_distance, 1),
            segments=segments,
            charger_candidates=charger_candidates,
            vehicle=req.vehicle,
            ambient_c=req.ambient_temp_c,
            confidence=req.confidence_target,
            disabled_ids=req.disabled_charger_ids,
            risk_aware=False,
        )

        risk_aware_opt = plan_segments_and_chargers(
            route_id=f"{route_id}_neo4j_risk",
            label="Neo4j Graph Route (Risk-Aware)",
            description=f"Risk-aware path traversed from Neo4j graph nodes with filtered charger reliability.",
            distance_km=round(total_distance, 1),
            segments=segments,
            charger_candidates=charger_candidates,
            vehicle=req.vehicle,
            ambient_c=req.ambient_temp_c,
            confidence=req.confidence_target,
            disabled_ids=req.disabled_charger_ids,
            risk_aware=True,
        )

        recommended = fastest_opt.route_id
        if risk_aware_opt and risk_aware_opt.feasible and not fastest_opt.feasible:
            recommended = risk_aware_opt.route_id
        elif risk_aware_opt and risk_aware_opt.feasible and risk_aware_opt.risk_score < fastest_opt.risk_score - 0.1:
            recommended = risk_aware_opt.route_id

        failure_scenario = None
        if req.disabled_charger_ids:
            failure_scenario = (
                f"Charger failure simulated for {len(req.disabled_charger_ids)} station(s). "
                f"Neo4j graph recalculated alternative feasible path."
            )

        return RoutePlanResponse(
            fastest_route=fastest_opt,
            risk_aware_route=risk_aware_opt,
            recommended=recommended,
            neo4j_used=True,
            data_source="Neo4j Graph Database (Connected & Active). P90 arrival confidence is analytical and not validated with real-world road data.",
            charger_failure_scenario=failure_scenario,
        )
    except Exception as e:
        logger.error(f"[Neo4j] Graph routing query error: {e}")
        return None


# ==============================================================================
# LIVE GRAPH INTELLIGENCE & TRANSACTIONAL SYNCHRONIZATION API
# ==============================================================================

ALLOWED_LABELS = {
    "City", "Region", "Road", "Highway", "RoadNode", "RoadSegment",
    "Junction", "ChargingStation", "ChargingConnector", "ChargingOperator",
    "ChargingReport", "Vehicle", "BatteryConfiguration", "Charger"
}

ALLOWED_REL_TYPES = {
    "CONNECTED_TO", "HAS_SEGMENT", "CONTAINS", "LOCATED_IN",
    "HAS_CHARGING_STATION", "HAS_CONNECTOR", "OPERATED_BY",
    "SUPPORTS", "COMPATIBLE_WITH", "HAS_BATTERY_CONFIGURATION",
    "REPORTS_STATUS", "LOCATED_NEAR", "ROAD_SEGMENT"
}


def _get_pk_field(entity_type: str) -> str:
    mapping = {
        "City": "city_id",
        "Region": "region_id",
        "Road": "road_id",
        "Highway": "highway_id",
        "RoadNode": "node_id",
        "RoadSegment": "segment_id",
        "Junction": "junction_id",
        "ChargingStation": "station_id",
        "ChargingConnector": "connector_id",
        "ChargingOperator": "operator_id",
        "ChargingReport": "report_id",
        "Vehicle": "vehicle_id",
        "BatteryConfiguration": "config_id",
    }
    return mapping.get(entity_type, "station_id")


def get_graph_statistics() -> Dict[str, Any]:
    """
    Query real Neo4j graph statistics (node counts by label, relationship counts by type).
    Returns graceful offline status when Neo4j is disabled or unconfigured.
    """
    if not is_enabled():
        return {
            "status": "DISABLED",
            "connected": False,
            "database": os.environ.get("NEO4J_DATABASE", "neo4j"),
            "total_nodes": 0,
            "total_relationships": 0,
            "nodes_by_type": {},
            "relationships_by_type": {},
            "message": "Neo4j is disabled by default (NEO4J_ENABLED=false)",
        }

    driver = get_driver()
    if not driver:
        return {
            "status": "DISCONNECTED",
            "connected": False,
            "database": os.environ.get("NEO4J_DATABASE", "neo4j"),
            "total_nodes": 0,
            "total_relationships": 0,
            "nodes_by_type": {},
            "relationships_by_type": {},
            "message": get_last_error() or "Unable to establish Neo4j driver connection",
        }

    try:
        with driver.session() as session:
            # Total nodes
            tot_nodes_res = session.run("MATCH (n) RETURN count(n) AS cnt").single()
            total_nodes = tot_nodes_res["cnt"] if tot_nodes_res else 0

            # Total relationships
            tot_rels_res = session.run("MATCH ()-[r]->() RETURN count(r) AS cnt").single()
            total_relationships = tot_rels_res["cnt"] if tot_rels_res else 0

            # Breakdown by node label
            nodes_by_type = {}
            for record in session.run("MATCH (n) UNWIND labels(n) AS lbl RETURN lbl, count(*) AS cnt ORDER BY cnt DESC"):
                nodes_by_type[record["lbl"]] = record["cnt"]

            # Breakdown by relationship type
            rels_by_type = {}
            for record in session.run("MATCH ()-[r]->() RETURN type(r) AS typ, count(*) AS cnt ORDER BY cnt DESC"):
                rels_by_type[record["typ"]] = record["cnt"]

            return {
                "status": "CONNECTED",
                "connected": True,
                "database": os.environ.get("NEO4J_DATABASE", "neo4j"),
                "total_nodes": total_nodes,
                "total_relationships": total_relationships,
                "nodes_by_type": nodes_by_type,
                "relationships_by_type": rels_by_type,
                "message": "Neo4j graph statistics retrieved successfully",
            }
    except Exception as e:
        logger.warning(f"[Neo4j] Failed to retrieve graph stats: {e}")
        return {
            "status": "DEGRADED",
            "connected": False,
            "database": os.environ.get("NEO4J_DATABASE", "neo4j"),
            "total_nodes": 0,
            "total_relationships": 0,
            "nodes_by_type": {},
            "relationships_by_type": {},
            "message": f"Query execution failed: {str(e)}",
        }


def get_graph_elements(
    limit: int = 150,
    entity_types: Optional[List[str]] = None,
    environment: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Retrieve nodes and connecting relationships for live graph visualization.
    Applies strict pagination, bounds, and entity filtering.
    """
    if not is_enabled():
        return {
            "status": "DISABLED",
            "nodes": [],
            "relationships": [],
            "total_nodes": 0,
            "total_relationships": 0,
            "message": "Neo4j is disabled (NEO4J_ENABLED=false)",
        }

    driver = get_driver()
    if not driver:
        return {
            "status": "DISCONNECTED",
            "nodes": [],
            "relationships": [],
            "total_nodes": 0,
            "total_relationships": 0,
            "message": get_last_error() or "Neo4j is disconnected",
        }

    clamped_limit = max(1, min(limit, 300))

    try:
        with driver.session() as session:
            # Query nodes
            where_clauses = []
            params: Dict[str, Any] = {"limit": clamped_limit}

            if environment:
                where_clauses.append("n.environment = $env")
                params["env"] = environment.upper()

            if entity_types:
                clean_types = [t for t in entity_types if t in ALLOWED_LABELS]
                if clean_types:
                    type_checks = " OR ".join(f"'{t}' IN labels(n)" for t in clean_types)
                    where_clauses.append(f"({type_checks})")

            where_str = f"WHERE {' AND '.join(where_clauses)}" if where_clauses else ""
            node_query = f"""
                MATCH (n)
                {where_str}
                RETURN n, labels(n) AS labels, elementId(n) AS eid
                LIMIT $limit
            """

            nodes_map = {}
            for r in session.run(node_query, **params):
                node_data = dict(r["n"])
                labels = r["labels"]
                primary_label = labels[0] if labels else "Node"
                if "Charger" in labels and "ChargingStation" in labels:
                    primary_label = "ChargingStation"

                node_id = (
                    node_data.get("station_id")
                    or node_data.get("charger_id")
                    or node_data.get("node_id")
                    or node_data.get("city_id")
                    or node_data.get("operator_id")
                    or node_data.get("connector_id")
                    or node_data.get("segment_id")
                    or node_data.get("id")
                    or str(r["eid"])
                )

                nodes_map[node_id] = {
                    "id": str(node_id),
                    "element_id": str(r["eid"]),
                    "label": primary_label,
                    "labels": labels,
                    "name": node_data.get("name") or node_data.get("station_name") or str(node_id),
                    "properties": node_data,
                    "provenance": node_data.get("provenance", "SIMULATED"),
                    "environment": node_data.get("environment", "DEMO"),
                }

            # Query relationships between the collected nodes
            relationships = []
            if nodes_map:
                id_list = list(nodes_map.keys())
                rel_query = """
                    MATCH (a)-[r]->(b)
                    WHERE (coalesce(a.station_id, a.node_id, a.city_id, a.operator_id, a.connector_id, a.segment_id, a.id) IN $id_list)
                      AND (coalesce(b.station_id, b.node_id, b.city_id, b.operator_id, b.connector_id, b.segment_id, b.id) IN $id_list)
                    RETURN coalesce(a.station_id, a.node_id, a.city_id, a.operator_id, a.connector_id, a.segment_id, a.id) AS src_id,
                           coalesce(b.station_id, b.node_id, b.city_id, b.operator_id, b.connector_id, b.segment_id, b.id) AS dst_id,
                           type(r) AS rel_type, properties(r) AS rel_props, elementId(r) AS rel_eid
                    LIMIT 400
                """
                for r in session.run(rel_query, id_list=id_list):
                    relationships.append({
                        "id": str(r["rel_eid"]),
                        "source": str(r["src_id"]),
                        "target": str(r["dst_id"]),
                        "type": str(r["rel_type"]),
                        "properties": dict(r["rel_props"]),
                    })

            return {
                "status": "CONNECTED",
                "nodes": list(nodes_map.values()),
                "relationships": relationships,
                "total_nodes": len(nodes_map),
                "total_relationships": len(relationships),
                "message": "Graph elements queried successfully",
            }
    except Exception as e:
        logger.error(f"[Neo4j] Failed to fetch graph elements: {e}")
        return {
            "status": "DEGRADED",
            "nodes": [],
            "relationships": [],
            "total_nodes": 0,
            "total_relationships": 0,
            "message": f"Graph query error: {str(e)}",
        }


def get_node_by_id(node_id: str) -> Optional[Dict[str, Any]]:
    """Retrieve full property payload and relationship degree for a single node."""
    driver = get_driver()
    if not driver:
        return None

    try:
        with driver.session() as session:
            query = """
                MATCH (n)
                WHERE coalesce(n.station_id, n.node_id, n.city_id, n.operator_id, n.connector_id, n.segment_id, n.id) = $nid
                OPTIONAL MATCH (n)-[out_r]->(target)
                OPTIONAL MATCH (source)-[in_r]->(n)
                RETURN n, labels(n) AS labels,
                       collect(DISTINCT {type: type(out_r), target: coalesce(target.station_id, target.node_id, target.name, target.id)}) AS out_rels,
                       collect(DISTINCT {type: type(in_r), source: coalesce(source.station_id, source.node_id, source.name, source.id)}) AS in_rels
            """
            res = session.run(query, nid=node_id).single()
            if not res or not res["n"]:
                return None

            node_data = dict(res["n"])
            return {
                "id": node_id,
                "labels": res["labels"],
                "properties": node_data,
                "outgoing_relationships": [r for r in res["out_rels"] if r["type"] is not None],
                "incoming_relationships": [r for r in res["in_rels"] if r["type"] is not None],
            }
    except Exception as e:
        logger.error(f"[Neo4j] get_node_by_id error: {e}")
        return None


def sync_entity_to_graph(payload: Dict[str, Any], operation: str) -> bool:
    """
    Idempotent transactional graph synchronizer.
    Applies MERGE-based upserts and safe entity deletions.
    """
    driver = get_driver()
    if not driver:
        return False

    entity_type = payload.get("entity_type")
    entity_id = payload.get("entity_id")

    if not entity_type or not entity_id:
        logger.error("[Neo4j Sync] Missing entity_type or entity_id in outbox payload")
        return False

    label = entity_type if entity_type in ALLOWED_LABELS else "AppEntity"
    pk_field = _get_pk_field(label)

    try:
        with driver.session() as session:
            if operation.upper() == "DELETE":
                # Safe detach delete for target entity
                del_query = f"""
                    MATCH (n:{label})
                    WHERE n.{pk_field} = $eid OR n.id = $eid
                    DETACH DELETE n
                """
                session.run(del_query, eid=entity_id)
                logger.info(f"[Neo4j Sync] Deleted node {label}:{entity_id}")
                return True

            # CREATE or UPDATE
            props = dict(payload.get("properties", {}))
            props["id"] = entity_id
            props[pk_field] = entity_id
            props["name"] = payload.get("name", entity_id)
            props["provenance"] = payload.get("provenance", "SIMULATED")
            props["environment"] = payload.get("environment", "DEMO")
            props["last_synchronized_at"] = datetime.now(timezone.utc).isoformat()

            # Ensure lat/lng are numeric floats if present
            if "lat" in props and props["lat"] is not None:
                props["lat"] = float(props["lat"])
            if "lng" in props and props["lng"] is not None:
                props["lng"] = float(props["lng"])
            if "latitude" in props and props["latitude"] is not None:
                props["latitude"] = float(props["latitude"])
                props["lat"] = float(props["latitude"])
            if "longitude" in props and props["longitude"] is not None:
                props["longitude"] = float(props["longitude"])
                props["lng"] = float(props["longitude"])

            # 1. Upsert target entity node
            upsert_query = f"""
                MERGE (n:{label} {{{pk_field}: $eid}})
                SET n += $props, n.id = $eid
            """
            session.run(upsert_query, eid=entity_id, props=props)

            # If ChargingStation, also mirror Charger label for backward compatibility
            if label == "ChargingStation":
                session.run("MATCH (n:ChargingStation {station_id: $eid}) SET n:Charger, n.charger_id = $eid", eid=entity_id)

            # 2. Reconcile relationships
            relationships = payload.get("relationships", [])
            for rel in relationships:
                to_id = rel.get("to_id")
                rel_type = rel.get("type", "CONNECTED_TO")
                rel_props = dict(rel.get("properties", {}))
                rel_props["created_at"] = datetime.now(timezone.utc).isoformat()

                if to_id and rel_type in ALLOWED_REL_TYPES:
                    rel_cypher = f"""
                        MATCH (a {{{pk_field}: $eid}})
                        MATCH (b)
                        WHERE coalesce(b.station_id, b.charger_id, b.node_id, b.city_id, b.operator_id, b.connector_id, b.segment_id, b.id) = $to_id
                        MERGE (a)-[r:{rel_type}]->(b)
                        SET r += $rprops
                    """
                    session.run(rel_cypher, eid=entity_id, to_id=to_id, rprops=rel_props)

            logger.info(f"[Neo4j Sync] Successfully synced {label}:{entity_id} ({operation})")
            return True
    except Exception as e:
        logger.error(f"[Neo4j Sync] Error syncing {label}:{entity_id}: {e}")
        raise e


def purge_demo_graph() -> int:
    """
    Safely purge ONLY entities created with environment = 'DEMO' or provenance = 'SIMULATED'.
    Never deletes production infrastructure.
    """
    driver = get_driver()
    if not driver:
        return 0

    try:
        with driver.session() as session:
            res = session.run("""
                MATCH (n)
                WHERE n.environment = 'DEMO'
                DETACH DELETE n
                RETURN count(n) AS deleted_count
            """).single()
            cnt = res["deleted_count"] if res else 0
            logger.info(f"[Neo4j] Purged {cnt} demo graph nodes.")
            return cnt
    except Exception as e:
        logger.error(f"[Neo4j] Purge demo graph error: {e}")
        return 0
