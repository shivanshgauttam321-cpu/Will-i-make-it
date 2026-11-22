"""
Charging Infrastructure Domain Models
=====================================
Domain representation for EV charging stations and connectors.

Key Engineering Principle:
Do not assign one single coarse confidence or provenance value to an entire station.
Separate:
- Station existence
- Station location (GPS)
- Connector types & ratings
- Operational status
- Live port availability
- Statistical reliability
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional, List, Tuple
from pydantic import BaseModel, Field, model_validator

from app.domain.provenance import (
    DataValue, DataProvenance, DataStatus, DataFloat, DataStr, DataInt, DataBool, DataCoords
)
from app.models.schemas import ConnectorType


class ConnectorDomain(BaseModel):
    """Physical charging plug and electrical characteristics."""
    connector_type: ConnectorType = Field(..., description="Plug standard (e.g. CCS2, CHAdeMO, Type2_AC)")
    rated_power_kw: DataFloat = Field(..., description="Nameplate power output in kW")
    voltage_v: Optional[DataFloat] = Field(None, description="Rated or operating DC/AC voltage in Volts")
    current_a: Optional[DataFloat] = Field(None, description="Maximum continuous current in Amperes")
    is_operational: DataBool = Field(..., description="Operating status of this specific connector")
    provenance: DataProvenance = Field(..., description="Connector specification provenance")

    @model_validator(mode="after")
    def validate_power_constraints(self) -> ConnectorDomain:
        if self.rated_power_kw.value is not None and self.rated_power_kw.value < 0:
            raise ValueError("Connector rated power cannot be negative")
        return self


class StationProvenanceBreakdown(BaseModel):
    """
    Explicit provenance tracking for distinct charging station attributes.
    Prevents confounding station existence with live availability or power rating.
    """
    existence: DataProvenance = Field(..., description="Provenance that this station exists physically")
    location: DataProvenance = Field(..., description="Provenance of GPS coordinates")
    connectors: DataProvenance = Field(..., description="Provenance of connector types and power ratings")
    operational_status: DataProvenance = Field(..., description="Provenance of whether hardware is active")
    live_availability: DataProvenance = Field(..., description="Provenance of real-time open port count")
    reliability: DataProvenance = Field(..., description="Provenance of calculated reliability metric")


class ChargingStationDomain(BaseModel):
    """
    EV Charging Hub / Station domain representation.
    Decouples existence, location, connector rating, operational status, and reliability.
    """
    station_id: str = Field(..., description="Unique station identifier")
    name: DataStr = Field(..., description="Station display name")
    coordinates: DataCoords = Field(..., description="(latitude, longitude) coordinates")
    address: Optional[str] = Field(None, description="Physical address or highway milestone description")
    operator: DataStr = Field(..., description="CPO (Charge Point Operator) name")

    connectors: List[ConnectorDomain] = Field(
        default_factory=list,
        description="List of available connectors at this hub"
    )
    max_power_kw: DataFloat = Field(..., description="Maximum simultaneous site power output in kW")
    available_ports: DataInt = Field(
        ...,
        description="Number of currently unreserved and unoccupied ports"
    )
    is_operational: DataBool = Field(
        ...,
        description="True if station is powered and accepting vehicles, False if broken/offline"
    )
    reliability_score: DataFloat = Field(
        ...,
        description="Statistical reliability metric (fraction between 0.0 and 1.0)"
    )
    last_observed_timestamp: Optional[datetime] = Field(
        None,
        description="Timestamp of most recent human or telemetry observation"
    )
    provenance_breakdown: Optional[StationProvenanceBreakdown] = Field(
        None,
        description="Attribute-level provenance breakdown"
    )
    provenance: DataProvenance = Field(
        ...,
        description="Overall station record provenance"
    )

    @model_validator(mode="after")
    def validate_station_constraints(self) -> ChargingStationDomain:
        # Validate coordinates
        if self.coordinates.value is not None:
            lat, lng = self.coordinates.value
            if not (-90.0 <= lat <= 90.0 and -180.0 <= lng <= 180.0):
                raise ValueError(f"Invalid GPS coordinates: ({lat}, {lng})")
        # Validate power
        if self.max_power_kw.value is not None and self.max_power_kw.value < 0:
            raise ValueError("Station max power cannot be negative")
        # Validate reliability
        if self.reliability_score.value is not None:
            if not (0.0 <= self.reliability_score.value <= 1.0):
                raise ValueError("Reliability score must be between 0.0 and 1.0")
        return self
