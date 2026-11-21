"""
Domain Adapters and Backward-Compatibility Layer
================================================
Bridges existing API schemas (app.models.schemas) with the rich,
provenance-aware domain models (app.domain).

Preserves 100% backward compatibility with the frontend and existing routers.
"""
from __future__ import annotations

from typing import List, Tuple
from app.models.schemas import (
    VehicleProfile,
    RouteSegment as RouteSegmentSchema,
    Charger as ChargerSchema,
    ConnectorType,
)
from app.domain.provenance import DataValue, DataProvenance, DataStatus, SourceType
from app.domain.vehicle import VehicleDomain
from app.domain.route import RouteSegmentDomain
from app.domain.charging import ChargingStationDomain, ConnectorDomain


def vehicle_profile_to_domain(
    profile: VehicleProfile,
    vehicle_id: str = "profile_default",
    status: DataStatus = DataStatus.SIMULATED,
    source_name: str = "Client VehicleProfile Input",
) -> VehicleDomain:
    """
    Convert a legacy API VehicleProfile to a rich VehicleDomain model.
    Attaches explicit units and provenance to each physical parameter.
    """
    prov = DataProvenance(
        status=status,
        source_name=source_name,
        source_type=SourceType.USER_REPORT if status == DataStatus.REAL else SourceType.SYNTHETIC_SIMULATION,
        notes="Converted from API VehicleProfile payload",
    )

    return VehicleDomain(
        vehicle_id=vehicle_id,
        make=DataValue(value="Generic", unit=None, provenance=prov),
        model=DataValue(value="EV Profile", unit=None, provenance=prov),
        battery_capacity_kwh=DataValue(value=profile.battery_capacity_kwh, unit="kWh", provenance=prov),
        usable_battery_capacity_kwh=DataValue(value=profile.battery_capacity_kwh, unit="kWh", provenance=prov),
        curb_mass_kg=DataValue(value=profile.vehicle_mass_kg, unit="kg", provenance=prov),
        drag_coefficient=DataValue(value=profile.drag_coefficient, unit=None, provenance=prov),
        frontal_area_m2=DataValue(value=profile.frontal_area_m2, unit="m2", provenance=prov),
        rolling_resistance_coeff=DataValue(value=profile.rolling_resistance, unit=None, provenance=prov),
        drivetrain_efficiency=DataValue(value=profile.drivetrain_efficiency, unit=None, provenance=prov),
        regen_efficiency=DataValue(value=profile.regen_efficiency, unit=None, provenance=prov),
        connector_types=profile.connector_types,
    )


def vehicle_domain_to_profile(
    domain: VehicleDomain,
    soc_start_pct: float = 80.0,
    soc_reserve_pct: float = 10.0,
    ac_load_kw: float = 1.5,
    payload_kg: float = 0.0,
) -> VehicleProfile:
    """
    Extract legacy API VehicleProfile from a VehicleDomain model.
    """
    return VehicleProfile(
        battery_capacity_kwh=domain.usable_battery_capacity_kwh.value or domain.battery_capacity_kwh.value or 40.0,
        soc_start_pct=soc_start_pct,
        soc_reserve_pct=soc_reserve_pct,
        vehicle_mass_kg=domain.curb_mass_kg.value or 1500.0,
        drag_coefficient=domain.drag_coefficient.value or 0.30,
        frontal_area_m2=domain.frontal_area_m2.value or 2.3,
        rolling_resistance=domain.rolling_resistance_coeff.value or 0.012,
        drivetrain_efficiency=domain.drivetrain_efficiency.value or 0.88,
        regen_efficiency=domain.regen_efficiency.value or 0.65,
        connector_types=domain.connector_types or [ConnectorType.CCS2],
        ac_load_kw=ac_load_kw,
        payload_kg=payload_kg,
    )


def segment_schema_to_domain(
    schema: RouteSegmentSchema,
    sequence_order: int = 0,
    status: DataStatus = DataStatus.SIMULATED,
    source_name: str = "Demo Route Data",
) -> RouteSegmentDomain:
    """Convert a legacy RouteSegment to a RouteSegmentDomain model."""
    prov = DataProvenance(
        status=status,
        source_name=source_name,
        source_type=SourceType.PHYSICS_MODEL if status == DataStatus.ESTIMATED else SourceType.SYNTHETIC_SIMULATION,
        notes="Converted from legacy RouteSegment",
    )

    is_grad_unknown = (schema.gradient_pct is None or getattr(schema, "gradient_status", None) == "UNKNOWN")
    if is_grad_unknown:
        grad_dv = DataValue.unknown(unit="%", notes="Elevation data unverified or unavailable in legacy schema")
    else:
        grad_dv = DataValue(value=schema.gradient_pct, unit="%", provenance=prov)

    speed_lim_val = getattr(schema, "speed_limit_kmh", None)
    speed_lim_dv = (
        DataValue.estimated(value=speed_lim_val, unit="km/h", source_name=source_name)
        if speed_lim_val is not None
        else None
    )

    return RouteSegmentDomain(
        segment_id=schema.segment_id,
        sequence_order=sequence_order,
        name=schema.name,
        distance=DataValue(value=schema.distance_km, unit="km", provenance=prov),
        speed=DataValue(value=schema.avg_speed_kmh, unit="km/h", provenance=prov),
        speed_limit=speed_lim_dv,
        gradient=grad_dv,
        raw_gradient=DataValue(value=getattr(schema, "raw_gradient_pct", None), unit="%", provenance=prov) if getattr(schema, "raw_gradient_pct", None) is not None else None,
        gradient_is_clamped=getattr(schema, "gradient_is_clamped", False),
        road_type=DataValue(value=schema.road_type, unit=None, provenance=prov),
        raw_road_class=getattr(schema, "raw_road_class", None),
        road_condition=DataValue.unknown(unit=None, notes="Surface condition not collected in legacy schema"),
    )


