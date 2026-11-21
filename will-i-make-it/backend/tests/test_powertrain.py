"""
Test Suite for Powertrain & Drivetrain Physics Engine (Stage C1, C1.1, C1.2)
=============================================================================
Validates Stage C1, C1.1, and C1.2 implementations:
1. Forward gearbox power & torque transformations (traction, heat loss).
2. Reverse gearbox power & torque transformations (braking, heat loss).
3. Gearbox efficiency & power conservation (zero residual).
4. Constant-torque motor envelope region.
5. Constant-power motor envelope region.
6. Motor speed limits & linear governor rolloff.
7. Zero-speed torque constraints & stall power.
8. Continuous (S1) vs Peak (S2) motor envelope limits.
9. Independent constraint tracking (torque, power, speed, current).
10. Missing OEM parameters & DataStatus provenance propagation.
11. Dimensional and sign-convention correctness.
12. Boundary conditions and invalid inputs (finite floats, positive limits).
13. Peak overload duration tracking, budget enforcement, and recovery rate (Correction 1).
14. Sequential route segment peak exposure propagation (Correction 1 & C1.2).
15. Motor envelope configuration invariants: omega_base <= omega_gov_start <= omega_max (Correction 2).
16. Torque-speed-power mechanical consistency validation (Correction 3).
17. Provenance combinations: REAL+REAL, REAL+EST, REAL+SIM, REAL+UNK, SIM+EST (Correction 4).
18. Stall electrical dissipation, explicit inverter loss, and provenance (Correction 5).
19. Exhausted budget + denied peak request exceeding continuous capability: no recovery (Correction C1.2).
20. Exhausted budget + valid continuous operation: recovery occurs (Correction C1.2).
21. Denied peak request followed by valid continuous recovery and subsequent peak request (Correction C1.2).
22. Boundary behavior at exactly exhausted budget (Correction C1.2).
23. Invalid or contradictory operating-mode inputs (Correction C1.2).
"""
import math
import pytest

from app.domain.provenance import DataStatus
from app.services.energy.powertrain_model import (
    OperatingEnvelopeMode,
    ActualOperatingMode,
    ConstraintStatus,
    GearboxConfig,
    MotorConfig,
    PeakExposureState,
    StallElectricalResult,
    combine_provenance,
    compute_motor_speed,
    transform_forward_traction,
    transform_reverse_braking,
    compute_wheel_force_from_motor_torque,
    compute_motor_envelope,
    compute_stator_phase_current,
    compute_stall_dc_power,
    is_demand_in_peak_overload,
    update_peak_exposure,
    check_powertrain_constraints,
)


@pytest.fixture
def default_gearbox() -> GearboxConfig:
    """Standard Tata Nexon EV single-speed gearbox parameters."""
    return GearboxConfig(
        gear_ratio=9.05,
        efficiency_fwd=0.97,
        efficiency_rev=0.96,
        wheel_radius_m=0.315,
        status=DataStatus.REAL,
    )


@pytest.fixture
def default_motor() -> MotorConfig:
    """Standard Tata Nexon EV 3-phase PMSM parameters with verified real ratings."""
    return MotorConfig(
        torque_cont_max_nm=145.0,
        power_cont_max_kw=65.0,
        max_speed_rpm=12000.0,  # ~1256.637 rad/s
        torque_peak_max_nm=245.0,
        power_peak_max_kw=95.0,
        pole_pairs=4,
        flux_linkage_wb=0.076603,
        stator_resistance_ohm=0.02,
        k_t_rms=0.650,
        governor_rolloff_fraction=0.05,
        peak_duration_budget_s=20.0,
        recovery_rate_s_per_s=0.20,
        inverter_current_limit_rms=400.0,
        inverter_dc_power_limit_kw=95.0,
        inverter_efficiency=0.95,
        inverter_standby_loss_w=550.0,
        inverter_loss_status=DataStatus.REAL,
        status=DataStatus.REAL,
    )


# ==============================================================================
# 1. FORWARD GEARBOX TRANSFORMATIONS (TRACTION)
# ==============================================================================

def test_forward_gearbox_traction(default_gearbox: GearboxConfig):
    """
    Test forward gearbox power and torque transformations.
    F_wheel = 1500 N, v = 20 m/s:
    P_wheel = 30.0 kW
    P_motor = 30.0 / 0.97 = 30.927835 kW (> 0)
    T_motor = (1500 * 0.315) / (9.05 * 0.97) = 53.824685 Nm
    P_loss = P_motor - P_wheel = 0.927835 kW (strictly positive)
    """
    res = transform_forward_traction(wheel_force_n=1500.0, vehicle_speed_ms=20.0, config=default_gearbox)

    assert res.wheel_force_n == 1500.0
    assert res.vehicle_speed_ms == 20.0
    assert pytest.approx(res.wheel_power_kw, rel=1e-6) == 30.0
    assert pytest.approx(res.motor_shaft_power_kw, rel=1e-6) == 30.0 / 0.97
    assert pytest.approx(res.motor_torque_req_nm, rel=1e-6) == (1500.0 * 0.315) / (9.05 * 0.97)
    assert pytest.approx(res.gearbox_loss_kw, rel=1e-6) == (30.0 / 0.97) - 30.0
    assert res.gearbox_loss_kw > 0.0

    # Wheel force inversion test: F_wheel = T_motor * N_gb * eta_fwd / r_wheel
    f_calc = compute_wheel_force_from_motor_torque(
        motor_torque_nm=res.motor_torque_req_nm,
        config=default_gearbox,
        is_regeneration=False,
    )
    assert pytest.approx(f_calc, rel=1e-6) == 1500.0


# ==============================================================================
# 2. REVERSE GEARBOX TRANSFORMATIONS (BRAKING)
# ==============================================================================

def test_reverse_gearbox_braking(default_gearbox: GearboxConfig):
    """
    Test reverse gearbox power and torque transformations under braking.
    F_wheel = -2000 N, v = 15 m/s:
    P_wheel = -30.0 kW (< 0)
    P_motor = -30.0 * 0.96 = -28.8 kW (< 0)
    T_motor_regen = (-(-2000) * 0.315 * 0.96) / 9.05 = 66.828729 Nm (positive magnitude)
    P_loss = -(-30.0) * (1 - 0.96) = +1.2 kW (strictly non-negative)
    """
    res = transform_reverse_braking(wheel_force_n=-2000.0, vehicle_speed_ms=15.0, config=default_gearbox)

    assert res.wheel_force_n == -2000.0
    assert res.vehicle_speed_ms == 15.0
    assert pytest.approx(res.wheel_power_kw, rel=1e-6) == -30.0
    assert pytest.approx(res.motor_shaft_power_kw, rel=1e-6) == -28.8
    assert res.motor_shaft_power_kw < 0.0
    assert pytest.approx(res.motor_torque_regen_nm, rel=1e-6) == (2000.0 * 0.315 * 0.96) / 9.05
    assert res.motor_torque_regen_nm > 0.0
    assert pytest.approx(res.gearbox_loss_kw, rel=1e-6) == 1.2
    assert res.gearbox_loss_kw > 0.0

    # Wheel braking force inversion: F_wheel = T_motor * N_gb / (eta_rev * r_wheel)
    f_calc = compute_wheel_force_from_motor_torque(
        motor_torque_nm=res.motor_torque_regen_nm,
        config=default_gearbox,
        is_regeneration=True,
    )
    assert pytest.approx(f_calc, rel=1e-6) == 2000.0


# ==============================================================================
# 3. GEARBOX POWER CONSERVATION & ZERO RESIDUAL
# ==============================================================================

def test_gearbox_power_conservation_residual(default_gearbox: GearboxConfig):
    """
    Verify exact mechanical power conservation P_mot = T_mot * omega_mot
    and energy ledger balance with zero residual in both directions.
    """
    speeds = [2.0, 10.0, 25.0, 35.0]

    # Forward traction
    for v in speeds:
        f_wheel = 1200.0
        fwd = transform_forward_traction(f_wheel, v, default_gearbox)
        omega = compute_motor_speed(v, default_gearbox).motor_speed_rad_s
        p_from_torque = (fwd.motor_torque_req_nm * omega) / 1000.0
        assert math.isclose(fwd.motor_shaft_power_kw, p_from_torque, rel_tol=1e-9)
        # First Law: P_motor = P_wheel + P_loss
        assert math.isclose(fwd.motor_shaft_power_kw, fwd.wheel_power_kw + fwd.gearbox_loss_kw, rel_tol=1e-9)

    # Reverse regeneration
    for v in speeds:
        f_wheel = -1600.0
        rev = transform_reverse_braking(f_wheel, v, default_gearbox)
        omega = compute_motor_speed(v, default_gearbox).motor_speed_rad_s
        p_from_torque = -(rev.motor_torque_regen_nm * omega) / 1000.0
        assert math.isclose(rev.motor_shaft_power_kw, p_from_torque, rel_tol=1e-9)
        # First Law signed: P_wheel = P_motor - P_loss  (e.g., -30 = -28.8 - 1.2)
        assert math.isclose(rev.wheel_power_kw, rev.motor_shaft_power_kw - rev.gearbox_loss_kw, rel_tol=1e-9)


