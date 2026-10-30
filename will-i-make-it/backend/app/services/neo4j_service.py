"""
Neo4j Graph Service
===================
Road network and charger graph modelling using Neo4j / AuraDB.
Handles graph persistence, Cypher-based EV routing queries, and
provides a graceful fallback when credentials are not configured
or authentication fails.

GRAPH SCHEMA
------------
Nodes:
  (:RoadNode {node_id, name, lat, lng, city, state})
  (:Charger {charger_id, name, lat, lng, max_power_kw, connector_types, operator, reliability_score})

Relationships:
  (:RoadNode)-[:ROAD_SEGMENT {
      segment_id, distance_km, avg_speed_kmh, gradient_pct, road_type
  }]->(:RoadNode)
  (:Charger)-[:LOCATED_AT]->(:RoadNode)
"""
from __future__ import annotations
import os
import math
from typing import Optional, List, Dict, Any
from dotenv import load_dotenv

load_dotenv()

_driver = None
_connected = False
_connection_attempted = False
_last_error = ""


def get_driver():
    """
    Get or initialize the Neo4j driver with resilience for:
    - Aura username normalization (translating account email/label to 'neo4j')
    - SSL certificate trust on Windows environments (fallback to neo4j+ssc://)
    """
    global _driver, _connected, _connection_attempted, _last_error
    if _driver is not None:
        return _driver

    uri = os.environ.get("NEO4J_URI", "").strip()
    raw_user = (os.environ.get("NEO4J_USERNAME") or os.environ.get("NEO4J_USER") or "neo4j").strip()
    password = os.environ.get("NEO4J_PASSWORD", "").strip()
    database = os.environ.get("NEO4J_DATABASE", "neo4j").strip()

    if not uri or not password:
        _connected = False
        _last_error = "NEO4J_URI or NEO4J_PASSWORD is not set"
        return None

    # Aura databases authenticate with username 'neo4j'
    user = raw_user
    instance_id = os.environ.get("AURA_INSTANCEID", "").strip()
    if not user or "@" in raw_user or "Aura" in raw_user or "(" in raw_user or user == instance_id:
        user = "neo4j"

    _connection_attempted = True

    try:
        from neo4j import GraphDatabase
    except ImportError:
        _last_error = "'neo4j' driver package not installed"
        print(f"[Neo4j] {_last_error}")
        return None

    # Test uri and SSL fallback if Windows trust store has issues with Let's Encrypt / DigiCert
    uris_to_try = [uri]
    if uri.startswith("neo4j+s://"):
        uris_to_try.append(uri.replace("neo4j+s://", "neo4j+ssc://"))
    elif uri.startswith("bolt+s://"):
        uris_to_try.append(uri.replace("bolt+s://", "bolt+ssc://"))

    for u in uris_to_try:
        try:
            d = GraphDatabase.driver(u, auth=(user, password))
            d.verify_connectivity()
            _driver = d
            _connected = True
            _last_error = ""
            print(f"[Neo4j] Successfully connected to {u} as user '{user}'")
            return _driver
        except Exception as e:
            _last_error = str(e)
            _driver = None
            _connected = False

    print(f"[Neo4j] Connection failed: {_last_error}")
    return None


def is_connected() -> bool:
    return _connected


def get_last_error() -> str:
    return _last_error


