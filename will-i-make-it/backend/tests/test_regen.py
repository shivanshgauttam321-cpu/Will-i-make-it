"""
Test Suite for Regenerative Braking & Inverter Electrical Acceptance (Stage C2.1)
=================================================================================
Validates C2.1 targeted engineering corrections:
1. Inverter DC current boundary: gross bridge current vs signed net HV bus current.
2. BMS hardware acceptance certainty: independent power/current availability and overall verification.
3. Missing hardware constraints: systematic audit ensuring CONDITIONAL status without defaults.
4. Provenance improvements: expanded regression tests for all individual parameter degradations.
5. Diagnostic arbitration: floating-point tolerance and structured active constraint tracking.
6. Energy conservation ledger evaluated strictly on DELIVERED quantities across all 4 regimes.
7. Aggregate tire-road adhesion limit evaluated on delivered force.
8. Low-speed rolloff, standstill safety, and non-negative losses.
9. Hand-calculated independent numerical reference cases.
"""
from __future__ import annotations

import math
import pytest

from app.domain.provenance import DataStatus
from app.services.energy.powertrain_model import (
    ConstraintStatus,
    GearboxConfig,
    MotorConfig,
    OperatingEnvelopeMode,
    compute_motor_speed,
)
from app.services.energy.regen_model import (
    InverterElectricalConfig,
    BMSConfig,
    BrakeBlendingConfig,
    BMSAcceptanceResult,
    AuxiliaryHVResult,
    BrakeBlendingResult,
    compute_low_speed_regen_factor,
    compute_auxiliary_hv_power,
    compute_bms_acceptance,
    blend_regenerative_and_friction_braking,
)


@pytest.fixture
def default_motor() -> MotorConfig:
    return MotorConfig(
        torque_cont_max_nm=145.0,
        power_cont_max_kw=65.0,
        max_speed_rpm=12000.0,
        torque_peak_max_nm=245.0,
        power_peak_max_kw=115.0,
        pole_pairs=4,
        flux_linkage_wb=0.076603,
        stator_resistance_ohm=0.020,
        k_t_rms=0.650,
        governor_rolloff_fraction=0.05,
        efficiency_mot=0.92,
        efficiency_gen=0.92,
        inverter_current_limit_rms=350.0,
        inverter_dc_power_limit_kw=65.0,
        inverter_efficiency=0.95,
        inverter_standby_loss_w=0.0,
        inverter_loss_status=DataStatus.REAL,
        status=DataStatus.REAL,
    )


@pytest.fixture
def default_gearbox() -> GearboxConfig:
    return GearboxConfig(
        gear_ratio=9.05,
        efficiency_fwd=0.97,
        efficiency_rev=0.96,
        wheel_radius_m=0.315,
        status=DataStatus.REAL,
    )


@pytest.fixture
def default_inverter() -> InverterElectricalConfig:
    return InverterElectricalConfig(
        dc_voltage_nominal_v=350.0,
        dc_voltage_max_v=420.0,
        dc_voltage_min_v=250.0,
        dc_current_limit_a=250.0,
        dc_power_limit_kw=65.0,
        efficiency_regen=0.95,
        standby_loss_w=0.0,
        dc_dc_efficiency=0.92,
        dc_dc_efficiency_status=DataStatus.REAL,
        status=DataStatus.REAL,
    )


@pytest.fixture
def default_bms() -> BMSConfig:
    return BMSConfig(
        max_charge_power_kw=65.0,
        max_charge_current_a=200.0,
        pack_nominal_voltage_v=350.0,
        cell_max_voltage_v=4.20,
        soc_taper_start=0.80,
        soc_cutoff=0.98,
        temp_optimal_low_c=15.0,
        temp_optimal_high_c=35.0,
        temp_cold_cutoff_c=-10.0,
        temp_hot_cutoff_c=50.0,
        status=DataStatus.REAL,
    )


@pytest.fixture
def default_blending() -> BrakeBlendingConfig:
    return BrakeBlendingConfig(
        v_cutoff_ms=1.0,
        v_blend_start_ms=3.0,
        friction_brake_max_force_n=15000.0,
        default_adhesion_coefficient=None,
        status=DataStatus.REAL,
    )


# =============================================================================
# 1. CORRECTION A: SIGNED HV BUS & INVERTER STANDBY ACCOUNTING (4 REGIMES)
# =============================================================================

def test_signed_hv_bus_regime_1_substantial_regen(
    default_motor: MotorConfig,
    default_gearbox: GearboxConfig,
    default_inverter: InverterElectricalConfig,
    default_bms: BMSConfig,
    default_blending: BrakeBlendingConfig,
):
    """
    Regime 1: Regeneration exceeds inverter standby AND auxiliary demand.
    - Gross regen DC power: 25.17 kW
    - Inverter standby: 200 W (0.20 kW)
    - Aux HV demand: 0.46 kW LV / 0.92 = 0.50 kW HV
    - Net inverter DC to bus: 25.1712 - 0.20 = 24.9712 kW (> 0)
    - Net battery charging: 24.9712 - 0.50 = 24.4712 kW (> 0, CHARGING)
    """
    inv_standby = default_inverter.model_copy(update={"standby_loss_w": 200.0})

    res = blend_regenerative_and_friction_braking(
        requested_brake_force_n=1500.0,
        vehicle_speed_ms=20.0,
        motor_config=default_motor,
        gearbox_config=default_gearbox,
        inverter_config=inv_standby,
        bms_config=default_bms,
        blending_config=default_blending,
        aux_lv_power_kw=0.46,
        normal_force_n=15000.0,
        adhesion_coefficient=0.80,
    )

    assert res.inverter_dc_power_gross_kw > 20.0
    assert pytest.approx(res.inverter_standby_kw, rel=1e-6) == 0.20
    assert res.inverter_dc_power_net_kw > 0.0
    assert pytest.approx(res.inverter_dc_power_net_kw, rel=1e-5) == res.inverter_dc_power_gross_kw - 0.20
    assert res.net_battery_charging_kw > 0.0  # Charging
    assert pytest.approx(res.net_battery_charging_kw, rel=1e-5) == res.inverter_dc_power_net_kw - res.auxiliary_hv_power_kw
    assert abs(res.energy_residual_kw) < 1e-5


def test_signed_hv_bus_regime_2_regen_exceeds_standby_not_aux(
    default_motor: MotorConfig,
    default_gearbox: GearboxConfig,
    default_inverter: InverterElectricalConfig,
    default_bms: BMSConfig,
    default_blending: BrakeBlendingConfig,
):
    """
    Regime 2: Regeneration exceeds standby, but is less than auxiliary demand.
    - Demanded braking: light (100 N at 10 m/s -> 1.0 kW wheel power)
    - Gross regen DC power: 1.0 * 0.96 * 0.92 * 0.95 = 0.83904 kW
    - Inverter standby: 200 W (0.20 kW) -> Net inverter DC = 0.83904 - 0.20 = 0.63904 kW (> 0)
    - Aux HV demand: 0.92 kW LV / 0.92 = 1.00 kW HV
    - Net battery charging: 0.63904 - 1.00 = -0.36096 kW (< 0, DISCHARGING)
    """
    inv_standby = default_inverter.model_copy(update={"standby_loss_w": 200.0})

    res = blend_regenerative_and_friction_braking(
        requested_brake_force_n=100.0,
        vehicle_speed_ms=10.0,
        motor_config=default_motor,
        gearbox_config=default_gearbox,
        inverter_config=inv_standby,
        bms_config=default_bms,
        blending_config=default_blending,
        aux_lv_power_kw=0.92,
    )

    assert res.inverter_dc_power_gross_kw > 0.80
    assert res.inverter_dc_power_net_kw > 0.0  # Positive net inverter output
    assert res.net_battery_charging_kw < 0.0   # Negative net battery request (discharging)
    assert pytest.approx(res.net_battery_charging_kw, rel=1e-5) == res.inverter_dc_power_net_kw - res.auxiliary_hv_power_kw
    assert abs(res.energy_residual_kw) < 1e-5