# ==============================================================================
# 4. CONSTANT-TORQUE ENVELOPE REGION
# ==============================================================================

def test_constant_torque_region(default_motor: MotorConfig):
    """
    For omega <= omega_base:
    Torque is capped at T_max, power scales linearly with omega.
    Continuous: omega_base = 65000 / 145 = 448.276 rad/s
    Peak: omega_base = 95000 / 245 = 387.755 rad/s
    """
    omega = 200.0  # rad/s (< base speed)

    # Continuous
    cont = compute_motor_envelope(omega, default_motor, mode=OperatingEnvelopeMode.CONTINUOUS)
    assert cont.operating_region == "constant_torque"
    assert cont.available_torque_nm == 145.0
    assert pytest.approx(cont.available_power_kw, rel=1e-6) == (145.0 * 200.0) / 1000.0  # 29.0 kW
    assert cont.governor_derate_factor == 1.0
    assert not cont.is_governor_active

    # Peak
    peak = compute_motor_envelope(omega, default_motor, mode=OperatingEnvelopeMode.PEAK)
    assert peak.operating_region == "constant_torque"
    assert peak.available_torque_nm == 245.0
    assert pytest.approx(peak.available_power_kw, rel=1e-6) == (245.0 * 200.0) / 1000.0  # 49.0 kW
    assert peak.governor_derate_factor == 1.0


# ==============================================================================
# 5. CONSTANT-POWER ENVELOPE REGION
# ==============================================================================

def test_constant_power_region(default_motor: MotorConfig):
    """
    For omega_base < omega <= omega_gov_start:
    Power is capped at P_max, torque decreases inversely with omega.
    """
    omega = 800.0  # rad/s

    # Continuous: P_max = 65 kW -> T = 65000 / 800 = 81.25 Nm
    cont = compute_motor_envelope(omega, default_motor, mode=OperatingEnvelopeMode.CONTINUOUS)
    assert cont.operating_region == "constant_power"
    assert cont.available_power_kw == 65.0
    assert pytest.approx(cont.available_torque_nm, rel=1e-6) == 81.25
    assert not cont.is_governor_active

    # Peak: P_max = 95 kW -> T = 95000 / 800 = 118.75 Nm
    peak = compute_motor_envelope(omega, default_motor, mode=OperatingEnvelopeMode.PEAK)
    assert peak.operating_region == "constant_power"
    assert peak.available_power_kw == 95.0
    assert pytest.approx(peak.available_torque_nm, rel=1e-6) == 118.75
    assert not peak.is_governor_active


# ==============================================================================
# 6. SPEED LIMITS & LINEAR GOVERNOR ROLLOFF
# ==============================================================================

def test_governor_rolloff_and_overspeed(default_motor: MotorConfig):
    """
    Test linear governor rolloff over the top 5% speed range:
    omega_max = 12000 * 2pi / 60 = 1256.637 rad/s
    omega_gov_start = 0.95 * 1256.637 = 1193.80515 rad/s
    At midpoint: omega = 1225.221075 rad/s -> S_gov = 0.50
    At omega_max: S_gov = 0.0 -> P = 0, T = 0
    At omega > omega_max: overspeed_cutoff -> P = 0, T = 0
    """
    omega_max = (default_motor.max_speed_rpm * 2.0 * math.pi) / 60.0
    omega_mid = omega_max * 0.975  # exactly halfway in governor region

    res_mid = compute_motor_envelope(omega_mid, default_motor, mode=OperatingEnvelopeMode.CONTINUOUS)
    assert res_mid.operating_region == "governor_rolloff"
    assert res_mid.is_governor_active
    assert pytest.approx(res_mid.governor_derate_factor, rel=1e-4) == 0.50
    assert pytest.approx(res_mid.available_power_kw, rel=1e-4) == 65.0 * 0.50

    # Exactly at omega_max
    res_max = compute_motor_envelope(omega_max, default_motor, mode=OperatingEnvelopeMode.CONTINUOUS)
    assert res_max.operating_region == "governor_rolloff"
    assert pytest.approx(res_max.governor_derate_factor, abs=1e-6) == 0.0
    assert res_max.available_power_kw == 0.0
    assert res_max.available_torque_nm == 0.0

    # Overspeed cutoff
    res_over = compute_motor_envelope(omega_max + 10.0, default_motor, mode=OperatingEnvelopeMode.CONTINUOUS)
    assert res_over.operating_region == "overspeed_cutoff"
    assert not res_over.is_governor_active
    assert res_over.is_overspeed_cutoff
    assert res_over.governor_derate_factor == 0.0
    assert res_over.available_power_kw == 0.0
    assert res_over.available_torque_nm == 0.0


# ==============================================================================
# 7. ZERO-SPEED TORQUE & STALL POWER CONSTRAINTS (CORRECTION 3 & 5)
# ==============================================================================

def test_zero_speed_stall_physics(default_motor: MotorConfig, default_gearbox: GearboxConfig):
    """
    At vehicle standstill (v = 0, hill hold):
    - Mechanical shaft power P_mech = T * omega = 0.
    - Stator phase current: I_rms = T / k_t_rms.
    - Stator copper loss: P_loss = 3 * I_rms^2 * R_s.
    - Inverter loss explicitly verified: P_inv = 550 W (REAL).
    - Torque is delivered without power constraint violation.
    """
    t_req = 200.0  # Nm (within peak 245 Nm)
    i_rms = compute_stator_phase_current(t_req, default_motor)
    expected_i = 200.0 / 0.650  # ~307.692 A_rms
    assert pytest.approx(i_rms, rel=1e-6) == expected_i

    stall_res = compute_stall_dc_power(t_req, default_motor, inverter_loss_w=550.0, inverter_loss_status=DataStatus.REAL)
    assert stall_res is not None
    p_stator_w, p_dc_stall_kw = stall_res
    expected_copper = 3.0 * (expected_i ** 2) * 0.02  # ~5680.47 W
    expected_dc_kw = (expected_copper + 550.0) / 1000.0
    assert pytest.approx(p_stator_w, rel=1e-4) == expected_copper
    assert pytest.approx(p_dc_stall_kw, rel=1e-4) == expected_dc_kw
    assert stall_res.status == ConstraintStatus.SATISFIED
    assert stall_res.provenance_status == DataStatus.REAL

    # Constraint check at v = 0 with mechanical power demand = 0.0
    status = check_powertrain_constraints(
        demand_torque_nm=t_req,
        demand_power_kw=0.0,
        vehicle_speed_ms=0.0,
        motor_config=default_motor,
        gearbox_config=default_gearbox,
        mode=OperatingEnvelopeMode.PEAK,
    )
    assert status.torque_status == ConstraintStatus.SATISFIED
    assert status.speed_status == ConstraintStatus.SATISFIED
    assert status.power_status == ConstraintStatus.SATISFIED  # zero-speed stall exempted from P_mech cap
    assert status.current_status == ConstraintStatus.SATISFIED
    assert status.overall_status == ConstraintStatus.SATISFIED
    assert status.stall_dc_power_kw is not None
    assert pytest.approx(status.stall_dc_power_kw, rel=1e-4) == expected_dc_kw


# ==============================================================================
# 8. CONTINUOUS (S1) VS PEAK (S2) MOTOR ENVELOPE MODES
# ==============================================================================

def test_continuous_vs_peak_modes(default_motor: MotorConfig, default_gearbox: GearboxConfig):
    """
    Compare continuous (S1) vs peak (S2) capability under the same torque demand (180 Nm at 10 m/s):
    - Under continuous (max 145 Nm): torque limit is violated.
    - Under peak (max 245 Nm): torque limit is satisfied.
    """
    t_req = 180.0
    v = 10.0
    # At v = 10 m/s: omega = 10 * 9.05 / 0.315 = 287.302 rad/s (< omega_base = 387.76 rad/s)
    omega = compute_motor_speed(v, default_gearbox).motor_speed_rad_s
    p_req = (t_req * omega) / 1000.0  # ~51.71 kW

    cont_res = check_powertrain_constraints(
        demand_torque_nm=t_req,
        demand_power_kw=p_req,
        vehicle_speed_ms=v,
        motor_config=default_motor,
        gearbox_config=default_gearbox,
        mode=OperatingEnvelopeMode.CONTINUOUS,
    )
    assert cont_res.torque_status == ConstraintStatus.VIOLATED
    assert cont_res.overall_status == ConstraintStatus.VIOLATED
    assert cont_res.diagnostic_code == "ERR_TORQUE_EXCEEDED"

    peak_res = check_powertrain_constraints(
        demand_torque_nm=t_req,
        demand_power_kw=p_req,
        vehicle_speed_ms=v,
        motor_config=default_motor,
        gearbox_config=default_gearbox,
        mode=OperatingEnvelopeMode.PEAK,
    )
    assert peak_res.torque_status == ConstraintStatus.SATISFIED
    assert peak_res.power_status == ConstraintStatus.SATISFIED
    assert peak_res.overall_status == ConstraintStatus.SATISFIED


