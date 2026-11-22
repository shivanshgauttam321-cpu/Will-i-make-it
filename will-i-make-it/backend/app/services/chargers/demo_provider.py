"""
Demonstration Charging Station Provider
=======================================
Supplies static baseline demonstration charging stations for Indian highway corridors.
Preserves explicit DEMO_SEED provenance and never claims live telemetry.
"""
from __future__ import annotations

from typing import List, Optional, Dict, Any
from app.services.chargers.base import ChargingDataProvider, ChargingProviderStation
from app.services.demo_data import CHARGERS


class DemoChargerProvider(ChargingDataProvider):
    """Provider supplying verified demonstration seed stations."""

    @property
    def provider_name(self) -> str:
        return "Certified Indian Demo Seed Repository"

    def is_available(self) -> bool:
        return True

    def _convert(self, c: Dict[str, Any]) -> ChargingProviderStation:
        return ChargingProviderStation(
            station_id=c["charger_id"],
            name=c["name"],
            latitude=float(c["lat"]),
            longitude=float(c["lng"]),
            max_power_kw=float(c["max_power_kw"]),
            operator_name=c.get("operator", "Independent"),
            connector_types=c.get("connector_types", []),
            status=c.get("status", "DEMO_SEED"),
            data_source=c.get("data_source", "DEMO_DATABASE"),
            verification_source=c.get("verification_source", "Demonstration seed data based on approximate public POI"),
            reliability_score=float(c.get("reliability_score", 0.50)),
            reliability_freshness_hours=c.get("reliability_freshness_hours"),
            is_operational=c.get("is_operational"),
            address=c.get("address"),
            last_verified_at=c.get("last_verified_at"),
        )

    def get_stations_in_bbox(
        self,
        min_lat: float,
        min_lng: float,
        max_lat: float,
        max_lng: float,
        connector_types: Optional[List[str]] = None,
        min_power_kw: float = 0.0,
    ) -> List[ChargingProviderStation]:
        results = []
        for c in CHARGERS.values():
            lat = c["lat"]
            lng = c["lng"]
            if min_lat <= lat <= max_lat and min_lng <= lng <= max_lng:
                if c["max_power_kw"] >= min_power_kw:
                    if connector_types:
                        if not any(ct in c.get("connector_types", []) for ct in connector_types):
                            continue
                    results.append(self._convert(c))
        return results

    def get_station_by_id(self, station_id: str) -> Optional[ChargingProviderStation]:
        if station_id in CHARGERS:
            return self._convert(CHARGERS[station_id])
        return None
