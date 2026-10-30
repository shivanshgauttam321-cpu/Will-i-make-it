# Will I Make It - EV Route Planner
# Pydantic schemas for request/response validation

from __future__ import annotations
from typing import Optional, List, Literal
from pydantic import BaseModel, Field, field_validator
from enum import Enum


class ConnectorType(str, Enum):
    CCS2 = "CCS2"
    CHAdeMO = "CHAdeMO"
    Type2_AC = "Type2_AC"
    Bharat_DC = "Bharat_DC"
    Bharat_AC = "Bharat_AC"


class VehicleProfile(BaseModel):
    """EV vehicle parameters for energy modelling."""
    battery_capacity_kwh: float = Field(40.0, ge=5, le=200, description="Total usable battery capacity in kWh")
    soc_start_pct: float = Field(80.0, ge=5, le=100, description="Starting state of charge in %")
    soc_reserve_pct: float = Field(10.0, ge=0, le=30, description="Minimum arrival SoC reserve in %")
    vehicle_mass_kg: float = Field(1500.0, ge=500, le=8000, description="Curb mass + payload in kg")
    drag_coefficient: float = Field(0.30, ge=0.1, le=0.8, description="Aerodynamic drag coefficient Cd")
    frontal_area_m2: float = Field(2.3, ge=1.0, le=6.0, description="Frontal area in m²")
    rolling_resistance: float = Field(0.012, ge=0.005, le=0.05, description="Rolling resistance coefficient Crr")
    drivetrain_efficiency: float = Field(0.88, ge=0.5, le=0.99, description="Motor + inverter + gearbox efficiency")
    regen_efficiency: float = Field(0.65, ge=0.0, le=0.95, description="Regenerative braking efficiency (fraction returned)")
    connector_types: List[ConnectorType] = Field(
        default=[ConnectorType.CCS2, ConnectorType.Type2_AC],
        description="Compatible connector types"
    )
    ac_load_kw: float = Field(1.5, ge=0.0, le=5.0, description="AC/climate auxiliary load in kW (0 = off)")
    payload_kg: float = Field(0.0, ge=0.0, le=2000.0, description="Additional payload beyond curb mass in kg")

    @field_validator('soc_reserve_pct')
    @classmethod
    def reserve_less_than_start(cls, v, values):
        return v


class RouteSegment(BaseModel):
    """A single road segment for energy calculation."""
    segment_id: str = Field(description="Unique segment identifier")
    distance_km: float = Field(ge=0.01, description="Segment distance in km")
    avg_speed_kmh: float = Field(ge=1, le=200, description="Average speed in km/h")
    gradient_pct: float = Field(0.0, ge=-30, le=30, description="Road gradient in % (positive = uphill)")
    road_type: Literal["highway", "urban", "rural"] = Field("urban")
    name: Optional[str] = None


class EnergyPredictRequest(BaseModel):
    """Request body for POST /api/energy/predict"""
    vehicle: VehicleProfile
    segments: List[RouteSegment] = Field(min_length=1)
    ambient_temp_c: float = Field(25.0, ge=-10, le=50, description="Ambient temperature in °C")
    confidence_target: float = Field(0.90, ge=0.5, le=0.99, description="Confidence target for P-percentile estimate")


class SegmentEnergyResult(BaseModel):
    """Energy breakdown for one segment."""
    segment_id: str
    name: Optional[str]
    distance_km: float
    rolling_kj: float = Field(description="Rolling resistance energy in kJ")
    aero_kj: float = Field(description="Aerodynamic drag energy in kJ")
    gradient_kj: float = Field(description="Gravitational potential energy in kJ (negative = regen)")
    aux_kj: float = Field(description="Auxiliary (AC + 12V) energy in kJ")
    regen_kj: float = Field(description="Regenerated energy in kJ (negative = recovered)")
    net_kwh: float = Field(description="Net energy from battery for this segment in kWh")
    net_kwh_p90: float = Field(description="Conservative P90 net energy in kWh")
    soc_after_pct: Optional[float] = None


