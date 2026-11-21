"""
Regenerative Braking & Inverter Electrical Acceptance Subsystem (Stage C2.1)
=============================================================================
Calculates physically consistent regenerative braking capability, inverter AC/DC
conversion, BMS charging acceptance, auxiliary load power balance, and blended
friction braking with exact 6-boundary energy conservation and provenance tracking.

PHYSICAL CONVENTIONS (FROZEN & REFINED FOR C2.1)
------------------------------------------------
1. Mechanical Power:
   - Positive wheel/motor power = traction (> 0).
   - Negative wheel/motor shaft power = regenerative braking (<= 0).
   - Mechanical and drivetrain losses are strictly non-negative (P_loss >= 0).

2. Battery Electrical Power:
   - Positive battery current = charging (I_batt > 0).
   - Negative battery current = discharging (I_batt < 0).
   - Battery terminal power is positive during charging (P_batt > 0)
     and negative during discharge (P_batt < 0).

3. Power Boundaries & Signed Ledger:
   Boundary 1: Wheel Mechanical Braking Power:
       P_wheel,req = (F_brake_req * v) / 1000  [kW]  (>= 0 magnitude)
       P_wheel,delivered = (F_delivered_total * v) / 1000  [kW]
       P_wheel,regen = (F_regen_accepted * v) / 1000  [kW]
       P_friction,delivered = (F_friction_delivered * v) / 1000  [kW]
       P_deficit = P_wheel,req - P_wheel,delivered  [kW]  (>= 0 undelivered)

   Boundary 2: Drivetrain Reverse Transformation:
       P_shaft = -P_wheel,regen * eta_gb_rev  [kW]  (Signed <= 0)
       P_loss_gb = P_wheel,regen * (1 - eta_gb_rev)  [kW]  (Loss >= 0)
       T_mot_regen = (F_regen_accepted * r_wheel * eta_gb_rev) / N_gb  [Nm]

   Boundary 3: Motor Stator AC Electrical Generation:
       P_mot_ac = P_shaft * eta_mot_gen  [kW]  (Signed <= 0)
       P_loss_mot = -P_shaft * (1 - eta_mot_gen)  [kW]  (Loss >= 0)
       I_stator_rms = T_mot_regen / k_t_rms  [A_rms]  (Checked against I_inverter_limit_rms)

   Boundary 4: Inverter DC Electrical Conversion & Standby:
       P_inv_dc_gross = -P_mot_ac * eta_inv_regen  [kW]  (Gross bridge generation >= 0)
       P_loss_inv_conv = -P_mot_ac * (1 - eta_inv_regen)  [kW]  (Rectification loss >= 0)
       P_standby_kw = standby_loss_w / 1000.0  [kW]  (Standby consumption >= 0)
       P_inv_dc_net = P_inv_dc_gross - P_standby_kw  [kW]  (Net fed to HV bus; can be < 0)
       P_loss_inv_total = P_loss_inv_conv + P_standby_kw  [kW]
       I_gross = P_inv_dc_gross * 1000 / V_nominal  [A]  (Compared against inverter DC current rating)
       I_net = P_inv_dc_net * 1000 / V_nominal  [A]      (Signed current transferred to HV bus)

   Boundary 5: HV Bus, Auxiliaries & Net Battery Request (Interface to C3):
       P_aux_HV = P_aux_LV / eta_dc_dc  [kW]  (>= 0 drawn)
       P_loss_dc_dc = P_aux_HV - P_aux_LV  [kW]  (Loss >= 0)
       P_batt_chg_net = P_inv_dc_net - P_aux_HV
                      = P_inv_dc_gross - P_standby_kw - P_aux_HV  [kW]
       (Signed: > 0 = charging battery, < 0 = discharging battery to cover loads)

   Boundary 6: Electrochemical Battery Stored Energy (Handled in Stage C3).

4. Conservation of Delivered Energy (Zero-Residual Invariant):
   The physical energy balance reconciles physically delivered quantities:
       P_wheel,delivered = P_friction,delivered + P_batt_chg_net + P_standby_kw + P_aux_HV
                           + P_loss_inv_conv + P_loss_mot + P_loss_gb
   Residual is strictly validated symmetrically: abs(energy_residual_kw) < 1e-5.
   Undelivered demand is reported explicitly as P_deficit.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import math
from typing import List, Optional, Tuple, Union
from pydantic import BaseModel, Field, field_validator, model_validator

from app.domain.provenance import DataStatus
from app.services.energy.powertrain_model import (
    ConstraintStatus,
    GearboxConfig,
    MotorConfig,
    OperatingEnvelopeMode,
    combine_provenance,
    compute_motor_speed,
    compute_motor_envelope,
    compute_stator_phase_current,
    _validate_finite_float,
)


# =============================================================================
# Configuration Models
# =============================================================================

class InverterElectricalConfig(BaseModel):
    """
    Inverter electrical ratings and AC/DC conversion configuration.
    
    Attributes:
        dc_voltage_nominal_v: Nominal DC bus voltage in Volts.
        dc_voltage_max_v: Maximum allowable DC bus voltage in Volts.
        dc_voltage_min_v: Minimum operating DC bus voltage in Volts.
        dc_current_limit_a: Maximum continuous inverter DC bridge output current in Amperes.
        dc_power_limit_kw: Maximum allowable gross DC power generation at inverter bridge in kW.
        efficiency_regen: Inverter AC-to-DC rectification efficiency (0 < eta <= 1.0).
        standby_loss_w: Inverter standby and switching electrical loss in Watts.
        dc_dc_efficiency: Efficiency of HV-to-LV DC-DC converter for auxiliary loads.
        dc_dc_efficiency_status: Provenance status of DC-DC converter efficiency parameter.
        status: Provenance status of inverter electrical parameters.
    """
    model_config = {"protected_namespaces": ()}

    dc_voltage_nominal_v: Optional[float] = Field(default=350.0, gt=50.0, le=1000.0, description="Nominal DC bus voltage (V)")
    dc_voltage_max_v: Optional[float] = Field(default=420.0, gt=50.0, le=1200.0, description="Maximum DC bus voltage (V)")
    dc_voltage_min_v: Optional[float] = Field(default=250.0, gt=20.0, le=800.0, description="Minimum DC bus voltage (V)")

    dc_current_limit_a: Optional[float] = Field(default=250.0, gt=0.0, le=2000.0, description="Max inverter DC bridge current limit (A)")
    dc_power_limit_kw: Optional[float] = Field(default=65.0, gt=0.0, le=1000.0, description="Max gross inverter DC power limit (kW)")

    efficiency_regen: float = Field(default=0.95, gt=0.50, le=1.0, description="Inverter rectification efficiency")
    standby_loss_w: float = Field(default=0.0, ge=0.0, le=10000.0, description="Inverter standby/switching loss (W)")
    dc_dc_efficiency: float = Field(default=0.92, gt=0.50, le=1.0, description="HV-to-LV DC-DC converter efficiency")
    dc_dc_efficiency_status: DataStatus = Field(default=DataStatus.ESTIMATED, description="DC-DC efficiency provenance status")

    status: DataStatus = Field(default=DataStatus.ESTIMATED, description="Provenance status of inverter electrical parameters")

    @field_validator("efficiency_regen", "dc_dc_efficiency")
    @classmethod
    def validate_efficiencies(cls, v: float) -> float:
        if not math.isfinite(v):
            raise ValueError("Efficiency must be a finite float")
        return v


class BMSConfig(BaseModel):
    """
    Battery Management System (BMS) charging acceptance limits and derating configuration.
    
    Attributes:
        max_charge_power_kw: Maximum continuous battery pack charging power in kW (None = unknown).
        max_charge_current_a: Maximum continuous battery pack charging current in Amperes (None = unknown).
        pack_nominal_voltage_v: Nominal battery pack voltage in Volts.
        cell_max_voltage_v: Maximum allowable cell terminal voltage in Volts.
        soc_taper_start: SOC (0.0 - 1.0) above which charging power derating begins.
        soc_cutoff: SOC (0.0 - 1.0) at which charging power drops to zero.
        temp_optimal_low_c: Lower ambient/cell temperature bound for 100% acceptance (°C).
        temp_optimal_high_c: Upper ambient/cell temperature bound for 100% acceptance (°C).
        temp_cold_cutoff_c: Minimum temperature below which charging is prohibited (°C).
        temp_hot_cutoff_c: Maximum temperature above which charging is prohibited (°C).
        status: Provenance status of BMS parameters.
    """
    model_config = {"protected_namespaces": ()}

    max_charge_power_kw: Optional[float] = Field(default=65.0, gt=0.0, le=500.0, description="Peak pack charge power acceptance (kW)")
    max_charge_current_a: Optional[float] = Field(default=200.0, gt=0.0, le=1000.0, description="Peak pack charge current acceptance (A)")
    pack_nominal_voltage_v: Optional[float] = Field(default=350.0, gt=50.0, le=1000.0, description="Nominal battery pack voltage (V)")
    cell_max_voltage_v: Optional[float] = Field(default=4.20, gt=2.0, le=5.0, description="Cell maximum terminal voltage (V)")

    soc_taper_start: float = Field(default=0.80, ge=0.50, lt=1.0, description="SOC where charge power taper begins")
    soc_cutoff: float = Field(default=0.98, gt=0.80, le=1.0, description="SOC where charge power reaches zero")

    temp_optimal_low_c: float = Field(default=15.0, ge=-20.0, le=40.0, description="Lower optimal temp bound (°C)")
    temp_optimal_high_c: float = Field(default=35.0, ge=20.0, le=60.0, description="Upper optimal temp bound (°C)")
    temp_cold_cutoff_c: float = Field(default=-10.0, ge=-40.0, le=10.0, description="Cold cutoff temperature (°C)")
    temp_hot_cutoff_c: float = Field(default=50.0, ge=35.0, le=80.0, description="Hot cutoff temperature (°C)")

    status: DataStatus = Field(default=DataStatus.ESTIMATED, description="Provenance status of BMS parameters")

    @model_validator(mode="after")
    def validate_bms_ranges(self) -> BMSConfig:
        if self.soc_taper_start >= self.soc_cutoff:
            raise ValueError(f"soc_taper_start ({self.soc_taper_start}) must be < soc_cutoff ({self.soc_cutoff})")
        if self.temp_cold_cutoff_c >= self.temp_optimal_low_c:
            raise ValueError("temp_cold_cutoff_c must be < temp_optimal_low_c")
        if self.temp_optimal_low_c >= self.temp_optimal_high_c:
            raise ValueError("temp_optimal_low_c must be < temp_optimal_high_c")
        if self.temp_optimal_high_c >= self.temp_hot_cutoff_c:
            raise ValueError("temp_optimal_high_c must be < temp_hot_cutoff_c")
        return self


class BrakeBlendingConfig(BaseModel):
    """
    Brake blending and chassis retarding configuration.
    
    Attributes:
        v_cutoff_ms: Speed below which regenerative braking is fully disabled (m/s).
                     Provisional vehicle-dependent calibration parameter.
        v_blend_start_ms: Speed below which regenerative braking begins tapering (m/s).
                           Provisional vehicle-dependent calibration parameter.
        friction_brake_max_force_n: Maximum total friction braking force capacity in Newtons.
        default_adhesion_coefficient: Optional verified aggregate tire-road friction coefficient mu.
        status: Provenance status of brake blending parameters.
    """
    model_config = {"protected_namespaces": ()}

    v_cutoff_ms: float = Field(default=1.0, ge=0.0, le=5.0, description="Full regen cutoff speed (m/s)")
    v_blend_start_ms: float = Field(default=3.0, gt=0.0, le=10.0, description="Regen rolloff start speed (m/s)")
    friction_brake_max_force_n: Optional[float] = Field(default=15000.0, gt=500.0, le=100000.0, description="Max friction brake force (N)")
    default_adhesion_coefficient: Optional[float] = Field(default=None, gt=0.0, le=2.5, description="Aggregate tire-road friction coefficient mu")

    status: DataStatus = Field(default=DataStatus.ESTIMATED, description="Provenance status of brake blending parameters")

    @model_validator(mode="after")
    def validate_speeds(self) -> BrakeBlendingConfig:
        if self.v_cutoff_ms >= self.v_blend_start_ms:
            raise ValueError(f"v_cutoff_ms ({self.v_cutoff_ms}) must be < v_blend_start_ms ({self.v_blend_start_ms})")
        return self


# =============================================================================
# Result Dataclasses (Typed Interfaces for C3 and C4)
# =============================================================================

@dataclass(frozen=True)
class BMSAcceptanceResult:
    """
    BMS charge acceptance evaluation result.
    
    Exposes admissible power/current and limit certainty independently to Stage C3 (Thevenin solver).
    Separates power-limit availability, current-limit availability, and overall acceptance status.
    """
    admissible_charge_power_kw: Optional[float]  # None if BMS max charge power is unknown
    admissible_charge_current_a: Optional[float] # None if BMS max charge current is unknown
    is_power_limit_known: bool                   # True if verified max charge power limit exists
    is_current_limit_known: bool                 # True if verified max charge current limit exists
    is_limit_known: bool                         # True if both power and current limits are known
    soc_derate_factor: float
    temp_derate_factor: float
    soh_derate_factor: float
    is_soc_derated: bool
    is_temp_derated: bool
    is_soh_derated: bool
    status: ConstraintStatus
    provenance_status: DataStatus
    notes: str


@dataclass(frozen=True)
class AuxiliaryHVResult:
    """HV-bus auxiliary load demand converted through DC-DC efficiency."""
    aux_lv_power_kw: float
    aux_hv_power_kw: float
    dc_dc_loss_kw: float
    status: DataStatus


@dataclass(frozen=True)
class BrakeBlendingResult:
    """
    Complete regenerative and friction brake blending result across all physical boundaries.
    
    Serves as the frozen typed interface contract for Stage C3 (Thevenin model)
    and Stage C4 (Heun/RK2 trajectory integrator).
    """
    # Boundary 1: Wheel Mechanical Demand & Delivery
    requested_brake_force_n: float            # Demanded total braking force magnitude (>= 0) [N]
    requested_brake_power_kw: float           # Demanded total braking power magnitude (>= 0) [kW]
    vehicle_speed_ms: float                   # Instantaneous vehicle velocity [m/s]
    delivered_brake_force_n: float            # Total actual braking force delivered at wheels [N]
    delivered_brake_power_kw: float           # Total actual mechanical braking power delivered [kW]
    braking_deficit_force_n: float            # Unmet braking force demand, if any [N]
    braking_deficit_power_kw: float           # Unmet braking power demand, if any [kW]

    # Regenerative & Friction Split
    accepted_regen_wheel_force_n: float       # Retarding force delivered by electric motor [N]
    accepted_regen_wheel_power_kw: float      # Signed mechanical wheel power absorbed by regen (<= 0) [kW]
    friction_brake_force_n: float             # Force assigned to mechanical friction brakes (>= 0) [N]
    friction_brake_power_kw: float            # Power dissipated in friction brakes (>= 0) [kW]

    # Boundary 2: Motor Shaft Mechanical Power
    motor_shaft_power_kw: float               # Signed power entering motor rotor shaft (<= 0) [kW]
    motor_torque_regen_nm: float              # Regenerative motor retarding torque magnitude (>= 0) [Nm]
    motor_speed_rad_s: float                  # Motor rotor angular velocity [rad/s]
    gearbox_loss_kw: float                    # Mechanical friction loss in gearbox (>= 0) [kW]

    # Boundary 3: Motor Stator AC Electrical Power
    motor_electrical_power_kw: float          # Signed AC generation power out of stator (<= 0) [kW]
    motor_loss_kw: float                      # Stator copper and iron losses during generation (>= 0) [kW]
    stator_current_rms_a: Optional[float]     # Required stator phase current [A_rms]
    stator_current_limit_rms_a: Optional[float]# Inverter AC phase current limit [A_rms]
    stator_current_status: ConstraintStatus   # AC stator current constraint satisfaction status

    # Boundary 4: Inverter DC Electrical Power & Standby
    inverter_dc_power_gross_kw: float         # Gross DC power generated by inverter rectification (>= 0) [kW]
    inverter_dc_power_net_kw: float           # Net DC power fed onto HV bus after standby loss (can be < 0) [kW]
    inverter_dc_current_gross_a: Optional[float] # Gross DC bridge current at nominal voltage [A] (checked vs rating)
    inverter_dc_current_net_a: Optional[float]   # Signed net DC current fed to HV bus [A] (HV bus accounting)
    inverter_dc_current_a: Optional[float]    # Backward-compatible alias for net inverter DC current [A]
    inverter_dc_current_limit_a: Optional[float]# Inverter DC bridge current limit [A]
    is_provisional_voltage_based: bool        # True if DC current is based on nominal voltage estimate
    inverter_standby_kw: float                # Inverter standby/switching consumption (>= 0) [kW]
    inverter_loss_conv_kw: float              # Inverter rectification conversion loss (>= 0) [kW]
    inverter_loss_kw: float                   # Total inverter losses: conv + standby (>= 0) [kW]

    # Boundary 5: HV Bus, Auxiliaries & Net Battery Request (Interface to C3)
    auxiliary_lv_power_kw: float              # Low-voltage auxiliary load [kW]
    auxiliary_hv_power_kw: float              # High-voltage auxiliary electrical load [kW]
    dc_dc_loss_kw: float                      # DC-DC conversion heat loss [kW]
    net_battery_charging_kw: float            # Net electrical power directed into battery (> 0 chg, < 0 dis) [kW]
    bms_admissible_power_kw: Optional[float]  # Maximum power BMS accepts (None if unconfigured) [kW]
    bms_admissible_current_a: Optional[float] # Maximum current BMS accepts (None if unconfigured) [A]
    is_bms_power_limit_known: bool            # True if BMS power acceptance limit is known
    is_bms_current_limit_known: bool          # True if BMS current acceptance limit is known
    is_bms_limit_known: bool                  # True if overall BMS acceptance limits are known (both power & current)

    # Energy Conservation Ledger Residual
    energy_residual_kw: float                 # Verification residual across delivered quantities [kW]

    # Low-speed & Curtailment Diagnostics
    low_speed_factor: float                   # Low-speed regen rolloff factor in [0.0, 1.0]
    is_regen_curtailed: bool                  # True if regen was throttled below available mechanical demand
    curtailment_reason: Optional[str]         # Primary reason for curtailment

    # Adhesion & Hardware Constraints
    adhesion_limit_force_n: Optional[float]   # Aggregate tire slip force ceiling [N]
    adhesion_status: ConstraintStatus         # Aggregate tire-road adhesion constraint status

    # Synthesis & Quality
    overall_status: ConstraintStatus          # SATISFIED, CONDITIONAL, or VIOLATED
    diagnostic_code: Optional[str]            # Primary diagnostic identifier
    active_constraints: List[str] = field(default_factory=list) # All simultaneously active/limiting constraints
    provenance_status: DataStatus = DataStatus.ESTIMATED        # Combined provenance status
    notes: List[str] = field(default_factory=list)              # Traceable engineering notes


# =============================================================================
# Core Calculation Functions
# =============================================================================

def compute_low_speed_regen_factor(
    vehicle_speed_ms: float,
    config: BrakeBlendingConfig,
) -> float:
    """
    Compute smooth low-speed regenerative braking rolloff derate factor in [0.0, 1.0].
    
    NOTE: v_cutoff_ms and v_blend_start_ms are provisional vehicle-dependent calibration
    parameters, NOT universal motor characteristics.
    
    At standstill (v = 0), returns strictly 0.0 with zero division risk.
    For v <= v_cutoff_ms, returns strictly 0.0 (back-EMF insufficient for boost).
    For v >= v_blend_start_ms, returns 1.0 (full regen capability).
    In between, applies a smooth continuous linear taper.
    """
    v = _validate_finite_float("vehicle_speed_ms", vehicle_speed_ms, min_val=0.0)
    if v <= config.v_cutoff_ms:
        return 0.0
    if v >= config.v_blend_start_ms:
        return 1.0
    return (v - config.v_cutoff_ms) / (config.v_blend_start_ms - config.v_cutoff_ms)


def compute_auxiliary_hv_power(
    aux_lv_power_kw: float,
    dc_dc_efficiency: float = 0.92,
    dc_dc_efficiency_status: Optional[DataStatus] = None,
    input_status: Optional[DataStatus] = None,
) -> AuxiliaryHVResult:
    """
    Convert low-voltage auxiliary power demand to high-voltage bus electrical load.
    
    Formula:
        P_aux_HV = P_aux_LV / eta_DC_DC  [kW]
        P_loss_dc_dc = P_aux_HV - P_aux_LV  [kW]
        
    Provenance is conservatively combined from input_status and dc_dc_efficiency_status.
    Does NOT infer REAL provenance from numeric values.
    """
    p_lv = _validate_finite_float("aux_lv_power_kw", aux_lv_power_kw, min_val=0.0)
    eta = _validate_finite_float("dc_dc_efficiency", dc_dc_efficiency, min_val=0.50, max_val=1.0)

    p_hv = p_lv / eta
    p_loss = p_hv - p_lv

    eff_status = dc_dc_efficiency_status or DataStatus.ESTIMATED
    status = combine_provenance(input_status, eff_status)

    return AuxiliaryHVResult(
        aux_lv_power_kw=p_lv,
        aux_hv_power_kw=p_hv,
        dc_dc_loss_kw=p_loss,
        status=status,
    )


def compute_bms_acceptance(
    battery_soc: float,
    battery_temp_c: float,
    config: BMSConfig,
    state_of_health: Optional[float] = None,
    input_status: Optional[DataStatus] = None,
    soc_status: Optional[DataStatus] = None,
    temp_status: Optional[DataStatus] = None,
    soh_status: Optional[DataStatus] = None,
) -> BMSAcceptanceResult:
    """
    Evaluate BMS charging power and current acceptance limits under instantaneous
    SOC, cell temperature, and SOH deratings.
    
    Physics & Derating Rules:
    1. SOC Derating:
       - For SOC <= soc_taper_start: factor = 1.0.
       - For SOC >= soc_cutoff: factor = 0.0.
       - In between: linear taper f_soc = (soc_cutoff - SOC) / (soc_cutoff - soc_taper_start).
    2. Temperature Derating:
       - For temp in [temp_optimal_low_c, temp_optimal_high_c]: factor = 1.0.
       - For temp <= temp_cold_cutoff_c: factor = 0.0 (prevent lithium plating).
       - For temp >= temp_hot_cutoff_c: factor = 0.0 (prevent thermal runaway).
       - In between: linear ramp from cutoff to optimal bound.
    3. State of Health Derating:
       - If SOH provided, derate acceptance linearly by clamp(SOH, 0.0, 1.0).
    4. Admissible Power:
       P_admissible = P_max * f_soc * f_temp * f_soh (if P_max configured; else None)
    5. Admissible Current:
       I_admissible = I_max * f_soc * f_temp * f_soh (if I_max configured; else None)
       
    Hardware Acceptance Certainty:
       Separates power-limit availability and current-limit availability.
       is_limit_known is True ONLY when both power and current limits are configured.
    """
    soc = _validate_finite_float("battery_soc", battery_soc, min_val=0.0, max_val=1.0)
    temp = _validate_finite_float("battery_temp_c", battery_temp_c, min_val=-60.0, max_val=90.0)

    # 1. SOC Derate Factor
    if soc <= config.soc_taper_start:
        f_soc = 1.0
    elif soc >= config.soc_cutoff:
        f_soc = 0.0
    else:
        f_soc = (config.soc_cutoff - soc) / (config.soc_cutoff - config.soc_taper_start)
    f_soc = max(0.0, min(1.0, f_soc))
    is_soc_derated = (f_soc < 0.999)

    # 2. Temperature Derate Factor
    if temp < config.temp_optimal_low_c:
        if temp <= config.temp_cold_cutoff_c:
            f_temp = 0.0
        else:
            f_temp = (temp - config.temp_cold_cutoff_c) / (config.temp_optimal_low_c - config.temp_cold_cutoff_c)
    elif temp > config.temp_optimal_high_c:
        if temp >= config.temp_hot_cutoff_c:
            f_temp = 0.0
        else:
            f_temp = (config.temp_hot_cutoff_c - temp) / (config.temp_hot_cutoff_c - config.temp_optimal_high_c)
    else:
        f_temp = 1.0
    f_temp = max(0.0, min(1.0, f_temp))
    is_temp_derated = (f_temp < 0.999)

    # 3. SOH Derate Factor
    if state_of_health is not None:
        soh = _validate_finite_float("state_of_health", state_of_health, min_val=0.0, max_val=1.0)
        f_soh = max(0.0, min(1.0, soh))
        is_soh_derated = (f_soh < 0.999)
    else:
        f_soh = 1.0
        is_soh_derated = False

    combined_factor = f_soc * f_temp * f_soh

    # 4. Admissible Power Calculation
    is_power_limit_known = (config.max_charge_power_kw is not None)
    if is_power_limit_known:
        p_admissible = config.max_charge_power_kw * combined_factor
    else:
        p_admissible = None

    # 5. Admissible Current Calculation
    is_current_limit_known = (config.max_charge_current_a is not None)
    if is_current_limit_known:
        i_admissible = config.max_charge_current_a * combined_factor
        if config.pack_nominal_voltage_v is not None and p_admissible is not None:
            p_from_i = (i_admissible * config.pack_nominal_voltage_v) / 1000.0
            p_admissible = min(p_admissible, p_from_i)
    else:
        i_admissible = None

    is_limit_known = is_power_limit_known and is_current_limit_known

    # Status synthesis
    if not is_power_limit_known or not is_current_limit_known:
        c_status = ConstraintStatus.CONDITIONAL
        missing_parts = []
        if not is_power_limit_known:
            missing_parts.append("charge power")
        if not is_current_limit_known:
            missing_parts.append("charge current")
        notes = f"BMS max {' and '.join(missing_parts)} limit unconfigured; battery acceptance unverified"
    elif config.status != DataStatus.REAL or (input_status is not None and input_status != DataStatus.REAL):
        c_status = ConstraintStatus.CONDITIONAL
        notes = "BMS charging acceptance evaluated conditionally under estimated/unverified inputs"
    else:
        c_status = ConstraintStatus.SATISFIED
        notes = "BMS charging acceptance verified against hardware envelope"

    prov_status = combine_provenance(input_status, soc_status, temp_status, soh_status, config.status)

    return BMSAcceptanceResult(
        admissible_charge_power_kw=p_admissible,
        admissible_charge_current_a=i_admissible,
        is_power_limit_known=is_power_limit_known,
        is_current_limit_known=is_current_limit_known,
        is_limit_known=is_limit_known,
        soc_derate_factor=f_soc,
        temp_derate_factor=f_temp,
        soh_derate_factor=f_soh,
        is_soc_derated=is_soc_derated,
        is_temp_derated=is_temp_derated,
        is_soh_derated=is_soh_derated,
        status=c_status,
        provenance_status=prov_status,
        notes=notes,
    )


def blend_regenerative_and_friction_braking(
    requested_brake_force_n: float,
    vehicle_speed_ms: float,
    motor_config: MotorConfig,
    gearbox_config: GearboxConfig,
    inverter_config: InverterElectricalConfig,
    bms_config: BMSConfig,
    blending_config: Optional[BrakeBlendingConfig] = None,
    battery_soc: float = 0.50,
    battery_temp_c: float = 25.0,
    state_of_health: Optional[float] = None,
    aux_lv_power_kw: float = 0.30,
    normal_force_n: Optional[float] = None,
    adhesion_coefficient: Optional[float] = None,
    envelope_mode: OperatingEnvelopeMode = OperatingEnvelopeMode.CONTINUOUS,
    input_status: Optional[DataStatus] = None,
    soc_status: Optional[DataStatus] = None,
    temp_status: Optional[DataStatus] = None,
    soh_status: Optional[DataStatus] = None,
    aux_status: Optional[DataStatus] = None,
    adhesion_input_status: Optional[DataStatus] = None,
) -> BrakeBlendingResult:
    """
    Deterministic regenerative and friction brake blending across all physical boundaries.
    
    Evaluation Sequence:
    1. Validate requested wheel braking force and vehicle speed.
    2. Compute motor rotational speed and low-speed rolloff factor.
    3. Evaluate motor continuous (S1) or peak (S2) regenerative torque/power capability.
    4. Evaluate AC stator phase current constraint vs inverter phase current limit.
    5. Evaluate BMS charging acceptance (SOC, temperature, SOH deratings).
    6. Evaluate HV-side auxiliary load demand and DC-DC conversion losses.
    7. Determine gross and net electrical DC acceptance at the inverter bridge.
    8. Back-propagate electrical acceptance to motor shaft and wheel force.
    9. Arbitrate accepted regenerative retarding force and assign remaining force to friction brakes.
    10. Enforce friction brake hardware capacity and report undelivered braking deficits.
    11. Enforce aggregate vehicle-level tire-road adhesion limits on delivered retarding force.
    12. Execute exact 6-boundary energy conservation ledger on delivered quantities.
    13. Synthesize diagnostic codes, constraint statuses, active constraints, and input provenance.
    """
    cfg_blend = blending_config or BrakeBlendingConfig()

    f_req = _validate_finite_float("requested_brake_force_n", requested_brake_force_n, min_val=0.0, max_val=100000.0)
    v = _validate_finite_float("vehicle_speed_ms", vehicle_speed_ms, min_val=0.0, max_val=150.0)

    # Validate aggregate adhesion inputs if provided
    if normal_force_n is not None:
        _validate_finite_float("normal_force_n", normal_force_n, min_val=0.1, max_val=500000.0)
    if adhesion_coefficient is not None:
        _validate_finite_float("adhesion_coefficient", adhesion_coefficient, min_val=0.01, max_val=2.5)

    # Demanded total braking power at wheels (magnitude, kW)
    p_req_wheel_kw = (f_req * v) / 1000.0

    notes_list: List[str] = []
    active_constraints: List[str] = []
    curtailment_reason: Optional[str] = None
    TOL = 1e-4

    # Step 1: Kinematics & Low-Speed Regen Factor
    speed_res = compute_motor_speed(v, gearbox_config, input_status=input_status)
    omega = speed_res.motor_speed_rad_s
    s_lowspeed = compute_low_speed_regen_factor(v, cfg_blend)

    # Step 2: Mechanical Motor Capability
    motor_env = compute_motor_envelope(omega, motor_config, mode=envelope_mode, input_status=input_status)
    t_mot_mech_avail = motor_env.available_torque_nm

    # Step 3: AC Stator Phase Current vs Inverter Phase Current Limit
    stator_current_limit_rms = motor_config.inverter_current_limit_rms
    has_valid_kt = (motor_config.k_t_rms is not None and motor_config.k_t_rms > 0)
    has_valid_inv_ac_limit = (stator_current_limit_rms is not None and stator_current_limit_rms > 0)

    stator_current_status = ConstraintStatus.SATISFIED
    if not has_valid_kt:
        stator_current_status = ConstraintStatus.CONDITIONAL
        notes_list.append("Motor torque constant k_t_rms unconfigured; AC stator current unverified")
        active_constraints.append("WARN_KT_UNVERIFIED")
    elif not has_valid_inv_ac_limit:
        stator_current_status = ConstraintStatus.CONDITIONAL
        notes_list.append("Inverter AC phase current limit unconfigured; stator current compliance unverified")
        active_constraints.append("WARN_STATOR_CURRENT_LIMIT_UNVERIFIED")
    else:
        # Both verified: calculate mechanical torque limit from inverter AC phase current
        t_mot_current_limit = stator_current_limit_rms * motor_config.k_t_rms
        t_mot_mech_avail = min(t_mot_mech_avail, t_mot_current_limit)

    # Mechanical Wheel Regenerative Force Capability (accounting for reverse gearbox efficiency)
    if omega > 1e-4 and v > 1e-4:
        f_wheel_mech_max = (t_mot_mech_avail * gearbox_config.gear_ratio) / (gearbox_config.efficiency_rev * gearbox_config.wheel_radius_m)
        f_wheel_mech_max *= s_lowspeed
    else:
        f_wheel_mech_max = 0.0

    # Step 4: BMS Charge Acceptance
    bms_res = compute_bms_acceptance(
        battery_soc=battery_soc,
        battery_temp_c=battery_temp_c,
        config=bms_config,
        state_of_health=state_of_health,
        input_status=input_status,
        soc_status=soc_status,
        temp_status=temp_status,
        soh_status=soh_status,
    )
    p_bms_allowed_kw = bms_res.admissible_charge_power_kw
    is_bms_power_limit_known = bms_res.is_power_limit_known
    is_bms_current_limit_known = bms_res.is_current_limit_known
    is_bms_limit_known = bms_res.is_limit_known

    if not is_bms_power_limit_known:
        notes_list.append("BMS charge power limit unknown; regeneration accepted conditionally pending C3 battery voltage validation")
        active_constraints.append("WARN_BMS_POWER_LIMIT_UNKNOWN")
    if not is_bms_current_limit_known:
        notes_list.append("BMS charge current limit unknown; battery current acceptance unverified")
        active_constraints.append("WARN_BMS_CURRENT_LIMIT_UNKNOWN")

    # Step 5: Auxiliary Electrical Demand on HV Bus
    aux_res = compute_auxiliary_hv_power(
        aux_lv_power_kw=aux_lv_power_kw,
        dc_dc_efficiency=inverter_config.dc_dc_efficiency,
        dc_dc_efficiency_status=inverter_config.dc_dc_efficiency_status,
        input_status=aux_status or input_status,
    )
    p_aux_hv_kw = aux_res.aux_hv_power_kw
    p_loss_dc_dc_kw = aux_res.dc_dc_loss_kw
    standby_kw = inverter_config.standby_loss_w / 1000.0

    # Step 6: Electrical Acceptance Limit at Inverter Bridge
    # dc_power_limit_kw defines maximum allowable GROSS DC generation at inverter bridge
    # Gross bridge power allows: P_inv_dc_gross <= P_bms_allowed + P_aux_HV + P_standby_kw (if BMS limit known)
    if is_bms_power_limit_known and p_bms_allowed_kw is not None:
        p_bms_gross_cap = p_bms_allowed_kw + p_aux_hv_kw + standby_kw
        p_inv_dc_gross_allowed = p_bms_gross_cap
    else:
        p_bms_gross_cap = float("inf")
        p_inv_dc_gross_allowed = float("inf")

    # Inverter DC power rating check
    is_inverter_power_limit_known = (inverter_config.dc_power_limit_kw is not None)
    if is_inverter_power_limit_known:
        p_inv_dc_gross_allowed = min(p_inv_dc_gross_allowed, inverter_config.dc_power_limit_kw)
    else:
        notes_list.append("Inverter gross DC power limit unconfigured; DC bridge power compliance unverified")
        active_constraints.append("WARN_INVERTER_POWER_LIMIT_UNKNOWN")

    # Inverter DC current rating check (provisional estimate evaluated at nominal voltage)
    is_inverter_current_limit_known = (inverter_config.dc_current_limit_a is not None)
    is_inverter_voltage_known = (inverter_config.dc_voltage_nominal_v is not None and inverter_config.dc_voltage_nominal_v > 0)
    is_provisional_voltage_based = False

    if is_inverter_current_limit_known and is_inverter_voltage_known:
        p_inv_dc_current_limit = (inverter_config.dc_current_limit_a * inverter_config.dc_voltage_nominal_v) / 1000.0
        p_inv_dc_gross_allowed = min(p_inv_dc_gross_allowed, p_inv_dc_current_limit)
        is_provisional_voltage_based = True
    else:
        p_inv_dc_current_limit = float("inf")
        if not is_inverter_current_limit_known:
            notes_list.append("Inverter DC current limit unconfigured; DC bridge current compliance unverified")
            active_constraints.append("WARN_INVERTER_CURRENT_LIMIT_UNKNOWN")
        if not is_inverter_voltage_known:
            notes_list.append("Inverter nominal DC voltage unconfigured; provisional DC current compliance unverified")
            active_constraints.append("WARN_INVERTER_VOLTAGE_UNKNOWN")

    # Back-propagate Electrical Acceptance to Wheel Force:
    p_mot_ac_allowed = p_inv_dc_gross_allowed / inverter_config.efficiency_regen
    p_mot_shaft_allowed = p_mot_ac_allowed / motor_config.efficiency_gen
    p_wheel_regen_allowed = p_mot_shaft_allowed / gearbox_config.efficiency_rev

    if v > 1e-4:
        f_wheel_elec_max = (p_wheel_regen_allowed * 1000.0) / v
        f_wheel_elec_max *= s_lowspeed
    else:
        f_wheel_elec_max = 0.0

    # Step 7: Aggregate Vehicle-Level Adhesion Ceiling
    mu = adhesion_coefficient if adhesion_coefficient is not None else cfg_blend.default_adhesion_coefficient
    f_adhesion_max: Optional[float] = None

    if mu is not None and normal_force_n is not None:
        f_adhesion_max = mu * normal_force_n
        if f_req <= f_adhesion_max + 1e-3:
            adhesion_status = ConstraintStatus.SATISFIED
        else:
            adhesion_status = ConstraintStatus.VIOLATED
            notes_list.append(f"Requested braking force ({f_req:.1f} N) exceeds aggregate tire adhesion limit ({f_adhesion_max:.1f} N)")
    else:
        adhesion_status = ConstraintStatus.CONDITIONAL
        notes_list.append("Aggregate tire-road adhesion unverified; conditional feasibility")
        active_constraints.append("WARN_ADHESION_UNVERIFIED")

    # Friction capacity budget check
    is_friction_capacity_known = (cfg_blend.friction_brake_max_force_n is not None)
    if not is_friction_capacity_known:
        notes_list.append("Friction brake force capacity unconfigured; mechanical braking capability unverified")
        active_constraints.append("WARN_FRICTION_CAPACITY_UNKNOWN")

    # Step 8: Accepted Regenerative Wheel Force Arbitration
    f_regen_candidates = [f_req, f_wheel_mech_max, f_wheel_elec_max]
    if f_adhesion_max is not None:
        f_regen_candidates.append(f_adhesion_max)

    f_regen_accepted = min(f_regen_candidates)
    f_regen_accepted = max(0.0, f_regen_accepted)

    # Diagnostic Arbitration for Active Regenerative Constraints (using TOL = 1e-4)
    elec_active_codes: List[str] = []
    if is_bms_power_limit_known and p_bms_allowed_kw is not None and abs(p_inv_dc_gross_allowed - p_bms_gross_cap) <= TOL:
        if bms_res.is_soc_derated:
            elec_active_codes.append("ERR_BATTERY_SOC_DERATE")
            notes_list.append(f"Regen curtailed by high battery SOC ({battery_soc * 100:.1f}%)")
        elif bms_res.is_temp_derated:
            elec_active_codes.append("ERR_BATTERY_TEMPERATURE_DERATE")
            notes_list.append(f"Regen curtailed by battery temperature ({battery_temp_c:.1f} °C)")
        else:
            elec_active_codes.append("ERR_BMS_CHARGE_POWER_LIMIT")
            notes_list.append(f"Regen curtailed by BMS charge acceptance limit ({p_bms_allowed_kw:.1f} kW)")

    if is_provisional_voltage_based and abs(p_inv_dc_gross_allowed - p_inv_dc_current_limit) <= TOL:
        elec_active_codes.append("ERR_INVERTER_CURRENT_LIMIT")
        notes_list.append("Regen curtailed by inverter DC current rating at nominal voltage")

    if is_inverter_power_limit_known and abs(p_inv_dc_gross_allowed - inverter_config.dc_power_limit_kw) <= TOL:
        elec_active_codes.append("ERR_INVERTER_DC_POWER_LIMIT")
        notes_list.append("Regen curtailed by inverter gross DC power rating")

    if not is_bms_power_limit_known and not elec_active_codes:
        elec_active_codes.append("WARN_ELECTRICAL_ACCEPTANCE_UNVERIFIED")

    mech_active_codes: List[str] = []
    if has_valid_inv_ac_limit and has_valid_kt and abs(t_mot_mech_avail - (stator_current_limit_rms * motor_config.k_t_rms)) <= TOL:
        mech_active_codes.append("ERR_STATOR_CURRENT_LIMIT")
        notes_list.append("Regen curtailed by motor AC stator phase current limit")
    if omega >= motor_env.governor_start_rad_s - TOL:
        mech_active_codes.append("ERR_REGEN_POWER_LIMIT")
        notes_list.append("Regen curtailed by motor high-speed governor derating")
    if not mech_active_codes:
        mech_active_codes.append("ERR_REGEN_TORQUE_LIMIT")
        notes_list.append(f"Regen curtailed by motor maximum retarding torque ({t_mot_mech_avail:.1f} Nm)")

    # Arbitrate Curtailment Reason and Active Constraints
    is_curtailed = False
    curtailment_active: List[str] = []

    if f_req > 1e-4:
        if v <= cfg_blend.v_cutoff_ms + 1e-4:
            is_curtailed = True
            curtailment_active.append("ERR_LOW_SPEED_REGEN_LIMIT")
            notes_list.append(f"Regen cutoff at low speed ({v:.2f} m/s <= {cfg_blend.v_cutoff_ms:.2f} m/s)")
        elif f_regen_accepted < (f_req - 1e-3):
            is_curtailed = True
            if f_adhesion_max is not None and abs(f_regen_accepted - f_adhesion_max) <= 1e-3:
                curtailment_active.append("ERR_ADHESION_EXCEEDED")
            if abs(f_regen_accepted - f_wheel_elec_max) <= 1e-3:
                curtailment_active.extend(elec_active_codes)
            if abs(f_regen_accepted - f_wheel_mech_max) <= 1e-3:
                curtailment_active.extend(mech_active_codes)

    # Primary curtailment priority hierarchy
    curtailment_priority = [
        "ERR_LOW_SPEED_REGEN_LIMIT",
        "ERR_ADHESION_EXCEEDED",
        "ERR_BATTERY_SOC_DERATE",
        "ERR_BATTERY_TEMPERATURE_DERATE",
        "ERR_STATOR_CURRENT_LIMIT",
        "ERR_INVERTER_CURRENT_LIMIT",
        "ERR_INVERTER_DC_POWER_LIMIT",
        "ERR_BMS_CHARGE_POWER_LIMIT",
        "ERR_REGEN_POWER_LIMIT",
        "ERR_REGEN_TORQUE_LIMIT",
        "WARN_ELECTRICAL_ACCEPTANCE_UNVERIFIED",
    ]
    for code in curtailment_priority:
        if code in curtailment_active:
            curtailment_reason = code
            break

    for code in curtailment_active:
        if code not in active_constraints:
            active_constraints.append(code)

    # Step 9: Forward Power Chain from Accepted Regenerative Force
    p_wheel_regen_kw = (f_regen_accepted * v) / 1000.0  # magnitude (kW)
    p_shaft_mag_kw = p_wheel_regen_kw * gearbox_config.efficiency_rev
    p_loss_gb_kw = p_wheel_regen_kw * (1.0 - gearbox_config.efficiency_rev)

    if omega > 1e-4:
        t_mot_regen_nm = (f_regen_accepted * gearbox_config.wheel_radius_m * gearbox_config.efficiency_rev) / gearbox_config.gear_ratio
    else:
        t_mot_regen_nm = 0.0

    # AC Electrical Generation
    p_mot_ac_mag_kw = p_shaft_mag_kw * motor_config.efficiency_gen
    p_loss_mot_kw = p_shaft_mag_kw * (1.0 - motor_config.efficiency_gen)
    i_stator_rms = compute_stator_phase_current(t_mot_regen_nm, motor_config) if has_valid_kt else None

    # Inverter DC Rectification & Standby (Boundary 4)
    p_inv_dc_gross_kw = p_mot_ac_mag_kw * inverter_config.efficiency_regen
    p_loss_inv_conv_kw = p_mot_ac_mag_kw * (1.0 - inverter_config.efficiency_regen)

    # Net inverter contribution to HV bus: UNCLAMPED SIGNED POWER
    p_inv_dc_net_kw = p_inv_dc_gross_kw - standby_kw
    p_loss_inv_total_kw = p_loss_inv_conv_kw + standby_kw

    # Inverter DC Currents at Nominal Voltage (Gross bridge current vs Net HV bus current)
    if is_inverter_voltage_known:
        v_nom = inverter_config.dc_voltage_nominal_v
        i_inv_dc_gross = (p_inv_dc_gross_kw * 1000.0) / v_nom
        i_inv_dc_net = (p_inv_dc_net_kw * 1000.0) / v_nom
    else:
        i_inv_dc_gross = None
        i_inv_dc_net = None

    # Step 10: HV Bus Balance & Net Battery Charging Request
    p_batt_chg_net_kw = p_inv_dc_net_kw - p_aux_hv_kw

    # Step 11: Friction Brake Compensation, Hardware Capacity & Adhesion Cap
    f_friction_req = max(0.0, f_req - f_regen_accepted)
    f_friction_hw_limit = cfg_blend.friction_brake_max_force_n if is_friction_capacity_known else float("inf")
    
    if f_adhesion_max is not None:
        f_friction_adh_limit = max(0.0, f_adhesion_max - f_regen_accepted)
    else:
        f_friction_adh_limit = float("inf")

    f_friction_delivered = min(f_friction_req, f_friction_hw_limit, f_friction_adh_limit)
    f_delivered_total = f_regen_accepted + f_friction_delivered

    braking_deficit_n = max(0.0, f_req - f_delivered_total)
    p_friction_delivered_kw = (f_friction_delivered * v) / 1000.0
    p_wheel_delivered_kw = (f_delivered_total * v) / 1000.0
    p_deficit_kw = (braking_deficit_n * v) / 1000.0

    if f_friction_delivered < (f_friction_req - 1e-3):
        if f_adhesion_max is not None and abs(f_friction_delivered - f_friction_adh_limit) <= 1e-3 and f_friction_adh_limit < f_friction_hw_limit:
            notes_list.append(f"Braking capped at aggregate tire adhesion limit ({f_adhesion_max:.1f} N); undelivered deficit is {braking_deficit_n:.1f} N")
            if "ERR_ADHESION_EXCEEDED" not in active_constraints:
                active_constraints.append("ERR_ADHESION_EXCEEDED")
        else:
            notes_list.append(f"Friction braking requirement ({f_friction_req:.1f} N) exceeds capacity ({f_friction_hw_limit:.1f} N); undelivered deficit is {braking_deficit_n:.1f} N")
            if "ERR_FRICTION_BRAKE_CAPACITY" not in active_constraints:
                active_constraints.append("ERR_FRICTION_BRAKE_CAPACITY")

    # Step 12: Exact Energy Conservation Ledger Check on DELIVERED Quantities
    p_energy_delivered_sum = (
        p_friction_delivered_kw
        + p_batt_chg_net_kw
        + standby_kw
        + p_aux_hv_kw
        + p_loss_inv_conv_kw
        + p_loss_mot_kw
        + p_loss_gb_kw
    )
    energy_residual = p_wheel_delivered_kw - p_energy_delivered_sum

    # Step 13: Provenance Combination
    prov_status = combine_provenance(
        input_status,
        motor_config.status,
        gearbox_config.status,
        inverter_config.status,
        inverter_config.dc_dc_efficiency_status,
        bms_config.status,
        cfg_blend.status,
        soc_status,
        temp_status,
        soh_status,
        aux_status,
        adhesion_input_status,
    )

    # Step 14: Constraint Status and Diagnostic Synthesis
    is_hardware_complete = (
        is_bms_power_limit_known
        and is_bms_current_limit_known
        and is_inverter_power_limit_known
        and is_inverter_current_limit_known
        and is_inverter_voltage_known
        and has_valid_kt
        and has_valid_inv_ac_limit
        and is_friction_capacity_known
        and (adhesion_status == ConstraintStatus.SATISFIED)
    )

    if braking_deficit_n > 1e-3:
        overall_status = ConstraintStatus.VIOLATED
        if "ERR_ADHESION_EXCEEDED" in active_constraints or adhesion_status == ConstraintStatus.VIOLATED:
            diagnostic_code = "ERR_ADHESION_EXCEEDED"
        else:
            diagnostic_code = "ERR_FRICTION_BRAKE_CAPACITY"
    elif adhesion_status == ConstraintStatus.VIOLATED:
        overall_status = ConstraintStatus.VIOLATED
        diagnostic_code = "ERR_ADHESION_EXCEEDED"
    elif stator_current_status == ConstraintStatus.VIOLATED:
        overall_status = ConstraintStatus.VIOLATED
        diagnostic_code = "ERR_STATOR_CURRENT_LIMIT"
    elif not is_hardware_complete or prov_status != DataStatus.REAL:
        overall_status = ConstraintStatus.CONDITIONAL
        # Primary diagnostic code selection among active warnings/curtailments
        if not is_bms_power_limit_known:
            diagnostic_code = "WARN_BMS_POWER_LIMIT_UNKNOWN"
        elif not is_bms_current_limit_known:
            diagnostic_code = "WARN_BMS_CURRENT_LIMIT_UNKNOWN"
        elif not has_valid_kt:
            diagnostic_code = "WARN_KT_UNVERIFIED"
        elif not has_valid_inv_ac_limit:
            diagnostic_code = "WARN_STATOR_CURRENT_LIMIT_UNVERIFIED"
        elif not is_inverter_power_limit_known:
            diagnostic_code = "WARN_INVERTER_POWER_LIMIT_UNKNOWN"
        elif not is_inverter_current_limit_known:
            diagnostic_code = "WARN_INVERTER_CURRENT_LIMIT_UNKNOWN"
        elif not is_inverter_voltage_known:
            diagnostic_code = "WARN_INVERTER_VOLTAGE_UNKNOWN"
        elif not is_friction_capacity_known:
            diagnostic_code = "WARN_FRICTION_CAPACITY_UNKNOWN"
        elif adhesion_status == ConstraintStatus.CONDITIONAL:
            diagnostic_code = curtailment_reason or "WARN_ADHESION_UNVERIFIED"
        else:
            diagnostic_code = curtailment_reason or "WARN_HARDWARE_LIMITS_UNVERIFIED"
    elif is_curtailed:
        overall_status = ConstraintStatus.SATISFIED
        diagnostic_code = curtailment_reason
    else:
        overall_status = ConstraintStatus.SATISFIED
        diagnostic_code = None
        notes_list.append("Full regenerative braking accepted within verified hardware envelope")

    return BrakeBlendingResult(
        requested_brake_force_n=f_req,
        requested_brake_power_kw=p_req_wheel_kw,
        vehicle_speed_ms=v,
        delivered_brake_force_n=f_delivered_total,
        delivered_brake_power_kw=p_wheel_delivered_kw,
        braking_deficit_force_n=braking_deficit_n,
        braking_deficit_power_kw=p_deficit_kw,
        accepted_regen_wheel_force_n=f_regen_accepted,
        accepted_regen_wheel_power_kw=-p_wheel_regen_kw,  # Signed <= 0
        friction_brake_force_n=f_friction_delivered,
        friction_brake_power_kw=p_friction_delivered_kw,
        motor_shaft_power_kw=-p_shaft_mag_kw,            # Signed <= 0
        motor_torque_regen_nm=t_mot_regen_nm,
        motor_speed_rad_s=omega,
        gearbox_loss_kw=p_loss_gb_kw,
        motor_electrical_power_kw=-p_mot_ac_mag_kw,      # Signed <= 0
        motor_loss_kw=p_loss_mot_kw,
        stator_current_rms_a=i_stator_rms,
        stator_current_limit_rms_a=stator_current_limit_rms,
        stator_current_status=stator_current_status,
        inverter_dc_power_gross_kw=p_inv_dc_gross_kw,
        inverter_dc_power_net_kw=p_inv_dc_net_kw,        # Signed: can be < 0
        inverter_dc_current_gross_a=i_inv_dc_gross,      # Gross bridge current for rating compliance
        inverter_dc_current_net_a=i_inv_dc_net,          # Signed net current for HV bus accounting
        inverter_dc_current_a=i_inv_dc_net,              # Backward-compatible alias for net DC current
        inverter_dc_current_limit_a=inverter_config.dc_current_limit_a,
        is_provisional_voltage_based=is_provisional_voltage_based,
        inverter_standby_kw=standby_kw,
        inverter_loss_conv_kw=p_loss_inv_conv_kw,
        inverter_loss_kw=p_loss_inv_total_kw,
        auxiliary_lv_power_kw=aux_lv_power_kw,
        auxiliary_hv_power_kw=p_aux_hv_kw,
        dc_dc_loss_kw=p_loss_dc_dc_kw,
        net_battery_charging_kw=p_batt_chg_net_kw,       # Signed: > 0 chg, < 0 dis
        bms_admissible_power_kw=p_bms_allowed_kw,
        bms_admissible_current_a=bms_res.admissible_charge_current_a,
        is_bms_power_limit_known=is_bms_power_limit_known,
        is_bms_current_limit_known=is_bms_current_limit_known,
        is_bms_limit_known=is_bms_limit_known,
        energy_residual_kw=energy_residual,
        low_speed_factor=s_lowspeed,
        is_regen_curtailed=is_curtailed,
        curtailment_reason=curtailment_reason,
        adhesion_limit_force_n=f_adhesion_max,
        adhesion_status=adhesion_status,
        overall_status=overall_status,
        diagnostic_code=diagnostic_code,
        active_constraints=active_constraints,
        provenance_status=prov_status,
        notes=notes_list,
    )
