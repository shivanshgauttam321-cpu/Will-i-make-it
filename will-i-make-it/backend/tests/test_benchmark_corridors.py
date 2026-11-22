"""
Automated validation of benchmark corridor simulations against machine-readable JSON fixtures.
Verifies that the physical simulation and routing service produce exact reproducible results
across all physical energy variables, thermal states, infrastructure provenance, and charging stops.
"""
import os
import json
import pytest
from app.services.energy.journey_simulator import simulate_journey
from app.services.routing_service import plan_routes
from app.models.schemas import RoutePlanRequest, VehicleProfile, RouteSegment


FIXTURES_DIR = os.path.join(os.path.dirname(__file__), "fixtures")
INPUT_FIXTURE_PATH = os.path.join(FIXTURES_DIR, "benchmark_corridors_input.json")
OUTPUT_FIXTURE_PATH = os.path.join(FIXTURES_DIR, "benchmark_corridors_output.json")


@pytest.fixture(scope="module")
def benchmark_inputs():
    with open(INPUT_FIXTURE_PATH, "r") as f:
        return json.load(f)


@pytest.fixture(scope="module")
def benchmark_outputs():
    with open(OUTPUT_FIXTURE_PATH, "r") as f:
        return json.load(f)


def test_fixtures_exist():
    assert os.path.exists(INPUT_FIXTURE_PATH), "benchmark_corridors_input.json must exist"
    assert os.path.exists(OUTPUT_FIXTURE_PATH), "benchmark_corridors_output.json must exist"


@pytest.mark.parametrize("corridor_idx", range(5))
def test_benchmark_corridor_reproducibility(corridor_idx, benchmark_inputs, benchmark_outputs):
    in_data = benchmark_inputs[corridor_idx]
    expected_out = benchmark_outputs[corridor_idx]

    corridor_id = in_data["corridor_id"]
    vp = in_data["vehicle_parameters"]
    segments = [RouteSegment(**s) for s in in_data["segments"]]

    # 1. Run physical simulation
    summary = simulate_journey(
        segments=segments,
        vehicle_mass_kg=vp["vehicle_mass_kg"],
        frontal_area_m2=2.3,
        drag_coeff=0.29,
        rolling_res_coeff=0.012,
        battery_capacity_kwh=vp["battery_capacity_kwh"],
        soc_start_pct=vp["soc_start_pct"],
        soc_reserve_pct=vp["soc_reserve_pct"],
        aux_power_kw=vp["aux_power_kw"],
        ambient_temp_c=vp["ambient_temp_c"],
        confidence_target=vp["confidence_target"],
    )

    exp_ps = expected_out["physical_simulation"]
    assert summary.total_distance_km == pytest.approx(exp_ps["total_distance_km"], rel=1e-3)
    assert summary.total_duration_min == pytest.approx(exp_ps["total_duration_min"], rel=1e-2)
    assert summary.initial_soc_pct == pytest.approx(exp_ps["initial_soc_pct"], abs=0.1)
    assert summary.final_soc_p50_pct == pytest.approx(exp_ps["final_soc_p50_pct"], abs=0.5)
    assert summary.final_soc_p90_pct == pytest.approx(exp_ps["final_soc_p90_pct"], abs=0.5)
    assert summary.feasibility_status.value == exp_ps["feasibility_status"]
    assert summary.total_traction_energy_kwh == pytest.approx(exp_ps["total_traction_energy_kwh"], rel=1e-2)
    assert summary.total_aux_energy_kwh == pytest.approx(exp_ps["total_aux_energy_kwh"], rel=1e-2)
    assert summary.total_btms_energy_kwh == pytest.approx(exp_ps["total_btms_energy_kwh"], rel=1e-2)
    assert summary.total_net_battery_kwh_p50 == pytest.approx(exp_ps["total_net_battery_kwh_p50"], rel=1e-2)
    assert summary.total_net_battery_kwh_p90 == pytest.approx(exp_ps["total_net_battery_kwh_p90"], rel=1e-2)
    assert summary.max_pack_temp_c == pytest.approx(exp_ps["max_pack_temp_c"], abs=0.5)
    assert summary.min_pack_temp_c == pytest.approx(exp_ps["min_pack_temp_c"], abs=0.5)
    assert summary.was_derated == exp_ps["was_derated"]
    assert summary.energy_residual_total_j == pytest.approx(exp_ps["energy_residual_total_j"], abs=1e-2)

    # 2. Run routing service API
    req = RoutePlanRequest(
        origin_lat=in_data["origin"]["lat"],
        origin_lng=in_data["origin"]["lng"],
        dest_lat=in_data["destination"]["lat"],
        dest_lng=in_data["destination"]["lng"],
        demo_route_id=in_data["corridor_id"] if in_data["corridor_id"] != "MUMBAI_PUNE_LOW_SOC" else "MUMBAI_PUNE",
        vehicle=VehicleProfile(
            battery_capacity_kwh=vp["battery_capacity_kwh"],
            soc_start_pct=vp["soc_start_pct"],
            soc_reserve_pct=vp["soc_reserve_pct"],
            vehicle_mass_kg=vp["vehicle_mass_kg"],
            aux_power_kw=vp["aux_power_kw"],
        ),
        ambient_temp_c=vp["ambient_temp_c"],
    )
    plan_resp = plan_routes(req)
    rec_route = plan_resp.risk_aware_route if (plan_resp.recommended == "risk_aware" and plan_resp.risk_aware_route) else plan_resp.fastest_route

    exp_rp = expected_out["routing_service_plan"]
    assert rec_route.feasibility_status == exp_rp["feasibility_status"]
    assert rec_route.is_energy_feasible == exp_rp["is_energy_feasible"]
    assert rec_route.all_chargers_reachable == exp_rp["all_chargers_reachable"]
    assert rec_route.infrastructure_status == exp_rp["infrastructure_status"]
    assert rec_route.overall_confidence == exp_rp["overall_confidence"]
    assert rec_route.distance_km == pytest.approx(exp_rp["total_distance_km"], rel=1e-2)
    assert rec_route.duration_min == pytest.approx(exp_rp["total_duration_min"], rel=1e-2)
    assert rec_route.energy_result.total_kwh_p50 == pytest.approx(exp_rp["energy_p50_kwh"], rel=1e-2)
    assert rec_route.energy_result.total_kwh_p90 == pytest.approx(exp_rp["energy_p90_kwh"], rel=1e-2)
    assert rec_route.energy_result.soc_final_p50_pct == pytest.approx(exp_rp["soc_remaining_p50_pct"], abs=0.5)
    assert rec_route.energy_result.soc_final_p90_pct == pytest.approx(exp_rp["soc_remaining_p90_pct"], abs=0.5)
    assert len(rec_route.charging_stops) == exp_rp["charging_stops_count"]

    for actual_stop, exp_stop in zip(rec_route.charging_stops, exp_rp["charging_stops"]):
        assert actual_stop.charger.charger_id == exp_stop["charger_id"]
        assert actual_stop.charger.name == exp_stop["name"]
        assert actual_stop.charger.status == exp_stop["status"]
        assert actual_stop.charger.data_source == exp_stop["data_source"]
        assert actual_stop.arrive_soc_pct == pytest.approx(exp_stop["arrive_soc_pct"], abs=0.5)
        assert actual_stop.depart_soc_pct == pytest.approx(exp_stop["depart_soc_pct"], abs=0.5)
        assert actual_stop.charge_duration_min == pytest.approx(exp_stop["charge_duration_min"], abs=0.5)
        assert actual_stop.charge_energy_kwh == pytest.approx(exp_stop["charge_energy_kwh"], rel=1e-2)