def test_signed_hv_bus_regime_3_regen_below_standby(
    default_motor: MotorConfig,
    default_gearbox: GearboxConfig,
    default_inverter: InverterElectricalConfig,
    default_bms: BMSConfig,
    default_blending: BrakeBlendingConfig,
):
    """
    Regime 3: Regeneration is below standby consumption.
    - Demanded braking: very light (20 N at 5 m/s -> 0.10 kW wheel power)
    - Gross regen DC power: 0.10 * 0.96 * 0.92 * 0.95 = 0.0839 kW
    - Inverter standby: 300 W (0.30 kW)
    - Net inverter DC to bus: 0.0839 - 0.30 = -0.2161 kW (< 0, INVERTER DRAWS POWER FROM BUS)
    - Aux HV demand: 0.46 kW LV / 0.92 = 0.50 kW HV
    - Net battery charging: -0.2161 - 0.50 = -0.7161 kW (< 0, DISCHARGING to cover aux + standby deficit)
    - Must NOT clamp inverter net output to 0.0!
    """
    inv_standby = default_inverter.model_copy(update={"standby_loss_w": 300.0})

    res = blend_regenerative_and_friction_braking(
        requested_brake_force_n=20.0,
        vehicle_speed_ms=5.0,
        motor_config=default_motor,
        gearbox_config=default_gearbox,
        inverter_config=inv_standby,
        bms_config=default_bms,
        blending_config=default_blending,
        aux_lv_power_kw=0.46,
    )

    assert res.inverter_dc_power_gross_kw < 0.10
    assert res.inverter_dc_power_net_kw < 0.0  # Net inverter output is NEGATIVE
    assert pytest.approx(res.inverter_dc_power_net_kw, rel=1e-5) == res.inverter_dc_power_gross_kw - 0.30
    assert res.net_battery_charging_kw < -0.50
    assert pytest.approx(res.net_battery_charging_kw, rel=1e-5) == res.inverter_dc_power_net_kw - res.auxiliary_hv_power_kw
    assert abs(res.energy_residual_kw) < 1e-5


def test_signed_hv_bus_regime_4_zero_regen_with_standby_and_aux(
    default_motor: MotorConfig,
    default_gearbox: GearboxConfig,
    default_inverter: InverterElectricalConfig,
    default_bms: BMSConfig,
    default_blending: BrakeBlendingConfig,
):
    """
    Regime 4: Zero regeneration available (standstill v = 0).
    - Gross regen DC power: 0.0 kW
    - Inverter standby: 250 W (0.25 kW)
    - Aux HV demand: 0.46 kW LV / 0.92 = 0.50 kW HV
    - Net inverter DC to bus: 0.0 - 0.25 = -0.25 kW (< 0)
    - Net battery charging: -0.25 - 0.50 = -0.75 kW (battery supplies full load)
    """
    inv_standby = default_inverter.model_copy(update={"standby_loss_w": 250.0})

    res = blend_regenerative_and_friction_braking(
        requested_brake_force_n=1000.0,
        vehicle_speed_ms=0.0,
        motor_config=default_motor,
        gearbox_config=default_gearbox,
        inverter_config=inv_standby,
        bms_config=default_bms,
        blending_config=default_blending,
        aux_lv_power_kw=0.46,
    )

    assert res.inverter_dc_power_gross_kw == 0.0
    assert pytest.approx(res.inverter_dc_power_net_kw, rel=1e-6) == -0.25
    assert pytest.approx(res.auxiliary_hv_power_kw, rel=1e-6) == 0.50
    assert pytest.approx(res.net_battery_charging_kw, rel=1e-6) == -0.75
    assert abs(res.energy_residual_kw) < 1e-5


# =============================================================================
# 2. TARGETED CORRECTION 1: INVERTER DC CURRENT BOUNDARY CORRECTION
# =============================================================================

def test_inverter_dc_current_gross_vs_net_boundary_distinction(
    default_motor: MotorConfig,
    default_gearbox: GearboxConfig,
    default_inverter: InverterElectricalConfig,
    default_bms: BMSConfig,
    default_blending: BrakeBlendingConfig,
):
    """
    Verify Correction 1:
    - I_gross = P_inv_dc_gross * 1000 / V_nominal (evaluated against bridge rating)
    - I_net = P_inv_dc_net * 1000 / V_nominal (signed current for HV bus accounting)
    - In Regime 1: I_gross > I_net > 0 (difference is exactly standby current)
    - In Regime 3: I_gross > 0, but I_net < 0 (drawing current from HV bus)
    - In Regime 4: I_gross == 0, I_net = -I_standby < 0
    """
    v_nom = 350.0
    p_standby_kw = 0.350  # 350 W -> 1.0 A at 350 V
    inv_standby = default_inverter.model_copy(update={"standby_loss_w": 350.0, "dc_voltage_nominal_v": v_nom})

    # Case 1: Substantial regen (Regime 1)
    res1 = blend_regenerative_and_friction_braking(
        requested_brake_force_n=1500.0, vehicle_speed_ms=20.0,
        motor_config=default_motor, gearbox_config=default_gearbox,
        inverter_config=inv_standby, bms_config=default_bms, blending_config=default_blending,
        normal_force_n=15000.0, adhesion_coefficient=0.80,
    )
    assert res1.inverter_dc_current_gross_a is not None
    assert res1.inverter_dc_current_net_a is not None
    assert res1.inverter_dc_current_gross_a > res1.inverter_dc_current_net_a
    assert pytest.approx(res1.inverter_dc_current_gross_a, rel=1e-5) == res1.inverter_dc_power_gross_kw * 1000.0 / v_nom
    assert pytest.approx(res1.inverter_dc_current_net_a, rel=1e-5) == res1.inverter_dc_power_net_kw * 1000.0 / v_nom
    assert pytest.approx(res1.inverter_dc_current_gross_a - res1.inverter_dc_current_net_a, rel=1e-5) == 1.0  # 350W / 350V = 1.0 A
    assert res1.inverter_dc_current_gross_a <= res1.inverter_dc_current_limit_a

    # Case 2: Regen below standby (Regime 3)
    res3 = blend_regenerative_and_friction_braking(
        requested_brake_force_n=20.0, vehicle_speed_ms=5.0,
        motor_config=default_motor, gearbox_config=default_gearbox,
        inverter_config=inv_standby, bms_config=default_bms, blending_config=default_blending,
    )
    assert res3.inverter_dc_current_gross_a > 0.0  # Generating small positive gross current at bridge
    assert res3.inverter_dc_current_net_a < 0.0    # Drawing net current from HV bus!
    assert pytest.approx(res3.inverter_dc_current_gross_a - res3.inverter_dc_current_net_a, rel=1e-5) == 1.0

    # Case 3: Standstill (Regime 4)
    res4 = blend_regenerative_and_friction_braking(
        requested_brake_force_n=1000.0, vehicle_speed_ms=0.0,
        motor_config=default_motor, gearbox_config=default_gearbox,
        inverter_config=inv_standby, bms_config=default_bms, blending_config=default_blending,
    )
    assert res4.inverter_dc_current_gross_a == 0.0
    assert pytest.approx(res4.inverter_dc_current_net_a, rel=1e-5) == -1.0


# =============================================================================
# 3. TARGETED CORRECTION 2: BMS HARDWARE ACCEPTANCE CERTAINTY
# =============================================================================

def test_bms_acceptance_certainty_independent_power_and_current(default_bms: BMSConfig):
    """
    Verify Correction 2:
    - Separates power-limit availability and current-limit availability.
    - is_limit_known is True ONLY when BOTH power and current limits are known.
    - An unknown BMS current limit reports CONDITIONAL status with explicit uncertainty.
    """
    # 1. Both known
    r_both = compute_bms_acceptance(0.50, 25.0, default_bms)
    assert r_both.is_power_limit_known is True
    assert r_both.is_current_limit_known is True
    assert r_both.is_limit_known is True
    assert r_both.admissible_charge_power_kw is not None
    assert r_both.admissible_charge_current_a is not None
    assert r_both.status == ConstraintStatus.SATISFIED

    # 2. Power known, Current unknown
    bms_no_curr = default_bms.model_copy(update={"max_charge_current_a": None})
    r_no_curr = compute_bms_acceptance(0.50, 25.0, bms_no_curr)
    assert r_no_curr.is_power_limit_known is True
    assert r_no_curr.is_current_limit_known is False
    assert r_no_curr.is_limit_known is False  # Must NOT represent as complete verification!
    assert pytest.approx(r_no_curr.admissible_charge_power_kw, rel=1e-5) == 65.0
    assert r_no_curr.admissible_charge_current_a is None
    assert r_no_curr.status == ConstraintStatus.CONDITIONAL
    assert "charge current limit unconfigured" in r_no_curr.notes

    # 3. Power unknown, Current known
    bms_no_pwr = default_bms.model_copy(update={"max_charge_power_kw": None})
    r_no_pwr = compute_bms_acceptance(0.50, 25.0, bms_no_pwr)
    assert r_no_pwr.is_power_limit_known is False
    assert r_no_pwr.is_current_limit_known is True
    assert r_no_pwr.is_limit_known is False
    assert r_no_pwr.admissible_charge_power_kw is None
    assert pytest.approx(r_no_pwr.admissible_charge_current_a, rel=1e-5) == 200.0
    assert r_no_pwr.status == ConstraintStatus.CONDITIONAL
    assert "charge power limit unconfigured" in r_no_pwr.notes


