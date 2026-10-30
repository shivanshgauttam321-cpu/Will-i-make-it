"""Charger management endpoints."""
from typing import Optional, List
from fastapi import APIRouter, HTTPException, Query
from app.models.schemas import ChargerReport, Charger, ConnectorType
from app.services.charger_service import (
    add_report, compute_reliability, get_trip
)
from app.services.demo_data import chargers_near, get_charger, get_all_chargers

router = APIRouter(prefix="/api/chargers", tags=["Chargers"])


@router.get("/nearby")
def nearby_chargers(
    lat: float = Query(..., description="Latitude"),
    lng: float = Query(..., description="Longitude"),
    radius_km: float = Query(50.0, ge=1, le=500, description="Search radius in km"),
    connector: Optional[List[str]] = Query(None, description="Filter by connector type"),
):
    """
    Find chargers within radius_km of a location.
    Returns reliability scores with freshness indicators.
    Unknown reliability is returned as 0.5, NOT as 'available'.
    """
    chargers = chargers_near(lat, lng, radius_km, connector)
    # Enrich with live reliability from DB
    enriched = []
    for c in chargers:
        rel = compute_reliability(c["charger_id"])
        enriched.append({
            **c,
            "reliability_score": rel["score"],
            "reliability_freshness_hours": rel["freshness_hours"],
            "total_reports": rel["total_reports"],
            "reliability_note": rel.get("note", ""),
        })
    return {
        "chargers": enriched,
        "count": len(enriched),
        "search_center": {"lat": lat, "lng": lng},
        "radius_km": radius_km,
        "disclaimer": "SIMULATED charger data. Real-time availability not guaranteed.",
    }


@router.get("/all")
def all_chargers():
    """List all demo chargers with computed reliability scores."""
    all_c = get_all_chargers()
    enriched = []
    for c in all_c:
        rel = compute_reliability(c["charger_id"])
        enriched.append({
            **c,
            "reliability_score": rel["score"],
            "reliability_freshness_hours": rel["freshness_hours"],
            "total_reports": rel["total_reports"],
        })
    return {"chargers": enriched, "count": len(enriched)}


@router.post("/report")
def submit_report(report: ChargerReport):
    """
    Submit an operational report for a charger.
    Reports affect the reliability score (smoothed Beta posterior).
    Use this endpoint to simulate charger failure for the demo.
    """
    charger = get_charger(report.charger_id)
    if not charger:
        raise HTTPException(status_code=404, detail=f"Charger '{report.charger_id}' not found")

    rid = add_report(
        charger_id=report.charger_id,
        success=report.success,
        connector=report.connector_type.value,
        power_kw=report.reported_power_kw,
        notes=report.notes,
        reporter_id=report.reporter_id,
    )

    new_rel = compute_reliability(report.charger_id)
    return {
        "report_id": rid,
        "charger_id": report.charger_id,
        "charger_name": charger["name"],
        "success_recorded": report.success,
        "new_reliability_score": new_rel["score"],
        "freshness_hours": new_rel["freshness_hours"],
        "total_reports": new_rel["total_reports"],
        "message": (
            f"Report recorded. New reliability score: {new_rel['score']:.2f} "
            f"(based on {new_rel['total_reports']} reports, smoothed Beta posterior)."
        ),
    }
