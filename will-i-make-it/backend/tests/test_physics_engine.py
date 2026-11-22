"""
Test Suite for Deterministic Physics Engine & Environmental Model
=================================================================
Validates Phase 3.1 Step B implementations:
- Signed aerodynamic drag (headwinds vs tailwinds)
- Rotational inertia & effective mass
- Meteorological wind decomposition & signed crosswinds
- HVAC operational states and baseline assumptions
- Physical-bounds and IEEE-754 finite value validation
- Provenance tracking and uncertainty propagation
"""
import math
import pytest

from app.domain.provenance import DataStatus
from app.services.energy.environment_model import (
    compute_air_density,
    compute_apparent_wind,
    compute_auxiliary_power,
    AuxiliaryConfig,
    HVACMode,
)
from app.services.energy.physics_engine import (
    compute_rolling_resistance,
    compute_aerodynamic_drag,
    compute_gradient_force,
    compute_tractive_force,
)


# ==============================================================================
# 1. SIGNED AERODYNAMICS & TAILWIND TESTS
# ==============================================================================

def test_signed_aerodynamic_drag_tailwind():
    """
    Mandatory Test:
    - Vehicle speed: 10 m/s
    - Vehicle heading: North (0.0°)
    - Wind FROM: South (180.0°)
    - Wind speed: 15 m/s
    - Expected apparent longitudinal airspeed: -5.0 m/s
    - Expected aerodynamic force: negative (propulsive thrust)
    """
    wind_res = compute_apparent_wind(
        vehicle_speed_ms=10.0,
        vehicle_heading_deg=0.0,
        wind_speed_ms=15.0,
        wind_direction_from_deg=180.0,
    )
    assert wind_res.apparent_airspeed_ms == pytest.approx(-5.0, abs=1e-5)
    assert wind_res.crosswind_ms == pytest.approx(0.0, abs=1e-5)
    assert wind_res.is_wind_unknown is False

    # Aerodynamic drag computation
    rho = 1.20
    cd = 0.28
    frontal_area = 2.2
    aero_res = compute_aerodynamic_drag(
        frontal_area_m2=frontal_area,
        drag_coefficient_cd=cd,
        apparent_airspeed_ms=wind_res.apparent_airspeed_ms,
        air_density_kg_m3=rho,
    )

    # Expected: 0.5 * 1.20 * 0.28 * 2.2 * |-5| * (-5) = -9.24 N
    expected_f_aero = 0.5 * rho * cd * frontal_area * abs(-5.0) * (-5.0)
    assert expected_f_aero < 0.0
    assert aero_res.force_n == pytest.approx(expected_f_aero, abs=1e-5)
    assert aero_res.force_n == pytest.approx(-9.24, abs=1e-2)


def test_signed_aerodynamic_drag_headwind():
    """
    Headwind test:
    - Vehicle speed: 10 m/s
    - Vehicle heading: North (0.0°)
    - Wind FROM: North (0.0°)
    - Wind speed: 15 m/s
    - Expected apparent airspeed: +25.0 m/s
    - Expected aerodynamic drag: positive (opposing motion)
    """
    wind_res = compute_apparent_wind(
        vehicle_speed_ms=10.0,
        vehicle_heading_deg=0.0,
        wind_speed_ms=15.0,
        wind_direction_from_deg=0.0,
    )
    assert wind_res.apparent_airspeed_ms == pytest.approx(25.0, abs=1e-5)

    aero_res = compute_aerodynamic_drag(
        frontal_area_m2=2.2,
        drag_coefficient_cd=0.28,
        apparent_airspeed_ms=wind_res.apparent_airspeed_ms,
        air_density_kg_m3=1.20,
    )
    # Expected: 0.5 * 1.20 * 0.28 * 2.2 * 25^2 = +231.0 N
    assert aero_res.force_n == pytest.approx(231.0, abs=1e-2)
    assert aero_res.force_n > 0.0