def test_bms_missing_current_limit_in_blending(
    default_motor: MotorConfig,
    default_gearbox: GearboxConfig,
    default_inverter: InverterElectricalConfig,
    default_bms: BMSConfig,
    default_blending: BrakeBlendingConfig,
):
    """
    Verify Correction 2 in blend_regenerative_and_friction_braking:
    - Missing BMS max charge current produces CONDITIONAL status.
    - Exposes is_bms_current_limit_known = False.
    - Active constraints contains WARN_BMS_CURRENT_LIMIT_UNKNOWN.
    """
    bms_no_curr = default_bms.model_copy(update={"max_charge_current_a": None})

    res = blend_regenerative_and_friction_braking(
        requested_brake_force_n=1000.0,
        vehicle_speed_ms=15.0,
        motor_config=default_motor,
        gearbox_config=default_gearbox,
        inverter_config=default_inverter,
        bms_config=bms_no_curr,
        blending_config=default_blending,
        normal_force_n=15000.0,
        adhesion_coefficient=0.80,
    )

    assert res.is_bms_power_limit_known is True
    assert res.is_bms_current_limit_known is False
    assert res.is_bms_limit_known is False
    assert res.bms_admissible_power_kw is not None
    assert res.bms_admissible_current_a is None
    assert res.overall_status == ConstraintStatus.CONDITIONAL
    assert "WARN_BMS_CURRENT_LIMIT_UNKNOWN" in res.active_constraints


# =============================================================================
# 4. TARGETED CORRECTION 3: SYSTEMATIC AUDIT OF MISSING HARDWARE CONSTRAINTS
# =============================================================================

def test_missing_bms_power_limit_conditional_no_fallback(default_bms: BMSConfig):
    """Verify missing BMS power limit produces CONDITIONAL without fallback."""
    bms_none = default_bms.model_copy(update={"max_charge_power_kw": None})
    res = compute_bms_acceptance(0.50, 25.0, bms_none)

    assert res.admissible_charge_power_kw is None
    assert res.is_power_limit_known is False
    assert res.is_limit_known is False
    assert res.status == ConstraintStatus.CONDITIONAL


def test_missing_bms_limit_blending_diagnostics(
    default_motor: MotorConfig,
    default_gearbox: GearboxConfig,
    default_inverter: InverterElectricalConfig,
    default_bms: BMSConfig,
    default_blending: BrakeBlendingConfig,
):
    """Verify missing BMS power limit in blending produces CONDITIONAL and diagnostic."""
    bms_none = default_bms.model_copy(update={"max_charge_power_kw": None})

    res = blend_regenerative_and_friction_braking(
        requested_brake_force_n=1000.0,
        vehicle_speed_ms=15.0,
        motor_config=default_motor,
        gearbox_config=default_gearbox,
        inverter_config=default_inverter,
        bms_config=bms_none,
        blending_config=default_blending,
    )

    assert res.is_bms_power_limit_known is False
    assert res.is_bms_limit_known is False
    assert res.bms_admissible_power_kw is None
    assert res.overall_status == ConstraintStatus.CONDITIONAL
    assert res.diagnostic_code == "WARN_BMS_POWER_LIMIT_UNKNOWN"
    assert "WARN_BMS_POWER_LIMIT_UNKNOWN" in res.active_constraints
    assert abs(res.energy_residual_kw) < 1e-5


def test_missing_kt_rms_stator_current_conditional(
    default_motor: MotorConfig,
    default_gearbox: GearboxConfig,
    default_inverter: InverterElectricalConfig,
    default_bms: BMSConfig,
    default_blending: BrakeBlendingConfig,
):
    """Verify missing motor k_t produces CONDITIONAL."""
    motor_no_kt = default_motor.model_copy(update={"k_t_rms": None})

    res = blend_regenerative_and_friction_braking(
        requested_brake_force_n=1000.0,
        vehicle_speed_ms=15.0,
        motor_config=motor_no_kt,
        gearbox_config=default_gearbox,
        inverter_config=default_inverter,
        bms_config=default_bms,
        blending_config=default_blending,
    )

    assert res.stator_current_rms_a is None
    assert res.stator_current_status == ConstraintStatus.CONDITIONAL
    assert res.overall_status == ConstraintStatus.CONDITIONAL
    assert "WARN_KT_UNVERIFIED" in res.active_constraints
    assert abs(res.energy_residual_kw) < 1e-5


def test_missing_inverter_ac_phase_current_limit_conditional(
    default_motor: MotorConfig,
    default_gearbox: GearboxConfig,
    default_inverter: InverterElectricalConfig,
    default_bms: BMSConfig,
    default_blending: BrakeBlendingConfig,
):
    """Verify missing inverter AC phase current limit produces CONDITIONAL."""
    motor_no_ac_limit = default_motor.model_copy(update={"inverter_current_limit_rms": None})

    res = blend_regenerative_and_friction_braking(
        requested_brake_force_n=1000.0,
        vehicle_speed_ms=15.0,
        motor_config=motor_no_ac_limit,
        gearbox_config=default_gearbox,
        inverter_config=default_inverter,
        bms_config=default_bms,
        blending_config=default_blending,
    )

    assert res.stator_current_rms_a is not None
    assert res.stator_current_limit_rms_a is None
    assert res.stator_current_status == ConstraintStatus.CONDITIONAL
    assert "WARN_STATOR_CURRENT_LIMIT_UNVERIFIED" in res.active_constraints
    assert abs(res.energy_residual_kw) < 1e-5


def test_missing_inverter_dc_power_limit_conditional(
    default_motor: MotorConfig,
    default_gearbox: GearboxConfig,
    default_inverter: InverterElectricalConfig,
    default_bms: BMSConfig,
    default_blending: BrakeBlendingConfig,
):
    """Verify missing inverter gross DC power limit produces CONDITIONAL."""
    inv_no_pwr = default_inverter.model_copy(update={"dc_power_limit_kw": None})

    res = blend_regenerative_and_friction_braking(
        requested_brake_force_n=1000.0, vehicle_speed_ms=15.0,
        motor_config=default_motor, gearbox_config=default_gearbox,
        inverter_config=inv_no_pwr, bms_config=default_bms, blending_config=default_blending,
        normal_force_n=15000.0, adhesion_coefficient=0.80,
    )

    assert res.overall_status == ConstraintStatus.CONDITIONAL
    assert "WARN_INVERTER_POWER_LIMIT_UNKNOWN" in res.active_constraints


def test_missing_inverter_dc_current_limit_conditional(
    default_motor: MotorConfig,
    default_gearbox: GearboxConfig,
    default_inverter: InverterElectricalConfig,
    default_bms: BMSConfig,
    default_blending: BrakeBlendingConfig,
):
    """Verify missing inverter DC current limit produces CONDITIONAL."""
    inv_no_curr = default_inverter.model_copy(update={"dc_current_limit_a": None})

    res = blend_regenerative_and_friction_braking(
        requested_brake_force_n=1000.0, vehicle_speed_ms=15.0,
        motor_config=default_motor, gearbox_config=default_gearbox,
        inverter_config=inv_no_curr, bms_config=default_bms, blending_config=default_blending,
        normal_force_n=15000.0, adhesion_coefficient=0.80,
    )

    assert res.overall_status == ConstraintStatus.CONDITIONAL
    assert "WARN_INVERTER_CURRENT_LIMIT_UNKNOWN" in res.active_constraints


def test_missing_inverter_nominal_voltage_conditional(
    default_motor: MotorConfig,
    default_gearbox: GearboxConfig,
    default_inverter: InverterElectricalConfig,
    default_bms: BMSConfig,
    default_blending: BrakeBlendingConfig,
):
    """Verify missing inverter nominal DC voltage produces CONDITIONAL and leaves currents as None."""
    inv_no_volt = default_inverter.model_copy(update={"dc_voltage_nominal_v": None})

    res = blend_regenerative_and_friction_braking(
        requested_brake_force_n=1000.0, vehicle_speed_ms=15.0,
        motor_config=default_motor, gearbox_config=default_gearbox,
        inverter_config=inv_no_volt, bms_config=default_bms, blending_config=default_blending,
        normal_force_n=15000.0, adhesion_coefficient=0.80,
    )

    assert res.inverter_dc_current_gross_a is None
    assert res.inverter_dc_current_net_a is None
    assert res.inverter_dc_current_a is None
    assert res.overall_status == ConstraintStatus.CONDITIONAL
    assert "WARN_INVERTER_VOLTAGE_UNKNOWN" in res.active_constraints


