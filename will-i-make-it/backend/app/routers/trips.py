"""Trip simulation and history endpoints."""
import uuid
import json
from fastapi import APIRouter, HTTPException
from app.models.schemas import TripSimulateRequest, TripRecord, VehicleProfile
from app.services.charger_service import save_trip, get_trip
from app.services.routing_service import plan_routes
from app.models.schemas import RoutePlanRequest
from app.services.demo_data import get_demo_route
import numpy as np

router = APIRouter(prefix="/api/trips", tags=["Trips"])

DISCLAIMER = (
    "SIMULATED trip. Actual energy drawn from the physics model + "
    "Gaussian noise to simulate real-world variance. "
    "MAE and coverage statistics shown are SYNTHETIC — "
    "computed against the same model with noise, not independent real-world data."
)


@router.post("/simulate", response_model=TripRecord)
def simulate_trip(req: TripSimulateRequest):
    """
    Simulate a completed EV trip for demonstration and metric reporting.

    Adds Gaussian noise (σ=8% of P50) to the physics prediction to simulate
    real-world variance. The resulting 'actual_kwh' is SYNTHETIC.
    Coverage metrics are computed against synthetic actuals only.

    **Do not present these metrics as real-world validation.**
    """
    # Get a route plan
    demo = get_demo_route(req.route_id)
    if not demo:
        raise HTTPException(status_code=404, detail=f"Route '{req.route_id}' not found")

    plan_req = RoutePlanRequest(
        origin_lat=demo["origin"]["lat"],
        origin_lng=demo["origin"]["lng"],
        dest_lat=demo["destination"]["lat"],
        dest_lng=demo["destination"]["lng"],
        vehicle=req.vehicle,
        ambient_temp_c=req.ambient_temp_c,
        demo_route_id=req.route_id,
    )

    from app.services.routing_service import plan_routes
    plan = plan_routes(plan_req)
    energy = plan.fastest_route.energy_result

    # Simulate actual energy with reproducible noise
    rng = np.random.default_rng(req.noise_seed or 42)
    noise_pct = rng.normal(0, 0.08)  # ±8% noise (σ)
    actual_kwh = energy.total_kwh_p50 * (1 + noise_pct)
    actual_kwh = max(0.1, actual_kwh)

    soc_final = req.vehicle.soc_start_pct - (actual_kwh / req.vehicle.battery_capacity_kwh) * 100.0
    soc_final = max(0.0, min(100.0, soc_final))

    trip_id = str(uuid.uuid4())[:8]
    within_p90 = actual_kwh <= energy.total_kwh_p90

    save_trip(
        trip_id=trip_id,
        route_id=req.route_id,
        actual_kwh=round(actual_kwh, 3),
        p50=energy.total_kwh_p50,
        p90=energy.total_kwh_p90,
        soc_final=round(soc_final, 2),
        vehicle_json=json.dumps(req.vehicle.model_dump()),
        notes=DISCLAIMER,
    )

    return TripRecord(
        trip_id=trip_id,
        route_id=req.route_id,
        created_at=__import__("datetime").datetime.now(__import__("datetime").timezone.utc).isoformat(),
        actual_kwh=round(actual_kwh, 3),
        predicted_kwh_p50=energy.total_kwh_p50,
        predicted_kwh_p90=energy.total_kwh_p90,
        within_p90=within_p90,
        soc_final_pct=round(soc_final, 2),
        notes=DISCLAIMER,
    )


@router.get("/{trip_id}", response_model=TripRecord)
def get_trip_record(trip_id: str):
    """Retrieve a previously simulated trip record."""
    record = get_trip(trip_id)
    if not record:
        raise HTTPException(status_code=404, detail=f"Trip '{trip_id}' not found")

    return TripRecord(
        trip_id=record["trip_id"],
        route_id=record["route_id"],
        created_at=record["created_at"],
        actual_kwh=record["actual_kwh"],
        predicted_kwh_p50=record["predicted_p50"],
        predicted_kwh_p90=record["predicted_p90"],
        within_p90=bool(record["within_p90"]),
        soc_final_pct=record["soc_final_pct"],
        notes=record.get("notes", ""),
    )
