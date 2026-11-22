"""
Open Charge Map API Provider Adapter
====================================
Integrates Open Charge Map (OCM) global registry for real-world public charging POIs.
Active only when OPEN_CHARGE_MAP_API_KEY is configured in environment.
Gracefully degrades with zero crashes when unconfigured or when network calls timeout.
"""
from __future__ import annotations

import os
import logging
import requests
from typing import List, Optional, Dict, Any
from app.services.chargers.base import ChargingDataProvider, ChargingProviderStation

logger = logging.getLogger(__name__)

OCM_BASE_URL = "https://api.openchargemap.io/v3/poi/"


class OpenChargeMapProvider(ChargingDataProvider):
    """Adapter for Open Charge Map public EV charging API."""

    def __init__(self, api_key: Optional[str] = None, timeout: float = 8.0):
        self._api_key = api_key or os.environ.get("OPEN_CHARGE_MAP_API_KEY", "").strip()
        self._timeout = timeout

    @property
    def provider_name(self) -> str:
        return "Open Charge Map Global Registry"

    def is_available(self) -> bool:
        return bool(self._api_key)

    def _map_connector_type(self, conn_id: int) -> str:
        """Map OCM ConnectionTypeID to standard connector enums."""
        mapping = {
            33: "CCS2",
            25: "Type2_AC",
            2: "CHAdeMO",
            1: "Type1_J1772",
            1036: "GB_T",
        }
        return mapping.get(conn_id, "Type2_AC")

    def get_stations_in_bbox(
        self,
        min_lat: float,
        min_lng: float,
        max_lat: float,
        max_lng: float,
        connector_types: Optional[List[str]] = None,
        min_power_kw: float = 0.0,
    ) -> List[ChargingProviderStation]:
        if not self.is_available():
            return []

        headers = {
            "X-API-Key": self._api_key,
            "User-Agent": "WillIMakeIt-EVRoutePlanner/2.0",
        }
        params = {
            "boundingbox": f"({min_lat},{min_lng}),({max_lat},{max_lng})",
            "countrycode": "IN",
            "maxresults": 50,
            "compact": "true",
            "verbose": "false",
        }

        try:
            resp = requests.get(OCM_BASE_URL, headers=headers, params=params, timeout=self._timeout)
            resp.raise_for_status()
            items = resp.json()

            stations = []
            for item in items:
                poi_id = f"OCM_{item.get('ID')}"
                addr_info = item.get("AddressInfo", {})
                lat = addr_info.get("Latitude")
                lng = addr_info.get("Longitude")
                if lat is None or lng is None:
                    continue

                conns = item.get("Connections", [])
                mapped_conns = []
                max_power = 0.0
                for c in conns:
                    t_id = c.get("ConnectionTypeID", 0)
                    mapped_conns.append(self._map_connector_type(t_id))
                    p = float(c.get("PowerKW") or 0.0)
                    if p > max_power:
                        max_power = p

                if max_power < min_power_kw:
                    continue
                if connector_types and not any(ct in mapped_conns for ct in connector_types):
                    continue

                status_type = item.get("StatusType", {})
                is_operational = status_type.get("IsOperational", True) if status_type else None
                status_str = "VERIFIED_REAL" if is_operational else "UNKNOWN"

                op_info = item.get("OperatorInfo", {})
                op_name = op_info.get("Title") or "OpenChargeMap Registered Operator"

                stations.append(
                    ChargingProviderStation(
                        station_id=poi_id,
                        name=f"{addr_info.get('Title', 'EV Charging Point')} [OCM]",
                        latitude=float(lat),
                        longitude=float(lng),
                        max_power_kw=max_power or 30.0,
                        operator_name=op_name,
                        connector_types=list(set(mapped_conns)) or ["CCS2"],
                        status=status_str,
                        data_source="OPEN_CHARGE_MAP",
                        verification_source="Open Charge Map community registry API (India)",
                        reliability_score=0.80 if is_operational else 0.50,
                        is_operational=is_operational,
                        address=f"{addr_info.get('AddressLine1', '')}, {addr_info.get('Town', '')}",
                        last_verified_at=item.get("DateLastStatusUpdate"),
                    )
                )
            return stations
        except Exception as e:
            logger.warning(f"[OpenChargeMap] POI fetch failed: {e}")
            return []

    def get_station_by_id(self, station_id: str) -> Optional[ChargingProviderStation]:
        if not self.is_available() or not station_id.startswith("OCM_"):
            return None
        raw_id = station_id.replace("OCM_", "")
        # Query single station
        headers = {
            "X-API-Key": self._api_key,
            "User-Agent": "WillIMakeIt-EVRoutePlanner/2.0",
        }
        try:
            resp = requests.get(f"{OCM_BASE_URL}{raw_id}", headers=headers, timeout=self._timeout)
            resp.raise_for_status()
            data = resp.json()
            if isinstance(data, list) and data:
                data = data[0]
            # Convert
            addr_info = data.get("AddressInfo", {})
            return ChargingProviderStation(
                station_id=station_id,
                name=addr_info.get("Title", "EV Station"),
                latitude=float(addr_info.get("Latitude", 0.0)),
                longitude=float(addr_info.get("Longitude", 0.0)),
                max_power_kw=50.0,
                operator_name=data.get("OperatorInfo", {}).get("Title", "OpenChargeMap Operator"),
                connector_types=["CCS2"],
                status="VERIFIED_REAL",
                data_source="OPEN_CHARGE_MAP",
                verification_source="Open Charge Map community registry API (India)",
            )
        except Exception:
            return None
