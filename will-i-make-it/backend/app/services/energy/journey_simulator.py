"""
Journey Simulation Engine (Full EV Powertrain & Battery Dynamic Integration)
===========================================================================
End-to-end multi-segment journey simulation reconciling:
1. Stage C1.3 mechanical motor & drivetrain physics.
2. Stage C2.1 regenerative braking & inverter electrical acceptance.
3. Stage C3 dynamic 1-RC Thevenin battery pack equivalent circuit.
4. Stage C4 lumped-parameter pack thermal dynamics & active BTMS.

Feasibility Decision Logic:
- WILL_MAKE_IT: Final P90 SOC >= reserve_pct, no battery depletion, no critical thermal limit.
- LOW_RESERVE: Final P50 SOC >= reserve_pct, but P90 < reserve_pct (uncertainty boundary breach).
- UNCERTAIN: Missing crucial topographical provenance (UNKNOWN elevation) or extreme variance.
- WILL_NOT_MAKE_IT: Battery depletes (SOC <= 0% or hit cutoff V_min) on route before destination.
"""
from __future__ import annotations

import dataclasses
import math
from dataclasses import dataclass, field
from enum import Enum
from typing import List, Optional, Tuple, Dict, Any

from app.domain.provenance import DataStatus
from app.services.energy.environment_model import (
    compute_air_density,
    compute_apparent_wind,
)
from app.services.energy.physics_engine import (
    compute_rolling_resistance,
    compute_aerodynamic_drag,
    compute_gradient_force,
)
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
    compute_internal_resistance,
    simulate_battery_step,
)
from app.services.energy.battery_integration import (
    DynamicBMSConfig,
    IntegratedPowertrainResult,
    create_dynamic_bms_config,
    simulate_integrated_powertrain_step,
)
from app.services.energy.thermal_model import (
    ThermalConfig,
    ThermalState,
    BtmsMode,
    ThermalDerateMode,
    ThermalStepResult,
    compute_thermal_derating,
    simulate_thermal_step,
)