def test_signed_crosswind_vector():
    """
    Signed crosswind test:
    - Wind FROM 90° (East) when heading 0° (North) -> wind from starboard/right (+crosswind)
    - Wind FROM 270° (West) when heading 0° (North) -> wind from port/left (-crosswind)
    """
    res_east = compute_apparent_wind(
        vehicle_speed_ms=15.0,
        vehicle_heading_deg=0.0,
        wind_speed_ms=10.0,
        wind_direction_from_deg=90.0,
    )
    assert res_east.apparent_airspeed_ms == pytest.approx(15.0, abs=1e-5)
    assert res_east.crosswind_ms == pytest.approx(10.0, abs=1e-5)

    res_west = compute_apparent_wind(
        vehicle_speed_ms=15.0,
        vehicle_heading_deg=0.0,
        wind_speed_ms=10.0,
        wind_direction_from_deg=270.0,
    )
    assert res_west.apparent_airspeed_ms == pytest.approx(15.0, abs=1e-5)
    assert res_west.crosswind_ms == pytest.approx(-10.0, abs=1e-5)


# ==============================================================================
# 2. ROTATIONAL INERTIA & EFFECTIVE MASS TESTS
# ==============================================================================

def test_rotational_inertia_and_effective_mass():
    """
    Validates rotational inertia factor lambda_rot and effective mass handling.
    """
    mass = 1600.0
    lambda_rot = 0.05
    # Default effective mass: 1600 * 1.05 = 1680 kg
    res = compute_tractive_force(
        total_mass_kg=mass,
        frontal_area_m2=2.2,
        drag_coefficient_cd=0.28,
        vehicle_speed_ms=20.0,
        acceleration_ms2=2.0,
        rotational_inertia_factor=lambda_rot,
    )
    assert res.effective_mass_kg == pytest.approx(1680.0, abs=1e-5)
    assert res.total_mass_kg == 1600.0
    assert res.f_inertial_n == pytest.approx(1680.0 * 2.0, abs=1e-5)

    # Custom effective mass override
    res_override = compute_tractive_force(
        total_mass_kg=mass,
        frontal_area_m2=2.2,
        drag_coefficient_cd=0.28,
        vehicle_speed_ms=20.0,
        acceleration_ms2=2.0,
        effective_mass_kg=1750.0,
    )
    assert res_override.effective_mass_kg == 1750.0
    assert res_override.f_inertial_n == pytest.approx(1750.0 * 2.0, abs=1e-5)

    # Rejection of invalid effective mass (effective_mass < total_mass)
    with pytest.raises(ValueError, match="must be greater than or equal to total_mass_kg"):
        compute_tractive_force(
            total_mass_kg=1600.0,
            frontal_area_m2=2.2,
            drag_coefficient_cd=0.28,
            vehicle_speed_ms=20.0,
            acceleration_ms2=1.0,
            effective_mass_kg=1500.0,
        )


# ==============================================================================
# 3. HVAC STATES & POWER CONSUMPTION TESTS
# ==============================================================================

def test_hvac_modes_and_power():
    """
    Validates the 5 explicit HVAC states and baseline models.
    """
    cfg = AuxiliaryConfig(
        p_base_kw=0.30,
        p_vent_kw=0.05,
        p_cool_base_kw=0.40,
        p_heat_base_kw=0.50,
        k_cool_kw_per_c=0.08,
        k_heat_kw_per_c=0.10,
        p_hvac_max_kw=3.50,
        cooling_threshold_c=24.0,
        heating_threshold_c=18.0,
        nominal_unknown_kw=0.50,
    )

    # 1. HVAC DISABLED
    res_disabled = compute_auxiliary_power(ambient_temp_c=35.0, hvac_enabled=False, config=cfg)
    assert res_disabled.hvac_mode == HVACMode.DISABLED
    assert res_disabled.hvac_power_kw == 0.0
    assert res_disabled.total_aux_power_kw == pytest.approx(0.30, abs=1e-5)
    assert res_disabled.is_hvac_estimated is False

    # 2. VENTILATION ONLY (Comfort deadband 18°C - 24°C)
    res_vent = compute_auxiliary_power(ambient_temp_c=21.0, hvac_enabled=True, config=cfg)
    assert res_vent.hvac_mode == HVACMode.VENTILATION_ONLY
    assert res_vent.hvac_power_kw == pytest.approx(0.05, abs=1e-5)
    assert res_vent.total_aux_power_kw == pytest.approx(0.35, abs=1e-5)

    # 3. COOLING (Indian summer 40°C)
    # Expected HVAC: 0.40 + 0.08 * (40 - 24) = 0.40 + 1.28 = 1.68 kW
    res_cool = compute_auxiliary_power(ambient_temp_c=40.0, hvac_enabled=True, config=cfg)
    assert res_cool.hvac_mode == HVACMode.COOLING
    assert res_cool.hvac_power_kw == pytest.approx(1.68, abs=1e-5)
    assert res_cool.total_aux_power_kw == pytest.approx(1.98, abs=1e-5)

    # 4. HEATING (Cold winter 8°C)
    # Expected HVAC: 0.50 + 0.10 * (18 - 8) = 0.50 + 1.00 = 1.50 kW
    res_heat = compute_auxiliary_power(ambient_temp_c=8.0, hvac_enabled=True, config=cfg)
    assert res_heat.hvac_mode == HVACMode.HEATING
    assert res_heat.hvac_power_kw == pytest.approx(1.50, abs=1e-5)
    assert res_heat.total_aux_power_kw == pytest.approx(1.80, abs=1e-5)

    # 5. UNKNOWN (Ambient temperature is None)
    res_unknown = compute_auxiliary_power(ambient_temp_c=None, hvac_enabled=True, config=cfg)
    assert res_unknown.hvac_mode == HVACMode.UNKNOWN
    assert res_unknown.hvac_power_kw == pytest.approx(0.50, abs=1e-5)
    assert res_unknown.total_aux_power_kw == pytest.approx(0.80, abs=1e-5)
    assert res_unknown.status == DataStatus.UNKNOWN


