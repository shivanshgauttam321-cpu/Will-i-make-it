"""
Whole-Journey Multi-Domain Energy & Thermal Conservation Test Suite
==================================================================
Validates independent closed-loop vehicle energy balance across:
- Wheel mechanical work
- Powertrain gearbox and motor/inverter losses
- High-voltage DC bus electrical power accounting
- Active BTMS electrical power and thermal coupling
- 1-RC Thevenin battery internal electrochemical ledger
- Lumped battery pack thermal balance

Tested Scenarios:
1. Urban stop-start cycle
2. Highway high-speed cruising
3. Uphill mountain climb (Ghat section)
4. Downhill steep descent with heavy regeneration
5. Mixed multi-road trip
6. High temperature (42°C) active liquid cooling
7. Sub-zero cold (-10°C) active PTC heating
8. Long-duration (5 hours / 400 km) endurance simulation
"""
import pytest
from app.models.schemas import RouteSegment
from app.services.energy.thermal_model import ThermalConfig
from app.services.energy.whole_journey_audit import run_whole_journey_energy_audit


def test_whole_journey_urban_cycle():
    """Urban stop-start journey with rolling resistance and traffic overhead."""
    segs = [
        RouteSegment(segment_id="u1", name="City Core 1", distance_km=5.0, avg_speed_kmh=30.0, gradient_pct=0.0, road_type="urban"),
        RouteSegment(segment_id="u2", name="City Core 2", distance_km=8.0, avg_speed_kmh=40.0, gradient_pct=0.5, road_type="urban"),
        RouteSegment(segment_id="u3", name="Ring Road", distance_km=7.0, avg_speed_kmh=50.0, gradient_pct=-0.3, road_type="urban"),
    ]
    res = run_whole_journey_energy_audit("Urban Cycle", segs, soc_start_pct=90.0, ambient_temp_c=25.0)

    assert res.is_energy_conserved is True
    assert res.is_thermal_conserved is True
    assert res.bus_electrical_residual_j < 1e-4
    assert res.battery_ledger_residual_j < 1e-4
    assert res.vehicle_closed_loop_residual_j < 1e-3


def test_whole_journey_highway_cruising():
    """High-speed highway cruising where aerodynamic drag dominates."""
    segs = [
        RouteSegment(segment_id="hw1", name="Expressway Leg 1", distance_km=40.0, avg_speed_kmh=100.0, gradient_pct=0.0, road_type="highway"),
        RouteSegment(segment_id="hw2", name="Expressway Leg 2", distance_km=50.0, avg_speed_kmh=110.0, gradient_pct=0.1, road_type="highway"),
    ]
    res = run_whole_journey_energy_audit("Highway Cruising", segs, soc_start_pct=95.0, ambient_temp_c=25.0)

    assert res.is_energy_conserved is True
    assert res.is_thermal_conserved is True
    assert res.w_aero_j > res.w_roll_j  # Aerodynamic work dominates at 100-110 km/h
    assert res.battery_ledger_residual_j < 1e-4
    assert res.vehicle_closed_loop_residual_j < 1e-3


def test_whole_journey_uphill_climb():
    """Steep mountain climb with substantial potential energy accumulation."""
    segs = [
        RouteSegment(segment_id="up1", name="Ghat Ascent 1", distance_km=12.0, avg_speed_kmh=45.0, gradient_pct=5.0, road_type="rural"),
        RouteSegment(segment_id="up2", name="Ghat Ascent 2", distance_km=8.0, avg_speed_kmh=40.0, gradient_pct=6.5, road_type="rural"),
    ]
    res = run_whole_journey_energy_audit("Uphill Ghat Climb", segs, soc_start_pct=90.0, ambient_temp_c=22.0)

    assert res.is_energy_conserved is True
    assert res.is_thermal_conserved is True
    assert res.w_grad_j > res.w_aero_j + res.w_roll_j  # Gravity work dominates
    assert res.battery_ledger_residual_j < 1e-4
    assert res.vehicle_closed_loop_residual_j < 1e-3