# ==============================================================================
# 9. INDEPENDENT CONSTRAINT TRACKING
# ==============================================================================

def test_independent_constraint_tracking(default_motor: MotorConfig, default_gearbox: GearboxConfig):
    """
    Verify each constraint (torque, power, speed, current) can be violated independently.
    """
    # 1. Overspeed violation: v = 45 m/s -> omega = 45 * 9.05 / 0.315 = 1292.86 rad/s > 1256.637
    omega_over = compute_motor_speed(45.0, default_gearbox).motor_speed_rad_s
    p_req_speed = (10.0 * omega_over) / 1000.0  # Consistent power
    res_speed = check_powertrain_constraints(
        demand_torque_nm=10.0,
        demand_power_kw=p_req_speed,
        vehicle_speed_ms=45.0,
        motor_config=default_motor,
        gearbox_config=default_gearbox,
        mode=OperatingEnvelopeMode.PEAK,
    )
    assert res_speed.speed_status == ConstraintStatus.VIOLATED
    assert res_speed.overall_status == ConstraintStatus.VIOLATED
    assert res_speed.diagnostic_code == "ERR_OVERSPEED_CUTOFF"

    # 2. Inverter current violation: configure motor with small inverter limit
    low_inv_motor = default_motor.model_copy(update={"inverter_current_limit_rms": 150.0})
    omega_curr = compute_motor_speed(5.0, default_gearbox).motor_speed_rad_s
    p_req_curr = (120.0 * omega_curr) / 1000.0
    res_curr = check_powertrain_constraints(
        demand_torque_nm=120.0,
        demand_power_kw=p_req_curr,
        vehicle_speed_ms=5.0,
        motor_config=low_inv_motor,
        gearbox_config=default_gearbox,
        mode=OperatingEnvelopeMode.PEAK,
    )
    assert res_curr.current_status == ConstraintStatus.VIOLATED
    assert res_curr.overall_status == ConstraintStatus.VIOLATED
    assert res_curr.diagnostic_code == "ERR_CURRENT_EXCEEDED"


# ==============================================================================
# 10. MISSING OEM PARAMETERS & PROVENANCE PROPAGATION
# ==============================================================================

def test_missing_oem_parameters_and_provenance(default_gearbox: GearboxConfig):
    """
    When inverter limit is missing or status is UNKNOWN / ESTIMATED:
    - Constraint status must be CONDITIONAL.
    - Provenance must reflect UNKNOWN or ESTIMATED.
    """
    unknown_motor = MotorConfig(
        torque_cont_max_nm=140.0,
        power_cont_max_kw=60.0,
        max_speed_rpm=12000.0,
        inverter_current_limit_rms=None,  # Missing OEM limit
        status=DataStatus.UNKNOWN,
    )

    omega = compute_motor_speed(10.0, default_gearbox).motor_speed_rad_s
    p_req = (100.0 * omega) / 1000.0  # Consistent mechanical power

    res = check_powertrain_constraints(
        demand_torque_nm=100.0,
        demand_power_kw=p_req,
        vehicle_speed_ms=10.0,
        motor_config=unknown_motor,
        gearbox_config=default_gearbox,
        mode=OperatingEnvelopeMode.CONTINUOUS,
    )
    assert res.current_status == ConstraintStatus.CONDITIONAL
    assert res.overall_status == ConstraintStatus.CONDITIONAL
    assert res.diagnostic_code == "WARN_HARDWARE_LIMITS_UNVERIFIED"
    assert res.provenance_status == DataStatus.UNKNOWN


# ==============================================================================
# 11. DIMENSIONAL AND SIGN CONVENTION CORRECTNESS
# ==============================================================================

def test_sign_conventions(default_gearbox: GearboxConfig):
    """
    Verify strict adherence to signed power conventions:
    - Positive wheel force -> Positive wheel power -> Positive motor power.
    - Negative wheel force -> Negative wheel power -> Negative motor power.
    - Gearbox heat dissipation is positive in both directions.
    """
    # Traction
    fwd = transform_forward_traction(wheel_force_n=500.0, vehicle_speed_ms=12.0, config=default_gearbox)
    assert fwd.wheel_power_kw > 0.0
    assert fwd.motor_shaft_power_kw > 0.0
    assert fwd.gearbox_loss_kw >= 0.0

    # Braking
    rev = transform_reverse_braking(wheel_force_n=-500.0, vehicle_speed_ms=12.0, config=default_gearbox)
    assert rev.wheel_power_kw < 0.0
    assert rev.motor_shaft_power_kw < 0.0
    assert rev.gearbox_loss_kw >= 0.0


# ==============================================================================
# 12. BOUNDARY CONDITIONS AND INVALID INPUTS
# ==============================================================================

def test_boundary_conditions_and_invalid_inputs(default_gearbox: GearboxConfig, default_motor: MotorConfig):
    """
    Verify rejection of negative speed, non-finite values, and inconsistent configurations.
    """
    # Negative speed
    with pytest.raises(ValueError, match="vehicle_speed_ms"):
        compute_motor_speed(-1.0, default_gearbox)

    with pytest.raises(ValueError, match="vehicle_speed_ms"):
        transform_forward_traction(100.0, -5.0, default_gearbox)

    # NaN / Inf validation
    with pytest.raises(ValueError, match="finite"):
        compute_motor_speed(float("nan"), default_gearbox)

    with pytest.raises(ValueError, match="finite"):
        compute_motor_speed(float("inf"), default_gearbox)

    # Gearbox config validations
    with pytest.raises(ValueError):
        GearboxConfig(gear_ratio=-1.0, wheel_radius_m=0.3)

    with pytest.raises(ValueError):
        GearboxConfig(gear_ratio=9.0, efficiency_fwd=1.5, wheel_radius_m=0.3)


# ==============================================================================
# 13. PEAK EXPOSURE ACCUMULATION & RECOVERY (CORRECTION 1 & C1.2)
# ==============================================================================

def test_peak_exposure_accumulation_and_recovery():
    """
    Deterministic peak-exposure state transition:
    Budget = 20.0 s, recovery rate = 0.20 s/s.
    Step 1: 10s peak overload -> exposure = 10s, remaining = 10s, not exhausted.
    Step 2: 12s peak overload -> exposure reaches 20s (capped), exhausted = True.
    Step 3: 30s continuous recovery -> recovered = 6s -> exposure = 14s, exhausted = False.
    Step 4: 80s continuous recovery -> recovered = 16s -> exposure = 0s (fully reset).
    """
    initial_state = PeakExposureState(budget_s=20.0, recovery_rate_s_per_s=0.20)
    assert initial_state.cumulative_exposure_s == 0.0
    assert initial_state.remaining_budget_s == 20.0
    assert not initial_state.is_exhausted

    # Step 1: 10s in peak
    s1 = update_peak_exposure(initial_state, dt_s=10.0, is_peak_operating=True)
    assert pytest.approx(s1.cumulative_exposure_s, rel=1e-6) == 10.0
    assert pytest.approx(s1.remaining_budget_s, rel=1e-6) == 10.0
    assert not s1.is_exhausted

    # Step 2: 12s in peak (exceeds remaining 10s)
    s2 = update_peak_exposure(s1, dt_s=12.0, is_peak_operating=True)
    assert pytest.approx(s2.cumulative_exposure_s, rel=1e-6) == 20.0
    assert pytest.approx(s2.remaining_budget_s, abs=1e-6) == 0.0
    assert s2.is_exhausted

    # Step 3: 30s recovery (continuous operation) -> 30 * 0.20 = 6.0s recovered
    s3 = update_peak_exposure(s2, dt_s=30.0, is_peak_operating=False)
    assert pytest.approx(s3.cumulative_exposure_s, rel=1e-6) == 14.0
    assert pytest.approx(s3.remaining_budget_s, rel=1e-6) == 6.0
    assert not s3.is_exhausted

    # Step 4: 80s recovery -> 80 * 0.20 = 16.0s recovered -> capped at 0.0
    s4 = update_peak_exposure(s3, dt_s=80.0, is_peak_operating=False)
    assert pytest.approx(s4.cumulative_exposure_s, abs=1e-6) == 0.0
    assert pytest.approx(s4.remaining_budget_s, rel=1e-6) == 20.0
    assert not s4.is_exhausted


# ==============================================================================
# 14. SEQUENTIAL ROUTE SEGMENTS PEAK EXPOSURE PROPAGATION (CORRECTION 1 & C1.2)
# ==============================================================================