def test_missing_friction_brake_capacity_conditional(
    default_motor: MotorConfig,
    default_gearbox: GearboxConfig,
    default_inverter: InverterElectricalConfig,
    default_bms: BMSConfig,
    default_blending: BrakeBlendingConfig,
):
    """Verify missing friction brake max capacity produces CONDITIONAL."""
    blend_no_fric = default_blending.model_copy(update={"friction_brake_max_force_n": None})

    res = blend_regenerative_and_friction_braking(
        requested_brake_force_n=1000.0, vehicle_speed_ms=15.0,
        motor_config=default_motor, gearbox_config=default_gearbox,
        inverter_config=default_inverter, bms_config=default_bms, blending_config=blend_no_fric,
        normal_force_n=15000.0, adhesion_coefficient=0.80,
    )

    assert res.overall_status == ConstraintStatus.CONDITIONAL
    assert "WARN_FRICTION_CAPACITY_UNKNOWN" in res.active_constraints


# =============================================================================
# 5. TARGETED CORRECTION 4: EXPANDED PROVENANCE REGRESSION TESTS
# =============================================================================

def test_provenance_all_material_inputs_and_conservative_combination(
    default_motor: MotorConfig,
    default_gearbox: GearboxConfig,
    default_inverter: InverterElectricalConfig,
    default_bms: BMSConfig,
    default_blending: BrakeBlendingConfig,
):
    """
    Verify conservative provenance propagation across all standard categories:
    - All REAL -> REAL
    - Temperature ESTIMATED -> ESTIMATED
    - SOC SIMULATED -> SIMULATED
    - Input UNKNOWN -> UNKNOWN
    - Aux STALE -> STALE
    - DC-DC efficiency ESTIMATED -> ESTIMATED
    """
    # 1. All REAL
    r_real = blend_regenerative_and_friction_braking(
        1000.0, 15.0, default_motor, default_gearbox, default_inverter, default_bms, default_blending,
        normal_force_n=15000.0, adhesion_coefficient=0.80,
        input_status=DataStatus.REAL, soc_status=DataStatus.REAL, temp_status=DataStatus.REAL,
        aux_status=DataStatus.REAL, adhesion_input_status=DataStatus.REAL,
    )
    assert r_real.provenance_status == DataStatus.REAL

    # 2. Temperature ESTIMATED -> ESTIMATED
    r_est = blend_regenerative_and_friction_braking(
        1000.0, 15.0, default_motor, default_gearbox, default_inverter, default_bms, default_blending,
        input_status=DataStatus.REAL, temp_status=DataStatus.ESTIMATED,
    )
    assert r_est.provenance_status == DataStatus.ESTIMATED

    # 3. SOC SIMULATED -> SIMULATED
    r_sim = blend_regenerative_and_friction_braking(
        1000.0, 15.0, default_motor, default_gearbox, default_inverter, default_bms, default_blending,
        input_status=DataStatus.REAL, soc_status=DataStatus.SIMULATED,
    )
    assert r_sim.provenance_status == DataStatus.SIMULATED

    # 4. Input UNKNOWN -> UNKNOWN
    r_unk = blend_regenerative_and_friction_braking(
        1000.0, 15.0, default_motor, default_gearbox, default_inverter, default_bms, default_blending,
        input_status=DataStatus.UNKNOWN,
    )
    assert r_unk.provenance_status == DataStatus.UNKNOWN

    # 5. Aux STALE -> STALE
    r_stale = blend_regenerative_and_friction_braking(
        1000.0, 15.0, default_motor, default_gearbox, default_inverter, default_bms, default_blending,
        input_status=DataStatus.REAL, aux_status=DataStatus.STALE,
    )
    assert r_stale.provenance_status == DataStatus.STALE

    # 6. DC-DC efficiency ESTIMATED -> ESTIMATED
    inv_dcdc_est = default_inverter.model_copy(update={"dc_dc_efficiency_status": DataStatus.ESTIMATED})
    r_dcdc = blend_regenerative_and_friction_braking(
        1000.0, 15.0, default_motor, default_gearbox, inv_dcdc_est, default_bms, default_blending,
        input_status=DataStatus.REAL,
    )
    assert r_dcdc.provenance_status == DataStatus.ESTIMATED


def test_provenance_independent_parameter_degradations(
    default_motor: MotorConfig,
    default_gearbox: GearboxConfig,
    default_inverter: InverterElectricalConfig,
    default_bms: BMSConfig,
    default_blending: BrakeBlendingConfig,
):
    """
    Independently verify that degrading EACH configuration object or input
    degrades the overall provenance without artificial upgrade from numeric defaults:
    - MotorConfig
    - GearboxConfig
    - InverterConfig
    - BMSConfig
    - BrakeBlendingConfig
    - Adhesion input
    """
    base_kwargs = dict(
        requested_brake_force_n=1000.0, vehicle_speed_ms=15.0,
        normal_force_n=15000.0, adhesion_coefficient=0.80,
        input_status=DataStatus.REAL, soc_status=DataStatus.REAL,
        temp_status=DataStatus.REAL, aux_status=DataStatus.REAL,
        adhesion_input_status=DataStatus.REAL,
    )

    # 1. Motor degraded to SIMULATED
    mot_sim = default_motor.model_copy(update={"status": DataStatus.SIMULATED})
    r = blend_regenerative_and_friction_braking(motor_config=mot_sim, gearbox_config=default_gearbox, inverter_config=default_inverter, bms_config=default_bms, blending_config=default_blending, **base_kwargs)
    assert r.provenance_status == DataStatus.SIMULATED

    # 2. Gearbox degraded to STALE
    gb_stale = default_gearbox.model_copy(update={"status": DataStatus.STALE})
    r = blend_regenerative_and_friction_braking(motor_config=default_motor, gearbox_config=gb_stale, inverter_config=default_inverter, bms_config=default_bms, blending_config=default_blending, **base_kwargs)
    assert r.provenance_status == DataStatus.STALE

    # 3. Inverter degraded to UNKNOWN
    inv_unk = default_inverter.model_copy(update={"status": DataStatus.UNKNOWN})
    r = blend_regenerative_and_friction_braking(motor_config=default_motor, gearbox_config=default_gearbox, inverter_config=inv_unk, bms_config=default_bms, blending_config=default_blending, **base_kwargs)
    assert r.provenance_status == DataStatus.UNKNOWN

    # 4. BMS degraded to ESTIMATED
    bms_est = default_bms.model_copy(update={"status": DataStatus.ESTIMATED})
    r = blend_regenerative_and_friction_braking(motor_config=default_motor, gearbox_config=default_gearbox, inverter_config=default_inverter, bms_config=bms_est, blending_config=default_blending, **base_kwargs)
    assert r.provenance_status == DataStatus.ESTIMATED

    # 5. Blending degraded to STALE
    blend_stale = default_blending.model_copy(update={"status": DataStatus.STALE})
    r = blend_regenerative_and_friction_braking(motor_config=default_motor, gearbox_config=default_gearbox, inverter_config=default_inverter, bms_config=default_bms, blending_config=blend_stale, **base_kwargs)
    assert r.provenance_status == DataStatus.STALE

    # 6. Adhesion input degraded to SIMULATED
    kwargs_adh = dict(base_kwargs, adhesion_input_status=DataStatus.SIMULATED)
    r = blend_regenerative_and_friction_braking(motor_config=default_motor, gearbox_config=default_gearbox, inverter_config=default_inverter, bms_config=default_bms, blending_config=default_blending, **kwargs_adh)
    assert r.provenance_status == DataStatus.SIMULATED


# =============================================================================
# 6. TARGETED CORRECTION 5: DIAGNOSTIC ARBITRATION & TOLERANCE
# =============================================================================

