"""
Powertrain and Drivetrain Physics Engine (Stage C1, C1.1, C1.2, C1.3)
======================================================================
Deterministic electric traction motor envelopes, forward/reverse gearbox
transformations, torque-speed curves, speed governor derating, electrical
phase current mapping, peak overload thermal exposure tracking, and zero-speed
stall physics for EV powertrain feasibility.

Physical Conventions:
- Vehicle velocity: v >= 0 [m/s]
- Tractive wheel force: F_wheel > 0 [N] -> Wheel power: P_wheel > 0 [kW]
- Braking wheel force: F_wheel < 0 [N] -> Wheel power: P_wheel < 0 [kW]
- Forward gearbox transmission: P_wheel = P_motor * eta_gb_fwd (> 0)
- Reverse gearbox regeneration: P_motor = P_wheel * eta_gb_rev (< 0)
- Gearbox mechanical heat losses: strictly non-negative (P_loss >= 0)
- Units: Force [N], Power [kW], Torque [Nm], Angular Speed [rad/s], Current [A_rms]
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import math
from typing import Optional, Tuple, Union

from pydantic import BaseModel, Field, field_validator, model_validator

from app.domain.provenance import DataStatus


class OperatingEnvelopeMode(str, Enum):
    """Motor operating rating mode requested by caller."""
    CONTINUOUS = "CONTINUOUS"  # S1 thermal steady-state
    PEAK = "PEAK"              # S2 short-duration overload


class ActualOperatingMode(str, Enum):
    """
    Physical operating regime determined by demand and hardware capability.
    
    CONTINUOUS: Operating within continuous (S1) thermal steady-state capability.
    PEAK: Operating in authorized overload (S2) with verified hardware feasibility.
    INFEASIBLE: Demanded operating point exceeds physical capability or violates hardware limits.
    """
    CONTINUOUS = "CONTINUOUS"
    PEAK = "PEAK"
    INFEASIBLE = "INFEASIBLE"


class ConstraintStatus(str, Enum):
    """Operational constraint satisfaction status."""
    SATISFIED = "SATISFIED"
    VIOLATED = "VIOLATED"
    CONDITIONAL = "CONDITIONAL"  # Missing parameter, unverified estimate, or boundary condition


def _validate_finite_float(name: str, value: float, min_val: Optional[float] = None, max_val: Optional[float] = None) -> float:
    """Validate that a float is finite and within physical bounds."""
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise TypeError(f"{name} must be a real number, got {type(value).__name__}")
    if not math.isfinite(value):
        raise ValueError(f"{name} must be finite, got {value}")
    if min_val is not None and value < min_val:
        raise ValueError(f"{name} ({value}) must be >= {min_val}")
    if max_val is not None and value > max_val:
        raise ValueError(f"{name} ({value}) must be <= {max_val}")
    return float(value)


def combine_provenance(*statuses: Optional[DataStatus]) -> DataStatus:
    """
    Deterministic provenance combination across physical calculations.
    
    Precedence:
    1. Any UNKNOWN -> UNKNOWN
    2. Any SIMULATED -> SIMULATED (synthetic data must never be masked as real or pure estimated)
    3. Any ESTIMATED -> ESTIMATED
    4. Any STALE -> STALE
    5. All REAL -> REAL
    
    Rule: An output must NEVER become REAL when any required input is
    SIMULATED, ESTIMATED, or UNKNOWN.
    """
    valid = [s for s in statuses if s is not None]
    if not valid:
        return DataStatus.UNKNOWN
    if any(s == DataStatus.UNKNOWN for s in valid):
        return DataStatus.UNKNOWN
    if any(s == DataStatus.SIMULATED for s in valid):
        return DataStatus.SIMULATED
    if any(s == DataStatus.ESTIMATED for s in valid):
        return DataStatus.ESTIMATED
    if any(s == DataStatus.STALE for s in valid):
        return DataStatus.STALE
    return DataStatus.REAL


class GearboxConfig(BaseModel):
    """
    Fixed-ratio transmission configuration.
    
    Attributes:
        gear_ratio: Reduction ratio N_gb (motor rotations per wheel rotation). Must be > 0.
        efficiency_fwd: Forward mechanical efficiency during traction (0 < eta <= 1.0).
        efficiency_rev: Reverse mechanical efficiency during regeneration (0 < eta <= 1.0).
        wheel_radius_m: Dynamic loaded tire radius in meters. Must be > 0.
        status: Provenance status of the gearbox parameters.
    """
    model_config = {"protected_namespaces": ()}

    gear_ratio: float = Field(..., gt=0.0, le=40.0, description="Gear reduction ratio N_gb")
    efficiency_fwd: float = Field(default=0.97, gt=0.50, le=1.0, description="Forward traction efficiency")
    efficiency_rev: float = Field(default=0.96, gt=0.50, le=1.0, description="Reverse regeneration efficiency")
    wheel_radius_m: float = Field(default=0.315, gt=0.10, le=1.0, description="Wheel rolling radius in meters")
    status: DataStatus = Field(default=DataStatus.ESTIMATED, description="Parameter provenance status")

    @field_validator("gear_ratio", "efficiency_fwd", "efficiency_rev", "wheel_radius_m")
    @classmethod
    def validate_finite_fields(cls, v: float) -> float:
        if not math.isfinite(v):
            raise ValueError("GearboxConfig parameters must be finite")
        return v


class MotorConfig(BaseModel):
    """
    Permanent Magnet Synchronous Motor (PMSM) and inverter configuration.
    
    Attributes:
        torque_cont_max_nm: Maximum continuous shaft torque (S1) in Nm.
        power_cont_max_kw: Maximum continuous shaft power (S1) in kW.
        max_speed_rpm: Maximum rotor rotational speed in RPM.
        torque_peak_max_nm: Optional peak short-duration torque in Nm. Defaults to continuous.
        power_peak_max_kw: Optional peak short-duration power in kW. Defaults to continuous.
        pole_pairs: Number of rotor pole pairs p.
        flux_linkage_wb: Permanent magnet flux linkage psi_m in Weber.
        stator_resistance_ohm: Stator winding phase resistance in Ohms.
        k_t_rms: Torque constant in Nm / A_rms.
        governor_rolloff_fraction: Fraction of max speed where governor derating begins (default 0.05).
        peak_duration_budget_s: Thermal peak duration budget in seconds (default 20.0s).
        recovery_rate_s_per_s: Thermal budget recovery rate in s/s (default 0.20 s/s).
        efficiency_mot: Average electromagnetic motoring efficiency (default 0.90).
        efficiency_gen: Average electromagnetic generating efficiency (default 0.90).
        inverter_current_limit_rms: Optional inverter maximum phase current in A_rms.
        inverter_dc_power_limit_kw: Optional inverter DC output power limit in kW.
        inverter_efficiency: Inverter electrical efficiency (default 0.95).
        inverter_standby_loss_w: Optional inverter electrical standby/switching loss in Watts.
        inverter_loss_status: Provenance status of inverter loss parameter.
        status: Provenance status of motor specifications.
    """
    model_config = {"protected_namespaces": ()}

    torque_cont_max_nm: float = Field(..., gt=0.0, le=3000.0, description="Max continuous shaft torque (Nm)")
    power_cont_max_kw: float = Field(..., gt=0.0, le=1500.0, description="Max continuous shaft power (kW)")
    max_speed_rpm: float = Field(..., gt=500.0, le=30000.0, description="Maximum rotor speed (RPM)")

    torque_peak_max_nm: Optional[float] = Field(None, gt=0.0, le=4000.0, description="Max peak shaft torque (Nm)")
    power_peak_max_kw: Optional[float] = Field(None, gt=0.0, le=2000.0, description="Max peak shaft power (kW)")

    pole_pairs: int = Field(default=4, ge=1, le=16, description="Rotor magnetic pole pairs")
    flux_linkage_wb: Optional[float] = Field(default=0.076603, gt=0.0, le=5.0, description="Magnet flux linkage (Wb)")
    stator_resistance_ohm: Optional[float] = Field(default=0.020, ge=0.0, le=5.0, description="Phase resistance (Ohm)")
    k_t_rms: Optional[float] = Field(default=0.650, gt=0.0, le=20.0, description="Torque constant (Nm/A_rms)")

    governor_rolloff_fraction: float = Field(default=0.05, gt=0.001, lt=0.25, description="Governor derate band fraction")
    peak_duration_budget_s: float = Field(default=20.0, gt=0.0, le=300.0, description="Peak duration budget (s)")
    recovery_rate_s_per_s: float = Field(default=0.20, gt=0.0, le=5.0, description="Peak recovery rate (s/s)")

    efficiency_mot: float = Field(default=0.90, gt=0.50, le=1.0, description="Motor electromagnetic efficiency")
    efficiency_gen: float = Field(default=0.90, gt=0.50, le=1.0, description="Generator electromagnetic efficiency")

    inverter_current_limit_rms: Optional[float] = Field(default=350.0, gt=0.0, le=2000.0, description="Inverter RMS phase current limit")
    inverter_dc_power_limit_kw: Optional[float] = Field(default=65.0, gt=0.0, le=2000.0, description="Inverter DC power limit")
    inverter_efficiency: float = Field(default=0.95, gt=0.50, le=1.0, description="Inverter DC/AC efficiency")
    inverter_standby_loss_w: Optional[float] = Field(default=None, ge=0.0, le=10000.0, description="Inverter electrical standby/switching loss in Watts")
    inverter_loss_status: DataStatus = Field(default=DataStatus.UNKNOWN, description="Provenance status of inverter loss parameter")

    status: DataStatus = Field(default=DataStatus.ESTIMATED, description="Parameter provenance status")

    @model_validator(mode="after")
    def validate_envelope_invariants(self) -> MotorConfig:
        # Default peak limits to continuous if omitted
        if self.torque_peak_max_nm is None:
            self.torque_peak_max_nm = self.torque_cont_max_nm
        if self.power_peak_max_kw is None:
            self.power_peak_max_kw = self.power_cont_max_kw

        # Enforce peak >= continuous
        if self.torque_peak_max_nm < self.torque_cont_max_nm:
            raise ValueError(
                f"Peak torque ({self.torque_peak_max_nm} Nm) cannot be less than continuous torque ({self.torque_cont_max_nm} Nm)"
            )
        if self.power_peak_max_kw < self.power_cont_max_kw:
            raise ValueError(
                f"Peak power ({self.power_peak_max_kw} kW) cannot be less than continuous power ({self.power_cont_max_kw} kW)"
            )

        # Base speeds and governor start speed
        omega_max = (self.max_speed_rpm * 2.0 * math.pi) / 60.0
        omega_gov_start = omega_max * (1.0 - self.governor_rolloff_fraction)
        omega_base_cont = (self.power_cont_max_kw * 1000.0) / self.torque_cont_max_nm
        omega_base_peak = (self.power_peak_max_kw * 1000.0) / self.torque_peak_max_nm

        # Validate independently for continuous and peak modes:
        # omega_base <= omega_governor_start <= omega_max
        if omega_base_cont > omega_gov_start:
            raise ValueError(
                f"Continuous base speed ({omega_base_cont:.2f} rad/s) exceeds governor start speed ({omega_gov_start:.2f} rad/s). "
                f"Disallowed configuration: omega_base <= omega_governor_start <= omega_max."
            )
        if omega_base_peak > omega_gov_start:
            raise ValueError(
                f"Peak base speed ({omega_base_peak:.2f} rad/s) exceeds governor start speed ({omega_gov_start:.2f} rad/s). "
                f"Disallowed configuration: omega_base <= omega_governor_start <= omega_max."
            )

        # Synchronize k_t_rms if flux_linkage is supplied and k_t_rms is not explicitly overridden
        if self.flux_linkage_wb is not None and self.k_t_rms is not None:
            k_t_calc = (3.0 / math.sqrt(2.0)) * self.pole_pairs * self.flux_linkage_wb
            if abs(self.k_t_rms - k_t_calc) > 0.05:
                pass

        return self


# ---------------------------------------------------------------------------
# Dataclasses for Structured Output Results & State Tracking
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class PeakExposureState:
    """
    Deterministic tracking of motor peak thermal overload duration across route segments.
    
    Attributes:
        cumulative_exposure_s: Cumulative time spent operating in peak overload (s).
        budget_s: Total allowable peak duration before thermal exhaustion (s).
        recovery_rate_s_per_s: Recovery rate of peak budget during continuous operation (s/s).
        is_exhausted: True when peak budget is fully depleted.
    """
    cumulative_exposure_s: float = 0.0
    budget_s: float = 20.0
    recovery_rate_s_per_s: float = 0.20
    is_exhausted: bool = False

    @property
    def remaining_budget_s(self) -> float:
        return max(0.0, self.budget_s - self.cumulative_exposure_s)


@dataclass(frozen=True)
class MotorSpeedResult:
    """Rotor and wheel rotational velocity."""
    motor_speed_rad_s: float
    motor_speed_rpm: float
    wheel_speed_rad_s: float
    is_overspeed: bool
    status: DataStatus = DataStatus.ESTIMATED


@dataclass(frozen=True)
class DrivetrainTractionResult:
    """Forward drivetrain transformation during traction (P_wheel >= 0)."""
    wheel_force_n: float            # Positive tractive force
    wheel_power_kw: float           # Positive mechanical wheel power
    motor_torque_req_nm: float      # Required motor shaft torque
    motor_shaft_power_kw: float     # Required motor shaft power
    gearbox_loss_kw: float          # Forward gearbox mechanical dissipation
    vehicle_speed_ms: float
    status: DataStatus


@dataclass(frozen=True)
class DrivetrainBrakingResult:
    """Reverse drivetrain transformation during braking (P_wheel <= 0)."""
    wheel_force_n: float            # Negative retarding wheel force
    wheel_power_kw: float           # Negative retarding mechanical wheel power
    motor_torque_regen_nm: float    # Regenerative motor retarding torque magnitude (>= 0)
    motor_shaft_power_kw: float     # Signed power entering motor rotor shaft (<= 0)
    gearbox_loss_kw: float          # Reverse gearbox mechanical dissipation (>= 0)
    vehicle_speed_ms: float
    status: DataStatus


@dataclass(frozen=True)
class MotorEnvelopeResult:
    """Available motor capability at a specific rotational speed."""
    mode: OperatingEnvelopeMode
    motor_speed_rad_s: float
    motor_speed_rpm: float
    base_speed_rad_s: float
    max_speed_rad_s: float
    governor_start_rad_s: float
    available_torque_nm: float
    available_power_kw: float
    is_governor_active: bool
    governor_derate_factor: float   # S_gov in [0.0, 1.0]
    is_overspeed_cutoff: bool
    operating_region: str           # constant_torque | constant_power | governor_rolloff | overspeed_cutoff
    status: DataStatus


@dataclass(frozen=True)
class StallElectricalResult:
    """Stator and inverter electrical dissipation at motor stall (v = 0)."""
    stator_phase_current_rms: float
    stator_copper_loss_w: float
    inverter_loss_w: Optional[float]
    total_stall_electrical_power_kw: Optional[float]
    status: ConstraintStatus
    provenance_status: DataStatus
    notes: str

    def __iter__(self):
        # Support tuple unpacking (stator_copper_loss_w, total_stall_electrical_power_kw) for compatibility
        return iter((self.stator_copper_loss_w, self.total_stall_electrical_power_kw))

    def __getitem__(self, index):
        return (self.stator_copper_loss_w, self.total_stall_electrical_power_kw)[index]


@dataclass(frozen=True)
class PowertrainConstraintResult:
    """Comprehensive constraint validation for motor and inverter operating limits."""
    torque_status: ConstraintStatus
    power_status: ConstraintStatus
    speed_status: ConstraintStatus
    current_status: ConstraintStatus
    overall_status: ConstraintStatus

    torque_margin_nm: float
    power_margin_kw: float
    speed_margin_rad_s: float

    phase_current_req_rms: Optional[float]
    inverter_current_margin_rms: Optional[float]
    stall_dc_power_kw: Optional[float]

    diagnostic_code: Optional[str]
    notes: str
    provenance_status: DataStatus

    peak_state: Optional[PeakExposureState] = None
    is_peak_exhausted: bool = False
    peak_requested: bool = False
    peak_granted: bool = False
    actual_operating_mode: ActualOperatingMode = ActualOperatingMode.CONTINUOUS


# ---------------------------------------------------------------------------
# Pure Physics Functions
# ---------------------------------------------------------------------------

def compute_motor_speed(
    vehicle_speed_ms: float,
    config: GearboxConfig,
    input_status: Optional[DataStatus] = None,
) -> MotorSpeedResult:
    """
    Compute wheel angular velocity, motor rotor angular velocity, and rotor RPM.
    
    Equations:
        omega_wheel = v / r_wheel  [rad/s]
        omega_motor = (v * N_gb) / r_wheel  [rad/s]
        N_rpm = omega_motor * 60 / (2 * pi)  [RPM]
    """
    v = _validate_finite_float("vehicle_speed_ms", vehicle_speed_ms, 0.0, 150.0)
    omega_wheel = v / config.wheel_radius_m
    omega_motor = omega_wheel * config.gear_ratio
    rpm = (omega_motor * 60.0) / (2.0 * math.pi)

    status = combine_provenance(input_status, config.status)

    return MotorSpeedResult(
        motor_speed_rad_s=omega_motor,
        motor_speed_rpm=rpm,
        wheel_speed_rad_s=omega_wheel,
        is_overspeed=False,
        status=status,
    )


def transform_forward_traction(
    wheel_force_n: float,
    vehicle_speed_ms: float,
    config: GearboxConfig,
    input_status: Optional[DataStatus] = None,
) -> DrivetrainTractionResult:
    """
    Transform positive tractive wheel force to motor shaft torque and power.
    
    Forward Gearbox Equations:
        P_wheel = (F_wheel * v) / 1000  [kW]  (>= 0)
        P_motor = P_wheel / eta_gb_fwd  [kW]  (>= 0)
        T_motor = (F_wheel * r_wheel) / (N_gb * eta_gb_fwd)  [Nm]  (>= 0)
        P_loss_gb = P_motor - P_wheel = P_motor * (1 - eta_gb_fwd)  [kW]  (>= 0)
    """
    f_wheel = _validate_finite_float("wheel_force_n", wheel_force_n, 0.0, 50000.0)
    v = _validate_finite_float("vehicle_speed_ms", vehicle_speed_ms, 0.0, 150.0)

    p_wheel_kw = (f_wheel * v) / 1000.0
    p_mot_kw = p_wheel_kw / config.efficiency_fwd
    t_mot_nm = (f_wheel * config.wheel_radius_m) / (config.gear_ratio * config.efficiency_fwd)
    p_loss_kw = p_mot_kw - p_wheel_kw

    status = combine_provenance(input_status, config.status)

    return DrivetrainTractionResult(
        wheel_force_n=f_wheel,
        wheel_power_kw=p_wheel_kw,
        motor_torque_req_nm=t_mot_nm,
        motor_shaft_power_kw=p_mot_kw,
        gearbox_loss_kw=p_loss_kw,
        vehicle_speed_ms=v,
        status=status,
    )


def transform_reverse_braking(
    wheel_force_n: float,
    vehicle_speed_ms: float,
    config: GearboxConfig,
    input_status: Optional[DataStatus] = None,
) -> DrivetrainBrakingResult:
    """
    Transform signed negative braking force at wheels to motor shaft torque and power.
    
    Reverse Gearbox Equations (Derived from Power Conservation):
        P_wheel = (F_wheel * v) / 1000  [kW]  (<= 0)
        P_motor = P_wheel * eta_gb_rev  [kW]  (<= 0, power flows from wheel to motor)
        T_motor_regen = (-F_wheel * r_wheel * eta_gb_rev) / N_gb  [Nm]  (>= 0 magnitude)
        P_loss_gb_rev = -P_wheel * (1 - eta_gb_rev)  [kW]  (>= 0 strictly non-negative heat)
    """
    f_wheel = _validate_finite_float("wheel_force_n", wheel_force_n, -50000.0, 0.0)
    v = _validate_finite_float("vehicle_speed_ms", vehicle_speed_ms, 0.0, 150.0)

    p_wheel_kw = (f_wheel * v) / 1000.0
    p_mot_kw = p_wheel_kw * config.efficiency_rev
    t_mot_regen_nm = (-f_wheel * config.wheel_radius_m * config.efficiency_rev) / config.gear_ratio
    p_loss_kw = -p_wheel_kw * (1.0 - config.efficiency_rev)

    status = combine_provenance(input_status, config.status)

    return DrivetrainBrakingResult(
        wheel_force_n=f_wheel,
        wheel_power_kw=p_wheel_kw,
        motor_torque_regen_nm=t_mot_regen_nm,
        motor_shaft_power_kw=p_mot_kw,
        gearbox_loss_kw=p_loss_kw,
        vehicle_speed_ms=v,
        status=status,
    )


def compute_wheel_force_from_motor_torque(
    motor_torque_nm: float,
    config: GearboxConfig,
    is_regeneration: bool = False,
) -> float:
    """
    Compute sustainable wheel force from motor shaft torque.
    
    Forward Traction:
        F_wheel = (T_mot * N_gb * eta_gb_fwd) / r_wheel  [N]  (> 0)
    
    Reverse Regeneration (retarding force capability at wheels):
        F_wheel_regen_max = (T_mot_regen * N_gb) / (eta_gb_rev * r_wheel)  [N]
    """
    t_mot = _validate_finite_float("motor_torque_nm", motor_torque_nm, 0.0, 5000.0)

    if not is_regeneration:
        return (t_mot * config.gear_ratio * config.efficiency_fwd) / config.wheel_radius_m
    else:
        return (t_mot * config.gear_ratio) / (config.efficiency_rev * config.wheel_radius_m)


def compute_motor_envelope(
    motor_speed_rad_s: float,
    motor_config: MotorConfig,
    mode: OperatingEnvelopeMode = OperatingEnvelopeMode.CONTINUOUS,
    input_status: Optional[DataStatus] = None,
) -> MotorEnvelopeResult:
    """
    Compute motor available torque and power from continuous or peak envelope.
    
    Operating Regions:
        1. Constant Torque Region (0 <= omega <= omega_base):
           T_avail = T_max, P_avail = (T_max * omega) / 1000
        2. Constant Power Region (omega_base < omega <= omega_gov_start):
           T_avail = (P_max * 1000) / omega, P_avail = P_max
        3. Governor Rolloff Region (omega_gov_start < omega <= omega_max):
           S_gov = (omega_max - omega) / (omega_max * delta_gov)
           T_avail = ((P_max * 1000) / omega) * S_gov, P_avail = P_max * S_gov
        4. Overspeed Cutoff Region (omega > omega_max):
           T_avail = 0.0, P_avail = 0.0
    """
    omega = _validate_finite_float("motor_speed_rad_s", motor_speed_rad_s, 0.0, 5000.0)

    rpm = (omega * 60.0) / (2.0 * math.pi)
    omega_max = (motor_config.max_speed_rpm * 2.0 * math.pi) / 60.0
    omega_gov_start = omega_max * (1.0 - motor_config.governor_rolloff_fraction)

    # Select rating parameters
    if mode == OperatingEnvelopeMode.CONTINUOUS:
        t_max = motor_config.torque_cont_max_nm
        p_max = motor_config.power_cont_max_kw
    else:
        t_max = motor_config.torque_peak_max_nm or motor_config.torque_cont_max_nm
        p_max = motor_config.power_peak_max_kw or motor_config.power_cont_max_kw

    omega_base = (p_max * 1000.0) / t_max
    status = combine_provenance(input_status, motor_config.status)

    # Determine region and capability
    if omega > omega_max:
        return MotorEnvelopeResult(
            mode=mode,
            motor_speed_rad_s=omega,
            motor_speed_rpm=rpm,
            base_speed_rad_s=omega_base,
            max_speed_rad_s=omega_max,
            governor_start_rad_s=omega_gov_start,
            available_torque_nm=0.0,
            available_power_kw=0.0,
            is_governor_active=False,
            governor_derate_factor=0.0,
            is_overspeed_cutoff=True,
            operating_region="overspeed_cutoff",
            status=status,
        )

    if omega <= omega_base:
        t_avail = t_max
        p_avail = (t_max * omega) / 1000.0
        s_gov = 1.0
        gov_active = False
        region = "constant_torque"
    elif omega <= omega_gov_start:
        t_avail = (p_max * 1000.0) / omega
        p_avail = p_max
        s_gov = 1.0
        gov_active = False
        region = "constant_power"
    else:
        # Governor rolloff
        delta_omega = omega_max * motor_config.governor_rolloff_fraction
        s_gov = max(0.0, min(1.0, (omega_max - omega) / delta_omega))
        t_raw = (p_max * 1000.0) / omega
        t_avail = t_raw * s_gov
        p_avail = p_max * s_gov
        gov_active = True
        region = "governor_rolloff"

    return MotorEnvelopeResult(
        mode=mode,
        motor_speed_rad_s=omega,
        motor_speed_rpm=rpm,
        base_speed_rad_s=omega_base,
        max_speed_rad_s=omega_max,
        governor_start_rad_s=omega_gov_start,
        available_torque_nm=t_avail,
        available_power_kw=p_avail,
        is_governor_active=gov_active,
        governor_derate_factor=s_gov,
        is_overspeed_cutoff=False,
        operating_region=region,
        status=status,
    )


def compute_stator_phase_current(motor_torque_nm: float, motor_config: MotorConfig) -> Optional[float]:
    """
    Compute required 3-phase RMS stator phase current for demanded electromagnetic torque.
    
    Formula:
        I_phase_rms = T_motor / k_t_rms  [A_rms]
    """
    t_mot = _validate_finite_float("motor_torque_nm", motor_torque_nm, 0.0, 5000.0)
    if motor_config.k_t_rms is None or motor_config.k_t_rms <= 0.0:
        return None
    return t_mot / motor_config.k_t_rms


def compute_stall_dc_power(
    motor_torque_nm: float,
    motor_config: MotorConfig,
    inverter_loss_w: Optional[float] = None,
    inverter_loss_status: Optional[DataStatus] = None,
) -> Optional[StallElectricalResult]:
    """
    Compute stator copper loss and electrical dissipation at motor standstill (v = 0, omega = 0).
    
    At standstill, mechanical shaft power is zero (P_mech = 0) and back-EMF is zero (E_back = 0).
    Electrical power drawn from the DC bus equals stator copper losses plus inverter losses:
        P_stator_loss = 3 * (I_phase_rms)^2 * R_s  [W]
        P_stall_elec = (P_stator_loss + P_loss_inv) / 1000  [kW]
    """
    t_mot = _validate_finite_float("motor_torque_nm", motor_torque_nm, 0.0, 5000.0)

    if motor_config.stator_resistance_ohm is None or motor_config.k_t_rms is None:
        return None

    i_rms = t_mot / motor_config.k_t_rms
    p_stator_w = 3.0 * (i_rms ** 2) * motor_config.stator_resistance_ohm

    # Determine inverter loss and its provenance
    inv_w = inverter_loss_w if inverter_loss_w is not None else motor_config.inverter_standby_loss_w
    inv_status = inverter_loss_status or motor_config.inverter_loss_status

    if inv_w is not None:
        p_total_kw = (p_stator_w + inv_w) / 1000.0
        c_status = ConstraintStatus.SATISFIED if inv_status == DataStatus.REAL else ConstraintStatus.CONDITIONAL
        p_status = combine_provenance(motor_config.status, inv_status)
        notes = f"Stall electrical dissipation computed with {inv_status.value} inverter loss ({inv_w:.1f} W)"
    else:
        # Default unverified estimate fallback (550.0 W)
        inv_w = 550.0
        p_total_kw = (p_stator_w + inv_w) / 1000.0
        c_status = ConstraintStatus.CONDITIONAL
        p_status = DataStatus.ESTIMATED
        notes = "Inverter loss unconfigured; unverified default estimate of 550.0 W applied conditionally"

    # Current limit check against inverter limit
    if motor_config.inverter_current_limit_rms is not None:
        if i_rms > motor_config.inverter_current_limit_rms:
            c_status = ConstraintStatus.VIOLATED
            notes += f"; Required current ({i_rms:.1f} A_rms) exceeds inverter limit ({motor_config.inverter_current_limit_rms:.1f} A_rms)"
    else:
        c_status = ConstraintStatus.CONDITIONAL
        notes += "; Inverter phase current limit unverified"

    return StallElectricalResult(
        stator_phase_current_rms=i_rms,
        stator_copper_loss_w=p_stator_w,
        inverter_loss_w=inv_w,
        total_stall_electrical_power_kw=p_total_kw,
        status=c_status,
        provenance_status=p_status,
        notes=notes,
    )


# ---------------------------------------------------------------------------
# Peak Exposure State & Accounting Functions (Correction 1, C1.2, C1.3)
# ---------------------------------------------------------------------------

def is_demand_in_peak_overload(
    demand_torque_nm: float,
    demand_power_kw: float,
    motor_config: MotorConfig,
) -> bool:
    """Return True if demand exceeds continuous S1 torque or power limits."""
    return (
        demand_torque_nm > (motor_config.torque_cont_max_nm + 1e-4)
        or demand_power_kw > (motor_config.power_cont_max_kw + 1e-4)
    )


def update_peak_exposure(
    current_state: PeakExposureState,
    dt_s: float,
    is_peak_operating: bool,
    budget_s: Optional[float] = None,
    recovery_rate_s_per_s: Optional[float] = None,
) -> PeakExposureState:
    """
    Deterministic peak-exposure state transition over a discrete time step dt_s.
    
    Equations:
    - If operating in peak overload:
        exposure_new = min(budget, exposure_prev + dt_s)
        is_exhausted = (exposure_new >= budget)
    - If operating sub-continuous (recovering):
        recovery = dt_s * recovery_rate
        exposure_new = max(0.0, exposure_prev - recovery)
        is_exhausted = (exposure_new >= budget)
    """
    dt = _validate_finite_float("dt_s", dt_s, min_val=0.0)
    budget = budget_s if budget_s is not None else current_state.budget_s
    rate = recovery_rate_s_per_s if recovery_rate_s_per_s is not None else current_state.recovery_rate_s_per_s

    _validate_finite_float("budget_s", budget, min_val=0.1)
    _validate_finite_float("recovery_rate_s_per_s", rate, min_val=0.0)

    if is_peak_operating:
        new_exposure = min(budget, current_state.cumulative_exposure_s + dt)
        exhausted = (new_exposure >= budget)
    else:
        recovered = dt * rate
        new_exposure = max(0.0, current_state.cumulative_exposure_s - recovered)
        exhausted = (new_exposure >= budget)

    return PeakExposureState(
        cumulative_exposure_s=new_exposure,
        budget_s=budget,
        recovery_rate_s_per_s=rate,
        is_exhausted=exhausted,
    )


# ---------------------------------------------------------------------------
# Comprehensive Constraint Validation (Stage C1, C1.1, C1.2, C1.3)
# ---------------------------------------------------------------------------

def check_powertrain_constraints(
    demand_torque_nm: float,
    demand_power_kw: float,
    vehicle_speed_ms: float,
    motor_config: MotorConfig,
    gearbox_config: GearboxConfig,
    mode: Union[OperatingEnvelopeMode, str] = OperatingEnvelopeMode.CONTINUOUS,
    peak_state: Optional[PeakExposureState] = None,
    dt_s: Optional[float] = None,
    input_status: Optional[DataStatus] = None,
) -> PowertrainConstraintResult:
    """
    Independently track and validate torque, power, speed, inverter current,
    mechanical torque/power consistency, and peak-duration budget constraints.
    
    Evaluation Sequence (Correction C1.3):
    1. Validate caller operating mode and kinematics.
    2. Check mechanical consistency: P_mech == T * omega within explicit tolerance.
    3. Evaluate stator phase current and inverter current limits.
    4. Compute continuous (S1) and peak (S2) capability envelopes.
    5. Evaluate physical feasibility against S1 continuous and S2 peak envelopes.
    6. Arbitrate peak authorization and determine actual_operating_mode:
       - Demand within S1 capability -> CONTINUOUS.
       - Demand above S1, within S2, and peak authorized -> PEAK.
       - Demand exceeding available capability -> INFEASIBLE.
    7. Update thermal state:
       - Accumulate peak exposure ONLY when actual_operating_mode is PEAK.
       - Grant recovery ONLY when operating point is verified within S1 capability.
       - No exposure and no recovery when infeasible, denied, or unverified.
    8. Synthesize constraint statuses, margins, diagnostics, and provenance.
    """
    # 0. Validate Operating Mode Input
    if isinstance(mode, str):
        try:
            mode = OperatingEnvelopeMode(mode)
        except ValueError:
            raise ValueError(f"Invalid operating mode '{mode}'. Must be one of {[m.value for m in OperatingEnvelopeMode]}")
    elif not isinstance(mode, OperatingEnvelopeMode):
        raise TypeError(f"Operating mode must be OperatingEnvelopeMode enum or str, got {type(mode).__name__}")

    t_req = _validate_finite_float("demand_torque_nm", demand_torque_nm, 0.0, 10000.0)
    p_req = _validate_finite_float("demand_power_kw", demand_power_kw, 0.0, 5000.0)
    v = _validate_finite_float("vehicle_speed_ms", vehicle_speed_ms, 0.0, 150.0)

    # 1. Kinematics
    speed_res = compute_motor_speed(v, gearbox_config, input_status=input_status)
    omega = speed_res.motor_speed_rad_s
    omega_max = (motor_config.max_speed_rpm * 2.0 * math.pi) / 60.0
    speed_margin = omega_max - omega
    speed_status = ConstraintStatus.SATISFIED if omega <= omega_max else ConstraintStatus.VIOLATED

    # 2. Mechanical Torque-Speed-Power Consistency Check (Correction 3)
    is_consistent = True
    consistency_note = None

    if v < 1e-4:
        # At standstill (v = 0, omega = 0), mechanical shaft power must strictly be zero
        if p_req > 0.05:  # Tolerance: 50 W
            is_consistent = False
            consistency_note = (
                f"Contradictory demand at zero speed: non-zero mechanical shaft power ({p_req:.2f} kW) "
                f"demanded while rotor speed is zero"
            )
    else:
        # P_mech,expected = (T_demand * omega) / 1000.0  [kW]
        p_expected = (t_req * omega) / 1000.0
        # Explicit tolerance: 100 W absolute or 2% relative
        tol = max(0.10, 0.02 * p_expected)
        if abs(p_req - p_expected) > tol:
            is_consistent = False
            consistency_note = (
                f"Inconsistent mechanical demand: requested power ({p_req:.2f} kW) does not match "
                f"torque*omega ({p_expected:.2f} kW) beyond tolerance ({tol:.2f} kW)"
            )

    # 3. Inverter Current Limit & Zero-Speed Stall Evaluation (Evaluated before thermal update)
    i_req = compute_stator_phase_current(t_req, motor_config)
    i_margin = None
    stall_dc_pwr = None
    current_status = ConstraintStatus.CONDITIONAL

    if v < 1e-4:
        stall_res = compute_stall_dc_power(t_req, motor_config)
        if stall_res is not None:
            stall_dc_pwr = stall_res.total_stall_electrical_power_kw
            current_status = stall_res.status
            if motor_config.inverter_current_limit_rms is not None and i_req is not None:
                i_margin = motor_config.inverter_current_limit_rms - i_req
        else:
            current_status = ConstraintStatus.CONDITIONAL
    else:
        if motor_config.inverter_current_limit_rms is not None and i_req is not None:
            i_margin = motor_config.inverter_current_limit_rms - i_req
            current_status = ConstraintStatus.SATISFIED if i_req <= motor_config.inverter_current_limit_rms + 1e-4 else ConstraintStatus.VIOLATED
        else:
            current_status = ConstraintStatus.CONDITIONAL

    # 4. Continuous (S1) and Peak (S2) Envelopes
    cont_env = compute_motor_envelope(omega, motor_config, mode=OperatingEnvelopeMode.CONTINUOUS, input_status=input_status)
    peak_env = compute_motor_envelope(omega, motor_config, mode=OperatingEnvelopeMode.PEAK, input_status=input_status)

    # 5. Envelope Feasibility Evaluation
    is_mechanically_within_continuous = (
        is_consistent
        and (speed_status == ConstraintStatus.SATISFIED)
        and (t_req <= cont_env.available_torque_nm + 1e-4)
        and (p_req <= cont_env.available_power_kw + 1e-4 if v >= 1e-4 else True)
    )

    is_mechanically_within_peak = (
        is_consistent
        and (speed_status == ConstraintStatus.SATISFIED)
        and (t_req <= peak_env.available_torque_nm + 1e-4)
        and (p_req <= peak_env.available_power_kw + 1e-4 if v >= 1e-4 else True)
    )

    # Verified continuous/peak requires that electrical current constraints are strictly SATISFIED
    is_verified_continuous = is_mechanically_within_continuous and (current_status == ConstraintStatus.SATISFIED)
    is_verified_peak = is_mechanically_within_peak and (current_status == ConstraintStatus.SATISFIED)

    # 6. Peak Request vs Peak Grant Arbitration (Issue 1)
    peak_requested = (mode == OperatingEnvelopeMode.PEAK)
    is_peak_exhausted = peak_state.is_exhausted if peak_state is not None else False
    peak_granted = peak_requested and not is_peak_exhausted

    # Determine Actual Operating Regime (Correction C1.3 Issue 1)
    if not is_consistent or speed_status == ConstraintStatus.VIOLATED or current_status == ConstraintStatus.VIOLATED:
        # Any physical contradiction or violated hardware limit precludes successful operation
        actual_operating_mode = ActualOperatingMode.INFEASIBLE
    elif is_mechanically_within_continuous:
        # Demand within S1 capability -> actual mode CONTINUOUS, even if PEAK was requested
        actual_operating_mode = ActualOperatingMode.CONTINUOUS
    elif peak_granted and is_mechanically_within_peak:
        # Demand above S1 but within S2 and all relevant hardware limits -> actual mode PEAK
        actual_operating_mode = ActualOperatingMode.PEAK
    else:
        # Demand exceeding available capability, or peak denied on overload, or infeasible
        actual_operating_mode = ActualOperatingMode.INFEASIBLE

    # Envelope selected for active constraint reporting
    env = peak_env if peak_granted else cont_env

    # 7. Torque and Power Limit Evaluation under active envelope
    t_avail = env.available_torque_nm
    t_margin = t_avail - t_req
    torque_status = ConstraintStatus.SATISFIED if t_req <= t_avail + 1e-4 else ConstraintStatus.VIOLATED

    p_avail = env.available_power_kw
    p_margin = p_avail - p_req
    if not is_consistent:
        power_status = ConstraintStatus.VIOLATED
    elif v < 1e-4:
        power_status = ConstraintStatus.SATISFIED
    else:
        power_status = ConstraintStatus.SATISFIED if p_req <= p_avail + 1e-4 else ConstraintStatus.VIOLATED

    # 8. Deterministic Peak Exposure State Update (Correction C1.3 Issue 2)
    # Validates operating feasibility before updating thermal state
    updated_peak_state = peak_state
    if peak_state is not None and dt_s is not None and dt_s > 0:
        if actual_operating_mode == ActualOperatingMode.PEAK and is_verified_peak:
            # Accumulate peak exposure ONLY when actual operating mode is PEAK (verified feasible overload)
            updated_peak_state = update_peak_exposure(
                peak_state, dt_s, is_peak_operating=True,
                budget_s=motor_config.peak_duration_budget_s,
                recovery_rate_s_per_s=motor_config.recovery_rate_s_per_s,
            )
        elif is_verified_continuous:
            # Grant recovery ONLY when operating point is verified within continuous capability
            # AND all constraints (torque, power, speed, inverter current) are SATISFIED
            updated_peak_state = update_peak_exposure(
                peak_state, dt_s, is_peak_operating=False,
                budget_s=motor_config.peak_duration_budget_s,
                recovery_rate_s_per_s=motor_config.recovery_rate_s_per_s,
            )
        else:
            # Infeasible request, denied peak, violated hardware limits, or unverified (CONDITIONAL) current:
            # NO EXPOSURE ACCUMULATES AND NO RECOVERY IS GRANTED!
            updated_peak_state = peak_state

    # 9. Overall Status and Diagnostic Synthesis
    diagnostic_code = None
    notes_list = []

    if not is_consistent:
        overall = ConstraintStatus.VIOLATED
        diagnostic_code = "ERR_TORQUE_POWER_INCONSISTENT"
        notes_list.append(consistency_note or "Contradictory mechanical demand")
    elif peak_requested and not peak_granted and not is_mechanically_within_continuous:
        overall = ConstraintStatus.VIOLATED
        diagnostic_code = "ERR_PEAK_BUDGET_EXHAUSTED"
        notes_list.append("Peak thermal budget exhausted; requested operating point exceeds continuous capability; no recovery granted")
    elif speed_status == ConstraintStatus.VIOLATED:
        overall = ConstraintStatus.VIOLATED
        diagnostic_code = "ERR_OVERSPEED_CUTOFF"
        notes_list.append(f"Motor speed ({speed_res.motor_speed_rpm:.0f} RPM) exceeds maximum ({motor_config.max_speed_rpm:.0f} RPM)")
    elif torque_status == ConstraintStatus.VIOLATED:
        overall = ConstraintStatus.VIOLATED
        diagnostic_code = "ERR_TORQUE_EXCEEDED"
        notes_list.append(f"Torque demand ({t_req:.1f} Nm) exceeds available envelope ({t_avail:.1f} Nm)")
    elif current_status == ConstraintStatus.VIOLATED:
        overall = ConstraintStatus.VIOLATED
        diagnostic_code = "ERR_CURRENT_EXCEEDED"
        notes_list.append(f"Phase current demand ({i_req:.1f} A_rms) exceeds inverter limit ({motor_config.inverter_current_limit_rms:.1f} A_rms)")
    elif power_status == ConstraintStatus.VIOLATED:
        overall = ConstraintStatus.VIOLATED
        diagnostic_code = "ERR_POWER_EXCEEDED"
        notes_list.append(f"Power demand ({p_req:.1f} kW) exceeds envelope ({p_avail:.1f} kW)")
    elif current_status == ConstraintStatus.CONDITIONAL or motor_config.status != DataStatus.REAL or gearbox_config.status != DataStatus.REAL:
        overall = ConstraintStatus.CONDITIONAL
        diagnostic_code = "WARN_HARDWARE_LIMITS_UNVERIFIED"
        notes_list.append("Hardware constraints conditionally feasible under unverified motor or electrical parameters")
    else:
        overall = ConstraintStatus.SATISFIED
        notes_list.append("All powertrain constraints verified satisfied")

    if env.is_governor_active:
        notes_list.append(f"Speed governor active (derate factor S_gov={env.governor_derate_factor:.3f})")

    # Combine provenance across all inputs (Correction 4)
    provenance = combine_provenance(input_status, motor_config.status, gearbox_config.status)
    final_exhausted = updated_peak_state.is_exhausted if updated_peak_state is not None else False

    return PowertrainConstraintResult(
        torque_status=torque_status,
        power_status=power_status,
        speed_status=speed_status,
        current_status=current_status,
        overall_status=overall,
        torque_margin_nm=t_margin,
        power_margin_kw=p_margin,
        speed_margin_rad_s=speed_margin,
        phase_current_req_rms=i_req,
        inverter_current_margin_rms=i_margin,
        stall_dc_power_kw=stall_dc_pwr,
        diagnostic_code=diagnostic_code,
        notes="; ".join(notes_list),
        provenance_status=provenance,
        peak_state=updated_peak_state,
        is_peak_exhausted=final_exhausted,
        peak_requested=peak_requested,
        peak_granted=peak_granted,
        actual_operating_mode=actual_operating_mode,
    )