# ==============================================================================
# 4. ATMOSPHERIC DENSITY & LAPSE RATE TESTS
# ==============================================================================

def test_air_density_barometric():
    """
    Validates air density calculation across sea level and high altitudes.
    """
    # Standard sea level at 25°C: rho = 101325 / (287.058 * 298.15) ≈ 1.1839 kg/m³
    res_sea = compute_air_density(elevation_m=0.0, ambient_temp_c=25.0)
    assert res_sea.density_kg_m3 == pytest.approx(1.1839, abs=1e-3)
    assert res_sea.is_standard_atmosphere is False

    # Default fallback when elevation is None
    res_fallback = compute_air_density(elevation_m=None, ambient_temp_c=25.0)
    assert res_fallback.is_standard_atmosphere is True
    assert res_fallback.elevation_used_m == 0.0

    # High altitude: Leh, Ladakh (3500 m) at 5°C
    res_leh = compute_air_density(elevation_m=3500.0, ambient_temp_c=5.0)
    assert res_leh.density_kg_m3 < 0.85
    assert res_leh.density_kg_m3 > 0.75


# ==============================================================================
# 5. ROLLING RESISTANCE & GRADIENT TESTS
# ==============================================================================

def test_rolling_resistance_and_normal_force():
    """
    Validates trigonometric normal force decomposition and unverified surface flag.
    """
    mass = 2000.0
    crr = 0.012

    # Flat road (0%)
    res_flat = compute_rolling_resistance(
        total_mass_kg=mass,
        base_crr=crr,
        gradient_pct=0.0,
        surface_tag="asphalt",
        smoothness_tag="good",
    )
    expected_f_normal = mass * 9.80665
    assert res_flat.normal_force_n == pytest.approx(expected_f_normal, abs=1e-4)
    assert res_flat.force_n == pytest.approx(crr * expected_f_normal, abs=1e-4)
    assert res_flat.is_gradient_unknown is False
    assert res_flat.is_surface_unverified is True  # Audit requirement: remains unverified

    # Steep 20% incline
    res_steep = compute_rolling_resistance(total_mass_kg=mass, base_crr=crr, gradient_pct=20.0)
    theta = math.atan(0.20)
    assert res_steep.grade_angle_rad == pytest.approx(theta, abs=1e-6)
    assert res_steep.normal_force_n == pytest.approx(mass * 9.80665 * math.cos(theta), abs=1e-4)
    assert res_steep.normal_force_n < expected_f_normal

    # Unknown gradient
    res_unknown = compute_rolling_resistance(total_mass_kg=mass, base_crr=crr, gradient_pct=None)
    assert res_unknown.is_gradient_unknown is True
    assert res_unknown.grade_angle_rad == 0.0