def test_peak_exposure_sequential_segments(default_motor: MotorConfig, default_gearbox: GearboxConfig):
    """
    Demonstrate peak exposure and recovery across 5 sequential route segments:
    - Seg 1 (Climb, dt=10s): Peak demand (200 Nm, v=10 m/s) -> exposure = 10s, feasible.
    - Seg 2 (Flat, dt=25s): Continuous demand (100 Nm, v=20 m/s) -> recovers 5s -> exposure = 5s.
    - Seg 3 (Sprint, dt=15s): Peak demand (200 Nm, v=10 m/s) -> exposure = 20s (exhausted).
    - Seg 4 (Continued Sprint, dt=5s): Attempt peak while exhausted (200 Nm > 145 Nm) ->
             Peak denied, demand exceeds continuous -> VIOLATED, NO RECOVERY (stays 20s).
    - Seg 5 (Descent/Flat, dt=40s): Continuous demand (100 Nm) -> recovers 8s -> exposure drops to 12s, un-exhausted.
    """
    v_climb = 10.0
    omega_climb = compute_motor_speed(v_climb, default_gearbox).motor_speed_rad_s
    t_peak = 200.0  # > 145 Nm continuous
    p_peak = (t_peak * omega_climb) / 1000.0

    v_flat = 20.0
    omega_flat = compute_motor_speed(v_flat, default_gearbox).motor_speed_rad_s
    t_cont = 100.0  # < 145 Nm continuous
    p_cont = (t_cont * omega_flat) / 1000.0

    # Segment 1: Steep climb for 10 s
    seg1_res = check_powertrain_constraints(
        demand_torque_nm=t_peak,
        demand_power_kw=p_peak,
        vehicle_speed_ms=v_climb,
        motor_config=default_motor,
        gearbox_config=default_gearbox,
        mode=OperatingEnvelopeMode.PEAK,
        peak_state=PeakExposureState(budget_s=20.0, recovery_rate_s_per_s=0.20),
        dt_s=10.0,
    )
    assert seg1_res.overall_status == ConstraintStatus.SATISFIED
    assert seg1_res.peak_requested
    assert seg1_res.peak_granted
    assert seg1_res.actual_operating_mode == ActualOperatingMode.PEAK
    assert seg1_res.peak_state is not None
    assert pytest.approx(seg1_res.peak_state.cumulative_exposure_s, rel=1e-6) == 10.0
    assert not seg1_res.is_peak_exhausted

    # Segment 2: Flat cruise for 25 s (recovering)
    seg2_res = check_powertrain_constraints(
        demand_torque_nm=t_cont,
        demand_power_kw=p_cont,
        vehicle_speed_ms=v_flat,
        motor_config=default_motor,
        gearbox_config=default_gearbox,
        mode=OperatingEnvelopeMode.CONTINUOUS,
        peak_state=seg1_res.peak_state,
        dt_s=25.0,
    )
    assert seg2_res.overall_status == ConstraintStatus.SATISFIED
    assert not seg2_res.peak_requested
    assert not seg2_res.peak_granted
    assert seg2_res.actual_operating_mode == ActualOperatingMode.CONTINUOUS
    assert seg2_res.peak_state is not None
    # 10s - (25 * 0.20) = 5.0 s
    assert pytest.approx(seg2_res.peak_state.cumulative_exposure_s, rel=1e-6) == 5.0
    assert not seg2_res.is_peak_exhausted

    # Segment 3: Sprint for 15 s (peak overload)
    seg3_res = check_powertrain_constraints(
        demand_torque_nm=t_peak,
        demand_power_kw=p_peak,
        vehicle_speed_ms=v_climb,
        motor_config=default_motor,
        gearbox_config=default_gearbox,
        mode=OperatingEnvelopeMode.PEAK,
        peak_state=seg2_res.peak_state,
        dt_s=15.0,
    )
    assert seg3_res.overall_status == ConstraintStatus.SATISFIED
    assert seg3_res.peak_granted
    assert seg3_res.peak_state is not None
    # 5s + 15s = 20.0 s -> reaches full budget!
    assert pytest.approx(seg3_res.peak_state.cumulative_exposure_s, rel=1e-6) == 20.0
    assert seg3_res.peak_state.is_exhausted
    assert seg3_res.is_peak_exhausted

    # Segment 4: Attempt continued peak overload while exhausted (dt=5s, 200 Nm > 145 Nm)
    seg4_res = check_powertrain_constraints(
        demand_torque_nm=t_peak,
        demand_power_kw=p_peak,
        vehicle_speed_ms=v_climb,
        motor_config=default_motor,
        gearbox_config=default_gearbox,
        mode=OperatingEnvelopeMode.PEAK,
        peak_state=seg3_res.peak_state,
        dt_s=5.0,
    )
    # Peak operation must be denied! Exceeds continuous -> VIOLATED, NO RECOVERY (stays at 20.0s)
    assert seg4_res.overall_status == ConstraintStatus.VIOLATED
    assert seg4_res.diagnostic_code == "ERR_PEAK_BUDGET_EXHAUSTED"
    assert seg4_res.peak_requested
    assert not seg4_res.peak_granted
    assert seg4_res.actual_operating_mode == ActualOperatingMode.INFEASIBLE
    assert seg4_res.is_peak_exhausted
    assert seg4_res.peak_state is not None
    # Strictly NO recovery when peak request is denied and exceeds continuous capability
    assert pytest.approx(seg4_res.peak_state.cumulative_exposure_s, rel=1e-6) == 20.0

    # Segment 5: Driver backs off to continuous for 40 s (100 Nm <= 145 Nm)
    seg5_res = check_powertrain_constraints(
        demand_torque_nm=t_cont,
        demand_power_kw=p_cont,
        vehicle_speed_ms=v_flat,
        motor_config=default_motor,
        gearbox_config=default_gearbox,
        mode=OperatingEnvelopeMode.CONTINUOUS,
        peak_state=seg4_res.peak_state,
        dt_s=40.0,
    )
    assert seg5_res.overall_status == ConstraintStatus.SATISFIED
    assert seg5_res.peak_state is not None
    # Recovered: 40 * 0.20 = 8.0 s -> exposure becomes 20 - 8 = 12.0 s
    assert pytest.approx(seg5_res.peak_state.cumulative_exposure_s, rel=1e-6) == 12.0
    assert not seg5_res.peak_state.is_exhausted
    assert not seg5_res.is_peak_exhausted


# ==============================================================================
# 15. MOTOR ENVELOPE CONFIGURATION INVARIANTS (CORRECTION 2)
# ==============================================================================

def test_motor_envelope_configuration_invariants_continuous():
    """
    Validate rejection of invalid continuous configuration where:
    omega_base_cont > omega_gov_start.
    max_speed_rpm = 12000 -> omega_max = 1256.637 rad/s.
    governor_rolloff_fraction = 0.05 -> omega_gov_start = 1193.805 rad/s.
    If power_cont = 120 kW, torque_cont = 90 Nm:
    omega_base_cont = 120000 / 90 = 1333.33 rad/s > 1193.805 rad/s -> REJECTED!
    """
    with pytest.raises(ValueError, match="Continuous base speed"):
        MotorConfig(
            torque_cont_max_nm=90.0,
            power_cont_max_kw=120.0,
            max_speed_rpm=12000.0,
            governor_rolloff_fraction=0.05,
        )


def test_motor_envelope_configuration_invariants_peak():
    """
    Validate rejection of invalid peak configuration where:
    omega_base_peak > omega_gov_start.
    max_speed_rpm = 12000 -> omega_gov_start = 1193.805 rad/s.
    If continuous is valid (T=100, P=65 -> omega_base=650 rad/s),
    and peak has T_peak=110 Nm >= T_cont, but P_peak=150 kW:
    omega_base_peak = 150000 / 110 = 1363.6 rad/s > 1193.805 rad/s -> REJECTED!
    """
    with pytest.raises(ValueError, match="Peak base speed"):
        MotorConfig(
            torque_cont_max_nm=100.0,
            power_cont_max_kw=65.0,
            torque_peak_max_nm=110.0,
            power_peak_max_kw=150.0,
            max_speed_rpm=12000.0,
            governor_rolloff_fraction=0.05,
        )


# ==============================================================================
# 16. TORQUE-SPEED-POWER MECHANICAL CONSISTENCY VALIDATION (CORRECTION 3)
# ==============================================================================

