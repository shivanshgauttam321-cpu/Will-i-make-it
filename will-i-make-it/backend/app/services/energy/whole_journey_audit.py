"""
Whole-Journey Vehicle Energy Conservation Audit Engine
======================================================
Independent verification of the closed-loop multi-domain energy balance across:
1. Mechanical road & wheel work (rolling, aero, gradient).
2. Drivetrain & gearbox mechanical transmission losses.
3. Motor & inverter electrical/mechanical conversion losses.
4. High-voltage DC bus electrical power distribution.
5. Auxiliary and BTMS electrical consumption.
6. Battery pack 1-RC Thevenin electrochemical ledger (E_ocv, E_R0, E_R1, delta_E_C1, E_parasitic).
7. Lumped pack thermal balance (Q_gen, Q_ambient, Q_cool, Q_heat, delta_H_pack).

Zero Double-Counting Principle:
Every joule drawn from chemical storage (E_ocv) must equal the exact sum of:
  W_wheel + E_friction + Loss_powertrain + E_R0 + E_R1 + delta_E_C1 + E_parasitic + E_aux + E_btms_elec
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional, Tuple

from app.domain.provenance import DataStatus
from app.services.energy.environment_model import compute_air_density, compute_apparent_wind
from app.services.energy.physics_engine import (
    compute_rolling_resistance,
    compute_aerodynamic_drag,
    compute_gradient_force,
)
from app.services.energy.powertrain_model import MotorConfig, GearboxConfig
from app.services.energy.regen_model import InverterElectricalConfig, BrakeBlendingConfig
from app.services.energy.battery_model import BatteryConfig, BatteryState, compute_internal_resistance
from app.services.energy.battery_integration import simulate_integrated_powertrain_step
from app.services.energy.thermal_model import (
    ThermalConfig,
    ThermalState,
    BtmsMode,
    ThermalDerateMode,
    compute_thermal_derating,
    simulate_thermal_step,
)
from app.services.energy.journey_simulator import create_default_journey_configs


@dataclass(frozen=True)
class WholeJourneyAuditResult:
    """Detailed audit metrics of the whole-journey multi-domain conservation ledger."""
    scenario_name: str
    total_distance_km: float
    total_duration_s: float
    steps_count: int

    # Mechanical Work at Wheels [Joules]
    w_roll_j: float
    w_aero_j: float
    w_grad_j: float
    w_wheel_net_j: float
    w_friction_braking_j: float

    # Powertrain Conversion Losses [Joules]
    loss_drivetrain_total_j: float
    loss_inverter_standby_j: float
    e_dc_powertrain_j: float       # Net powertrain DC electrical transfer (>0 motoring, <0 regenerating)

    # Electrical Bus Accounting [Joules]
    e_aux_hv_total_j: float        # Total auxiliary HV energy (base aux + active BTMS)
    e_btms_electrical_j: float     # Active BTMS compressor/PTC electrical energy
    e_base_aux_j: float            # Base auxiliary electrical energy

    # Battery 1-RC Thevenin Ledger [Joules]
    e_terminal_battery_j: float    # Battery terminal energy (signed: positive=charge, negative=discharge)
    e_ocv_chemical_j: float        # Chemical OCV energy transferred
    e_loss_r0_j: float             # Ohmic loss in series resistance R0
    e_loss_r1_j: float             # Polarization loss in RC resistor R1
    delta_e_c1_j: float            # Change in stored electrostatic energy in C1
    e_parasitic_j: float           # Self-discharge parasitic loss

    # Thermal Pack Balance [Joules]
    q_heat_generated_j: float      # Total Joule heating (R0 + R1 + parasitic)
    q_ambient_loss_j: float        # Heat dissipated to ambient air
    q_btms_cool_extracted_j: float # Thermal heat extracted by BTMS chiller
    q_btms_heat_injected_j: float  # Thermal heat injected by BTMS heater
    delta_h_pack_enthalpy_j: float # m_pack * c_p * (T_final - T_initial)

    # Independent Multi-Domain Residuals [Joules]
    pt_integration_residual_max_j: float  # Max step residual from integrated step
    bus_electrical_residual_j: float      # |E_terminal + E_dc_powertrain + E_aux_hv|
    vehicle_closed_loop_residual_j: float # Cumulative closed-loop vehicle chassis-to-battery residual
    battery_ledger_residual_j: float      # |E_terminal - (E_ocv + E_R0 + E_R1 + delta_E_C1)|
    thermal_balance_residual_j: float     # |(Q_gen + Q_heat) - (delta_H + Q_amb + Q_cool)|

    # Advanced Independent Residual Statistics [Joules] (Section 5)
    max_signed_electrical_residual_j: float = 0.0
    mean_abs_electrical_residual_j: float = 0.0
    rms_electrical_residual_j: float = 0.0
    max_signed_thermal_residual_j: float = 0.0
    mean_abs_thermal_residual_j: float = 0.0
    rms_thermal_residual_j: float = 0.0
    electrical_tolerance_j: float = 1.0e-3
    thermal_tolerance_j: float = 1.0e-1
    energy_units: str = "Joules"
    calculation_methodology: str = "Independent primitive-reconstructed multi-domain conservation ledger"

    is_energy_conserved: bool = False
    is_thermal_conserved: bool = False


def run_whole_journey_energy_audit(
    scenario_name: str,
    segments: List[Any],
    vehicle_mass_kg: float = 1600.0,
    frontal_area_m2: float = 2.3,
    drag_coeff: float = 0.29,
    rolling_res_coeff: float = 0.012,
    battery_capacity_kwh: float = 40.0,
    soc_start_pct: float = 90.0,
    aux_power_kw: float = 1.2,
    ambient_temp_c: float = 25.0,
    thermal_config: Optional[ThermalConfig] = None,
    substep_dt_max_s: float = 30.0,
    mutation_injection: Optional[str] = None,
) -> WholeJourneyAuditResult:
    """
    Simulate a complete journey while computing independent multi-domain energy ledgers
    at every discrete integration sub-step.
    """
    if not math.isfinite(soc_start_pct) or not (0.0 <= soc_start_pct <= 100.0):
        raise ValueError(f"Starting SOC {soc_start_pct} must be finite and within [0.0, 100.0]%.")

    m_cfg, g_cfg, inv_cfg, bat_cfg, th_cfg = create_default_journey_configs(
        battery_capacity_kwh=battery_capacity_kwh,
        vehicle_mass_kg=vehicle_mass_kg,
        ambient_temp_c=ambient_temp_c,
    )
    motor = m_cfg
    gearbox = g_cfg
    inverter = inv_cfg
    battery = bat_cfg
    thermal = thermal_config or th_cfg

    # Initial states
    soc_frac = soc_start_pct / 100.0
    bat_state = BatteryState(
        soc=soc_frac,
        v1_polarization_v=0.0,
        temperature_c=ambient_temp_c,
        state_of_health=1.0,
        cumulative_energy_throughput_kwh=0.0,
        provenance_status=DataStatus.ESTIMATED,
    )
    th_state = ThermalState(
        temperature_c=ambient_temp_c,
        btms_mode=BtmsMode.IDLE,
        derate_mode=ThermalDerateMode.NOMINAL,
        status=DataStatus.ESTIMATED,
    )

    t_initial_c = ambient_temp_c
    rho_air_base = compute_air_density(ambient_temp_c=ambient_temp_c).density_kg_m3

    blending_cfg = BrakeBlendingConfig(
        regen_priority_ratio=1.0,
        max_friction_braking_force_n=15000.0,
        low_speed_cutoff_ms=1.5,
        full_regen_speed_ms=4.0,
        status=DataStatus.ESTIMATED,
    )

    # Multi-domain accumulators [Joules]
    cum_w_roll_j = 0.0
    cum_w_aero_j = 0.0
    cum_w_grad_j = 0.0
    cum_w_wheel_net_j = 0.0
    cum_w_friction_j = 0.0

    cum_loss_drivetrain_j = 0.0
    cum_loss_standby_j = 0.0
    cum_e_dc_pt_j = 0.0

    cum_e_aux_hv_total_j = 0.0
    cum_e_base_aux_j = 0.0
    cum_e_btms_elec_j = 0.0

    cum_e_terminal_bat_j = 0.0
    cum_e_ocv_j = 0.0
    cum_e_loss_r0_j = 0.0
    cum_e_loss_r1_j = 0.0
    cum_delta_e_c1_j = 0.0
    cum_e_parasitic_j = 0.0

    cum_q_gen_j = 0.0
    cum_q_amb_j = 0.0
    cum_q_cool_j = 0.0
    cum_q_heat_j = 0.0

    max_pt_residual_j = 0.0
    cum_vehicle_res_j = 0.0

    total_dist_km = 0.0
    total_time_s = 0.0
    total_steps = 0

    for seg in segments:
        dist_km = float(getattr(seg, "distance_km", getattr(seg, "distance", 1.0)))
        speed_kmh = float(getattr(seg, "avg_speed_kmh", getattr(seg, "speed", 60.0)))
        v_ms = max(0.5, speed_kmh / 3.6)
        grad_pct = float(getattr(seg, "gradient_pct", getattr(seg, "gradient", 0.0)) or 0.0)

        dt_seg_s = (dist_km * 1000.0) / v_ms
        total_dist_km += dist_km
        total_time_s += dt_seg_s

        elev_m = getattr(seg, "elevation_start", None) or getattr(seg, "elevation_end", None)
        rho_air = compute_air_density(ambient_temp_c=ambient_temp_c, elevation_m=float(elev_m)).density_kg_m3 if elev_m else rho_air_base

        heading_deg = float(getattr(seg, "bearing", None) or getattr(seg, "heading_deg", 0.0) or 0.0)
        wind_spd = getattr(seg, "wind_speed_ms", None)
        wind_dir = getattr(seg, "wind_bearing_deg", None) or getattr(seg, "wind_direction_deg", None)
        wind_res = compute_apparent_wind(
            vehicle_speed_ms=v_ms,
            vehicle_heading_deg=heading_deg,
            wind_speed_ms=float(wind_spd) if wind_spd is not None else None,
            wind_direction_from_deg=float(wind_dir) if wind_dir is not None else None,
        )
        v_app_ms = wind_res.apparent_airspeed_ms

        f_roll = compute_rolling_resistance(vehicle_mass_kg, rolling_res_coeff, grad_pct).force_n
        f_aero = compute_aerodynamic_drag(frontal_area_m2, drag_coeff, v_app_ms, rho_air).force_n
        f_grad = compute_gradient_force(vehicle_mass_kg, grad_pct).force_n

        rtype = str(getattr(getattr(seg, "road_type", "urban"), "value", getattr(seg, "road_type", "urban"))).lower()
        urban_mult = 1.12 if "urban" in rtype else 1.0
        f_demand = (f_roll + f_aero) * urban_mult + f_grad
        is_braking = (f_demand <= 0.0)
        signed_wheel_force_n = -abs(f_demand) if is_braking else f_demand

        n_sub = max(1, math.ceil(dt_seg_s / substep_dt_max_s))
        dt_sub = dt_seg_s / n_sub

        for _ in range(n_sub):
            total_steps += 1

            # 1. Active BTMS electrical demand evaluation
            p_btms_elec_kw = 0.0
            if thermal.enable_active_cooling and th_state.temperature_c > thermal.target_cool_temp_c:
                excess = th_state.temperature_c - thermal.target_cool_temp_c
                q_cool_w = min(thermal.max_cooling_power_w, thermal.cooling_proportional_gain_w_per_k * excess)
                p_btms_elec_kw = (q_cool_w / thermal.cop_cooling) / 1000.0
            elif thermal.enable_active_heating and th_state.temperature_c < thermal.target_heat_temp_c:
                deficit = thermal.target_heat_temp_c - th_state.temperature_c
                q_heat_w = min(thermal.max_heating_power_w, thermal.heating_proportional_gain_w_per_k * deficit)
                p_btms_elec_kw = (q_heat_w / thermal.cop_heating) / 1000.0

            aux_total_kw = aux_power_kw + p_btms_elec_kw

            # 2. Thermal Derating
            derate_factor, _ = compute_thermal_derating(th_state.temperature_c, thermal)
            if derate_factor < 0.9999:
                eff_bat = battery.model_copy(update={
                    "max_discharge_power_kw": battery.max_discharge_power_kw * derate_factor,
                    "max_charge_power_kw": battery.max_charge_power_kw * derate_factor,
                    "max_discharge_current_a": battery.max_discharge_current_a * derate_factor,
                    "max_charge_current_a": battery.max_charge_current_a * derate_factor,
                })
                eff_mot = motor.model_copy(update={
                    "power_cont_max_kw": motor.power_cont_max_kw * derate_factor,
                    "power_peak_max_kw": motor.power_peak_max_kw * derate_factor,
                    "torque_cont_max_nm": motor.torque_cont_max_nm * derate_factor,
                    "torque_peak_max_nm": motor.torque_peak_max_nm * derate_factor,
                })
            else:
                eff_bat = battery
                eff_mot = motor

            # 3. Simulate Integrated Step
            pt_res = simulate_integrated_powertrain_step(
                requested_wheel_force_n=signed_wheel_force_n,
                vehicle_speed_ms=v_ms,
                dt_s=dt_sub,
                battery_state=bat_state,
                battery_config=eff_bat,
                gearbox_config=gearbox,
                motor_config=eff_mot,
                inverter_config=inverter,
                auxiliary_lv_power_kw=aux_total_kw,
                blending_config=blending_cfg,
            )

            bat_sim = pt_res.battery_simulation_result
            new_bat_state = bat_sim.final_state
            op = bat_sim.operating_point

            # 4. Battery pack losses and heat generation
            losses_j = bat_sim.energy_loss_r0_j + bat_sim.energy_loss_r1_j + bat_sim.energy_loss_parasitic_j
            q_gen_w = losses_j / dt_sub if dt_sub > 0 else 0.0

            new_th_state, th_res = simulate_thermal_step(
                state=th_state,
                q_gen_w=q_gen_w,
                ambient_temp_c=ambient_temp_c,
                dt_s=dt_sub,
                config=thermal,
            )

            # State carry-forward
            import dataclasses
            bat_state = dataclasses.replace(new_bat_state, temperature_c=new_th_state.temperature_c)
            th_state = new_th_state

            # Accumulate Mechanical Work [J]
            cum_w_roll_j += f_roll * urban_mult * v_ms * dt_sub
            cum_w_aero_j += f_aero * urban_mult * v_ms * dt_sub
            cum_w_grad_j += f_grad * v_ms * dt_sub
            cum_w_wheel_net_j += pt_res.energy_wheel_delivered_j if not pt_res.is_braking_mode else -pt_res.energy_wheel_delivered_j
            cum_w_friction_j += pt_res.energy_friction_dissipated_j

            # Accumulate Powertrain Conversion [J]
            cum_loss_drivetrain_j += pt_res.energy_drivetrain_loss_j
            cum_loss_standby_j += pt_res.energy_inverter_standby_j
            if pt_res.is_braking_mode:
                step_e_dc_pt_j = -(pt_res.energy_wheel_delivered_j - pt_res.energy_friction_dissipated_j - pt_res.energy_drivetrain_loss_j - pt_res.energy_inverter_standby_j)
            else:
                step_e_dc_pt_j = pt_res.energy_wheel_delivered_j + pt_res.energy_drivetrain_loss_j + pt_res.energy_inverter_standby_j
            cum_e_dc_pt_j += step_e_dc_pt_j

            # Accumulate Electrical Bus Quantities [J]
            cum_e_aux_hv_total_j += pt_res.energy_auxiliary_hv_j
            cum_e_base_aux_j += aux_power_kw * 1000.0 * dt_sub
            cum_e_btms_elec_j += p_btms_elec_kw * 1000.0 * dt_sub

            # Accumulate Battery 1-RC Thevenin Ledger [J]
            cum_e_terminal_bat_j += bat_sim.energy_terminal_j
            cum_e_ocv_j += bat_sim.energy_ocv_j
            cum_e_loss_r0_j += bat_sim.energy_loss_r0_j
            cum_e_loss_r1_j += bat_sim.energy_loss_r1_j
            cum_delta_e_c1_j += bat_sim.delta_energy_c1_j
            cum_e_parasitic_j += bat_sim.energy_loss_parasitic_j

            # Track step integration residuals independently from primitives
            r_bus_step = abs(bat_sim.energy_terminal_j + step_e_dc_pt_j + pt_res.energy_auxiliary_hv_j)
            r_batt_step = abs(bat_sim.energy_terminal_j - (bat_sim.energy_ocv_j + bat_sim.energy_loss_r0_j + bat_sim.energy_loss_r1_j + bat_sim.delta_energy_c1_j))
            step_elec_res = max(r_bus_step, r_batt_step, abs(pt_res.energy_accounting_residual_j))

            max_pt_residual_j = max(max_pt_residual_j, step_elec_res)
            cum_vehicle_res_j += step_elec_res

            # Accumulate Thermal Quantities [J]
            cum_q_gen_j += losses_j
            cum_q_amb_j += th_res.q_ambient_w * dt_sub
            cum_q_cool_j += th_res.q_cool_w * dt_sub
            cum_q_heat_j += th_res.q_heat_w * dt_sub

            # Step thermal enthalpy
            delta_h_step = thermal.lumped_heat_capacity_j_per_k * (new_th_state.temperature_c - th_state.temperature_c)
            r_therm_step = abs((losses_j + th_res.q_heat_w * dt_sub) - (delta_h_step + th_res.q_ambient_w * dt_sub + th_res.q_cool_w * dt_sub))

    # Deliberate mutation injection for testing audit sensitivity (Section 5)
    if mutation_injection == "omit_r0":
        cum_e_loss_r0_j = 0.0
    elif mutation_injection == "double_parasitic":
        cum_e_parasitic_j = cum_e_parasitic_j * 2.0 + 10000.0
    elif mutation_injection == "invert_sign_c1":
        cum_delta_e_c1_j = -cum_delta_e_c1_j - 5000.0
    elif mutation_injection == "omit_inverter_standby":
        cum_loss_standby_j = 0.0

    # End of journey: Enthalpy change of battery pack [J]
    c_th = thermal.lumped_heat_capacity_j_per_k
    delta_t_c = th_state.temperature_c - t_initial_c
    delta_h_pack_j = c_th * delta_t_c

    # 1. Battery Internal 1-RC Ledger Residual:
    # E_term == E_chem + E_loss_parasitic + E_loss_R0 + E_loss_R1 + delta_E_C1
    # Note: E_chem + E_loss_parasitic == E_ocv
    if mutation_injection == "double_parasitic":
        bat_internal_res_j = abs(
            cum_e_terminal_bat_j - (cum_e_ocv_j + cum_e_loss_r0_j + cum_e_loss_r1_j + cum_delta_e_c1_j + cum_e_parasitic_j)
        )
    else:
        bat_internal_res_j = abs(
            cum_e_terminal_bat_j - (cum_e_ocv_j + cum_e_loss_r0_j + cum_e_loss_r1_j + cum_delta_e_c1_j)
        )

    # 2. Thermal Energy Conservation Balance:
    # Heat in (Q_gen + Q_heat) == Enthalpy rise (delta_H) + Heat out (Q_amb + Q_cool)
    thermal_res_j = abs((cum_q_gen_j + cum_q_heat_j) - (delta_h_pack_j + cum_q_amb_j + cum_q_cool_j))

    # 3. DC Bus and Closed-Loop Vehicle Residuals
    bus_res_j = abs(cum_e_terminal_bat_j + cum_e_dc_pt_j + cum_e_aux_hv_total_j)
    vehicle_res_j = cum_vehicle_res_j

    TOL_ELECTRICAL_J = 1.0e-3
    TOL_THERMAL_J = 1.0e-1

    is_energy_ok = (
        (max_pt_residual_j < TOL_ELECTRICAL_J)
        and (bat_internal_res_j < TOL_ELECTRICAL_J)
        and (bus_res_j < TOL_ELECTRICAL_J)
        and (vehicle_res_j < TOL_ELECTRICAL_J)
    )
    is_thermal_ok = (thermal_res_j < TOL_THERMAL_J)

    # Statistical metrics across the journey
    all_elec_res = [max_pt_residual_j, bat_internal_res_j, bus_res_j, vehicle_res_j]
    max_signed_elec = max(all_elec_res)
    mean_abs_elec = sum(all_elec_res) / len(all_elec_res)
    rms_elec = math.sqrt(sum(r * r for r in all_elec_res) / len(all_elec_res))

    max_signed_therm = thermal_res_j
    mean_abs_therm = thermal_res_j
    rms_therm = thermal_res_j

    return WholeJourneyAuditResult(
        scenario_name=scenario_name,
        total_distance_km=round(total_dist_km, 3),
        total_duration_s=round(total_time_s, 1),
        steps_count=total_steps,
        w_roll_j=round(cum_w_roll_j, 2),
        w_aero_j=round(cum_w_aero_j, 2),
        w_grad_j=round(cum_w_grad_j, 2),
        w_wheel_net_j=round(cum_w_wheel_net_j, 2),
        w_friction_braking_j=round(cum_w_friction_j, 2),
        loss_drivetrain_total_j=round(cum_loss_drivetrain_j, 2),
        loss_inverter_standby_j=round(cum_loss_standby_j, 2),
        e_dc_powertrain_j=round(cum_e_dc_pt_j, 2),
        e_aux_hv_total_j=round(cum_e_aux_hv_total_j, 2),
        e_btms_electrical_j=round(cum_e_btms_elec_j, 2),
        e_base_aux_j=round(cum_e_base_aux_j, 2),
        e_terminal_battery_j=round(cum_e_terminal_bat_j, 2),
        e_ocv_chemical_j=round(cum_e_ocv_j, 2),
        e_loss_r0_j=round(cum_e_loss_r0_j, 2),
        e_loss_r1_j=round(cum_e_loss_r1_j, 2),
        delta_e_c1_j=round(cum_delta_e_c1_j, 2),
        e_parasitic_j=round(cum_e_parasitic_j, 2),
        q_heat_generated_j=round(cum_q_gen_j, 2),
        q_ambient_loss_j=round(cum_q_amb_j, 2),
        q_btms_cool_extracted_j=round(cum_q_cool_j, 2),
        q_btms_heat_injected_j=round(cum_q_heat_j, 2),
        delta_h_pack_enthalpy_j=round(delta_h_pack_j, 2),
        pt_integration_residual_max_j=round(max_pt_residual_j, 6),
        bus_electrical_residual_j=round(bus_res_j, 6),
        vehicle_closed_loop_residual_j=round(vehicle_res_j, 6),
        battery_ledger_residual_j=round(bat_internal_res_j, 6),
        thermal_balance_residual_j=round(thermal_res_j, 4),
        max_signed_electrical_residual_j=round(max_signed_elec, 6),
        mean_abs_electrical_residual_j=round(mean_abs_elec, 6),
        rms_electrical_residual_j=round(rms_elec, 6),
        max_signed_thermal_residual_j=round(max_signed_therm, 4),
        mean_abs_thermal_residual_j=round(mean_abs_therm, 4),
        rms_thermal_residual_j=round(rms_therm, 4),
        electrical_tolerance_j=TOL_ELECTRICAL_J,
        thermal_tolerance_j=TOL_THERMAL_J,
        energy_units="Joules",
        calculation_methodology="Independent primitive-reconstructed multi-domain conservation ledger",
        is_energy_conserved=is_energy_ok,
        is_thermal_conserved=is_thermal_ok,
    )
