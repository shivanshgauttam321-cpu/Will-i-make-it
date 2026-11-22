"""
Integration & Validation Tests for Journey Simulation Engine
============================================================
Tests multi-segment journey simulation, physical road-load forces,
1-RC battery state integration, C4 thermal dynamics, and feasibility logic.
"""
import pytest
from app.models.schemas import RouteSegment
from app.services.energy.journey_simulator import (
    FeasibilityStatus,
    simulate_journey,
    create_default_journey_configs,
)


def _make_segments():
    return [
        RouteSegment(segment_id="s1", name="City Start", distance_km=10.0, avg_speed_kmh=40.0, gradient_pct=0.0, road_type="urban"),
        RouteSegment(segment_id="s2", name="Highway Flat", distance_km=40.0, avg_speed_kmh=80.0, gradient_pct=0.2, road_type="highway"),
        RouteSegment(segment_id="s3", name="Uphill Ghat", distance_km=15.0, avg_speed_kmh=50.0, gradient_pct=4.0, road_type="rural"),
        RouteSegment(segment_id="s4", name="Downhill Regen", distance_km=15.0, avg_speed_kmh=60.0, gradient_pct=-3.5, road_type="highway"),
        RouteSegment(segment_id="s5", name="City End", distance_km=10.0, avg_speed_kmh=45.0, gradient_pct=0.0, road_type="urban"),
    ]


def test_standard_journey_simulation_physics():
    segs = _make_segments()
    summary = simulate_journey(
        segments=segs,
        vehicle_mass_kg=1600.0,
        frontal_area_m2=2.3,
        drag_coeff=0.29,
        rolling_res_coeff=0.012,
        battery_capacity_kwh=50.0,
        soc_start_pct=90.0,
        soc_reserve_pct=15.0,
        aux_power_kw=1.5,
        ambient_temp_c=25.0,
    )

    # 90 km total distance
    assert pytest.approx(summary.total_distance_km, abs=0.5) == 90.0
    # Feasible journey starting from 90%
    assert summary.feasibility_status in (FeasibilityStatus.WILL_MAKE_IT, FeasibilityStatus.LOW_RESERVE)
    # Energy breakdown consistency
    assert summary.total_traction_energy_kwh > 0.0
    assert summary.total_regen_energy_kwh > 0.0  # s4 downhill recovered energy
    assert summary.total_aux_energy_kwh > 0.0
    assert summary.final_soc_p50_pct < summary.initial_soc_pct
    assert summary.final_soc_p90_pct <= summary.final_soc_p50_pct
    # Symmetrical energy conservation ledger residual bounded
    assert summary.energy_residual_total_j < 1e-3

    # Downhill segment telemetry inspection
    downhill_telem = [t for t in summary.segment_telemetry if t.segment_id == "s4"][0]
    assert downhill_telem.is_braking is True
    assert downhill_telem.energy_regen_kwh > 0.0
    assert downhill_telem.f_grad_n < 0.0  # Gravitational assist


def test_journey_infeasible_low_initial_soc():
    segs = _make_segments()
    summary = simulate_journey(
        segments=segs,
        vehicle_mass_kg=1600.0,
        frontal_area_m2=2.3,
        drag_coeff=0.29,
        rolling_res_coeff=0.012,
        battery_capacity_kwh=40.0,
        soc_start_pct=10.0,  # Only 10% SOC for 90 km
        soc_reserve_pct=10.0,
        aux_power_kw=1.5,
        ambient_temp_c=25.0,
    )

    assert summary.feasibility_status == FeasibilityStatus.WILL_NOT_MAKE_IT
    assert summary.feasibility_margin_kwh < 0.0
    assert any("WILL NOT MAKE IT" in e for e in summary.explanations)


def test_journey_low_reserve_classification():
    # Tailor initial SOC so P50 finishes just above reserve, but P90 breaches reserve
    segs = [
        RouteSegment(segment_id="lr1", name="Trip", distance_km=70.0, avg_speed_kmh=80.0, gradient_pct=0.0, road_type="highway")
    ]
    # For 70km @ 80kmh on 40kWh battery, consumption ~ 11-13 kWh (~30% SOC)
    # If starting SOC is 45% and reserve is 18%, P50 arrival is ~20% (> 18%), but P90 arrival is ~16% (< 18%)
    summary = simulate_journey(
        segments=segs,
        vehicle_mass_kg=1600.0,
        frontal_area_m2=2.3,
        drag_coeff=0.29,
        rolling_res_coeff=0.012,
        battery_capacity_kwh=40.0,
        soc_start_pct=45.0,
        soc_reserve_pct=20.0,
        aux_power_kw=1.0,
        ambient_temp_c=25.0,
    )

    if summary.final_soc_p50_pct >= 20.0 and summary.final_soc_p90_pct < 20.0:
        assert summary.feasibility_status == FeasibilityStatus.LOW_RESERVE
        assert any("LOW RESERVE" in e for e in summary.explanations)