def test_torque_power_consistency_validation(default_motor: MotorConfig, default_gearbox: GearboxConfig):
    """
    In check_powertrain_constraints:
    1. Reject non-zero mechanical shaft power at standstill (v = 0).
    2. Reject inconsistent power demand at speed (P != T * omega).
    3. Accept consistent power demand within tolerance.
    """
    # 1. Contradictory demand at standstill: 10 kW mechanical shaft power at 0 m/s
    res_zero = check_powertrain_constraints(
        demand_torque_nm=100.0,
        demand_power_kw=10.0,  # Physically impossible at v = 0
        vehicle_speed_ms=0.0,
        motor_config=default_motor,
        gearbox_config=default_gearbox,
    )
    assert res_zero.overall_status == ConstraintStatus.VIOLATED
    assert res_zero.power_status == ConstraintStatus.VIOLATED
    assert res_zero.diagnostic_code == "ERR_TORQUE_POWER_INCONSISTENT"

    # 2. Inconsistent demand at speed: v = 15 m/s, T = 80 Nm
    # omega = 15 * 9.05 / 0.315 = 430.952 rad/s -> P_expected = 80 * 430.952 / 1000 = 34.476 kW
    # Demanding 15.0 kW is contradictory beyond tolerance
    res_inconsistent = check_powertrain_constraints(
        demand_torque_nm=80.0,
        demand_power_kw=15.0,  # Conflicts with 34.48 kW
        vehicle_speed_ms=15.0,
        motor_config=default_motor,
        gearbox_config=default_gearbox,
    )
    assert res_inconsistent.overall_status == ConstraintStatus.VIOLATED
    assert res_inconsistent.power_status == ConstraintStatus.VIOLATED
    assert res_inconsistent.diagnostic_code == "ERR_TORQUE_POWER_INCONSISTENT"

    # 3. Consistent demand within tolerance
    res_consistent = check_powertrain_constraints(
        demand_torque_nm=80.0,
        demand_power_kw=34.48,  # Exactly matches within tolerance
        vehicle_speed_ms=15.0,
        motor_config=default_motor,
        gearbox_config=default_gearbox,
    )
    assert res_consistent.power_status == ConstraintStatus.SATISFIED
    assert res_consistent.overall_status == ConstraintStatus.SATISFIED


# ==============================================================================
# 17. PROVENANCE COMBINATION RULES (CORRECTION 4)
# ==============================================================================

def test_provenance_combination_rules(default_gearbox: GearboxConfig, default_motor: MotorConfig):
    """
    Verify all required provenance combination rules:
    - REAL + REAL -> REAL
    - REAL + ESTIMATED -> ESTIMATED
    - REAL + SIMULATED -> SIMULATED
    - REAL + UNKNOWN -> UNKNOWN
    - SIMULATED + ESTIMATED -> SIMULATED
    - Output must NEVER become REAL when any input is SIMULATED, ESTIMATED or UNKNOWN.
    """
    assert combine_provenance(DataStatus.REAL, DataStatus.REAL) == DataStatus.REAL
    assert combine_provenance(DataStatus.REAL, DataStatus.ESTIMATED) == DataStatus.ESTIMATED
    assert combine_provenance(DataStatus.REAL, DataStatus.SIMULATED) == DataStatus.SIMULATED
    assert combine_provenance(DataStatus.REAL, DataStatus.UNKNOWN) == DataStatus.UNKNOWN
    assert combine_provenance(DataStatus.SIMULATED, DataStatus.ESTIMATED) == DataStatus.SIMULATED

    # Verify across drivetrain transformations
    gb_real = default_gearbox.model_copy(update={"status": DataStatus.REAL})
    gb_est = default_gearbox.model_copy(update={"status": DataStatus.ESTIMATED})
    gb_sim = default_gearbox.model_copy(update={"status": DataStatus.SIMULATED})
    gb_unk = default_gearbox.model_copy(update={"status": DataStatus.UNKNOWN})

    # Traction transformation
    assert transform_forward_traction(1000.0, 15.0, gb_real, input_status=DataStatus.REAL).status == DataStatus.REAL
    assert transform_forward_traction(1000.0, 15.0, gb_est, input_status=DataStatus.REAL).status == DataStatus.ESTIMATED
    assert transform_forward_traction(1000.0, 15.0, gb_sim, input_status=DataStatus.REAL).status == DataStatus.SIMULATED
    assert transform_forward_traction(1000.0, 15.0, gb_unk, input_status=DataStatus.REAL).status == DataStatus.UNKNOWN
    assert transform_forward_traction(1000.0, 15.0, gb_sim, input_status=DataStatus.ESTIMATED).status == DataStatus.SIMULATED

    # Braking transformation
    assert transform_reverse_braking(-1000.0, 15.0, gb_real, input_status=DataStatus.REAL).status == DataStatus.REAL
    assert transform_reverse_braking(-1000.0, 15.0, gb_est, input_status=DataStatus.REAL).status == DataStatus.ESTIMATED


# ==============================================================================
# 18. STALL ELECTRICAL ASSUMPTIONS & INVERTER LOSS PROVENANCE (CORRECTION 5)
# ==============================================================================

def test_stall_electrical_assumptions_provenance(default_motor: MotorConfig):
    """
    Verify Correction 5:
    1. 3-phase RMS copper loss equation: P_stator = 3 * I_rms^2 * R_s.
    2. Explicit inverter loss configuration and provenance.
    3. Missing inverter loss marks CONDITIONAL with unverified estimate.
    4. Missing inverter current limit marks CONDITIONAL.
    """
    # 1. Stator copper loss calculation
    t_mot = 150.0  # Nm
    i_rms = t_mot / default_motor.k_t_rms  # 150 / 0.650 = 230.769 A_rms
    expected_copper = 3.0 * (i_rms ** 2) * default_motor.stator_resistance_ohm  # ~3195.27 W

    # 2. Configured REAL inverter loss (600 W)
    motor_with_real_inv = default_motor.model_copy(update={
        "inverter_standby_loss_w": 600.0,
        "inverter_loss_status": DataStatus.REAL,
    })
    res_real = compute_stall_dc_power(t_mot, motor_with_real_inv)
    assert res_real is not None
    assert pytest.approx(res_real.stator_copper_loss_w, rel=1e-6) == expected_copper
    assert pytest.approx(res_real.inverter_loss_w, rel=1e-6) == 600.0
    assert pytest.approx(res_real.total_stall_electrical_power_kw, rel=1e-6) == (expected_copper + 600.0) / 1000.0
    assert res_real.status == ConstraintStatus.SATISFIED
    assert res_real.provenance_status == DataStatus.REAL

    # 3. Missing inverter loss -> unverified 550 W fallback -> CONDITIONAL + ESTIMATED
    motor_missing_inv = default_motor.model_copy(update={
        "inverter_standby_loss_w": None,
        "inverter_loss_status": DataStatus.UNKNOWN,
    })
    res_unverified = compute_stall_dc_power(t_mot, motor_missing_inv)
    assert res_unverified is not None
    assert res_unverified.inverter_loss_w == 550.0
    assert res_unverified.status == ConstraintStatus.CONDITIONAL
    assert res_unverified.provenance_status == DataStatus.ESTIMATED

    # 4. Inverter current limit exceeded at stall
    motor_low_inv = default_motor.model_copy(update={"inverter_current_limit_rms": 200.0})
    res_exceeded = compute_stall_dc_power(t_mot, motor_low_inv)
    assert res_exceeded is not None
    assert res_exceeded.status == ConstraintStatus.VIOLATED


# ==============================================================================
# 19. EXHAUSTED BUDGET + DENIED PEAK: NO RECOVERY (CORRECTION C1.2)
# ==============================================================================

def test_exhausted_budget_denied_peak_no_recovery(default_motor: MotorConfig, default_gearbox: GearboxConfig):
    """
    Verify Requirement 1 & 4 of C1.2:
    - Exhausted peak budget (20.0s).
    - Request peak operation with demand exceeding continuous capability (180 Nm > 145 Nm).
    - Peak capability is denied.
    - Result: VIOLATED, diagnostic ERR_PEAK_BUDGET_EXHAUSTED.
    - Zero recovery is granted; exposure remains at 20.0s, is_exhausted remains True.
    """
    exhausted_state = PeakExposureState(
        cumulative_exposure_s=20.0,
        budget_s=20.0,
        recovery_rate_s_per_s=0.20,
        is_exhausted=True,
    )
    v = 10.0
    omega = compute_motor_speed(v, default_gearbox).motor_speed_rad_s
    t_overload = 180.0  # Exceeds continuous limit (145 Nm)
    p_overload = (t_overload * omega) / 1000.0

    res = check_powertrain_constraints(
        demand_torque_nm=t_overload,
        demand_power_kw=p_overload,
        vehicle_speed_ms=v,
        motor_config=default_motor,
        gearbox_config=default_gearbox,
        mode=OperatingEnvelopeMode.PEAK,
        peak_state=exhausted_state,
        dt_s=10.0,
    )

    assert res.overall_status == ConstraintStatus.VIOLATED
    assert res.diagnostic_code == "ERR_PEAK_BUDGET_EXHAUSTED"
    assert res.peak_requested is True
    assert res.peak_granted is False
    assert res.actual_operating_mode == ActualOperatingMode.INFEASIBLE
    assert res.is_peak_exhausted is True
    assert res.peak_state is not None
    # Crucial assertion: ZERO recovery granted when operating point exceeds continuous capability
    assert res.peak_state.cumulative_exposure_s == 20.0
    assert res.peak_state.is_exhausted is True
    assert res.peak_state.remaining_budget_s == 0.0


