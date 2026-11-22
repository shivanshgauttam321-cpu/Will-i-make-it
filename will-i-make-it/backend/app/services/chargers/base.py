"""
Charging Infrastructure Provider Base Architecture
===================================================
Defines contracts for real-world and simulated charging station providers.
Guarantees strict attribution of provenance, operator identity, connector specifications,
and operational status across all external data feeds.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import List, Optional, Dict, Any


@dataclass
class ChargingProviderStation:
    """Normalized charging station entity returned by data providers."""
    station_id: str
    name: str
    latitude: float
    longitude: float
    max_power_kw: float
    operator_name: str
    connector_types: List[str]
    status: str = "UNKNOWN"  # VERIFIED_REAL, DEMO_SEED, HYPOTHETICAL, STALE, UNKNOWN
    data_source: str = "UNKNOWN"
    verification_source: str = "Unverified"
    reliability_score: float = 0.50
    reliability_freshness_hours: Optional[float] = None
    is_operational: Optional[bool] = None
    address: Optional[str] = None
    last_verified_at: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "charger_id": self.station_id,
            "name": self.name,
            "lat": self.latitude,
            "lng": self.longitude,
            "max_power_kw": self.max_power_kw,
            "operator": self.operator_name,
            "connector_types": self.connector_types,
            "status": self.status,
            "data_source": self.data_source,
            "verification_source": self.verification_source,
            "reliability_score": self.reliability_score,
            "reliability_freshness_hours": self.reliability_freshness_hours,
            "is_operational": self.is_operational,
            "address": self.address,
            "last_verified_at": self.last_verified_at,
        }


class ChargingDataProvider(ABC):
    """Abstract interface for external charging network providers."""

    @property
    @abstractmethod
    def provider_name(self) -> str:
        """Name of the data provider."""
        ...

    @abstractmethod
    def is_available(self) -> bool:
        """Return True if the provider is configured and reachable."""
        ...

    @abstractmethod
    def get_stations_in_bbox(
        self,
        min_lat: float,
        min_lng: float,
        max_lat: float,
        max_lng: float,
        connector_types: Optional[List[str]] = None,
        min_power_kw: float = 0.0,
    ) -> List[ChargingProviderStation]:
        """Query stations within a bounding box."""
        ...

    @abstractmethod
    def get_station_by_id(self, station_id: str) -> Optional[ChargingProviderStation]:
        """Retrieve a specific station by its unique ID."""
        ...
