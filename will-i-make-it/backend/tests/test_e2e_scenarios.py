"""
End-to-End Mission Scenario Suite (Scenarios A through J)
========================================================
Validates end-to-end EV journey planning, route segmentation, 1-RC Thevenin
battery dynamics, C4 thermal coupling, charger reliability, and feasibility decisions.
"""
import pytest
from app.models.schemas import RoutePlanRequest, VehicleProfile, ConnectorType
from app.services.routing_service import plan_routes
from app.services.demo_data import get_demo_route


def _base_vehicle(
    battery_kwh: float = 40.0,
    soc_start: float = 80.0,
    soc_reserve: float = 10.0,
    payload_kg: float = 0.0,
    ac_kw: float = 1.5,
) -> VehicleProfile:
    return VehicleProfile(
        battery_capacity_kwh=battery_kwh,
        soc_start_pct=soc_start,
        soc_reserve_pct=soc_reserve,
        vehicle_mass_kg=1550.0,
        drag_coefficient=0.29,
        frontal_area_m2=2.3,
        rolling_resistance=0.012,
        drivetrain_efficiency=0.88,
        regen_efficiency=0.65,
        connector_types=[ConnectorType.CCS2, ConnectorType.Type2_AC],
        ac_load_kw=ac_kw,
        payload_kg=payload_kg,
    )


# Scenario A: Mumbai -> Pune Expressway (148 km, Ghats incline & downhill regen)
def test_scenario_a_mumbai_pune():
    demo = get_demo_route("MUMBAI_PUNE")
    req = RoutePlanRequest(
        origin_lat=demo["origin"]["lat"],
        origin_lng=demo["origin"]["lng"],
        dest_lat=demo["destination"]["lat"],
        dest_lng=demo["destination"]["lng"],
        vehicle=_base_vehicle(battery_kwh=50.0, soc_start=95.0, soc_reserve=12.0),
        ambient_temp_c=28.0,
        demo_route_id="MUMBAI_PUNE",
    )
    res = plan_routes(req)
    assert res.fastest_route.feasible is True
    assert res.fastest_route.energy_result.total_kwh_p50 > 15.0
    # Provenance of regen present
    regen_seg = [s for s in res.fastest_route.energy_result.segments if s.regen_kj < 0]
    assert len(regen_seg) > 0
    assert res.fastest_route.feasibility_status in ("WILL_MAKE_IT", "LOW_RESERVE")


# Scenario B: Delhi -> Gurugram (32 km short commute, direct transit)
def test_scenario_b_delhi_gurugram():
    demo = get_demo_route("DELHI_GURUGRAM")
    req = RoutePlanRequest(
        origin_lat=demo["origin"]["lat"],
        origin_lng=demo["origin"]["lng"],
        dest_lat=demo["destination"]["lat"],
        dest_lng=demo["destination"]["lng"],
        vehicle=_base_vehicle(battery_kwh=40.0, soc_start=70.0, soc_reserve=10.0),
        ambient_temp_c=25.0,
        demo_route_id="DELHI_GURUGRAM",
    )
    res = plan_routes(req)
    assert res.fastest_route.feasible is True
    assert len(res.fastest_route.charging_stops) == 0
    assert res.fastest_route.energy_result.soc_final_p90_pct > 50.0
    assert res.fastest_route.feasibility_status == "WILL_MAKE_IT"


# Scenario C: Bengaluru -> Mysuru (143 km rolling terrain)
def test_scenario_c_bengaluru_mysuru():
    demo = get_demo_route("BENGALURU_MYSURU")
    req = RoutePlanRequest(
        origin_lat=demo["origin"]["lat"],
        origin_lng=demo["origin"]["lng"],
        dest_lat=demo["destination"]["lat"],
        dest_lng=demo["destination"]["lng"],
        vehicle=_base_vehicle(battery_kwh=40.0, soc_start=85.0, soc_reserve=10.0),
        ambient_temp_c=24.0,
        demo_route_id="BENGALURU_MYSURU",
    )
    res = plan_routes(req)
    assert res.fastest_route.distance_km > 130.0
    assert res.fastest_route.energy_result.total_kwh_p50 > 12.0


# Scenario D: Delhi -> Agra (210 km long highway range test)
def test_scenario_d_delhi_agra():
    demo = get_demo_route("DELHI_AGRA")
    req = RoutePlanRequest(
        origin_lat=demo["origin"]["lat"],
        origin_lng=demo["origin"]["lng"],
        dest_lat=demo["destination"]["lat"],
        dest_lng=demo["destination"]["lng"],
        vehicle=_base_vehicle(battery_kwh=40.0, soc_start=60.0, soc_reserve=10.0),
        ambient_temp_c=30.0,
        demo_route_id="DELHI_AGRA",
    )
    res = plan_routes(req)
    # Starting at 60% on 40kWh for 210km highway is demanding
    assert res.fastest_route.energy_result.total_kwh_p90 > 25.0


