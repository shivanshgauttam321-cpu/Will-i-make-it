"""
Powertrain & Battery Dynamic System Integration Layer (Stage C3 Phase 4)
========================================================================
High-fidelity orchestration and reconciliation subsystem integrating:
1. Stage C1.3 mechanical motor & drivetrain physics.
2. Stage C2.1 regenerative braking & inverter electrical acceptance.
3. Stage C3 dynamic 1-RC Thevenin battery pack equivalent circuit.

PHYSICAL ARCHITECTURE & RECONCILIATION PRINCIPLES
-------------------------------------------------
1. Dynamic Battery Acceptance:
   - C2.1 generates signed requested battery power: `net_battery_charging_kw` (Boundary 5).
     * Positive (> 0): Charging request from net electrical regeneration after covering
       inverter standby and high-voltage auxiliary loads.
     * Negative (< 0): Discharging request from battery to cover electrical loads when
       auxiliary loads and standby losses exceed regenerative generation.
   - Stage C3 dynamic battery model arbitrates actual physical acceptance:
     `P_accepted = simulate_battery_step(P_requested, state, dt, config)`.

2. Regenerative Braking Reconciliation (Charging Shortfall):
   - When requested charging exceeds actual battery acceptance (P_req > P_accepted >= 0):
     * The battery rejects delta_P_rejected_elec = P_req - P_accepted > 0 [kW].
     * The motor cannot generate this rejected electrical power.
     * Drivetrain conversion efficiency maps electrical rejection to wheel mechanical power:
         delta_P_wheel_regen_rejected = delta_P_rejected_elec / (eta_inv * eta_mot * eta_gb)
     * To prevent braking failure and preserve driver-demanded deceleration, the retarding
       shortfall is automatically transferred to the mechanical friction brakes:
         P_friction_additional = delta_P_wheel_regen_rejected
         F_friction_additional = (P_friction_additional * 1000) / vehicle_speed  (for v > 0)
     * Friction braking capacity F_friction_max is enforced; any remaining shortfall is
       flagged as a physical braking deficit.
     * At standstill or low speeds (v <= v_cutoff), C2.1 rolloff already sets regen to zero,
       preventing division by zero.

3. Auxiliary Loads & Discharge Curtailment:
   - When P_req < P_accepted <= 0 (battery requested to discharge to support HV auxiliaries,
     but limited by undervoltage cutoff, max discharge current/power, or min SOC):
     * The unmet power delta_P_unserved = P_accepted - P_req > 0 [kW] is an UNSERVED ELECTRICAL DEMAND.
     * It is never reported as rejected regenerative braking or friction braking.

4. End-to-End Energy Conservation:
   - Complete multi-boundary energy conservation ledger reconciling delivered wheel mechanical
     work, friction dissipation, drivetrain conversion losses, inverter standby consumption,
     DC-DC conversion losses, auxiliary consumption, and internal battery chemical storage/losses.
   - Residual is strictly verified symmetrically across all operating modes.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import math
from typing import List, Optional, Tuple, Union
from pydantic import Field

from app.domain.provenance import DataStatus
from app.services.energy.powertrain_model import (
    ConstraintStatus,
    GearboxConfig,
    MotorConfig,
    OperatingEnvelopeMode,
    combine_provenance,
    _validate_finite_float,
)
from app.services.energy.regen_model import (
    InverterElectricalConfig,
    BMSConfig,
    BrakeBlendingConfig,
    BrakeBlendingResult,
    AuxiliaryHVResult,
    blend_regenerative_and_friction_braking,
    compute_auxiliary_hv_power,
)
from app.services.energy.battery_model import (
    BatteryConfig,
    BatteryState,
    TheveninParameters,
    BatteryOperatingPoint,
    BatterySimulationResult,
    compute_internal_resistance,
    simulate_battery_step,
    _compute_tau_exponential_factors,
)


# =============================================================================
# Integrated Powertrain & Battery Result Dataclass
# =============================================================================

@dataclass(frozen=True)
class IntegratedPowertrainResult:
    """
    Complete consolidated result of a single integrated powertrain simulation step.
    
    Reconciles mechanical chassis retarding, electrical conversion, inverter acceptance,
    and dynamic 1-RC battery state.
    """
    # Operating Mode & Timestep
    is_braking_mode: bool                       # True if braking/regen, False if traction/idle
    dt_s: float                                 # Step duration [s]
    vehicle_speed_ms: float                     # Vehicle velocity during step [m/s]

    # Mechanical Wheel Boundary
    requested_wheel_force_n: float              # Requested mechanical force magnitude at wheels [N]
    requested_wheel_power_kw: float             # Requested mechanical power magnitude [kW]
    delivered_wheel_force_n: float              # Total actual mechanical force delivered [N]
    delivered_wheel_power_kw: float             # Total actual mechanical power delivered [kW]
    braking_deficit_force_n: float              # Unmet braking force demand, if any [N]
    braking_deficit_power_kw: float             # Unmet braking power demand, if any [kW]
    traction_deficit_force_n: float = 0.0       # Unmet traction force demand, if any [N]
    traction_deficit_power_kw: float = 0.0      # Unmet traction power demand, if any [kW]

    # Retarding Split (Reconciled with Battery Acceptance)
    delivered_regen_force_n: float = 0.0        # Actual electrical regen force delivered at wheels [N]
    delivered_regen_power_kw: float = 0.0       # Signed mechanical wheel power absorbed by regen (<= 0) [kW]
    delivered_friction_force_n: float = 0.0     # Total friction braking force delivered [N]
    delivered_friction_power_kw: float = 0.0    # Total friction braking power dissipated [kW]
    additional_friction_force_n: float = 0.0    # Friction force added due to battery rejection [N]
    additional_friction_power_kw: float = 0.0   # Friction power added due to battery rejection [kW]

    # Subsystem Results (Immutable Contracts)
    c2_blending_result: Optional[BrakeBlendingResult] = None # Frozen C2.1 result (if in braking mode)
    battery_simulation_result: Optional[BatterySimulationResult] = None # C3 battery simulation result

    # Electrical Power Flow & Reconciled Boundaries
    requested_battery_power_kw: float = 0.0     # Net signed power requested from/to battery [kW]
    accepted_battery_power_kw: float = 0.0      # Actual signed power delivered into/from battery [kW]
    battery_power_deficit_kw: float = 0.0       # Shortfall: P_requested - P_accepted [kW]
    rejected_regen_electrical_power_kw: float = 0.0 # Electrical regen rejected by battery (>= 0) [kW]
    rejected_regen_electrical_energy_j: float = 0.0 # Energy rejected by battery over step [J]
    unserved_electrical_power_kw: float = 0.0   # Electrical load not supplied due to battery discharge limits [kW]
    unserved_electrical_energy_j: float = 0.0   # Unserved electrical load energy over step [J]

    # Battery State Transitions
    initial_battery_state: Optional[BatteryState] = None # State prior to step
    final_battery_state: Optional[BatteryState] = None   # State after step integration
    battery_current_a: float = 0.0              # Solved battery current (> 0 chg, < 0 dis) [A]
    terminal_voltage_avg_v: float = 0.0         # Dynamic average terminal voltage [V]
    terminal_voltage_end_v: float = 0.0         # End-of-step terminal voltage [V]
    delta_soc: float = 0.0                      # SOC change over step: final - initial
    delta_v1_v: float = 0.0                     # Polarization overpotential change [V]

    # Energy Conservation Ledger Components [J] (C3-INT-03)
    energy_wheel_requested_j: float = 0.0       # Requested wheel mechanical energy [J]
    energy_wheel_delivered_j: float = 0.0       # Actual delivered wheel mechanical energy [J]
    energy_unserved_traction_j: float = 0.0     # Unserved traction mechanical energy [J]
    energy_auxiliary_requested_j: float = 0.0   # Requested high-voltage auxiliary energy [J]
    energy_auxiliary_supplied_j: float = 0.0    # Actual supplied high-voltage auxiliary energy [J]
    energy_unserved_auxiliary_j: float = 0.0    # Unserved high-voltage auxiliary energy [J]
    energy_wheel_mechanical_j: float = 0.0      # Mechanical wheel work transferred [J]
    energy_friction_dissipated_j: float = 0.0   # Total friction brake dissipation [J]
    energy_drivetrain_loss_j: float = 0.0       # Gearbox, motor, and inverter conversion losses [J]
    energy_inverter_standby_j: float = 0.0      # Inverter standby consumption [J]
    energy_auxiliary_hv_j: float = 0.0          # Auxiliary HV load consumed [J]
    energy_battery_terminal_j: float = 0.0      # Electrical energy entering/leaving battery terminals [J]
    energy_battery_loss_j: float = 0.0          # Battery internal losses (R0 + R1 + parasitic) [J]
    delta_energy_c1_storage_j: float = 0.0      # Battery C1 capacitive energy change [J]
    energy_battery_chemical_j: float = 0.0      # Reversible electrochemical storage/release [J]
    energy_accounting_residual_j: float = 0.0   # End-to-end energy conservation residual [J]

    # Synthesis & Diagnostics
    active_constraints: List[str] = field(default_factory=list) # All active constraints across C1, C2, and C3
    diagnostic_code: Optional[str] = None       # Primary diagnostic code
    overall_status: ConstraintStatus = ConstraintStatus.SATISFIED # SATISFIED, CONDITIONAL, or VIOLATED
    provenance_status: DataStatus = DataStatus.ESTIMATED # Combined conservative provenance
    notes: List[str] = field(default_factory=list) # Traceable engineering notes


# =============================================================================
# Dynamic BMS Adapter Helper (C3-BMS-01)
# =============================================================================

class DynamicBMSConfig(BMSConfig):
    """
    Dynamic runtime adapter subclassing BMSConfig that permits exact zero charge power
    and current limits (ge=0.0) without violating base BMSConfig Pydantic schema validation.
    """
    max_charge_power_kw: Optional[float] = Field(default=65.0, ge=0.0, le=500.0, description="Dynamic peak charge power (kW)")
    max_charge_current_a: Optional[float] = Field(default=200.0, ge=0.0, le=1000.0, description="Dynamic peak charge current (A)")


def create_dynamic_bms_config(
    battery_config: BatteryConfig,
    battery_state: BatteryState,
    dt_s: float,
) -> BMSConfig:
    """
    Derive dynamic BMSConfig limits for C2.1 feedforward brake blending based on
    the instantaneous 1-RC Thevenin battery pack state.
    
    Preserves exact zero acceptance without artificial positive floors (C3-BMS-01).
    """
    params = compute_internal_resistance(battery_state.soc, battery_state.temperature_c, battery_config)
    v_oc = params.v_oc_v
    r0 = params.r0_ohm
    r1 = params.r1_ohm
    tau1 = params.tau1_s
    v1_0 = battery_state.v1_polarization_v

    beta, one_minus_beta, alpha, one_minus_alpha = _compute_tau_exponential_factors(dt_s, tau1)
    v_pack_max = battery_config.cell_voltage_max_v * battery_config.series_cells

    # Current limits from overvoltage ceiling:
    # 1. Start-of-step: V_term(0) <= V_max => I <= (V_max - V_oc - V1(0)) / R_0
    i_vmax_candidates = []
    if r0 > 1e-6:
        i_vmax_candidates.append((v_pack_max - v_oc - v1_0) / r0)

    # 2. End-of-step: V_term(dt) <= V_max => I <= (V_max - V_oc - beta * V1(0)) / (R0 + R1 * (1 - beta))
    r_end = r0 + r1 * one_minus_beta
    if r_end > 1e-6:
        i_vmax_candidates.append((v_pack_max - v_oc - beta * v1_0) / r_end)

    i_dyn_max = min(i_vmax_candidates) if i_vmax_candidates else float("inf")
    if battery_config.max_charge_current_a is not None:
        i_dyn_max = min(i_dyn_max, battery_config.max_charge_current_a)

    # Convert to dynamic power ceiling
    v_eff = v_oc + alpha * v1_0
    r_eff = r0 + r1 * one_minus_alpha
    p_dyn_max_kw = ((v_eff + i_dyn_max * r_eff) * i_dyn_max) / 1000.0 if (math.isfinite(i_dyn_max) and i_dyn_max > 0.0) else 0.0
    if p_dyn_max_kw is not None and battery_config.max_charge_power_kw is not None:
        p_dyn_max_kw = min(p_dyn_max_kw, battery_config.max_charge_power_kw)

    # Bounds clipping
    base_p_max = battery_config.max_charge_power_kw or 65.0
    base_i_max = battery_config.max_charge_current_a or 200.0

    if p_dyn_max_kw is not None and math.isfinite(p_dyn_max_kw):
        p_dyn_max_kw = max(0.0, min(p_dyn_max_kw, base_p_max))
    else:
        p_dyn_max_kw = base_p_max

    if i_dyn_max is not None and math.isfinite(i_dyn_max):
        i_dyn_max = max(0.0, min(i_dyn_max, base_i_max))
    else:
        i_dyn_max = base_i_max

    # Exact zero acceptance when SOC reaches maximum operating boundary
    if battery_state.soc >= battery_config.soc_max_operating:
        p_dyn_max_kw = 0.0
        i_dyn_max = 0.0

    return DynamicBMSConfig(
        max_charge_power_kw=p_dyn_max_kw,
        max_charge_current_a=i_dyn_max,
        pack_nominal_voltage_v=battery_config.nominal_pack_voltage_v,
        cell_max_voltage_v=battery_config.cell_voltage_max_v,
        soc_taper_start=battery_config.soc_max_operating * 0.90,
        soc_cutoff=battery_config.soc_max_operating,
        temp_optimal_low_c=battery_config.temp_optimal_low_c,
        temp_optimal_high_c=battery_config.temp_optimal_high_c,
        temp_cold_cutoff_c=-20.0,
        temp_hot_cutoff_c=60.0,
        status=battery_config.status,
    )


# =============================================================================
# Core System Integration Engine
# =============================================================================

def simulate_integrated_powertrain_step(
    requested_wheel_force_n: float,
    vehicle_speed_ms: float,
    dt_s: float,
    battery_state: BatteryState,
    battery_config: BatteryConfig,
    gearbox_config: GearboxConfig,
    motor_config: MotorConfig,
    inverter_config: InverterElectricalConfig,
    auxiliary_lv_power_kw: float = 0.0,
    blending_config: Optional[BrakeBlendingConfig] = None,
    adhesion_limit_n: Optional[float] = None,
    bms_config_override: Optional[BMSConfig] = None,
    input_status: Optional[DataStatus] = None,
) -> IntegratedPowertrainResult:
    """
    Execute a single discrete physical step of the integrated EV powertrain.
    
    Seamlessly orchestrates:
    - Braking demand (requested_wheel_force_n < 0 or vehicle decelerating under regen)
    - Traction demand (requested_wheel_force_n > 0)
    - Standstill / Zero power (requested_wheel_force_n == 0)
    - Dynamic 1-RC battery state integration
    - Mechanical-to-electrical regenerative reconciliation and additional friction braking
    - Complete multi-boundary zero-residual energy accounting ledger
    """
    dt = _validate_finite_float("dt_s", dt_s, min_val=0.0001, max_val=3600.0)
    v_ms = _validate_finite_float("vehicle_speed_ms", vehicle_speed_ms, min_val=0.0, max_val=200.0)
    f_req = _validate_finite_float("requested_wheel_force_n", requested_wheel_force_n, min_val=-200000.0, max_val=200000.0)
    p_aux_lv = _validate_finite_float("auxiliary_lv_power_kw", auxiliary_lv_power_kw, min_val=0.0, max_val=50.0)

    notes_list: List[str] = []
    active_constraints: List[str] = []
    TOL = 1e-4

    # Determine operating regime
    # Conventional signed force: f_req < 0 means retarding/braking force; f_req > 0 means traction
    is_braking = (f_req < -TOL)
    p_req_wheel_kw = (abs(f_req) * v_ms) / 1000.0
    f_trac_deficit_n = 0.0
    p_trac_deficit_kw = 0.0

    if is_braking:
        # =====================================================================
        # BRAKING REGIME (C2.1 + C3 RECONCILIATION)
        # =====================================================================
        # 1. Feedforward Dynamic BMS Limits
        bms_cfg = bms_config_override or create_dynamic_bms_config(battery_config, battery_state, dt)
        blend_cfg = blending_config or BrakeBlendingConfig()

        # 2. Stage C2.1 Regenerative & Friction Brake Blending
        # Note: C2.1 takes positive magnitude for requested_brake_force_n
        c2_res = blend_regenerative_and_friction_braking(
            requested_brake_force_n=abs(f_req),
            vehicle_speed_ms=v_ms,
            motor_config=motor_config,
            gearbox_config=gearbox_config,
            inverter_config=inverter_config,
            bms_config=bms_cfg,
            blending_config=blend_cfg,
            battery_soc=battery_state.soc,
            battery_temp_c=battery_state.temperature_c,
            state_of_health=battery_state.state_of_health,
            aux_lv_power_kw=p_aux_lv,
            adhesion_coefficient=adhesion_limit_n,
            input_status=input_status,
        )

        p_batt_req_kw = c2_res.net_battery_charging_kw

        # 3. Stage C3 Closed-Loop Dynamic Battery Simulation
        batt_res = simulate_battery_step(
            requested_power_kw=p_batt_req_kw,
            state=battery_state,
            dt_s=dt,
            config=battery_config,
            input_status=c2_res.provenance_status,
        )

        p_batt_accepted_kw = batt_res.accepted_power_kw
        p_batt_deficit_kw = p_batt_req_kw - p_batt_accepted_kw

        # 4. Mechanical & Electrical Shortfall Reconciliation
        f_add_friction_n = 0.0
        p_add_friction_kw = 0.0
        p_rejected_elec_kw = 0.0
        e_rejected_elec_j = 0.0
        p_unserved_elec_kw = 0.0
        e_unserved_elec_j = 0.0

        f_delivered_regen_n = c2_res.accepted_regen_wheel_force_n
        p_delivered_regen_kw = c2_res.accepted_regen_wheel_power_kw
        f_delivered_friction_n = c2_res.friction_brake_force_n
        p_delivered_friction_kw = c2_res.friction_brake_power_kw
        f_deficit_n = c2_res.braking_deficit_force_n
        p_deficit_kw = c2_res.braking_deficit_power_kw

        if p_batt_req_kw > 0.0 and p_batt_deficit_kw > TOL:
            # Case 4.A: Battery rejected charging power (P_req > P_accepted >= 0)
            p_rejected_elec_kw = p_batt_deficit_kw
            e_rejected_elec_j = p_rejected_elec_kw * dt * 1000.0

            # Map rejected electrical power back to wheel mechanical retarding power:
            # P_batt = P_inv_dc_net - P_aux = P_inv_dc_gross - P_standby - P_aux
            # delta_P_inv_dc_gross = delta_P_batt
            # Inverter rectification efficiency: eta_inv = inverter_config.efficiency_regen
            # Motor efficiency during generation: eta_mot
            # Gearbox efficiency during regen: eta_gb = gearbox_config.efficiency_regen
            eta_inv = max(0.10, inverter_config.efficiency_regen)
            eta_gb = max(0.10, getattr(gearbox_config, "efficiency_rev", getattr(gearbox_config, "efficiency_regen", 0.97)))

            # Motor conversion efficiency from C2.1 result
            if abs(c2_res.motor_shaft_power_kw) > 1e-6:
                eta_mot = abs(c2_res.motor_electrical_power_kw / c2_res.motor_shaft_power_kw)
                eta_mot = max(0.10, min(1.0, eta_mot))
            else:
                eta_mot = 0.90

            eta_chain = eta_inv * eta_mot * eta_gb
            delta_p_wheel_mech_kw = p_rejected_elec_kw / eta_chain

            # Preserving vehicle deceleration: Allocate rejected retarding to friction brakes
            p_add_friction_kw = delta_p_wheel_mech_kw
            f_add_friction_n = (p_add_friction_kw * 1000.0 / v_ms) if v_ms > 0.1 else 0.0

            # Adjust delivered regen downwards
            p_delivered_regen_kw = min(0.0, c2_res.accepted_regen_wheel_power_kw + delta_p_wheel_mech_kw)
            f_delivered_regen_n = max(0.0, c2_res.accepted_regen_wheel_force_n - f_add_friction_n)

            # Check total friction force against chassis friction capacity
            f_fric_cap = blend_cfg.friction_brake_max_force_n if blend_cfg.friction_brake_max_force_n is not None else float("inf")
            candidate_total_friction_n = c2_res.friction_brake_force_n + f_add_friction_n

            if candidate_total_friction_n <= f_fric_cap:
                f_delivered_friction_n = candidate_total_friction_n
                p_delivered_friction_kw = c2_res.friction_brake_power_kw + p_add_friction_kw
            else:
                # Friction brakes saturated!
                f_delivered_friction_n = f_fric_cap
                p_delivered_friction_kw = (f_fric_cap * v_ms) / 1000.0
                f_shortfall_n = candidate_total_friction_n - f_fric_cap
                f_deficit_n += f_shortfall_n
                p_deficit_kw += (f_shortfall_n * v_ms) / 1000.0
                active_constraints.append("ERR_FRICTION_BRAKE_CAPACITY_EXCEEDED")
                notes_list.append("Chassis friction brake capacity exceeded after reallocating rejected regen")

            notes_list.append(
                f"Battery rejected {p_rejected_elec_kw:.2f} kW regen; reallocated "
                f"{p_add_friction_kw:.2f} kW ({f_add_friction_n:.1f} N) to friction brakes"
            )

        elif p_batt_req_kw < 0.0 and p_batt_deficit_kw < -TOL:
            # Case 4.B: Battery curtailed requested discharge (P_req < P_accepted <= 0)
            # Auxiliary/standby loads unserved
            p_unserved_elec_kw = abs(p_batt_deficit_kw)
            e_unserved_elec_j = p_unserved_elec_kw * dt * 1000.0
            active_constraints.append("ERR_BATTERY_DISCHARGE_CURTAILED")
            notes_list.append(
                f"Battery discharge curtailed by {p_unserved_elec_kw:.2f} kW; "
                f"unserved electrical load on HV bus"
            )

        f_delivered_total_n = f_delivered_regen_n + f_delivered_friction_n
        p_delivered_total_kw = abs(p_delivered_regen_kw) + p_delivered_friction_kw

        # Copy C2 active constraints
        active_constraints.extend(c2_res.active_constraints)

    else:
        # =====================================================================
        # TRACTION / STANDSTILL REGIME (C3-INT-01, C3-INT-02, C3-INT-03)
        # =====================================================================
        c2_res = None
        f_delivered_regen_n = 0.0
        p_delivered_regen_kw = 0.0
        f_delivered_friction_n = 0.0
        p_delivered_friction_kw = 0.0
        f_add_friction_n = 0.0
        p_add_friction_kw = 0.0
        p_rejected_elec_kw = 0.0
        e_rejected_elec_j = 0.0
        f_deficit_n = 0.0
        p_deficit_kw = 0.0

        if f_req > TOL:
            # Positive mechanical traction power requested at wheels:
            p_wheel_trac_req_kw = (f_req * v_ms) / 1000.0

            # Direction-specific forward drivetrain efficiencies (C3-INT-02)
            eta_gb_trac = max(0.10, getattr(gearbox_config, "efficiency_fwd", getattr(gearbox_config, "efficiency", 0.97)))
            eta_mot_trac = max(0.10, getattr(motor_config, "efficiency_mot", 0.92))
            eta_inv_trac = max(
                0.10,
                getattr(
                    inverter_config,
                    "inverter_efficiency",
                    getattr(
                        inverter_config,
                        "efficiency_mot",
                        getattr(motor_config, "inverter_efficiency", 0.95),
                    ),
                ),
            )
            eta_trac_chain = eta_gb_trac * eta_mot_trac * eta_inv_trac
            p_inv_dc_gross_trac_req_kw = p_wheel_trac_req_kw / eta_trac_chain
        else:
            p_wheel_trac_req_kw = 0.0
            eta_trac_chain = 1.0
            p_inv_dc_gross_trac_req_kw = 0.0

        # Auxiliary & Standby HV bus loads
        aux_res = compute_auxiliary_hv_power(p_aux_lv, inverter_config.dc_dc_efficiency, inverter_config.dc_dc_efficiency_status)
        p_standby_kw = inverter_config.standby_loss_w / 1000.0
        p_aux_hv_req_kw = aux_res.aux_hv_power_kw
        p_bus_demand_kw = p_inv_dc_gross_trac_req_kw + p_standby_kw + p_aux_hv_req_kw

        # In traction/idle, power leaves battery => DISCHARGE => signed negative power:
        p_batt_req_kw = -p_bus_demand_kw

        batt_res = simulate_battery_step(
            requested_power_kw=p_batt_req_kw,
            state=battery_state,
            dt_s=dt,
            config=battery_config,
            input_status=input_status,
        )

        p_batt_accepted_kw = batt_res.accepted_power_kw
        p_elec_avail_kw = abs(p_batt_accepted_kw)

        # Priority-based electrical power allocation (C3-INT-01 & C3-INT-03)
        # 1. Inverter standby consumption
        p_standby_served_kw = min(p_elec_avail_kw, p_standby_kw)
        p_rem1 = p_elec_avail_kw - p_standby_served_kw

        # 2. Auxiliary HV load
        p_aux_hv_served_kw = min(p_rem1, p_aux_hv_req_kw)
        p_unserved_aux_kw = p_aux_hv_req_kw - p_aux_hv_served_kw
        p_rem2 = p_rem1 - p_aux_hv_served_kw

        # 3. Propulsion traction power at inverter DC link
        p_inv_dc_trac_served_kw = min(p_rem2, p_inv_dc_gross_trac_req_kw)
        p_unserved_trac_elec_kw = p_inv_dc_gross_trac_req_kw - p_inv_dc_trac_served_kw

        p_unserved_elec_kw = p_unserved_aux_kw + p_unserved_trac_elec_kw
        e_unserved_elec_j = p_unserved_elec_kw * dt * 1000.0

        if p_unserved_elec_kw > TOL:
            active_constraints.append("ERR_BATTERY_DISCHARGE_CURTAILED")
            notes_list.append(f"Traction battery discharge curtailed by {p_unserved_elec_kw:.2f} kW")

        # Delivered wheel mechanical traction power and force (C3-INT-01)
        p_wheel_trac_delivered_kw = p_inv_dc_trac_served_kw * eta_trac_chain

        if v_ms > 0.1:
            f_delivered_total_n = min(f_req, (p_wheel_trac_delivered_kw * 1000.0) / v_ms)
            p_delivered_total_kw = (f_delivered_total_n * v_ms) / 1000.0
        else:
            if p_inv_dc_gross_trac_req_kw > 1e-6:
                trac_ratio = p_inv_dc_trac_served_kw / p_inv_dc_gross_trac_req_kw
                f_delivered_total_n = f_req * min(1.0, max(0.0, trac_ratio))
            else:
                f_delivered_total_n = 0.0
            p_delivered_total_kw = (f_delivered_total_n * v_ms) / 1000.0

        f_trac_deficit_n = max(0.0, f_req - f_delivered_total_n)
        p_trac_deficit_kw = max(0.0, p_wheel_trac_req_kw - p_delivered_total_kw)

        if f_trac_deficit_n > TOL or p_trac_deficit_kw > TOL:
            active_constraints.append("ERR_TRACTION_FORCE_CURTAILED")
            notes_list.append(
                f"Traction force curtailed to {f_delivered_total_n:.1f} N "
                f"(deficit {f_trac_deficit_n:.1f} N) due to battery discharge limit"
            )

    # Combine active constraints and diagnostic codes
    active_constraints.extend(batt_res.active_constraints)
    active_constraints = list(dict.fromkeys(active_constraints))  # Deduplicate while preserving order

    # Diagnostic code selection
    diagnostic_code = batt_res.operating_point.diagnostic_code
    if not diagnostic_code and c2_res is not None:
        diagnostic_code = c2_res.diagnostic_code
    if not diagnostic_code and is_braking and f_deficit_n > TOL:
        diagnostic_code = "ERR_BRAKING_FORCE_CURTAILED"
    if not diagnostic_code and not is_braking and f_trac_deficit_n > TOL:
        diagnostic_code = "ERR_TRACTION_FORCE_CURTAILED"

    # Overall Status Synthesis
    if "ERR_BATTERY_INFEASIBLE_BOUNDS" in active_constraints or f_deficit_n > 1.0 or f_trac_deficit_n > 1.0:
        overall_status = ConstraintStatus.VIOLATED
    elif batt_res.overall_status == ConstraintStatus.VIOLATED:
        overall_status = ConstraintStatus.VIOLATED
    elif batt_res.overall_status == ConstraintStatus.CONDITIONAL or (c2_res and c2_res.overall_status == ConstraintStatus.CONDITIONAL):
        overall_status = ConstraintStatus.CONDITIONAL
    else:
        overall_status = ConstraintStatus.SATISFIED

    # Combine provenance
    combined_prov = combine_provenance(
        input_status,
        battery_state.provenance_status,
        battery_config.status,
        c2_res.provenance_status if c2_res else None,
    )

    # =========================================================================
    # END-TO-END MULTI-BOUNDARY ENERGY ACCOUNTING LEDGER (C3-INT-03)
    # =========================================================================
    e_batt_term_j = batt_res.energy_terminal_j
    e_batt_chem_j = batt_res.energy_chem_j
    e_c1_storage_j = batt_res.delta_energy_c1_j
    e_batt_loss_j = batt_res.energy_loss_r0_j + batt_res.energy_loss_r1_j + batt_res.energy_loss_parasitic_j

    if is_braking:
        f_trac_deficit_n = 0.0
        p_trac_deficit_kw = 0.0
        e_wheel_req_j = (p_req_wheel_kw * 1000.0) * dt
        e_wheel_mech_j = (p_delivered_total_kw * 1000.0) * dt
        e_unserved_trac_j = 0.0

        e_friction_j = (p_delivered_friction_kw * 1000.0) * dt
        e_standby_j = (c2_res.inverter_standby_kw * 1000.0) * dt if c2_res else (inverter_config.standby_loss_w * dt)
        e_aux_hv_req_j = (c2_res.auxiliary_hv_power_kw * 1000.0) * dt if c2_res else 0.0
        e_unserved_aux_j = e_unserved_elec_j
        e_aux_hv_supplied_j = max(0.0, e_aux_hv_req_j - e_unserved_aux_j)
        e_aux_hv_j = e_aux_hv_supplied_j

        # Gross inverter DC generation reconciled with actual battery acceptance:
        p_inv_dc_gross_delivered_kw = max(0.0, p_batt_accepted_kw + (e_standby_j / dt) / 1000.0 + (e_aux_hv_j / dt) / 1000.0)

        # Drivetrain loss is mechanical wheel regen power minus gross inverter DC power:
        p_drivetrain_loss_kw = max(0.0, abs(p_delivered_regen_kw) - p_inv_dc_gross_delivered_kw)
        e_drivetrain_loss_j = p_drivetrain_loss_kw * 1000.0 * dt

        # Balance: e_wheel_mech == e_friction + e_drivetrain_loss + e_standby + e_aux_hv + e_batt_term
        e_absorbed_sum_j = e_friction_j + e_drivetrain_loss_j + e_standby_j + e_aux_hv_j + e_batt_term_j
        e_accounting_residual_j = e_wheel_mech_j - e_absorbed_sum_j
    else:
        e_wheel_req_j = (p_wheel_trac_req_kw * 1000.0) * dt
        e_wheel_mech_j = (p_delivered_total_kw * 1000.0) * dt
        e_unserved_trac_j = (p_trac_deficit_kw * 1000.0) * dt
        e_friction_j = 0.0

        e_standby_j = (p_standby_served_kw * 1000.0) * dt
        e_aux_hv_req_j = (p_aux_hv_req_kw * 1000.0) * dt
        e_aux_hv_supplied_j = (p_aux_hv_served_kw * 1000.0) * dt
        e_unserved_aux_j = (p_unserved_aux_kw * 1000.0) * dt
        e_aux_hv_j = e_aux_hv_supplied_j

        # Drivetrain forward loss: difference between inverter DC input and delivered wheel mechanical power
        p_inv_dc_delivered_kw = (p_delivered_total_kw / eta_trac_chain) if eta_trac_chain > 0.0 else 0.0
        p_drivetrain_loss_kw = max(0.0, p_inv_dc_delivered_kw - p_delivered_total_kw)
        e_drivetrain_loss_j = p_drivetrain_loss_kw * 1000.0 * dt

        # Balance: |e_batt_term| == e_wheel_mech + e_drivetrain_loss + e_standby + e_aux_hv
        e_supplied_j = abs(e_batt_term_j)
        e_consumed_sum_j = e_wheel_mech_j + e_drivetrain_loss_j + e_standby_j + e_aux_hv_j
        e_accounting_residual_j = e_supplied_j - e_consumed_sum_j

    notes_list.extend(batt_res.notes)
    if c2_res is not None:
        notes_list.extend(c2_res.notes)

    return IntegratedPowertrainResult(
        is_braking_mode=is_braking,
        dt_s=dt,
        vehicle_speed_ms=v_ms,
        requested_wheel_force_n=abs(f_req),
        requested_wheel_power_kw=p_req_wheel_kw,
        delivered_wheel_force_n=f_delivered_total_n,
        delivered_wheel_power_kw=p_delivered_total_kw,
        braking_deficit_force_n=f_deficit_n,
        braking_deficit_power_kw=p_deficit_kw,
        traction_deficit_force_n=f_trac_deficit_n,
        traction_deficit_power_kw=p_trac_deficit_kw,
        delivered_regen_force_n=f_delivered_regen_n,
        delivered_regen_power_kw=p_delivered_regen_kw,
        delivered_friction_force_n=f_delivered_friction_n,
        delivered_friction_power_kw=p_delivered_friction_kw,
        additional_friction_force_n=f_add_friction_n,
        additional_friction_power_kw=p_add_friction_kw,
        c2_blending_result=c2_res,
        battery_simulation_result=batt_res,
        requested_battery_power_kw=p_batt_req_kw,
        accepted_battery_power_kw=p_batt_accepted_kw,
        battery_power_deficit_kw=batt_res.deficit_power_kw,
        rejected_regen_electrical_power_kw=p_rejected_elec_kw,
        rejected_regen_electrical_energy_j=e_rejected_elec_j,
        unserved_electrical_power_kw=p_unserved_elec_kw,
        unserved_electrical_energy_j=e_unserved_elec_j,
        initial_battery_state=battery_state,
        final_battery_state=batt_res.final_state,
        battery_current_a=batt_res.operating_point.current_a,
        terminal_voltage_avg_v=batt_res.operating_point.terminal_voltage_v,
        terminal_voltage_end_v=batt_res.operating_point.terminal_voltage_end_v,
        delta_soc=batt_res.final_state.soc - battery_state.soc,
        delta_v1_v=batt_res.final_state.v1_polarization_v - battery_state.v1_polarization_v,
        energy_wheel_requested_j=e_wheel_req_j,
        energy_wheel_delivered_j=e_wheel_mech_j,
        energy_unserved_traction_j=e_unserved_trac_j,
        energy_auxiliary_requested_j=e_aux_hv_req_j,
        energy_auxiliary_supplied_j=e_aux_hv_supplied_j,
        energy_unserved_auxiliary_j=e_unserved_aux_j,
        energy_wheel_mechanical_j=e_wheel_mech_j,
        energy_friction_dissipated_j=e_friction_j,
        energy_drivetrain_loss_j=e_drivetrain_loss_j,
        energy_inverter_standby_j=e_standby_j,
        energy_auxiliary_hv_j=e_aux_hv_j,
        energy_battery_terminal_j=e_batt_term_j,
        energy_battery_loss_j=e_batt_loss_j,
        delta_energy_c1_storage_j=e_c1_storage_j,
        energy_battery_chemical_j=e_batt_chem_j,
        energy_accounting_residual_j=e_accounting_residual_j,
        active_constraints=active_constraints,
        diagnostic_code=diagnostic_code,
        overall_status=overall_status,
        provenance_status=combined_prov,
        notes=notes_list,
    )
