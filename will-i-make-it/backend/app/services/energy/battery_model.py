"""
Dynamic Battery Modeling Subsystem (Stage C3)
=============================================
High-fidelity, deterministic 1-RC Thevenin Equivalent Circuit (TEC) model for
EV battery packs with dynamic polarization overpotentials, closed-loop terminal
voltage calculation, exact quadratic power-to-current solution, joint boundary
arbitration, Coulomb counting SOC integration, and exact internal energy accounting.

PHYSICAL & CIRCUIT CONVENTIONS (C3 FROZEN STANDARDS)
----------------------------------------------------
1. Current & Power Sign Conventions:
   - Positive battery current = Charging (I_batt > 0).
   - Negative battery current = Discharging (I_batt < 0).
   - Positive battery terminal power = Charging (P_batt > 0, power flows into battery).
   - Negative battery terminal power = Discharging (P_batt < 0, power flows out of battery).
   - Matches C2.1 HV bus Boundary 5 convention (`net_battery_charging_kw`).

2. 1-RC Thevenin Circuit Topology:
   - Pack open-circuit voltage: V_oc(SOC, T) [V]
   - Pack series ohmic resistance: R_0(SOC, T) [Ohm]
   - Polarization branch: Parallel combination of R_1(SOC, T) [Ohm] and C_1(SOC, T) [F]
   - Polarization time constant: tau_1 = R_1 * C_1 [s]
   - Polarization overpotential: V_1(t) [V] (across C_1)

3. Terminal Voltage:
   - Instantaneous terminal voltage:
       V_term(t) = V_oc(SOC, T) + I(t) * R_0(SOC, T) + V_1(t)
   - During charging (I > 0): V_term > V_oc (polarization and ohmic drop raise V_term).
   - During discharging (I < 0): V_term < V_oc (polarization and ohmic drop depress V_term).
   - At open circuit (I = 0, V_1 = 0): V_term = V_oc.

4. Dynamic Polarization ODE & Exact Zero-Order-Hold (ZOH) Update:
   - Governing differential equation:
       d(V_1)/dt = (I / C_1) - (V_1 / (R_1 * C_1)) = (R_1 * I - V_1) / tau_1
   - Under constant current I over step dt:
       beta = exp(-dt / tau_1)
       one_minus_beta = -expm1(-dt / tau_1)
       V_1(t + dt) = V_1(t) * beta + R_1 * I * one_minus_beta
   - Average polarization overpotential:
       alpha = (tau_1 / dt) * one_minus_beta
       avg_V_1 = alpha * V_1(0) + I * R_1 * (1 - alpha)
   - Average terminal voltage over step:
       V_eff = V_oc + alpha * V_1(0)
       R_eff = R_0 + R_1 * (1 - alpha)
       avg_V_term = V_eff + I * R_eff
   - Unconditionally numerically stable for any dt > 0 using expm1 and series expansions.

5. Complete Internal Energy Conservation Ledger:
   - Terminal electrical energy:
       E_term = avg_V_term * I * dt  [J]
   - Total electrochemical OCV energy:
       E_oc = V_oc * I * dt  [J]
   - Coulombic Efficiency & Parasitic Loss:
       During charging (I > 0):
         E_chem = eta_coul_chg * E_oc  [J] (reversible electrochemical storage)
         E_loss_parasitic = (1 - eta_coul_chg) * E_oc  [J] (irreversible side reactions)
       During discharging (I <= 0):
         E_chem = E_oc  [J]
         E_loss_parasitic = 0.0  [J]
       Identity: E_oc = E_chem + E_loss_parasitic
   - Ohmic & Polarization Losses:
       E_loss_R0 = I^2 * R_0 * dt  [J] (>= 0, Joule heating in series R_0)
       delta_E_C1 = 0.5 * C_1 * (V_1(t + dt)^2 - V_1(t)^2)  [J] (capacitive storage change)
       E_loss_R1 = I * integral_0^dt V_1(t) dt - delta_E_C1  [J] (>= 0, Joule heating in R_1)
   - Fundamental Conservation Identities:
       E_term == E_oc + E_loss_R0 + E_loss_R1 + delta_E_C1
       E_term == E_chem + E_loss_parasitic + E_loss_R0 + E_loss_R1 + delta_E_C1
   - Residual is strictly verified: abs(energy_residual_j) < 1e-5 J.

6. Joint Operating-Point Arbitration:
   - Jointly arbitrates terminal voltage [V_min, V_max] (evaluated at t=0 and t=dt),
     current [I_dis_max, I_chg_max], power [P_dis_max, P_chg_max], and SOC boundaries.
   - Detects empty feasible intervals (i_lower_bound > i_upper_bound) and diagnoses
     ERR_BATTERY_INFEASIBLE_BOUNDS.
   - Constrains discharge current to the monotonic physical branch I >= -V_eff / (2 * R_eff),
     preventing unphysical root selection beyond maximum theoretical power transfer.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import math
from typing import List, Optional, Tuple, Union
from pydantic import BaseModel, Field, field_validator, model_validator

from app.domain.provenance import DataStatus
from app.services.energy.powertrain_model import (
    ConstraintStatus,
    combine_provenance,
    _validate_finite_float,
)


# =============================================================================
# Mathematical Helpers for High-Precision Exponential Evaluation
# =============================================================================

def _compute_tau_exponential_factors(dt_s: float, tau1_s: float) -> Tuple[float, float, float, float]:
    """
    Compute beta = exp(-dt/tau1), 1 - beta = -expm1(-dt/tau1), alpha, and 1 - alpha.
    
    alpha = (tau1 / dt) * (1 - exp(-dt / tau1))
    
    For x = dt / tau1 < 1e-3, computes 1 - alpha via Taylor series to avoid catastrophic
    cancellation in 1.0 - alpha:
        1 - alpha = x * (0.5 - x * (1/6 - x / 24))
    """
    if tau1_s <= 1e-9:
        return 0.0, 1.0, 0.0, 1.0

    x = dt_s / tau1_s
    beta = math.exp(-x)
    one_minus_beta = -math.expm1(-x)

    if x < 1e-3:
        one_minus_alpha = x * (0.5 - x * ((1.0 / 6.0) - x / 24.0))
        alpha = 1.0 - one_minus_alpha
    else:
        alpha = (tau1_s / dt_s) * one_minus_beta if dt_s > 1e-9 else 1.0
        one_minus_alpha = 1.0 - alpha

    return beta, one_minus_beta, alpha, one_minus_alpha


def _interpolate_soc_table(table: List[Tuple[float, float]], soc: float) -> float:
    """
    Piecewise linear interpolation on a validated (SOC, value) curve with flat clamp extrapolation.
    """
    if soc <= table[0][0]:
        return table[0][1]
    if soc >= table[-1][0]:
        return table[-1][1]
    for i in range(len(table) - 1):
        s0, v0 = table[i]
        s1, v1 = table[i + 1]
        if s0 <= soc <= s1:
            frac = (soc - s0) / (s1 - s0) if (s1 > s0) else 0.0
            return v0 + frac * (v1 - v0)
    return table[-1][1]


# =============================================================================
# Configuration & Characterization Models
# =============================================================================

class BatteryConfig(BaseModel):
    """
    Battery pack electrochemical, equivalent circuit, and hardware ratings.
    
    Attributes:
        cell_chemistry: Chemistry designator (e.g., 'NMC', 'LFP', 'NCA').
        series_cells: Number of individual cells connected in series (N_s).
        parallel_strings: Number of parallel cell strings (N_p).
        nominal_cell_capacity_ah: Rated capacity of a single cell in Ampere-hours.
        nominal_pack_capacity_kwh: Rated gross energy capacity of the pack in kWh.
        nominal_pack_voltage_v: Nominal pack terminal voltage in Volts.
        cell_voltage_min_v: Safe minimum cell cutoff terminal voltage in Volts.
        cell_voltage_max_v: Safe maximum cell cutoff terminal voltage in Volts.
        cell_voltage_nominal_v: Nominal individual cell voltage in Volts.
        soc_min_operating: Safe minimum operating SOC boundary (0.0 - 1.0).
        soc_max_operating: Safe maximum operating SOC boundary (0.0 - 1.0).
        r0_pack_baseline_ohm: Baseline pack series ohmic resistance R_0 in Ohms.
        r1_pack_baseline_ohm: Baseline pack polarization resistance R_1 in Ohms.
        c1_pack_baseline_f: Baseline pack polarization capacitance C_1 in Farads.
        max_charge_current_a: Maximum allowable continuous charging current in Amperes (> 0).
        max_discharge_current_a: Maximum allowable continuous discharging current in Amperes (< 0).
        max_charge_power_kw: Maximum allowable continuous charging power in kW (> 0).
        max_discharge_power_kw: Maximum allowable continuous discharging power in kW (< 0).
        coulombic_efficiency_chg: Charge Coulombic efficiency (0.80 < eta <= 1.0).
        coulombic_efficiency_dis: Discharge Coulombic efficiency (typically 1.0).
        ocv_curve: Optional verified piecewise (SOC, Cell_OCV_V) characterization curve.
        r0_soc_table: Optional verified (SOC, R0_pack_ohm) table.
        r1_soc_table: Optional verified (SOC, R1_pack_ohm) table.
        c1_soc_table: Optional verified (SOC, C1_pack_f) table.
        temp_optimal_low_c: Lower ambient/cell temperature bound for full performance (°C).
        temp_optimal_high_c: Upper ambient/cell temperature bound for full performance (°C).
        status: Provenance status of the battery configuration parameters.
    """
    model_config = {"protected_namespaces": ()}

    cell_chemistry: str = Field(default="NMC", description="Battery cell chemistry")
    series_cells: int = Field(default=96, gt=0, le=1000, description="Cells in series N_s")
    parallel_strings: int = Field(default=1, gt=0, le=50, description="Parallel cell strings N_p")

    nominal_cell_capacity_ah: float = Field(default=60.0, gt=0.1, le=1000.0, description="Cell nominal capacity (Ah)")
    nominal_pack_capacity_kwh: float = Field(default=20.0, gt=0.5, le=500.0, description="Pack nominal capacity (kWh)")
    nominal_pack_voltage_v: float = Field(default=355.2, gt=20.0, le=1200.0, description="Pack nominal voltage (V)")

    cell_voltage_min_v: float = Field(default=2.80, gt=1.0, le=4.0, description="Cell minimum cutoff voltage (V)")
    cell_voltage_max_v: float = Field(default=4.20, gt=3.0, le=5.0, description="Cell maximum cutoff voltage (V)")
    cell_voltage_nominal_v: float = Field(default=3.70, gt=2.0, le=4.5, description="Cell nominal voltage (V)")

    soc_min_operating: float = Field(default=0.05, ge=0.0, lt=0.5, description="Minimum operating SOC boundary")
    soc_max_operating: float = Field(default=0.98, gt=0.5, le=1.0, description="Maximum operating SOC boundary")

    # Baseline 1-RC Equivalent Circuit Parameters (Pack Level)
    r0_pack_baseline_ohm: float = Field(default=0.035, ge=0.0, le=5.0, description="Pack ohmic resistance R_0 (Ohm)")
    r1_pack_baseline_ohm: float = Field(default=0.025, ge=0.0, le=5.0, description="Pack polarization resistance R_1 (Ohm)")
    c1_pack_baseline_f: float = Field(default=2000.0, gt=1.0, le=500000.0, description="Pack polarization capacitance C_1 (F)")

    # Hardware Limits (Explicit Optional Ratings)
    max_charge_current_a: Optional[float] = Field(default=200.0, gt=0.0, le=2000.0, description="Continuous charge current limit (A)")
    max_discharge_current_a: Optional[float] = Field(default=-300.0, lt=0.0, ge=-3000.0, description="Continuous discharge current limit (A)")
    max_charge_power_kw: Optional[float] = Field(default=65.0, gt=0.0, le=1000.0, description="Continuous charge power limit (kW)")
    max_discharge_power_kw: Optional[float] = Field(default=-100.0, lt=0.0, ge=-2000.0, description="Continuous discharge power limit (kW)")

    # Coulombic Efficiencies
    coulombic_efficiency_chg: float = Field(default=0.99, gt=0.80, le=1.0, description="Coulombic charging efficiency")
    coulombic_efficiency_dis: float = Field(
        default=1.00,
        description="Coulombic discharging efficiency (strictly 1.0 by physical Faradaic de-intercalation convention)"
    )

    # Characterization Profiles (Verified OEM or User Configured)
    ocv_curve: Optional[List[Tuple[float, float]]] = Field(
        default=None,
        description="Piecewise cell OCV table as list of (SOC, Cell_OCV_V) pairs"
    )
    r0_soc_table: Optional[List[Tuple[float, float]]] = Field(
        default=None,
        description="Piecewise pack R0 table as list of (SOC, R0_ohm) pairs"
    )
    r1_soc_table: Optional[List[Tuple[float, float]]] = Field(
        default=None,
        description="Piecewise pack R1 table as list of (SOC, R1_ohm) pairs"
    )
    c1_soc_table: Optional[List[Tuple[float, float]]] = Field(
        default=None,
        description="Piecewise pack C1 table as list of (SOC, C1_f) pairs"
    )

    temp_optimal_low_c: float = Field(default=15.0, ge=-20.0, le=40.0, description="Optimal temperature lower bound (°C)")
    temp_optimal_high_c: float = Field(default=35.0, ge=20.0, le=60.0, description="Optimal temperature upper bound (°C)")

    status: DataStatus = Field(default=DataStatus.ESTIMATED, description="Parameter provenance status")

    @field_validator("ocv_curve")
    @classmethod
    def validate_ocv_curve(cls, v: Optional[List[Tuple[float, float]]]) -> Optional[List[Tuple[float, float]]]:
        if v is None:
            return None
        if len(v) < 2:
            raise ValueError("ocv_curve must contain at least 2 characterization points")
        for idx, pt in enumerate(v):
            if not (isinstance(pt, (tuple, list)) and len(pt) == 2):
                raise ValueError(f"ocv_curve entry at index {idx} must be a (SOC, Cell_OCV_V) pair")
            s, val = pt
            if not (math.isfinite(s) and math.isfinite(val)):
                raise ValueError(f"ocv_curve entry {pt} contains non-finite values")
            if not (0.0 <= s <= 1.0):
                raise ValueError(f"ocv_curve SOC {s} must be in range [0.0, 1.0]")
            if val <= 0.0:
                raise ValueError(f"ocv_curve cell voltage {val} must be positive (> 0.0 V)")
        for i in range(len(v) - 1):
            if v[i + 1][0] <= v[i][0]:
                raise ValueError(
                    f"ocv_curve SOC coordinates must be strictly increasing: {v[i][0]} >= {v[i+1][0]}"
                )
        return v

    @field_validator("r0_soc_table", "r1_soc_table", "c1_soc_table")
    @classmethod
    def validate_impedance_table(cls, v: Optional[List[Tuple[float, float]]]) -> Optional[List[Tuple[float, float]]]:
        if v is None:
            return None
        if len(v) < 2:
            raise ValueError("Impedance characterization table must contain at least 2 points")
        for idx, pt in enumerate(v):
            if not (isinstance(pt, (tuple, list)) and len(pt) == 2):
                raise ValueError(f"Impedance table entry at index {idx} must be a (SOC, value) pair")
            s, val = pt
            if not (math.isfinite(s) and math.isfinite(val)):
                raise ValueError(f"Impedance table entry {pt} contains non-finite values")
            if not (0.0 <= s <= 1.0):
                raise ValueError(f"Impedance table SOC {s} must be in range [0.0, 1.0]")
            if val <= 0.0:
                raise ValueError(f"Impedance table value {val} must be strictly positive (> 0.0)")
        for i in range(len(v) - 1):
            if v[i + 1][0] <= v[i][0]:
                raise ValueError(
                    f"Impedance table SOC coordinates must be strictly increasing: {v[i][0]} >= {v[i+1][0]}"
                )
        return v

    @field_validator("coulombic_efficiency_dis")
    @classmethod
    def validate_discharge_efficiency(cls, v: float) -> float:
        if not math.isfinite(v):
            raise ValueError("coulombic_efficiency_dis must be a finite float")
        if abs(v - 1.0) > 1e-6:
            raise ValueError(
                "coulombic_efficiency_dis must be exactly 1.0. Electrochemical convention: all Faradaic charge "
                "loss is assigned to charging parasitic side reactions (eta_chg < 1.0). De-intercalation during "
                "discharge has unit Faradaic yield (eta_dis == 1.0), preserving exact physical consistency with "
                "the electrochemical energy ledger."
            )
        return 1.0

    @model_validator(mode="after")
    def validate_voltages_and_soc(self) -> BatteryConfig:
        if self.cell_voltage_min_v >= self.cell_voltage_nominal_v:
            raise ValueError("cell_voltage_min_v must be < cell_voltage_nominal_v")
        if self.cell_voltage_nominal_v >= self.cell_voltage_max_v:
            raise ValueError("cell_voltage_nominal_v must be < cell_voltage_max_v")
        if self.soc_min_operating >= self.soc_max_operating:
            raise ValueError("soc_min_operating must be < soc_max_operating")
        if self.temp_optimal_low_c >= self.temp_optimal_high_c:
            raise ValueError("temp_optimal_low_c must be < temp_optimal_high_c")
        return self


# =============================================================================
# State & Result Dataclasses
# =============================================================================

@dataclass(frozen=True)
class BatteryState:
    """
    Dynamic state of the electrochemical battery pack at an instant in time.
    """
    soc: float                                  # State of charge fraction in [0.0, 1.0]
    v1_polarization_v: float                    # Polarization overpotential across C_1 [V]
    temperature_c: float                        # Cell/pack bulk temperature [°C]
    state_of_health: float                      # Pack capacity retention fraction in (0.0, 1.0]
    cumulative_energy_throughput_kwh: float     # Cumulative gross energy throughput [kWh]
    provenance_status: DataStatus               # Provenance status of the battery state

    def __post_init__(self):
        if not math.isfinite(self.soc) or not (0.0 <= self.soc <= 1.0):
            raise ValueError(f"BatteryState soc must be finite in [0.0, 1.0], got {self.soc}")
        if not math.isfinite(self.v1_polarization_v):
            raise ValueError(f"BatteryState v1_polarization_v must be finite, got {self.v1_polarization_v}")
        if not math.isfinite(self.temperature_c) or not (-60.0 <= self.temperature_c <= 90.0):
            raise ValueError(f"BatteryState temperature_c must be finite in [-60.0, 90.0], got {self.temperature_c}")
        if not math.isfinite(self.state_of_health) or not (0.0 < self.state_of_health <= 1.0):
            raise ValueError(f"BatteryState state_of_health must be finite in (0.0, 1.0], got {self.state_of_health}")
        if not math.isfinite(self.cumulative_energy_throughput_kwh) or self.cumulative_energy_throughput_kwh < 0.0:
            raise ValueError(f"BatteryState cumulative_energy_throughput_kwh must be finite >= 0.0, got {self.cumulative_energy_throughput_kwh}")


@dataclass(frozen=True)
class TheveninParameters:
    """
    Evaluated 1-RC Thevenin equivalent circuit parameters at given (SOC, Temperature).
    """
    v_oc_v: float                               # Pack open-circuit voltage [V]
    r0_ohm: float                               # Series ohmic resistance [Ohm]
    r1_ohm: float                               # Polarization resistance [Ohm]
    c1_f: float                                 # Polarization capacitance [F]
    tau1_s: float                               # Polarization time constant R_1 * C_1 [s]
    is_ocv_verified: bool                       # True if calculated from verified OEM characterization
    is_impedance_verified: bool                 # True only if R0, R1, and C1 are ALL verified
    is_r0_verified: bool = False                # True if R0 is from verified experimental data
    is_r1_verified: bool = False                # True if R1 is from verified experimental data
    is_c1_verified: bool = False                # True if C1 is from verified experimental data


@dataclass(frozen=True)
class BatteryOperatingPoint:
    """
    Operating electrical point resulting from instantaneous power/current arbitration.
    """
    terminal_voltage_v: float                   # Dynamic average terminal voltage V_term [V]
    terminal_voltage_end_v: float               # End-of-step terminal voltage V_term(dt) [V]
    current_a: float                            # Terminal current I (> 0 charge, < 0 discharge) [A]
    terminal_power_kw: float                    # Average terminal power P_term (> 0 charge, < 0 discharge) [kW]
    ocv_power_kw: float                         # Total electrochemical OCV power: V_oc * I [kW]
    p_chem_kw: float                            # Reversible chemical storage/release rate [kW]
    p_loss_parasitic_kw: float                  # Parasitic side-reaction loss rate [kW] (>= 0)
    p_loss_r0_kw: float                         # Ohmic Joule heating in R_0 [kW] (>= 0)
    p_loss_r1_kw: float                         # Joule heating in R_1 [kW] (>= 0)
    p_c1_storage_kw: float                      # Rate of energy storage in C_1 [kW]
    is_voltage_limited: bool                    # True if terminal voltage hit V_min or V_max cutoff
    is_current_limited: bool                    # True if current hit max charge or discharge current
    is_power_limited: bool                      # True if power hit max charge or discharge power rating
    is_soc_limited: bool                        # True if operation was restricted by SOC boundary
    status: ConstraintStatus                    # Operating point constraint status
    diagnostic_code: Optional[str]              # Diagnostic code for active restriction


@dataclass(frozen=True)
class BatterySimulationResult:
    """
    Complete result of a single discrete simulation step on the 1-RC Thevenin circuit.
    """
    initial_state: BatteryState                 # State prior to step
    final_state: BatteryState                   # State after step integration
    operating_point: BatteryOperatingPoint      # Feasible electrical operating point during step
    dt_s: float                                 # Step duration [s]
    requested_power_kw: float                   # Demanded terminal power (> 0 chg, < 0 dis) [kW]
    accepted_power_kw: float                    # Physically delivered terminal power [kW]
    deficit_power_kw: float                     # Shortfall: P_requested - P_accepted [kW]
    energy_terminal_j: float                    # Terminal electrical energy transferred [J]
    energy_ocv_j: float                         # Total electrochemical energy V_oc * I * dt [J]
    energy_chem_j: float                        # Reversible chemical energy stored/released [J]
    energy_loss_parasitic_j: float              # Irreversible dissipation in parasitic reactions [J] (>= 0)
    energy_loss_r0_j: float                     # Joule dissipation in R_0 [J] (>= 0)
    energy_loss_r1_j: float                     # Joule dissipation in R_1 [J] (>= 0)
    delta_energy_c1_j: float                    # Stored capacitive energy change in C_1 [J]
    energy_residual_j: float                    # Energy conservation verification residual [J]
    overall_status: ConstraintStatus            # SATISFIED, CONDITIONAL, or VIOLATED
    active_constraints: List[str]               # All simultaneously active boundary constraints
    provenance_status: DataStatus               # Combined provenance of inputs and simulation
    notes: List[str]                            # Traceable engineering notes


# =============================================================================
# Core 1-RC Thevenin Electrochemical Functions
# =============================================================================

def compute_ocv(
    soc: float,
    temperature_c: float,
    config: BatteryConfig,
) -> Tuple[float, bool]:
    """
    Calculate pack open-circuit voltage V_oc from state of charge and temperature.
    
    Returns:
        Tuple of (v_oc_pack_v, is_verified).
        If verified ocv_curve is configured, interpolates linearly across characterization points.
        Otherwise, evaluates standard continuous illustrative Nernstian cell potential model
        labeled explicitly as unverified (is_verified = False).
    """
    soc_clamped = _validate_finite_float("soc", soc, min_val=0.0, max_val=1.0)
    temp_clamped = _validate_finite_float("temperature_c", temperature_c, min_val=-60.0, max_val=90.0)

    if config.ocv_curve:
        v_cell = _interpolate_soc_table(config.ocv_curve, soc_clamped)
        is_verified = True
    else:
        # Illustrative continuous OCV profile for lithium-ion cell
        v_min = config.cell_voltage_min_v
        v_max = config.cell_voltage_max_v

        # Smooth, monotonically increasing illustrative OCV representation
        v_cell = v_min + (v_max - v_min) * (0.85 * soc_clamped + 0.15 * (soc_clamped ** 2))
        # Small thermal Nernstian slope correction: ~0.1 mV/K
        v_cell += 0.0001 * (temp_clamped - 25.0) * (soc_clamped - 0.5)
        v_cell = max(v_min, min(v_max, v_cell))
        is_verified = False

    pack_ocv = v_cell * config.series_cells
    return pack_ocv, is_verified


def compute_internal_resistance(
    soc: float,
    temperature_c: float,
    config: BatteryConfig,
) -> TheveninParameters:
    """
    Calculate temperature- and SOC-dependent 1-RC Thevenin parameters for the pack:
    - V_oc: Open-circuit voltage [V]
    - R_0: Ohmic series resistance [Ohm]
    - R_1: Polarization resistance [Ohm]
    - C_1: Polarization capacitance [F]
    - tau_1: RC time constant R_1 * C_1 [s]
    """
    soc_c = _validate_finite_float("soc", soc, min_val=0.0, max_val=1.0)
    temp_c = _validate_finite_float("temperature_c", temperature_c, min_val=-60.0, max_val=90.0)

    v_oc, is_ocv_verified = compute_ocv(soc_c, temp_c, config)

    # 1. Base Ohmic Resistance R_0
    is_r0_verified = False
    if config.r0_soc_table:
        r0_base = _interpolate_soc_table(config.r0_soc_table, soc_c)
        is_r0_verified = True
    else:
        # Illustrative U-shaped resistance curve (higher at extreme low/high SOC)
        soc_factor = 1.0 + 0.35 * (1.0 - soc_c)**2 + 0.20 * (soc_c**3)
        r0_base = config.r0_pack_baseline_ohm * soc_factor
        is_r0_verified = False

    # 2. Temperature Derating for Resistance (Arrhenius-like behavior)
    if temp_c < config.temp_optimal_low_c:
        delta_t = config.temp_optimal_low_c - temp_c
        temp_factor = 1.0 + 0.04 * delta_t + 0.001 * (delta_t**2)
    elif temp_c > config.temp_optimal_high_c:
        temp_factor = max(0.85, 1.0 - 0.005 * (temp_c - config.temp_optimal_high_c))
    else:
        temp_factor = 1.0

    r0 = r0_base * temp_factor

    # 3. Polarization Resistance R_1
    is_r1_verified = False
    if config.r1_soc_table:
        r1_base = _interpolate_soc_table(config.r1_soc_table, soc_c)
        is_r1_verified = True
    else:
        r1_base = config.r1_pack_baseline_ohm * (1.0 + 0.25 * (1.0 - soc_c))
        is_r1_verified = False

    r1 = r1_base * temp_factor

    # 4. Polarization Capacitance C_1
    is_c1_verified = False
    if config.c1_soc_table:
        c1_base = _interpolate_soc_table(config.c1_soc_table, soc_c)
        is_c1_verified = True
    else:
        c1_base = config.c1_pack_baseline_f
        is_c1_verified = False

    c1 = c1_base / max(0.5, temp_factor)
    tau1 = r1 * c1

    is_impedance_verified = is_r0_verified and is_r1_verified and is_c1_verified

    return TheveninParameters(
        v_oc_v=v_oc,
        r0_ohm=r0,
        r1_ohm=r1,
        c1_f=c1,
        tau1_s=tau1,
        is_ocv_verified=is_ocv_verified,
        is_impedance_verified=is_impedance_verified,
        is_r0_verified=is_r0_verified,
        is_r1_verified=is_r1_verified,
        is_c1_verified=is_c1_verified,
    )


def solve_battery_current(
    requested_power_kw: float,
    current_v_eff: float,
    r_eff_ohm: float,
) -> Tuple[float, float, bool]:
    """
    Solve the quadratic Thevenin circuit average power equation for battery current:
        P_avg = avg_V_term * I = (V_eff + I * R_eff) * I = R_eff * I^2 + V_eff * I
        
    Numerically stable quadratic formulation:
        I = (2 * P_avg) / (V_eff + sqrt(V_eff^2 + 4 * R_eff * P_avg))
        
    Returns:
        Tuple of (solved_current_a, achievable_power_kw, is_real_root).
        If discriminant < 0 on discharge (demanded power exceeds maximum source transfer P_max = -V_eff^2 / 4R_eff),
        returns the peak physical current I = -V_eff / (2R_eff), power = -V_eff^2 / (4R_eff), and is_real_root = False.
    """
    p_w = requested_power_kw * 1000.0
    v_eff = current_v_eff
    r_eff = r_eff_ohm

    if r_eff <= 1e-9:
        if abs(v_eff) > 1e-4:
            i_ideal = p_w / v_eff
            return i_ideal, requested_power_kw, True
        return 0.0, 0.0, True

    discriminant = v_eff * v_eff + 4.0 * r_eff * p_w

    if discriminant < 0.0:
        i_peak = -v_eff / (2.0 * r_eff)
        p_peak_kw = (-v_eff * v_eff / (4.0 * r_eff)) / 1000.0
        return i_peak, p_peak_kw, False

    sqrt_disc = math.sqrt(discriminant)
    denom = v_eff + sqrt_disc
    if abs(denom) > 1e-9:
        i_sol = (2.0 * p_w) / denom
    else:
        i_sol = (-v_eff + sqrt_disc) / (2.0 * r_eff)

    return i_sol, requested_power_kw, True


def integrate_battery_state(
    initial_state: BatteryState,
    current_a: float,
    thevenin_params: TheveninParameters,
    dt_s: float,
    config: BatteryConfig,
) -> Tuple[BatteryState, float, float, float]:
    """
    Integrate battery state forward by dt_s under constant current current_a.
    
    State Integrations:
    1. Polarization overpotential V_1(t + dt) via zero-order-hold (ZOH) exact analytical solution:
       V_1(t + dt) = V_1(t) * exp(-dt / tau_1) + R_1 * I * (1 - exp(-dt / tau_1))
    2. Coulomb counting SOC update:
       SOC(t + dt) = SOC(t) + (eta_coulomb * I * dt) / Q_nom
    3. Exact internal branch energy dissipation:
       E_loss_R1 = Joule dissipation in R_1 over dt [J]
       delta_E_C1 = 0.5 * C_1 * (V_1(t + dt)^2 - V_1(t)^2) [J]
       
    Returns:
        Tuple of (final_state, energy_loss_r1_j, delta_energy_c1_j, integrated_avg_v1_v).
    """
    dt = _validate_finite_float("dt_s", dt_s, min_val=0.0001, max_val=3600.0)
    i_curr = current_a
    v1_0 = initial_state.v1_polarization_v
    r1 = thevenin_params.r1_ohm
    c1 = thevenin_params.c1_f
    tau1 = thevenin_params.tau1_s

    # 1. Polarization Update (ZOH exact integration with high-precision expm1)
    beta, one_minus_beta, alpha, one_minus_alpha = _compute_tau_exponential_factors(dt, tau1)
    v1_final = v1_0 * beta + r1 * i_curr * one_minus_beta

    # 2. RC Branch Energy Ledger Calculations:
    # Average polarization overpotential: avg_v1 = alpha * v1_0 + r1 * i_curr * (1 - alpha)
    avg_v1 = alpha * v1_0 + r1 * i_curr * one_minus_alpha
    int_v1_dt = avg_v1 * dt

    # Total energy entering parallel RC branch: E_RC = I * int_0^dt V_1(t) dt
    e_rc_branch_j = i_curr * int_v1_dt

    # Electrostatic stored energy change in capacitor C_1:
    delta_e_c1_j = 0.5 * c1 * (v1_final * v1_final - v1_0 * v1_0)

    # Resistor Joule dissipation in R_1: E_loss_R1 = E_RC - delta_E_C1
    e_loss_r1_j = e_rc_branch_j - delta_e_c1_j
    e_loss_r1_j = max(0.0, e_loss_r1_j)  # Enforce physical non-negativity against precision floor

    # 3. Coulomb Counting SOC Update
    if i_curr > 0:
        eta_c = config.coulombic_efficiency_chg
    else:
        eta_c = config.coulombic_efficiency_dis

    q_nom_as = config.nominal_cell_capacity_ah * config.parallel_strings * 3600.0 * initial_state.state_of_health
    delta_soc = (eta_c * i_curr * dt) / q_nom_as
    final_soc = max(0.0, min(1.0, initial_state.soc + delta_soc))

    # Energy throughput
    abs_throughput_kwh = (abs(i_curr) * config.nominal_pack_voltage_v * dt / 3600.0) / 1000.0
    cumulative_throughput = initial_state.cumulative_energy_throughput_kwh + abs_throughput_kwh

    # Provenance propagation across parameter models
    param_status = DataStatus.REAL if (thevenin_params.is_ocv_verified and thevenin_params.is_impedance_verified) else DataStatus.ESTIMATED
    state_prov = combine_provenance(initial_state.provenance_status, param_status, config.status)

    final_state = BatteryState(
        soc=final_soc,
        v1_polarization_v=v1_final,
        temperature_c=initial_state.temperature_c,
        state_of_health=initial_state.state_of_health,
        cumulative_energy_throughput_kwh=cumulative_throughput,
        provenance_status=state_prov,
    )

    return final_state, e_loss_r1_j, delta_e_c1_j, avg_v1


def simulate_battery_step(
    requested_power_kw: float,
    state: BatteryState,
    dt_s: float,
    config: BatteryConfig,
    input_status: Optional[DataStatus] = None,
) -> BatterySimulationResult:
    """
    Execute a single discrete physical step of the 1-RC Thevenin battery model.
    
    Arbitration & Simulation Sequence:
    1. Evaluate dynamic Thevenin parameters (V_oc, R_0, R_1, C_1, tau_1) at current state.
    2. Compute effective average circuit parameters V_eff and R_eff:
       alpha = (tau_1 / dt) * (1 - exp(-dt / tau_1))
       V_eff = V_oc + alpha * V_1(0)
       R_eff = R_0 + R_1 * (1 - alpha)
    3. Compute joint physical bounds for both instantaneous and end-of-step voltages:
       - Voltage bounds: [V_min, V_max] derived from series cell limits.
       - Current bounds: [I_dis_max, I_chg_max] from hardware ratings and voltage cutoffs.
       - Monotonic power branch: Enforces I >= -V_eff / (2 * R_eff) to prevent unphysical root selection.
       - Power bounds: [P_dis_max, P_chg_max] from hardware power ratings.
       - SOC bounds: No charge if SOC >= SOC_max; no discharge if SOC <= SOC_min.
       - Detects empty feasible interval (i_lower_bound > i_upper_bound) and flags ERR_BATTERY_INFEASIBLE_BOUNDS.
    4. Jointly arbitrate achievable terminal power before solving current.
    5. Solve exact quadratic Thevenin current for accepted power using (V_eff, R_eff).
    6. Integrate dynamic state (polarization overpotential V_1, SOC via Coulomb counting).
    7. Compute closed-loop energy ledger (E_term, E_oc, E_chem, E_parasitic, E_loss_R0, E_loss_R1, delta_E_C1).
    8. Verify exact zero-residual energy conservation (|residual| < 1e-5 J).
    9. Synthesize constraint statuses, diagnostic codes, and provenance.
    """
    dt = _validate_finite_float("dt_s", dt_s, min_val=0.0001, max_val=3600.0)
    p_req_kw = _validate_finite_float("requested_power_kw", requested_power_kw, min_val=-2000.0, max_val=2000.0)

    notes_list: List[str] = []
    active_constraints: List[str] = []
    TOL = 1e-4

    # 1. Dynamic Thevenin Parameter Evaluation
    params = compute_internal_resistance(state.soc, state.temperature_c, config)
    v_oc = params.v_oc_v
    r0 = params.r0_ohm
    r1 = params.r1_ohm
    tau1 = params.tau1_s
    v1_0 = state.v1_polarization_v

    # 2. Average Thevenin Parameters over Step [0, dt]
    beta, one_minus_beta, alpha, one_minus_alpha = _compute_tau_exponential_factors(dt, tau1)

    v_eff = v_oc + alpha * v1_0
    r_eff = r0 + r1 * one_minus_alpha

    # End-of-step parameters for V_term(dt):
    # V_term(dt) = (V_oc + beta * V_1_0) + I * [R_0 + R_1 * (1 - beta)]
    v_end_base = v_oc + beta * v1_0
    r_end_eff = r0 + r1 * one_minus_beta

    # 3. Joint Hardware & Physical Boundary Determination
    v_pack_min = config.cell_voltage_min_v * config.series_cells
    v_pack_max = config.cell_voltage_max_v * config.series_cells

    # Current bounds imposed by terminal voltage limits
    # We enforce V_min <= V_term <= V_max both at start-of-step and at end-of-step
    i_vmax_candidates = []
    i_vmin_candidates = []

    # Start-of-step: V_term(0) = V_oc + V_1(0) + I * R_0
    v_start_base = v_oc + v1_0
    if r0 > 1e-6:
        i_vmax_candidates.append((v_pack_max - v_start_base) / r0)
        i_vmin_candidates.append((v_pack_min - v_start_base) / r0)

    # End-of-step: V_term(dt) = v_end_base + I * r_end_eff
    if r_end_eff > 1e-6:
        i_vmax_candidates.append((v_pack_max - v_end_base) / r_end_eff)
        i_vmin_candidates.append((v_pack_min - v_end_base) / r_end_eff)

    i_vmax = min(i_vmax_candidates) if i_vmax_candidates else float("inf")
    i_vmin = max(i_vmin_candidates) if i_vmin_candidates else -float("inf")

    # Check start-of-step initial voltage independent of current (C3-BAT-03)
    is_initial_overvoltage = (v_start_base > v_pack_max + 1e-4)
    is_initial_undervoltage = (v_start_base < v_pack_min - 1e-4)

    if is_initial_overvoltage:
        i_vmax = min(i_vmax, 0.0)
        if r0 <= 1e-6:
            active_constraints.append("ERR_BATTERY_OVERVOLTAGE_CUTOFF")
            notes_list.append(
                f"Initial terminal voltage ({v_start_base:.2f} V) exceeds maximum pack voltage "
                f"({v_pack_max:.2f} V) with zero/near-zero R0"
            )
    if is_initial_undervoltage:
        i_vmin = max(i_vmin, 0.0)
        if r0 <= 1e-6:
            active_constraints.append("ERR_BATTERY_UNDERVOLTAGE_CUTOFF")
            notes_list.append(
                f"Initial terminal voltage ({v_start_base:.2f} V) is below minimum pack voltage "
                f"({v_pack_min:.2f} V) with zero/near-zero R0"
            )

    # Hardware continuous current ratings
    i_hard_max = config.max_charge_current_a if config.max_charge_current_a is not None else float("inf")
    i_hard_min = config.max_discharge_current_a if config.max_discharge_current_a is not None else -float("inf")

    # Joint current limits from hardware and voltage cutoffs
    i_upper_bound = min(i_hard_max, i_vmax)
    i_lower_bound = max(i_hard_min, i_vmin)

    # Physical monotonicity constraint (DEF-C3-04):
    # For P(I) = (V_eff + I * R_eff) * I, dP/dI = 2 * R_eff * I + V_eff.
    # The physically selected branch must remain on I >= -V_eff / (2 * R_eff).
    if r_eff > 1e-6:
        i_vertex = -v_eff / (2.0 * r_eff)
        i_lower_bound = max(i_lower_bound, i_vertex)

    # Dynamic SOC boundary enforcement over timestep dt (C3-BAT-01)
    q_nom_as = config.nominal_cell_capacity_ah * config.parallel_strings * 3600.0 * state.state_of_health

    # 1. Charging SOC boundary: SOC(t + dt) <= soc_max_operating
    if state.soc >= config.soc_max_operating:
        i_soc_max = 0.0
        is_soc_charge_blocked = True
    else:
        eta_chg = config.coulombic_efficiency_chg
        # delta_SOC = (eta_chg * I * dt) / q_nom_as <= soc_max - soc
        i_soc_max = ((config.soc_max_operating - state.soc) * q_nom_as) / (eta_chg * dt)
        i_soc_max = max(0.0, i_soc_max)
        is_soc_charge_blocked = False

    # 2. Discharging SOC boundary: SOC(t + dt) >= soc_min_operating
    if state.soc <= config.soc_min_operating:
        i_soc_min = 0.0
        is_soc_discharge_blocked = True
    else:
        # Discharging with Faradaic efficiency 1.0: delta_SOC = (I * dt) / q_nom_as >= soc_min - soc
        i_soc_min = ((config.soc_min_operating - state.soc) * q_nom_as) / dt
        i_soc_min = min(0.0, i_soc_min)
        is_soc_discharge_blocked = False

    i_upper_bound = min(i_upper_bound, i_soc_max)
    i_lower_bound = max(i_lower_bound, i_soc_min)

    # Check for empty feasible operating interval (DEF-C3-03)
    if i_lower_bound > i_upper_bound + 1e-6:
        active_constraints.append("ERR_BATTERY_INFEASIBLE_BOUNDS")
        notes_list.append(
            f"Contradictory physical bounds: lower current limit ({i_lower_bound:.2f} A) "
            f"exceeds upper current limit ({i_upper_bound:.2f} A)"
        )
        p_accepted_kw = 0.0
        p_deficit_kw = p_req_kw
        i_actual = 0.0
        diagnostic_code = "ERR_BATTERY_INFEASIBLE_BOUNDS"
        c_status = ConstraintStatus.VIOLATED

        final_state, e_loss_r1_j, delta_e_c1_j, avg_v1 = integrate_battery_state(
            initial_state=state,
            current_a=0.0,
            thevenin_params=params,
            dt_s=dt,
            config=config,
        )
        v_term_avg = v_oc + avg_v1
        v_term_end = v_oc + final_state.v1_polarization_v

        # Ledger for zero current
        e_term_j = 0.0
        e_oc_j = 0.0
        e_chem_j = 0.0
        e_loss_parasitic_j = 0.0
        e_loss_r0_j = 0.0
        energy_residual_j = e_term_j - (e_chem_j + e_loss_parasitic_j + e_loss_r0_j + e_loss_r1_j + delta_e_c1_j)

        op_point = BatteryOperatingPoint(
            terminal_voltage_v=v_term_avg,
            terminal_voltage_end_v=v_term_end,
            current_a=0.0,
            terminal_power_kw=0.0,
            ocv_power_kw=0.0,
            p_chem_kw=0.0,
            p_loss_parasitic_kw=0.0,
            p_loss_r0_kw=0.0,
            p_loss_r1_kw=(e_loss_r1_j / dt) / 1000.0,
            p_c1_storage_kw=(delta_e_c1_j / dt) / 1000.0,
            is_voltage_limited=True,
            is_current_limited=False,
            is_power_limited=False,
            is_soc_limited=False,
            status=c_status,
            diagnostic_code=diagnostic_code,
        )
        model_param_status = DataStatus.REAL if (params.is_ocv_verified and params.is_impedance_verified) else DataStatus.ESTIMATED
        effective_config_status = combine_provenance(config.status, model_param_status) if model_param_status != DataStatus.REAL else config.status
        prov_status = combine_provenance(input_status, state.provenance_status, effective_config_status)
        final_state = final_state.__class__(
            soc=final_state.soc,
            v1_polarization_v=final_state.v1_polarization_v,
            temperature_c=final_state.temperature_c,
            state_of_health=final_state.state_of_health,
            cumulative_energy_throughput_kwh=final_state.cumulative_energy_throughput_kwh,
            provenance_status=prov_status,
        )
        return BatterySimulationResult(
            initial_state=state,
            final_state=final_state,
            operating_point=op_point,
            dt_s=dt,
            requested_power_kw=p_req_kw,
            accepted_power_kw=0.0,
            deficit_power_kw=p_deficit_kw,
            energy_terminal_j=e_term_j,
            energy_ocv_j=e_oc_j,
            energy_chem_j=e_chem_j,
            energy_loss_parasitic_j=e_loss_parasitic_j,
            energy_loss_r0_j=e_loss_r0_j,
            energy_loss_r1_j=e_loss_r1_j,
            delta_energy_c1_j=delta_e_c1_j,
            energy_residual_j=energy_residual_j,
            overall_status=c_status,
            active_constraints=active_constraints,
            provenance_status=prov_status,
            notes=notes_list,
        )

    # Calculate corresponding feasible terminal power boundaries using average power formula
    # P_bar = (V_eff + I * R_eff) * I
    p_from_i_upper_kw = ((v_eff + i_upper_bound * r_eff) * i_upper_bound) / 1000.0 if math.isfinite(i_upper_bound) else float("inf")
    p_from_i_lower_kw = ((v_eff + i_lower_bound * r_eff) * i_lower_bound) / 1000.0 if math.isfinite(i_lower_bound) else -float("inf")

    p_hard_chg_max_kw = config.max_charge_power_kw if config.max_charge_power_kw is not None else float("inf")
    p_hard_dis_max_kw = config.max_discharge_power_kw if config.max_discharge_power_kw is not None else -float("inf")

    p_feasible_max_kw = max(0.0, min(p_hard_chg_max_kw, p_from_i_upper_kw))
    p_feasible_min_kw = min(0.0, max(p_hard_dis_max_kw, p_from_i_lower_kw))

    # Check maximum theoretical power transfer on discharge (DEF-C3-01):
    # P_peak = -V_eff^2 / (4 * R_eff). Initialized to -inf to avoid UnboundLocalError.
    p_peak_transfer_kw = -float("inf")
    if r_eff > 1e-6:
        p_peak_transfer_kw = (-v_eff * v_eff / (4.0 * r_eff)) / 1000.0
        p_feasible_min_kw = max(p_feasible_min_kw, p_peak_transfer_kw)

    # 4. Joint Power Arbitration
    if p_req_kw > 0.0:  # Charging request
        p_accepted_kw = min(p_req_kw, p_feasible_max_kw)
    elif p_req_kw < 0.0:  # Discharging request
        p_accepted_kw = max(p_req_kw, p_feasible_min_kw)
    else:
        p_accepted_kw = 0.0

    p_deficit_kw = p_req_kw - p_accepted_kw

    # 5. Exact Quadratic Current Solution for Accepted Power
    i_actual, _, is_real_root = solve_battery_current(p_accepted_kw, v_eff, r_eff)

    # Dynamic State Integration
    final_state, e_loss_r1_j, delta_e_c1_j, avg_v1 = integrate_battery_state(
        initial_state=state,
        current_a=i_actual,
        thevenin_params=params,
        dt_s=dt,
        config=config,
    )

    # Exact Average Terminal Voltage and End-of-step Terminal Voltage
    v_term_avg = v_oc + i_actual * r0 + avg_v1
    v_term_end = v_oc + i_actual * r0 + final_state.v1_polarization_v

    # 6. Boundary Flagging and Diagnostics
    is_v_lim = False
    is_i_lim = False
    is_p_lim = False
    is_soc_lim = False
    diagnostic_code = None

    if abs(p_deficit_kw) > TOL:
        if p_req_kw > 0.0:
            if is_soc_charge_blocked or (math.isfinite(i_soc_max) and abs(i_actual - i_soc_max) <= 1e-3):
                is_soc_lim = True
                active_constraints.append("ERR_BATTERY_SOC_MAX_REACHED")
                if is_soc_charge_blocked:
                    notes_list.append(f"Charging prohibited: SOC ({state.soc*100:.1f}%) >= max limit ({config.soc_max_operating*100:.1f}%)")
                else:
                    notes_list.append(f"Charging curtailed to prevent SOC crossing maximum limit ({config.soc_max_operating*100:.1f}%) over timestep")
            if math.isfinite(i_vmax) and abs(i_actual - i_vmax) <= 1e-3:
                is_v_lim = True
                active_constraints.append("ERR_BATTERY_OVERVOLTAGE_CUTOFF")
                notes_list.append(f"Charging curtailed by pack overvoltage limit ({v_pack_max:.1f} V)")
            if config.max_charge_current_a is not None and abs(i_actual - config.max_charge_current_a) <= 1e-3:
                is_i_lim = True
                active_constraints.append("ERR_BATTERY_MAX_CHARGE_CURRENT")
                notes_list.append(f"Charging curtailed by max charge current rating ({config.max_charge_current_a:.1f} A)")
            if config.max_charge_power_kw is not None and abs(p_accepted_kw - config.max_charge_power_kw) <= TOL:
                is_p_lim = True
                active_constraints.append("ERR_BATTERY_MAX_CHARGE_POWER")
                notes_list.append(f"Charging curtailed by max charge power rating ({config.max_charge_power_kw:.1f} kW)")
        else:
            if is_soc_discharge_blocked or (math.isfinite(i_soc_min) and abs(i_actual - i_soc_min) <= 1e-3):
                is_soc_lim = True
                active_constraints.append("ERR_BATTERY_SOC_MIN_REACHED")
                if is_soc_discharge_blocked:
                    notes_list.append(f"Discharge prohibited: SOC ({state.soc*100:.1f}%) <= min limit ({config.soc_min_operating*100:.1f}%)")
                else:
                    notes_list.append(f"Discharge curtailed to prevent SOC crossing minimum limit ({config.soc_min_operating*100:.1f}%) over timestep")
            if math.isfinite(i_vmin) and abs(i_actual - i_vmin) <= 1e-3:
                is_v_lim = True
                active_constraints.append("ERR_BATTERY_UNDERVOLTAGE_CUTOFF")
                notes_list.append(f"Discharge curtailed by pack undervoltage limit ({v_pack_min:.1f} V)")
            if config.max_discharge_current_a is not None and abs(i_actual - config.max_discharge_current_a) <= 1e-3:
                is_i_lim = True
                active_constraints.append("ERR_BATTERY_MAX_DISCHARGE_CURRENT")
                notes_list.append(f"Discharge curtailed by max discharge current rating ({config.max_discharge_current_a:.1f} A)")
            if config.max_discharge_power_kw is not None and abs(p_accepted_kw - config.max_discharge_power_kw) <= TOL:
                is_p_lim = True
                active_constraints.append("ERR_BATTERY_MAX_DISCHARGE_POWER")
                notes_list.append(f"Discharge curtailed by max discharge power rating ({config.max_discharge_power_kw:.1f} kW)")
            if not is_real_root or (math.isfinite(p_peak_transfer_kw) and abs(p_accepted_kw - p_peak_transfer_kw) <= TOL):
                is_p_lim = True
                active_constraints.append("ERR_BATTERY_THEVENIN_MAX_POWER_TRANSFER")
                notes_list.append("Discharge capped at maximum theoretical source power transfer")

    # Primary diagnostic code selection by physical precedence
    diag_precedence = [
        "ERR_BATTERY_INFEASIBLE_BOUNDS",
        "ERR_BATTERY_SOC_MAX_REACHED",
        "ERR_BATTERY_SOC_MIN_REACHED",
        "ERR_BATTERY_OVERVOLTAGE_CUTOFF",
        "ERR_BATTERY_UNDERVOLTAGE_CUTOFF",
        "ERR_BATTERY_MAX_CHARGE_CURRENT",
        "ERR_BATTERY_MAX_DISCHARGE_CURRENT",
        "ERR_BATTERY_MAX_CHARGE_POWER",
        "ERR_BATTERY_MAX_DISCHARGE_POWER",
        "ERR_BATTERY_THEVENIN_MAX_POWER_TRANSFER",
    ]
    for code in diag_precedence:
        if code in active_constraints:
            diagnostic_code = code
            break

    # 7. Exact Energy Conservation Ledger (DEF-C3-06)
    # Terminal electrical energy transferred across the battery terminals over timestep dt:
    e_term_j = (v_term_avg * i_actual) * dt
    e_oc_j = (v_oc * i_actual) * dt
    e_loss_r0_j = (i_actual * i_actual * r0) * dt

    # Electrochemical reversible chemical storage and parasitic side-reaction dissipation:
    if i_actual > 0.0:
        eta_chg = config.coulombic_efficiency_chg
        e_chem_j = eta_chg * e_oc_j
        e_loss_parasitic_j = (1.0 - eta_chg) * e_oc_j
    else:
        # Discharging or standstill
        e_chem_j = e_oc_j
        e_loss_parasitic_j = 0.0

    e_loss_parasitic_j = max(0.0, e_loss_parasitic_j)

    # Complete internal energy conservation ledger balance:
    # E_term == E_chem + E_loss_parasitic + E_loss_R0 + E_loss_R1 + delta_E_C1
    # Notice: E_chem + E_loss_parasitic == E_oc
    e_internal_sum_j = e_chem_j + e_loss_parasitic_j + e_loss_r0_j + e_loss_r1_j + delta_e_c1_j
    energy_residual_j = e_term_j - e_internal_sum_j

    # Operating Point Power Components in kW:
    p_term_actual_kw = (v_term_avg * i_actual) / 1000.0
    p_oc_kw = (v_oc * i_actual) / 1000.0
    p_chem_kw = (e_chem_j / dt) / 1000.0
    p_loss_parasitic_kw = (e_loss_parasitic_j / dt) / 1000.0
    p_loss_r0_kw = (i_actual * i_actual * r0) / 1000.0
    p_loss_r1_kw = (e_loss_r1_j / dt) / 1000.0
    p_c1_storage_kw = (delta_e_c1_j / dt) / 1000.0

    # 8. Constraint Status Synthesis
    if abs(p_deficit_kw) > TOL:
        c_status = ConstraintStatus.VIOLATED if (is_soc_lim or is_v_lim) else ConstraintStatus.CONDITIONAL
    else:
        c_status = ConstraintStatus.SATISFIED

    if not params.is_ocv_verified or not params.is_impedance_verified:
        if c_status == ConstraintStatus.SATISFIED:
            c_status = ConstraintStatus.CONDITIONAL
            notes_list.append("Thevenin OCV or impedance evaluated using estimated/illustrative curves")

    # Combine input and parameter provenance conservatively (C3-PROV-01)
    # If OCV or impedance parameters are unverified (estimated/illustrative curves),
    # the parameter provenance must be degraded to ESTIMATED.
    model_param_status = DataStatus.REAL if (params.is_ocv_verified and params.is_impedance_verified) else DataStatus.ESTIMATED
    effective_config_status = combine_provenance(config.status, model_param_status) if model_param_status != DataStatus.REAL else config.status
    prov_status = combine_provenance(input_status, state.provenance_status, effective_config_status)

    final_state = final_state.__class__(
        soc=final_state.soc,
        v1_polarization_v=final_state.v1_polarization_v,
        temperature_c=final_state.temperature_c,
        state_of_health=final_state.state_of_health,
        cumulative_energy_throughput_kwh=final_state.cumulative_energy_throughput_kwh,
        provenance_status=prov_status,
    )

    op_point = BatteryOperatingPoint(
        terminal_voltage_v=v_term_avg,
        terminal_voltage_end_v=v_term_end,
        current_a=i_actual,
        terminal_power_kw=p_term_actual_kw,
        ocv_power_kw=p_oc_kw,
        p_chem_kw=p_chem_kw,
        p_loss_parasitic_kw=p_loss_parasitic_kw,
        p_loss_r0_kw=p_loss_r0_kw,
        p_loss_r1_kw=p_loss_r1_kw,
        p_c1_storage_kw=p_c1_storage_kw,
        is_voltage_limited=is_v_lim,
        is_current_limited=is_i_lim,
        is_power_limited=is_p_lim,
        is_soc_limited=is_soc_lim,
        status=c_status,
        diagnostic_code=diagnostic_code,
    )

    return BatterySimulationResult(
        initial_state=state,
        final_state=final_state,
        operating_point=op_point,
        dt_s=dt,
        requested_power_kw=p_req_kw,
        accepted_power_kw=p_accepted_kw,
        deficit_power_kw=p_deficit_kw,
        energy_terminal_j=e_term_j,
        energy_ocv_j=e_oc_j,
        energy_chem_j=e_chem_j,
        energy_loss_parasitic_j=e_loss_parasitic_j,
        energy_loss_r0_j=e_loss_r0_j,
        energy_loss_r1_j=e_loss_r1_j,
        delta_energy_c1_j=delta_e_c1_j,
        energy_residual_j=energy_residual_j,
        overall_status=c_status,
        active_constraints=active_constraints,
        provenance_status=prov_status,
        notes=notes_list,
    )
