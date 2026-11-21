"""
Route, Segment, and Elevation Domain Models
===========================================
Normalized domain representation for road routes, directed road segments,
and elevation profiles.
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional, List, Tuple
from pydantic import BaseModel, Field, model_validator

from app.domain.provenance import (
    DataValue, DataProvenance, DataStatus, DataFloat, DataStr
)
from app.domain.environment import WeatherDomain, TrafficDomain


class ElevationDomain(BaseModel):
    """Point elevation data with retrieval metadata and source attribution."""
    latitude: float = Field(..., ge=-90.0, le=90.0)
    longitude: float = Field(..., ge=-180.0, le=180.0)
    elevation: DataFloat = Field(..., description="Elevation above mean sea level in meters")
    elevation_source: Optional[str] = Field(None, description="DEM provider (e.g. SRTM, Copernicus, Open-Meteo DEM)")
    retrieval_timestamp: Optional[datetime] = Field(None, description="When elevation was queried")
    resolution_m: Optional[float] = Field(None, description="Spatial grid resolution in meters")
    interpolation_method: Optional[str] = Field(None, description="Bilinear, bicubic, or nearest neighbor")
    provenance: DataProvenance = Field(..., description="Elevation provenance metadata")


class RouteSegmentDomain(BaseModel):
    """
    A single directed road segment forming part of a journey.
    Carries independently attributed parameters for geometry, elevation, traffic, and weather.
    """
    segment_id: str = Field(..., description="Unique segment identifier")
    sequence_order: int = Field(0, ge=0, description="0-indexed order along the route")
    name: Optional[str] = Field(None, description="Road or highway name (e.g. Mumbai-Pune Expressway)")

    distance: DataFloat = Field(..., description="Segment length in km")
    speed: DataFloat = Field(..., description="Target or average vehicle speed in km/h")
    speed_limit: Optional[DataFloat] = Field(None, description="Statutory speed limit in km/h if known")
    elevation_start: Optional[DataFloat] = Field(None, description="Starting elevation in meters")
    elevation_end: Optional[DataFloat] = Field(None, description="Ending elevation in meters")
    gradient: DataFloat = Field(..., description="Accepted road gradient in % (positive = uphill, negative = downhill)")
    raw_gradient: Optional[DataFloat] = Field(None, description="Calculated gradient in % before clamping")
    gradient_is_clamped: bool = Field(False, description="True if raw gradient exceeded realistic bounds (±35%)")

    road_type: DataStr = Field(..., description="Road category: highway, urban, rural, expressway")
    raw_road_class: Optional[str] = Field(None, description="Original road class from routing provider (e.g. motorway, trunk_link)")
    road_condition: DataStr = Field(
        ...,
        description="Surface quality: SMOOTH_ASPHALT, ROUGH, POTHOLED, GRAVEL, UNKNOWN"
    )

    traffic: Optional[TrafficDomain] = Field(None, description="Traffic state on this segment")
    weather: Optional[WeatherDomain] = Field(None, description="Ambient weather along this segment")
    energy_prediction_kwh: Optional[DataFloat] = Field(None, description="Modeled net energy draw in kWh")
    geometry: Optional[List[Tuple[float, float]]] = Field(None, description="Waypoints [(lat, lng), ...] defining the curve")

    @model_validator(mode="after")
    def validate_segment_constraints(self) -> RouteSegmentDomain:
        if self.distance.value is not None and self.distance.value <= 0:
            raise ValueError("Segment distance must be strictly positive")
        if self.speed.value is not None and self.speed.value <= 0:
            raise ValueError("Segment speed must be positive")
        if self.gradient.value is not None:
            if not (-35.0 <= self.gradient.value <= 35.0):
                raise ValueError(f"Gradient {self.gradient.value}% exceeds realistic road bounds (-35% to +35%)")
        return self


class RouteDomain(BaseModel):
    """
    Normalized journey route representation.
    Composed of sequenced segments, origin/destination nodes, and provider provenance.
    """
    route_id: str = Field(..., description="Unique route identification")
    origin_coordinates: Tuple[float, float] = Field(..., description="Start (lat, lng)")
    destination_coordinates: Tuple[float, float] = Field(..., description="End (lat, lng)")
    origin_name: Optional[str] = Field(None, description="Human-readable origin description")
    dest_name: Optional[str] = Field(None, description="Human-readable destination description")

    distance: DataFloat = Field(..., description="Total journey distance in km")
    duration: DataFloat = Field(..., description="Estimated travel time in minutes")

    route_provider: Optional[str] = Field(None, description="Routing engine (e.g. OSRM, Valhalla, Mappls)")
    route_provider_reference: Optional[str] = Field(None, description="Routing API query reference or hash")
    retrieval_timestamp: Optional[datetime] = Field(None, description="When route was generated")

    segments: List[RouteSegmentDomain] = Field(default_factory=list, description="Ordered road segments")
    geometry: Optional[List[Tuple[float, float]]] = Field(None, description="Full road-snapped polyline coordinates")
    elevation_gain_m: Optional[float] = Field(None, description="Total elevation gain in meters")
    elevation_loss_m: Optional[float] = Field(None, description="Total elevation loss in meters")
    alternatives: List[str] = Field(default_factory=list, description="Identifiers of alternative routes considered")
    provenance: DataProvenance = Field(..., description="Provenance of route geometry and topology")

    @model_validator(mode="after")
    def validate_route_constraints(self) -> RouteDomain:
        olat, olng = self.origin_coordinates
        dlat, dlng = self.destination_coordinates
        if not (-90.0 <= olat <= 90.0 and -180.0 <= olng <= 180.0):
            raise ValueError(f"Origin coordinates invalid: ({olat}, {olng})")
        if not (-90.0 <= dlat <= 90.0 and -180.0 <= dlng <= 180.0):
            raise ValueError(f"Destination coordinates invalid: ({dlat}, {dlng})")
        if self.distance.value is not None and self.distance.value <= 0:
            raise ValueError("Total route distance must be positive")
        return self
