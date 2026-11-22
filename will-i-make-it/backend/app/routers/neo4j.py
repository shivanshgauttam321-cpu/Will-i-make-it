"""
Neo4j Aura Intelligence & Outbox Synchronization Router
======================================================
Provides live graph exploration, real-time node/edge inspection, statistics,
and reliable transactional outbox synchronization endpoints.
"""
from __future__ import annotations

import logging
from typing import Optional, List, Dict, Any
from fastapi import APIRouter, HTTPException, Query, BackgroundTasks
from pydantic import BaseModel, Field

from app.services.neo4j_service import (
    is_enabled as neo4j_enabled,
    check_health as neo4j_health,
    get_graph_statistics,
    get_graph_elements,
    get_node_by_id,
    purge_demo_graph,
)
from app.services.outbox_service import (
    save_entity,
    delete_entity,
    get_outbox_events,
    get_outbox_stats,
    cleanup_demo_records,
)
from app.services.graph_sync_service import (
    get_sync_health_overview,
    process_outbox_batch,
    retry_single_event,
)
from app.services.sync_worker import trigger_sync

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/neo4j", tags=["Neo4j Graph & Synchronization"])


# --- Schemas ---

class DemoStationInput(BaseModel):
    station_id: Optional[str] = Field(default="CHR_DEMO_EXPRESS_01", description="Unique station ID")
    name: Optional[str] = Field(default="Jio-bp Pulse Expressway Hub [DEMO]", description="Station name")
    lat: Optional[float] = Field(default=18.9820, description="Latitude")
    lng: Optional[float] = Field(default=73.0840, description="Longitude")
    power_kw: Optional[float] = Field(default=60.0, description="Charging power in kW")
    operator_name: Optional[str] = Field(default="Jio-bp Pulse", description="Operator name")
    connector_type: Optional[str] = Field(default="CCS2", description="Primary connector standard")
    city_name: Optional[str] = Field(default="Navi Mumbai", description="City location")


class UpdateStationInput(BaseModel):
    station_id: str = Field(default="CHR_DEMO_EXPRESS_01", description="Station ID to update")
    name: Optional[str] = Field(default=None, description="Updated station name")
    power_kw: Optional[float] = Field(default=120.0, description="Upgraded power capacity in kW")
    is_operational: Optional[bool] = Field(default=True, description="Operational status")
    reliability_score: Optional[float] = Field(default=0.95, description="Updated reliability score")


# --- Endpoints ---

@router.get("/health")
def get_health() -> Dict[str, Any]:
    """Check live Neo4j Aura cluster connection health with masked credentials."""
    return neo4j_health()


@router.get("/stats")
def get_stats() -> Dict[str, Any]:
    """Retrieve actual node counts by label, relationship counts by type, and outbox event metrics."""
    graph_stats = get_graph_statistics()
    outbox_stats = get_outbox_stats()
    return {
        **graph_stats,
        "outbox_statistics": outbox_stats,
    }


@router.get("/graph")
def get_graph(
    limit: int = Query(150, ge=1, le=300, description="Max nodes to fetch"),
    entity_types: Optional[str] = Query(None, description="Comma-separated list of node labels"),
    environment: Optional[str] = Query(None, description="Filter by environment (DEMO, PROD)"),
) -> Dict[str, Any]:
    """
    Retrieve live nodes and connecting relationships from Neo4j for the Graph Monitor dashboard.
    Applies strict pagination, bounds, and entity filtering.
    """
    types_list = [t.strip() for t in entity_types.split(",")] if entity_types else None
    return get_graph_elements(limit=limit, entity_types=types_list, environment=environment)


@router.get("/nodes/{node_id}")
def get_node(node_id: str) -> Dict[str, Any]:
    """Retrieve full property map and incident relationships for a specific graph node."""
    node = get_node_by_id(node_id)
    if not node:
        raise HTTPException(status_code=404, detail=f"Graph node '{node_id}' not found")
    return node


@router.get("/sync/status")
def get_sync_status() -> Dict[str, Any]:
    """Get overall status of the outbox processor, worker health, and Neo4j connection."""
    return get_sync_health_overview()


@router.get("/sync/events")
def get_sync_events(
    limit: int = Query(50, ge=1, le=200, description="Max outbox events to fetch"),
    status: Optional[str] = Query(None, description="Filter by event status (PENDING, SUCCESS, FAILED, DEAD_LETTER)"),
) -> Dict[str, Any]:
    """Retrieve recent outbox events for the dashboard event monitor."""
    events = get_outbox_events(limit=limit, status=status)
    return {
        "count": len(events),
        "events": events,
    }


@router.post("/sync/retry/{event_id}")
def retry_event(event_id: str) -> Dict[str, Any]:
    """Authorized manual retry of a failed or dead-letter outbox event."""
    result = retry_single_event(event_id)
    if not result.get("success"):
        raise HTTPException(status_code=404, detail=result.get("message"))
    return result


@router.post("/sync/trigger")
def trigger_outbox_sync(background_tasks: BackgroundTasks) -> Dict[str, Any]:
    """Trigger an immediate outbox synchronization batch."""
    background_tasks.add_task(trigger_sync)
    res = process_outbox_batch(limit=25)
    return {
        "message": "Outbox synchronization triggered",
        "result": res,
    }


# ==============================================================================
# CONTROLLED DEMO WORKFLOW ENDPOINTS (Section 9 & 10)
# ==============================================================================

