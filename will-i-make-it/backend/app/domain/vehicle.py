"""
Vehicle Domain Models
=====================
Strongly-typed vehicle representation with individual parameter provenance.
Parameters are represented independently to distinguish verified manufacturer
specs from estimated or simulated parameters.
"""
from __future__ import annotations

from typing import Optional, List
from pydantic import BaseModel, Field, model_validator

from app.domain.provenance import DataValue, DataQuality, DataStatus, DataFloat, DataStr, DataInt
from app.models.schemas import ConnectorType


class VehicleParameter(DataValue[float]):
    """Physical vehicle parameter with units and source provenance."""
    pass


class VehicleDomain(BaseModel):
    """
    EV vehicle definition with parameter-level provenance.
    Avoids assigning a single coarse provenance to the entire vehicle.
    """
    model_config = {"protected_namespaces": ()}

    vehicle_id: str = Field(..., description="Unique vehicle profile ID")
    make: DataStr = Field(..., description="Vehicle manufacturer name")
    model: DataStr = Field(..., description="Vehicle model name")
    variant: Optional[DataStr] = Field(None, description="Specific trim or variant")
    model_year: Optional[DataInt] = Field(None, description="Model production year")

    # Core physical parameters
    battery_capacity_kwh: DataFloat = Field(
        ...,
        description="Gross battery pack capacity in kWh"
    )
    usable_battery_capacity_kwh: DataFloat = Field(
        ...,
        description="Net usable battery capacity in kWh"
    )
    curb_mass_kg: DataFloat = Field(
        ...,
        description="Curb mass of the vehicle in kg"
    )
    drag_coefficient: DataFloat = Field(
        ...,
        description="Aerodynamic drag coefficient (Cd, dimensionless)"
    )
    frontal_area_m2: DataFloat = Field(
        ...,
        description="Frontal cross-sectional area in m²"
    )
    rolling_resistance_coeff: DataFloat = Field(
        ...,
        description="Rolling resistance coefficient (Crr, dimensionless)"
    )
    drivetrain_efficiency: DataFloat = Field(
        ...,
        description="Overall drivetrain transmission efficiency (fraction between 0.5 and 1.0)"
    )
    regen_efficiency: DataFloat = Field(
        ...,
        description="Maximum kinetic energy recovery efficiency (fraction between 0.0 and 0.95)"
    )

    # Charging specifications
    max_dc_charging_power_kw: Optional[DataFloat] = Field(
        None,
        description="Peak DC fast charging power acceptance in kW"
    )
    max_ac_charging_power_kw: Optional[DataFloat] = Field(
        None,
        description="Peak on-board AC charger acceptance in kW"
    )
    charging_curve_reference: Optional[str] = Field(
        None,
        description="Identifier or reference key to the charging power profile curve"
    )
    connector_types: List[ConnectorType] = Field(
        default_factory=list,
        description="Compatible physical connector standards"
    )

    # Operational quality assessment
    data_quality: Optional[DataQuality] = Field(
        None,
        description="Multi-dimensional quality assessment for this vehicle record"
    )

    @model_validator(mode="after")
    def validate_physical_constraints(self) -> VehicleDomain:
        # Validate battery capacity
        if self.battery_capacity_kwh.value is not None:
            if self.battery_capacity_kwh.value <= 0:
                raise ValueError("Gross battery capacity must be positive")
        if self.usable_battery_capacity_kwh.value is not None:
            if self.usable_battery_capacity_kwh.value <= 0:
                raise ValueError("Usable battery capacity must be positive")
            if (self.battery_capacity_kwh.value is not None and
                    self.usable_battery_capacity_kwh.value > self.battery_capacity_kwh.value):
                raise ValueError("Usable battery capacity cannot exceed gross capacity")

        # Validate mass
        if self.curb_mass_kg.value is not None and self.curb_mass_kg.value <= 0:
            raise ValueError("Vehicle curb mass must be positive")

        # Validate drag coefficient
        if self.drag_coefficient.value is not None:
            if not (0.10 <= self.drag_coefficient.value <= 0.85):
                raise ValueError(f"Drag coefficient {self.drag_coefficient.value} outside credible range (0.10 - 0.85)")

        # Validate frontal area
        if self.frontal_area_m2.value is not None:
            if not (1.0 <= self.frontal_area_m2.value <= 6.0):
                raise ValueError(f"Frontal area {self.frontal_area_m2.value} m² outside credible range (1.0 - 6.0 m²)")

        # Validate efficiencies
        if self.drivetrain_efficiency.value is not None:
            if not (0.30 <= self.drivetrain_efficiency.value <= 1.0):
                raise ValueError("Drivetrain efficiency must be between 0.30 and 1.0")
        if self.regen_efficiency.value is not None:
            if not (0.0 <= self.regen_efficiency.value <= 0.95):
                raise ValueError("Regen efficiency must be between 0.0 and 0.95")

        return self