# ==============================================================================
# 20. EXHAUSTED BUDGET + VALID CONTINUOUS: RECOVERY OCCURS (CORRECTION C1.2)
# ==============================================================================

def test_exhausted_budget_valid_continuous_recovery(default_motor: MotorConfig, default_gearbox: GearboxConfig):
    """
    Verify Requirement 3 of C1.2:
    - Exhausted peak budget (20.0s).
    - Accepted operating point satisfies continuous envelope (100 Nm <= 145 Nm, P <= 65 kW).
    - Recovery is granted: delta_exposure = dt * recovery_rate = 25 * 0.20 = 5.0 s.
    - New exposure = 20.0 - 5.0 = 15.0 s, is_exhausted clears to False.
    """
    exhausted_state = PeakExposureState(
        cumulative_exposure_s=20.0,
        budget_s=20.0,
        recovery_rate_s_per_s=0.20,
        is_exhausted=True,
    )
    v = 15.0
    omega = compute_motor_speed(v, default_gearbox).motor_speed_rad_s
    t_cont = 100.0  # Within continuous limit (145 Nm)
    p_cont = (t_cont * omega) / 1000.0

    res = check_powertrain_constraints(
        demand_torque_nm=t_cont,
        demand_power_kw=p_cont,
        vehicle_speed_ms=v,
        motor_config=default_motor,
        gearbox_config=default_gearbox,
        mode=OperatingEnvelopeMode.CONTINUOUS,
        peak_state=exhausted_state,
        dt_s=25.0,
    )

    assert res.overall_status == ConstraintStatus.SATISFIED
    assert res.peak_requested is False
    assert res.peak_granted is False
    assert res.actual_operating_mode == ActualOperatingMode.CONTINUOUS
    assert res.is_peak_exhausted is False
    assert res.peak_state is not None
    assert pytest.approx(res.peak_state.cumulative_exposure_s, rel=1e-6) == 15.0
    assert pytest.approx(res.peak_state.remaining_budget_s, rel=1e-6) == 5.0
    assert res.peak_state.is_exhausted is False


# ==============================================================================
# 21. DENIED PEAK FOLLOWED BY RECOVERY AND SUBSEQUENT PEAK (CORRECTION C1.2)
# ==============================================================================

def test_denied_peak_then_recovery_then_subsequent_peak(default_motor: MotorConfig, default_gearbox: GearboxConfig):
    """
    Step 1: Peak budget exhausted (20s). Overload request (200 Nm) -> Denied, VIOLATED, no recovery (20s).
    Step 2: Continuous operation (90 Nm <= 145 Nm) for 30s -> Recovers 30 * 0.20 = 6s -> 14s (remaining 6s).
    Step 3: Subsequent peak request (200 Nm) for 4s -> GRANTED! Exposure becomes 14 + 4 = 18s (remaining 2s).
    Step 4: Subsequent peak request for 3s -> GRANTED for remaining 2s, saturates budget to 20s (exhausted).
    """
    v = 10.0
    omega = compute_motor_speed(v, default_gearbox).motor_speed_rad_s
    t_overload = 200.0
    p_overload = (t_overload * omega) / 1000.0

    t_cont = 90.0
    p_cont = (t_cont * omega) / 1000.0

    state_0 = PeakExposureState(cumulative_exposure_s=20.0, budget_s=20.0, recovery_rate_s_per_s=0.20, is_exhausted=True)

    # Step 1: Denied peak overload
    r1 = check_powertrain_constraints(
        demand_torque_nm=t_overload, demand_power_kw=p_overload, vehicle_speed_ms=v,
        motor_config=default_motor, gearbox_config=default_gearbox,
        mode=OperatingEnvelopeMode.PEAK, peak_state=state_0, dt_s=5.0,
    )
    assert r1.overall_status == ConstraintStatus.VIOLATED
    assert not r1.peak_granted
    assert r1.peak_state.cumulative_exposure_s == 20.0
    assert r1.peak_state.is_exhausted is True

    # Step 2: Valid continuous recovery for 30 s
    r2 = check_powertrain_constraints(
        demand_torque_nm=t_cont, demand_power_kw=p_cont, vehicle_speed_ms=v,
        motor_config=default_motor, gearbox_config=default_gearbox,
        mode=OperatingEnvelopeMode.CONTINUOUS, peak_state=r1.peak_state, dt_s=30.0,
    )
    assert r2.overall_status == ConstraintStatus.SATISFIED
    assert pytest.approx(r2.peak_state.cumulative_exposure_s, rel=1e-6) == 14.0
    assert r2.peak_state.is_exhausted is False

    # Step 3: Subsequent peak request for 4 s (budget available: 6s)
    r3 = check_powertrain_constraints(
        demand_torque_nm=t_overload, demand_power_kw=p_overload, vehicle_speed_ms=v,
        motor_config=default_motor, gearbox_config=default_gearbox,
        mode=OperatingEnvelopeMode.PEAK, peak_state=r2.peak_state, dt_s=4.0,
    )
    assert r3.overall_status == ConstraintStatus.SATISFIED
    assert r3.peak_granted is True
    assert pytest.approx(r3.peak_state.cumulative_exposure_s, rel=1e-6) == 18.0
    assert r3.peak_state.is_exhausted is False

    # Step 4: Subsequent peak request for 3 s -> hits 20s budget ceiling
    r4 = check_powertrain_constraints(
        demand_torque_nm=t_overload, demand_power_kw=p_overload, vehicle_speed_ms=v,
        motor_config=default_motor, gearbox_config=default_gearbox,
        mode=OperatingEnvelopeMode.PEAK, peak_state=r3.peak_state, dt_s=3.0,
    )
    assert r4.overall_status == ConstraintStatus.SATISFIED
    assert r4.peak_granted is True
    assert pytest.approx(r4.peak_state.cumulative_exposure_s, rel=1e-6) == 20.0
    assert r4.peak_state.is_exhausted is True


# ==============================================================================
# 22. BOUNDARY BEHAVIOR AT EXACTLY EXHAUSTED BUDGET (CORRECTION C1.2)
# ==============================================================================

def test_boundary_behavior_exactly_exhausted_budget(default_motor: MotorConfig, default_gearbox: GearboxConfig):
    """
    Test boundary behavior:
    1. Exactly at budget: cumulative_exposure_s == budget_s (20.0 == 20.0).
    2. Overload attempt: exposure cannot exceed budget (clamped at 20.0).
    3. Partial overload right at boundary (19.8s + 0.5s) -> clamped at 20.0s, is_exhausted becomes True.
    """
    # Boundary state
    boundary_state = PeakExposureState(cumulative_exposure_s=19.8, budget_s=20.0, recovery_rate_s_per_s=0.20, is_exhausted=False)
    assert pytest.approx(boundary_state.remaining_budget_s, rel=1e-6) == 0.2

    # Step that crosses boundary
    v = 10.0
    omega = compute_motor_speed(v, default_gearbox).motor_speed_rad_s
    t_overload = 190.0
    p_overload = (t_overload * omega) / 1000.0

    res = check_powertrain_constraints(
        demand_torque_nm=t_overload, demand_power_kw=p_overload, vehicle_speed_ms=v,
        motor_config=default_motor, gearbox_config=default_gearbox,
        mode=OperatingEnvelopeMode.PEAK, peak_state=boundary_state, dt_s=0.5,
    )
    assert res.overall_status == ConstraintStatus.SATISFIED
    assert res.peak_granted is True
    assert pytest.approx(res.peak_state.cumulative_exposure_s, rel=1e-6) == 20.0
    assert res.peak_state.is_exhausted is True
    assert res.peak_state.remaining_budget_s == 0.0


# ==============================================================================
# 23. INVALID OR CONTRADICTORY OPERATING-MODE INPUTS (CORRECTION C1.2)
# ==============================================================================

def test_invalid_or_contradictory_operating_modes(default_motor: MotorConfig, default_gearbox: GearboxConfig):
    """
    Validate rejection of invalid operating-mode inputs:
    - String that is not a valid OperatingEnvelopeMode enum value -> ValueError.
    - Type that is neither str nor OperatingEnvelopeMode -> TypeError.
    """
    with pytest.raises(ValueError, match="Invalid operating mode"):
        check_powertrain_constraints(
            demand_torque_nm=50.0,
            demand_power_kw=10.0,
            vehicle_speed_ms=10.0,
            motor_config=default_motor,
            gearbox_config=default_gearbox,
            mode="TURBO_HYPERDRIVE",
        )

    with pytest.raises(TypeError, match="Operating mode must be"):
        check_powertrain_constraints(
            demand_torque_nm=50.0,
            demand_power_kw=10.0,
            vehicle_speed_ms=10.0,
            motor_config=default_motor,
            gearbox_config=default_gearbox,
            mode=12345,  # type: ignore
        )


# ==============================================================================
# 24. C1.3 DEDICATED REGRESSION TEST SUITE (ACTUAL OPERATING REGIME INTEGRITY)
# ==============================================================================