def test_whole_journey_downhill_regeneration():
    """Steep mountain descent where regenerative braking returns energy to battery."""
    segs = [
        RouteSegment(segment_id="down1", name="Ghat Descent 1", distance_km=15.0, avg_speed_kmh=50.0, gradient_pct=-4.5, road_type="highway"),
        RouteSegment(segment_id="down2", name="Ghat Descent 2", distance_km=10.0, avg_speed_kmh=45.0, gradient_pct=-5.5, road_type="highway"),
    ]
    res = run_whole_journey_energy_audit("Downhill Regeneration", segs, soc_start_pct=60.0, ambient_temp_c=20.0)

    assert res.is_energy_conserved is True
    assert res.is_thermal_conserved is True
    # Gravitational assistance is negative (delivers work to the wheels)
    assert res.w_grad_j < 0.0
    # Inverter net DC is negative (generating into the HV bus)
    assert res.e_dc_powertrain_j < 0.0
    assert res.battery_ledger_residual_j < 1e-4
    assert res.vehicle_closed_loop_residual_j < 1e-3


def test_whole_journey_mixed_corridor():
    """Mixed urban, uphill, downhill, and highway multi-segment corridor."""
    segs = [
        RouteSegment(segment_id="m1", name="Urban Start", distance_km=15.0, avg_speed_kmh=40.0, gradient_pct=0.0, road_type="urban"),
        RouteSegment(segment_id="m2", name="Highway Fast", distance_km=45.0, avg_speed_kmh=90.0, gradient_pct=0.2, road_type="highway"),
        RouteSegment(segment_id="m3", name="Uphill Ghat", distance_km=15.0, avg_speed_kmh=45.0, gradient_pct=4.0, road_type="rural"),
        RouteSegment(segment_id="m4", name="Downhill Regen", distance_km=15.0, avg_speed_kmh=55.0, gradient_pct=-3.5, road_type="highway"),
        RouteSegment(segment_id="m5", name="City Approach", distance_km=10.0, avg_speed_kmh=35.0, gradient_pct=0.0, road_type="urban"),
    ]
    res = run_whole_journey_energy_audit("Mixed Corridor", segs, soc_start_pct=90.0, ambient_temp_c=26.0)

    assert res.is_energy_conserved is True
    assert res.is_thermal_conserved is True
    assert res.battery_ledger_residual_j < 1e-4
    assert res.vehicle_closed_loop_residual_j < 1e-3


def test_whole_journey_extreme_heat_btms_cooling():
    """High ambient temperature (42°C) triggering active BTMS chiller liquid cooling."""
    segs = [
        RouteSegment(segment_id="hot1", name="Desert Highway 1", distance_km=40.0, avg_speed_kmh=110.0, gradient_pct=0.0, road_type="highway"),
        RouteSegment(segment_id="hot2", name="Desert Highway 2", distance_km=40.0, avg_speed_kmh=110.0, gradient_pct=0.0, road_type="highway"),
    ]
    th_cfg = ThermalConfig(
        enable_active_cooling=True,
        target_cool_temp_c=32.0,
        max_cooling_power_w=4000.0,
        cop_cooling=3.0,
    )
    res = run_whole_journey_energy_audit(
        "Hot Ambient BTMS Cooling", segs, soc_start_pct=95.0, ambient_temp_c=42.0, thermal_config=th_cfg
    )

    assert res.is_energy_conserved is True
    assert res.is_thermal_conserved is True
    # Active cooling extracted heat and drew electrical power from the battery
    assert res.q_btms_cool_extracted_j > 0.0
    assert res.e_btms_electrical_j > 0.0
    assert res.battery_ledger_residual_j < 1e-4
    assert res.vehicle_closed_loop_residual_j < 1e-3


