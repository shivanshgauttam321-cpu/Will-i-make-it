"""
Environmental & Auxiliary Modeling for EV Powertrain
=====================================================
Deterministic calculation of barometric air density, meteorological apparent
wind vectors, and auxiliary/HVAC electrical power draw.

Units:
- Pressure: Pa
- Temperature: °C (converted to Kelvin internally)
- Elevation: m
- Speed: m/s
- Direction/Heading: degrees (0-360° from North)
- Power: kW
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import math
from typing import Optional

from app.domain.provenance import DataStatus

# Physical constants (CODATA / ISA standard)
ISA_SEA_LEVEL_PRESSURE_PA: float = 101325.0
ISA_SEA_LEVEL_TEMP_K: float = 288.15
ISA_LAPSE_RATE_K_PER_M: float = 0.0065
GRAVITY_M_S2: float = 9.80665
MOLAR_MASS_AIR_KG_MOL: float = 0.0289644
UNIVERSAL_GAS_CONST: float = 8.314462
SPECIFIC_GAS_CONST_AIR: float = 287.058


class HVACMode(str, Enum):
    """Operational state of the cabin climate control system."""
    DISABLED = "DISABLED"
    VENTILATION_ONLY = "VENTILATION_ONLY"
    COOLING = "COOLING"
    HEATING = "HEATING"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True)
class AirDensityResult:
    """Atmospheric density computation result with provenance tracking."""
    density_kg_m3: float
    status: DataStatus
    input_status: Optional[DataStatus]
    is_standard_atmosphere: bool
    elevation_used_m: float
    temperature_used_c: float


@dataclass(frozen=True)
class ApparentWindResult:
    """Aerodynamic wind vector decomposed along and across vehicle axis."""
    apparent_airspeed_ms: float
    crosswind_ms: float  # Signed: > 0 from starboard (right), < 0 from port (left)
    status: DataStatus
    input_status: Optional[DataStatus]
    is_wind_unknown: bool
    heading_deg_used: float


@dataclass(frozen=True)
class AuxiliaryPowerResult:
    """Auxiliary electrical power draw with generic model assumptions documented."""
    total_aux_power_kw: float
    base_power_kw: float
    hvac_power_kw: float
    hvac_mode: HVACMode
    is_hvac_estimated: bool
    status: DataStatus
    input_status: Optional[DataStatus]


@dataclass
class AuxiliaryConfig:
    """
    Configurable parameters for generic auxiliary and HVAC baseline power.
    NOTE: All values represent generic engineering model assumptions, NOT fleet-measured data.
    """
    p_base_kw: float = 0.30            # Model assumption: 12V bus, lighting, ECUs
    p_vent_kw: float = 0.05            # Model assumption: blower fan only
    p_cool_base_kw: float = 0.40       # Model assumption: A/C compressor baseline
    p_heat_base_kw: float = 0.50       # Model assumption: PTC/heat pump baseline
    k_cool_kw_per_c: float = 0.08      # Model assumption: cooling gradient per °C
    k_heat_kw_per_c: float = 0.10      # Model assumption: heating gradient per °C
    p_hvac_max_kw: float = 3.50        # Model assumption: HVAC saturation ceiling
    cooling_threshold_c: float = 24.0  # Ambient temperature above which cooling engages
    heating_threshold_c: float = 18.0  # Ambient temperature below which heating engages
    nominal_unknown_kw: float = 0.50   # Fallback assumption when ambient temperature is unknown

    def __post_init__(self) -> None:
        # 1. Electrical power parameters: must be finite and non-negative
        power_params = {
            "p_base_kw": self.p_base_kw,
            "p_vent_kw": self.p_vent_kw,
            "p_cool_base_kw": self.p_cool_base_kw,
            "p_heat_base_kw": self.p_heat_base_kw,
            "k_cool_kw_per_c": self.k_cool_kw_per_c,
            "k_heat_kw_per_c": self.k_heat_kw_per_c,
            "p_hvac_max_kw": self.p_hvac_max_kw,
            "nominal_unknown_kw": self.nominal_unknown_kw,
        }
        for k, v in power_params.items():
            if not isinstance(v, (int, float)) or not math.isfinite(v) or v < 0.0:
                raise ValueError(f"AuxiliaryConfig power parameter '{k}' must be finite and non-negative")

        # 2. Temperature threshold parameters: must be finite within physical limits (-50°C to 65°C)
        temp_params = {
            "cooling_threshold_c": self.cooling_threshold_c,
            "heating_threshold_c": self.heating_threshold_c,
        }
        for k, v in temp_params.items():
            if not isinstance(v, (int, float)) or not math.isfinite(v):
                raise ValueError(f"AuxiliaryConfig temperature parameter '{k}' must be a finite numerical value")
            if not (-50.0 <= v <= 65.0):
                raise ValueError(
                    f"AuxiliaryConfig temperature parameter '{k}' ({v}) is outside physical bounds [-50.0, 65.0]"
                )

        # 3. Invariant: cooling threshold must be strictly greater than heating threshold
        if self.cooling_threshold_c <= self.heating_threshold_c:
            raise ValueError(
                f"cooling_threshold_c ({self.cooling_threshold_c}) must be strictly greater than "
                f"heating_threshold_c ({self.heating_threshold_c})"
            )


def _validate_finite(name: str, value: Optional[float], min_val: float, max_val: float) -> None:
    """Validate that an optional float is finite and within physical bounds."""
    if value is not None:
        if not isinstance(value, (int, float)) or not math.isfinite(value):
            raise ValueError(f"Parameter '{name}' must be a finite numerical value")
        if not (min_val <= value <= max_val):
            raise ValueError(
                f"Parameter '{name}' ({value}) is outside physical bounds [{min_val}, {max_val}]"
            )


def compute_air_density(
    elevation_m: Optional[float] = None,
    ambient_temp_c: Optional[float] = 25.0,
    sea_level_pressure_pa: float = ISA_SEA_LEVEL_PRESSURE_PA,
    input_status: Optional[DataStatus] = None,
) -> AirDensityResult:
    """
    Computes ambient dry air density using the International Standard Atmosphere (ISA)
    barometric lapse model with strict boundary checking.
    """
    _validate_finite("elevation_m", elevation_m, -500.0, 9000.0)
    _validate_finite("ambient_temp_c", ambient_temp_c, -50.0, 65.0)
    _validate_finite("sea_level_pressure_pa", sea_level_pressure_pa, 50000.0, 115000.0)

    is_standard = False
    if elevation_m is None:
        h = 0.0
        is_standard = True
    else:
        h = float(elevation_m)

    if ambient_temp_c is None:
        temp_c = 25.0
        derived_status = DataStatus.UNKNOWN
    else:
        temp_c = float(ambient_temp_c)
        derived_status = DataStatus.ESTIMATED

    t_abs_k = temp_c + 273.15
    # Barometric pressure at elevation h
    exponent = (GRAVITY_M_S2 * MOLAR_MASS_AIR_KG_MOL) / (UNIVERSAL_GAS_CONST * ISA_LAPSE_RATE_K_PER_M)
    pressure_h = sea_level_pressure_pa * math.pow(
        1.0 - (ISA_LAPSE_RATE_K_PER_M * h / ISA_SEA_LEVEL_TEMP_K), exponent
    )
    density = pressure_h / (SPECIFIC_GAS_CONST_AIR * t_abs_k)

    return AirDensityResult(
        density_kg_m3=density,
        status=derived_status,
        input_status=input_status,
        is_standard_atmosphere=is_standard,
        elevation_used_m=h,
        temperature_used_c=temp_c,
    )


def compute_apparent_wind(
    vehicle_speed_ms: float,
    vehicle_heading_deg: float,
    wind_speed_ms: Optional[float] = None,
    wind_direction_from_deg: Optional[float] = None,
    input_status: Optional[DataStatus] = None,
) -> ApparentWindResult:
    """
    Computes apparent longitudinal airspeed and signed crosswind vector.
    Conforms to meteorological standard: wind_direction is the azimuth the wind is blowing FROM.
    """
    _validate_finite("vehicle_speed_ms", vehicle_speed_ms, 0.0, 100.0)
    _validate_finite("vehicle_heading_deg", vehicle_heading_deg, -3600.0, 3600.0)
    _validate_finite("wind_speed_ms", wind_speed_ms, 0.0, 80.0)
    _validate_finite("wind_direction_from_deg", wind_direction_from_deg, -3600.0, 3600.0)

    heading_norm = vehicle_heading_deg % 360.0

    if wind_speed_ms == 0.0:
        # Zero wind speed: wind direction is mathematically irrelevant (0 * cos = 0, 0 * sin = 0)
        return ApparentWindResult(
            apparent_airspeed_ms=vehicle_speed_ms,
            crosswind_ms=0.0,
            status=DataStatus.ESTIMATED,
            input_status=input_status,
            is_wind_unknown=False,
            heading_deg_used=heading_norm,
        )

    if wind_speed_ms is None or wind_direction_from_deg is None:
        # Unknown wind: cannot resolve aerodynamic vector. Fallback to calm ground speed.
        return ApparentWindResult(
            apparent_airspeed_ms=vehicle_speed_ms,
            crosswind_ms=0.0,
            status=DataStatus.UNKNOWN,
            input_status=input_status or DataStatus.UNKNOWN,
            is_wind_unknown=True,
            heading_deg_used=heading_norm,
        )

    wind_dir_norm = wind_direction_from_deg % 360.0
    delta_rad = math.radians(wind_dir_norm - heading_norm)
    headwind = wind_speed_ms * math.cos(delta_rad)
    crosswind = wind_speed_ms * math.sin(delta_rad)

    # UNCLAMPED SIGNED APPARENT AIRSPEED
    v_app = vehicle_speed_ms + headwind

    return ApparentWindResult(
        apparent_airspeed_ms=v_app,
        crosswind_ms=crosswind,
        status=DataStatus.ESTIMATED,
        input_status=input_status,
        is_wind_unknown=False,
        heading_deg_used=heading_norm,
    )


def compute_auxiliary_power(
    ambient_temp_c: Optional[float],
    hvac_enabled: bool = True,
    config: Optional[AuxiliaryConfig] = None,
    input_status: Optional[DataStatus] = None,
) -> AuxiliaryPowerResult:
    """
    Computes auxiliary electrical power load with configurable HVAC modeling.
    Distinguishes DISABLED, VENTILATION_ONLY, COOLING, HEATING, and UNKNOWN states.
    """
    _validate_finite("ambient_temp_c", ambient_temp_c, -50.0, 65.0)
    cfg = config or AuxiliaryConfig()
    base_kw = cfg.p_base_kw

    if not hvac_enabled:
        return AuxiliaryPowerResult(
            total_aux_power_kw=base_kw,
            base_power_kw=base_kw,
            hvac_power_kw=0.0,
            hvac_mode=HVACMode.DISABLED,
            is_hvac_estimated=False,
            status=DataStatus.ESTIMATED,
            input_status=input_status,
        )

    if ambient_temp_c is None:
        return AuxiliaryPowerResult(
            total_aux_power_kw=base_kw + cfg.nominal_unknown_kw,
            base_power_kw=base_kw,
            hvac_power_kw=cfg.nominal_unknown_kw,
            hvac_mode=HVACMode.UNKNOWN,
            is_hvac_estimated=True,
            status=DataStatus.UNKNOWN,
            input_status=input_status or DataStatus.UNKNOWN,
        )

    if ambient_temp_c > cfg.cooling_threshold_c:
        dt = ambient_temp_c - cfg.cooling_threshold_c
        p_hvac = min(cfg.p_hvac_max_kw, cfg.p_cool_base_kw + cfg.k_cool_kw_per_c * dt)
        mode = HVACMode.COOLING
    elif ambient_temp_c < cfg.heating_threshold_c:
        dt = cfg.heating_threshold_c - ambient_temp_c
        p_hvac = min(cfg.p_hvac_max_kw, cfg.p_heat_base_kw + cfg.k_heat_kw_per_c * dt)
        mode = HVACMode.HEATING
    else:
        p_hvac = cfg.p_vent_kw
        mode = HVACMode.VENTILATION_ONLY

    return AuxiliaryPowerResult(
        total_aux_power_kw=base_kw + p_hvac,
        base_power_kw=base_kw,
        hvac_power_kw=p_hvac,
        hvac_mode=mode,
        is_hvac_estimated=True,
        status=DataStatus.ESTIMATED,
        input_status=input_status,
    )