def test_gradient_force():
    """
    Validates exact gravitational force on grade: F_grade = m * g * sin(theta).
    """
    mass = 1800.0
    g = 9.80665

    # 10% grade
    res_10 = compute_gradient_force(total_mass_kg=mass, gradient_pct=10.0)
    theta = math.atan(0.10)
    expected_f = mass * g * math.sin(theta)
    assert res_10.force_n == pytest.approx(expected_f, abs=1e-4)
    assert res_10.is_gradient_unknown is False

    # Negative grade (downhill -10%)
    res_downhill = compute_gradient_force(total_mass_kg=mass, gradient_pct=-10.0)
    assert res_downhill.force_n == pytest.approx(-expected_f, abs=1e-4)

    # Missing gradient (None)
    res_none = compute_gradient_force(total_mass_kg=mass, gradient_pct=None)
    assert res_none.force_n == 0.0
    assert res_none.is_gradient_unknown is True


# ==============================================================================
# 6. UNCERTAINTY & PROVENANCE PROPAGATION
# ==============================================================================

def test_tractive_force_provenance_and_uncertainty():
    """
    Validates propagation of unknown wind, unknown gradient, and input provenance.
    """
    # Case A: Unknown wind (apparent_airspeed_ms is None or is_wind_unknown is True)
    res_a = compute_tractive_force(
        total_mass_kg=1800.0,
        frontal_area_m2=2.3,
        drag_coefficient_cd=0.29,
        vehicle_speed_ms=15.0,
        gradient_pct=2.0,
        apparent_airspeed_ms=None,
    )
    assert res_a.is_wind_unknown is True
    assert res_a.status == DataStatus.UNKNOWN

    # Case B: Unknown gradient
    res_b = compute_tractive_force(
        total_mass_kg=1800.0,
        frontal_area_m2=2.3,
        drag_coefficient_cd=0.29,
        vehicle_speed_ms=15.0,
        gradient_pct=None,
        apparent_airspeed_ms=15.0,
        is_wind_unknown=False,
    )
    assert res_b.is_gradient_unknown is True
    assert res_b.status == DataStatus.UNKNOWN

    # Case C: Fully known inputs -> derived status ESTIMATED
    res_c = compute_tractive_force(
        total_mass_kg=1800.0,
        frontal_area_m2=2.3,
        drag_coefficient_cd=0.29,
        vehicle_speed_ms=15.0,
        gradient_pct=2.0,
        apparent_airspeed_ms=15.0,
        is_wind_unknown=False,
    )
    assert res_c.is_gradient_unknown is False
    assert res_c.is_wind_unknown is False
    assert res_c.status == DataStatus.ESTIMATED


# ==============================================================================
# 7. IEEE-754 FINITE & BOUNDS VALIDATION
# ==============================================================================

def test_ieee754_finite_and_bounds_rejection():
    """
    Validates rejection of NaN, inf, and physically out-of-bounds parameters.
    """
    # Mass bounds
    with pytest.raises(ValueError):
        compute_rolling_resistance(total_mass_kg=float("nan"))
    with pytest.raises(ValueError):
        compute_rolling_resistance(total_mass_kg=float("inf"))
    with pytest.raises(ValueError):
        compute_rolling_resistance(total_mass_kg=50.0)  # Too light (< 200 kg)

    # Speed bounds
    with pytest.raises(ValueError):
        compute_apparent_wind(vehicle_speed_ms=-1.0, vehicle_heading_deg=0.0)
    with pytest.raises(ValueError):
        compute_apparent_wind(vehicle_speed_ms=float("nan"), vehicle_heading_deg=0.0)

    # Air density bounds
    with pytest.raises(ValueError):
        compute_air_density(ambient_temp_c=-60.0)  # Out of bound (< -50°C)
    with pytest.raises(ValueError):
        compute_air_density(elevation_m=12000.0)   # Above 9000 m troposphere limit

    # AuxiliaryConfig validation
    with pytest.raises(ValueError):
        AuxiliaryConfig(p_base_kw=-0.1)
    with pytest.raises(ValueError):
        AuxiliaryConfig(cooling_threshold_c=15.0, heating_threshold_c=20.0)  # Inverted thresholds


# ==============================================================================
# 8. STEP B.1 TARGETED TESTS (AUDIT RESOLUTIONS)
# ==============================================================================

