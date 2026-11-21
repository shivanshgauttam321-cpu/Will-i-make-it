# Will I Make It - EV Route Planner
# Pydantic schemas for request/response validation

from __future__ import annotations
from typing import Optional, List, Literal
from datetime import datetime
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
    soc_start_pct: float = Field(80.0, ge=0.0, le=100.0, description="Starting state of charge in % (0.0 to 100.0 inclusive)")
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

    @field_validator('soc_start_pct')
    @classmethod
    def validate_soc_start_bounds(cls, v: float) -> float:
        import math
        if not math.isfinite(v) or v < 0.0 or v > 100.0:
            raise ValueError(f"Starting SOC must be finite and within [0.0, 100.0]%, got {v}")
        return v

    @field_validator('soc_reserve_pct')
    @classmethod
    def reserve_less_than_start(cls, v, values):
        return v


class RouteSegment(BaseModel):
    """A single road segment for energy calculation."""
    model_config = {"extra": "allow"}

    segment_id: str = Field(description="Unique segment identifier")
    distance_km: float = Field(ge=0.01, description="Segment distance in km")
    avg_speed_kmh: float = Field(ge=1, le=200, description="Average speed in km/h")
    gradient_pct: Optional[float] = Field(None, ge=-35, le=35, description="Road gradient in % (None if UNKNOWN)")
    gradient_status: Optional[str] = Field(None, description="DataStatus: REAL, ESTIMATED, UNKNOWN")
    gradient_is_clamped: bool = Field(False, description="True if raw gradient exceeded plausibility bounds")
    raw_gradient_pct: Optional[float] = Field(None, description="Exact calculated gradient before clamping")
    speed_limit_kmh: Optional[float] = Field(None, ge=1, le=200, description="Statutory speed limit if known")
    road_type: Literal["highway", "urban", "rural"] = Field("urban")
    raw_road_class: Optional[str] = Field(None, description="Original road class from routing provider")
    name: Optional[str] = None
    bearing: Optional[float] = Field(None, description="Vehicle heading azimuth in degrees")
    wind_speed_ms: Optional[float] = Field(None, description="Wind speed in m/s")
    wind_direction_deg: Optional[float] = Field(None, description="Wind direction blowing from in degrees")
    elevation_start: Optional[float] = Field(None, description="Start elevation in m")
    elevation_end: Optional[float] = Field(None, description="End elevation in m")


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
    gradient_unknown: bool = Field(False, description="True if elevation/gradient data was unavailable")
    gradient_clamped: bool = Field(False, description="True if gradient was clamped to realistic limits")


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
    uncertainty_disclosure: str = Field(
        default="MODEL_BASED_P90_ESTIMATE",
        description="Explicit classification of P90 as a mathematical model estimate, not an empirical fleet warranty",
    )


class Charger(BaseModel):
    """A charging station."""
    model_config = {"extra": "allow"}

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
    status: str = Field(
        default="UNKNOWN",
        description="VERIFIED_REAL, DEMO_SEED, HYPOTHETICAL, STALE, UNKNOWN",
    )
    data_source: Optional[str] = Field(
        default=None,
        description="Originating data catalog or provider (e.g. OpenData, SeedCatalog, UserReport)",
    )
    verification_source: Optional[str] = Field(
        default=None,
        description="Method used for verification (e.g. LiveOCPP, PhysicalAudit, SyntheticDemo)",
    )
    last_verified_at: Optional[datetime] = Field(
        default=None,
        description="Timestamp of most recent empirical verification or status audit",
    )


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
    reference_time: Optional[datetime] = Field(None, description="Deterministic reference time for test/simulation evaluation")


class ChargingStop(BaseModel):
    charger: Charger
    arrive_soc_pct: float
    depart_soc_pct: float
    charge_duration_min: float
    charge_energy_kwh: float
    charge_notes: Optional[str] = Field(
        default=None,
        description="Physical charging model notes (e.g. CCCV taper, thermal limits)",
    )


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
    feasibility_status: Optional[str] = Field(
        default=None,
        description="WILL_MAKE_IT, SIMULATED_WITH_DEMO_INFRASTRUCTURE, CONDITIONAL_INFRASTRUCTURE_REQUIRED, LOW_RESERVE, UNCERTAIN, WILL_NOT_MAKE_IT, SIMULATION_ERROR",
    )
    is_energy_feasible: Optional[bool] = Field(
        default=None,
        description="True if vehicle battery can physically complete journey under driving energy demands",
    )
    all_chargers_reachable: Optional[bool] = Field(
        default=None,
        description="True if battery arrives at every scheduled charging stop above minimum operating limit",
    )
    infrastructure_status: Optional[str] = Field(
        default="UNKNOWN",
        description="Aggregate provenance of required infrastructure: VERIFIED_REAL, DEMO_SEED, HYPOTHETICAL, UNKNOWN",
    )
    overall_confidence: Optional[str] = Field(
        default="MODEL_BASED",
        description="Overall route confidence level based on combined physics and infrastructure verification",
    )
    max_battery_temp_c: Optional[float] = Field(default=None, description="Peak pack temperature during journey [°C]")
    min_battery_temp_c: Optional[float] = Field(default=None, description="Minimum pack temperature during journey [°C]")
    was_thermally_derated: Optional[bool] = Field(default=None, description="True if thermal derating was triggered")
    total_btms_energy_kwh: Optional[float] = Field(default=None, description="Active thermal management electrical consumption in kWh")


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
