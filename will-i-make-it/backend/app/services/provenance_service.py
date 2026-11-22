"""
Centralized Data & Provenance Architecture Service
===================================================
Tracks health, operational status, data classification, and licensing of all
external data providers (Routing, Elevation, Weather, Charging Infrastructure, AI, Graph).
Enforces unambiguous provenance classifications:
- REAL: Direct measured telemetry from live sensors or official real-time APIs.
- ESTIMATED: Statistically inferred or physically resampled values.
- SIMULATED: Deterministic model-based outputs or demonstration seed data.
- STALE: Data whose freshness threshold has expired.
- UNKNOWN: Default unverified or missing parameters.
"""
from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Dict, Any, List

from app.domain.provenance import DataStatus, SourceType


class ProvenanceService:
    """Centralized metadata and health inventory for all active application data feeds."""

    @staticmethod
    def get_providers_inventory() -> Dict[str, Any]:
        """Return status, licensing, and provenance classification for all integrated providers."""
        from app.services.neo4j_service import is_enabled as neo4j_enabled, is_connected as neo4j_connected, check_health as neo4j_health
        from app.services.sarvam_service import is_enabled as sarvam_enabled, is_configured as sarvam_configured
        from app.services.chargers.open_charge_map import OpenChargeMapProvider
        from app.services.chargers.ev_yatra_provider import EVYatraProvider

        ocm_provider = OpenChargeMapProvider()
        ev_yatra_provider = EVYatraProvider()

        return {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "provenance_definitions": {
                "REAL": "Direct measured telemetry from live physical sensors or official OCPP feeds.",
                "ESTIMATED": "Algorithmically resampled or statistically projected numerical values.",
                "SIMULATED": "Physics-driven synthetic model calculations or demo seed datasets.",
                "STALE": "Cached telemetry whose validity window has expired (>48 hours).",
                "UNKNOWN": "Default unverified parameter with neutral prior attribution.",
            },
            "providers": [
                {
                    "domain": "GRAPH_DATABASE",
                    "name": "Neo4j / AuraDB",
                    "enabled": neo4j_enabled(),
                    "active": neo4j_connected(),
                    "data_classification": "SIMULATED_WITH_TOPOLOGY",
                    "license": "Commercial / AuraDB Enterprise or Community",
                    "credentials_configured": bool(os.environ.get("NEO4J_URI") and os.environ.get("NEO4J_PASSWORD")),
                    "details": neo4j_health(),
                },
                {
                    "domain": "SPEECH_AND_AI",
                    "name": "Sarvam AI (Saarika & Bulbul)",
                    "enabled": sarvam_enabled(),
                    "active": sarvam_configured(),
                    "data_classification": "AI_GENERATED_EXPLANATION",
                    "license": "Sarvam AI Developer License",
                    "credentials_configured": bool(os.environ.get("SARVAM_API_KEY")),
                    "details": {
                        "stt_model": os.environ.get("SARVAM_STT_MODEL", "saarika:v2"),
                        "tts_model": os.environ.get("SARVAM_TTS_MODEL", "bulbul:v1"),
                    },
                },
                {
                    "domain": "ROUTING",
                    "name": "OSRM Road-Snapped Engine",
                    "enabled": True,
                    "active": True,
                    "data_classification": "REAL_TOPOLOGY",
                    "license": "OpenStreetMap ODbL",
                    "credentials_configured": True,
                    "details": {"server": os.environ.get("OSRM_SERVER_URL", "https://router.project-osrm.org")},
                },
                {
                    "domain": "ELEVATION",
                    "name": "Open-Meteo DEM Elevation API",
                    "enabled": True,
                    "active": True,
                    "data_classification": "ESTIMATED",
                    "license": "Open-Meteo Non-Commercial / Attribution",
                    "credentials_configured": True,
                    "details": {"endpoint": os.environ.get("OPEN_METEO_ELEVATION_URL", "https://api.open-meteo.com/v1/elevation")},
                },
                {
                    "domain": "WEATHER",
                    "name": "Open-Meteo Atmospheric Forecast",
                    "enabled": True,
                    "active": True,
                    "data_classification": "ESTIMATED",
                    "license": "Open-Meteo Non-Commercial / Attribution",
                    "credentials_configured": True,
                    "details": {"endpoint": os.environ.get("OPEN_METEO_WEATHER_URL", "https://api.open-meteo.com/v1/forecast")},
                },
                {
                    "domain": "CHARGERS_OPEN_CHARGE_MAP",
                    "name": "Open Charge Map Registry",
                    "enabled": ocm_provider.is_available(),
                    "active": ocm_provider.is_available(),
                    "data_classification": "REAL",
                    "license": "Creative Commons Attribution-ShareAlike 4.0 International",
                    "credentials_configured": ocm_provider.is_available(),
                    "details": {"status": "ACTIVE" if ocm_provider.is_available() else "AWAITING_API_KEY"},
                },
                {
                    "domain": "CHARGERS_DEMO_SEED",
                    "name": "Certified Demonstration Seed Stations",
                    "enabled": True,
                    "active": True,
                    "data_classification": "DEMO_SEED",
                    "license": "Internal Project Benchmark Dataset",
                    "credentials_configured": True,
                    "details": {"stations_count": 5},
                },
            ],
            "physics_authority": "EV 'Will I Make It?' Physics Simulation Core is the authoritative source for all energy, voltage, thermal, and reachability feasibility computations.",
        }
