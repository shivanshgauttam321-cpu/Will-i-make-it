"""
Thermal Dynamics & Battery Thermal Management Subsystem (Stage C4)
===================================================================
High-fidelity lumped-parameter thermal modeling for EV battery packs.

Physics & Governing Equations:
------------------------------
1. Lumped Pack Energy Balance:
   C_th * (dT/dt) = Q_dot_gen - Q_dot_ambient - Q_dot_cool + Q_dot_heat

   where:
   - C_th: Bulk lumped heat capacity of the battery pack [J/K] = m_pack * c_p
   - Q_dot_gen: Total internal heat generation rate [W]
       = Q_dot_r0 + Q_dot_r1 + Q_dot_parasitic
       = (E_loss_r0 + E_loss_r1 + E_loss_parasitic) / dt
   - Q_dot_ambient: Convective / conductive ambient heat dissipation [W]
       = h_A * (T_pack - T_ambient)
   - Q_dot_cool: Active liquid / chiller cooling heat extraction [W]
   - Q_dot_heat: Active PTC pack heating heat injection [W]

2. Analytical Exponential Update:
   To ensure unconditional numerical stability across arbitrary timesteps dt:
     tau_th = C_th / h_A
     T_inf = T_ambient + (Q_dot_gen - Q_dot_cool + Q_dot_heat) / h_A
     T(t + dt) = T_inf + (T(t) - T_inf) * exp(-dt / tau_th)
   When h_A == 0:
     T(t + dt) = T(t) + (Q_dot_net / C_th) * dt

3. Active Battery Thermal Management System (BTMS):
   - Cooling mode: active when T_pack > target_cool_temp_c
       Q_dot_cool = min(max_cooling_power_w, k_cool * (T_pack - target_cool_temp_c))
       P_btms_elec_kw = (Q_dot_cool / cop_cooling) / 1000.0
   - Heating mode: active when T_pack < target_heat_temp_c
       Q_dot_heat = min(max_heating_power_w, k_heat * (target_heat_temp_c - T_pack))
       P_btms_elec_kw = (Q_dot_heat / cop_heating) / 1000.0

4. Thermal Derating:
   Continuous derating factor in [0.0, 1.0] applied to dynamic charge/discharge limits
   under extreme temperature conditions (hot >= 45°C, cold <= 5°C).
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from enum import Enum
from typing import List, Optional, Tuple
from pydantic import BaseModel, Field, model_validator

from app.domain.provenance import DataStatus
from app.services.energy.powertrain_model import _validate_finite_float


class BtmsMode(str, Enum):
    IDLE = "IDLE"
    COOLING = "COOLING"
    HEATING = "HEATING"


class ThermalDerateMode(str, Enum):
    NOMINAL = "NOMINAL"
    COLD_DERATED = "COLD_DERATED"
    HOT_DERATED = "HOT_DERATED"
    OVERHEAT_CRITICAL = "OVERHEAT_CRITICAL"


class ThermalConfig(BaseModel):
    """
    Configuration parameters for pack thermal dynamics and BTMS.
    """
    model_config = {"protected_namespaces": ()}

    # Pack physical thermal parameters
    pack_mass_kg: float = Field(default=350.0, gt=0.0, description="Mass of the battery pack in kg")
    specific_heat_j_per_kg_k: float = Field(
        default=900.0, gt=0.0, description="Specific heat capacity of pack materials [J/(kg*K)]"
    )
    heat_transfer_coeff_w_per_k: float = Field(
        default=12.0, ge=0.0, description="Enclosure ambient heat transfer conductance h*A [W/K]"
    )

    # Active BTMS cooling parameters
    enable_active_cooling: bool = Field(default=True, description="Enable active liquid/chiller cooling")
    target_cool_temp_c: float = Field(default=32.0, description="Temperature threshold to start active cooling [°C]")
    max_cooling_power_w: float = Field(default=3500.0, ge=0.0, description="Peak thermal heat rejection rate [W]")
    cooling_proportional_gain_w_per_k: float = Field(
        default=500.0, gt=0.0, description="Cooling rate per °C above target [W/K]"
    )
    cop_cooling: float = Field(default=3.0, gt=0.0, description="BTMS chiller Coefficient of Performance")

    # Active BTMS heating parameters
    enable_active_heating: bool = Field(default=True, description="Enable active PTC pack heating")
    target_heat_temp_c: float = Field(default=12.0, description="Temperature threshold to start active heating [°C]")
    max_heating_power_w: float = Field(default=2500.0, ge=0.0, description="Peak thermal heating input rate [W]")
    heating_proportional_gain_w_per_k: float = Field(
        default=400.0, gt=0.0, description="Heating rate per °C below target [W/K]"
    )
    cop_heating: float = Field(default=1.0, gt=0.0, description="PTC heater Coefficient of Performance")

    # Thermal derating boundaries
    temp_derate_hot_start_c: float = Field(default=45.0, description="Temperature where hot derating starts [°C]")
    temp_derate_hot_cutoff_c: float = Field(default=55.0, description="Temperature where power is cut to zero [°C]")
    temp_derate_cold_start_c: float = Field(default=5.0, description="Temperature where cold derating starts [°C]")
    temp_derate_cold_cutoff_c: float = Field(default=-15.0, description="Temperature where cold power is clamped [°C]")
    min_cold_derate_fraction: float = Field(default=0.15, ge=0.0, le=1.0, description="Minimum cold power fraction")

    # Provenance
    status: DataStatus = Field(default=DataStatus.ESTIMATED, description="Provenance status of thermal parameters")

    @property
    def lumped_heat_capacity_j_per_k(self) -> float:
        """Total bulk heat capacity C_th [J/K]."""
        return self.pack_mass_kg * self.specific_heat_j_per_kg_k

    @model_validator(mode="after")
    def validate_thermal_bounds(self) -> ThermalConfig:
        if self.target_heat_temp_c >= self.target_cool_temp_c:
            raise ValueError("target_heat_temp_c must be strictly less than target_cool_temp_c")
        if self.temp_derate_hot_start_c >= self.temp_derate_hot_cutoff_c:
            raise ValueError("temp_derate_hot_start_c must be strictly less than temp_derate_hot_cutoff_c")
        if self.temp_derate_cold_cutoff_c >= self.temp_derate_cold_start_c:
            raise ValueError("temp_derate_cold_cutoff_c must be strictly less than temp_derate_cold_start_c")
        return self


@dataclass(frozen=True)
class ThermalState:
    """
    Thermal state of the battery pack.
    """
    temperature_c: float
    btms_mode: BtmsMode = BtmsMode.IDLE
    derate_mode: ThermalDerateMode = ThermalDerateMode.NOMINAL
    status: DataStatus = DataStatus.ESTIMATED

    def __post_init__(self):
        if not math.isfinite(self.temperature_c) or not (-60.0 <= self.temperature_c <= 95.0):
            raise ValueError(f"ThermalState temperature_c must be finite in [-60.0, 95.0], got {self.temperature_c}")


@dataclass(frozen=True)
class ThermalStepResult:
    """
    Detailed result of one thermal simulation timestep.
    """
    initial_temperature_c: float
    final_temperature_c: float
    ambient_temperature_c: float
    dt_s: float
    q_gen_w: float
    q_ambient_w: float
    q_cool_w: float
    q_heat_w: float
    q_net_w: float
    p_btms_electrical_kw: float
    derate_factor: float
    btms_mode: BtmsMode
    derate_mode: ThermalDerateMode
    status: DataStatus
    notes: List[str] = field(default_factory=list)


def compute_thermal_derating(temperature_c: float, config: ThermalConfig) -> Tuple[float, ThermalDerateMode]:
    """
    Compute continuous thermal derating multiplier in [0.0, 1.0] and mode based on pack temperature.
    
    - Normal range [cold_start, hot_start]: 1.0, NOMINAL
    - Hot derating (hot_start to hot_cutoff): linearly scales from 1.0 to 0.0, HOT_DERATED
    - Critical hot (>= hot_cutoff): 0.0, OVERHEAT_CRITICAL
    - Cold derating (cold_cutoff to cold_start): linearly scales from min_fraction to 1.0, COLD_DERATED
    """
    t = _validate_finite_float("temperature_c", temperature_c, min_val=-60.0, max_val=95.0)

    # Hot derating
    if t >= config.temp_derate_hot_cutoff_c:
        return 0.0, ThermalDerateMode.OVERHEAT_CRITICAL
    elif t > config.temp_derate_hot_start_c:
        span = config.temp_derate_hot_cutoff_c - config.temp_derate_hot_start_c
        factor = max(0.0, min(1.0, 1.0 - (t - config.temp_derate_hot_start_c) / span))
        return factor, ThermalDerateMode.HOT_DERATED

    # Cold derating
    if t <= config.temp_derate_cold_cutoff_c:
        return config.min_cold_derate_fraction, ThermalDerateMode.COLD_DERATED
    elif t < config.temp_derate_cold_start_c:
        span = config.temp_derate_cold_start_c - config.temp_derate_cold_cutoff_c
        fraction = (t - config.temp_derate_cold_cutoff_c) / span
        factor = config.min_cold_derate_fraction + fraction * (1.0 - config.min_cold_derate_fraction)
        return factor, ThermalDerateMode.COLD_DERATED

    return 1.0, ThermalDerateMode.NOMINAL


def simulate_thermal_step(
    state: ThermalState,
    q_gen_w: float,
    ambient_temp_c: float,
    dt_s: float,
    config: ThermalConfig,
) -> Tuple[ThermalState, ThermalStepResult]:
    """
    Simulate one thermal timestep on the lumped battery pack.
    """
    dt = _validate_finite_float("dt_s", dt_s, min_val=1e-6)
    q_gen = _validate_finite_float("q_gen_w", q_gen_w, min_val=0.0)
    t_amb = _validate_finite_float("ambient_temp_c", ambient_temp_c, min_val=-60.0, max_val=70.0)
    t_init = state.temperature_c

    notes: List[str] = []

    # 1. Determine active BTMS cooling or heating
    q_cool_w = 0.0
    q_heat_w = 0.0
    p_btms_elec_kw = 0.0
    btms_mode = BtmsMode.IDLE

    if config.enable_active_cooling and t_init > config.target_cool_temp_c:
        excess = t_init - config.target_cool_temp_c
        q_cool_w = min(config.max_cooling_power_w, config.cooling_proportional_gain_w_per_k * excess)
        p_btms_elec_kw = (q_cool_w / config.cop_cooling) / 1000.0
        btms_mode = BtmsMode.COOLING
        notes.append(f"BTMS cooling active: extracting {q_cool_w:.1f} W ({p_btms_elec_kw:.3f} kW elec)")
    elif config.enable_active_heating and t_init < config.target_heat_temp_c:
        deficit = config.target_heat_temp_c - t_init
        q_heat_w = min(config.max_heating_power_w, config.heating_proportional_gain_w_per_k * deficit)
        p_btms_elec_kw = (q_heat_w / config.cop_heating) / 1000.0
        btms_mode = BtmsMode.HEATING
        notes.append(f"BTMS heating active: injecting {q_heat_w:.1f} W ({p_btms_elec_kw:.3f} kW elec)")

    # 2. Convective / ambient heat transfer conductance
    h_a = config.heat_transfer_coeff_w_per_k
    c_th = config.lumped_heat_capacity_j_per_k

    q_internal_net = q_gen - q_cool_w + q_heat_w

    if h_a > 1e-9:
        tau_th = c_th / h_a
        t_infinity = t_amb + (q_internal_net / h_a)
        decay = math.exp(-dt / tau_th)
        t_final = t_infinity + (t_init - t_infinity) * decay
        q_amb_avg_w = h_a * ((t_infinity - t_amb) + (t_init - t_infinity) * (tau_th / dt) * (1.0 - decay))
    else:
        dt_c = (q_internal_net / c_th) * dt
        t_final = t_init + dt_c
        q_amb_avg_w = 0.0

    q_net_w = q_gen - q_amb_avg_w - q_cool_w + q_heat_w

    # 3. Thermal derating calculation
    derate_factor, derate_mode = compute_thermal_derating(t_final, config)
    if derate_mode == ThermalDerateMode.OVERHEAT_CRITICAL:
        notes.append("CRITICAL: Pack temperature exceeds hot cutoff threshold")
    elif derate_mode == ThermalDerateMode.HOT_DERATED:
        notes.append(f"Hot derating active: power factor = {derate_factor:.2f}")
    elif derate_mode == ThermalDerateMode.COLD_DERATED:
        notes.append(f"Cold derating active: power factor = {derate_factor:.2f}")

    new_state = ThermalState(
        temperature_c=t_final,
        btms_mode=btms_mode,
        derate_mode=derate_mode,
        status=config.status,
    )

    result = ThermalStepResult(
        initial_temperature_c=t_init,
        final_temperature_c=t_final,
        ambient_temperature_c=t_amb,
        dt_s=dt,
        q_gen_w=q_gen,
        q_ambient_w=q_amb_avg_w,
        q_cool_w=q_cool_w,
        q_heat_w=q_heat_w,
        q_net_w=q_net_w,
        p_btms_electrical_kw=p_btms_elec_kw,
        derate_factor=derate_factor,
        btms_mode=btms_mode,
        derate_mode=derate_mode,
        status=config.status,
        notes=notes,
    )

    return new_state, result