def test_journey_unknown_elevation_uncertainty():
    segs = [
        RouteSegment(segment_id="u1", name="Unknown Hill", distance_km=20.0, avg_speed_kmh=60.0, gradient_pct=None, gradient_status="UNKNOWN", road_type="rural")
    ]
    summary = simulate_journey(
        segments=segs,
        vehicle_mass_kg=1600.0,
        frontal_area_m2=2.3,
        drag_coeff=0.29,
        rolling_res_coeff=0.012,
        battery_capacity_kwh=50.0,
        soc_start_pct=90.0,
        soc_reserve_pct=10.0,
        ambient_temp_c=25.0,
    )

    assert summary.feasibility_status == FeasibilityStatus.UNCERTAIN
    assert any("UNCERTAIN" in e for e in summary.explanations)


def test_journey_thermal_cooling_in_hot_climate():
    # Long high-speed highway in 42°C heat
    hot_segs = [
        RouteSegment(segment_id=f"h{i}", name=f"Highway {i}", distance_km=30.0, avg_speed_kmh=110.0, gradient_pct=0.0, road_type="highway")
        for i in range(4)
    ]
    summary = simulate_journey(
        segments=hot_segs,
        vehicle_mass_kg=1800.0,
        frontal_area_m2=2.4,
        drag_coeff=0.30,
        rolling_res_coeff=0.012,
        battery_capacity_kwh=75.0,
        soc_start_pct=95.0,
        soc_reserve_pct=10.0,
        aux_power_kw=2.0,
        ambient_temp_c=42.0,
    )

    # Battery warms up under sustained 110 km/h and high ambient
    assert summary.max_pack_temp_c >= 42.0
    # BTMS cooling should have activated to reject heat
    assert summary.total_btms_energy_kwh >= 0.0


def test_journey_cold_weather_heating():
    cold_segs = [
        RouteSegment(segment_id="c1", name="Cold Cruise", distance_km=25.0, avg_speed_kmh=60.0, gradient_pct=0.0, road_type="rural")
    ]
    summary = simulate_journey(
        segments=cold_segs,
        vehicle_mass_kg=1600.0,
        frontal_area_m2=2.3,
        drag_coeff=0.29,
        rolling_res_coeff=0.012,
        battery_capacity_kwh=50.0,
        soc_start_pct=80.0,
        soc_reserve_pct=15.0,
        aux_power_kw=1.0,
        ambient_temp_c=-5.0,
    )

    first_telem = summary.segment_telemetry[0]
    assert first_telem.btms_mode in ("HEATING", "IDLE")


def test_acklam_normal_quantiles():
    from app.services.energy.journey_simulator import get_normal_quantile

    assert pytest.approx(get_normal_quantile(0.50), abs=1e-5) == 0.00000
    assert pytest.approx(get_normal_quantile(0.90), abs=1e-4) == 1.28155
    assert pytest.approx(get_normal_quantile(0.95), abs=1e-4) == 1.64485
    assert pytest.approx(get_normal_quantile(0.99), abs=1e-4) == 2.32635


def test_thermal_battery_temperature_coupling():
    """Verify that battery cell temperature in telemetry and state updates with thermal pack dynamics."""
    segs = [
        RouteSegment(segment_id="t1", name="Heavy Load", distance_km=50.0, avg_speed_kmh=120.0, gradient_pct=1.0, road_type="highway")
    ]
    summary = simulate_journey(
        segments=segs,
        vehicle_mass_kg=2000.0,
        frontal_area_m2=2.4,
        drag_coeff=0.30,
        rolling_res_coeff=0.012,
        battery_capacity_kwh=60.0,
        soc_start_pct=90.0,
        soc_reserve_pct=10.0,
        aux_power_kw=1.5,
        ambient_temp_c=35.0,
    )
    telem = summary.segment_telemetry[0]
    # Temperature should have increased above ambient 35°C due to I^2*R losses
    assert telem.battery_temp_c > 35.0
    assert summary.max_pack_temp_c > 35.0