def seed_graph() -> bool:
    """Seed the Neo4j graph with road nodes, segments, and charging stations."""
    driver = get_driver()
    if not driver:
        return False

    from app.services.demo_data import DEMO_ROUTES, CHARGERS

    try:
        with driver.session() as session:
            # Constraints
            session.run("CREATE CONSTRAINT road_node_id IF NOT EXISTS FOR (n:RoadNode) REQUIRE n.node_id IS UNIQUE")
            session.run("CREATE CONSTRAINT charger_id IF NOT EXISTS FOR (c:Charger) REQUIRE c.charger_id IS UNIQUE")

            # Seed chargers
            for cid, c in CHARGERS.items():
                session.run("""
                    MERGE (ch:Charger {charger_id: $id})
                    SET ch.name = $name,
                        ch.lat = $lat, ch.lng = $lng,
                        ch.max_power_kw = $power,
                        ch.operator = $op,
                        ch.reliability_score = $rel,
                        ch.connector_types = $connectors
                """, id=cid, name=c["name"], lat=c["lat"], lng=c["lng"],
                    power=c["max_power_kw"], op=c["operator"],
                    rel=c["reliability_score"],
                    connectors=c["connector_types"])

            # Seed road segments from demo routes
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
                        SET a.lat = $flat, a.lng = $flng, a.name = $fname
                        MERGE (b:RoadNode {node_id: $tid})
                        SET b.lat = $tlat, b.lng = $tlng, b.name = $tname
                        MERGE (a)-[r:ROAD_SEGMENT {segment_id: $sid}]->(b)
                        SET r.distance_km = $dist, r.avg_speed_kmh = $speed,
                            r.gradient_pct = $grad, r.road_type = $rtype
                    """, fid=from_id, flat=from_lat, flng=from_lng, fname=seg.get("name", ""),
                        tid=to_id, tlat=to_lat, tlng=to_lng, tname="",
                        sid=seg["segment_id"], dist=seg["distance_km"],
                        speed=seg["avg_speed_kmh"], grad=seg["gradient_pct"],
                        rtype=seg["road_type"])

            print("[Neo4j] Graph successfully seeded with road network & chargers.")
            return True
    except Exception as e:
        print(f"[Neo4j] Seeding failed: {e}")
        return False


def plan_with_neo4j(req) -> Optional[Any]:
    """
    Query Neo4j graph for EV-feasible path matching request origin/destination.
    Returns None if Neo4j is offline or query returns empty, allowing clean demo fallback.
    """
    driver = get_driver()
    if not driver:
        return None

    try:
        from app.models.schemas import RouteSegment, RoutePlanResponse
        from app.services.routing_service import plan_segments_and_chargers

        route_id = req.demo_route_id or "MUMBAI_PUNE"

        with driver.session() as session:
            # Query road segments stored in graph
            result = session.run("""
                MATCH (a:RoadNode)-[r:ROAD_SEGMENT]->(b:RoadNode)
                WHERE a.node_id STARTS WITH $prefix
                RETURN r.segment_id AS segment_id, r.distance_km AS distance_km,
                       r.avg_speed_kmh AS avg_speed_kmh, r.gradient_pct AS gradient_pct,
                       r.road_type AS road_type, a.name AS name
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
                    name=rec["name"]
                )
                for rec in records
            ]

            # Query chargers stored in graph
            charger_res = session.run("""
                MATCH (c:Charger)
                RETURN c.charger_id AS charger_id, c.name AS name,
                       c.lat AS lat, c.lng AS lng, c.max_power_kw AS max_power_kw,
                       c.connector_types AS connector_types, c.operator AS operator,
                       c.reliability_score AS reliability_score
            """)
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
                }
                for rec in charger_res
            ]

        total_distance = sum(s.distance_km for s in segments)

        fastest_opt = plan_segments_and_chargers(
            route_id=f"{route_id}_neo4j",
            label="Neo4j Graph Route (Fastest)",
            description=f"Path traversed directly from Neo4j graph nodes. Total: {total_distance:.1f} km.",
            distance_km=round(total_distance, 1),
            segments=segments,
            charger_candidates=charger_candidates,
            vehicle=req.vehicle,
            ambient_c=req.ambient_temp_c,
            confidence=req.confidence_target,
            disabled_ids=req.disabled_charger_ids,
            risk_aware=False
        )

        risk_aware_opt = plan_segments_and_chargers(
            route_id=f"{route_id}_neo4j",
            label="Neo4j Graph Route (Risk-Aware)",
            description=f"Risk-aware path traversed from Neo4j graph nodes with filtered charger reliability.",
            distance_km=round(total_distance, 1),
            segments=segments,
            charger_candidates=charger_candidates,
            vehicle=req.vehicle,
            ambient_c=req.ambient_temp_c,
            confidence=req.confidence_target,
            disabled_ids=req.disabled_charger_ids,
            risk_aware=True
        )

        recommended = fastest_opt.route_id
        if risk_aware_opt and risk_aware_opt.feasible and not fastest_opt.feasible:
            recommended = risk_aware_opt.route_id
        elif risk_aware_opt and risk_aware_opt.feasible and risk_aware_opt.risk_score < fastest_opt.risk_score - 0.1:
            recommended = risk_aware_opt.route_id

        failure_scenario = None
        if req.disabled_charger_ids:
            failure_scenario = f"Charger failure simulated for {len(req.disabled_charger_ids)} station(s). Neo4j graph recalculated alternative feasible path."

        return RoutePlanResponse(
            fastest_route=fastest_opt,
            risk_aware_route=risk_aware_opt,
            recommended=recommended,
            neo4j_used=True,
            data_source="Neo4j Graph Database (Connected & Active). P90 arrival confidence is analytical and not validated with real-world road data.",
            charger_failure_scenario=failure_scenario
        )
    except Exception as e:
        print(f"[Neo4j] Graph routing query error: {e}")
        return None