def test_auxiliary_config_temperature_thresholds():
    """
    Validates negative Celsius thresholds, ordering invariant, and NaN/inf rejection.
    """
    # 1. Physically valid negative heating threshold (sub-zero climate)
    cfg_cold = AuxiliaryConfig(heating_threshold_c=-5.0, cooling_threshold_c=18.0)
    assert cfg_cold.heating_threshold_c == -5.0
    res_heat = compute_auxiliary_power(ambient_temp_c=-10.0, hvac_enabled=True, config=cfg_cold)
    assert res_heat.hvac_mode == HVACMode.HEATING
    # Expected heating: 0.50 + 0.10 * (-5.0 - (-10.0)) = 0.50 + 0.50 = 1.00 kW
    assert res_heat.hvac_power_kw == pytest.approx(1.00, abs=1e-5)

    # 2. Both thresholds negative (cold storage / refrigerated compartment)
    cfg_freezer = AuxiliaryConfig(heating_threshold_c=-15.0, cooling_threshold_c=-5.0)
    assert cfg_freezer.cooling_threshold_c == -5.0
    assert cfg_freezer.heating_threshold_c == -15.0

    # 3. Invalid threshold ordering (cooling <= heating)
    with pytest.raises(ValueError, match="must be strictly greater than"):
        AuxiliaryConfig(heating_threshold_c=22.0, cooling_threshold_c=22.0)
    with pytest.raises(ValueError, match="must be strictly greater than"):
        AuxiliaryConfig(heating_threshold_c=25.0, cooling_threshold_c=20.0)

    # 4. NaN / Inf rejection on temperature thresholds
    with pytest.raises(ValueError, match="must be a finite numerical value"):
        AuxiliaryConfig(heating_threshold_c=float("nan"))
    with pytest.raises(ValueError, match="must be a finite numerical value"):
        AuxiliaryConfig(cooling_threshold_c=float("inf"))

    # 5. Out of physical bounds rejection (< -50°C or > 65°C)
    with pytest.raises(ValueError, match="outside physical bounds"):
        AuxiliaryConfig(heating_threshold_c=-60.0)
    with pytest.raises(ValueError, match="outside physical bounds"):
        AuxiliaryConfig(cooling_threshold_c=75.0)


def test_wind_uncertainty_propagation_and_rejection():
    """
    Validates:
    - Direct passing of ApparentWindResult propagates is_wind_unknown
    - Omission of is_wind_unknown when passing numeric apparent_airspeed_ms raises ValueError
    """
    # 1. Passing ApparentWindResult directly with UNKNOWN wind
    wind_unknown = compute_apparent_wind(
        vehicle_speed_ms=15.0,
        vehicle_heading_deg=0.0,
        wind_speed_ms=None,
    )
    assert wind_unknown.is_wind_unknown is True
    res_via_obj = compute_tractive_force(
        total_mass_kg=1800.0,
        frontal_area_m2=2.3,
        drag_coefficient_cd=0.29,
        vehicle_speed_ms=15.0,
        gradient_pct=0.0,
        wind=wind_unknown,
    )
    assert res_via_obj.is_wind_unknown is True
    assert res_via_obj.status == DataStatus.UNKNOWN

    # 2. Passing ApparentWindResult directly with KNOWN wind
    wind_known = compute_apparent_wind(
        vehicle_speed_ms=15.0,
        vehicle_heading_deg=0.0,
        wind_speed_ms=5.0,
        wind_direction_from_deg=0.0,
    )
    assert wind_known.is_wind_unknown is False
    res_known_obj = compute_tractive_force(
        total_mass_kg=1800.0,
        frontal_area_m2=2.3,
        drag_coefficient_cd=0.29,
        vehicle_speed_ms=15.0,
        gradient_pct=0.0,
        wind=wind_known,
    )
    assert res_known_obj.is_wind_unknown is False
    assert res_known_obj.status == DataStatus.ESTIMATED

    # 3. Numeric apparent_airspeed_ms provided without is_wind_unknown -> MUST raise ValueError
    with pytest.raises(ValueError, match="is_wind_unknown must be explicitly specified"):
        compute_tractive_force(
            total_mass_kg=1800.0,
            frontal_area_m2=2.3,
            drag_coefficient_cd=0.29,
            vehicle_speed_ms=15.0,
            apparent_airspeed_ms=15.0,
            # is_wind_unknown omitted!
        )


