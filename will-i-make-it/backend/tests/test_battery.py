"""
Unit Test Suite for Dynamic 1-RC Thevenin Battery Model (Stage C3 Phase 2.1)
=============================================================================
Validates:
1. Open-circuit voltage (OCV) and internal impedance calculations.
2. Numerically stable quadratic current solver across charge, discharge, and zero-R0 limits.
3. Exact internal 1-RC energy conservation ledger: E_term == E_oc + E_R0 + E_R1 + delta_E_C1.
4. Polarization overpotential ZOH dynamic integration and asymptotic relaxation.
5. Coulomb counting SOC integration and Coulombic efficiency.
6. Joint boundary arbitration (voltage cutoffs, current ratings, power limits, SOC limits).
7. Physical loss non-negativity (E_loss_R0 >= 0, E_loss_R1 >= 0, E_loss_parasitic >= 0).
8. Parameter and runtime provenance tracking with separated impedance flags.
9. DEF-C3-01: Zero-R0 discharge deficit crash prevention (no UnboundLocalError).
10. DEF-C3-03: Empty feasible interval detection (ERR_BATTERY_INFEASIBLE_BOUNDS).
11. DEF-C3-04: Monotonic power mapping and maximum power transfer vertex adherence.
12. DEF-C3-05: Pydantic curve validation (monotonicity, boundaries, positive values).
13. DEF-C3-06: Coulombic efficiency and parasitic electrochemical dissipation accounting.
14. DEF-C3-07: High-precision expm1 and series evaluation across tiny and large timesteps.
15. TEST-C3-01 & TEST-C3-02: Independent hand-calculated numerical benchmark tests.
"""
from __future__ import annotations

import math
import pytest
from pydantic import ValidationError