def test_c1_3_peak_requested_sub_continuous_demand(default_motor: MotorConfig, default_gearbox: GearboxConfig):
    """
    Test 1: PEAK requested with sub-continuous demand (100 Nm vs 145 Nm limit).
    - peak_requested == True
    - peak_granted == True (thermal budget available)
    - actual_operating_mode == CONTINUOUS (demand is fully within S1 capability)
    - Thermal state receives RECOVERY, NOT exposure.
    """
    state_0 = PeakExposureState(
        cumulative_exposure_s=10.0,
        budget_s=20.0,
        recovery_rate_s_per_s=0.20,
        is_exhausted=False,
    )
    v = 15.0
    omega = compute_motor_speed(v, default_gearbox).motor_speed_rad_s
    t_demand = 100.0  # < 145 Nm continuous
    p_demand = (t_demand * omega) / 1000.0  # ~43.1 kW < 65 kW continuous

    res = check_powertrain_constraints(
        demand_torque_nm=t_demand,
        demand_power_kw=p_demand,
        vehicle_speed_ms=v,
        motor_config=default_motor,
        gearbox_config=default_gearbox,
        mode=OperatingEnvelopeMode.PEAK,
        peak_state=state_0,
        dt_s=10.0,
    )

    assert res.overall_status == ConstraintStatus.SATISFIED
    assert res.peak_requested is True
    assert res.peak_granted is True
    assert res.actual_operating_mode == ActualOperatingMode.CONTINUOUS
    assert res.peak_state is not None
    # 10.0 - (10.0 * 0.20) = 8.0 s -> RECOVERY, NOT exposure
    assert pytest.approx(res.peak_state.cumulative_exposure_s, rel=1e-6) == 8.0
    assert not res.peak_state.is_exhausted


def test_c1_3_peak_requested_valid_overload_demand(default_motor: MotorConfig, default_gearbox: GearboxConfig):
    """
    Test 2: PEAK requested with valid overload demand (200 Nm > 145 Nm, <= 245 Nm).
    - peak_requested == True
    - peak_granted == True
    - actual_operating_mode == PEAK
    - Thermal state receives EXPOSURE.
    """
    state_0 = PeakExposureState(
        cumulative_exposure_s=5.0,
        budget_s=20.0,
        recovery_rate_s_per_s=0.20,
        is_exhausted=False,
    )
    v = 10.0
    omega = compute_motor_speed(v, default_gearbox).motor_speed_rad_s
    t_demand = 200.0  # Overload above 145 Nm continuous, within 245 Nm peak
    p_demand = (t_demand * omega) / 1000.0

    res = check_powertrain_constraints(
        demand_torque_nm=t_demand,
        demand_power_kw=p_demand,
        vehicle_speed_ms=v,
        motor_config=default_motor,
        gearbox_config=default_gearbox,
        mode=OperatingEnvelopeMode.PEAK,
        peak_state=state_0,
        dt_s=6.0,
    )

    assert res.overall_status == ConstraintStatus.SATISFIED
    assert res.peak_requested is True
    assert res.peak_granted is True
    assert res.actual_operating_mode == ActualOperatingMode.PEAK
    assert res.peak_state is not None
    # 5.0 + 6.0 = 11.0 s -> EXPOSURE accumulates
    assert pytest.approx(res.peak_state.cumulative_exposure_s, rel=1e-6) == 11.0
    assert not res.peak_state.is_exhausted


def test_c1_3_peak_requested_exceeds_peak_torque_limit(default_motor: MotorConfig, default_gearbox: GearboxConfig):
    """
    Test 3: PEAK requested with demand exceeding peak torque limit (280 Nm vs 245 Nm limit).
    - peak_requested == True
    - actual_operating_mode == INFEASIBLE
    - overall_status == VIOLATED
    - Thermal state receives NO EXPOSURE accumulation.
    """
    state_0 = PeakExposureState(
        cumulative_exposure_s=5.0,
        budget_s=20.0,
        recovery_rate_s_per_s=0.20,
        is_exhausted=False,
    )
    v = 10.0
    omega = compute_motor_speed(v, default_gearbox).motor_speed_rad_s
    t_demand = 280.0  # Exceeds peak max 245 Nm
    p_demand = (t_demand * omega) / 1000.0

    res = check_powertrain_constraints(
        demand_torque_nm=t_demand,
        demand_power_kw=p_demand,
        vehicle_speed_ms=v,
        motor_config=default_motor,
        gearbox_config=default_gearbox,
        mode=OperatingEnvelopeMode.PEAK,
        peak_state=state_0,
        dt_s=5.0,
    )

    assert res.overall_status == ConstraintStatus.VIOLATED
    assert res.torque_status == ConstraintStatus.VIOLATED
    assert res.peak_requested is True
    assert res.actual_operating_mode == ActualOperatingMode.INFEASIBLE
    assert res.peak_state is not None
    # State preserved, NO exposure accumulation and NO recovery
    assert res.peak_state.cumulative_exposure_s == 5.0


def test_c1_3_demand_exceeds_inverter_current_limit(default_motor: MotorConfig, default_gearbox: GearboxConfig):
    """
    Test 4: Demand exceeding inverter current limit:
    - Mechanically within nominal torque and speed envelope (180 Nm <= 245 Nm).
    - But stator current (180 / 0.65 = 276.9 A) exceeds inverter limit (200 A).
    - actual_operating_mode == INFEASIBLE
    - overall_status == VIOLATED, diagnostic == ERR_CURRENT_EXCEEDED
    - Thermal state receives NO EXPOSURE accumulation and NO RECOVERY.
    """
    motor_with_limited_inverter = default_motor.model_copy(update={"inverter_current_limit_rms": 200.0})
    state_0 = PeakExposureState(
        cumulative_exposure_s=7.0,
        budget_s=20.0,
        recovery_rate_s_per_s=0.20,
        is_exhausted=False,
    )
    v = 10.0
    omega = compute_motor_speed(v, default_gearbox).motor_speed_rad_s
    t_demand = 180.0  # Needs 276.92 A rms > 200 A limit
    p_demand = (t_demand * omega) / 1000.0

    res = check_powertrain_constraints(
        demand_torque_nm=t_demand,
        demand_power_kw=p_demand,
        vehicle_speed_ms=v,
        motor_config=motor_with_limited_inverter,
        gearbox_config=default_gearbox,
        mode=OperatingEnvelopeMode.PEAK,
        peak_state=state_0,
        dt_s=5.0,
    )

    assert res.overall_status == ConstraintStatus.VIOLATED
    assert res.current_status == ConstraintStatus.VIOLATED
    assert res.diagnostic_code == "ERR_CURRENT_EXCEEDED"
    assert res.actual_operating_mode == ActualOperatingMode.INFEASIBLE
    assert res.peak_state is not None
    # State preserved: NO exposure and NO recovery
    assert res.peak_state.cumulative_exposure_s == 7.0


def test_c1_3_continuous_demand_inverter_current_violated_no_recovery(default_motor: MotorConfig, default_gearbox: GearboxConfig):
    """
    Test 5: Continuous torque/power demand but inverter current limit violated:
    - Mechanically within continuous envelope (100 Nm <= 145 Nm).
    - But stator current (100 / 0.65 = 153.85 A) exceeds tight inverter limit (100 A).
    - No verified continuous operation.
    - actual_operating_mode == INFEASIBLE
    - Thermal state receives NO RECOVERY.
    """
    motor_with_tight_inverter = default_motor.model_copy(update={"inverter_current_limit_rms": 100.0})
    state_0 = PeakExposureState(
        cumulative_exposure_s=10.0,
        budget_s=20.0,
        recovery_rate_s_per_s=0.20,
        is_exhausted=False,
    )
    v = 15.0
    omega = compute_motor_speed(v, default_gearbox).motor_speed_rad_s
    t_demand = 100.0  # Within 145 Nm continuous, but 153.85 A > 100 A
    p_demand = (t_demand * omega) / 1000.0

    res = check_powertrain_constraints(
        demand_torque_nm=t_demand,
        demand_power_kw=p_demand,
        vehicle_speed_ms=v,
        motor_config=motor_with_tight_inverter,
        gearbox_config=default_gearbox,
        mode=OperatingEnvelopeMode.CONTINUOUS,
        peak_state=state_0,
        dt_s=10.0,
    )

    assert res.overall_status == ConstraintStatus.VIOLATED
    assert res.current_status == ConstraintStatus.VIOLATED
    assert res.diagnostic_code == "ERR_CURRENT_EXCEEDED"
    assert res.actual_operating_mode == ActualOperatingMode.INFEASIBLE
    assert res.peak_state is not None
    # Stays at 10.0s: NO RECOVERY granted
    assert res.peak_state.cumulative_exposure_s == 10.0