def test_diagnostic_arbitration_consistent_tolerance_and_multiple_active(
    default_motor: MotorConfig,
    default_gearbox: GearboxConfig,
    default_inverter: InverterElectricalConfig,
    default_bms: BMSConfig,
    default_blending: BrakeBlendingConfig,
):
    """
    Verify Correction 5:
    - Multiple simultaneously active constraints are all recorded in active_constraints.
    - Identification uses consistent tolerance (TOL = 1e-4) instead of exact float equality.
    - Primary diagnostic_code is selected according to physical hierarchy.
    """
    # Configure inverter DC power limit and DC current limit to be numerically identical at 20.0 kW
    # 57.142857 A * 350 V / 1000 = 20.0 kW
    inv_dual = default_inverter.model_copy(update={
        "dc_power_limit_kw": 20.0,
        "dc_current_limit_a": 20.0 * 1000.0 / 350.0,
        "dc_voltage_nominal_v": 350.0,
    })

    res = blend_regenerative_and_friction_braking(
        requested_brake_force_n=3000.0, vehicle_speed_ms=15.0,
        motor_config=default_motor, gearbox_config=default_gearbox,
        inverter_config=inv_dual, bms_config=default_bms, blending_config=default_blending,
        normal_force_n=15000.0, adhesion_coefficient=0.80,
    )

    assert res.is_regen_curtailed is True
    # Both active simultaneously within tolerance!
    assert "ERR_INVERTER_CURRENT_LIMIT" in res.active_constraints
    assert "ERR_INVERTER_DC_POWER_LIMIT" in res.active_constraints
    # Primary diagnostic code assigned deterministically
    assert res.diagnostic_code == "ERR_INVERTER_CURRENT_LIMIT"


# =============================================================================
# 7. CHASSIS BRAKE BLENDING, FRICTION DEFICIT & AGGREGATE ADHESION
# =============================================================================

def test_energy_ledger_friction_capacity_exceeded_deficit(
    default_motor: MotorConfig,
    default_gearbox: GearboxConfig,
    default_inverter: InverterElectricalConfig,
    default_bms: BMSConfig,
    default_blending: BrakeBlendingConfig,
):
    """
    Verify Correction B: Friction brake capacity exceeded:
    Exact fixture numbers:
    - Demanded: 20000.0 N at 20.0 m/s -> P_req = 400.0 kW
    - Friction capacity: 15000.0 N -> Delivered friction = 15000.0 N, P_fric_deliv = 300.0 kW
    - Regen accepted: limited by continuous power 65.0 kW:
        P_shaft = 65.0 kW
        P_wheel = 65.0 / 0.96 = 67.708333 kW
        F_wheel_regen = (67.708333 * 1000) / 20.0 = 3385.416667 N
    - Total delivered force: 15000.0 + 3385.4167 = 18385.4167 N < 20000.0 N
    - Deficit force: 20000.0 - 18385.4167 = 1614.5833 N
    - Deficit power: 1614.5833 * 20.0 / 1000 = 32.2917 kW
    - Conservation ledger must balance DELIVERED mechanical power (367.7083 kW), NOT requested power!
    - Residual = |P_wheel_delivered - sum(delivered components)| < 1e-5 kW.
    """
    res = blend_regenerative_and_friction_braking(
        requested_brake_force_n=20000.0,
        vehicle_speed_ms=20.0,
        motor_config=default_motor,
        gearbox_config=default_gearbox,
        inverter_config=default_inverter,
        bms_config=default_bms,
        blending_config=default_blending,
        normal_force_n=30000.0,
        adhesion_coefficient=1.2,
    )

    assert res.overall_status == ConstraintStatus.VIOLATED
    assert res.diagnostic_code == "ERR_FRICTION_BRAKE_CAPACITY"
    assert "ERR_FRICTION_BRAKE_CAPACITY" in res.active_constraints
    assert pytest.approx(res.friction_brake_force_n, rel=1e-5) == 15000.0
    assert pytest.approx(res.accepted_regen_wheel_force_n, rel=1e-5) == 3385.416667
    assert pytest.approx(res.delivered_brake_force_n, rel=1e-5) == 18385.416667
    assert pytest.approx(res.braking_deficit_force_n, rel=1e-5) == 1614.583333
    assert pytest.approx(res.braking_deficit_power_kw, rel=1e-5) == 32.291667

    # Ledger check on DELIVERED quantities:
    p_delivered_sum = (
        res.friction_brake_power_kw
        + res.net_battery_charging_kw
        + res.inverter_standby_kw
        + res.auxiliary_hv_power_kw
        + res.inverter_loss_conv_kw
        + res.motor_loss_kw
        + res.gearbox_loss_kw
    )
    assert pytest.approx(res.delivered_brake_power_kw, rel=1e-5) == p_delivered_sum
    assert abs(res.energy_residual_kw) < 1e-5


def test_energy_ledger_dc_dc_conversion_loss_reconciliation(
    default_motor: MotorConfig,
    default_gearbox: GearboxConfig,
    default_inverter: InverterElectricalConfig,
    default_bms: BMSConfig,
    default_blending: BrakeBlendingConfig,
):
    """
    Verify auxiliary accounting satisfies:
    auxiliary HV input = auxiliary LV output + DC-DC conversion loss
    """
    res = blend_regenerative_and_friction_braking(
        requested_brake_force_n=1000.0,
        vehicle_speed_ms=15.0,
        motor_config=default_motor,
        gearbox_config=default_gearbox,
        inverter_config=default_inverter,
        bms_config=default_bms,
        blending_config=default_blending,
        aux_lv_power_kw=0.46,
    )

    assert pytest.approx(res.auxiliary_hv_power_kw, rel=1e-6) == res.auxiliary_lv_power_kw + res.dc_dc_loss_kw
    assert pytest.approx(res.auxiliary_hv_power_kw, rel=1e-6) == 0.46 / 0.92
    assert abs(res.energy_residual_kw) < 1e-5


def test_inverter_dc_power_limit_constrains_gross_bridge_power(
    default_motor: MotorConfig,
    default_gearbox: GearboxConfig,
    default_inverter: InverterElectricalConfig,
    default_bms: BMSConfig,
    default_blending: BrakeBlendingConfig,
):
    """
    Verify dc_power_limit_kw constrains GROSS bridge DC generation:
    - Inverter DC power limit: 20.0 kW
    - Gross DC generated must not exceed 20.0 kW (+ 1e-4 tolerance).
    """
    inv_20kw = default_inverter.model_copy(update={"dc_power_limit_kw": 20.0, "dc_current_limit_a": None})

    res = blend_regenerative_and_friction_braking(
        requested_brake_force_n=2500.0,
        vehicle_speed_ms=20.0,
        motor_config=default_motor,
        gearbox_config=default_gearbox,
        inverter_config=inv_20kw,
        bms_config=default_bms,
        blending_config=default_blending,
        normal_force_n=15000.0,
        adhesion_coefficient=0.80,
    )

    assert res.is_regen_curtailed is True
    assert res.inverter_dc_power_gross_kw <= 20.0 + 1e-4
    assert res.curtailment_reason == "ERR_INVERTER_DC_POWER_LIMIT"
    assert abs(res.energy_residual_kw) < 1e-5


def test_inverter_dc_current_at_different_nominal_voltages(
    default_motor: MotorConfig,
    default_gearbox: GearboxConfig,
    default_inverter: InverterElectricalConfig,
    default_bms: BMSConfig,
    default_blending: BrakeBlendingConfig,
):
    """
    Verify different nominal voltages produce different provisional current-limited power:
    - 50.0 A at 300 V -> 15.0 kW provisional gross limit
    - 50.0 A at 400 V -> 20.0 kW provisional gross limit
    """
    inv_300v = default_inverter.model_copy(update={"dc_current_limit_a": 50.0, "dc_voltage_nominal_v": 300.0, "dc_power_limit_kw": None})
    inv_400v = default_inverter.model_copy(update={"dc_current_limit_a": 50.0, "dc_voltage_nominal_v": 400.0, "dc_power_limit_kw": None})

    r_300 = blend_regenerative_and_friction_braking(
        requested_brake_force_n=2000.0, vehicle_speed_ms=20.0,
        motor_config=default_motor, gearbox_config=default_gearbox,
        inverter_config=inv_300v, bms_config=default_bms, blending_config=default_blending,
        normal_force_n=15000.0, adhesion_coefficient=0.80,
    )
    r_400 = blend_regenerative_and_friction_braking(
        requested_brake_force_n=2000.0, vehicle_speed_ms=20.0,
        motor_config=default_motor, gearbox_config=default_gearbox,
        inverter_config=inv_400v, bms_config=default_bms, blending_config=default_blending,
        normal_force_n=15000.0, adhesion_coefficient=0.80,
    )

    assert pytest.approx(r_300.inverter_dc_power_gross_kw, rel=1e-2) == 15.0
    assert pytest.approx(r_400.inverter_dc_power_gross_kw, rel=1e-2) == 20.0
    assert r_300.is_provisional_voltage_based is True
    assert r_400.is_provisional_voltage_based is True
    assert abs(r_300.energy_residual_kw) < 1e-5
    assert abs(r_400.energy_residual_kw) < 1e-5