from app.domain.provenance import DataStatus
from app.services.energy.powertrain_model import ConstraintStatus
from app.services.energy.battery_model import (
    BatteryConfig,
    BatteryState,
    TheveninParameters,
    BatteryOperatingPoint,
    BatterySimulationResult,
    compute_ocv,
    compute_internal_resistance,
    solve_battery_current,
    integrate_battery_state,
    simulate_battery_step,
    _compute_tau_exponential_factors,
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
def default_initial_state() -> BatteryState:
    return BatteryState(
        soc=0.50,
        v1_polarization_v=0.0,
        temperature_c=25.0,
        state_of_health=1.0,
        cumulative_energy_throughput_kwh=0.0,
        provenance_status=DataStatus.REAL,
    )


# =============================================================================
# 1. OCV & IMPEDANCE CHARACTERIZATION
# =============================================================================

def test_ocv_monotonicity_and_bounds(default_battery_config: BatteryConfig):
    """Verify OCV is monotonically increasing with SOC and bounded within cell limits."""
    soc_points = [0.0, 0.1, 0.25, 0.5, 0.75, 0.9, 1.0]
    ocvs = [compute_ocv(s, 25.0, default_battery_config)[0] for s in soc_points]

    v_min_pack = default_battery_config.cell_voltage_min_v * default_battery_config.series_cells
    v_max_pack = default_battery_config.cell_voltage_max_v * default_battery_config.series_cells

    for v in ocvs:
        assert v_min_pack <= v <= v_max_pack

    for i in range(len(ocvs) - 1):
        assert ocvs[i] < ocvs[i + 1]


def test_verified_custom_ocv_table(default_battery_config: BatteryConfig):
    """Verify interpolation when explicit verified characterization curve is provided."""
    custom_curve = [(0.0, 3.0), (0.5, 3.7), (1.0, 4.2)]
    cfg = default_battery_config.model_copy(update={"ocv_curve": custom_curve})

    v_pack, is_ver = compute_ocv(0.25, 25.0, cfg)
    # At SOC 0.25, cell OCV = 3.0 + 0.5 * (3.7 - 3.0) = 3.35 V
    expected_pack_v = 3.35 * 96
    assert pytest.approx(v_pack, rel=1e-5) == expected_pack_v
    assert is_ver is True


def test_internal_resistance_temperature_derating(default_battery_config: BatteryConfig):
    """Verify internal resistance increases sharply at low cold temperatures."""
    p_warm = compute_internal_resistance(0.50, 25.0, default_battery_config)
    p_cold = compute_internal_resistance(0.50, -10.0, default_battery_config)

    assert p_cold.r0_ohm > p_warm.r0_ohm * 1.5
    assert p_cold.r1_ohm > p_warm.r1_ohm * 1.5


# =============================================================================
# 2. NUMERICALLY STABLE QUADRATIC CURRENT SOLVER
# =============================================================================

def test_current_solver_charge_discharge_and_zero():
    """Verify solve_battery_current across charging, discharging, and zero power against hand roots."""
    v0 = 360.0
    r0 = 0.040

    # 1. Charging: +36 kW
    # 0.04 * I^2 + 360 * I - 36000 = 0 => I = (-360 + sqrt(360^2 + 4 * 0.04 * 36000)) / (2 * 0.04) = 98.91288... A
    i_chg, p_chg, real_chg = solve_battery_current(36.0, v0, r0)
    assert real_chg is True
    assert pytest.approx(i_chg, rel=1e-5) == 98.91288
    v_term_chg = v0 + i_chg * r0
    assert pytest.approx((v_term_chg * i_chg) / 1000.0, rel=1e-5) == 36.0

    # 2. Discharging: -36 kW
    # 0.04 * I^2 + 360 * I + 36000 = 0 => I = (-360 + sqrt(360^2 - 4 * 0.04 * 36000)) / (2 * 0.04) = -101.13651... A
    i_dis, p_dis, real_dis = solve_battery_current(-36.0, v0, r0)
    assert real_dis is True
    assert pytest.approx(i_dis, rel=1e-5) == -101.13651
    v_term_dis = v0 + i_dis * r0
    assert pytest.approx((v_term_dis * i_dis) / 1000.0, rel=1e-5) == -36.0

    # 3. Zero power: 0 kW -> 0 A
    i_zero, p_zero, real_zero = solve_battery_current(0.0, v0, r0)
    assert real_zero is True
    assert i_zero == 0.0


def test_current_solver_zero_resistance_limit():
    """Verify solve_battery_current gracefully handles zero internal resistance."""
    v0 = 360.0
    r0 = 0.0

    i_sol, p_sol, real_sol = solve_battery_current(36.0, v0, r0)
    assert real_sol is True
    assert pytest.approx(i_sol, rel=1e-5) == 36000.0 / 360.0  # Exactly 100 A


def test_current_solver_max_power_transfer_limit():
    """Verify maximum power transfer limit detection when discharge demand exceeds V0^2 / 4R0."""
    v0 = 360.0
    r0 = 0.040
    # Max transfer = -360^2 / (4 * 0.04) = -129600 / 0.16 = -810,000 W = -810 kW
    p_impossible_kw = -900.0

    i_peak, p_peak_kw, real_root = solve_battery_current(p_impossible_kw, v0, r0)
    assert real_root is False
    assert pytest.approx(p_peak_kw, rel=1e-5) == -810.0
    assert pytest.approx(i_peak, rel=1e-5) == -360.0 / (2 * 0.040)  # -4500 A


# =============================================================================
# 3. EXACT INTERNAL 1-RC ENERGY CONSERVATION LEDGER
# =============================================================================

def test_energy_conservation_ledger_charging(
    default_battery_config: BatteryConfig,
    default_initial_state: BatteryState,
):
    """
    Verify exact internal energy conservation ledger on charging:
    E_term == E_chem + E_loss_parasitic + E_loss_R0 + E_loss_R1 + delta_E_C1
    Residual must be strictly zero: abs(energy_residual_j) < 1e-5 J.
    """
    dt = 1.0  # 1 second step
    res = simulate_battery_step(
        requested_power_kw=40.0,
        state=default_initial_state,
        dt_s=dt,
        config=default_battery_config,
    )

    assert res.accepted_power_kw > 0.0
    assert res.operating_point.current_a > 0.0
    assert res.operating_point.p_loss_r0_kw > 0.0
    assert res.energy_loss_r0_j > 0.0
    assert res.energy_loss_r1_j >= 0.0
    assert res.energy_loss_parasitic_j > 0.0  # 1% parasitic loss from eta_chg = 0.99
    assert res.delta_energy_c1_j > 0.0  # Charging capacitor C1

    # Exact energy conservation ledger identity
    e_sum = res.energy_ocv_j + res.energy_loss_r0_j + res.energy_loss_r1_j + res.delta_energy_c1_j
    assert pytest.approx(res.energy_terminal_j, rel=1e-5) == e_sum

    e_chem_sum = res.energy_chem_j + res.energy_loss_parasitic_j + res.energy_loss_r0_j + res.energy_loss_r1_j + res.delta_energy_c1_j
    assert pytest.approx(res.energy_terminal_j, rel=1e-5) == e_chem_sum
    assert abs(res.energy_residual_j) < 1e-5


def test_energy_conservation_ledger_discharging(
    default_battery_config: BatteryConfig,
    default_initial_state: BatteryState,
):
    """
    Verify exact internal energy conservation ledger on discharging:
    E_term (< 0) == E_oc (< 0) + E_loss_R0 (> 0) + E_loss_R1 (> 0) + delta_E_C1
    Ohmic and polarization losses remain strictly non-negative!
    """
    dt = 2.0
    res = simulate_battery_step(
        requested_power_kw=-50.0,
        state=default_initial_state,
        dt_s=dt,
        config=default_battery_config,
    )

    assert res.accepted_power_kw < 0.0
    assert res.operating_point.current_a < 0.0
    assert res.energy_loss_r0_j > 0.0
    assert res.energy_loss_r1_j >= 0.0
    assert res.energy_loss_parasitic_j == 0.0  # Zero on discharge

    e_sum = res.energy_ocv_j + res.energy_loss_r0_j + res.energy_loss_r1_j + res.delta_energy_c1_j
    assert pytest.approx(res.energy_terminal_j, rel=1e-5) == e_sum
    assert abs(res.energy_residual_j) < 1e-5


def test_energy_conservation_relaxation_step(
    default_battery_config: BatteryConfig,
    default_initial_state: BatteryState,
):
    """
    Verify relaxation step (I = 0) with pre-existing polarization voltage V1:
    - E_term = 0 J (open circuit)
    - Polarization capacitor discharges through R1: delta_E_C1 < 0, E_loss_R1 > 0
    - delta_E_C1 + E_loss_R1 == 0 J!
    """
    state_polarized = BatteryState(
        soc=0.50,
        v1_polarization_v=5.0,  # 5 Volts across C1
        temperature_c=25.0,
        state_of_health=1.0,
        cumulative_energy_throughput_kwh=10.0,
        provenance_status=DataStatus.REAL,
    )

    res = simulate_battery_step(
        requested_power_kw=0.0,
        state=state_polarized,
        dt_s=5.0,
        config=default_battery_config,
    )

    assert res.operating_point.current_a == 0.0
    assert res.energy_terminal_j == 0.0
    assert res.energy_ocv_j == 0.0
    assert res.energy_loss_r0_j == 0.0
    assert res.delta_energy_c1_j < 0.0  # Capacitor lost energy
    assert res.energy_loss_r1_j > 0.0   # Dissipated as heat in R1
    # Energy lost by C1 exactly equals heat in R1:
    assert pytest.approx(res.energy_loss_r1_j, rel=1e-5) == -res.delta_energy_c1_j
    assert abs(res.energy_residual_j) < 1e-5


# =============================================================================
# 4. POLARIZATION DYNAMICS & COULOMB COUNTING
# =============================================================================

def test_polarization_exponential_asymptotic_convergence(
    default_battery_config: BatteryConfig,
    default_initial_state: BatteryState,
):
    """Verify polarization voltage converges exponentially toward I * R1 under constant current."""
    params = compute_internal_resistance(0.50, 25.0, default_battery_config)
    r1 = params.r1_ohm
    tau1 = params.tau1_s
    i_const = 50.0
    v1_asymptotic = i_const * r1

    state = default_initial_state
    for _ in range(5):
        state, _, _, _ = integrate_battery_state(state, i_const, params, dt_s=tau1, config=default_battery_config)

    # After 5 time constants, (1 - exp(-5)) > 0.993
    assert pytest.approx(state.v1_polarization_v, rel=1e-2) == v1_asymptotic


def test_coulomb_counting_soc_integration(
    default_battery_config: BatteryConfig,
    default_initial_state: BatteryState,
):
    """Verify Coulomb counting updates SOC accurately under charging and discharging."""
    params = compute_internal_resistance(0.50, 25.0, default_battery_config)
    # Charge with 60 A for 360 seconds (0.1 hour) on 60 Ah pack -> delta_soc = 0.1 * 0.99 = 0.099
    state_chg, _, _, _ = integrate_battery_state(default_initial_state, current_a=60.0, thevenin_params=params, dt_s=360.0, config=default_battery_config)
    assert pytest.approx(state_chg.soc, rel=1e-4) == 0.50 + 0.099

    # Discharge with -60 A for 360 seconds (eta_dis = 1.0) -> delta_soc = -0.10
    state_dis, _, _, _ = integrate_battery_state(default_initial_state, current_a=-60.0, thevenin_params=params, dt_s=360.0, config=default_battery_config)
    assert pytest.approx(state_dis.soc, rel=1e-4) == 0.40


# =============================================================================
# 5. JOINT BOUNDARY ARBITRATION
# =============================================================================

def test_joint_arbitration_pack_overvoltage_cutoff(
    default_battery_config: BatteryConfig,
    default_initial_state: BatteryState,
):
    """
    Verify pack overvoltage cutoff limits terminal charging power:
    Terminal voltage must not exceed cell_max_voltage * N_s (4.20 * 96 = 403.2 V).
    """
    state_high_soc = default_initial_state.__class__(
        soc=0.95,
        v1_polarization_v=2.0,
        temperature_c=25.0,
        state_of_health=1.0,
        cumulative_energy_throughput_kwh=0.0,
        provenance_status=DataStatus.REAL,
    )

    res = simulate_battery_step(
        requested_power_kw=100.0,
        state=state_high_soc,
        dt_s=1.0,
        config=default_battery_config,
    )

    v_max = default_battery_config.cell_voltage_max_v * default_battery_config.series_cells
    assert res.operating_point.terminal_voltage_v <= v_max + 1e-4
    assert res.accepted_power_kw < 100.0
    assert res.deficit_power_kw > 0.0
    assert abs(res.energy_residual_j) < 1e-5


def test_joint_arbitration_pack_undervoltage_cutoff(
    default_battery_config: BatteryConfig,
    default_initial_state: BatteryState,
):
    """
    Verify pack undervoltage cutoff limits terminal discharging power:
    Terminal voltage must not drop below cell_min_voltage * N_s (2.80 * 96 = 268.8 V).
    """
    state_low_soc = default_initial_state.__class__(
        soc=0.10,
        v1_polarization_v=-2.0,
        temperature_c=25.0,
        state_of_health=1.0,
        cumulative_energy_throughput_kwh=0.0,
        provenance_status=DataStatus.REAL,
    )

    res = simulate_battery_step(
        requested_power_kw=-150.0,
        state=state_low_soc,
        dt_s=1.0,
        config=default_battery_config,
    )

    v_min = default_battery_config.cell_voltage_min_v * default_battery_config.series_cells
    assert res.operating_point.terminal_voltage_v >= v_min - 1e-4
    assert res.accepted_power_kw > -150.0
    assert res.deficit_power_kw < 0.0
    assert abs(res.energy_residual_j) < 1e-5


def test_joint_arbitration_soc_operating_limits(
    default_battery_config: BatteryConfig,
    default_initial_state: BatteryState,
):
    """
    Verify charging is blocked when SOC >= soc_max_operating (0.98),
    and discharging is blocked when SOC <= soc_min_operating (0.05).
    """
    state_full = BatteryState(soc=0.99, v1_polarization_v=0.0, temperature_c=25.0, state_of_health=1.0, cumulative_energy_throughput_kwh=0.0, provenance_status=DataStatus.REAL)
    res_chg = simulate_battery_step(20.0, state_full, 1.0, default_battery_config)
    assert res_chg.accepted_power_kw == 0.0
    assert res_chg.operating_point.current_a == 0.0
    assert "ERR_BATTERY_SOC_MAX_REACHED" in res_chg.active_constraints

    state_empty = BatteryState(soc=0.04, v1_polarization_v=0.0, temperature_c=25.0, state_of_health=1.0, cumulative_energy_throughput_kwh=0.0, provenance_status=DataStatus.REAL)
    res_dis = simulate_battery_step(-20.0, state_empty, 1.0, default_battery_config)
    assert res_dis.accepted_power_kw == 0.0
    assert res_dis.operating_point.current_a == 0.0
    assert "ERR_BATTERY_SOC_MIN_REACHED" in res_dis.active_constraints

    # Dynamic projection over long timestep: discharge from 0.07 cannot drop below 0.05
    state_near_empty = BatteryState(soc=0.07, v1_polarization_v=0.0, temperature_c=25.0, state_of_health=1.0, cumulative_energy_throughput_kwh=0.0, provenance_status=DataStatus.REAL)
    res_proj = simulate_battery_step(-50.0, state_near_empty, 300.0, default_battery_config)
    assert res_proj.final_state.soc >= default_battery_config.soc_min_operating - 1e-6
    assert res_proj.operating_point.is_soc_limited is True
    assert "ERR_BATTERY_SOC_MIN_REACHED" in res_proj.active_constraints
    assert abs(res_proj.energy_residual_j) < 1e-5


def test_provenance_propagation_in_battery_simulation(
    default_battery_config: BatteryConfig,
    default_initial_state: BatteryState,
):
    """Verify conservative provenance combination across battery simulation (C3-PROV-01)."""
    # When curves are unverified (illustrative/estimated), provenance MUST degrade to ESTIMATED
    # even when config.status and input_status are REAL (preventing provenance leak)
    r_unverified = simulate_battery_step(10.0, default_initial_state, 1.0, default_battery_config, input_status=DataStatus.REAL)
    assert r_unverified.provenance_status == DataStatus.ESTIMATED

    # When all characterization curves are fully verified OEM data and input is REAL, result is REAL
    verified_cfg = default_battery_config.model_copy(update={
        "ocv_curve": [(0.0, 3.0), (1.0, 4.2)],
        "r0_soc_table": [(0.0, 0.04), (1.0, 0.04)],
        "r1_soc_table": [(0.0, 0.02), (1.0, 0.02)],
        "c1_soc_table": [(0.0, 2000.0), (1.0, 2000.0)],
        "status": DataStatus.REAL,
    })
    r_real = simulate_battery_step(10.0, default_initial_state, 1.0, verified_cfg, input_status=DataStatus.REAL)
    assert r_real.provenance_status == DataStatus.REAL

    # Provenance ordering: SIMULATED is preserved when input is SIMULATED
    r_sim = simulate_battery_step(10.0, default_initial_state, 1.0, verified_cfg, input_status=DataStatus.SIMULATED)
    assert r_sim.provenance_status == DataStatus.SIMULATED

    cfg_est = verified_cfg.model_copy(update={"status": DataStatus.ESTIMATED})
    r_est = simulate_battery_step(10.0, default_initial_state, 1.0, cfg_est, input_status=DataStatus.REAL)
    assert r_est.provenance_status == DataStatus.ESTIMATED


# =============================================================================
# 6. CORRECTIVE PATCH TESTS (DEF-C3-01 THROUGH DEF-C3-07)
# =============================================================================

def test_def_c3_01_zero_r0_discharge_deficit_no_unbound_crash(
    default_battery_config: BatteryConfig,
    default_initial_state: BatteryState,
):
    """
    DEF-C3-01 Regression Test:
    Verify that simulate_battery_step with R0 = 0 and a discharge deficit does NOT raise
    UnboundLocalError on p_peak_transfer_kw.
    """
    cfg_zero_r0 = default_battery_config.model_copy(update={
        "r0_pack_baseline_ohm": 0.0,
        "max_discharge_power_kw": -30.0,
    })

    # Request -100 kW discharge when max allowed is -30 kW
    res = simulate_battery_step(
        requested_power_kw=-100.0,
        state=default_initial_state,
        dt_s=1.0,
        config=cfg_zero_r0,
    )

    assert res.accepted_power_kw == -30.0
    assert res.deficit_power_kw == -70.0
    assert res.operating_point.is_power_limited is True
    assert "ERR_BATTERY_MAX_DISCHARGE_POWER" in res.active_constraints
    assert abs(res.energy_residual_j) < 1e-5


def test_def_c3_03_empty_feasible_interval_infeasible_bounds(
    default_battery_config: BatteryConfig,
):
    """
    DEF-C3-03 Test:
    Explicitly detect i_lower_bound > i_upper_bound.
    Return clearly diagnosed infeasible operating point with ERR_BATTERY_INFEASIBLE_BOUNDS.
    """
    # Case 1: Pack voltage below minimum where required charging current exceeds max_charge_current
    # Minimum pack voltage = 2.80 * 96 = 268.8 V
    # Severe undervoltage state: OCV = 250 V (via custom curve)
    custom_low_ocv = [(0.0, 2.50), (1.0, 4.20)]
    cfg_low = default_battery_config.model_copy(update={
        "ocv_curve": custom_low_ocv,
        "max_charge_current_a": 50.0,
        "r0_pack_baseline_ohm": 0.10,
    })
    # At SOC=0.0, OCV = 240 V. To reach 268.8 V with R0 = 0.10: I = (268.8 - 240) / 0.10 = 288 A > 50 A max.
    state_undervolt = BatteryState(
        soc=0.0,
        v1_polarization_v=0.0,
        temperature_c=25.0,
        state_of_health=1.0,
        cumulative_energy_throughput_kwh=0.0,
        provenance_status=DataStatus.REAL,
    )
    res_under = simulate_battery_step(requested_power_kw=10.0, state=state_undervolt, dt_s=1.0, config=cfg_low)
    assert res_under.overall_status == ConstraintStatus.VIOLATED
    assert res_under.operating_point.diagnostic_code == "ERR_BATTERY_INFEASIBLE_BOUNDS"
    assert "ERR_BATTERY_INFEASIBLE_BOUNDS" in res_under.active_constraints
    assert res_under.accepted_power_kw == 0.0

    # Case 2: Pack voltage above maximum where required discharge current exceeds max_discharge_current
    # Maximum pack voltage = 4.20 * 96 = 403.2 V
    # Severe overvoltage state: OCV = 420 V
    custom_high_ocv = [(0.0, 3.0), (1.0, 4.50)]
    cfg_high = default_battery_config.model_copy(update={
        "ocv_curve": custom_high_ocv,
        "max_discharge_current_a": -50.0,
        "r0_pack_baseline_ohm": 0.10,
    })
    # At SOC=1.0, OCV = 432 V. To get below 403.2 V: I = (403.2 - 432) / 0.10 = -288 A < -50 A max discharge.
    state_overvolt = BatteryState(
        soc=1.0,
        v1_polarization_v=0.0,
        temperature_c=25.0,
        state_of_health=1.0,
        cumulative_energy_throughput_kwh=0.0,
        provenance_status=DataStatus.REAL,
    )
    res_over = simulate_battery_step(requested_power_kw=-10.0, state=state_overvolt, dt_s=1.0, config=cfg_high)
    assert res_over.overall_status == ConstraintStatus.VIOLATED
    assert res_over.operating_point.diagnostic_code == "ERR_BATTERY_INFEASIBLE_BOUNDS"
    assert "ERR_BATTERY_INFEASIBLE_BOUNDS" in res_over.active_constraints
    assert res_over.accepted_power_kw == 0.0


def test_def_c3_04_maximum_power_transfer_vertex_and_monotonicity(
    default_battery_config: BatteryConfig,
    default_initial_state: BatteryState,
):
    """
    DEF-C3-04 Test:
    Verify that current remains strictly on the physically admissible branch I >= -V_eff / (2 * R_eff)
    and does not jump to the high-current alternative branch when demanding extreme discharge power.
    """
    # Unconstrained hardware current and power to probe the circuit boundary
    cfg_unconstrained = default_battery_config.model_copy(update={
        "max_discharge_power_kw": None,
        "max_discharge_current_a": None,
        "cell_voltage_min_v": 1.0,  # lower voltage cutoff to allow probing circuit transfer
    })
    params = compute_internal_resistance(default_initial_state.soc, default_initial_state.temperature_c, cfg_unconstrained)
    v_eff = params.v_oc_v
    # For dt = 1.0, compute exact r_eff
    _, _, _, om_alpha = _compute_tau_exponential_factors(1.0, params.tau1_s)
    r_eff = params.r0_ohm + params.r1_ohm * om_alpha
    p_peak_theoretical_kw = (-v_eff * v_eff / (4.0 * r_eff)) / 1000.0
    i_peak_theoretical_a = -v_eff / (2.0 * r_eff)

    # Request double the theoretical peak power
    res = simulate_battery_step(
        requested_power_kw=p_peak_theoretical_kw * 2.0,
        state=default_initial_state,
        dt_s=1.0,
        config=cfg_unconstrained,
    )

    # Must be clamped at peak power transfer and vertex current
    assert pytest.approx(res.accepted_power_kw, rel=1e-3) == p_peak_theoretical_kw
    assert pytest.approx(res.operating_point.current_a, rel=1e-3) == i_peak_theoretical_a
    assert "ERR_BATTERY_THEVENIN_MAX_POWER_TRANSFER" in res.active_constraints
    assert abs(res.energy_residual_j) < 1e-5


def test_def_c3_02_impedance_provenance_split(default_battery_config: BatteryConfig):
    """
    DEF-C3-02 Test:
    Verify that supplying only r0_soc_table sets is_r0_verified=True, but keeps
    is_impedance_verified=False because R1 and C1 are unverified.
    Only when all 3 tables are supplied is is_impedance_verified=True.
    """
    r0_table = [(0.0, 0.05), (1.0, 0.03)]
    cfg_r0_only = default_battery_config.model_copy(update={"r0_soc_table": r0_table})
    p_r0 = compute_internal_resistance(0.50, 25.0, cfg_r0_only)
    assert p_r0.is_r0_verified is True
    assert p_r0.is_r1_verified is False
    assert p_r0.is_c1_verified is False
    assert p_r0.is_impedance_verified is False

    r1_table = [(0.0, 0.03), (1.0, 0.02)]
    c1_table = [(0.0, 1500.0), (1.0, 2500.0)]
    cfg_all = default_battery_config.model_copy(update={
        "r0_soc_table": r0_table,
        "r1_soc_table": r1_table,
        "c1_soc_table": c1_table,
    })
    p_all = compute_internal_resistance(0.50, 25.0, cfg_all)
    assert p_all.is_r0_verified is True
    assert p_all.is_r1_verified is True
    assert p_all.is_c1_verified is True
    assert p_all.is_impedance_verified is True


def test_def_c3_05_curve_validation_pydantic():
    """
    DEF-C3-05 Test:
    Verify that Pydantic validators reject invalid characterization curves.
    """
    # 1. Non-monotonic SOC coordinates
    with pytest.raises(ValidationError, match="strictly increasing"):
        BatteryConfig(ocv_curve=[(0.5, 3.5), (0.2, 3.8)])

    # 2. SOC out of [0, 1] range
    with pytest.raises(ValidationError, match=r"range \[0\.0, 1\.0\]"):
        BatteryConfig(ocv_curve=[(-0.1, 3.0), (1.0, 4.2)])

    # 3. Non-positive voltage
    with pytest.raises(ValidationError, match="positive"):
        BatteryConfig(ocv_curve=[(0.0, 0.0), (1.0, 4.2)])

    # 4. Fewer than 2 points
    with pytest.raises(ValidationError, match="at least 2"):
        BatteryConfig(r0_soc_table=[(0.5, 0.04)])

    # 5. Negative resistance in table
    with pytest.raises(ValidationError, match="strictly positive"):
        BatteryConfig(r0_soc_table=[(0.0, 0.04), (1.0, -0.01)])


def test_def_c3_06_coulombic_efficiency_and_parasitic_energy(
    default_battery_config: BatteryConfig,
    default_initial_state: BatteryState,
):
    """
    DEF-C3-06 Test:
    Verify that charging Coulombic efficiency (eta_chg = 0.95) correctly partitions
    OCV energy into reversible chemical storage and parasitic side-reaction dissipation:
    E_chem = 0.95 * E_oc
    E_loss_parasitic = 0.05 * E_oc
    E_chem is 100% consistent with delta_soc * Q_nom * V_oc.
    """
    cfg = default_battery_config.model_copy(update={"coulombic_efficiency_chg": 0.95})
    dt = 10.0
    res = simulate_battery_step(requested_power_kw=30.0, state=default_initial_state, dt_s=dt, config=cfg)

    # 1. Exact partitioning
    assert pytest.approx(res.energy_chem_j, rel=1e-5) == 0.95 * res.energy_ocv_j
    assert pytest.approx(res.energy_loss_parasitic_j, rel=1e-5) == 0.05 * res.energy_ocv_j
    assert pytest.approx(res.energy_chem_j + res.energy_loss_parasitic_j, rel=1e-5) == res.energy_ocv_j

    # 2. Reversible chemical energy corresponds to actual charge transferred to SOC
    params = compute_internal_resistance(default_initial_state.soc, default_initial_state.temperature_c, cfg)
    q_nom_as = cfg.nominal_cell_capacity_ah * cfg.parallel_strings * 3600.0 * default_initial_state.state_of_health
    delta_soc = res.final_state.soc - default_initial_state.soc
    q_chem_stored = delta_soc * q_nom_as
    assert pytest.approx(res.energy_chem_j, rel=1e-5) == q_chem_stored * params.v_oc_v

    # 3. Energy ledger strictly balances with zero residual
    assert abs(res.energy_residual_j) < 1e-5


def test_def_c3_07_extreme_timesteps_precision(
    default_battery_config: BatteryConfig,
    default_initial_state: BatteryState,
):
    """
    DEF-C3-07 Test:
    Verify numerical stability and zero energy residual across extreme timesteps:
    tiny dt = 0.0001 s (100 us) and large dt = 3600.0 s (1 hour).
    """
    # Tiny timestep
    res_tiny = simulate_battery_step(requested_power_kw=25.0, state=default_initial_state, dt_s=0.0001, config=default_battery_config)
    assert math.isfinite(res_tiny.operating_point.current_a)
    assert abs(res_tiny.energy_residual_j) < 1e-5

    # Large timestep
    res_large = simulate_battery_step(requested_power_kw=25.0, state=default_initial_state, dt_s=3600.0, config=default_battery_config)
    assert math.isfinite(res_large.operating_point.current_a)
    assert abs(res_large.energy_residual_j) < 1e-5


# =============================================================================
# 7. INDEPENDENT HAND-CALCULATED BENCHMARK TESTS (TEST-C3-01 & TEST-C3-02)
# =============================================================================

def test_hand_calculated_charging_nonzero_initial_polarization():
    """
    TEST-C3-01: Independent analytical hand-calculated benchmark for charging with V1(0) = 3.0 V.
    
    Circuit Parameters:
      N_s = 96
      Cell OCV = 3.6458333 V => Pack V_oc = 350.0 V
      R_0 = 0.04 Ohm, R_1 = 0.02 Ohm, C_1 = 1000.0 F => tau_1 = 20.0 s
      V_1(0) = 3.0 V, dt = 2.0 s, I = 50.0 A (charging)
      eta_chg = 0.99
    
    Independent Calculus Derivations:
      x = dt / tau_1 = 2.0 / 20.0 = 0.1
      beta = exp(-0.1) = 0.9048374180359595
      1 - beta = 0.09516258196404048
      V_1(2) = 3.0 * beta + 0.02 * 50 * (1 - beta) = 2.809674836071918 V
      alpha = (20 / 2) * (1 - beta) = 0.9516258196404048
      1 - alpha = 0.0483741803595952
      avg_V_1 = alpha * 3.0 + 0.02 * 50 * (1 - alpha) = 2.903251639280809 V
      V_eff = 350.0 + alpha * 3.0 = 352.8548774589212 V
      R_eff = 0.04 + 0.02 * (1 - alpha) = 0.0409674836071919 Ohm
      avg_V_term = V_eff + 50 * R_eff = 354.9032516392808 V
      P_term = avg_V_term * 50 = 17745.16258196404 W = 17.745163 kW
      E_term = P_term * 2.0 = 35490.32516392808 J
      E_oc = 350.0 * 50 * 2.0 = 35000.0 J
      E_chem = 0.99 * 35000.0 = 34650.0 J
      E_loss_parasitic = 0.01 * 35000.0 = 350.0 J
      E_loss_R0 = 50^2 * 0.04 * 2.0 = 200.0 J
      delta_E_C1 = 0.5 * 1000 * (V_1(2)^2 - 3.0^2) = -552.8636573887268 J
      E_RC = 50 * avg_V_1 * 2.0 = 290.3251639280809 J
      E_loss_R1 = E_RC - delta_E_C1 = 843.1888213168077 J
    """
    ocv_table = [(0.0, 350.0 / 96.0), (1.0, 350.0 / 96.0)]
    r0_table = [(0.0, 0.04), (1.0, 0.04)]
    r1_table = [(0.0, 0.02), (1.0, 0.02)]
    c1_table = [(0.0, 1000.0), (1.0, 1000.0)]
    cfg = BatteryConfig(
        series_cells=96,
        nominal_cell_capacity_ah=60.0,
        nominal_pack_capacity_kwh=21.0,
        nominal_pack_voltage_v=350.0,
        cell_voltage_min_v=2.50,
        cell_voltage_max_v=4.20,
        cell_voltage_nominal_v=3.65,
        ocv_curve=ocv_table,
        r0_soc_table=r0_table,
        r1_soc_table=r1_table,
        c1_soc_table=c1_table,
        temp_optimal_low_c=10.0,
        temp_optimal_high_c=40.0,
        coulombic_efficiency_chg=0.99,
        coulombic_efficiency_dis=1.00,
        max_charge_power_kw=100.0,
        max_charge_current_a=200.0,
    )
    init_state = BatteryState(
        soc=0.50,
        v1_polarization_v=3.0,
        temperature_c=25.0,
        state_of_health=1.0,
        cumulative_energy_throughput_kwh=0.0,
        provenance_status=DataStatus.REAL,
    )

    # Demanded terminal power = 17.74516258 kW
    res = simulate_battery_step(requested_power_kw=17.74516258, state=init_state, dt_s=2.0, config=cfg)

    # Verify against independent hand-calculated values
    assert pytest.approx(res.operating_point.current_a, abs=1e-3) == 50.0
    assert pytest.approx(res.final_state.v1_polarization_v, abs=1e-5) == 2.8096748
    assert pytest.approx(res.operating_point.terminal_voltage_v, abs=1e-4) == 354.90325
    assert pytest.approx(res.energy_terminal_j, abs=1e-2) == 35490.33
    assert pytest.approx(res.energy_ocv_j, abs=1e-2) == 35000.00
    assert pytest.approx(res.energy_chem_j, abs=1e-2) == 34650.00
    assert pytest.approx(res.energy_loss_parasitic_j, abs=1e-2) == 350.00
    assert pytest.approx(res.energy_loss_r0_j, abs=1e-2) == 200.00
    assert pytest.approx(res.delta_energy_c1_j, abs=1e-2) == -552.86
    assert pytest.approx(res.energy_loss_r1_j, abs=1e-2) == 843.19
    assert abs(res.energy_residual_j) < 1e-5


def test_hand_calculated_discharging_nonzero_initial_polarization():
    """
    TEST-C3-01: Independent analytical hand-calculated benchmark for discharging with V1(0) = -2.0 V.
    
    Circuit Parameters:
      N_s = 96, V_oc = 350.0 V, R_0 = 0.04 Ohm, R_1 = 0.02 Ohm, C_1 = 1000.0 F => tau_1 = 20.0 s
      V_1(0) = -2.0 V, dt = 2.0 s, I = -50.0 A (discharging)
      eta_dis = 1.00
    
    Independent Calculus Derivations:
      beta = exp(-0.1) = 0.904837418
      1 - beta = 0.095162582
      V_1(2) = -2.0 * beta + 0.02 * (-50) * (1 - beta) = -1.809674836 - 0.095162582 = -1.904837418 V
      alpha = 0.95162582
      1 - alpha = 0.04837418
      avg_V_1 = alpha * (-2.0) + 0.02 * (-50) * (1 - alpha) = -1.903251639 - 0.048374180 = -1.951625819 V
      V_eff = 350.0 + alpha * (-2.0) = 348.09674836 V
      R_eff = 0.04096748 Ohm
      avg_V_term = V_eff + (-50) * R_eff = 346.04837418 V
      P_term = avg_V_term * (-50) = -17302.418709 W = -17.302419 kW
      E_term = P_term * 2.0 = -34604.837418 J
      E_oc = 350.0 * (-50) * 2.0 = -35000.0 J
      E_chem = -35000.0 J, E_loss_parasitic = 0.0 J
      E_loss_R0 = (-50)^2 * 0.04 * 2.0 = 200.0 J
      delta_E_C1 = 0.5 * 1000 * ((-1.904837418)^2 - (-2.0)^2) = 500 * (3.6284058 - 4.0) = -185.797103 J
      E_RC = (-50) * avg_V_1 * 2.0 = 195.162582 J
      E_loss_R1 = E_RC - delta_E_C1 = 195.162582 - (-185.797103) = 380.959685 J
    """
    ocv_table = [(0.0, 350.0 / 96.0), (1.0, 350.0 / 96.0)]
    r0_table = [(0.0, 0.04), (1.0, 0.04)]
    r1_table = [(0.0, 0.02), (1.0, 0.02)]
    c1_table = [(0.0, 1000.0), (1.0, 1000.0)]
    cfg = BatteryConfig(
        series_cells=96,
        nominal_cell_capacity_ah=60.0,
        nominal_pack_capacity_kwh=21.0,
        nominal_pack_voltage_v=350.0,
        cell_voltage_min_v=2.50,
        cell_voltage_max_v=4.20,
        cell_voltage_nominal_v=3.65,
        ocv_curve=ocv_table,
        r0_soc_table=r0_table,
        r1_soc_table=r1_table,
        c1_soc_table=c1_table,
        temp_optimal_low_c=10.0,
        temp_optimal_high_c=40.0,
        coulombic_efficiency_chg=0.99,
        coulombic_efficiency_dis=1.00,
        max_discharge_power_kw=-100.0,
        max_discharge_current_a=-200.0,
    )
    init_state = BatteryState(
        soc=0.50,
        v1_polarization_v=-2.0,
        temperature_c=25.0,
        state_of_health=1.0,
        cumulative_energy_throughput_kwh=0.0,
        provenance_status=DataStatus.REAL,
    )

    res = simulate_battery_step(requested_power_kw=-17.3024187, state=init_state, dt_s=2.0, config=cfg)

    assert pytest.approx(res.operating_point.current_a, abs=1e-3) == -50.0
    assert pytest.approx(res.final_state.v1_polarization_v, abs=1e-5) == -1.9048374
    assert pytest.approx(res.operating_point.terminal_voltage_v, abs=1e-4) == 346.04837
    assert pytest.approx(res.energy_terminal_j, abs=1e-2) == -34604.84
    assert pytest.approx(res.energy_ocv_j, abs=1e-2) == -35000.00
    assert pytest.approx(res.energy_chem_j, abs=1e-2) == -35000.00
    assert pytest.approx(res.energy_loss_parasitic_j, abs=1e-5) == 0.0
    assert pytest.approx(res.energy_loss_r0_j, abs=1e-2) == 200.00
    assert pytest.approx(res.delta_energy_c1_j, abs=1e-2) == -185.80
    assert pytest.approx(res.energy_loss_r1_j, abs=1e-2) == 380.96
    assert abs(res.energy_residual_j) < 1e-5


def test_direct_hardware_curtailments(
    default_battery_config: BatteryConfig,
    default_initial_state: BatteryState,
):
    """
    TEST-C3-02: Explicitly verify curtailment diagnostics against each hardware rating.
    """
    # 1. Max charge power
    cfg_p_chg = default_battery_config.model_copy(update={"max_charge_power_kw": 25.0})
    res_p_chg = simulate_battery_step(50.0, default_initial_state, 1.0, cfg_p_chg)
    assert res_p_chg.accepted_power_kw == 25.0
    assert "ERR_BATTERY_MAX_CHARGE_POWER" in res_p_chg.active_constraints
    assert res_p_chg.operating_point.diagnostic_code == "ERR_BATTERY_MAX_CHARGE_POWER"

    # 2. Max discharge power
    cfg_p_dis = default_battery_config.model_copy(update={"max_discharge_power_kw": -35.0})
    res_p_dis = simulate_battery_step(-80.0, default_initial_state, 1.0, cfg_p_dis)
    assert res_p_dis.accepted_power_kw == -35.0
    assert "ERR_BATTERY_MAX_DISCHARGE_POWER" in res_p_dis.active_constraints
    assert res_p_dis.operating_point.diagnostic_code == "ERR_BATTERY_MAX_DISCHARGE_POWER"

    # 3. Max charge current
    cfg_i_chg = default_battery_config.model_copy(update={"max_charge_current_a": 50.0, "max_charge_power_kw": 100.0})
    res_i_chg = simulate_battery_step(80.0, default_initial_state, 1.0, cfg_i_chg)
    assert pytest.approx(res_i_chg.operating_point.current_a, abs=1e-3) == 50.0
    assert "ERR_BATTERY_MAX_CHARGE_CURRENT" in res_i_chg.active_constraints

    # 4. Max discharge current
    cfg_i_dis = default_battery_config.model_copy(update={"max_discharge_current_a": -50.0, "max_discharge_power_kw": -100.0})
    res_i_dis = simulate_battery_step(-80.0, default_initial_state, 1.0, cfg_i_dis)
    assert pytest.approx(res_i_dis.operating_point.current_a, abs=1e-3) == -50.0
    assert "ERR_BATTERY_MAX_DISCHARGE_CURRENT" in res_i_dis.active_constraints


def test_multistep_drive_cycle_polarization(
    default_battery_config: BatteryConfig,
    default_initial_state: BatteryState,
):
    """
    TEST-C3-02: Multi-step drive cycle tracking polarization accumulation, relaxation,
    and cumulative energy conservation ledger across 10 discrete steps.
    """
    state = default_initial_state
    demands = [30.0, 40.0, 0.0, -25.0, -35.0, 0.0, 50.0, -10.0, 0.0, 0.0]
    total_term_j = 0.0
    total_sum_j = 0.0

    for step_p in demands:
        res = simulate_battery_step(
            requested_power_kw=step_p,
            state=state,
            dt_s=2.0,
            config=default_battery_config,
        )
        assert abs(res.energy_residual_j) < 1e-5
        total_term_j += res.energy_terminal_j
        total_sum_j += (res.energy_chem_j + res.energy_loss_parasitic_j + res.energy_loss_r0_j + res.energy_loss_r1_j + res.delta_energy_c1_j)
        state = res.final_state

    assert pytest.approx(total_term_j, rel=1e-5) == total_sum_j


# =============================================================================
# 8. PHASE 3 COMPREHENSIVE INDEPENDENT VALIDATION SUITE
# =============================================================================

def test_battery_config_topology_and_limits_validation():
    """Phase 3.A: Verify topology configuration and rejection of invalid boundaries."""
    # Valid multi-string configuration
    cfg = BatteryConfig(
        series_cells=108,
        parallel_strings=2,
        nominal_cell_capacity_ah=75.0,
        nominal_pack_capacity_kwh=60.0,
        nominal_pack_voltage_v=400.0,
        cell_voltage_min_v=2.70,
        cell_voltage_nominal_v=3.70,
        cell_voltage_max_v=4.25,
        soc_min_operating=0.03,
        soc_max_operating=0.97,
    )
    assert cfg.series_cells == 108
    assert cfg.parallel_strings == 2

    # Reject series_cells <= 0
    with pytest.raises(ValidationError):
        BatteryConfig(series_cells=0)

    # Reject parallel_strings <= 0
    with pytest.raises(ValidationError):
        BatteryConfig(parallel_strings=0)

    # Reject cell_voltage_min >= cell_voltage_nominal
    with pytest.raises(ValidationError, match="cell_voltage_min_v must be < cell_voltage_nominal_v"):
        BatteryConfig(cell_voltage_min_v=3.80, cell_voltage_nominal_v=3.70)

    # Reject cell_voltage_nominal >= cell_voltage_max
    with pytest.raises(ValidationError, match="cell_voltage_nominal_v must be < cell_voltage_max_v"):
        BatteryConfig(cell_voltage_nominal_v=4.30, cell_voltage_max_v=4.20)

    # Reject invalid SOC range
    with pytest.raises(ValidationError):
        BatteryConfig(soc_min_operating=0.60)

    with pytest.raises(ValidationError):
        BatteryConfig(soc_max_operating=0.40)


def test_ocv_extrapolation_and_flat_clamping(default_battery_config: BatteryConfig):
    """Phase 3.B: Verify OCV flat clamping at SOC boundaries without wild extrapolation."""
    curve = [(0.1, 3.2), (0.9, 4.1)]
    cfg = default_battery_config.model_copy(update={"ocv_curve": curve})

    # Sub-boundary clamp
    v_low, _ = compute_ocv(0.0, 25.0, cfg)
    assert pytest.approx(v_low, rel=1e-5) == 3.2 * 96

    # Super-boundary clamp
    v_high, _ = compute_ocv(1.0, 25.0, cfg)
    assert pytest.approx(v_high, rel=1e-5) == 4.1 * 96


def test_impedance_all_three_tables_interpolated(default_battery_config: BatteryConfig):
    """Phase 3.C: Verify simultaneous linear interpolation of R0, R1, and C1 tables."""
    r0_table = [(0.0, 0.06), (1.0, 0.03)]
    r1_table = [(0.0, 0.04), (1.0, 0.02)]
    c1_table = [(0.0, 1000.0), (1.0, 3000.0)]
    cfg = default_battery_config.model_copy(update={
        "r0_soc_table": r0_table,
        "r1_soc_table": r1_table,
        "c1_soc_table": c1_table,
        "temp_optimal_low_c": 15.0,
        "temp_optimal_high_c": 35.0,
    })

    # At SOC = 0.50, optimal temperature:
    # R0 = 0.06 - 0.5 * 0.03 = 0.045 Ohm
    # R1 = 0.04 - 0.5 * 0.02 = 0.030 Ohm
    # C1 = 1000 + 0.5 * 2000 = 2000.0 F
    params = compute_internal_resistance(0.50, 25.0, cfg)
    assert pytest.approx(params.r0_ohm, rel=1e-5) == 0.045
    assert pytest.approx(params.r1_ohm, rel=1e-5) == 0.030
    assert pytest.approx(params.c1_f, rel=1e-5) == 2000.0
    assert pytest.approx(params.tau1_s, rel=1e-5) == 0.030 * 2000.0  # 60 s
    assert params.is_impedance_verified is True


def test_current_solver_power_reconstruction_precision():
    """Phase 3.D: Verify accepted current reconstructs requested power across entire operating range."""
    v_eff = 355.0
    r_eff = 0.045

    power_sweep_kw = [-150.0, -100.0, -50.0, -25.0, -10.0, 0.0, 5.0, 15.0, 35.0, 60.0, 100.0]
    for p_kw in power_sweep_kw:
        i_sol, p_achievable_kw, is_real = solve_battery_current(p_kw, v_eff, r_eff)
        assert is_real is True
        # Reconstructed terminal power P = (V_eff + I * R_eff) * I
        p_reconstructed_w = (v_eff + i_sol * r_eff) * i_sol
        p_target_w = p_achievable_kw * 1000.0
        assert pytest.approx(p_reconstructed_w, abs=1e-6) == p_target_w


def test_numerical_robustness_nan_inf_rejection(
    default_battery_config: BatteryConfig,
    default_initial_state: BatteryState,
):
    """Phase 3.K: Verify rejection of NaN, inf, and out-of-range floats in model functions."""
    with pytest.raises(ValueError, match="finite"):
        simulate_battery_step(float("nan"), default_initial_state, 1.0, default_battery_config)

    with pytest.raises(ValueError, match="finite"):
        simulate_battery_step(float("inf"), default_initial_state, 1.0, default_battery_config)

    with pytest.raises(ValueError, match="finite"):
        simulate_battery_step(20.0, default_initial_state, float("nan"), default_battery_config)

    with pytest.raises(ValueError, match="finite"):
        compute_ocv(float("nan"), 25.0, default_battery_config)

    with pytest.raises(ValueError, match="finite"):
        compute_internal_resistance(0.5, float("inf"), default_battery_config)
