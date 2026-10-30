"""Health and system info endpoints."""
from fastapi import APIRouter
from app.services.neo4j_service import is_connected as neo4j_connected, get_last_error as neo4j_last_error
from app.services.sarvam_service import is_configured as sarvam_configured

router = APIRouter(prefix="/api", tags=["Health"])


@router.get("/health")
def health_check():
    connected = neo4j_connected()
    return {
        "status": "ok",
        "service": "Will I Make It – EV Route Planner",
        "version": "1.0.0-mvp",
        "neo4j_connected": connected,
        "neo4j_diagnostic": "Connected & active" if connected else (neo4j_last_error() or "Not connected (fallback active)"),
        "sarvam_configured": sarvam_configured(),
        "data_disclaimer": (
            "All routes, chargers, and energy estimates in demo mode are SIMULATED. "
            "Not validated against real-world Indian EV drive data."
        ),
    }