@router.post("/demo/create-sample")
def create_demo_infrastructure(
    payload: Optional[DemoStationInput] = None,
    background_tasks: BackgroundTasks = None,
) -> Dict[str, Any]:
    """
    Administrator-controlled demonstration: creates sample interconnected demo entities
    (City, Operator, RoadSegment, ChargingStation, Connector) in the primary SQLite DB.
    Generates outbox events and triggers near real-time synchronization to Neo4j.
    """
    data = payload or DemoStationInput()
    sid = data.station_id or "CHR_DEMO_EXPRESS_01"
    cid = f"CITY_{data.city_name.upper().replace(' ', '_')}"
    opid = f"OP_{data.operator_name.upper().replace(' ', '_').replace('-', '_')}"
    conn_id = f"CONN_{sid}_{data.connector_type}"
    seg_id = f"SEG_{cid}_EXPRESSWAY"

    created_events = []

    # 1. City
    city_ent, ev1 = save_entity(
        entity_type="City",
        entity_id=cid,
        name=data.city_name,
        properties={"lat": data.lat, "lng": data.lng, "state": "Maharashtra"},
        provenance="SIMULATED",
        environment="DEMO",
    )
    created_events.append(ev1)

    # 2. Operator
    op_ent, ev2 = save_entity(
        entity_type="ChargingOperator",
        entity_id=opid,
        name=data.operator_name,
        properties={"country": "India", "reliability_tier": "Verified Enterprise"},
        provenance="SIMULATED",
        environment="DEMO",
    )
    created_events.append(ev2)

    # 3. Connector
    conn_ent, ev3 = save_entity(
        entity_type="ChargingConnector",
        entity_id=conn_id,
        name=f"{data.connector_type} Gun",
        properties={"type": data.connector_type, "max_power_kw": data.power_kw},
        provenance="SIMULATED",
        environment="DEMO",
    )
    created_events.append(ev3)

    # 4. Road Segment
    seg_ent, ev4 = save_entity(
        entity_type="RoadSegment",
        entity_id=seg_id,
        name=f"{data.city_name} Expressway Corridor",
        properties={"distance_km": 28.5, "speed_limit_kmh": 100, "road_type": "expressway"},
        relationships=[{"to_id": cid, "type": "LOCATED_IN"}],
        provenance="SIMULATED",
        environment="DEMO",
    )
    created_events.append(ev4)

    # 5. Charging Station (interconnected)
    st_ent, ev5 = save_entity(
        entity_type="ChargingStation",
        entity_id=sid,
        name=data.name,
        properties={
            "lat": data.lat,
            "lng": data.lng,
            "max_power_kw": data.power_kw,
            "operator": data.operator_name,
            "status": "OPERATIONAL",
            "reliability_score": 0.92,
            "data_source": "WEBSITE_DEMO_PORTAL",
            "verification_source": "Administrator Demonstration Seed",
        },
        relationships=[
            {"to_id": cid, "type": "LOCATED_IN"},
            {"to_id": opid, "type": "OPERATED_BY"},
            {"to_id": conn_id, "type": "HAS_CONNECTOR"},
            {"to_id": seg_id, "type": "HAS_CHARGING_STATION"},
        ],
        provenance="SIMULATED",
        environment="DEMO",
    )
    created_events.append(ev5)

    # Wake up synchronization worker
    trigger_sync()
    if background_tasks:
        background_tasks.add_task(process_outbox_batch, limit=10)

    return {
        "success": True,
        "message": f"Demo infrastructure created with {len(created_events)} entities & outbox events.",
        "station_id": sid,
        "events_created": created_events,
        "environment": "DEMO",
        "provenance": "SIMULATED",
    }


@router.post("/demo/update-sample")
def update_demo_station(
    payload: Optional[UpdateStationInput] = None,
    background_tasks: BackgroundTasks = None,
) -> Dict[str, Any]:
    """
    Administrator-controlled demonstration: updates the demo charging station in the
    primary SQLite DB, generates an UPDATE outbox event, and syncs changes to Neo4j.
    """
    data = payload or UpdateStationInput()
    sid = data.station_id

    # Retrieve current entity properties
    from app.services.outbox_service import _get_conn
    conn = _get_conn()
    row = conn.execute("SELECT properties_json, name FROM app_entities WHERE entity_id = ?", (sid,)).fetchone()
    conn.close()

    if not row:
        raise HTTPException(status_code=404, detail=f"Station '{sid}' not found in primary database.")

    import json
    current_props = json.loads(row["properties_json"])
    station_name = data.name or row["name"]
    if data.power_kw is not None:
        current_props["max_power_kw"] = data.power_kw
    if data.reliability_score is not None:
        current_props["reliability_score"] = data.reliability_score
    if data.is_operational is not None:
        current_props["status"] = "OPERATIONAL" if data.is_operational else "OUT_OF_SERVICE"

    updated_ent, event_id = save_entity(
        entity_type="ChargingStation",
        entity_id=sid,
        name=station_name,
        properties=current_props,
        provenance="SIMULATED",
        environment="DEMO",
    )

    trigger_sync()
    if background_tasks:
        background_tasks.add_task(process_outbox_batch, limit=5)

    return {
        "success": True,
        "message": f"Demo station '{sid}' updated. Outbox event '{event_id}' queued.",
        "event_id": event_id,
        "updated_properties": current_props,
    }


@router.post("/demo/cleanup")
def cleanup_demo_data() -> Dict[str, Any]:
    """
    Administrator-controlled cleanup: purges ONLY demonstration records (environment = 'DEMO')
    from both the primary SQLite database and Neo4j graph.
    Leaves production and real infrastructure completely untouched.
    """
    sqlite_res = cleanup_demo_records()
    neo4j_deleted = purge_demo_graph()

    return {
        "success": True,
        "message": "Demo records cleaned up successfully from both databases.",
        "primary_db_cleanup": sqlite_res,
        "neo4j_nodes_deleted": neo4j_deleted,
    }
