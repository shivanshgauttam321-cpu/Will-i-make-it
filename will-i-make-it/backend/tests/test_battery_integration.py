"""
Integration Test Suite for C2.1 + C3 Powertrain & Dynamic Battery Subsystems
=============================================================================
Validates end-to-end integration across C1.3, C2.1, and C3:
1. Normal regenerative charging.
2. Battery near maximum SOC.
3. Battery at maximum SOC.
4. Battery near minimum SOC.
5. Battery at minimum SOC.
6. Cold battery.
7. Hot battery.
8. High polarization voltage.
9. Charge-current restriction.
10. Charge-power restriction.
11. Terminal overvoltage restriction.
12. Battery discharge.
13. Discharge-current restriction.
14. Discharge-power restriction.
15. Auxiliary load greater than available generation.
16. Zero-power operation.
17. Standstill.
18. Low-speed regeneration.
19. Sudden changes in requested power.
20. Multi-step driving cycle.
21. Repeated regenerative braking events.
22. Alternating traction and regeneration.
23. Battery unable to accept the full regenerative request.
24. Complete friction-brake reconciliation.
25. Energy conservation across the integrated path.
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
)
from app.services.energy.regen_model import (
    InverterElectricalConfig,
    BMSConfig,
    BrakeBlendingConfig,
)
from app.services.energy.battery_model import (
    BatteryConfig,
    BatteryState,
    TheveninParameters,
    BatteryOperatingPoint,
    BatterySimulationResult,
    simulate_battery_step,
)
from app.services.energy.battery_integration import (
    IntegratedPowertrainResult,
    create_dynamic_bms_config,
    simulate_integrated_powertrain_step,
)


@pytest.fixture
def default_gearbox() -> GearboxConfig:
    return GearboxConfig(
        gear_ratio=9.05,
        efficiency_fwd=0.97,
        efficiency_rev=0.97,
        wheel_radius_m=0.315,
        status=DataStatus.REAL,
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
        status=DataStatus.REAL,
    )


@pytest.fixture
def default_inverter() -> InverterElectricalConfig:
    return InverterElectricalConfig(
        dc_voltage_nominal_v=355.2,
        dc_voltage_max_v=405.0,
        dc_voltage_min_v=265.0,
        dc_current_limit_a=250.0,
        dc_power_limit_kw=75.0,
        efficiency_regen=0.95,
        standby_loss_w=150.0,
        dc_dc_efficiency=0.92,
        status=DataStatus.REAL,
    )


@pytest.fixture
def default_battery_config() -> BatteryConfig:
    return BatteryConfig(
        cell_chemistry="NMC",
        series_cells=96,
        parallel_strings=1,
        nominal_cell_capacity_ah=60.0,
        nominal_pack_capacity_kwh=21.3,
        nominal_pack_voltage_v=355.2,
        cell_voltage_min_v=2.80,
        cell_voltage_max_v=4.20,
        cell_voltage_nominal_v=3.70,
        soc_min_operating=0.05,
        soc_max_operating=0.98,
        r0_pack_baseline_ohm=0.040,
        r1_pack_baseline_ohm=0.025,
        c1_pack_baseline_f=2000.0,
        max_charge_current_a=200.0,
        max_discharge_current_a=-300.0,
        max_charge_power_kw=65.0,
        max_discharge_power_kw=-100.0,
        coulombic_efficiency_chg=0.99,
        coulombic_efficiency_dis=1.00,
        status=DataStatus.REAL,
    )


@pytest.fixture
def default_battery_state() -> BatteryState:
    return BatteryState(
        soc=0.50,
        v1_polarization_v=0.0,
        temperature_c=25.0,
        state_of_health=1.0,
        cumulative_energy_throughput_kwh=0.0,
        provenance_status=DataStatus.REAL,
    )


# =============================================================================
# INTEGRATION TESTS 1 TO 25
# =============================================================================

def test_01_normal_regenerative_charging(
    default_gearbox, default_motor, default_inverter, default_battery_config, default_battery_state
):
    """Test 1: Normal regenerative braking cleanly charges battery and preserves demand."""
    res = simulate_integrated_powertrain_step(
        requested_wheel_force_n=-2000.0,
        vehicle_speed_ms=20.0,
        dt_s=1.0,
        battery_state=default_battery_state,
        battery_config=default_battery_config,
        gearbox_config=default_gearbox,
        motor_config=default_motor,
        inverter_config=default_inverter,
        auxiliary_lv_power_kw=0.5,
    )

    assert res.is_braking_mode is True
    assert res.delivered_wheel_force_n == pytest.approx(2000.0, rel=1e-3)
    assert res.braking_deficit_force_n == 0.0
    assert res.delivered_regen_force_n > 0.0
    assert res.accepted_battery_power_kw > 0.0  # Battery charging
    assert res.battery_current_a > 0.0
    assert res.delta_soc > 0.0
    assert abs(res.energy_accounting_residual_j) < 1e-3


def test_02_battery_near_maximum_soc(
    default_gearbox, default_motor, default_inverter, default_battery_config, default_battery_state
):
    """Test 2: Battery near maximum SOC experiences taper or cutoff without vehicle braking failure."""
    state_near_max = default_battery_state.__class__(
        soc=0.97,
        v1_polarization_v=1.0,
        temperature_c=25.0,
        state_of_health=1.0,
        cumulative_energy_throughput_kwh=0.0,
        provenance_status=DataStatus.REAL,
    )
    res = simulate_integrated_powertrain_step(
        requested_wheel_force_n=-2500.0,
        vehicle_speed_ms=20.0,
        dt_s=1.0,
        battery_state=state_near_max,
        battery_config=default_battery_config,
        gearbox_config=default_gearbox,
        motor_config=default_motor,
        inverter_config=default_inverter,
    )

    # Even if battery acceptance is restricted, total braking is satisfied by friction brakes
    assert res.delivered_wheel_force_n == pytest.approx(2500.0, rel=1e-3)
    assert res.braking_deficit_force_n == 0.0
    assert res.delivered_friction_force_n > 0.0


def test_03_battery_at_maximum_soc(
    default_gearbox, default_motor, default_inverter, default_battery_config, default_battery_state
):
    """Test 3: Battery at maximum SOC (0.98) rejects charging; retarding demand satisfied by friction."""
    state_max = default_battery_state.__class__(
        soc=0.98,
        v1_polarization_v=0.0,
        temperature_c=25.0,
        state_of_health=1.0,
        cumulative_energy_throughput_kwh=0.0,
        provenance_status=DataStatus.REAL,
    )
    res = simulate_integrated_powertrain_step(
        requested_wheel_force_n=-2000.0,
        vehicle_speed_ms=20.0,
        dt_s=1.0,
        battery_state=state_max,
        battery_config=default_battery_config,
        gearbox_config=default_gearbox,
        motor_config=default_motor,
        inverter_config=default_inverter,
    )

    # Battery charging accepted must be <= 0 kW (cannot charge)
    assert res.accepted_battery_power_kw <= 0.0
    # Full retarding demand is delivered at wheels
    assert res.delivered_wheel_force_n == pytest.approx(2000.0, rel=1e-3)
    assert res.delivered_friction_force_n > 1800.0
    assert res.braking_deficit_force_n == 0.0


def test_04_battery_near_minimum_soc(
    default_gearbox, default_motor, default_inverter, default_battery_config, default_battery_state
):
    """Test 4: Battery near minimum SOC can accept regenerative charging to recover charge."""
    state_low = default_battery_state.__class__(
        soc=0.06,
        v1_polarization_v=-1.0,
        temperature_c=25.0,
        state_of_health=1.0,
        cumulative_energy_throughput_kwh=0.0,
        provenance_status=DataStatus.REAL,
    )
    res = simulate_integrated_powertrain_step(
        requested_wheel_force_n=-2000.0,
        vehicle_speed_ms=20.0,
        dt_s=1.0,
        battery_state=state_low,
        battery_config=default_battery_config,
        gearbox_config=default_gearbox,
        motor_config=default_motor,
        inverter_config=default_inverter,
    )

    assert res.accepted_battery_power_kw > 0.0
    assert res.final_battery_state.soc > 0.06


def test_05_battery_at_minimum_soc(
    default_gearbox, default_motor, default_inverter, default_battery_config, default_battery_state
):
    """Test 5: Battery at minimum SOC (0.05) cannot discharge to power auxiliaries; flags unserved demand."""
    state_empty = default_battery_state.__class__(
        soc=0.05,
        v1_polarization_v=0.0,
        temperature_c=25.0,
        state_of_health=1.0,
        cumulative_energy_throughput_kwh=0.0,
        provenance_status=DataStatus.REAL,
    )
    # Standstill with 3 kW auxiliary load -> battery cannot discharge
    res = simulate_integrated_powertrain_step(
        requested_wheel_force_n=0.0,
        vehicle_speed_ms=0.0,
        dt_s=1.0,
        battery_state=state_empty,
        battery_config=default_battery_config,
        gearbox_config=default_gearbox,
        motor_config=default_motor,
        inverter_config=default_inverter,
        auxiliary_lv_power_kw=3.0,
    )

    assert res.accepted_battery_power_kw == 0.0
    assert res.unserved_electrical_power_kw > 0.0
    assert "ERR_BATTERY_SOC_MIN_REACHED" in res.active_constraints


def test_06_cold_battery(
    default_gearbox, default_motor, default_inverter, default_battery_config, default_battery_state
):
    """Test 6: Cold battery (-15°C) has higher internal impedance and lower acceptance."""
    state_cold = default_battery_state.__class__(
        soc=0.50,
        v1_polarization_v=0.0,
        temperature_c=-15.0,
        state_of_health=1.0,
        cumulative_energy_throughput_kwh=0.0,
        provenance_status=DataStatus.REAL,
    )
    res = simulate_integrated_powertrain_step(
        requested_wheel_force_n=-3000.0,
        vehicle_speed_ms=25.0,
        dt_s=1.0,
        battery_state=state_cold,
        battery_config=default_battery_config,
        gearbox_config=default_gearbox,
        motor_config=default_motor,
        inverter_config=default_inverter,
    )

    assert res.delivered_wheel_force_n == pytest.approx(3000.0, rel=1e-3)
    assert abs(res.energy_accounting_residual_j) < 1e-3


def test_07_hot_battery(
    default_gearbox, default_motor, default_inverter, default_battery_config, default_battery_state
):
    """Test 7: Hot battery (45°C) operates with derated parameters."""
    state_hot = default_battery_state.__class__(
        soc=0.50,
        v1_polarization_v=0.0,
        temperature_c=45.0,
        state_of_health=1.0,
        cumulative_energy_throughput_kwh=0.0,
        provenance_status=DataStatus.REAL,
    )
    res = simulate_integrated_powertrain_step(
        requested_wheel_force_n=-2000.0,
        vehicle_speed_ms=20.0,
        dt_s=1.0,
        battery_state=state_hot,
        battery_config=default_battery_config,
        gearbox_config=default_gearbox,
        motor_config=default_motor,
        inverter_config=default_inverter,
    )

    assert res.delivered_wheel_force_n == pytest.approx(2000.0, rel=1e-3)


def test_08_high_polarization_voltage(
    default_gearbox, default_motor, default_inverter, default_battery_config, default_battery_state
):
    """Test 8: Pre-existing high polarization voltage (V1 = 6.0 V) raises terminal voltage toward cutoff."""
    state_pol = default_battery_state.__class__(
        soc=0.90,
        v1_polarization_v=6.0,
        temperature_c=25.0,
        state_of_health=1.0,
        cumulative_energy_throughput_kwh=0.0,
        provenance_status=DataStatus.REAL,
    )
    res = simulate_integrated_powertrain_step(
        requested_wheel_force_n=-3000.0,
        vehicle_speed_ms=25.0,
        dt_s=1.0,
        battery_state=state_pol,
        battery_config=default_battery_config,
        gearbox_config=default_gearbox,
        motor_config=default_motor,
        inverter_config=default_inverter,
    )

    v_pack_max = default_battery_config.cell_voltage_max_v * default_battery_config.series_cells
    assert res.terminal_voltage_avg_v <= v_pack_max + 1e-4
    assert res.delivered_wheel_force_n == pytest.approx(3000.0, rel=1e-3)


def test_09_charge_current_restriction(
    default_gearbox, default_motor, default_inverter, default_battery_config, default_battery_state
):
    """Test 9: Charge current limit curtails battery charging and preserves braking demand."""
    cfg_i_limit = default_battery_config.model_copy(update={"max_charge_current_a": 40.0})
    res = simulate_integrated_powertrain_step(
        requested_wheel_force_n=-4000.0,
        vehicle_speed_ms=25.0,
        dt_s=1.0,
        battery_state=default_battery_state,
        battery_config=cfg_i_limit,
        gearbox_config=default_gearbox,
        motor_config=default_motor,
        inverter_config=default_inverter,
    )

    assert res.battery_current_a <= 40.0 + 1e-2
    assert res.delivered_wheel_force_n == pytest.approx(4000.0, rel=1e-3)
    assert res.delivered_friction_force_n > 0.0


def test_10_charge_power_restriction(
    default_gearbox, default_motor, default_inverter, default_battery_config, default_battery_state
):
    """Test 10: Charge power limit (20 kW) curtails battery charging and preserves braking demand."""
    cfg_p_limit = default_battery_config.model_copy(update={"max_charge_power_kw": 20.0})
    res = simulate_integrated_powertrain_step(
        requested_wheel_force_n=-4000.0,
        vehicle_speed_ms=25.0,
        dt_s=1.0,
        battery_state=default_battery_state,
        battery_config=cfg_p_limit,
        gearbox_config=default_gearbox,
        motor_config=default_motor,
        inverter_config=default_inverter,
    )

    assert res.accepted_battery_power_kw == pytest.approx(20.0, abs=1e-2)
    assert res.delivered_wheel_force_n == pytest.approx(4000.0, rel=1e-3)
    assert res.delivered_friction_force_n > 0.0


def test_11_terminal_overvoltage_restriction(
    default_gearbox, default_motor, default_inverter, default_battery_config, default_battery_state
):
    """Test 11: Terminal overvoltage cutoff limits battery charging voltage."""
    state_high_v = default_battery_state.__class__(
        soc=0.96,
        v1_polarization_v=3.0,
        temperature_c=25.0,
        state_of_health=1.0,
        cumulative_energy_throughput_kwh=0.0,
        provenance_status=DataStatus.REAL,
    )
    res = simulate_integrated_powertrain_step(
        requested_wheel_force_n=-5000.0,
        vehicle_speed_ms=25.0,
        dt_s=1.0,
        battery_state=state_high_v,
        battery_config=default_battery_config,
        gearbox_config=default_gearbox,
        motor_config=default_motor,
        inverter_config=default_inverter,
    )

    v_pack_max = default_battery_config.cell_voltage_max_v * default_battery_config.series_cells
    assert res.terminal_voltage_avg_v <= v_pack_max + 1e-4
    assert res.delivered_wheel_force_n == pytest.approx(5000.0, rel=1e-3)


def test_12_battery_discharge(
    default_gearbox, default_motor, default_inverter, default_battery_config, default_battery_state
):
    """Test 12: Traction demand discharges battery with correct signs and energy ledger balance."""
    res = simulate_integrated_powertrain_step(
        requested_wheel_force_n=2500.0,  # Traction demand
        vehicle_speed_ms=20.0,
        dt_s=1.0,
        battery_state=default_battery_state,
        battery_config=default_battery_config,
        gearbox_config=default_gearbox,
        motor_config=default_motor,
        inverter_config=default_inverter,
        auxiliary_lv_power_kw=1.0,
    )

    assert res.is_braking_mode is False
    assert res.accepted_battery_power_kw < 0.0  # Discharging
    assert res.battery_current_a < 0.0
    assert res.delta_soc < 0.0
    assert abs(res.energy_accounting_residual_j) < 1e-3


def test_13_discharge_current_restriction(
    default_gearbox, default_motor, default_inverter, default_battery_config, default_battery_state
):
    """Test 13: Discharge current rating curtails battery discharge during heavy traction."""
    cfg_dis_i = default_battery_config.model_copy(update={"max_discharge_current_a": -50.0})
    res = simulate_integrated_powertrain_step(
        requested_wheel_force_n=4000.0,
        vehicle_speed_ms=25.0,
        dt_s=1.0,
        battery_state=default_battery_state,
        battery_config=cfg_dis_i,
        gearbox_config=default_gearbox,
        motor_config=default_motor,
        inverter_config=default_inverter,
    )

    assert pytest.approx(res.battery_current_a, abs=1e-2) == -50.0
    assert res.unserved_electrical_power_kw > 0.0


def test_14_discharge_power_restriction(
    default_gearbox, default_motor, default_inverter, default_battery_config, default_battery_state
):
    """Test 14: Discharge power rating curtails battery discharge."""
    cfg_dis_p = default_battery_config.model_copy(update={"max_discharge_power_kw": -25.0})
    res = simulate_integrated_powertrain_step(
        requested_wheel_force_n=4000.0,
        vehicle_speed_ms=25.0,
        dt_s=1.0,
        battery_state=default_battery_state,
        battery_config=cfg_dis_p,
        gearbox_config=default_gearbox,
        motor_config=default_motor,
        inverter_config=default_inverter,
    )

    assert pytest.approx(res.accepted_battery_power_kw, abs=1e-2) == -25.0
    assert res.unserved_electrical_power_kw > 0.0


def test_15_auxiliary_load_greater_than_available_generation(
    default_gearbox, default_motor, default_inverter, default_battery_config, default_battery_state
):
    """Test 15: Mild regen with high auxiliary load produces net battery discharge request."""
    # 500 N braking at 5 m/s = 2.5 kW wheel retarding power
    # 4 kW LV auxiliary load converts to ~4.35 kW HV load > gross regen (~2.0 kW)
    res = simulate_integrated_powertrain_step(
        requested_wheel_force_n=-500.0,
        vehicle_speed_ms=5.0,
        dt_s=1.0,
        battery_state=default_battery_state,
        battery_config=default_battery_config,
        gearbox_config=default_gearbox,
        motor_config=default_motor,
        inverter_config=default_inverter,
        auxiliary_lv_power_kw=4.0,
    )

    assert res.is_braking_mode is True
    # Net battery power is negative (battery discharges to assist auxiliaries)
    assert res.requested_battery_power_kw < 0.0
    assert res.accepted_battery_power_kw < 0.0
    assert res.rejected_regen_electrical_power_kw == 0.0


def test_16_zero_power_operation(
    default_gearbox, default_motor, default_inverter, default_battery_config, default_battery_state
):
    """Test 16: Zero wheel force at cruise maintains zero traction work while powering auxiliaries."""
    res = simulate_integrated_powertrain_step(
        requested_wheel_force_n=0.0,
        vehicle_speed_ms=20.0,
        dt_s=1.0,
        battery_state=default_battery_state,
        battery_config=default_battery_config,
        gearbox_config=default_gearbox,
        motor_config=default_motor,
        inverter_config=default_inverter,
        auxiliary_lv_power_kw=1.0,
    )

    assert res.delivered_wheel_force_n == 0.0
    assert res.accepted_battery_power_kw < 0.0  # Powers 1 kW aux load
    assert abs(res.energy_accounting_residual_j) < 1e-3


def test_17_standstill(
    default_gearbox, default_motor, default_inverter, default_battery_config, default_battery_state
):
    """Test 17: Vehicle standstill (v = 0 m/s) avoids division by zero and correctly handles standby."""
    res = simulate_integrated_powertrain_step(
        requested_wheel_force_n=0.0,
        vehicle_speed_ms=0.0,
        dt_s=2.0,
        battery_state=default_battery_state,
        battery_config=default_battery_config,
        gearbox_config=default_gearbox,
        motor_config=default_motor,
        inverter_config=default_inverter,
        auxiliary_lv_power_kw=0.5,
    )

    assert res.vehicle_speed_ms == 0.0
    assert res.delivered_wheel_force_n == 0.0
    assert res.delivered_wheel_power_kw == 0.0
    assert res.accepted_battery_power_kw < 0.0  # Powers standby + aux
    assert abs(res.energy_accounting_residual_j) < 1e-3


def test_18_low_speed_regeneration(
    default_gearbox, default_motor, default_inverter, default_battery_config, default_battery_state
):
    """Test 18: Speed below v_cutoff (0.5 m/s) disables regen completely; 100% friction braking."""
    blend_cfg = BrakeBlendingConfig(v_cutoff_ms=1.0, v_blend_start_ms=3.0)
    res_cutoff = simulate_integrated_powertrain_step(
        requested_wheel_force_n=-2000.0,
        vehicle_speed_ms=0.5,
        dt_s=1.0,
        battery_state=default_battery_state,
        battery_config=default_battery_config,
        gearbox_config=default_gearbox,
        motor_config=default_motor,
        inverter_config=default_inverter,
        blending_config=blend_cfg,
    )

    assert res_cutoff.delivered_wheel_force_n == pytest.approx(2000.0, rel=1e-3)
    assert res_cutoff.delivered_regen_force_n == 0.0
    assert res_cutoff.delivered_friction_force_n == pytest.approx(2000.0, rel=1e-3)


def test_19_sudden_changes_in_requested_power(
    default_gearbox, default_motor, default_inverter, default_battery_config, default_battery_state
):
    """Test 19: Sudden step-change from full traction (+3000 N) to full braking (-4000 N)."""
    # Step 1: Traction
    res1 = simulate_integrated_powertrain_step(
        requested_wheel_force_n=3000.0,
        vehicle_speed_ms=20.0,
        dt_s=1.0,
        battery_state=default_battery_state,
        battery_config=default_battery_config,
        gearbox_config=default_gearbox,
        motor_config=default_motor,
        inverter_config=default_inverter,
    )
    assert res1.accepted_battery_power_kw < 0.0

    # Step 2: Instantaneous flip to hard braking
    res2 = simulate_integrated_powertrain_step(
        requested_wheel_force_n=-4000.0,
        vehicle_speed_ms=20.0,
        dt_s=1.0,
        battery_state=res1.final_battery_state,
        battery_config=default_battery_config,
        gearbox_config=default_gearbox,
        motor_config=default_motor,
        inverter_config=default_inverter,
    )
    assert res2.delivered_wheel_force_n == pytest.approx(4000.0, rel=1e-3)
    assert abs(res2.energy_accounting_residual_j) < 1e-3


def test_20_multi_step_driving_cycle(
    default_gearbox, default_motor, default_inverter, default_battery_config, default_battery_state
):
    """Test 20: 10-step drive cycle tracking persistent battery state across consecutive steps."""
    state = default_battery_state
    forces = [1500.0, 2500.0, 1000.0, 0.0, -1500.0, -2500.0, -500.0, 0.0, 2000.0, -2000.0]
    speeds = [10.0, 15.0, 20.0, 20.0, 18.0, 14.0, 10.0, 8.0, 12.0, 9.0]

    for f_req, v_cur in zip(forces, speeds):
        res = simulate_integrated_powertrain_step(
            requested_wheel_force_n=f_req,
            vehicle_speed_ms=v_cur,
            dt_s=1.0,
            battery_state=state,
            battery_config=default_battery_config,
            gearbox_config=default_gearbox,
            motor_config=default_motor,
            inverter_config=default_inverter,
        )
        assert abs(res.energy_accounting_residual_j) < 1e-3
        state = res.final_battery_state


def test_21_repeated_regenerative_braking_events(
    default_gearbox, default_motor, default_inverter, default_battery_config, default_battery_state
):
    """Test 21: Repeated regen pulses build up polarization voltage V1 dynamically."""
    state = default_battery_state
    for _ in range(5):
        res = simulate_integrated_powertrain_step(
            requested_wheel_force_n=-2000.0,
            vehicle_speed_ms=20.0,
            dt_s=2.0,
            battery_state=state,
            battery_config=default_battery_config,
            gearbox_config=default_gearbox,
            motor_config=default_motor,
            inverter_config=default_inverter,
        )
        assert res.delta_v1_v > 0.0
        state = res.final_battery_state

    # Polarization overpotential accumulated over consecutive pulses
    assert state.v1_polarization_v > 0.4


def test_22_alternating_traction_and_regeneration(
    default_gearbox, default_motor, default_inverter, default_battery_config, default_battery_state
):
    """Test 22: Alternating positive and negative wheel forces with exact conservation."""
    state = default_battery_state
    for i in range(6):
        force = 2000.0 if (i % 2 == 0) else -2000.0
        res = simulate_integrated_powertrain_step(
            requested_wheel_force_n=force,
            vehicle_speed_ms=15.0,
            dt_s=1.0,
            battery_state=state,
            battery_config=default_battery_config,
            gearbox_config=default_gearbox,
            motor_config=default_motor,
            inverter_config=default_inverter,
        )
        assert abs(res.energy_accounting_residual_j) < 1e-3
        state = res.final_battery_state


def test_23_battery_unable_to_accept_full_regenerative_request(
    default_gearbox, default_motor, default_inverter, default_battery_config, default_battery_state
):
    """Test 23: Battery capping charging power identifies rejected electrical energy explicitly."""
    cfg_capped = default_battery_config.model_copy(update={"max_charge_power_kw": 15.0})
    res = simulate_integrated_powertrain_step(
        requested_wheel_force_n=-3000.0,
        vehicle_speed_ms=25.0,
        dt_s=1.0,
        battery_state=default_battery_state,
        battery_config=cfg_capped,
        gearbox_config=default_gearbox,
        motor_config=default_motor,
        inverter_config=default_inverter,
        bms_config_override=BMSConfig(max_charge_power_kw=65.0, status=DataStatus.REAL),
    )

    assert pytest.approx(res.accepted_battery_power_kw, abs=1e-2) == 15.0
    assert res.rejected_regen_electrical_power_kw > 0.0
    assert res.rejected_regen_electrical_energy_j > 0.0


def test_24_complete_friction_brake_reconciliation(
    default_gearbox, default_motor, default_inverter, default_battery_config, default_battery_state
):
    """Test 24: Friction brake reconciliation preserves 100% of driver-demanded braking force."""
    cfg_capped = default_battery_config.model_copy(update={"max_charge_power_kw": 10.0})
    res = simulate_integrated_powertrain_step(
        requested_wheel_force_n=-3500.0,
        vehicle_speed_ms=20.0,
        dt_s=1.0,
        battery_state=default_battery_state,
        battery_config=cfg_capped,
        gearbox_config=default_gearbox,
        motor_config=default_motor,
        inverter_config=default_inverter,
        bms_config_override=BMSConfig(max_charge_power_kw=65.0, status=DataStatus.REAL),
    )

    assert res.delivered_wheel_force_n == pytest.approx(3500.0, rel=1e-3)
    assert res.additional_friction_force_n > 0.0
    assert res.braking_deficit_force_n == 0.0


def test_25_energy_conservation_across_integrated_path(
    default_gearbox, default_motor, default_inverter, default_battery_config, default_battery_state
):
    """Test 25: Multi-boundary energy conservation ledger verifies across both braking and traction."""
    # 1. Braking step
    res_brake = simulate_integrated_powertrain_step(
        requested_wheel_force_n=-2500.0,
        vehicle_speed_ms=18.0,
        dt_s=1.5,
        battery_state=default_battery_state,
        battery_config=default_battery_config,
        gearbox_config=default_gearbox,
        motor_config=default_motor,
        inverter_config=default_inverter,
        auxiliary_lv_power_kw=1.0,
    )
    assert abs(res_brake.energy_accounting_residual_j) < 1e-3
    assert abs(res_brake.battery_simulation_result.energy_residual_j) < 1e-5

    # 2. Traction step
    res_trac = simulate_integrated_powertrain_step(
        requested_wheel_force_n=2500.0,
        vehicle_speed_ms=18.0,
        dt_s=1.5,
        battery_state=res_brake.final_battery_state,
        battery_config=default_battery_config,
        gearbox_config=default_gearbox,
        motor_config=default_motor,
        inverter_config=default_inverter,
        auxiliary_lv_power_kw=1.0,
    )
    assert abs(res_trac.energy_accounting_residual_j) < 1e-3
    assert abs(res_trac.battery_simulation_result.energy_residual_j) < 1e-5


# =============================================================================
# DEFECT REGRESSION TESTS (C3-INT-01 THROUGH C3-REGEN-01)
# =============================================================================

def test_c3_int_01_traction_curtailment_when_battery_limited(
    default_gearbox, default_motor, default_inverter, default_battery_config, default_battery_state
):
    """
    C3-INT-01: Traction Curtailment Verification.
    When battery discharge is limited, delivered wheel force and power MUST be curtailed
    below requested values, and unmet demand must be explicitly flagged.
    """
    # Cap battery discharge power to -10 kW (while requested traction requires ~60 kW)
    cfg_capped = default_battery_config.model_copy(update={"max_discharge_power_kw": -10.0})

    res = simulate_integrated_powertrain_step(
        requested_wheel_force_n=3000.0,
        vehicle_speed_ms=20.0,  # Requested wheel power = 60 kW
        dt_s=1.0,
        battery_state=default_battery_state,
        battery_config=cfg_capped,
        gearbox_config=default_gearbox,
        motor_config=default_motor,
        inverter_config=default_inverter,
    )

    # Delivered wheel force and power MUST be curtailed below requested
    assert res.delivered_wheel_force_n < 3000.0
    assert res.delivered_wheel_power_kw < 60.0
    assert res.delivered_wheel_force_n > 0.0  # Still delivers what battery allows

    # Traction deficit must be positive and equal requested minus delivered
    assert res.traction_deficit_force_n == pytest.approx(3000.0 - res.delivered_wheel_force_n, rel=1e-4)
    assert res.traction_deficit_power_kw == pytest.approx(60.0 - res.delivered_wheel_power_kw, rel=1e-4)
    assert res.traction_deficit_force_n > 0.0

    # Status must be VIOLATED due to unmet traction demand
    assert res.overall_status == ConstraintStatus.VIOLATED
    assert "ERR_TRACTION_FORCE_CURTAILED" in res.active_constraints
    assert abs(res.energy_accounting_residual_j) < 1e-3


def test_c3_int_01_traction_zero_speed_handling(
    default_gearbox, default_motor, default_inverter, default_battery_config, default_battery_state
):
    """C3-INT-01: Traction at zero and low speed handles power-to-force conversion without division by zero."""
    # At standstill v = 0, mechanical power is zero; no division by zero occurs
    res_zero = simulate_integrated_powertrain_step(
        requested_wheel_force_n=2000.0,
        vehicle_speed_ms=0.0,
        dt_s=1.0,
        battery_state=default_battery_state,
        battery_config=default_battery_config,
        gearbox_config=default_gearbox,
        motor_config=default_motor,
        inverter_config=default_inverter,
    )
    assert res_zero.delivered_wheel_force_n == 0.0
    assert res_zero.delivered_wheel_power_kw == 0.0
    assert abs(res_zero.energy_accounting_residual_j) < 1e-3

    # At low non-zero speed (e.g. 1.0 m/s), full traction force is delivered smoothly
    res_low = simulate_integrated_powertrain_step(
        requested_wheel_force_n=2000.0,
        vehicle_speed_ms=1.0,
        dt_s=1.0,
        battery_state=default_battery_state,
        battery_config=default_battery_config,
        gearbox_config=default_gearbox,
        motor_config=default_motor,
        inverter_config=default_inverter,
    )
    assert res_low.delivered_wheel_force_n == pytest.approx(2000.0, rel=1e-3)
    assert res_low.delivered_wheel_power_kw == pytest.approx(2.0, rel=1e-3)
    assert abs(res_low.energy_accounting_residual_j) < 1e-3


def test_c3_int_02_direction_specific_drivetrain_efficiencies(
    default_gearbox, default_motor, default_inverter, default_battery_config, default_battery_state
):
    """
    C3-INT-02: Direction-specific efficiencies affect battery demand correctly.
    Lower motor traction efficiency requires MORE battery discharge for identical wheel mechanical power.
    """
    mot_high_eff = default_motor.model_copy(update={"efficiency_mot": 0.95})
    mot_low_eff = default_motor.model_copy(update={"efficiency_mot": 0.80})

    res_high = simulate_integrated_powertrain_step(
        requested_wheel_force_n=2000.0,
        vehicle_speed_ms=20.0,
        dt_s=1.0,
        battery_state=default_battery_state,
        battery_config=default_battery_config,
        gearbox_config=default_gearbox,
        motor_config=mot_high_eff,
        inverter_config=default_inverter,
    )

    res_low = simulate_integrated_powertrain_step(
        requested_wheel_force_n=2000.0,
        vehicle_speed_ms=20.0,
        dt_s=1.0,
        battery_state=default_battery_state,
        battery_config=default_battery_config,
        gearbox_config=default_gearbox,
        motor_config=mot_low_eff,
        inverter_config=default_inverter,
    )

    # Both achieve requested wheel force
    assert res_high.delivered_wheel_force_n == pytest.approx(2000.0, rel=1e-3)
    assert res_low.delivered_wheel_force_n == pytest.approx(2000.0, rel=1e-3)

    # Lower motor efficiency extracts MORE discharge power from battery: |P_batt_low| > |P_batt_high|
    assert abs(res_low.accepted_battery_power_kw) > abs(res_high.accepted_battery_power_kw)
    assert res_low.energy_drivetrain_loss_j > res_high.energy_drivetrain_loss_j
    assert abs(res_high.energy_accounting_residual_j) < 1e-3
    assert abs(res_low.energy_accounting_residual_j) < 1e-3


def test_c3_int_03_unserved_power_not_disguised_as_drivetrain_loss(
    default_gearbox, default_motor, default_inverter, default_battery_config, default_battery_state
):
    """
    C3-INT-03: End-to-end energy accounting separates unserved demand from drivetrain losses.
    Unserved demand must not be counted as consumed energy.
    """
    cfg_capped = default_battery_config.model_copy(update={"max_discharge_power_kw": -15.0})

    res = simulate_integrated_powertrain_step(
        requested_wheel_force_n=3000.0,
        vehicle_speed_ms=25.0,  # 75 kW requested
        dt_s=1.0,
        battery_state=default_battery_state,
        battery_config=cfg_capped,
        gearbox_config=default_gearbox,
        motor_config=default_motor,
        inverter_config=default_inverter,
        auxiliary_lv_power_kw=2.0,
    )

    # Unserved power and energy are positive
    assert res.unserved_electrical_power_kw > 0.0
    assert res.energy_unserved_traction_j > 0.0

    # Only actual consumed energy enters the energy ledger
    # |E_batt| == E_wheel_delivered + E_drivetrain_loss + E_standby + E_aux_supplied
    assert abs(res.energy_accounting_residual_j) < 1e-3
    assert res.energy_wheel_delivered_j == pytest.approx(res.delivered_wheel_power_kw * 1000.0, rel=1e-4)


def test_c3_bms_01_zero_bms_acceptance_preservation(
    default_battery_config, default_battery_state
):
    """
    C3-BMS-01: Zero BMS acceptance remains strictly 0.0 without artificial positive floor.
    """
    # 1. State at maximum operating SOC
    state_max_soc = default_battery_state.__class__(
        soc=0.98,
        v1_polarization_v=0.0,
        temperature_c=25.0,
        state_of_health=1.0,
        cumulative_energy_throughput_kwh=0.0,
        provenance_status=DataStatus.REAL,
    )
    bms_cfg = create_dynamic_bms_config(default_battery_config, state_max_soc, 1.0)
    assert bms_cfg.max_charge_power_kw == 0.0
    assert bms_cfg.max_charge_current_a == 0.0
    assert isinstance(bms_cfg, BMSConfig)


def test_c3_bat_01_soc_boundary_crossing_long_timestep(
    default_battery_config, default_battery_state
):
    """
    C3-BAT-01: Timestep integration curtails charging/discharging to prevent crossing SOC boundaries.
    """
    # Starting at SOC = 0.96 with soc_max_operating = 0.98
    state_high = default_battery_state.__class__(
        soc=0.96,
        v1_polarization_v=0.0,
        temperature_c=25.0,
        state_of_health=1.0,
        cumulative_energy_throughput_kwh=0.0,
        provenance_status=DataStatus.REAL,
    )

    # Long timestep (dt = 300 s) with high charging power request (60 kW)
    # Without dynamic SOC current bounds, this would charge ~5 kWh into a 21 kWh pack, pushing SOC to > 1.15!
    res = simulate_battery_step(60.0, state_high, 300.0, default_battery_config)

    # Final SOC must not exceed soc_max_operating (0.98)
    assert res.final_state.soc <= default_battery_config.soc_max_operating + 1e-6
    assert res.operating_point.is_soc_limited is True
    assert "ERR_BATTERY_SOC_MAX_REACHED" in res.active_constraints
    assert abs(res.energy_residual_j) < 1e-5


def test_c3_bat_02_discharge_coulombic_efficiency_validation():
    """
    C3-BAT-02: coulombic_efficiency_dis must be exactly 1.0; configurations < 1.0 are rejected.
    """
    with pytest.raises(ValueError, match="coulombic_efficiency_dis must be exactly 1.0"):
        BatteryConfig(coulombic_efficiency_dis=0.95)


def test_c3_bat_03_zero_r0_initial_voltage_validation(default_battery_config, default_battery_state):
    """
    C3-BAT-03: Zero R0 detects already-invalid initial terminal voltage.
    """
    cfg_zero_r0 = default_battery_config.model_copy(update={"r0_pack_baseline_ohm": 0.0})
    # Initial polarization voltage 25 V pushes initial terminal voltage above 403.2 V max cutoff
    state_overvoltage = default_battery_state.__class__(
        soc=0.97,
        v1_polarization_v=25.0,
        temperature_c=25.0,
        state_of_health=1.0,
        cumulative_energy_throughput_kwh=0.0,
        provenance_status=DataStatus.REAL,
    )

    res = simulate_battery_step(10.0, state_overvoltage, 1.0, cfg_zero_r0)
    assert "ERR_BATTERY_OVERVOLTAGE_CUTOFF" in res.active_constraints
    assert res.accepted_power_kw <= 0.0  # Charging prohibited
    assert res.overall_status == ConstraintStatus.VIOLATED


def test_c3_val_01_invalid_state_and_config_validation(default_battery_config):
    """
    C3-VAL-01: State and configuration classes reject non-physical inputs.
    """
    # Invalid SOC in BatteryState
    with pytest.raises(ValueError, match="BatteryState soc must be finite in"):
        BatteryState(soc=1.5, v1_polarization_v=0.0, temperature_c=25.0, state_of_health=1.0, cumulative_energy_throughput_kwh=0.0, provenance_status=DataStatus.REAL)

    # Invalid SOH in BatteryState
    with pytest.raises(ValueError, match="BatteryState state_of_health must be finite in"):
        BatteryState(soc=0.5, v1_polarization_v=0.0, temperature_c=25.0, state_of_health=0.0, cumulative_energy_throughput_kwh=0.0, provenance_status=DataStatus.REAL)

    # Negative throughput in BatteryState
    with pytest.raises(ValueError, match="BatteryState cumulative_energy_throughput_kwh must be finite >= 0.0"):
        BatteryState(soc=0.5, v1_polarization_v=0.0, temperature_c=25.0, state_of_health=1.0, cumulative_energy_throughput_kwh=-5.0, provenance_status=DataStatus.REAL)
