"""
Elevation Provider Base Interface
=================================
Abstract interface for Digital Elevation Model (DEM) providers.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import List, Tuple, Optional
from pydantic import BaseModel, Field

from app.domain.provenance import DataProvenance, DataStatus, SourceType


class ElevationResult(BaseModel):
    """Container for batch elevation queries with queried vs interpolated provenance."""
    elevations: List[Optional[float]] = Field(
        ...,
        description="Elevations above sea level in meters; None if retrieval failed"
    )
    raw_elevations: Optional[List[Optional[float]]] = Field(
        None,
        description="Unfiltered raw DEM query points before median/moving-average smoothing"
    )
    queried_indices: List[int] = Field(
        default_factory=list,
        description="Indices directly retrieved from DEM API"
    )
    interpolated_indices: List[int] = Field(
        default_factory=list,
        description="Indices derived via spatial path-distance interpolation"
    )
    provider_name: str
    provenance: DataProvenance
    resolution_m: Optional[float] = Field(90.0, description="Native DEM spatial grid resolution in meters")


class ElevationProvider(ABC):
    """Abstract interface for elevation lookups."""

    @property
    @abstractmethod
    def provider_name(self) -> str:
        """Name of the DEM data source."""
        pass

    @abstractmethod
    def is_available(self) -> bool:
        """Check if elevation API endpoint is configured."""
        pass

    @abstractmethod
    def get_elevations(
        self,
        coordinates: List[Tuple[float, float]],
        cumulative_distances_m: Optional[List[float]] = None,
    ) -> ElevationResult:
        """
        Query elevations in meters for a sequence of (lat, lng) coordinates.
        Coordinates for which elevation cannot be retrieved should be None.
        """
        pass