# Scenario E: Charger Outage & Dynamic Corridor Rerouting
def test_scenario_e_charger_failure_reroute():
    demo = get_demo_route("MUMBAI_PUNE")
    # Low battery forces charging
    v = _base_vehicle(battery_kwh=40.0, soc_start=28.0, soc_reserve=10.0)
    req_normal = RoutePlanRequest(
        origin_lat=demo["origin"]["lat"],
        origin_lng=demo["origin"]["lng"],
        dest_lat=demo["destination"]["lat"],
        dest_lng=demo["destination"]["lng"],
        vehicle=v,
        ambient_temp_c=25.0,
        demo_route_id="MUMBAI_PUNE",
    )
    res_normal = plan_routes(req_normal)
    primary_charger_id = res_normal.fastest_route.charging_stops[0].charger.charger_id

    # Now disable that charger
    req_disabled = RoutePlanRequest(
        origin_lat=demo["origin"]["lat"],
        origin_lng=demo["origin"]["lng"],
        dest_lat=demo["destination"]["lat"],
        dest_lng=demo["destination"]["lng"],
        vehicle=v,
        ambient_temp_c=25.0,
        demo_route_id="MUMBAI_PUNE",
        disabled_charger_ids=[primary_charger_id],
    )
    res_disabled = plan_routes(req_disabled)
    # Disabled charger is not in the updated route stops
    updated_charger_ids = [cs.charger.charger_id for cs in res_disabled.fastest_route.charging_stops]
    assert primary_charger_id not in updated_charger_ids


# Scenario F: Heavy Payload (Cargo + 4 Passengers = +350 kg)
def test_scenario_f_heavy_payload():
    demo = get_demo_route("DELHI_GURUGRAM")
    v_light = _base_vehicle(payload_kg=0.0)
    v_heavy = _base_vehicle(payload_kg=350.0)

    res_light = plan_routes(RoutePlanRequest(
        origin_lat=demo["origin"]["lat"], origin_lng=demo["origin"]["lng"],
        dest_lat=demo["destination"]["lat"], dest_lng=demo["destination"]["lng"],
        vehicle=v_light, ambient_temp_c=25.0, demo_route_id="DELHI_GURUGRAM",
    ))
    res_heavy = plan_routes(RoutePlanRequest(
        origin_lat=demo["origin"]["lat"], origin_lng=demo["origin"]["lng"],
        dest_lat=demo["destination"]["lat"], dest_lng=demo["destination"]["lng"],
        vehicle=v_heavy, ambient_temp_c=25.0, demo_route_id="DELHI_GURUGRAM",
    ))

    # Heavy vehicle consumes strictly more energy
    assert res_heavy.fastest_route.energy_result.total_kwh_p50 > res_light.fastest_route.energy_result.total_kwh_p50


# Scenario G: Extreme Cold Climate (-5°C)
def test_scenario_g_extreme_cold_weather():
    demo = get_demo_route("DELHI_GURUGRAM")
    v = _base_vehicle()
    res_warm = plan_routes(RoutePlanRequest(
        origin_lat=demo["origin"]["lat"], origin_lng=demo["origin"]["lng"],
        dest_lat=demo["destination"]["lat"], dest_lng=demo["destination"]["lng"],
        vehicle=v, ambient_temp_c=25.0, demo_route_id="DELHI_GURUGRAM",
    ))
    res_cold = plan_routes(RoutePlanRequest(
        origin_lat=demo["origin"]["lat"], origin_lng=demo["origin"]["lng"],
        dest_lat=demo["destination"]["lat"], dest_lng=demo["destination"]["lng"],
        vehicle=v, ambient_temp_c=-5.0, demo_route_id="DELHI_GURUGRAM",
    ))
    # Cold ambient increases battery resistance and energy consumption
    assert res_cold.fastest_route.energy_result.total_kwh_p50 > res_warm.fastest_route.energy_result.total_kwh_p50


# Scenario H: Extreme Hot Summer Climate (42°C)
def test_scenario_h_extreme_hot_weather():
    demo = get_demo_route("MUMBAI_PUNE")
    v = _base_vehicle(battery_kwh=50.0, soc_start=90.0)
    res_hot = plan_routes(RoutePlanRequest(
        origin_lat=demo["origin"]["lat"], origin_lng=demo["origin"]["lng"],
        dest_lat=demo["destination"]["lat"], dest_lng=demo["destination"]["lng"],
        vehicle=v, ambient_temp_c=42.0, demo_route_id="MUMBAI_PUNE",
    ))
    # Thermal response verified
    assert res_hot.fastest_route.max_battery_temp_c is not None
    assert res_hot.fastest_route.max_battery_temp_c >= 40.0


# Scenario I: Low Starting SOC & Infeasibility
def test_scenario_i_infeasible_low_soc():
    demo = get_demo_route("DELHI_AGRA")
    # Disable corridor chargers so 210 km cannot be completed with 15% starting SOC
    charger_ids = demo.get("charger_ids", [])
    v = _base_vehicle(battery_kwh=40.0, soc_start=15.0, soc_reserve=10.0)
    res = plan_routes(RoutePlanRequest(
        origin_lat=demo["origin"]["lat"], origin_lng=demo["origin"]["lng"],
        dest_lat=demo["destination"]["lat"], dest_lng=demo["destination"]["lng"],
        vehicle=v, ambient_temp_c=25.0, demo_route_id="DELHI_AGRA",
        disabled_charger_ids=charger_ids,
    ))
    assert res.fastest_route.feasible is False
    assert res.fastest_route.feasibility_margin_kwh < 0.0


# Scenario J: Multi-Boundary Energy Conservation Verification
def test_scenario_j_energy_conservation():
    from app.services.energy.journey_simulator import simulate_journey
    demo = get_demo_route("MUMBAI_PUNE")
    from app.models.schemas import RouteSegment
    segs = [RouteSegment(**s) for s in demo["segments"]]
    summary = simulate_journey(
        segments=segs,
        vehicle_mass_kg=1600.0,
        frontal_area_m2=2.3,
        drag_coeff=0.29,
        rolling_res_coeff=0.012,
        battery_capacity_kwh=50.0,
        soc_start_pct=90.0,
        soc_reserve_pct=15.0,
        ambient_temp_c=25.0,
    )
    # Total energy conservation residual across the entire 148 km corridor is bounded near zero
    assert summary.energy_residual_total_j < 1e-3
