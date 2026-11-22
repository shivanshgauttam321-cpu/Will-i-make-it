"""
Deterministic Longitudinal Vehicle Physics Engine
==================================================
Calculates exact road loads, rotational inertia, signed aerodynamic forces,
and mechanical wheel power for EV powertrain analysis.

Units:
- Mass: kg
- Force: N
- Power: kW
- Speed: m/s
- Acceleration: m/s²
- Angle: radians
"""
from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Optional

from app.domain.provenance import DataStatus
from app.services.energy.environment_model import (
    GRAVITY_M_S2,
    _validate_finite,
    compute_air_density,
    compute_apparent_wind,
    compute_auxiliary_power,
    AirDensityResult,
    ApparentWindResult,
    AuxiliaryPowerResult,
    AuxiliaryConfig,
    HVACMode,
)


@dataclass(frozen=True)
class RollingResistanceResult:
    """Tire-road rolling resistance force and normal force decomposition."""
    force_n: float
    normal_force_n: float
    grade_angle_rad: float
    is_gradient_unknown: bool
    is_surface_unverified: bool
    c_rr_used: float
    raw_surface_tag: Optional[str]
    raw_smoothness_tag: Optional[str]


@dataclass(frozen=True)
class AerodynamicDragResult:
    """Aerodynamic drag force with signed apparent airspeed preservation."""
    force_n: float
    apparent_speed_ms: float
    air_density_kg_m3: float
    status: DataStatus
    input_status: Optional[DataStatus]


@dataclass(frozen=True)
class GradientForceResult:
    """Exact gravitational gradient force along road slope."""
    force_n: float
    is_gradient_unknown: bool
    grade_angle_rad: float


@dataclass(frozen=True)
class TractiveForceResult:
    """Aggregated longitudinal forces, inertia, and mechanical wheel power."""
    f_total_n: float
    f_roll_n: float
    f_aero_n: float
    f_grade_n: float
    f_inertial_n: float
    p_wheel_kw: float
    effective_mass_kg: float
    total_mass_kg: float
    is_gradient_unknown: bool
    is_wind_unknown: bool
    is_surface_unverified: bool
    status: DataStatus


def compute_rolling_resistance(
    total_mass_kg: float,
    base_crr: float = 0.010,
    gradient_pct: Optional[float] = None,
    surface_tag: Optional[str] = None,
    smoothness_tag: Optional[str] = None,
) -> RollingResistanceResult:
    """
    Computes tire rolling resistance force without small-angle approximations.
    Uses neutral 1.0 multiplier for uncalibrated surfaces and marks uncertainty.
    """
    _validate_finite("total_mass_kg", total_mass_kg, 200.0, 45000.0)
    _validate_finite("base_crr", base_crr, 0.002, 0.060)
    _validate_finite("gradient_pct", gradient_pct, -40.0, 40.0)

    is_grad_unknown = (gradient_pct is None)
    theta = 0.0 if is_grad_unknown else math.atan(gradient_pct / 100.0)

    # In Step B, without an empirically validated Indian road surface dynamometer table,
    # road surface contribution remains unverified (neutral 1.0 multiplier applied)
    # even when raw OSM/user surface tags are present.
    is_surface_unverified = True
    c_rr_eff = base_crr * 1.0 * 1.0

    f_normal = total_mass_kg * GRAVITY_M_S2 * math.cos(theta)
    f_roll = c_rr_eff * f_normal

    return RollingResistanceResult(
        force_n=f_roll,
        normal_force_n=f_normal,
        grade_angle_rad=theta,
        is_gradient_unknown=is_grad_unknown,
        is_surface_unverified=is_surface_unverified,
        c_rr_used=c_rr_eff,
        raw_surface_tag=surface_tag,
        raw_smoothness_tag=smoothness_tag,
    )


def compute_aerodynamic_drag(
    frontal_area_m2: float,
    drag_coefficient_cd: float,
    apparent_airspeed_ms: float,
    air_density_kg_m3: float,
    input_status: Optional[DataStatus] = None,
) -> AerodynamicDragResult:
    """
    Computes signed aerodynamic drag force:
    F_aero = 0.5 * rho * Cd * A * abs(v_app) * v_app
    Preserves negative aerodynamic drag (propulsive force) under strong tailwinds.
    """
    _validate_finite("frontal_area_m2", frontal_area_m2, 0.50, 12.0)
    _validate_finite("drag_coefficient_cd", drag_coefficient_cd, 0.10, 1.20)
    _validate_finite("apparent_airspeed_ms", apparent_airspeed_ms, -150.0, 150.0)
    _validate_finite("air_density_kg_m3", air_density_kg_m3, 0.30, 1.80)

    # SIGNED AERODYNAMIC FORCE
    f_aero = 0.5 * air_density_kg_m3 * drag_coefficient_cd * frontal_area_m2 * abs(apparent_airspeed_ms) * apparent_airspeed_ms

    return AerodynamicDragResult(
        force_n=f_aero,
        apparent_speed_ms=apparent_airspeed_ms,
        air_density_kg_m3=air_density_kg_m3,
        status=DataStatus.ESTIMATED,
        input_status=input_status,
    )