def test_ac_phase_current_vs_dc_current_distinction(
    default_motor: MotorConfig,
    default_gearbox: GearboxConfig,
    default_inverter: InverterElectricalConfig,
    default_bms: BMSConfig,
    default_blending: BrakeBlendingConfig,
):
    """
    Verify AC stator phase current vs DC inverter current distinction:
    1. Case A: Low inverter AC phase current limit (100 A rms) constrains motor torque.
       With k_t = 0.65 Nm/A, max torque is 65.0 Nm.
    2. Case B: Ample AC limit (350 A), but tight DC current limit (20 A at 350 V = 7.0 kW).
       DC current limit constrains gross DC power, curtailing regen at inverter bridge.
    """
    # Case A: AC Phase Current Limited
    motor_ac_tight = default_motor.model_copy(update={"inverter_current_limit_rms": 100.0})
    res_ac = blend_regenerative_and_friction_braking(
        requested_brake_force_n=3000.0, vehicle_speed_ms=10.0,
        motor_config=motor_ac_tight, gearbox_config=default_gearbox,
        inverter_config=default_inverter, bms_config=default_bms, blending_config=default_blending,
        normal_force_n=15000.0, adhesion_coefficient=0.80,
    )
    assert res_ac.is_regen_curtailed is True
    assert res_ac.stator_current_rms_a <= 100.0 + 1e-4
    assert res_ac.curtailment_reason == "ERR_STATOR_CURRENT_LIMIT"

    # Case B: DC Current Limited
    inv_dc_tight = default_inverter.model_copy(update={"dc_current_limit_a": 20.0, "dc_power_limit_kw": None})
    res_dc = blend_regenerative_and_friction_braking(
        requested_brake_force_n=3000.0, vehicle_speed_ms=10.0,
        motor_config=default_motor, gearbox_config=default_gearbox,
        inverter_config=inv_dc_tight, bms_config=default_bms, blending_config=default_blending,
        normal_force_n=15000.0, adhesion_coefficient=0.80,
    )
    assert res_dc.is_regen_curtailed is True
    assert res_dc.inverter_dc_power_gross_kw <= 7.0 + 1e-4  # 20 A * 350 V = 7.0 kW
    assert res_dc.curtailment_reason == "ERR_INVERTER_CURRENT_LIMIT"
    assert abs(res_ac.energy_residual_kw) < 1e-5
    assert abs(res_dc.energy_residual_kw) < 1e-5


def test_aggregate_adhesion_validation_and_invalid_inputs(
    default_motor: MotorConfig,
    default_gearbox: GearboxConfig,
    default_inverter: InverterElectricalConfig,
    default_bms: BMSConfig,
    default_blending: BrakeBlendingConfig,
):
    """
    Verify aggregate adhesion:
    1. Reject negative or zero normal force.
    2. Reject negative or extreme (> 2.5) adhesion coefficient.
    3. Low friction road (mu=0.20, F_z=10,000 N, demand 4,000 N):
       - Delivered force must not exceed 2,000 N.
       - Deficit force must equal 2,000 N.
       - Adhesion status and overall status must be VIOLATED.
    """
    # 1. Invalid normal force (<= 0)
    with pytest.raises(ValueError, match="normal_force_n"):
        blend_regenerative_and_friction_braking(
            1000.0, 15.0, default_motor, default_gearbox, default_inverter, default_bms, default_blending,
            normal_force_n=-500.0, adhesion_coefficient=0.80,
        )

    # 2. Invalid adhesion coefficient (> 2.5)
    with pytest.raises(ValueError, match="adhesion_coefficient"):
        blend_regenerative_and_friction_braking(
            1000.0, 15.0, default_motor, default_gearbox, default_inverter, default_bms, default_blending,
            normal_force_n=15000.0, adhesion_coefficient=3.0,
        )

    # 3. Invalid adhesion coefficient (<= 0)
    with pytest.raises(ValueError, match="adhesion_coefficient"):
        blend_regenerative_and_friction_braking(
            1000.0, 15.0, default_motor, default_gearbox, default_inverter, default_bms, default_blending,
            normal_force_n=15000.0, adhesion_coefficient=-0.1,
        )

    # 4. Slippery road exceeding aggregate adhesion: 4000 N demand on 10000 N normal force with mu=0.20 -> max 2000 N
    r_slip = blend_regenerative_and_friction_braking(
        4000.0, 15.0, default_motor, default_gearbox, default_inverter, default_bms, default_blending,
        normal_force_n=10000.0, adhesion_coefficient=0.20,
    )
    assert r_slip.adhesion_status == ConstraintStatus.VIOLATED
    assert r_slip.overall_status == ConstraintStatus.VIOLATED
    assert r_slip.diagnostic_code == "ERR_ADHESION_EXCEEDED"
    assert r_slip.delivered_brake_force_n <= 2000.0 + 1e-4
    assert pytest.approx(r_slip.braking_deficit_force_n, rel=1e-4) == 2000.0
    assert abs(r_slip.energy_residual_kw) < 1e-5


def test_normal_adhesion_full_braking_delivered(
    default_motor: MotorConfig,
    default_gearbox: GearboxConfig,
    default_inverter: InverterElectricalConfig,
    default_bms: BMSConfig,
    default_blending: BrakeBlendingConfig,
):
    """Verify normal adhesion (mu=0.90, F_z=15000 N): full braking delivered."""
    res = blend_regenerative_and_friction_braking(
        3000.0, 15.0, default_motor, default_gearbox, default_inverter, default_bms, default_blending,
        normal_force_n=15000.0, adhesion_coefficient=0.90,
    )
    assert res.adhesion_status == ConstraintStatus.SATISFIED
    assert res.braking_deficit_force_n == 0.0
    assert pytest.approx(res.delivered_brake_force_n, rel=1e-5) == 3000.0
    assert abs(res.energy_residual_kw) < 1e-5


# =============================================================================
# 8. LOW-SPEED REGEN & BMS DETAILED SUITE
# =============================================================================

def test_low_speed_blend_transition_and_continuity(default_blending: BrakeBlendingConfig):
    """Verify low-speed blend continuity and monotonicity."""
    v_cut = default_blending.v_cutoff_ms  # 1.0
    v_start = default_blending.v_blend_start_ms  # 3.0

    assert compute_low_speed_regen_factor(0.0, default_blending) == 0.0
    assert compute_low_speed_regen_factor(v_cut, default_blending) == 0.0
    assert compute_low_speed_regen_factor(v_start, default_blending) == 1.0
    assert compute_low_speed_regen_factor(v_start + 5.0, default_blending) == 1.0

    # Monotonicity test across fine speed grid
    speeds = [0.0, 0.5, 1.0, 1.0001, 1.25, 1.5, 1.75, 2.0, 2.25, 2.5, 2.75, 2.9999, 3.0, 5.0, 20.0]
    factors = [compute_low_speed_regen_factor(v, default_blending) for v in speeds]
    for i in range(len(factors) - 1):
        assert factors[i] <= factors[i + 1]


def test_low_speed_rolloff_exact_points_and_zero_standstill(
    default_motor: MotorConfig,
    default_gearbox: GearboxConfig,
    default_inverter: InverterElectricalConfig,
    default_bms: BMSConfig,
    default_blending: BrakeBlendingConfig,
):
    """Verify low-speed rolloff across specific boundary points."""
    v_points = [0.0, 0.5, 1.0, 1.001, 2.0, 3.0, 10.0]
    for v in v_points:
        res = blend_regenerative_and_friction_braking(
            requested_brake_force_n=1000.0, vehicle_speed_ms=v,
            motor_config=default_motor, gearbox_config=default_gearbox,
            inverter_config=default_inverter, bms_config=default_bms, blending_config=default_blending,
            normal_force_n=15000.0, adhesion_coefficient=0.80,
        )
        if v <= 1.0:
            assert res.low_speed_factor == 0.0
            assert res.accepted_regen_wheel_force_n == 0.0
            assert pytest.approx(res.friction_brake_force_n, rel=1e-5) == 1000.0
        elif v == 2.0:
            assert pytest.approx(res.low_speed_factor, rel=1e-4) == 0.5
        elif v >= 3.0:
            assert res.low_speed_factor == 1.0
        assert abs(res.energy_residual_kw) < 1e-5


def test_bms_soc_taper_sweep(default_bms: BMSConfig):
    """Verify BMS acceptance SOC taper from 0% to 100%."""
    for soc in [0.10, 0.50, 0.70, 0.80]:
        res = compute_bms_acceptance(soc, 25.0, default_bms)
        assert res.soc_derate_factor == 1.0
        assert pytest.approx(res.admissible_charge_power_kw, rel=1e-5) == 65.0

    res_half = compute_bms_acceptance(0.89, 25.0, default_bms)
    assert pytest.approx(res_half.soc_derate_factor, rel=1e-5) == 0.50
    assert pytest.approx(res_half.admissible_charge_power_kw, rel=1e-5) == 32.50

    res_cutoff = compute_bms_acceptance(0.98, 25.0, default_bms)
    assert res_cutoff.soc_derate_factor == 0.0
    assert res_cutoff.admissible_charge_power_kw == 0.0


