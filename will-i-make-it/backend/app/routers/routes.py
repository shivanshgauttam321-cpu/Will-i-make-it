"""Route planning endpoints."""
from typing import List
from fastapi import APIRouter, HTTPException, Query
from app.models.schemas import RoutePlanRequest, RoutePlanResponse
from app.services.routing_service import plan_routes
from app.services.demo_data import get_all_demo_routes, get_demo_route

router = APIRouter(prefix="/api/routes", tags=["Routes"])


@router.get("/demo")
def list_demo_routes():
    """
    List all available demo routes.
    All routes are SIMULATED with approximate Indian geography data.
    """
    routes = get_all_demo_routes()
    return {
        "routes": routes,
        "count": len(routes),
        "disclaimer": "SIMULATED routes using approximate Indian road data. Not real-time navigation.",
    }


@router.get("/demo/{route_id}")
def get_demo_route_detail(route_id: str):
    """Get full detail (including segments) for a specific demo route."""
    route = get_demo_route(route_id)
    if not route:
        raise HTTPException(status_code=404, detail=f"Demo route '{route_id}' not found")
    return route


@router.get("/geocode")
def geocode_places(q: str = Query("", description="Search term for Indian cities, places, or landmarks")):
    """
    Search places and coordinates across India for custom EV route planning.
    Combines instant pre-indexed major Indian locations with live OpenStreetMap geocoding.
    """
    from app.services.geocoding_service import search_locations
    return {"query": q, "results": search_locations(q, limit=8)}


@router.get("/geometry/{route_id}")
def get_route_geometry_endpoint(route_id: str):
    """
    Returns exact road-snapped coordinates [[lat, lng], ...] for a given route.
    Traces actual expressways and highways turn-by-turn with high precision.
    """
    route = get_demo_route(route_id)
    if not route:
        raise HTTPException(status_code=404, detail=f"Route '{route_id}' not found")
    geom = route.get("road_geometry", [])
    return {
        "route_id": route_id,
        "coordinates": geom,
        "point_count": len(geom),
        "precision": "high-definition-road-snapped",
    }


@router.post("/plan", response_model=RoutePlanResponse)
def plan(req: RoutePlanRequest):
    """
    Plan an EV trip with battery-feasibility constraints.

    Compares fastest vs risk-aware routes. Accounts for:
    - Per-segment energy consumption (P50 and P90)
    - Charging stops (charger reliability, connector compatibility)
    - Reserve SoC constraint at destination
    - Optional disabled chargers (failure simulation)

    Use `demo_route_id` to force a specific demo scenario.
    Use `disabled_charger_ids` to simulate charger failures.
    """
    try:
        return plan_routes(req)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Route planning failed: {str(e)}")