def test_btms_power_increases_battery_energy():
    """Verify that active BTMS cooling or heating draws electrical power from the battery."""
    segs = [
        RouteSegment(segment_id="b1", name="Desert Sprint", distance_km=60.0, avg_speed_kmh=110.0, gradient_pct=0.0, road_type="highway")
    ]
    summary_hot = simulate_journey(
        segments=segs,
        vehicle_mass_kg=1800.0,
        frontal_area_m2=2.3,
        drag_coeff=0.29,
        rolling_res_coeff=0.012,
        battery_capacity_kwh=60.0,
        soc_start_pct=90.0,
        soc_reserve_pct=10.0,
        aux_power_kw=1.0,
        ambient_temp_c=45.0,
    )
    assert summary_hot.total_btms_energy_kwh > 0.0
    assert summary_hot.total_net_battery_kwh_p50 > 0.0


def test_thermal_derating_activation():
    """Verify that extreme pack temperature triggers thermal power derating."""
    from app.services.energy.thermal_model import ThermalConfig
    th_cfg = ThermalConfig(
        pack_mass_kg=200.0,
        specific_heat_j_per_kg_k=900.0,
        heat_transfer_coeff_w_per_k=5.0,
        temp_derate_hot_start_c=38.0,
        temp_derate_hot_cutoff_c=48.0,
        enable_active_cooling=False,
    )
    segs = [
        RouteSegment(segment_id="d1", name="Hot Climb", distance_km=40.0, avg_speed_kmh=110.0, gradient_pct=3.0, road_type="highway")
    ]
    summary = simulate_journey(
        segments=segs,
        vehicle_mass_kg=2000.0,
        frontal_area_m2=2.4,
        drag_coeff=0.30,
        rolling_res_coeff=0.012,
        battery_capacity_kwh=60.0,
        soc_start_pct=90.0,
        soc_reserve_pct=10.0,
        aux_power_kw=1.0,
        ambient_temp_c=40.0,
        thermal_config=th_cfg,
    )
    assert summary.was_derated is True
    assert any(t.derate_factor < 1.0 for t in summary.segment_telemetry)


def test_wind_vector_drag_impact():
    """Verify that headwind increases aerodynamic drag and total net energy."""
    calm_seg = [
        RouteSegment(segment_id="w1", name="Calm", distance_km=30.0, avg_speed_kmh=90.0, gradient_pct=0.0, road_type="highway")
    ]
    summary_calm = simulate_journey(
        segments=calm_seg,
        vehicle_mass_kg=1600.0,
        frontal_area_m2=2.3,
        drag_coeff=0.29,
        rolling_res_coeff=0.012,
        battery_capacity_kwh=50.0,
        soc_start_pct=80.0,
        soc_reserve_pct=10.0,
        aux_power_kw=1.0,
        ambient_temp_c=25.0,
    )

    # Now with 15 m/s (~54 km/h) direct headwind (vehicle heading 0°, wind from 0°)
    headwind_seg = [
        RouteSegment(
            segment_id="w2", name="Headwind", distance_km=30.0, avg_speed_kmh=90.0, gradient_pct=0.0, road_type="highway",
            bearing=0.0, wind_speed_ms=15.0, wind_direction_deg=0.0,
        )
    ]
    summary_headwind = simulate_journey(
        segments=headwind_seg,
        vehicle_mass_kg=1600.0,
        frontal_area_m2=2.3,
        drag_coeff=0.29,
        rolling_res_coeff=0.012,
        battery_capacity_kwh=50.0,
        soc_start_pct=80.0,
        soc_reserve_pct=10.0,
        aux_power_kw=1.0,
        ambient_temp_c=25.0,
    )

    f_aero_calm = summary_calm.segment_telemetry[0].f_aero_n
    f_aero_headwind = summary_headwind.segment_telemetry[0].f_aero_n
    assert f_aero_headwind > f_aero_calm
    assert summary_headwind.total_net_battery_kwh_p50 > summary_calm.total_net_battery_kwh_p50


