"""
Composite Charging Data Provider
================================
Aggregates and deduplicates charging stations across multiple provider backends
(Demo Seed, Open Charge Map, BEE EV Yatra).
Applies geospatial proximity deduplication and preserves authoritative provenance.
"""
from __future__ import annotations

import math
from typing import List, Optional, Dict, Any, Tuple
from app.services.chargers.base import ChargingDataProvider, ChargingProviderStation
from app.services.chargers.demo_provider import DemoChargerProvider
from app.services.chargers.open_charge_map import OpenChargeMapProvider
from app.services.chargers.ev_yatra_provider import EVYatraProvider


def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6371.0
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2.0) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2.0) ** 2
    return 2.0 * r * math.asin(math.sqrt(max(0.0, min(1.0, a))))


class CompositeChargerProvider(ChargingDataProvider):
    """Aggregates stations from all active external and seed providers."""

    def __init__(self, providers: Optional[List[ChargingDataProvider]] = None):
        if providers is not None:
            self._providers = providers
        else:
            self._providers = [
                DemoChargerProvider(),
                OpenChargeMapProvider(),
                EVYatraProvider(),
            ]

    @property
    def provider_name(self) -> str:
        active = [p.provider_name for p in self._providers if p.is_available()]
        return f"Composite Provider ({', '.join(active)})"

    def is_available(self) -> bool:
        return any(p.is_available() for p in self._providers)

    def get_stations_in_bbox(
        self,
        min_lat: float,
        min_lng: float,
        max_lat: float,
        max_lng: float,
        connector_types: Optional[List[str]] = None,
        min_power_kw: float = 0.0,
    ) -> List[ChargingProviderStation]:
        raw_stations: List[ChargingProviderStation] = []
        for p in self._providers:
            if p.is_available():
                try:
                    stations = p.get_stations_in_bbox(
                        min_lat, min_lng, max_lat, max_lng, connector_types, min_power_kw
                    )
                    raw_stations.extend(stations)
                except Exception:
                    pass

        # Deduplicate stations located within 50 meters of each other
        deduped: List[ChargingProviderStation] = []
        for s in raw_stations:
            duplicate = False
            for existing in deduped:
                dist_km = _haversine_km(s.latitude, s.longitude, existing.latitude, existing.longitude)
                if dist_km < 0.05:  # 50 meters
                    duplicate = True
                    # If incoming is VERIFIED_REAL and existing is DEMO_SEED, upgrade
                    if s.status == "VERIFIED_REAL" and existing.status != "VERIFIED_REAL":
                        existing.status = "VERIFIED_REAL"
                        existing.name = s.name
                        existing.data_source = s.data_source
                        existing.verification_source = s.verification_source
                    break
            if not duplicate:
                deduped.append(s)

        return deduped

    def get_station_by_id(self, station_id: str) -> Optional[ChargingProviderStation]:
        for p in self._providers:
            if p.is_available():
                st = p.get_station_by_id(station_id)
                if st:
                    return st
        return None

    def get_corridor_stations(
        self,
        polyline: List[List[float]],
        buffer_km: float = 35.0,
        connector_types: Optional[List[str]] = None,
        min_power_kw: float = 0.0,
    ) -> List[ChargingProviderStation]:
        """Find stations within buffer_km of a polyline."""
        if not polyline:
            return []

        lats = [pt[0] for pt in polyline]
        lngs = [pt[1] for pt in polyline]
        lat_buf = buffer_km / 111.0
        lng_buf = buffer_km / (111.0 * max(0.2, math.cos(math.radians(sum(lats) / len(lats)))))

        min_lat = min(lats) - lat_buf
        max_lat = max(lats) + lat_buf
        min_lng = min(lngs) - lng_buf
        max_lng = max(lngs) + lng_buf

        bbox_stations = self.get_stations_in_bbox(
            min_lat, min_lng, max_lat, max_lng, connector_types, min_power_kw
        )

        corridor_stations = []
        for s in bbox_stations:
            min_dist = min(_haversine_km(s.latitude, s.longitude, pt[0], pt[1]) for pt in polyline)
            if min_dist <= buffer_km:
                corridor_stations.append(s)

        return corridor_stations
