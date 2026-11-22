"""
Routing Provider Base Interfaces
================================
Abstract interface and data structures for external routing providers.
Supports switching between Mappls, Valhalla, OSRM, or test mocks.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import List, Tuple, Optional, Dict, Any
from pydantic import BaseModel, Field

from app.domain.provenance import DataProvenance, DataStatus, SourceType


class ProviderStep(BaseModel):
    """Maneuver or turn step returned by a routing provider."""
    name: Optional[str] = None
    instruction: Optional[str] = None
    distance_m: float
    duration_s: float
    start_coordinate: Tuple[float, float] = Field(..., description="(lat, lng)")
    end_coordinate: Tuple[float, float] = Field(..., description="(lat, lng)")
    geometry: Optional[List[Tuple[float, float]]] = None
    speed_limit_kmh: Optional[float] = None
    road_class: Optional[str] = None
    surface: Optional[str] = None


class ProviderRouteResult(BaseModel):
    """Normalized output from a routing provider query."""
    provider_name: str
    provider_route_id: Optional[str] = None
    distance_m: float
    duration_s: float
    geometry: List[Tuple[float, float]] = Field(..., description="Display geometry [(lat, lng), ...]")
    steps: List[ProviderStep] = Field(default_factory=list)
    alternatives: List[ProviderRouteResult] = Field(default_factory=list)
    raw_metadata: Dict[str, Any] = Field(default_factory=dict)
    provenance: DataProvenance


class RoutingProvider(ABC):
    """Abstract routing engine contract."""

    @property
    @abstractmethod
    def provider_name(self) -> str:
        """Name of the routing service."""
        pass

    @abstractmethod
    def is_available(self) -> bool:
        """Check if provider credentials/endpoints are operational."""
        pass

    @abstractmethod
    def get_route(
        self,
        origin: Tuple[float, float],
        destination: Tuple[float, float],
        options: Optional[Dict[str, Any]] = None,
    ) -> ProviderRouteResult:
        """
        Request driving route between origin and destination.
        Coordinates are (lat, lng).
        Raises ProviderError if request fails.
        """
        pass

    def get_route_alternatives(
        self,
        origin: Tuple[float, float],
        destination: Tuple[float, float],
        options: Optional[Dict[str, Any]] = None,
    ) -> List[ProviderRouteResult]:
        """Request route alternatives if supported by provider."""
        primary = self.get_route(origin, destination, options)
        return [primary] + primary.alternatives


class RoutingProviderError(Exception):
    """Raised when a routing provider request fails."""
    def __init__(self, provider: str, message: str, status_code: Optional[int] = None):
        self.provider = provider
        self.status_code = status_code
        super().__init__(f"[{provider}] {message}")