def test_c1_3_valid_continuous_operation_recovery(default_motor: MotorConfig, default_gearbox: GearboxConfig):
    """
    Test 6: Valid continuous operation with all constraints satisfied:
    - Torque, speed, power, and stator current all satisfied within continuous envelope.
    - Thermal state receives RECOVERY.
    """
    state_0 = PeakExposureState(
        cumulative_exposure_s=12.0,
        budget_s=20.0,
        recovery_rate_s_per_s=0.20,
        is_exhausted=False,
    )
    v = 15.0
    omega = compute_motor_speed(v, default_gearbox).motor_speed_rad_s
    t_demand = 100.0  # 153.85 A <= 400 A inverter limit, 100 <= 145 Nm
    p_demand = (t_demand * omega) / 1000.0

    res = check_powertrain_constraints(
        demand_torque_nm=t_demand,
        demand_power_kw=p_demand,
        vehicle_speed_ms=v,
        motor_config=default_motor,
        gearbox_config=default_gearbox,
        mode=OperatingEnvelopeMode.CONTINUOUS,
        peak_state=state_0,
        dt_s=10.0,
    )

    assert res.overall_status == ConstraintStatus.SATISFIED
    assert res.current_status == ConstraintStatus.SATISFIED
    assert res.actual_operating_mode == ActualOperatingMode.CONTINUOUS
    assert res.peak_state is not None
    # 12.0 - (10.0 * 0.20) = 10.0 s -> RECOVERY applied
    assert pytest.approx(res.peak_state.cumulative_exposure_s, rel=1e-6) == 10.0


def test_c1_3_exhausted_peak_budget_denied_overload_infeasible(default_motor: MotorConfig, default_gearbox: GearboxConfig):
    """
    Test 7: Exhausted peak budget with demand exceeding continuous capability:
    - peak_requested == True
    - peak_granted == False
    - actual_operating_mode == INFEASIBLE
    - overall_status == VIOLATED, diagnostic == ERR_PEAK_BUDGET_EXHAUSTED
    - Thermal state receives NO RECOVERY; exhausted state preserved.
    """
    exhausted_state = PeakExposureState(
        cumulative_exposure_s=20.0,
        budget_s=20.0,
        recovery_rate_s_per_s=0.20,
        is_exhausted=True,
    )
    v = 10.0
    omega = compute_motor_speed(v, default_gearbox).motor_speed_rad_s
    t_demand = 180.0  # Exceeds continuous limit 145 Nm
    p_demand = (t_demand * omega) / 1000.0

    res = check_powertrain_constraints(
        demand_torque_nm=t_demand,
        demand_power_kw=p_demand,
        vehicle_speed_ms=v,
        motor_config=default_motor,
        gearbox_config=default_gearbox,
        mode=OperatingEnvelopeMode.PEAK,
        peak_state=exhausted_state,
        dt_s=5.0,
    )

    assert res.overall_status == ConstraintStatus.VIOLATED
    assert res.diagnostic_code == "ERR_PEAK_BUDGET_EXHAUSTED"
    assert res.peak_requested is True
    assert res.peak_granted is False
    assert res.actual_operating_mode == ActualOperatingMode.INFEASIBLE
    assert res.is_peak_exhausted is True
    assert res.peak_state is not None
    assert res.peak_state.cumulative_exposure_s == 20.0
    assert res.peak_state.is_exhausted is True


def test_c1_3_sequential_segment_propagation_mixed_regimes(default_motor: MotorConfig, default_gearbox: GearboxConfig):
    """
    Test 8: Sequential segment propagation across mixed operating regimes:
    Correctly updates thermal budget across segments requiring continuous, peak, and infeasible operation.
    - Seg 1: Valid Peak overload (200 Nm, dt=5s) -> actual mode PEAK, exposure: 0 -> 5s.
    - Seg 2: Sub-continuous demand with PEAK requested (100 Nm, dt=10s) -> actual mode CONTINUOUS,
             recovers 10 * 0.20 = 2s -> exposure: 3s.
    - Seg 3: Infeasible overload exceeding peak capability (280 Nm, dt=5s) -> actual mode INFEASIBLE,
             VIOLATED, exposure preserved at 3s.
    - Seg 4: Continuous demand with CONTINUOUS requested (90 Nm, dt=15s) -> actual mode CONTINUOUS,
             SATISFIED, recovers 15 * 0.20 = 3s -> exposure: 0s.
    """
    v = 10.0
    omega = compute_motor_speed(v, default_gearbox).motor_speed_rad_s

    # Segment 1: Valid Peak overload
    t1 = 200.0
    p1 = (t1 * omega) / 1000.0
    s1 = check_powertrain_constraints(
        demand_torque_nm=t1, demand_power_kw=p1, vehicle_speed_ms=v,
        motor_config=default_motor, gearbox_config=default_gearbox,
        mode=OperatingEnvelopeMode.PEAK,
        peak_state=PeakExposureState(budget_s=20.0, recovery_rate_s_per_s=0.20),
        dt_s=5.0,
    )
    assert s1.overall_status == ConstraintStatus.SATISFIED
    assert s1.peak_granted is True
    assert s1.actual_operating_mode == ActualOperatingMode.PEAK
    assert pytest.approx(s1.peak_state.cumulative_exposure_s, rel=1e-6) == 5.0

    # Segment 2: Sub-continuous demand with PEAK requested
    t2 = 100.0
    p2 = (t2 * omega) / 1000.0
    s2 = check_powertrain_constraints(
        demand_torque_nm=t2, demand_power_kw=p2, vehicle_speed_ms=v,
        motor_config=default_motor, gearbox_config=default_gearbox,
        mode=OperatingEnvelopeMode.PEAK, peak_state=s1.peak_state, dt_s=10.0,
    )
    assert s2.overall_status == ConstraintStatus.SATISFIED
    assert s2.peak_requested is True
    assert s2.actual_operating_mode == ActualOperatingMode.CONTINUOUS
    assert pytest.approx(s2.peak_state.cumulative_exposure_s, rel=1e-6) == 3.0  # 5.0 - 2.0

    # Segment 3: Infeasible overload exceeding peak capability (280 Nm > 245 Nm)
    t3 = 280.0
    p3 = (t3 * omega) / 1000.0
    s3 = check_powertrain_constraints(
        demand_torque_nm=t3, demand_power_kw=p3, vehicle_speed_ms=v,
        motor_config=default_motor, gearbox_config=default_gearbox,
        mode=OperatingEnvelopeMode.PEAK, peak_state=s2.peak_state, dt_s=5.0,
    )
    assert s3.overall_status == ConstraintStatus.VIOLATED
    assert s3.actual_operating_mode == ActualOperatingMode.INFEASIBLE
    assert pytest.approx(s3.peak_state.cumulative_exposure_s, rel=1e-6) == 3.0  # Preserved!

    # Segment 4: Valid continuous demand
    t4 = 90.0
    p4 = (t4 * omega) / 1000.0
    s4 = check_powertrain_constraints(
        demand_torque_nm=t4, demand_power_kw=p4, vehicle_speed_ms=v,
        motor_config=default_motor, gearbox_config=default_gearbox,
        mode=OperatingEnvelopeMode.CONTINUOUS, peak_state=s3.peak_state, dt_s=15.0,
    )
    assert s4.overall_status == ConstraintStatus.SATISFIED
    assert s4.actual_operating_mode == ActualOperatingMode.CONTINUOUS
    assert pytest.approx(s4.peak_state.cumulative_exposure_s, rel=1e-6) == 0.0  # Clamped at 0.0


def test_c1_3_missing_inverter_current_limit_conditional_no_recovery(default_motor: MotorConfig, default_gearbox: GearboxConfig):
    """
    Test 9: Missing inverter current limit:
    - inverter_current_limit_rms is None.
    - Yields CONDITIONAL status for current and overall.
    - Precludes claiming verified continuous acceptance.
    - Thermal state receives NO RECOVERY.
    """
    motor_no_current_limit = default_motor.model_copy(update={"inverter_current_limit_rms": None})
    state_0 = PeakExposureState(
        cumulative_exposure_s=10.0,
        budget_s=20.0,
        recovery_rate_s_per_s=0.20,
        is_exhausted=False,
    )
    v = 15.0
    omega = compute_motor_speed(v, default_gearbox).motor_speed_rad_s
    t_demand = 100.0
    p_demand = (t_demand * omega) / 1000.0

    res = check_powertrain_constraints(
        demand_torque_nm=t_demand,
        demand_power_kw=p_demand,
        vehicle_speed_ms=v,
        motor_config=motor_no_current_limit,
        gearbox_config=default_gearbox,
        mode=OperatingEnvelopeMode.CONTINUOUS,
        peak_state=state_0,
        dt_s=10.0,
    )

    assert res.current_status == ConstraintStatus.CONDITIONAL
    assert res.overall_status == ConstraintStatus.CONDITIONAL
    assert res.actual_operating_mode == ActualOperatingMode.CONTINUOUS
    assert res.peak_state is not None
    # Crucial: NO recovery granted because current check is CONDITIONAL (unverified),
    # so is_within_continuous is False!
    assert res.peak_state.cumulative_exposure_s == 10.0

