"""
Tests for energy prediction model.
Tests cover: units/signs, battery bounds, uphill vs flat, AC load,
low battery, charger incompatibility, charger failure, route feasibility.

All tests use SYNTHETIC data from the physics model.
"""
import pytest
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.models.schemas import (
    VehicleProfile, RouteSegment, EnergyPredictRequest, ConnectorType
)
from app.services.energy_model import predict_energy, predict_segment, _temp_correction, _p90_factor


# ─── Fixtures ────────────────────────────────────────────────────────────────

def default_vehicle(**kwargs):
    params = dict(
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
    params.update(kwargs)
    return VehicleProfile(**params)


def flat_segment(sid="S1", dist=10.0, speed=80.0, grad=0.0, rtype="highway"):
    return RouteSegment(
        segment_id=sid, distance_km=dist, avg_speed_kmh=speed,
        gradient_pct=grad, road_type=rtype, name=sid
    )


# ─── Unit & Sign Tests ────────────────────────────────────────────────────────

class TestEnergySignsAndUnits:
    def test_flat_positive_energy(self):
        """Flat road must consume positive energy."""
        vehicle = default_vehicle()
        seg = flat_segment(grad=0.0)
        req = EnergyPredictRequest(vehicle=vehicle, segments=[seg], ambient_temp_c=25.0)
        resp = predict_energy(req)
        assert resp.total_kwh_p50 > 0, "Flat road must draw positive energy"

    def test_uphill_more_than_flat(self):
        """Uphill segment must consume more energy than flat equivalent."""
        vehicle = default_vehicle()
        seg_flat = flat_segment("FLAT", grad=0.0)
        seg_up = flat_segment("UP", grad=5.0)  # 5% gradient
        req_flat = EnergyPredictRequest(vehicle=vehicle, segments=[seg_flat], ambient_temp_c=25.0)
        req_up = EnergyPredictRequest(vehicle=vehicle, segments=[seg_up], ambient_temp_c=25.0)
        resp_flat = predict_energy(req_flat)
        resp_up = predict_energy(req_up)
        assert resp_up.total_kwh_p50 > resp_flat.total_kwh_p50, \
            "Uphill should consume more energy than flat"

    def test_downhill_less_than_flat_with_regen(self):
        """Downhill with regen should use less energy than flat."""
        vehicle = default_vehicle(regen_efficiency=0.65)
        seg_flat = flat_segment("FLAT", grad=0.0)
        seg_down = flat_segment("DOWN", grad=-4.0, rtype="rural")
        req_flat = EnergyPredictRequest(vehicle=vehicle, segments=[seg_flat], ambient_temp_c=25.0)
        req_down = EnergyPredictRequest(vehicle=vehicle, segments=[seg_down], ambient_temp_c=25.0)
        resp_flat = predict_energy(req_flat)
        resp_down = predict_energy(req_down)
        assert resp_down.total_kwh_p50 < resp_flat.total_kwh_p50, \
            "Downhill with regen should use less energy than flat"

    def test_ac_load_increases_energy(self):
        """AC load (aux power) must increase total energy consumption."""
        vehicle_no_ac = default_vehicle(ac_load_kw=0.0)
        vehicle_ac = default_vehicle(ac_load_kw=2.0)
        seg = flat_segment()
        req_no_ac = EnergyPredictRequest(vehicle=vehicle_no_ac, segments=[seg], ambient_temp_c=25.0)
        req_ac = EnergyPredictRequest(vehicle=vehicle_ac, segments=[seg], ambient_temp_c=25.0)
        resp_no_ac = predict_energy(req_no_ac)
        resp_ac = predict_energy(req_ac)
        assert resp_ac.total_kwh_p50 > resp_no_ac.total_kwh_p50, \
            "AC load must increase energy consumption"

    def test_p90_geq_p50(self):
        """P90 (conservative) estimate must be >= P50 (expected)."""
        vehicle = default_vehicle()
        seg = flat_segment()
        req = EnergyPredictRequest(vehicle=vehicle, segments=[seg], ambient_temp_c=25.0)
        resp = predict_energy(req)
        assert resp.total_kwh_p90 >= resp.total_kwh_p50, "P90 must be >= P50"

    def test_soc_final_decreases(self):
        """Final SoC must be less than starting SoC for a positive energy trip."""
        vehicle = default_vehicle(soc_start_pct=80.0)
        seg = flat_segment(dist=50.0)
        req = EnergyPredictRequest(vehicle=vehicle, segments=[seg], ambient_temp_c=25.0)
        resp = predict_energy(req)
        assert resp.soc_final_p50_pct < 80.0, "Final SoC must be less than start"

    def test_soc_bounded(self):
        """Final SoC must be between 0 and 100."""
        vehicle = default_vehicle(soc_start_pct=5.0)
        seg = flat_segment(dist=200.0)
        req = EnergyPredictRequest(vehicle=vehicle, segments=[seg], ambient_temp_c=25.0)
        resp = predict_energy(req)
        assert 0.0 <= resp.soc_final_p50_pct <= 100.0
        assert 0.0 <= resp.soc_final_p90_pct <= 100.0

    def test_energy_kwh_reasonable(self):
        """Energy for 10 km at 80 km/h should be roughly 1-3 kWh for typical EV."""
        vehicle = default_vehicle()
        seg = flat_segment(dist=10.0, speed=80.0)
        req = EnergyPredictRequest(vehicle=vehicle, segments=[seg], ambient_temp_c=25.0)
        resp = predict_energy(req)
        assert 0.5 <= resp.total_kwh_p50 <= 5.0, \
            f"10 km energy {resp.total_kwh_p50:.3f} kWh is unreasonable"

    def test_payload_increases_energy(self):
        """Higher payload must increase energy consumption."""
        vehicle_light = default_vehicle(payload_kg=0.0)
        vehicle_heavy = default_vehicle(payload_kg=400.0)
        seg = flat_segment()
        req_light = EnergyPredictRequest(vehicle=vehicle_light, segments=[seg], ambient_temp_c=25.0)
        req_heavy = EnergyPredictRequest(vehicle=vehicle_heavy, segments=[seg], ambient_temp_c=25.0)
        resp_light = predict_energy(req_light)
        resp_heavy = predict_energy(req_heavy)
        assert resp_heavy.total_kwh_p50 > resp_light.total_kwh_p50, \
            "Heavier vehicle must use more energy"

    def test_cold_temperature_increases_energy(self):
        """Cold ambient temperature must increase energy (battery efficiency penalty)."""
        vehicle = default_vehicle()
        seg = flat_segment()
        req_warm = EnergyPredictRequest(vehicle=vehicle, segments=[seg], ambient_temp_c=25.0)
        req_cold = EnergyPredictRequest(vehicle=vehicle, segments=[seg], ambient_temp_c=5.0)
        resp_warm = predict_energy(req_warm)
        resp_cold = predict_energy(req_cold)
        assert resp_cold.total_kwh_p50 > resp_warm.total_kwh_p50, \
            "Cold temperature should increase energy consumption"


class TestFeasibility:
    def test_long_trip_infeasible_low_soc(self):
        """A very long trip with low starting SoC must be infeasible."""
        vehicle = default_vehicle(soc_start_pct=20.0, battery_capacity_kwh=40.0)
        segments = [flat_segment(f"S{i}", dist=50.0) for i in range(6)]  # 300 km
        req = EnergyPredictRequest(vehicle=vehicle, segments=segments, ambient_temp_c=25.0)
        resp = predict_energy(req)
        assert not resp.feasible, "300 km with 20% SoC (40 kWh battery) should be infeasible"

    def test_short_trip_feasible(self):
        """A short 20 km trip with full battery should be feasible."""
        vehicle = default_vehicle(soc_start_pct=100.0, battery_capacity_kwh=40.0)
        seg = flat_segment(dist=20.0)
        req = EnergyPredictRequest(vehicle=vehicle, segments=[seg], ambient_temp_c=25.0)
        resp = predict_energy(req)
        assert resp.feasible, "Short 20 km trip from full battery should be feasible"

    def test_multiple_segments_energy_sum(self):
        """Sum of segment energies must equal total P50."""
        vehicle = default_vehicle()
        segments = [flat_segment(f"S{i}", dist=10.0) for i in range(5)]
        req = EnergyPredictRequest(vehicle=vehicle, segments=segments, ambient_temp_c=25.0)
        resp = predict_energy(req)
        seg_sum = sum(s.net_kwh for s in resp.segments)
        assert abs(seg_sum - resp.total_kwh_p50) < 0.001, \
            f"Segment sum {seg_sum:.4f} != total P50 {resp.total_kwh_p50:.4f}"


class TestUncertainty:
    def test_p90_factor_positive(self):
        """P90 factor must be > 1 (conservative)."""
        factor = _p90_factor(0.12, 0.90)
        assert factor > 1.0

    def test_temp_correction_cold(self):
        """Cold temperature correction factor must be > 1."""
        factor = _temp_correction(10.0)
        assert factor > 1.0

    def test_temp_correction_warm(self):
        """Warm temperature (>= 25C) correction factor must be 1.0."""
        factor = _temp_correction(30.0)
        assert factor == 1.0

    def test_higher_confidence_gives_higher_p90(self):
        """Higher confidence target must give higher P90 estimate."""
        vehicle = default_vehicle()
        seg = flat_segment()
        req_90 = EnergyPredictRequest(vehicle=vehicle, segments=[seg],
                                       ambient_temp_c=25.0, confidence_target=0.90)
        req_95 = EnergyPredictRequest(vehicle=vehicle, segments=[seg],
                                       ambient_temp_c=25.0, confidence_target=0.95)
        resp_90 = predict_energy(req_90)
        resp_95 = predict_energy(req_95)
        assert resp_95.total_kwh_p90 >= resp_90.total_kwh_p90, \
            "P95 estimate should be >= P90 estimate"


# ─── Routing & Charger Tests ──────────────────────────────────────────────────

class TestRoutingFeasibility:
    def test_demo_route_feasible(self):
        """Mumbai-Pune demo route should be feasible with default vehicle from high SoC."""
        from app.models.schemas import RoutePlanRequest
        from app.services.routing_service import plan_routes

        req = RoutePlanRequest(
            origin_lat=19.076, origin_lng=72.8777,
            dest_lat=18.5204, dest_lng=73.8567,
            vehicle=default_vehicle(soc_start_pct=95.0),
            demo_route_id="MUMBAI_PUNE",
        )
        resp = plan_routes(req)
        assert resp.fastest_route is not None
        assert resp.fastest_route.feasible is True
        assert resp.fastest_route.energy_result.soc_final_p90_pct >= req.vehicle.soc_reserve_pct

    def test_deterministic_preferred_charger_fails_and_feasible_alternative_selected(self):
        """
        Deterministic test scenario:
        1. Vehicle starts Mumbai-Pune with 45% SoC (insufficient to complete 148 km without charging).
        2. Preferred corridor charger CHR_MH_003 (Lonavala) is marked unavailable.
        3. Route engine evaluates corridor alternative CHR_MH_004 (Jio-bp Urse) or CHR_MH_001.
        4. Alternative charger is selected, charge time is calculated, and trip remains feasible.
        """
        from app.models.schemas import RoutePlanRequest
        from app.services.routing_service import plan_routes

        # Normal run: CHR_MH_003 is available
        req_normal = RoutePlanRequest(
            origin_lat=19.076, origin_lng=72.8777,
            dest_lat=18.5204, dest_lng=73.8567,
            vehicle=default_vehicle(soc_start_pct=45.0, soc_reserve_pct=15.0),
            demo_route_id="MUMBAI_PUNE",
        )
        resp_normal = plan_routes(req_normal)
        assert resp_normal.fastest_route.charging_stops, "45% SoC on Mumbai-Pune must require a charging stop"
        assert resp_normal.fastest_route.charging_stops[0].charger.charger_id == "CHR_MH_003"

        # Failure run: preferred charger CHR_MH_003 fails
        req_failure = RoutePlanRequest(
            origin_lat=19.076, origin_lng=72.8777,
            dest_lat=18.5204, dest_lng=73.8567,
            vehicle=default_vehicle(soc_start_pct=45.0, soc_reserve_pct=15.0),
            demo_route_id="MUMBAI_PUNE",
            disabled_charger_ids=["CHR_MH_003"],
        )
        resp_failure = plan_routes(req_failure)

        # 1. Preferred failed charger must NOT be used
        used_ids = [cs.charger.charger_id for cs in resp_failure.fastest_route.charging_stops]
        assert "CHR_MH_003" not in used_ids, "Failed charger CHR_MH_003 must not be selected"

        # 2. Alternative corridor charger (CHR_MH_004) must be selected
        assert "CHR_MH_004" in used_ids, f"Expected alternative CHR_MH_004, got {used_ids}"

        # 3. Alternative route must remain battery-feasible with arrival SoC >= reserve
        assert resp_failure.fastest_route.feasible is True, "Alternative route must be feasible"
        assert resp_failure.fastest_route.energy_result.soc_final_p90_pct >= 15.0
        assert resp_failure.fastest_route.feasibility_margin_kwh > 0.0

        # 4. Charging time and energy must be physically computed
        stop = resp_failure.fastest_route.charging_stops[0]
        assert stop.charge_duration_min > 0.0
        assert stop.charge_energy_kwh > 0.0
        assert stop.depart_soc_pct > stop.arrive_soc_pct

        # 5. Explanatory reporting of the failure scenario
        assert resp_failure.charger_failure_scenario is not None
        assert "CHR_MH_003" in resp_failure.charger_failure_scenario or "ChargeZone" in resp_failure.charger_failure_scenario

    def test_infeasible_trip_due_to_battery_exhaustion(self):
        """
        Trip starting with insufficient SoC (10% on 30 kWh) must be flagged infeasible
        due to battery exhaustion before reaching a charging stop.
        """
        from app.models.schemas import RoutePlanRequest
        from app.services.routing_service import plan_routes

        req = RoutePlanRequest(
            origin_lat=19.076, origin_lng=72.8777,
            dest_lat=18.5204, dest_lng=73.8567,
            vehicle=default_vehicle(soc_start_pct=10.0, battery_capacity_kwh=30.0, soc_reserve_pct=15.0),
            demo_route_id="MUMBAI_PUNE",
        )
        resp = plan_routes(req)
        assert resp.fastest_route.feasible is False, "Trip starting with 10% SoC should be infeasible"
        assert "INFEASIBLE" in resp.fastest_route.explanation
        assert resp.fastest_route.risk_score >= 0.90

    def test_reserve_violation_flagged_infeasible(self):
        """
        When vehicle arrives with positive SoC that is strictly below the required reserve,
        the route engine must flag feasible == False and report negative margin.
        """
        from app.models.schemas import RoutePlanRequest
        from app.services.routing_service import plan_routes

        # 60% start SoC with 25% reserve requirement and all corridor chargers disabled
        req = RoutePlanRequest(
            origin_lat=19.076, origin_lng=72.8777,
            dest_lat=18.5204, dest_lng=73.8567,
            vehicle=default_vehicle(soc_start_pct=60.0, soc_reserve_pct=25.0),
            demo_route_id="MUMBAI_PUNE",
            disabled_charger_ids=["CHR_MH_003", "CHR_MH_004", "CHR_MH_001"],
        )
        resp = plan_routes(req)
        route = resp.fastest_route

        # Arrival SoC is positive (e.g. ~10-15%) but below required 25% reserve
        p90_soc = route.energy_result.soc_final_p90_pct
        assert p90_soc < 25.0, f"Expected P90 SoC < 25%, got {p90_soc}"
        assert route.feasible is False, "Route violating reserve constraint must have feasible == False"
        assert route.feasibility_margin_kwh < 0.0, "Margin must be negative when reserve is violated"
        assert "reserve" in route.explanation.lower()

    def test_charger_connector_incompatibility_enforcement(self):
        """
        Vehicle with CHAdeMO-only connector must not use CCS2-only corridor chargers.
        If route requires charging and no compatible charger exists, route must be infeasible.
        """
        from app.models.schemas import RoutePlanRequest
        from app.services.routing_service import plan_routes

        # Vehicle with only CHAdeMO connector
        chademo_vehicle = default_vehicle(
            soc_start_pct=50.0,
            soc_reserve_pct=15.0,
            connector_types=[ConnectorType.CHAdeMO]
        )
        req_incompatible = RoutePlanRequest(
            origin_lat=19.076, origin_lng=72.8777,
            dest_lat=18.5204, dest_lng=73.8567,
            vehicle=chademo_vehicle,
            demo_route_id="MUMBAI_PUNE",
        )
        resp_incompatible = plan_routes(req_incompatible)

        # Check no incompatible charger stops were assigned
        for stop in resp_incompatible.fastest_route.charging_stops:
            connectors = [ct.value for ct in stop.charger.connector_types]
            assert "CHAdeMO" in connectors

        # Because corridor only has CCS2/Type2, no charging stop is possible -> infeasible
        assert resp_incompatible.fastest_route.feasible is False
        assert "incompatib" in resp_incompatible.fastest_route.explanation.lower()

        # In contrast, CCS2-equipped vehicle at same 50% SoC can charge and is feasible
        ccs2_vehicle = default_vehicle(
            soc_start_pct=50.0,
            soc_reserve_pct=15.0,
            connector_types=[ConnectorType.CCS2]
        )
        req_compatible = RoutePlanRequest(
            origin_lat=19.076, origin_lng=72.8777,
            dest_lat=18.5204, dest_lng=73.8567,
            vehicle=ccs2_vehicle,
            demo_route_id="MUMBAI_PUNE",
        )
        resp_compatible = plan_routes(req_compatible)
        assert resp_compatible.fastest_route.feasible is True
        assert len(resp_compatible.fastest_route.charging_stops) > 0

    def test_risk_aware_route_selects_high_reliability_charger(self):
        """
        Risk-aware route must reject CHR_MH_003 (score 0.62 < 0.75 threshold)
        and choose CHR_MH_004 (score 0.94 >= 0.75).
        """
        from app.models.schemas import RoutePlanRequest
        from app.services.routing_service import plan_routes

        req = RoutePlanRequest(
            origin_lat=19.076, origin_lng=72.8777,
            dest_lat=18.5204, dest_lng=73.8567,
            vehicle=default_vehicle(soc_start_pct=45.0, soc_reserve_pct=15.0),
            demo_route_id="MUMBAI_PUNE",
        )
        resp = plan_routes(req)

        # Fastest route uses first encountered charger CHR_MH_003
        assert resp.fastest_route.charging_stops[0].charger.charger_id == "CHR_MH_003"

        # Risk-aware route filters out CHR_MH_003 (reliability < 0.75) and uses CHR_MH_004
        assert resp.risk_aware_route is not None
        assert resp.risk_aware_route.charging_stops[0].charger.charger_id == "CHR_MH_004"
        assert resp.risk_aware_route.risk_score <= resp.fastest_route.risk_score

    def test_neo4j_used_flag_and_demo_fallback_reporting(self):
        """
        When Neo4j is offline or unauthenticated, neo4j_used must be False and
        data_source must explicitly identify deterministic demo fallback.
        """
        from app.models.schemas import RoutePlanRequest
        from app.services.routing_service import plan_routes

        req = RoutePlanRequest(
            origin_lat=19.076, origin_lng=72.8777,
            dest_lat=18.5204, dest_lng=73.8567,
            vehicle=default_vehicle(),
            demo_route_id="MUMBAI_PUNE",
        )
        resp = plan_routes(req)
        assert resp.neo4j_used is False, "Without valid Neo4j credentials, neo4j_used must be False"
        assert "SIMULATED demo data" in resp.data_source
        assert "deterministic demo fallback" in resp.data_source

    def test_uncertainty_disclaimer_no_false_calibration(self):
        """
        Verify that uncertainty method and data disclaimers never claim real-world
        calibration or empirical validation.
        """
        from app.models.schemas import RoutePlanRequest
        from app.services.routing_service import plan_routes
        from app.services.energy_model import ASSUMPTIONS

        req = RoutePlanRequest(
            origin_lat=19.076, origin_lng=72.8777,
            dest_lat=18.5204, dest_lng=73.8567,
            vehicle=default_vehicle(),
            demo_route_id="MUMBAI_PUNE",
        )
        resp = plan_routes(req)

        disclaimer = resp.fastest_route.energy_result.data_disclaimer
        assert "NOT validated against independent real-world" in disclaimer

        # Energy model default assumptions must explicitly state analytical nature
        assert any("ANALYTICAL" in a and "not validated" in a for a in ASSUMPTIONS)


class TestChargingPhysicsAndRoutingConstraints:
    def test_charging_time_physics_calculation(self):
        """
        Verify charging time formula: t_minutes = (kWh_needed / P_charger_kw) * 60
        e.g., charging 20 kWh on a 50 kW DC fast charger must take exactly 24.0 minutes.
        """
        from app.services.routing_service import _compute_charge_time_min

        # 40 kWh battery: charge from 20% to 80% (60% delta = 24 kWh) on 60 kW charger -> 24 / 60 * 60 = 24.0 min
        mins, kwh = _compute_charge_time_min(
            arrive_soc_pct=20.0,
            target_soc_pct=80.0,
            capacity_kwh=40.0,
            charger_power_kw=60.0
        )
        assert abs(kwh - 24.0) < 0.01
        assert abs(mins - 24.0) < 0.1

        # 30 kWh battery: charge from 10% to 80% (70% delta = 21 kWh) on 30 kW charger -> 21 / 30 * 60 = 42.0 min
        mins2, kwh2 = _compute_charge_time_min(
            arrive_soc_pct=10.0,
            target_soc_pct=80.0,
            capacity_kwh=30.0,
            charger_power_kw=30.0
        )
        assert abs(kwh2 - 21.0) < 0.01
        assert abs(mins2 - 42.0) < 0.1

    def test_charging_time_zero_or_negative_delta(self):
        """If arrive SoC >= target SoC, charging duration and added energy must be 0."""
        from app.services.routing_service import _compute_charge_time_min

        mins, kwh = _compute_charge_time_min(85.0, 80.0, 40.0, 50.0)
        assert mins == 0.0
        assert kwh == 0.0

    def test_multi_segment_directed_battery_tracking(self):
        """
        Battery SoC must decrease progressively across directed segments,
        recovering appropriate energy on steep downhill segments.
        """
        vehicle = default_vehicle(soc_start_pct=80.0, battery_capacity_kwh=40.0)
        uphill = RouteSegment(segment_id="UP_01", distance_km=20.0, avg_speed_kmh=50.0, gradient_pct=3.0, road_type="rural", name="Ghat Climb")
        downhill = RouteSegment(segment_id="DOWN_01", distance_km=20.0, avg_speed_kmh=60.0, gradient_pct=-2.5, road_type="highway", name="Ghat Descent")

        res_up, soc_up = predict_segment(uphill, vehicle, soc_before_pct=80.0)
        res_down, soc_down = predict_segment(downhill, vehicle, soc_before_pct=soc_up)

        assert soc_up < 80.0, "Uphill climb must reduce SoC"
        assert res_down.regen_kj < 0.0, "Downhill segment must engage regenerative braking"
        assert res_up.net_kwh > res_down.net_kwh, "Uphill energy must exceed downhill energy"


class TestCustomRouteAndGeocoding:
    def test_custom_route_planning_arbitrary_cities(self):
        """
        Verify that user can plan a route between ANY arbitrary Indian cities
        (e.g. New Delhi to Jaipur) without being limited to preset demo routes.
        """
        from app.models.schemas import RoutePlanRequest
        from app.services.routing_service import plan_routes

        v = default_vehicle(battery_capacity_kwh=40.5, soc_start_pct=90.0, soc_reserve_pct=10.0)
        req = RoutePlanRequest(
            origin_lat=28.6139, origin_lng=77.2090,
            dest_lat=26.9124, dest_lng=75.7873,
            origin_name="New Delhi",
            dest_name="Jaipur",
            vehicle=v,
            ambient_temp_c=28.0,
            confidence_target=0.90,
            demo_route_id=None,  # Custom mode
        )
        resp = plan_routes(req)

        assert resp.fastest_route is not None
        # Real highway driving distance Delhi to Jaipur is ~280+ km
        assert resp.fastest_route.distance_km >= 200.0, f"Expected real highway distance, got {resp.fastest_route.distance_km}"
        assert len(resp.fastest_route.segments) >= 2, "Custom route must be decomposed into segments"
        assert resp.fastest_route.road_geometry is not None and len(resp.fastest_route.road_geometry) > 10
        assert "Dynamic Road-Snapped" in resp.data_source
        assert resp.fastest_route.energy_result.total_kwh_p50 > 0.0

    def test_geocoding_service_search(self):
        """Verify Indian place search returns accurate coordinates and names."""
        from app.services.geocoding_service import search_locations

        results = search_locations("jaipur")
        assert len(results) > 0
        assert "Jaipur" in results[0]["name"]
        assert 25.0 <= results[0]["lat"] <= 28.0
        assert 74.0 <= results[0]["lng"] <= 77.0

        mumbai_res = search_locations("mumbai")
        assert len(mumbai_res) > 0
        assert "Mumbai" in mumbai_res[0]["name"]
        assert 18.0 <= mumbai_res[0]["lat"] <= 20.0




class TestChargerReliability:
    def test_unknown_charger_gets_prior(self):
        """Charger with no reports should get 0.5 reliability (not 1.0)."""
        from app.services.charger_service import compute_reliability
        result = compute_reliability("NONEXISTENT_CHR")
        assert result["score"] == 0.5, "Unknown charger should get 0.5 prior"
        assert result["freshness_hours"] is None

    def test_all_success_high_score(self):
        """Charger with recent all-success reports should have high score."""
        from app.services.charger_service import compute_reliability
        # CHR_DL_001 has 3 success reports in seed data
        result = compute_reliability("CHR_DL_001")
        assert result["score"] >= 0.70, f"CHR_DL_001 should have high reliability, got {result['score']}"

    def test_mixed_reports_medium_score(self):
        """Charger with mixed reports should have medium score."""
        from app.services.charger_service import compute_reliability
        # CHR_MH_003 has 1 success, 2 failures
        result = compute_reliability("CHR_MH_003")
        assert 0.2 < result["score"] < 0.8, f"CHR_MH_003 should have medium reliability, got {result['score']}"


class TestSimulation:
    def test_simulation_reproducible(self):
        """Same noise_seed must produce same simulated actual_kwh."""
        from app.models.schemas import TripSimulateRequest
        from app.routers.trips import simulate_trip

        req = TripSimulateRequest(
            route_id="DELHI_GURUGRAM",
            vehicle=default_vehicle(),
            noise_seed=123,
        )
        r1 = simulate_trip(req)
        r2 = simulate_trip(req)
        assert abs(r1.actual_kwh - r2.actual_kwh) < 0.001, \
            "Same seed should give same simulated actual_kwh"

    def test_simulation_within_p90_mostly(self):
        """With default noise (σ=8%), most simulations should be within P90."""
        from app.models.schemas import TripSimulateRequest
        from app.routers.trips import simulate_trip

        within_count = 0
        n = 20
        for seed in range(n):
            req = TripSimulateRequest(
                route_id="DELHI_GURUGRAM",
                vehicle=default_vehicle(),
                noise_seed=seed,
            )
            r = simulate_trip(req)
            if r.within_p90:
                within_count += 1

        coverage = within_count / n
        # P90 with σ=8% noise should cover ≥80% of synthetic draws
        # (Not a claim about real-world coverage)
        assert coverage >= 0.70, \
            f"SYNTHETIC P90 coverage {coverage:.0%} is unexpectedly low (seed 0-{n-1})"