def test_bms_temperature_derating(default_bms: BMSConfig):
    """Verify BMS acceptance temperature derating."""
    res_opt = compute_bms_acceptance(0.50, 25.0, default_bms)
    assert res_opt.temp_derate_factor == 1.0

    res_cold = compute_bms_acceptance(0.50, -10.0, default_bms)
    assert res_cold.temp_derate_factor == 0.0
    assert res_cold.admissible_charge_power_kw == 0.0

    res_cold_mid = compute_bms_acceptance(0.50, 2.5, default_bms)
    assert pytest.approx(res_cold_mid.temp_derate_factor, rel=1e-5) == 0.50
    assert pytest.approx(res_cold_mid.admissible_charge_power_kw, rel=1e-5) == 32.50

    res_hot_mid = compute_bms_acceptance(0.50, 42.5, default_bms)
    assert pytest.approx(res_hot_mid.temp_derate_factor, rel=1e-5) == 0.50
    assert pytest.approx(res_hot_mid.admissible_charge_power_kw, rel=1e-5) == 32.50

    res_hot = compute_bms_acceptance(0.50, 50.0, default_bms)
    assert res_hot.temp_derate_factor == 0.0
    assert res_hot.admissible_charge_power_kw == 0.0


def test_bms_combined_soc_and_temperature_derating(default_bms: BMSConfig):
    """Verify multiplicative interaction of SOC and temperature derating."""
    res = compute_bms_acceptance(0.89, 2.5, default_bms)
    assert pytest.approx(res.soc_derate_factor, rel=1e-5) == 0.50
    assert pytest.approx(res.temp_derate_factor, rel=1e-5) == 0.50
    assert pytest.approx(res.admissible_charge_power_kw, rel=1e-5) == 16.25


def test_zero_acceptance_pack_high_soc_aux_absorption(
    default_motor: MotorConfig,
    default_gearbox: GearboxConfig,
    default_inverter: InverterElectricalConfig,
    default_bms: BMSConfig,
    default_blending: BrakeBlendingConfig,
):
    """Verify zero battery acceptance at high SOC (99%)."""
    # Case 1: Aux load present (0.46 kW LV / 0.92 = 0.50 kW HV)
    r_aux = blend_regenerative_and_friction_braking(
        requested_brake_force_n=1000.0, vehicle_speed_ms=15.0,
        motor_config=default_motor, gearbox_config=default_gearbox,
        inverter_config=default_inverter, bms_config=default_bms, blending_config=default_blending,
        battery_soc=0.99, battery_temp_c=25.0, aux_lv_power_kw=0.46,
        normal_force_n=15000.0, adhesion_coefficient=0.80,
    )
    assert r_aux.bms_admissible_power_kw == 0.0
    assert pytest.approx(r_aux.net_battery_charging_kw, abs=1e-9) == 0.0
    assert r_aux.accepted_regen_wheel_force_n > 0.0  # Powers aux
    assert abs(r_aux.energy_residual_kw) < 1e-5

    # Case 2: Zero aux load
    r_no_aux = blend_regenerative_and_friction_braking(
        requested_brake_force_n=1000.0, vehicle_speed_ms=15.0,
        motor_config=default_motor, gearbox_config=default_gearbox,
        inverter_config=default_inverter, bms_config=default_bms, blending_config=default_blending,
        battery_soc=0.99, battery_temp_c=25.0, aux_lv_power_kw=0.0,
        normal_force_n=15000.0, adhesion_coefficient=0.80,
    )
    assert r_no_aux.bms_admissible_power_kw == 0.0
    assert pytest.approx(r_no_aux.net_battery_charging_kw, abs=1e-9) == 0.0
    assert r_no_aux.accepted_regen_wheel_force_n == 0.0
    assert pytest.approx(r_no_aux.friction_brake_force_n, rel=1e-5) == 1000.0
    assert abs(r_no_aux.energy_residual_kw) < 1e-5


# =============================================================================
# 9. HAND-CALCULATED NUMERICAL REFERENCE INTEGRATION CASES
# =============================================================================

def test_hand_calculated_reference_integration_case(
    default_motor: MotorConfig,
    default_gearbox: GearboxConfig,
    default_inverter: InverterElectricalConfig,
    default_bms: BMSConfig,
    default_blending: BrakeBlendingConfig,
):
    """
    Independent hand-calculated reference case 1 (Uncurtailed normal regen):
    - v = 20.0 m/s
    - F_brake_req = 1500 N
    - P_wheel_brake_req = (1500 * 20) / 1000 = 30.0 kW
    - Standby loss: 200 W (0.20 kW)
    - Aux LV load: 460 W (0.46 kW) -> Aux HV load = 0.46 / 0.92 = 0.50 kW
    - Nominal voltage: 350.0 V
    - Hand-calculated expected values:
      P_wheel_regen = -30.0 kW
      P_shaft = -30.0 * 0.96 = -28.80 kW (P_loss_gb = 1.20 kW)
      P_mot_ac = -28.80 * 0.92 = -26.496 kW (P_loss_mot = 2.304 kW)
      P_inv_dc_gross = 26.496 * 0.95 = 25.1712 kW (P_loss_inv_conv = 1.3248 kW)
      P_inv_dc_net = 25.1712 - 0.20 = 24.9712 kW
      P_batt_chg_net = 24.9712 - 0.50 = 24.4712 kW
      I_inv_dc_gross = 25.1712 * 1000 / 350.0 = 71.917714 A
      I_inv_dc_net = 24.9712 * 1000 / 350.0 = 71.346286 A
      Residual = 0.0 kW!
    """
    inv_standby = default_inverter.model_copy(update={"standby_loss_w": 200.0})

    res = blend_regenerative_and_friction_braking(
        requested_brake_force_n=1500.0,
        vehicle_speed_ms=20.0,
        motor_config=default_motor,
        gearbox_config=default_gearbox,
        inverter_config=inv_standby,
        bms_config=default_bms,
        blending_config=default_blending,
        aux_lv_power_kw=0.46,
        normal_force_n=15000.0,
        adhesion_coefficient=0.80,
        input_status=DataStatus.REAL,
        soc_status=DataStatus.REAL,
        temp_status=DataStatus.REAL,
        aux_status=DataStatus.REAL,
        adhesion_input_status=DataStatus.REAL,
    )

    assert pytest.approx(res.requested_brake_power_kw, rel=1e-6) == 30.0
    assert pytest.approx(res.accepted_regen_wheel_power_kw, rel=1e-6) == -30.0
    assert pytest.approx(res.motor_shaft_power_kw, rel=1e-6) == -28.80
    assert pytest.approx(res.motor_electrical_power_kw, rel=1e-6) == -26.496
    assert pytest.approx(res.inverter_dc_power_gross_kw, rel=1e-6) == 25.1712
    assert pytest.approx(res.inverter_standby_kw, rel=1e-6) == 0.20
    assert pytest.approx(res.inverter_dc_power_net_kw, rel=1e-6) == 24.9712
    assert pytest.approx(res.auxiliary_hv_power_kw, rel=1e-6) == 0.50
    assert pytest.approx(res.net_battery_charging_kw, rel=1e-6) == 24.4712
    assert pytest.approx(res.gearbox_loss_kw, rel=1e-6) == 1.20
    assert pytest.approx(res.motor_loss_kw, rel=1e-6) == 2.304
    assert pytest.approx(res.inverter_loss_conv_kw, rel=1e-6) == 1.3248

    # Boundary 4 Current separation
    assert pytest.approx(res.inverter_dc_current_gross_a, rel=1e-5) == 25.1712 * 1000.0 / 350.0
    assert pytest.approx(res.inverter_dc_current_net_a, rel=1e-5) == 24.9712 * 1000.0 / 350.0
    assert pytest.approx(res.inverter_dc_current_a, rel=1e-5) == 24.9712 * 1000.0 / 350.0
    assert pytest.approx(res.inverter_dc_current_gross_a - res.inverter_dc_current_net_a, rel=1e-5) == 0.20 * 1000.0 / 350.0

    # BMS Certainty
    assert res.is_bms_power_limit_known is True
    assert res.is_bms_current_limit_known is True
    assert res.is_bms_limit_known is True

    assert abs(res.energy_residual_kw) < 1e-6
    assert res.overall_status == ConstraintStatus.SATISFIED
    assert res.provenance_status == DataStatus.REAL


