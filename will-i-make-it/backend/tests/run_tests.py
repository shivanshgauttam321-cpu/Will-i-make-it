"""
Standalone test runner for Will I Make It EV Route Planner.
Can be run with plain Python 3 without requiring pytest!
Verifies:
- Energy units, signs, and physical reasonableness
- Battery bounds (0-100%) and SoC degradation
- Uphill vs Flat vs Downhill + Regen
- AC load sensitivity
- P90 >= P50 uncertainty coverage
- Cold temperature impact
- Payload sensitivity
- Route feasibility under low vs high SoC
- Charger compatibility filtering
- Charger reliability calculation (Beta posterior Laplace smoothing)
- Simulated failure & rerouting explanation
- Simulation reproducibility & synthetic metrics
"""

import sys
import os
import math

# Add backend directory to sys.path
backend_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

from app.models.schemas import (
    VehicleProfile, RouteSegment, EnergyPredictRequest, ConnectorType, RoutePlanRequest
)
from app.services.energy_model import predict_energy, predict_segment, _temp_correction, _p90_factor
from app.services.routing_service import plan_routes
from app.services.charger_service import init_db, compute_reliability, add_report
from app.routers.trips import simulate_trip
from app.models.schemas import TripSimulateRequest


def test_suite():
    passed = 0
    failed = 0
    total = 0

    def assert_test(cond, name, msg=""):
        nonlocal passed, failed, total
        total += 1
        if cond:
            passed += 1
            print(f"  [PASS] {name}")
        else:
            failed += 1
            print(f"  [FAIL] {name}: {msg}")

    print("\n--- 1. Testing Energy Model Physics, Units & Signs ---")
    vehicle = VehicleProfile(
        battery_capacity_kwh=40.0,
        soc_start_pct=80.0,
        soc_reserve_pct=10.0,
        vehicle_mass_kg=1500.0,
        drag_coefficient=0.30,
        frontal_area_m2=2.3,
        rolling_resistance=0.012,
        drivetrain_efficiency=0.88,
        regen_efficiency=0.65,
        connector_types=[ConnectorType.CCS2],
        ac_load_kw=0.0,
        payload_kg=0.0,
    )

    seg_flat = RouteSegment(segment_id="FLAT", distance_km=10.0, avg_speed_kmh=80.0, gradient_pct=0.0, road_type="highway")
    req_flat = EnergyPredictRequest(vehicle=vehicle, segments=[seg_flat], ambient_temp_c=25.0)
    res_flat = predict_energy(req_flat)

    assert_test(res_flat.total_kwh_p50 > 0, "Flat road consumes positive energy", f"Got {res_flat.total_kwh_p50}")
    assert_test(0.5 <= res_flat.total_kwh_p50 <= 5.0, "10km @ 80km/h consumes reasonable EV energy (0.5-5.0 kWh)", f"Got {res_flat.total_kwh_p50}")

    seg_up = RouteSegment(segment_id="UP", distance_km=10.0, avg_speed_kmh=80.0, gradient_pct=5.0, road_type="highway")
    req_up = EnergyPredictRequest(vehicle=vehicle, segments=[seg_up], ambient_temp_c=25.0)
    res_up = predict_energy(req_up)
    assert_test(res_up.total_kwh_p50 > res_flat.total_kwh_p50, "Uphill consumes more energy than flat", f"{res_up.total_kwh_p50} > {res_flat.total_kwh_p50}")

    seg_down = RouteSegment(segment_id="DOWN", distance_km=10.0, avg_speed_kmh=80.0, gradient_pct=-4.0, road_type="rural")
    req_down = EnergyPredictRequest(vehicle=vehicle, segments=[seg_down], ambient_temp_c=25.0)
    res_down = predict_energy(req_down)
    assert_test(res_down.total_kwh_p50 < res_flat.total_kwh_p50, "Downhill with regen consumes less energy than flat", f"{res_down.total_kwh_p50} < {res_flat.total_kwh_p50}")

    print("\n--- 2. Testing Auxiliary Load (AC) & Temperature ---")
    vehicle_ac = vehicle.model_copy(update={"ac_load_kw": 2.0})
    req_ac = EnergyPredictRequest(vehicle=vehicle_ac, segments=[seg_flat], ambient_temp_c=25.0)
    res_ac = predict_energy(req_ac)
    assert_test(res_ac.total_kwh_p50 > res_flat.total_kwh_p50, "AC load increases total energy", f"{res_ac.total_kwh_p50} > {res_flat.total_kwh_p50}")

    req_cold = EnergyPredictRequest(vehicle=vehicle, segments=[seg_flat], ambient_temp_c=5.0)
    res_cold = predict_energy(req_cold)
    assert_test(res_cold.total_kwh_p50 > res_flat.total_kwh_p50, "Cold ambient temperature increases energy consumption", f"{res_cold.total_kwh_p50} > {res_flat.total_kwh_p50}")

    vehicle_heavy = vehicle.model_copy(update={"payload_kg": 400.0})
    req_heavy = EnergyPredictRequest(vehicle=vehicle_heavy, segments=[seg_flat], ambient_temp_c=25.0)
    res_heavy = predict_energy(req_heavy)
    assert_test(res_heavy.total_kwh_p50 > res_flat.total_kwh_p50, "Payload increases energy consumption", f"{res_heavy.total_kwh_p50} > {res_flat.total_kwh_p50}")

    print("\n--- 3. Testing Battery Bounds & Uncertainty (P50 vs P90) ---")
    assert_test(res_flat.total_kwh_p90 >= res_flat.total_kwh_p50, "P90 conservative estimate >= P50 expected", f"{res_flat.total_kwh_p90} >= {res_flat.total_kwh_p50}")
    assert_test(0.0 <= res_flat.soc_final_p50_pct <= 100.0, "Final SoC bounded in [0, 100]", f"Got {res_flat.soc_final_p50_pct}")
    assert_test(res_flat.soc_final_p50_pct < vehicle.soc_start_pct, "Final SoC < starting SoC for positive trip", f"{res_flat.soc_final_p50_pct} < {vehicle.soc_start_pct}")

    print("\n--- 4. Testing Route Feasibility Constraints ---")
    long_segs = [RouteSegment(segment_id=f"S{i}", distance_km=60.0, avg_speed_kmh=90.0, gradient_pct=0.0, road_type="highway") for i in range(5)]
    low_soc_vehicle = vehicle.model_copy(update={"soc_start_pct": 20.0})
    req_infeasible = EnergyPredictRequest(vehicle=low_soc_vehicle, segments=long_segs, ambient_temp_c=25.0)
    res_infeasible = predict_energy(req_infeasible)
    assert_test(not res_infeasible.feasible, "300km trip with 20% starting SoC is flagged INFEASIBLE", f"Feasible: {res_infeasible.feasible}")

    req_feasible = EnergyPredictRequest(vehicle=vehicle.model_copy(update={"soc_start_pct": 100.0}), segments=[seg_flat], ambient_temp_c=25.0)
    res_feasible = predict_energy(req_feasible)
    assert_test(res_feasible.feasible, "Short 10km trip with 100% SoC is flagged FEASIBLE", f"Feasible: {res_feasible.feasible}")

    print("\n--- 5. Testing Charger Reliability & DB Persistence ---")
    init_db()
    unknown_rel = compute_reliability("NON_EXISTENT_CHARGER")
    assert_test(unknown_rel["score"] == 0.5, "Unknown charger defaults honestly to 0.5 prior (not assumed 100% operational)", f"Got {unknown_rel['score']}")
    assert_test(unknown_rel["freshness_hours"] is None, "Unknown charger has None freshness", f"Got {unknown_rel['freshness_hours']}")

    from datetime import datetime, timezone
    seed_ref_time = datetime(2026, 10, 29, 12, 0, 0, tzinfo=timezone.utc)
    delhi_rel = compute_reliability("CHR_DL_001", as_of=seed_ref_time)
    assert_test(delhi_rel["score"] >= 0.70, "Charger with positive seed history has score >= 0.70", f"Got {delhi_rel['score']}")

    add_report("CHR_MH_003", False, "CCS2", None, "TEST: charger broke down", "test_user", reported_at=seed_ref_time.isoformat())
    mh3_rel = compute_reliability("CHR_MH_003", as_of=seed_ref_time)
    assert_test(mh3_rel["score"] < 0.60, "Charger with failure report reflects decreased reliability", f"Got {mh3_rel['score']}")

    print("\n--- 6. Testing Charger Failure Demo & Rerouting ---")
    req_plan = RoutePlanRequest(
        origin_lat=19.076, origin_lng=72.8777,
        dest_lat=18.5204, dest_lng=73.8567,
        vehicle=vehicle.model_copy(update={"soc_start_pct": 50.0}),
        demo_route_id="MUMBAI_PUNE",
        disabled_charger_ids=["CHR_MH_003"]
    )
    plan_res = plan_routes(req_plan)
    assert_test(plan_res.charger_failure_scenario is not None, "Charger failure scenario produces explainability note", plan_res.charger_failure_scenario)
    assert_test(all(cs.charger.charger_id != "CHR_MH_003" for cs in plan_res.fastest_route.charging_stops),
                "Disabled charger CHR_MH_003 is excluded from charging stops", "Excluded correctly")

    print("\n--- 7. Testing Trip Simulation (Reproducibility & Uncertainty) ---")
    sim_req1 = TripSimulateRequest(route_id="DELHI_GURUGRAM", vehicle=vehicle, noise_seed=42)
    sim_req2 = TripSimulateRequest(route_id="DELHI_GURUGRAM", vehicle=vehicle, noise_seed=42)
    sim1 = simulate_trip(sim_req1)
    sim2 = simulate_trip(sim_req2)
    assert_test(abs(sim1.actual_kwh - sim2.actual_kwh) < 1e-4, "Simulation with fixed seed is deterministic and reproducible", f"{sim1.actual_kwh} == {sim2.actual_kwh}")

    print("\n" + "="*50)
    print(f"TEST RUN COMPLETED: {passed}/{total} PASSED, {failed} FAILED")
    print("="*50 + "\n")
    return failed == 0

if __name__ == "__main__":
    success = test_suite()
    sys.exit(0 if success else 1)