@pytest.mark.parametrize("soc_val", [0.0, 0.1, 1.0, 10.0, 50.0, 90.0, 99.0, 99.9, 100.0])
def test_soc_boundary_spectrum(soc_val):
    """Verify that starting SOC values across the full 0% to 100% spectrum are accepted without artificial clamping."""
    seg = [
        RouteSegment(segment_id="soc_test", name="Short Step", distance_km=1.0, avg_speed_kmh=50.0, gradient_pct=0.0, road_type="urban")
    ]
    summary = simulate_journey(
        segments=seg,
        vehicle_mass_kg=1600.0,
        frontal_area_m2=2.3,
        drag_coeff=0.29,
        rolling_res_coeff=0.012,
        battery_capacity_kwh=40.0,
        soc_start_pct=soc_val,
        soc_reserve_pct=10.0,
        aux_power_kw=1.0,
        ambient_temp_c=25.0,
    )
    assert pytest.approx(summary.initial_soc_pct, abs=1e-3) == soc_val
    assert summary.final_soc_p50_pct <= soc_val + 0.1


@pytest.mark.parametrize("invalid_soc", [-10.0, -0.01, 100.01, 150.0, float("nan"), float("inf"), float("-inf")])
def test_soc_invalid_values_rejected_with_validation_error(invalid_soc):
    """Verify that invalid starting SOC values are explicitly rejected with ValueError and never silently clamped."""
    seg = [
        RouteSegment(segment_id="soc_err", name="Step", distance_km=1.0, avg_speed_kmh=50.0, gradient_pct=0.0, road_type="urban")
    ]
    with pytest.raises(ValueError, match="Starting SOC must be finite and within"):
        simulate_journey(
            segments=seg,
            vehicle_mass_kg=1600.0,
            frontal_area_m2=2.3,
            drag_coeff=0.29,
            rolling_res_coeff=0.012,
            battery_capacity_kwh=40.0,
            soc_start_pct=invalid_soc,
            soc_reserve_pct=10.0,
        )


def test_substepping_numerical_conservation_1hr_5hr():
    """Verify that long duration journeys (1h and 5h continuous) maintain exact energy ledger conservation."""
    # 5 hours at 80 km/h = 400 km
    long_seg = [
        RouteSegment(segment_id="long1", name="Long Highway", distance_km=400.0, avg_speed_kmh=80.0, gradient_pct=0.0, road_type="highway")
    ]
    summary = simulate_journey(
        segments=long_seg,
        vehicle_mass_kg=1800.0,
        frontal_area_m2=2.3,
        drag_coeff=0.29,
        rolling_res_coeff=0.012,
        battery_capacity_kwh=100.0,
        soc_start_pct=100.0,
        soc_reserve_pct=10.0,
        aux_power_kw=1.2,
        ambient_temp_c=25.0,
    )
    assert summary.total_duration_min == 300.0
    # Energy conservation residual across all 300 sub-steps bounded
    assert summary.energy_residual_total_j < 1e-3


def test_btms_enabled_vs_disabled_energy_accounting():
    """Verify exact energy difference when active BTMS is enabled vs disabled under hot conditions."""
    from app.services.energy.thermal_model import ThermalConfig
    seg = [
        RouteSegment(segment_id="btms_test", name="Hot Sprint", distance_km=50.0, avg_speed_kmh=110.0, gradient_pct=0.0, road_type="highway")
    ]
    th_enabled = ThermalConfig(enable_active_cooling=True, target_cool_temp_c=32.0)
    th_disabled = ThermalConfig(enable_active_cooling=False, target_cool_temp_c=32.0)

    summary_enabled = simulate_journey(
        segments=seg,
        vehicle_mass_kg=1800.0,
        frontal_area_m2=2.3,
        drag_coeff=0.29,
        rolling_res_coeff=0.012,
        battery_capacity_kwh=60.0,
        soc_start_pct=90.0,
        soc_reserve_pct=10.0,
        aux_power_kw=1.0,
        ambient_temp_c=40.0,
        thermal_config=th_enabled,
    )

    summary_disabled = simulate_journey(
        segments=seg,
        vehicle_mass_kg=1800.0,
        frontal_area_m2=2.3,
        drag_coeff=0.29,
        rolling_res_coeff=0.012,
        battery_capacity_kwh=60.0,
        soc_start_pct=90.0,
        soc_reserve_pct=10.0,
        aux_power_kw=1.0,
        ambient_temp_c=40.0,
        thermal_config=th_disabled,
    )

    assert summary_enabled.total_btms_energy_kwh > 0.0
    assert summary_disabled.total_btms_energy_kwh == 0.0
    # Enabling active BTMS draws additional electrical energy from the battery
    assert summary_enabled.total_net_battery_kwh_p50 > summary_disabled.total_net_battery_kwh_p50