def test_hand_calculated_reference_curtailed_blended_case(
    default_motor: MotorConfig,
    default_gearbox: GearboxConfig,
    default_blending: BrakeBlendingConfig,
):
    """
    Independent hand-calculated reference case 2 (Curtailed by inverter DC current, with friction blending):
    Parameters:
    - Speed: v = 15.0 m/s
    - Demanded braking force: F_req = 5000.0 N -> P_req = (5000.0 * 15.0) / 1000 = 75.0 kW
    - Gearbox: N_gb = 9.05, r_w = 0.315 m, eta_fwd = 0.97, eta_rev = 0.96
    - Motor: cont_max_nm = 145.0, cont_max_kw = 50.0, eta_gen = 0.92, k_t = 0.650 Nm/A
    - Inverter:
        V_nom = 350.0 V,
        I_dc_limit = 120.0 A -> P_current_limit = (120 * 350) / 1000 = 42.0 kW (provisional),
        P_dc_limit = 45.0 kW,
        eta_regen = 0.95,
        standby_loss = 150 W (0.15 kW),
        dc_dc_eff = 0.92
    - Aux LV load: 368 W (0.368 kW) -> Aux HV load = 0.368 / 0.92 = 0.40 kW, P_dc_dc_loss = 0.032 kW
    - BMS: max charge power 50.0 kW, max current 150 A (52.5 kW), SOC = 0.50, T = 25°C -> BMS limit = 50.0 kW
      (Required gross DC for BMS limit = 50.0 + 0.40 + 0.15 = 50.55 kW)
    - Inverter DC current constraint binds first at 42.0 kW gross DC bridge generation!

    Exact physical chain derivations:
    1. Gross bridge DC power: P_inv_dc_gross = 42.0 kW
    2. Motor electrical power: P_mot_elec = -(42.0 / 0.95) = -44.210526 kW
       Inverter conversion loss: P_loss_inv_conv = 44.210526 - 42.0 = 2.210526 kW
    3. Motor shaft power: P_shaft = -(44.210526 / 0.92) = -48.054920 kW
       Motor internal loss: P_loss_mot = 48.054920 - 44.210526 = 3.844394 kW
    4. Motor angular speed:
       omega_wheel = 15.0 / 0.315 = 47.619048 rad/s
       omega_motor = 47.619048 * 9.05 = 430.952381 rad/s
       Motor torque: T_motor = (48054.920) / 430.952381 = 111.50865 Nm <= 145.0 Nm
       Stator current: I_stator_rms = 111.50865 / 0.650 = 171.5518 A rms <= 350 A rms
    5. Wheel regen power: P_wheel_regen = -(48.054920 / 0.96) = -50.057208 kW
       Gearbox reverse loss: P_loss_gb = 50.057208 - 48.054920 = 2.002288 kW
    6. Wheel regen force:
       F_wheel_regen = (50057.208) / 15.0 = 3337.1472 N
    7. Friction brake blending:
       F_friction = 5000.0 - 3337.1472 = 1662.8528 N
       P_friction = (1662.8528 * 15.0) / 1000 = 24.942792 kW
    8. HV bus and Battery accounting:
       P_inv_dc_net = 42.0 - 0.15 = 41.85 kW
       P_batt_chg_net = 41.85 - 0.40 = 41.45 kW
       I_inv_dc_gross = 42.0 * 1000 / 350.0 = 120.0 A (exact compliance with rating!)
       I_inv_dc_net = 41.85 * 1000 / 350.0 = 119.571429 A (signed current to HV bus)
    9. Energy conservation ledger (Delivered quantities):
       P_delivered = P_friction (24.942792) + P_batt (41.45) + P_standby (0.15) + P_aux (0.40)
                   + P_loss_inv (2.210526) + P_loss_mot (3.844394) + P_loss_gb (2.002288)
                   = 75.000000 kW!
       Residual = |75.0 - 75.0| = 0.0 kW!
    """
    mot_custom = default_motor.model_copy(update={"power_cont_max_kw": 50.0})
    inv_custom = InverterElectricalConfig(
        dc_voltage_nominal_v=350.0,
        dc_voltage_max_v=420.0,
        dc_voltage_min_v=250.0,
        dc_current_limit_a=120.0,
        dc_power_limit_kw=45.0,
        efficiency_regen=0.95,
        standby_loss_w=150.0,
        dc_dc_efficiency=0.92,
        dc_dc_efficiency_status=DataStatus.REAL,
        status=DataStatus.REAL,
    )
    bms_custom = BMSConfig(
        max_charge_power_kw=50.0,
        max_charge_current_a=150.0,
        pack_nominal_voltage_v=350.0,
        cell_max_voltage_v=4.20,
        soc_taper_start=0.80,
        soc_cutoff=0.98,
        temp_optimal_low_c=15.0,
        temp_optimal_high_c=35.0,
        temp_cold_cutoff_c=-10.0,
        temp_hot_cutoff_c=50.0,
        status=DataStatus.REAL,
    )

    res = blend_regenerative_and_friction_braking(
        requested_brake_force_n=5000.0,
        vehicle_speed_ms=15.0,
        motor_config=mot_custom,
        gearbox_config=default_gearbox,
        inverter_config=inv_custom,
        bms_config=bms_custom,
        blending_config=default_blending,
        aux_lv_power_kw=0.368,
        normal_force_n=20000.0,
        adhesion_coefficient=0.80,
        input_status=DataStatus.REAL,
        soc_status=DataStatus.REAL,
        temp_status=DataStatus.REAL,
        aux_status=DataStatus.REAL,
        adhesion_input_status=DataStatus.REAL,
    )

    # 1. Kinematics and curtailment
    assert res.is_regen_curtailed is True
    assert res.curtailment_reason == "ERR_INVERTER_CURRENT_LIMIT"
    assert "ERR_INVERTER_CURRENT_LIMIT" in res.active_constraints
    assert res.is_provisional_voltage_based is True
    assert pytest.approx(res.requested_brake_power_kw, rel=1e-5) == 75.0

    # 2. Forces
    assert pytest.approx(res.accepted_regen_wheel_force_n, rel=1e-4) == 3337.1472
    assert pytest.approx(res.friction_brake_force_n, rel=1e-4) == 1662.8528
    assert pytest.approx(res.delivered_brake_force_n, rel=1e-5) == 5000.0
    assert res.braking_deficit_force_n == 0.0

    # 3. Powers and Losses
    assert pytest.approx(res.accepted_regen_wheel_power_kw, rel=1e-4) == -50.057208
    assert pytest.approx(res.gearbox_loss_kw, rel=1e-4) == 2.002288
    assert pytest.approx(res.motor_shaft_power_kw, rel=1e-4) == -48.054920
    assert pytest.approx(res.motor_loss_kw, rel=1e-4) == 3.844394
    assert pytest.approx(res.motor_electrical_power_kw, rel=1e-4) == -44.210526
    assert pytest.approx(res.inverter_loss_conv_kw, rel=1e-4) == 2.210526

    # 4. Inverter Bridge & HV Bus
    assert pytest.approx(res.inverter_dc_power_gross_kw, rel=1e-5) == 42.0
    assert pytest.approx(res.inverter_standby_kw, rel=1e-5) == 0.15
    assert pytest.approx(res.inverter_dc_power_net_kw, rel=1e-5) == 41.85

    # 5. Aux & Battery
    assert pytest.approx(res.auxiliary_lv_power_kw, rel=1e-5) == 0.368
    assert pytest.approx(res.auxiliary_hv_power_kw, rel=1e-5) == 0.40
    assert pytest.approx(res.dc_dc_loss_kw, rel=1e-5) == 0.032
    assert pytest.approx(res.net_battery_charging_kw, rel=1e-5) == 41.45

    # 6. Electrical Stator & DC currents
    assert pytest.approx(res.stator_current_rms_a, rel=1e-4) == 171.5518
    assert pytest.approx(res.inverter_dc_current_gross_a, rel=1e-4) == 120.0
    assert pytest.approx(res.inverter_dc_current_net_a, rel=1e-4) == 41.85 * 1000.0 / 350.0
    assert pytest.approx(res.inverter_dc_current_a, rel=1e-4) == 41.85 * 1000.0 / 350.0

    # 7. Energy Conservation Ledger
    assert abs(res.energy_residual_kw) < 1e-5
    assert res.overall_status == ConstraintStatus.SATISFIED
    assert res.provenance_status == DataStatus.REAL
