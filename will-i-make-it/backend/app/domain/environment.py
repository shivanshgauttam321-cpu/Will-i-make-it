"""
Environmental Domain Models
===========================
Domain representations for Weather and Traffic observations with explicit
distinctions between live measurements, forecasts, historical baselines,
and synthetic assumptions.
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional, Literal
from pydantic import BaseModel, Field, model_validator

from app.domain.provenance import DataValue, DataProvenance, DataStatus, DataFloat, DataStr


class WeatherDomain(BaseModel):
    """
    Atmospheric and ambient conditions along a corridor or at a waypoint.
    Distinguishes observed weather from forecast predictions.
    """
    ambient_temperature: DataFloat = Field(
        ...,
        description="Ambient air temperature in °C"
    )
    wind_speed: Optional[DataFloat] = Field(
        None,
        description="Wind speed in km/h or m/s (specified in unit)"
    )
    wind_direction_deg: Optional[DataFloat] = Field(
        None,
        description="Wind direction in degrees from true North (0–360°)"
    )
    precipitation_mm: Optional[DataFloat] = Field(
        None,
        description="Precipitation rate or accumulation in mm"
    )
    condition: Optional[DataStr] = Field(
        None,
        description="Categorical weather description (e.g. CLEAR, RAIN, FOG)"
    )
    is_forecast: bool = Field(
        False,
        description="True if value is a forecast prediction, False if actual observation"
    )
    forecast_timestamp: Optional[datetime] = Field(
        None,
        description="Valid forecast target time if is_forecast is True"
    )
    retrieval_timestamp: Optional[datetime] = Field(
        None,
        description="Timestamp when the weather record was fetched"
    )
    provenance: DataProvenance = Field(
        ...,
        description="Overall weather record provenance"
    )

    @model_validator(mode="after")
    def validate_weather_consistency(self) -> WeatherDomain:
        # Forecasts cannot be marked REAL observation
        if self.is_forecast and self.provenance.status == DataStatus.REAL:
            raise ValueError(
                "A weather forecast cannot be marked with DataStatus.REAL. "
                "Use DataStatus.ESTIMATED for weather forecasts."
            )
        # Validate wind direction
        if self.wind_direction_deg and self.wind_direction_deg.value is not None:
            if not (0.0 <= self.wind_direction_deg.value <= 360.0):
                raise ValueError("Wind direction must be between 0.0 and 360.0 degrees")
        # Validate precipitation
        if self.precipitation_mm and self.precipitation_mm.value is not None:
            if self.precipitation_mm.value < 0.0:
                raise ValueError("Precipitation cannot be negative")
        return self


class TrafficDomain(BaseModel):
    """
    Road segment or corridor traffic flow condition.
    Distinguishes live sensor telemetry from historical speed averages or synthetic traffic.
    """
    speed: DataFloat = Field(
        ...,
        description="Observed, estimated, or historical average speed in km/h"
    )
    congestion_level: DataStr = Field(
        ...,
        description="Flow categorization (e.g. FREE_FLOW, MODERATE, HEAVY, CONGESTED, STANDSTILL, UNKNOWN)"
    )
    delay_seconds: Optional[DataFloat] = Field(
        None,
        description="Estimated delay relative to free-flow conditions in seconds"
    )
    observation_time: Optional[datetime] = Field(
        None,
        description="Observation timestamp for live telemetry"
    )
    traffic_type: Literal["LIVE", "HISTORICAL", "STATIC_ASSUMPTION", "SIMULATED", "UNKNOWN"] = Field(
        "STATIC_ASSUMPTION",
        description="Category of traffic source"
    )
    provenance: DataProvenance = Field(
        ...,
        description="Traffic data provenance"
    )

    @model_validator(mode="after")
    def validate_traffic_consistency(self) -> TrafficDomain:
        if self.traffic_type == "LIVE" and self.provenance.status not in (DataStatus.REAL, DataStatus.STALE):
            raise ValueError("LIVE traffic must have DataStatus.REAL or DataStatus.STALE")
        if self.traffic_type == "SIMULATED" and self.provenance.status != DataStatus.SIMULATED:
            raise ValueError("SIMULATED traffic must have DataStatus.SIMULATED")
        if self.speed.value is not None and self.speed.value < 0:
            raise ValueError("Traffic speed cannot be negative")
        return self
