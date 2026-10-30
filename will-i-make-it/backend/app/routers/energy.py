"""Energy prediction endpoints."""
from fastapi import APIRouter, HTTPException
from app.models.schemas import EnergyPredictRequest, EnergyPredictResponse
from app.services.energy_model import predict_energy

router = APIRouter(prefix="/api/energy", tags=["Energy"])


@router.post("/predict", response_model=EnergyPredictResponse)
def predict(req: EnergyPredictRequest):
    """
    Predict trip energy consumption for given vehicle and route segments.

    Returns P50 (expected) and P90 (conservative) energy estimates,
    per-segment breakdown, and feasibility relative to SoC reserve.

    **Note:** All estimates are physics-model-based with synthetic uncertainty.
    P90 coverage is NOT validated against independent Indian EV data.
    """
    try:
        return predict_energy(req)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Energy prediction failed: {str(e)}")