class EnergyPredictResponse(BaseModel):
    """Response for POST /api/energy/predict"""
    total_kwh_p50: float = Field(description="Expected (P50) total energy consumption in kWh")
    total_kwh_p90: float = Field(description="Conservative (P90) total energy in kWh")
    soc_final_p50_pct: float = Field(description="Expected final SoC in %")
    soc_final_p90_pct: float = Field(description="Conservative final SoC in %")
    feasible: bool = Field(description="True if P90 final SoC >= reserve")
    segments: List[SegmentEnergyResult]
    assumptions: List[str]
    uncertainty_method: str
    data_disclaimer: str


class Charger(BaseModel):
    """A charging station."""
    charger_id: str
    name: str
    lat: float
    lng: float
    connector_types: List[ConnectorType]
    max_power_kw: float
    operator: str
    reliability_score: float = Field(ge=0, le=1, description="Smoothed reliability 0–1")
    reliability_freshness_hours: Optional[float] = Field(None, description="Age of most recent report in hours")
    is_operational: Optional[bool] = Field(None, description="None = unknown status")
    address: Optional[str] = None


class ChargerReport(BaseModel):
    """User report for POST /api/chargers/report"""
    charger_id: str
    success: bool = Field(description="Was charging successful?")
    connector_type: ConnectorType
    reported_power_kw: Optional[float] = None
    notes: Optional[str] = None
    reporter_id: Optional[str] = Field(None, description="Anonymous session ID")


class RoutePlanRequest(BaseModel):
    """Request body for POST /api/routes/plan"""
    origin_lat: float = Field(ge=5, le=40)
    origin_lng: float = Field(ge=60, le=100)
    dest_lat: float = Field(ge=5, le=40)
    dest_lng: float = Field(ge=60, le=100)
    origin_name: Optional[str] = Field(None, description="Human readable origin name or address")
    dest_name: Optional[str] = Field(None, description="Human readable destination name or address")
    vehicle: VehicleProfile
    ambient_temp_c: float = Field(25.0, ge=-10, le=50)
    confidence_target: float = Field(0.90, ge=0.5, le=0.99)
    demo_route_id: Optional[str] = Field(None, description="Use a preset demo route by ID")
    disabled_charger_ids: List[str] = Field(default=[], description="Charger IDs to treat as unavailable (failure demo)")


class ChargingStop(BaseModel):
    charger: Charger
    arrive_soc_pct: float
    depart_soc_pct: float
    charge_duration_min: float
    charge_energy_kwh: float


class RouteOption(BaseModel):
    route_id: str
    label: str
    description: str
    distance_km: float
    duration_min: float
    segments: List[RouteSegment]
    charging_stops: List[ChargingStop]
    energy_result: EnergyPredictResponse
    risk_score: float = Field(ge=0, le=1, description="0=low risk, 1=high risk")
    feasible: bool
    feasibility_margin_kwh: float
    explanation: str
    road_geometry: Optional[List[List[float]]] = Field(default=[], description="Exact road coordinates [[lat, lng], ...] snapped to highways and city streets")


class RoutePlanResponse(BaseModel):
    fastest_route: RouteOption
    risk_aware_route: Optional[RouteOption]
    recommended: str = Field(description="route_id of recommended option")
    neo4j_used: bool
    data_source: str
    charger_failure_scenario: Optional[str] = None


class TripSimulateRequest(BaseModel):
    route_id: str
    vehicle: VehicleProfile
    ambient_temp_c: float = 25.0
    noise_seed: Optional[int] = None


class TripRecord(BaseModel):
    trip_id: str
    route_id: str
    created_at: str
    actual_kwh: float
    predicted_kwh_p50: float
    predicted_kwh_p90: float
    within_p90: bool
    soc_final_pct: float
    notes: str


class NearbyChargersRequest(BaseModel):
    lat: float
    lng: float
    radius_km: float = Field(50.0, ge=1, le=500)
    connector_types: Optional[List[ConnectorType]] = None