def compute_gradient_force(
    total_mass_kg: float,
    gradient_pct: Optional[float] = None,
) -> GradientForceResult:
    """
    Computes exact gravitational grade force:
    F_grade = m * g * sin(theta)
    """
    _validate_finite("total_mass_kg", total_mass_kg, 200.0, 45000.0)
    _validate_finite("gradient_pct", gradient_pct, -40.0, 40.0)

    if gradient_pct is None:
        return GradientForceResult(
            force_n=0.0,
            is_gradient_unknown=True,
            grade_angle_rad=0.0,
        )

    theta = math.atan(gradient_pct / 100.0)
    f_grade = total_mass_kg * GRAVITY_M_S2 * math.sin(theta)

    return GradientForceResult(
        force_n=f_grade,
        is_gradient_unknown=False,
        grade_angle_rad=theta,
    )


def compute_tractive_force(
    total_mass_kg: float,
    frontal_area_m2: float,
    drag_coefficient_cd: float,
    vehicle_speed_ms: float,
    acceleration_ms2: float = 0.0,
    rotational_inertia_factor: float = 0.05,
    effective_mass_kg: Optional[float] = None,
    gradient_pct: Optional[float] = None,
    air_density_kg_m3: float = 1.20,
    wind: Optional[ApparentWindResult] = None,
    apparent_airspeed_ms: Optional[float] = None,
    is_wind_unknown: Optional[bool] = None,
    base_crr: float = 0.010,
    surface_tag: Optional[str] = None,
    smoothness_tag: Optional[str] = None,
    input_status: Optional[DataStatus] = None,
) -> TractiveForceResult:
    """
    Aggregates longitudinal forces, rotational inertia, and mechanical wheel power.
    Validates effective_mass_kg >= total_mass_kg and propagates unknown wind/gradient status.
    Requires complete ApparentWindResult or explicit is_wind_unknown when passing apparent_airspeed_ms.
    """
    _validate_finite("total_mass_kg", total_mass_kg, 200.0, 45000.0)
    _validate_finite("vehicle_speed_ms", vehicle_speed_ms, 0.0, 100.0)
    _validate_finite("acceleration_ms2", acceleration_ms2, -15.0, 15.0)
    _validate_finite("rotational_inertia_factor", rotational_inertia_factor, 0.0, 0.30)
    _validate_finite("effective_mass_kg", effective_mass_kg, 200.0, 60000.0)

    # Validate effective mass vs total mass
    if effective_mass_kg is not None:
        if effective_mass_kg < total_mass_kg:
            raise ValueError(
                f"effective_mass_kg ({effective_mass_kg}) must be greater than or equal to "
                f"total_mass_kg ({total_mass_kg})"
            )
        m_eff = float(effective_mass_kg)
    else:
        m_eff = total_mass_kg * (1.0 + rotational_inertia_factor)

    # Resolve aerodynamic airspeed and wind uncertainty
    if wind is not None:
        v_aero = wind.apparent_airspeed_ms
        wind_unknown = wind.is_wind_unknown
        wind_input_status = wind.input_status or input_status
    elif apparent_airspeed_ms is not None:
        if is_wind_unknown is None:
            raise ValueError(
                "is_wind_unknown must be explicitly specified (True or False) when apparent_airspeed_ms is provided numerically"
            )
        v_aero = apparent_airspeed_ms
        wind_unknown = is_wind_unknown
        wind_input_status = input_status
    else:
        # No wind supplied: default to calm ground speed with wind marked unknown
        v_aero = vehicle_speed_ms
        wind_unknown = True
        wind_input_status = input_status

    res_roll = compute_rolling_resistance(
        total_mass_kg=total_mass_kg,
        base_crr=base_crr,
        gradient_pct=gradient_pct,
        surface_tag=surface_tag,
        smoothness_tag=smoothness_tag,
    )
    res_aero = compute_aerodynamic_drag(
        frontal_area_m2=frontal_area_m2,
        drag_coefficient_cd=drag_coefficient_cd,
        apparent_airspeed_ms=v_aero,
        air_density_kg_m3=air_density_kg_m3,
        input_status=wind_input_status,
    )
    res_grade = compute_gradient_force(
        total_mass_kg=total_mass_kg,
        gradient_pct=gradient_pct,
    )
    f_inertial = m_eff * acceleration_ms2

    f_total = res_roll.force_n + res_aero.force_n + res_grade.force_n + f_inertial
    p_wheel_kw = (f_total * vehicle_speed_ms) / 1000.0

    derived_status = DataStatus.UNKNOWN if (res_roll.is_gradient_unknown or wind_unknown) else DataStatus.ESTIMATED

    return TractiveForceResult(
        f_total_n=f_total,
        f_roll_n=res_roll.force_n,
        f_aero_n=res_aero.force_n,
        f_grade_n=res_grade.force_n,
        f_inertial_n=f_inertial,
        p_wheel_kw=p_wheel_kw,
        effective_mass_kg=m_eff,
        total_mass_kg=total_mass_kg,
        is_gradient_unknown=res_roll.is_gradient_unknown,
        is_wind_unknown=wind_unknown,
        is_surface_unverified=res_roll.is_surface_unverified,
        status=derived_status,
    )