def test_zero_wind_speed_edge_case():
    """
    Validates that wind_speed_ms=0.0 is treated as known calm wind (is_wind_unknown=False)
    even if wind_direction_from_deg is None.
    Also validates rejection of negative wind speed.
    """
    # Calm wind with undefined direction
    res_calm = compute_apparent_wind(
        vehicle_speed_ms=20.0,
        vehicle_heading_deg=45.0,
        wind_speed_ms=0.0,
        wind_direction_from_deg=None,
    )
    assert res_calm.apparent_airspeed_ms == 20.0
    assert res_calm.crosswind_ms == 0.0
    assert res_calm.is_wind_unknown is False
    assert res_calm.status == DataStatus.ESTIMATED

    # Negative wind speed rejection
    with pytest.raises(ValueError, match="outside physical bounds"):
        compute_apparent_wind(
            vehicle_speed_ms=20.0,
            vehicle_heading_deg=45.0,
            wind_speed_ms=-2.0,
        )


def test_negative_wheel_power_steep_descent():
    """
    Validates negative tractive force and negative wheel power during steep regenerative descent.
    """
    res = compute_tractive_force(
        total_mass_kg=2000.0,
        frontal_area_m2=2.2,
        drag_coefficient_cd=0.28,
        vehicle_speed_ms=15.0,
        gradient_pct=-15.0,  # 15% downhill
        apparent_airspeed_ms=15.0,
        is_wind_unknown=False,
    )
    # Gravitational downhill pull exceeds rolling + aerodynamic resistance
    assert res.f_grade_n < 0.0
    assert res.f_total_n < 0.0
    assert res.p_wheel_kw < 0.0


def test_zero_vehicle_speed_wheel_power():
    """
    Validates that stationary vehicle (v = 0.0 m/s) produces strictly 0.0 kW wheel power.
    """
    res = compute_tractive_force(
        total_mass_kg=1800.0,
        frontal_area_m2=2.2,
        drag_coefficient_cd=0.28,
        vehicle_speed_ms=0.0,
        acceleration_ms2=0.0,
        gradient_pct=0.0,
    )
    assert res.p_wheel_kw == 0.0
    assert res.f_roll_n > 0.0


def test_normal_force_unaffected_by_rotational_inertia():
    """
    Validates that normal force and gravitational grade force are strictly invariant
    with respect to rotational inertia factor lambda_rot.
    """
    res_zero_rot = compute_tractive_force(
        total_mass_kg=2000.0,
        frontal_area_m2=2.2,
        drag_coefficient_cd=0.28,
        vehicle_speed_ms=15.0,
        acceleration_ms2=2.0,
        gradient_pct=10.0,
        rotational_inertia_factor=0.0,
        apparent_airspeed_ms=15.0,
        is_wind_unknown=False,
    )
    res_high_rot = compute_tractive_force(
        total_mass_kg=2000.0,
        frontal_area_m2=2.2,
        drag_coefficient_cd=0.28,
        vehicle_speed_ms=15.0,
        acceleration_ms2=2.0,
        gradient_pct=10.0,
        rotational_inertia_factor=0.25,
        apparent_airspeed_ms=15.0,
        is_wind_unknown=False,
    )
    assert res_zero_rot.f_roll_n == pytest.approx(res_high_rot.f_roll_n, abs=1e-5)
    assert res_zero_rot.f_grade_n == pytest.approx(res_high_rot.f_grade_n, abs=1e-5)
    assert res_high_rot.f_inertial_n > res_zero_rot.f_inertial_n
    assert res_high_rot.f_inertial_n == pytest.approx(2000.0 * 1.25 * 2.0, abs=1e-5)


def test_upstream_real_provenance_retained_separately():
    """
    Validates that upstream DataStatus.REAL is preserved in input_status
    while derived calculation status remains DataStatus.ESTIMATED.
    """
    res_density = compute_air_density(
        elevation_m=200.0,
        ambient_temp_c=20.0,
        input_status=DataStatus.REAL,
    )
    assert res_density.status == DataStatus.ESTIMATED
    assert res_density.input_status == DataStatus.REAL

    res_wind = compute_apparent_wind(
        vehicle_speed_ms=10.0,
        vehicle_heading_deg=0.0,
        wind_speed_ms=5.0,
        wind_direction_from_deg=0.0,
        input_status=DataStatus.REAL,
    )
    assert res_wind.status == DataStatus.ESTIMATED
    assert res_wind.input_status == DataStatus.REAL