def get_normal_quantile(p: float) -> float:
    """
    Acklam's algorithm for inverse standard normal cumulative distribution function (quantile function).
    Provides continuous, high-precision quantile mapping:
    - P50 -> 0.00000
    - P90 -> 1.28155
    - P95 -> 1.64485
    - P99 -> 2.32635
    """
    if p <= 0.0:
        return -float("inf")
    if p >= 1.0:
        return float("inf")
    if p == 0.5:
        return 0.0

    # Coefficients in rational approximations
    a = (
        -3.969683028665376e01,
        2.209460984245205e02,
        -2.759285104469687e02,
        1.383577518672690e02,
        -3.066479806614716e01,
        2.506628277459239e00,
    )
    b = (
        -5.447609879822406e01,
        1.615858368580409e02,
        -1.556989798598866e02,
        6.680131188771972e01,
        -1.328068155288572e01,
    )
    c = (
        -7.784894002430293e-03,
        -3.223964580411365e-01,
        -2.400758277161838e00,
        -2.549732539343734e00,
        4.374664141464968e00,
        2.938163982698783e00,
    )
    d = (
        7.784695709041462e-03,
        3.224671290700398e-01,
        2.445134137142996e00,
        3.754408661907416e00,
    )

    p_low = 0.02425
    p_high = 1.0 - p_low

    if p < p_low:
        q = math.sqrt(-2.0 * math.log(p))
        return (
            ((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5]
        ) / ((((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1.0)
    elif p <= p_high:
        q = p - 0.5
        r = q * q
        return (
            (((((a[0] * r + a[1]) * r + a[2]) * r + a[3]) * r + a[4]) * r + a[5])
            * q
            / (((((b[0] * r + b[1]) * r + b[2]) * r + b[3]) * r + b[4]) * r + 1.0)
        )
    else:
        q = math.sqrt(-2.0 * math.log(1.0 - p))
        return -(
            ((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5]
        ) / ((((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1.0)


class FeasibilityStatus(str, Enum):
    WILL_MAKE_IT = "WILL_MAKE_IT"
    SIMULATED_WITH_DEMO_INFRASTRUCTURE = "SIMULATED_WITH_DEMO_INFRASTRUCTURE"
    CONDITIONAL_INFRASTRUCTURE_REQUIRED = "CONDITIONAL_INFRASTRUCTURE_REQUIRED"
    LOW_RESERVE = "LOW_RESERVE"
    UNCERTAIN = "UNCERTAIN"
    WILL_NOT_MAKE_IT = "WILL_NOT_MAKE_IT"
    SIMULATION_ERROR = "SIMULATION_ERROR"


# Minimum allowable operating SOC [%]. Below 2.0%, the BMS enforces an absolute contactor open cutoff
# to protect cell chemistry from irreversible copper/cathode dissolution and severe undervoltage.
MIN_OPERATING_SOC_PCT: float = 2.0


@dataclass(frozen=True)
class ChargingEventResult:
    """Detailed record of a continuous, physically-constrained charging event."""
    charger_id: str
    charger_name: str
    charger_status: str
    arrive_soc_pct: float
    depart_soc_pct: float
    target_soc_pct: float
    charge_duration_min: float
    energy_added_battery_kwh: float
    energy_from_grid_kwh: float
    peak_charge_power_kw: float
    avg_charge_power_kw: float
    battery_temp_start_c: float
    battery_temp_end_c: float
    btms_cooling_energy_kwh: float
    was_derated: bool
    notes: List[str] = field(default_factory=list)


@dataclass(frozen=True)
class MultiStopJourneySummary:
    """Complete consolidated multi-stop journey simulation output."""
    total_distance_km: float
    total_driving_duration_min: float
    total_charging_duration_min: float
    total_journey_duration_min: float
    initial_soc_pct: float
    final_soc_p50_pct: float
    final_soc_p90_pct: float
    reserve_soc_pct: float
    feasibility_status: FeasibilityStatus
    is_energy_feasible: bool
    all_chargers_reachable: bool
    infrastructure_status: str
    overall_confidence: str
    feasibility_margin_kwh: float
    total_traction_energy_kwh: float
    total_regen_energy_kwh: float
    total_aux_energy_kwh: float
    total_btms_energy_kwh: float
    total_charging_energy_added_kwh: float
    total_charging_energy_grid_kwh: float
    total_net_battery_kwh_p50: float
    total_net_battery_kwh_p90: float
    total_friction_dissipation_kwh: float
    total_battery_internal_losses_kwh: float
    max_pack_temp_c: float
    min_pack_temp_c: float
    was_derated: bool
    energy_residual_total_j: float
    explanations: List[str]
    charging_events: List[ChargingEventResult]
    segment_telemetry: List[JourneySegmentTelemetry]


@dataclass(frozen=True)
class JourneySegmentTelemetry:
    """Detailed telemetry record for a single segment of a journey."""
    segment_id: str
    name: str
    distance_km: float
    speed_kmh: float
    duration_s: float
    gradient_pct: float
    elevation_start_m: Optional[float]
    elevation_end_m: Optional[float]
    ambient_temp_c: float
    f_roll_n: float
    f_aero_n: float
    f_grad_n: float
    f_net_wheel_n: float
    p_wheel_kw: float
    is_braking: bool
    soc_start_pct: float
    soc_end_pct: float
    v_terminal_v: float
    battery_current_a: float
    battery_power_kw: float
    battery_temp_c: float
    btms_mode: str
    derate_factor: float
    energy_net_kwh: float
    energy_regen_kwh: float
    energy_aux_kwh: float
    energy_btms_kwh: float
    energy_loss_battery_kwh: float
    energy_friction_kwh: float
    gradient_unknown: bool = False


@dataclass(frozen=True)
class JourneySimulationSummary:
    """Complete consolidated journey simulation output with decision engine results."""
    total_distance_km: float
    total_duration_min: float
    initial_soc_pct: float
    final_soc_p50_pct: float
    final_soc_p90_pct: float
    reserve_soc_pct: float
    feasibility_status: FeasibilityStatus
    feasibility_margin_kwh: float
    total_traction_energy_kwh: float
    total_regen_energy_kwh: float
    total_aux_energy_kwh: float
    total_btms_energy_kwh: float
    total_net_battery_kwh_p50: float
    total_net_battery_kwh_p90: float
    total_friction_dissipation_kwh: float
    total_battery_internal_losses_kwh: float
    max_pack_temp_c: float
    min_pack_temp_c: float
    was_derated: bool
    energy_residual_total_j: float
    explanations: List[str]
    segment_telemetry: List[JourneySegmentTelemetry]


def create_default_journey_configs(
    battery_capacity_kwh: float = 40.0,
    vehicle_mass_kg: float = 1600.0,
    max_motor_power_kw: float = 100.0,
    max_charge_power_kw: float = 65.0,
    ambient_temp_c: float = 25.0,
) -> Tuple[MotorConfig, GearboxConfig, InverterElectricalConfig, BatteryConfig, ThermalConfig]:
    """
    Generate harmonized powertrain, battery, and thermal configs.
    """
    # 1. Gearbox
    gearbox = GearboxConfig(
        gear_ratio=9.0,
        efficiency_fwd=0.97,
        efficiency_rev=0.96,
        wheel_radius_m=0.334,
        status=DataStatus.ESTIMATED,
    )

    # 2. Motor: 100 kW peak PMSM, ~250 Nm
    motor = MotorConfig(
        torque_cont_max_nm=180.0,
        power_cont_max_kw=max_motor_power_kw * 0.75,
        max_speed_rpm=12000.0,
        torque_peak_max_nm=250.0,
        power_peak_max_kw=max_motor_power_kw,
        pole_pairs=4,
        efficiency_mot=0.92,
        efficiency_gen=0.90,
        status=DataStatus.ESTIMATED,
    )

    # 3. Inverter
    inverter = InverterElectricalConfig(
        dc_voltage_nominal_v=350.0,
        dc_current_limit_a=350.0,
        dc_power_limit_kw=max_motor_power_kw * 1.1,
        efficiency_regen=0.96,
        standby_loss_w=80.0,
        status=DataStatus.ESTIMATED,
    )

    # 4. Battery: 1-RC Thevenin ~350V, scaled to requested capacity
    series_cells = 96
    nom_cell_ah = (battery_capacity_kwh * 1000.0) / (series_cells * 3.65)
    r0_cell = 0.0012
    r1_cell = 0.0008
    c1_cell = 2500.0

    battery = BatteryConfig(
        cell_chemistry="NMC",
        series_cells=series_cells,
        parallel_strings=1,
        nominal_cell_capacity_ah=nom_cell_ah,
        nominal_pack_capacity_kwh=battery_capacity_kwh,
        nominal_pack_voltage_v=series_cells * 3.65,
        cell_voltage_min_v=2.80,
        cell_voltage_max_v=4.25,
        cell_voltage_nominal_v=3.65,
        soc_min_operating=0.02,
        soc_max_operating=0.98,
        r0_pack_baseline_ohm=r0_cell * series_cells,
        r1_pack_baseline_ohm=r1_cell * series_cells,
        c1_pack_baseline_f=c1_cell / series_cells,
        max_charge_current_a=(max_charge_power_kw * 1000.0) / 350.0,
        max_discharge_current_a=-(max_motor_power_kw * 1000.0 * 1.15) / 300.0,
        max_charge_power_kw=max_charge_power_kw,
        max_discharge_power_kw=-max_motor_power_kw * 1.15,
        status=DataStatus.ESTIMATED,
    )

    # 5. Thermal: pack mass ~ 22% of vehicle mass
    thermal = ThermalConfig(
        pack_mass_kg=max(150.0, vehicle_mass_kg * 0.22),
        specific_heat_j_per_kg_k=900.0,
        heat_transfer_coeff_w_per_k=14.0,
        enable_active_cooling=True,
        enable_active_heating=True,
        target_cool_temp_c=32.0,
        target_heat_temp_c=12.0,
        status=DataStatus.ESTIMATED,
    )

    return motor, gearbox, inverter, battery, thermal


def simulate_journey(
    segments: List[Any],
    vehicle_mass_kg: float,
    frontal_area_m2: float,
    drag_coeff: float,
    rolling_res_coeff: float,
    battery_capacity_kwh: float,
    soc_start_pct: float,
    soc_reserve_pct: float,
    aux_power_kw: float = 1.2,
    ambient_temp_c: float = 25.0,
    confidence_target: float = 0.90,
    wheel_radius_m: float = 0.334,
    motor_config: Optional[MotorConfig] = None,
    gearbox_config: Optional[GearboxConfig] = None,
    inverter_config: Optional[InverterElectricalConfig] = None,
    battery_config: Optional[BatteryConfig] = None,
    thermal_config: Optional[ThermalConfig] = None,
) -> JourneySimulationSummary:
    """
    Run full continuous multi-segment journey simulation with high physical fidelity.
    """
    # Use defaults if not provided
    m_cfg, g_cfg, inv_cfg, bat_cfg, th_cfg = create_default_journey_configs(
        battery_capacity_kwh=battery_capacity_kwh,
        vehicle_mass_kg=vehicle_mass_kg,
        ambient_temp_c=ambient_temp_c,
    )
    motor = motor_config or m_cfg
    gearbox = gearbox_config or g_cfg
    inverter = inverter_config or inv_cfg
    battery = battery_config or bat_cfg
    thermal = thermal_config or th_cfg

    # Explicit validation: accept [0.0, 100.0] inclusive; reject invalid input without silent clamping
    if not math.isfinite(soc_start_pct) or not (0.0 <= soc_start_pct <= 100.0):
        raise ValueError(
            f"Invalid soc_start_pct: {soc_start_pct}. Starting SOC must be finite and within [0.0, 100.0]%."
        )
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

    # Baseline sea-level air density
    rho_air_base = compute_air_density(ambient_temp_c=ambient_temp_c).density_kg_m3

    # Dynamic BMS & Blending configs
    blending_cfg = BrakeBlendingConfig(
        regen_priority_ratio=1.0,
        max_friction_braking_force_n=15000.0,
        low_speed_cutoff_ms=1.5,
        full_regen_speed_ms=4.0,
        status=DataStatus.ESTIMATED,
    )

    total_dist_km = 0.0
    total_time_s = 0.0
    total_tract_kwh = 0.0
    total_regen_kwh = 0.0
    total_aux_kwh = 0.0
    total_btms_kwh = 0.0
    total_friction_kwh = 0.0
    total_battery_loss_kwh = 0.0
    total_residual_j = 0.0

    max_temp_c = ambient_temp_c
    min_temp_c = ambient_temp_c
    was_derated = False
    battery_depleted = False
    has_unknown_elevation = False
    explanations: List[str] = []
    telemetry_list: List[JourneySegmentTelemetry] = []

    # Road-type sigma for log-normal P90
    sigma_map = {"highway": 0.12, "rural": 0.20, "urban": 0.18}
    z_q = get_normal_quantile(confidence_target)
    total_p50_kwh = 0.0
    total_p90_kwh = 0.0

    for seg in segments:
        if isinstance(seg, dict):
            from app.models.schemas import RouteSegment
            seg = RouteSegment(**seg)

        # Extract segment attributes gracefully
        sid = getattr(seg, "segment_id", "seg")
        sname = getattr(seg, "name", sid) or sid
        
        # Distance
        dist_attr = getattr(seg, "distance_km", None)
        if dist_attr is None:
            dist_attr = getattr(seg, "distance", 1.0)
        dist_km = float(getattr(dist_attr, "value", dist_attr))

        # Speed
        speed_attr = getattr(seg, "avg_speed_kmh", None)
        if speed_attr is None:
            speed_attr = getattr(seg, "speed", 60.0)
        speed_kmh = float(getattr(speed_attr, "value", speed_attr))
        v_ms = max(0.5, speed_kmh / 3.6)

        # Gradient
        grad_attr = getattr(seg, "gradient_pct", None)
        if grad_attr is None:
            grad_attr = getattr(seg, "gradient", 0.0)
        
        is_unknown = False
        if grad_attr is None or getattr(seg, "gradient_status", None) == "UNKNOWN":
            is_unknown = True
            has_unknown_elevation = True
            grad_pct = 0.0
        else:
            grad_val = getattr(grad_attr, "value", grad_attr)
            if grad_val is None:
                is_unknown = True
                has_unknown_elevation = True
                grad_pct = 0.0
            else:
                grad_pct = float(grad_val)

        rtype = str(getattr(getattr(seg, "road_type", "urban"), "value", getattr(seg, "road_type", "urban"))).lower()
        if "high" in rtype or "express" in rtype:
            rtype_norm = "highway"
        elif "rur" in rtype:
            rtype_norm = "rural"
        else:
            rtype_norm = "urban"

        # Duration of segment
        dt_seg_s = (dist_km * 1000.0) / v_ms
        total_dist_km += dist_km
        total_time_s += dt_seg_s

        # Wind & Atmospheric Density Resolution (RC2-AERO-01)
        elev_m = getattr(seg, "elevation_start", None) or getattr(seg, "elevation_end", None)
        if elev_m is not None:
            rho_air = compute_air_density(ambient_temp_c=ambient_temp_c, elevation_m=float(elev_m)).density_kg_m3
        else:
            rho_air = rho_air_base

        heading_deg = float(getattr(seg, "bearing", None) or getattr(seg, "heading_deg", 0.0) or 0.0)
        wind_spd = getattr(seg, "wind_speed_ms", None)
        if wind_spd is None and getattr(seg, "wind_speed_kmh", None) is not None:
            wind_spd = float(getattr(seg, "wind_speed_kmh")) / 3.6
        wind_dir = getattr(seg, "wind_bearing_deg", None) or getattr(seg, "wind_direction_deg", None)
        if wind_dir is not None:
            wind_dir = float(wind_dir)

        wind_res = compute_apparent_wind(
            vehicle_speed_ms=v_ms,
            vehicle_heading_deg=heading_deg,
            wind_speed_ms=float(wind_spd) if wind_spd is not None else None,
            wind_direction_from_deg=wind_dir,
        )
        v_apparent_ms = wind_res.apparent_airspeed_ms

        # 1. Road forces
        f_roll = compute_rolling_resistance(
            total_mass_kg=vehicle_mass_kg,
            base_crr=rolling_res_coeff,
            gradient_pct=grad_pct if not is_unknown else None,
        ).force_n
        f_aero = compute_aerodynamic_drag(
            frontal_area_m2=frontal_area_m2,
            drag_coefficient_cd=drag_coeff,
            apparent_airspeed_ms=v_apparent_ms,
            air_density_kg_m3=rho_air,
        ).force_n
        f_grad = compute_gradient_force(
            total_mass_kg=vehicle_mass_kg,
            gradient_pct=grad_pct if not is_unknown else None,
        ).force_n

        # Stop-start correction factor for urban
        urban_mult = 1.12 if rtype_norm == "urban" else 1.0
        f_tract_demand = (f_roll + f_aero) * urban_mult + f_grad
        p_wheel_demand_kw = (f_tract_demand * v_ms) / 1000.0

        # Signed force: positive = traction, negative = braking
        is_braking = (f_tract_demand <= 0.0)
        signed_wheel_force_n = -abs(f_tract_demand) if is_braking else f_tract_demand

        # Total base auxiliary power
        aux_base_kw = aux_power_kw

        # Sub-stepping: limit each discrete integration step dt to max 60.0s
        max_substep_dt = 60.0
        n_substeps = max(1, math.ceil(dt_seg_s / max_substep_dt))
        dt_sub = dt_seg_s / n_substeps

        soc_before_pct = bat_state.soc * 100.0
        seg_net_kwh = 0.0
        seg_regen_kwh = 0.0
        seg_aux_kwh = 0.0
        seg_btms_kwh = 0.0
        seg_loss_kwh = 0.0
        seg_fric_kwh = 0.0
        seg_tract_kwh = 0.0

        latest_op = None
        latest_th_res = None

        for _ in range(n_substeps):
            # Evaluate active BTMS electrical power based on current pack temperature (RC2-THERM-02)
            p_btms_elec_kw = 0.0
            if thermal.enable_active_cooling and th_state.temperature_c > thermal.target_cool_temp_c:
                excess = th_state.temperature_c - thermal.target_cool_temp_c
                q_cool_w = min(thermal.max_cooling_power_w, thermal.cooling_proportional_gain_w_per_k * excess)
                p_btms_elec_kw = (q_cool_w / thermal.cop_cooling) / 1000.0
            elif thermal.enable_active_heating and th_state.temperature_c < thermal.target_heat_temp_c:
                deficit = thermal.target_heat_temp_c - th_state.temperature_c
                q_heat_w = min(thermal.max_heating_power_w, thermal.heating_proportional_gain_w_per_k * deficit)
                p_btms_elec_kw = (q_heat_w / thermal.cop_heating) / 1000.0

            # Combined electrical auxiliary load delivered by battery
            aux_step_total_kw = aux_base_kw + p_btms_elec_kw

            # Evaluate thermal derating factor and scale admissible limits (RC2-THERM-03)
            derate_factor, _ = compute_thermal_derating(th_state.temperature_c, thermal)
            if derate_factor < 0.9999:
                was_derated = True
                eff_battery = battery.model_copy(update={
                    "max_discharge_power_kw": battery.max_discharge_power_kw * derate_factor,
                    "max_charge_power_kw": battery.max_charge_power_kw * derate_factor,
                    "max_discharge_current_a": battery.max_discharge_current_a * derate_factor,
                    "max_charge_current_a": battery.max_charge_current_a * derate_factor,
                })
                eff_motor = motor.model_copy(update={
                    "power_cont_max_kw": motor.power_cont_max_kw * derate_factor,
                    "power_peak_max_kw": motor.power_peak_max_kw * derate_factor,
                    "torque_cont_max_nm": motor.torque_cont_max_nm * derate_factor,
                    "torque_peak_max_nm": motor.torque_peak_max_nm * derate_factor,
                })
            else:
                eff_battery = battery
                eff_motor = motor

            # Simulate integrated powertrain step
            pt_res = simulate_integrated_powertrain_step(
                requested_wheel_force_n=signed_wheel_force_n,
                vehicle_speed_ms=v_ms,
                dt_s=dt_sub,
                battery_state=bat_state,
                battery_config=eff_battery,
                gearbox_config=gearbox,
                motor_config=eff_motor,
                inverter_config=inverter,
                auxiliary_lv_power_kw=aux_step_total_kw,
                blending_config=blending_cfg,
            )

            bat_sim = pt_res.battery_simulation_result
            new_bat_state = bat_sim.final_state
            latest_op = bat_sim.operating_point

            # Pack internal losses converted to heat generation rate Q_dot_gen [W]
            pack_losses_j = bat_sim.energy_loss_r0_j + bat_sim.energy_loss_r1_j + bat_sim.energy_loss_parasitic_j
            q_gen_w = pack_losses_j / dt_sub if dt_sub > 0 else 0.0

            # Thermal model update
            new_th_state, th_res = simulate_thermal_step(
                state=th_state,
                q_gen_w=q_gen_w,
                ambient_temp_c=ambient_temp_c,
                dt_s=dt_sub,
                config=thermal,
            )
            latest_th_res = th_res

            # Depletion checks
            if new_bat_state.soc <= battery.soc_min_operating or (
                latest_op.is_voltage_limited and latest_op.terminal_voltage_v <= battery.cell_voltage_min_v * battery.series_cells
            ):
                battery_depleted = True

            # Synchronize thermal state into battery state for next step (RC2-THERM-01)
            bat_state = dataclasses.replace(new_bat_state, temperature_c=new_th_state.temperature_c)
            th_state = new_th_state

            max_temp_c = max(max_temp_c, th_state.temperature_c)
            min_temp_c = min(min_temp_c, th_state.temperature_c)

            sub_net_kwh = -(bat_sim.accepted_power_kw * dt_sub) / 3600.0
            sub_regen_kwh = (abs(pt_res.delivered_regen_power_kw) * dt_sub) / 3600.0 if is_braking else 0.0
            sub_aux_kwh = (aux_base_kw * dt_sub) / 3600.0
            sub_btms_kwh = (p_btms_elec_kw * dt_sub) / 3600.0
            sub_loss_kwh = pack_losses_j / (3600.0 * 1000.0)
            sub_fric_kwh = (pt_res.delivered_friction_power_kw * dt_sub) / 3600.0

            seg_net_kwh += sub_net_kwh
            seg_regen_kwh += sub_regen_kwh
            seg_aux_kwh += sub_aux_kwh
            seg_btms_kwh += sub_btms_kwh
            seg_loss_kwh += sub_loss_kwh
            seg_fric_kwh += sub_fric_kwh
            if not is_braking:
                seg_tract_kwh += (pt_res.delivered_wheel_power_kw * dt_sub) / 3600.0
            total_residual_j += abs(bat_sim.energy_residual_j)

        soc_after_pct = bat_state.soc * 100.0
        op = latest_op
        th_res = latest_th_res

        total_tract_kwh += seg_tract_kwh
        total_regen_kwh += seg_regen_kwh
        total_aux_kwh += seg_aux_kwh
        total_btms_kwh += seg_btms_kwh
        total_friction_kwh += seg_fric_kwh
        total_battery_loss_kwh += seg_loss_kwh

        total_p50_kwh += seg_net_kwh

        # P90 uncertainty applied to tractive net load (excluding constant baseline auxiliary)
        sig = sigma_map.get(rtype_norm, 0.18)
        p90_factor = math.exp(z_q * sig)
        seg_traction_portion = max(0.0, seg_net_kwh - seg_aux_kwh)
        seg_p90_kwh = seg_traction_portion * p90_factor + seg_aux_kwh
        total_p90_kwh += seg_p90_kwh

        telem = JourneySegmentTelemetry(
            segment_id=sid,
            name=sname,
            distance_km=round(dist_km, 3),
            speed_kmh=round(speed_kmh, 1),
            duration_s=round(dt_seg_s, 1),
            gradient_pct=round(grad_pct, 2),
            elevation_start_m=getattr(seg, "elevation_start", None),
            elevation_end_m=getattr(seg, "elevation_end", None),
            ambient_temp_c=ambient_temp_c,
            f_roll_n=round(f_roll, 1),
            f_aero_n=round(f_aero, 1),
            f_grad_n=round(f_grad, 1),
            f_net_wheel_n=round(f_tract_demand, 1),
            p_wheel_kw=round(p_wheel_demand_kw, 2),
            is_braking=is_braking,
            soc_start_pct=round(soc_before_pct, 2),
            soc_end_pct=round(soc_after_pct, 2),
            v_terminal_v=round(op.terminal_voltage_v, 2),
            battery_current_a=round(op.current_a, 2),
            battery_power_kw=round(op.terminal_power_kw, 2),
            battery_temp_c=round(th_state.temperature_c, 2),
            btms_mode=th_state.btms_mode.value,
            derate_factor=round(th_res.derate_factor, 3),
            energy_net_kwh=round(seg_net_kwh, 4),
            energy_regen_kwh=round(seg_regen_kwh, 4),
            energy_aux_kwh=round(seg_aux_kwh, 4),
            energy_btms_kwh=round(seg_btms_kwh, 4),
            energy_loss_battery_kwh=round(seg_loss_kwh, 4),
            energy_friction_kwh=round(seg_fric_kwh, 4),
            gradient_unknown=is_unknown,
        )
        telemetry_list.append(telem)

    # 4. Final Feasibility Decision & Authoritative SOC Quantification (RC2-SOC-01)
    # The nominal final SOC is directly obtained from the physically integrated battery state
    final_soc_p50 = max(0.0, min(100.0, bat_state.soc * 100.0))

    final_soc_p90 = soc_start_pct - (total_p90_kwh / battery_capacity_kwh) * 100.0
    final_soc_p90 = max(-50.0, min(100.0, final_soc_p90))

    margin_kwh = (final_soc_p90 - soc_reserve_pct) / 100.0 * battery_capacity_kwh

    if battery_depleted or final_soc_p50 <= 0.0 or final_soc_p90 < 0.0:
        status = FeasibilityStatus.WILL_NOT_MAKE_IT
        explanations.append(
            f"WILL NOT MAKE IT: Battery depletion detected. Final P90 SOC drops to {final_soc_p90:.1f}%, "
            f"violating minimum operational limits. Recharging stop required."
        )
    elif final_soc_p90 < soc_reserve_pct:
        status = FeasibilityStatus.LOW_RESERVE
        explanations.append(
            f"LOW RESERVE: Expected arrival SOC is {final_soc_p50:.1f}%, but under conservative P90 "
            f"conditions arrival SOC drops to {final_soc_p90:.1f}%, which is below the required {soc_reserve_pct:.0f}% safety reserve "
            f"(deficit: {abs(margin_kwh):.1f} kWh)."
        )
    elif has_unknown_elevation:
        status = FeasibilityStatus.UNCERTAIN
        explanations.append(
            "UNCERTAIN: Significant portion of the route lacks verified digital elevation models. "
            "Simulated on nominal flat assumptions without empirical hill climbs."
        )
    else:
        status = FeasibilityStatus.WILL_MAKE_IT
        explanations.append(
            f"WILL MAKE IT: Feasible journey. Arrival SOC (P90) is {final_soc_p90:.1f}%, safely exceeding "
            f"the {soc_reserve_pct:.0f}% reserve requirement with +{margin_kwh:.1f} kWh buffer."
        )

    if was_derated:
        explanations.append(
            f"Thermal Notice: Battery pack reached {max_temp_c:.1f}°C during heavy load, triggering dynamic BTMS cooling and power derating."
        )

    return JourneySimulationSummary(
        total_distance_km=round(total_dist_km, 2),
        total_duration_min=round(total_time_s / 60.0, 1),
        initial_soc_pct=round(soc_start_pct, 2),
        final_soc_p50_pct=round(final_soc_p50, 2),
        final_soc_p90_pct=round(final_soc_p90, 2),
        reserve_soc_pct=round(soc_reserve_pct, 2),
        feasibility_status=status,
        feasibility_margin_kwh=round(margin_kwh, 2),
        total_traction_energy_kwh=round(total_tract_kwh, 3),
        total_regen_energy_kwh=round(total_regen_kwh, 3),
        total_aux_energy_kwh=round(total_aux_kwh, 3),
        total_btms_energy_kwh=round(total_btms_kwh, 3),
        total_net_battery_kwh_p50=round(total_p50_kwh, 3),
        total_net_battery_kwh_p90=round(total_p90_kwh, 3),
        total_friction_dissipation_kwh=round(total_friction_kwh, 3),
        total_battery_internal_losses_kwh=round(total_battery_loss_kwh, 3),
        max_pack_temp_c=round(max_temp_c, 2),
        min_pack_temp_c=round(min_temp_c, 2),
        was_derated=was_derated,
        energy_residual_total_j=round(total_residual_j, 4),
        explanations=explanations,
        segment_telemetry=telemetry_list,
    )


# =============================================================================
# Authoritative Continuous Multi-Stop Simulation Architecture (C3-MS-01)
# =============================================================================

def simulate_charging_event(
    state: BatteryState,
    thermal_state: ThermalState,
    target_soc_pct: float,
    charger_max_power_kw: float,
    battery_config: BatteryConfig,
    thermal_config: ThermalConfig,
    ambient_temp_c: float,
    battery_capacity_kwh: float = 40.0,
    charger_id: str = "CHARGER_DEMO",
    charger_name: str = "Fast Charger",
    charger_status: str = "UNKNOWN",
    grid_efficiency: float = 0.92,
    substep_dt_s: float = 60.0,
    max_charge_time_min: float = 180.0,
) -> Tuple[BatteryState, ThermalState, ChargingEventResult]:
    """
    Simulate a physically constrained charging event on the continuous 1-RC Thevenin battery state.
    
    Models:
    - Joint power boundaries: min(charger power, battery max charge power).
    - Continuous CCCV taper above 80% SOC.
    - Continuous thermal evolution & dynamic BTMS liquid cooling.
    - Preserves continuous polarization voltage (V1), SOC, temperature, and throughput.
    """
    cur_bat = state
    cur_th = thermal_state
    init_soc = cur_bat.soc * 100.0
    target_soc_frac = min(1.0, max(0.0, target_soc_pct / 100.0))

    notes: List[str] = [
        f"Charging at {charger_name} ({charger_id}) rated at {charger_max_power_kw:.1f} kW [{charger_status}].",
        "Duration is an idealized CCCV engineering estimate constrained by 1-RC Thevenin and thermal models.",
    ]

    if cur_bat.soc >= target_soc_frac:
        notes.append("Battery already at or above target SOC. Zero charge energy transferred.")
        return cur_bat, cur_th, ChargingEventResult(
            charger_id=charger_id,
            charger_name=charger_name,
            charger_status=charger_status,
            arrive_soc_pct=round(init_soc, 2),
            depart_soc_pct=round(init_soc, 2),
            target_soc_pct=round(target_soc_pct, 2),
            charge_duration_min=0.0,
            energy_added_battery_kwh=0.0,
            energy_from_grid_kwh=0.0,
            peak_charge_power_kw=0.0,
            avg_charge_power_kw=0.0,
            battery_temp_start_c=round(cur_th.temperature_c, 2),
            battery_temp_end_c=round(cur_th.temperature_c, 2),
            btms_cooling_energy_kwh=0.0,
            was_derated=False,
            notes=notes,
        )

    t_elapsed_s = 0.0
    cum_energy_battery_j = 0.0
    cum_btms_elec_j = 0.0
    peak_charge_kw = 0.0
    was_derated = False
    temp_start = cur_th.temperature_c

    while cur_bat.soc < (target_soc_frac - 1e-4) and t_elapsed_s < (max_charge_time_min * 60.0):
        # 1. Thermal derating factor
        derate_factor, derate_mode = compute_thermal_derating(cur_th.temperature_c, thermal_config)
        if derate_factor < 0.9999:
            was_derated = True

        # 2. CCCV Taper above 80% SOC
        if cur_bat.soc > 0.80:
            f_taper = max(0.15, 1.0 - 0.85 * ((cur_bat.soc - 0.80) / 0.20))
        else:
            f_taper = 1.0

        p_base_kw = min(charger_max_power_kw, battery_config.max_charge_power_kw)
        p_admissible_kw = max(0.5, p_base_kw * derate_factor * f_taper)

        # 3. Dynamic sub-step time (ensure we do not overshoot target SOC)
        soc_deficit = max(0.0, target_soc_frac - cur_bat.soc)
        approx_energy_j = soc_deficit * (battery_capacity_kwh * 3_600_000.0)
        dt_needed_s = approx_energy_j / (p_admissible_kw * 1000.0) if p_admissible_kw > 0 else substep_dt_s
        dt = min(substep_dt_s, max(1.0, dt_needed_s))

        # 4. Discrete battery step on 1-RC Thevenin circuit
        eff_battery = battery_config.model_copy(update={
            "max_charge_power_kw": battery_config.max_charge_power_kw * derate_factor,
            "max_charge_current_a": battery_config.max_charge_current_a * derate_factor,
        })
        bat_sim = simulate_battery_step(
            requested_power_kw=p_admissible_kw,
            state=cur_bat,
            dt_s=dt,
            config=eff_battery,
        )

        p_actual_kw = bat_sim.accepted_power_kw
        peak_charge_kw = max(peak_charge_kw, p_actual_kw)
        cum_energy_battery_j += bat_sim.energy_terminal_j

        # 5. Pack heat dissipation
        losses_j = bat_sim.energy_loss_r0_j + bat_sim.energy_loss_r1_j + bat_sim.energy_loss_parasitic_j
        q_gen_w = losses_j / dt if dt > 0 else 0.0

        # 6. Lumped thermal integration step
        new_th, th_step = simulate_thermal_step(
            state=cur_th,
            q_gen_w=q_gen_w,
            ambient_temp_c=ambient_temp_c,
            dt_s=dt,
            config=thermal_config,
        )
        cum_btms_elec_j += th_step.p_btms_electrical_kw * 1000.0 * dt

        # 7. Carry-forward continuous states
        cur_bat = dataclasses.replace(bat_sim.final_state, temperature_c=new_th.temperature_c)
        cur_th = new_th
        t_elapsed_s += dt

    duration_min = t_elapsed_s / 60.0
    energy_added_kwh = cum_energy_battery_j / 3_600_000.0
    energy_grid_kwh = energy_added_kwh / grid_efficiency if grid_efficiency > 0 else energy_added_kwh
    avg_power_kw = (energy_added_kwh / (duration_min / 60.0)) if duration_min > 0 else 0.0
    final_soc_pct = cur_bat.soc * 100.0

    return cur_bat, cur_th, ChargingEventResult(
        charger_id=charger_id,
        charger_name=charger_name,
        charger_status=charger_status,
        arrive_soc_pct=round(init_soc, 2),
        depart_soc_pct=round(final_soc_pct, 2),
        target_soc_pct=round(target_soc_pct, 2),
        charge_duration_min=round(duration_min, 1),
        energy_added_battery_kwh=round(energy_added_kwh, 3),
        energy_from_grid_kwh=round(energy_grid_kwh, 3),
        peak_charge_power_kw=round(peak_charge_kw, 1),
        avg_charge_power_kw=round(avg_power_kw, 1),
        battery_temp_start_c=round(temp_start, 2),
        battery_temp_end_c=round(cur_th.temperature_c, 2),
        btms_cooling_energy_kwh=round(cum_btms_elec_j / 3_600_000.0, 3),
        was_derated=was_derated,
        notes=notes,
    )


def simulate_multistop_journey(
    segments: List[Any],
    scheduled_stops: List[Dict[str, Any]],
    vehicle_mass_kg: float,
    frontal_area_m2: float,
    drag_coeff: float,
    rolling_res_coeff: float,
    battery_capacity_kwh: float,
    soc_start_pct: float,
    soc_reserve_pct: float,
    aux_power_kw: float = 1.2,
    ambient_temp_c: float = 25.0,
    confidence_target: float = 0.90,
    wheel_radius_m: float = 0.334,
    motor_config: Optional[MotorConfig] = None,
    gearbox_config: Optional[GearboxConfig] = None,
    inverter_config: Optional[InverterElectricalConfig] = None,
    battery_config: Optional[BatteryConfig] = None,
    thermal_config: Optional[ThermalConfig] = None,
) -> MultiStopJourneySummary:
    """
    Authoritative continuous simulation of a multi-stop EV journey.
    
    Preserves continuous physical states (SOC, V1 polarization voltage, pack temperature,
    throughput, thermal BTMS modes) across both driving segments and intermediate charging stops.
    Enforces minimum operational boundary (2.0% SOC) and evaluates reachability rigorously.
    """
    m_cfg, g_cfg, inv_cfg, bat_cfg, th_cfg = create_default_journey_configs(
        battery_capacity_kwh=battery_capacity_kwh,
        vehicle_mass_kg=vehicle_mass_kg,
        ambient_temp_c=ambient_temp_c,
    )
    motor = motor_config or m_cfg
    gearbox = gearbox_config or g_cfg
    inverter = inverter_config or inv_cfg
    battery = battery_config or bat_cfg
    thermal = thermal_config or th_cfg

    if not math.isfinite(soc_start_pct) or not (0.0 <= soc_start_pct <= 100.0):
        raise ValueError(f"Invalid soc_start_pct: {soc_start_pct}. Must be within [0.0, 100.0]%.")

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

    rho_air_base = compute_air_density(ambient_temp_c=ambient_temp_c).density_kg_m3
    blending_cfg = BrakeBlendingConfig(
        max_regen_torque_nm=motor.torque_peak_max_nm,
        low_speed_cutoff_ms=1.5,
        full_regen_speed_ms=4.0,
        status=DataStatus.ESTIMATED,
    )

    # Accumulators
    total_dist_km = 0.0
    total_driving_time_s = 0.0
    total_tract_kwh = 0.0
    total_regen_kwh = 0.0
    total_aux_kwh = 0.0
    total_btms_kwh = 0.0
    total_friction_kwh = 0.0
    total_battery_loss_kwh = 0.0
    total_residual_j = 0.0
    total_p50_net_kwh = 0.0
    total_p90_net_kwh = 0.0

    max_temp_c = ambient_temp_c
    min_temp_c = ambient_temp_c
    was_derated = False
    battery_depleted = False
    depleted_segment_name = ""
    all_chargers_reachable = True
    has_unknown_elevation = False

    explanations: List[str] = []
    telemetry_list: List[JourneySegmentTelemetry] = []
    charging_results: List[ChargingEventResult] = []

    # Map stops by segment index (trigger after that segment completes)
    stops_by_idx: Dict[int, Dict[str, Any]] = {}
    for stop in scheduled_stops:
        idx = int(stop.get("after_segment_index", 0))
        stops_by_idx[idx] = stop

    sigma_map = {"highway": 0.12, "rural": 0.20, "urban": 0.18}
    z_q = get_normal_quantile(confidence_target)

    for seg_idx, raw_seg in enumerate(segments):
        if isinstance(raw_seg, dict):
            from app.models.schemas import RouteSegment
            seg = RouteSegment(**raw_seg)
        else:
            seg = raw_seg

        sid = getattr(seg, "segment_id", f"seg_{seg_idx}")
        sname = getattr(seg, "name", sid) or sid
        dist_km = float(getattr(seg, "distance_km", 1.0))
        speed_kmh = float(getattr(seg, "avg_speed_kmh", 60.0))
        v_ms = max(0.5, speed_kmh / 3.6)

        grad_attr = getattr(seg, "gradient_pct", 0.0)
        if grad_attr is None or getattr(seg, "gradient_status", None) == "UNKNOWN":
            has_unknown_elevation = True
            grad_pct = 0.0
        else:
            grad_pct = float(grad_attr)

        rtype_norm = str(getattr(seg, "road_type", "urban")).lower()
        if "highway" in rtype_norm or "express" in rtype_norm:
            rtype_norm = "highway"
        elif "rural" in rtype_norm:
            rtype_norm = "rural"
        else:
            rtype_norm = "urban"

        dt_seg_s = (dist_km * 1000.0) / v_ms
        total_dist_km += dist_km
        total_driving_time_s += dt_seg_s

        # Wind & atmospheric resistance
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

        urban_mult = 1.12 if rtype_norm == "urban" else 1.0
        f_tract_demand = (f_roll + f_aero) * urban_mult + f_grad
        is_braking = (f_tract_demand <= 0.0)
        signed_wheel_force_n = -abs(f_tract_demand) if is_braking else f_tract_demand

        # Sub-stepping
        max_substep_dt = 60.0
        n_substeps = max(1, math.ceil(dt_seg_s / max_substep_dt))
        dt_sub = dt_seg_s / n_substeps

        soc_before_pct = bat_state.soc * 100.0
        seg_net_kwh = 0.0
        seg_regen_kwh = 0.0
        seg_aux_kwh = 0.0
        seg_btms_kwh = 0.0
        seg_loss_kwh = 0.0
        seg_fric_kwh = 0.0
        latest_op = None

        # Check if battery was already depleted before starting this segment
        if bat_state.soc * 100.0 <= MIN_OPERATING_SOC_PCT:
            battery_depleted = True
            if not depleted_segment_name:
                depleted_segment_name = sname

        for _ in range(n_substeps):
            if battery_depleted:
                break

            # BTMS power
            p_btms_elec_kw = 0.0
            if thermal.enable_active_cooling and th_state.temperature_c > thermal.target_cool_temp_c:
                excess = th_state.temperature_c - thermal.target_cool_temp_c
                q_cool_w = min(thermal.max_cooling_power_w, thermal.cooling_proportional_gain_w_per_k * excess)
                p_btms_elec_kw = (q_cool_w / thermal.cop_cooling) / 1000.0
            elif thermal.enable_active_heating and th_state.temperature_c < thermal.target_heat_temp_c:
                deficit = thermal.target_heat_temp_c - th_state.temperature_c
                q_heat_w = min(thermal.max_heating_power_w, thermal.heating_proportional_gain_w_per_k * deficit)
                p_btms_elec_kw = (q_heat_w / thermal.cop_heating) / 1000.0

            aux_step_total_kw = aux_power_kw + p_btms_elec_kw

            derate_factor, _ = compute_thermal_derating(th_state.temperature_c, thermal)
            if derate_factor < 0.9999:
                was_derated = True
                eff_battery = battery.model_copy(update={
                    "max_discharge_power_kw": battery.max_discharge_power_kw * derate_factor,
                    "max_charge_power_kw": battery.max_charge_power_kw * derate_factor,
                    "max_discharge_current_a": battery.max_discharge_current_a * derate_factor,
                    "max_charge_current_a": battery.max_charge_current_a * derate_factor,
                })
                eff_motor = motor.model_copy(update={
                    "power_cont_max_kw": motor.power_cont_max_kw * derate_factor,
                    "power_peak_max_kw": motor.power_peak_max_kw * derate_factor,
                    "torque_cont_max_nm": motor.torque_cont_max_nm * derate_factor,
                    "torque_peak_max_nm": motor.torque_peak_max_nm * derate_factor,
                })
            else:
                eff_battery = battery
                eff_motor = motor

            pt_res = simulate_integrated_powertrain_step(
                requested_wheel_force_n=signed_wheel_force_n,
                vehicle_speed_ms=v_ms,
                dt_s=dt_sub,
                battery_state=bat_state,
                battery_config=eff_battery,
                gearbox_config=gearbox,
                motor_config=eff_motor,
                inverter_config=inverter,
                auxiliary_lv_power_kw=aux_step_total_kw,
                blending_config=blending_cfg,
            )

            bat_sim = pt_res.battery_simulation_result
            new_bat_state = bat_sim.final_state
            latest_op = bat_sim.operating_point

            losses_j = bat_sim.energy_loss_r0_j + bat_sim.energy_loss_r1_j + bat_sim.energy_loss_parasitic_j
            q_gen_w = losses_j / dt_sub if dt_sub > 0 else 0.0

            new_th_state, th_res = simulate_thermal_step(
                state=th_state,
                q_gen_w=q_gen_w,
                ambient_temp_c=ambient_temp_c,
                dt_s=dt_sub,
                config=thermal,
            )

            # Advance continuous state
            bat_state = dataclasses.replace(new_bat_state, temperature_c=new_th_state.temperature_c)
            th_state = new_th_state

            # Energy metrics
            step_terminal_kwh = -bat_sim.energy_terminal_j / 3_600_000.0
            seg_net_kwh += step_terminal_kwh
            if pt_res.is_braking_mode:
                seg_regen_kwh += abs(pt_res.delivered_regen_power_kw * (dt_sub / 3600.0))
            seg_aux_kwh += aux_power_kw * (dt_sub / 3600.0)
            seg_btms_kwh += p_btms_elec_kw * (dt_sub / 3600.0)
            seg_loss_kwh += losses_j / 3_600_000.0
            seg_fric_kwh += pt_res.energy_friction_dissipated_j / 3_600_000.0
            total_residual_j += abs(pt_res.energy_accounting_residual_j) + abs(bat_sim.energy_residual_j)

            max_temp_c = max(max_temp_c, th_state.temperature_c)
            min_temp_c = min(min_temp_c, th_state.temperature_c)

            # Depletion check: hit minimum operating cutoff
            if bat_state.soc * 100.0 <= MIN_OPERATING_SOC_PCT:
                battery_depleted = True
                if not depleted_segment_name:
                    depleted_segment_name = sname

        # Segment level P90 dispersion
        sigma = sigma_map.get(rtype_norm, 0.15)
        seg_p50_kwh = max(0.0, seg_net_kwh)
        seg_p90_kwh = seg_p50_kwh * math.exp(z_q * sigma)

        total_p50_net_kwh += seg_p50_kwh
        total_p90_net_kwh += seg_p90_kwh
        total_tract_kwh += max(0.0, seg_net_kwh - seg_aux_kwh - seg_btms_kwh)
        total_regen_kwh += seg_regen_kwh
        total_aux_kwh += seg_aux_kwh
        total_btms_kwh += seg_btms_kwh
        total_friction_kwh += seg_fric_kwh
        total_battery_loss_kwh += seg_loss_kwh

        soc_after_pct = bat_state.soc * 100.0
        telemetry_list.append(JourneySegmentTelemetry(
            segment_id=sid,
            name=sname,
            distance_km=dist_km,
            speed_kmh=speed_kmh,
            duration_s=dt_seg_s,
            gradient_pct=grad_pct,
            elevation_start_m=getattr(seg, "elevation_start", None),
            elevation_end_m=getattr(seg, "elevation_end", None),
            ambient_temp_c=ambient_temp_c,
            f_roll_n=round(f_roll, 1),
            f_aero_n=round(f_aero, 1),
            f_grad_n=round(f_grad, 1),
            f_net_wheel_n=round(signed_wheel_force_n, 1),
            p_wheel_kw=round((signed_wheel_force_n * v_ms) / 1000.0, 2),
            is_braking=is_braking,
            soc_start_pct=round(soc_before_pct, 2),
            soc_end_pct=round(soc_after_pct, 2),
            v_terminal_v=round(latest_op.terminal_voltage_v, 1) if latest_op else 400.0,
            battery_current_a=round(latest_op.current_a, 1) if latest_op else 0.0,
            battery_power_kw=round(latest_op.terminal_power_kw, 2) if latest_op else 0.0,
            battery_temp_c=round(th_state.temperature_c, 2),
            btms_mode=th_state.btms_mode.value,
            derate_factor=round(derate_factor, 3),
            energy_net_kwh=round(seg_net_kwh, 3),
            energy_regen_kwh=round(seg_regen_kwh, 3),
            energy_aux_kwh=round(seg_aux_kwh, 3),
            energy_btms_kwh=round(seg_btms_kwh, 3),
            energy_loss_battery_kwh=round(seg_loss_kwh, 3),
            energy_friction_kwh=round(seg_fric_kwh, 3),
            gradient_unknown=(grad_attr is None or getattr(seg, "gradient_status", None) == "UNKNOWN"),
        ))

        # Check if a scheduled charging stop occurs after this segment
        if seg_idx in stops_by_idx:
            stop_cfg = stops_by_idx[seg_idx]
            chg_id = stop_cfg.get("charger_id", "CHARGER")
            chg_name = stop_cfg.get("charger_name", chg_id)
            chg_status = stop_cfg.get("charger_status", "UNKNOWN")
            chg_pwr = float(stop_cfg.get("max_power_kw", 50.0))
            chg_target_soc = float(stop_cfg.get("target_soc_pct", 80.0))

            # Verify reachability: Did the battery deplete before reaching this charger?
            if battery_depleted or bat_state.soc * 100.0 <= MIN_OPERATING_SOC_PCT:
                all_chargers_reachable = False
                explanations.append(
                    f"CRITICAL: Vehicle arrived at charger '{chg_name}' with {bat_state.soc * 100.0:.1f}% SOC, "
                    f"violating minimum operating cutoff ({MIN_OPERATING_SOC_PCT}%). Charger is UNREACHABLE."
                )
            else:
                # Execute continuous physical charging simulation
                new_bat, new_th, chg_res = simulate_charging_event(
                    state=bat_state,
                    thermal_state=th_state,
                    target_soc_pct=chg_target_soc,
                    charger_max_power_kw=chg_pwr,
                    battery_config=battery,
                    thermal_config=thermal,
                    ambient_temp_c=ambient_temp_c,
                    battery_capacity_kwh=battery_capacity_kwh,
                    charger_id=chg_id,
                    charger_name=chg_name,
                    charger_status=chg_status,
                )
                charging_results.append(chg_res)
                bat_state = new_bat
                th_state = new_th
                max_temp_c = max(max_temp_c, chg_res.battery_temp_end_c)
                min_temp_c = min(min_temp_c, chg_res.battery_temp_end_c)
                if chg_res.was_derated:
                    was_derated = True

    # 4. Final Feasibility Decision & Authoritative Quantification
    total_charging_time_min = sum(c.charge_duration_min for c in charging_results)
    total_charging_energy_batt_kwh = sum(c.energy_added_battery_kwh for c in charging_results)
    total_charging_energy_grid_kwh = sum(c.energy_from_grid_kwh for c in charging_results)
    total_journey_duration_min = (total_driving_time_s / 60.0) + total_charging_time_min

    final_soc_p50 = max(0.0, min(100.0, bat_state.soc * 100.0))
    # Net energy balance over full journey
    final_soc_p90 = max(0.0, min(100.0, final_soc_p50 - (total_p90_net_kwh - total_p50_net_kwh) / battery_capacity_kwh * 100.0))
    margin_kwh = (final_soc_p90 - soc_reserve_pct) / 100.0 * battery_capacity_kwh

    is_energy_feasible = (not battery_depleted) and all_chargers_reachable and (final_soc_p90 >= soc_reserve_pct)

    # Determine aggregate infrastructure provenance
    all_statuses = [c.charger_status for c in charging_results]
    if any(s == "HYPOTHETICAL" for s in all_statuses):
        infr_status = "HYPOTHETICAL"
    elif any(s in ("DEMO_SEED", "UNKNOWN", "STALE") for s in all_statuses):
        infr_status = "DEMO_SEED"
    elif all_statuses and all(s == "VERIFIED_REAL" for s in all_statuses):
        infr_status = "VERIFIED_REAL"
    else:
        infr_status = "NONE_REQUIRED"

    if not all_chargers_reachable or battery_depleted or final_soc_p50 <= MIN_OPERATING_SOC_PCT:
        feasibility_status = FeasibilityStatus.WILL_NOT_MAKE_IT
        explanations.append(
            f"WILL NOT MAKE IT: Battery depletion detected on route (segment '{depleted_segment_name}'). "
            f"Arrival SOC dropped below {MIN_OPERATING_SOC_PCT}% minimum operating limit."
        )
    elif final_soc_p90 < soc_reserve_pct:
        feasibility_status = FeasibilityStatus.LOW_RESERVE
        explanations.append(
            f"LOW RESERVE: Expected arrival SOC is {final_soc_p50:.1f}%, but under conservative P90 "
            f"conditions arrival SOC drops to {final_soc_p90:.1f}%, below {soc_reserve_pct:.0f}% safety reserve "
            f"(deficit: {abs(margin_kwh):.1f} kWh)."
        )
    elif has_unknown_elevation:
        feasibility_status = FeasibilityStatus.UNCERTAIN
        explanations.append("UNCERTAIN: Significant portion of route lacks verified digital elevation models.")
    elif infr_status == "HYPOTHETICAL":
        feasibility_status = FeasibilityStatus.CONDITIONAL_INFRASTRUCTURE_REQUIRED
        explanations.append("CONDITIONAL: Journey physically feasible only with hypothetical mid-route charging stops.")
    elif infr_status == "DEMO_SEED":
        feasibility_status = FeasibilityStatus.SIMULATED_WITH_DEMO_INFRASTRUCTURE
        explanations.append(
            f"FEASIBLE WITH DEMO INFRASTRUCTURE: Simulated feasible with {len(charging_results)} demonstration seed charger(s). "
            f"Live OCPP availability not verified."
        )
    else:
        feasibility_status = FeasibilityStatus.WILL_MAKE_IT
        explanations.append(
            f"WILL MAKE IT: Feasible journey. Final arrival SOC (P90) is {final_soc_p90:.1f}%, safely exceeding "
            f"the {soc_reserve_pct:.0f}% reserve requirement with +{margin_kwh:.1f} kWh buffer."
        )

    if was_derated:
        explanations.append(
            f"Thermal Notice: Battery pack reached {max_temp_c:.1f}°C during heavy load/charging, triggering dynamic BTMS cooling."
        )

    return MultiStopJourneySummary(
        total_distance_km=round(total_dist_km, 2),
        total_driving_duration_min=round(total_driving_time_s / 60.0, 1),
        total_charging_duration_min=round(total_charging_time_min, 1),
        total_journey_duration_min=round(total_journey_duration_min, 1),
        initial_soc_pct=round(soc_start_pct, 2),
        final_soc_p50_pct=round(final_soc_p50, 2),
        final_soc_p90_pct=round(final_soc_p90, 2),
        reserve_soc_pct=round(soc_reserve_pct, 2),
        feasibility_status=feasibility_status,
        is_energy_feasible=is_energy_feasible,
        all_chargers_reachable=all_chargers_reachable,
        infrastructure_status=infr_status,
        overall_confidence="MODEL_BASED_P90_ESTIMATE",
        feasibility_margin_kwh=round(margin_kwh, 2),
        total_traction_energy_kwh=round(total_tract_kwh, 3),
        total_regen_energy_kwh=round(total_regen_kwh, 3),
        total_aux_energy_kwh=round(total_aux_kwh, 3),
        total_btms_energy_kwh=round(total_btms_kwh, 3),
        total_charging_energy_added_kwh=round(total_charging_energy_batt_kwh, 3),
        total_charging_energy_grid_kwh=round(total_charging_energy_grid_kwh, 3),
        total_net_battery_kwh_p50=round(total_p50_net_kwh, 3),
        total_net_battery_kwh_p90=round(total_p90_net_kwh, 3),
        total_friction_dissipation_kwh=round(total_friction_kwh, 3),
        total_battery_internal_losses_kwh=round(total_battery_loss_kwh, 3),
        max_pack_temp_c=round(max_temp_c, 2),
        min_pack_temp_c=round(min_temp_c, 2),
        was_derated=was_derated,
        energy_residual_total_j=round(total_residual_j, 4),
        explanations=explanations,
        charging_events=charging_results,
        segment_telemetry=telemetry_list,
    )