def test_whole_journey_extreme_cold_btms_heating():
    """Sub-zero ambient temperature (-10°C) triggering active BTMS PTC heating."""
    segs = [
        RouteSegment(segment_id="cold1", name="Winter Cruise", distance_km=30.0, avg_speed_kmh=60.0, gradient_pct=0.0, road_type="rural"),
    ]
    th_cfg = ThermalConfig(
        enable_active_heating=True,
        target_heat_temp_c=12.0,
        max_heating_power_w=3000.0,
        cop_heating=1.0,
    )
    res = run_whole_journey_energy_audit(
        "Cold Ambient BTMS Heating", segs, soc_start_pct=85.0, ambient_temp_c=-10.0, thermal_config=th_cfg
    )

    assert res.is_energy_conserved is True
    assert res.is_thermal_conserved is True
    # Active heating injected heat and drew electrical power
    assert res.q_btms_heat_injected_j > 0.0
    assert res.e_btms_electrical_j > 0.0
    assert res.battery_ledger_residual_j < 1e-4
    assert res.vehicle_closed_loop_residual_j < 1e-3


def test_whole_journey_5hour_endurance():
    """Long-duration 5-hour continuous endurance simulation (400 km)."""
    segs = [
        RouteSegment(segment_id="end1", name="Endurance Leg 1", distance_km=200.0, avg_speed_kmh=80.0, gradient_pct=0.0, road_type="highway"),
        RouteSegment(segment_id="end2", name="Endurance Leg 2", distance_km=200.0, avg_speed_kmh=80.0, gradient_pct=0.0, road_type="highway"),
    ]
    res = run_whole_journey_energy_audit(
        "5-Hour Endurance", segs, battery_capacity_kwh=100.0, soc_start_pct=100.0, ambient_temp_c=25.0
    )

    assert res.is_energy_conserved is True
    assert res.is_thermal_conserved is True
    assert res.total_duration_s == 18000.0  # Exactly 5 hours
    assert res.battery_ledger_residual_j < 1e-3
    assert res.vehicle_closed_loop_residual_j < 1e-2


def test_whole_journey_audit_detects_omitted_r0():
    """Verify that omitting series Joule loss R0 causes the independent audit to fail."""
    segs = [
        RouteSegment(segment_id="err1", name="Test Leg", distance_km=10.0, avg_speed_kmh=60.0, gradient_pct=0.0, road_type="highway"),
    ]
    res = run_whole_journey_energy_audit("Omit R0 Mutation", segs, soc_start_pct=80.0, mutation_injection="omit_r0")
    assert res.is_energy_conserved is False
    assert res.battery_ledger_residual_j > 100.0, "Audit must catch omitted R0 loss"


def test_whole_journey_audit_detects_double_counted_parasitic():
    """Verify that double-counting parasitic loss causes the independent audit to fail."""
    segs = [
        RouteSegment(segment_id="err2", name="Downhill", distance_km=15.0, avg_speed_kmh=50.0, gradient_pct=-4.0, road_type="highway"),
    ]
    res = run_whole_journey_energy_audit("Double Parasitic Mutation", segs, soc_start_pct=60.0, mutation_injection="double_parasitic")
    assert res.is_energy_conserved is False
    assert res.battery_ledger_residual_j > 100.0, "Audit must catch double-counted parasitic loss"


def test_whole_journey_audit_detects_inverted_c1_sign():
    """Verify that inverting capacitor storage sign causes the independent audit to fail."""
    segs = [
        RouteSegment(segment_id="err3", name="Ascent", distance_km=10.0, avg_speed_kmh=50.0, gradient_pct=3.0, road_type="rural"),
    ]
    res = run_whole_journey_energy_audit("Invert C1 Mutation", segs, soc_start_pct=70.0, mutation_injection="invert_sign_c1")
    assert res.is_energy_conserved is False
    assert res.battery_ledger_residual_j > 100.0, "Audit must catch inverted C1 sign"


def test_whole_journey_audit_residual_statistics_reported():
    """Verify that statistical residual metrics (max, mean, RMS) are reported."""
    segs = [
        RouteSegment(segment_id="stat1", name="Cruising", distance_km=20.0, avg_speed_kmh=80.0, gradient_pct=0.0, road_type="highway"),
    ]
    res = run_whole_journey_energy_audit("Residual Stats", segs, soc_start_pct=85.0)
    assert res.is_energy_conserved is True
    assert res.max_signed_electrical_residual_j < 1e-3
    assert res.mean_abs_electrical_residual_j < 1e-3
    assert res.rms_electrical_residual_j < 1e-3
    assert res.calculation_methodology == "Independent primitive-reconstructed multi-domain conservation ledger"