def segment_domain_to_schema(domain: RouteSegmentDomain) -> RouteSegmentSchema:
    """Convert RouteSegmentDomain back to legacy RouteSegment schema while preserving UNKNOWN status."""
    rtype = domain.road_type.value if domain.road_type.value in ("highway", "urban", "rural") else "highway"

    is_grad_unknown = (
        domain.gradient.provenance.status == DataStatus.UNKNOWN
        or domain.gradient.value is None
    )
    grad_val = None if is_grad_unknown else domain.gradient.value
    grad_status = "UNKNOWN" if is_grad_unknown else domain.gradient.provenance.status.value
    raw_grad_val = domain.raw_gradient.value if (domain.raw_gradient and domain.raw_gradient.value is not None) else None
    speed_lim = domain.speed_limit.value if (domain.speed_limit and domain.speed_limit.value is not None) else None

    return RouteSegmentSchema(
        segment_id=domain.segment_id,
        distance_km=domain.distance.value or 1.0,
        avg_speed_kmh=domain.speed.value or 60.0,
        gradient_pct=grad_val,
        gradient_status=grad_status,
        gradient_is_clamped=domain.gradient_is_clamped,
        raw_gradient_pct=raw_grad_val,
        speed_limit_kmh=speed_lim,
        road_type=rtype,  # type: ignore
        raw_road_class=domain.raw_road_class,
        name=domain.name,
    )


def charger_schema_to_domain(
    schema: ChargerSchema,
    status: DataStatus = DataStatus.SIMULATED,
    source_name: str = "Demo Charger Network",
) -> ChargingStationDomain:
    """Convert a legacy Charger schema to a rich ChargingStationDomain."""
    prov = DataProvenance(
        status=status,
        source_name=source_name,
        source_type=SourceType.SYNTHETIC_SIMULATION,
        notes="Converted from legacy Charger schema",
    )

    connectors = [
        ConnectorDomain(
            connector_type=ct,
            rated_power_kw=DataValue(value=schema.max_power_kw, unit="kW", provenance=prov),
            is_operational=DataValue(value=True, unit=None, provenance=prov),
            provenance=prov,
        )
        for ct in schema.connector_types
    ]

    return ChargingStationDomain(
        station_id=schema.charger_id,
        name=DataValue(value=schema.name, unit=None, provenance=prov),
        coordinates=DataValue(value=(schema.lat, schema.lng), unit="deg", provenance=prov),
        address=schema.address,
        operator=DataValue(value=schema.operator, unit=None, provenance=prov),
        connectors=connectors,
        max_power_kw=DataValue(value=schema.max_power_kw, unit="kW", provenance=prov),
        available_ports=DataValue(value=len(schema.connector_types), unit="ports", provenance=prov),
        is_operational=DataValue(
            value=schema.is_operational if schema.is_operational is not None else True,
            unit=None,
            provenance=prov,
        ),
        reliability_score=DataValue(
            value=schema.reliability_score,
            unit="fraction",
            provenance=DataProvenance(
                status=DataStatus.ESTIMATED,
                source_name="Laplace Smoothed Beta Posterior",
                source_type=SourceType.STATISTICAL_INFERENCE,
            ),
        ),
        provenance=prov,
    )


def charger_domain_to_schema(domain: ChargingStationDomain) -> ChargerSchema:
    """Convert ChargingStationDomain back to legacy Charger schema."""
    lat, lng = domain.coordinates.value if domain.coordinates.value else (0.0, 0.0)
    connectors = [c.connector_type for c in domain.connectors]
    return ChargerSchema(
        charger_id=domain.station_id,
        name=domain.name.value or "Unknown Station",
        lat=lat,
        lng=lng,
        connector_types=connectors or [ConnectorType.CCS2],
        max_power_kw=domain.max_power_kw.value or 50.0,
        operator=domain.operator.value or "Unknown Operator",
        reliability_score=domain.reliability_score.value or 0.5,
        is_operational=domain.is_operational.value,
        address=domain.address,
    )
