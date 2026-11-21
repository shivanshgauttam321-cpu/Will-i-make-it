"""
Valhalla Open-Source Routing Fallback Provider
==============================================
Client for Valhalla routing instances (self-hosted or public).
Supports turn-by-turn maneuvers, road types, and shape decoding.
"""
from __future__ import annotations

import os
import json
import urllib.request
from datetime import datetime, timezone
from typing import Tuple, Optional, Dict, Any, List

from app.domain.provenance import DataProvenance, DataStatus, SourceType
from app.services.routing.base import (
    RoutingProvider,
    ProviderRouteResult,
    ProviderStep,
    RoutingProviderError,
)


def _decode_polyline6(encoded: str) -> List[Tuple[float, float]]:
    """Decode a Valhalla polyline6 string into [(lat, lng), ...] with precision 1e-6."""
    points = []
    index = 0
    lat = 0
    lng = 0
    length = len(encoded)

    while index < length:
        # Latitude
        shift = 0
        result = 0
        while True:
            byte = ord(encoded[index]) - 63
            index += 1
            result |= (byte & 0x1F) << shift
            shift += 5
            if byte < 0x20:
                break
        dlat = ~(result >> 1) if (result & 1) else (result >> 1)
        lat += dlat

        # Longitude
        shift = 0
        result = 0
        while True:
            byte = ord(encoded[index]) - 63
            index += 1
            result |= (byte & 0x1F) << shift
            shift += 5
            if byte < 0x20:
                break
        dlng = ~(result >> 1) if (result & 1) else (result >> 1)
        lng += dlng

        points.append((lat / 1e6, lng / 1e6))

    return points


class ValhallaRoutingProvider(RoutingProvider):
    """Routing engine using a Valhalla HTTP endpoint."""

    def __init__(self, base_url: Optional[str] = None, timeout_seconds: float = 8.0):
        self.base_url = (base_url or os.environ.get("VALHALLA_URL", "")).strip().rstrip("/")
        self.timeout_seconds = timeout_seconds

    @property
    def provider_name(self) -> str:
        return "Valhalla"

    def is_available(self) -> bool:
        """True only if an explicit Valhalla endpoint URL is configured."""
        return bool(self.base_url)

    def get_route(
        self,
        origin: Tuple[float, float],
        destination: Tuple[float, float],
        options: Optional[Dict[str, Any]] = None,
    ) -> ProviderRouteResult:
        if not self.is_available():
            raise RoutingProviderError(
                "Valhalla",
                "Valhalla endpoint URL (VALHALLA_URL) is not configured in environment."
            )

        olat, olng = origin
        dlat, dlng = destination
        opts = options or {}
        costing = opts.get("costing", "auto")

        payload = {
            "locations": [
                {"lat": olat, "lon": olng},
                {"lat": dlat, "lon": dlng},
            ],
            "costing": costing,
            "directions_options": {"units": "kilometers"},
        }

        url = f"{self.base_url}/route"
        req_data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=req_data,
            headers={"Content-Type": "application/json", "User-Agent": "WillIMakeIt-EV/1.0"},
            method="POST",
        )

        try:
            with urllib.request.urlopen(req, timeout=self.timeout_seconds) as resp:
                body = json.loads(resp.read().decode())
                trip = body.get("trip", {})
                legs = trip.get("legs", [])
                if not legs:
                    raise RoutingProviderError("Valhalla", "No route legs returned by Valhalla.")

                leg = legs[0]
                shape = leg.get("shape", "")
                decoded_geom = _decode_polyline6(shape) if shape else [(olat, olng), (dlat, dlng)]

                steps: List[ProviderStep] = []
                for m in leg.get("maneuvers", []):
                    steps.append(ProviderStep(
                        instruction=m.get("instruction"),
                        name=m.get("street_names", [None])[0] if m.get("street_names") else None,
                        distance_m=float(m.get("length", 0.0)) * 1000.0,
                        duration_s=float(m.get("time", 0.0)),
                        start_coordinate=(olat, olng),
                        end_coordinate=(dlat, dlng),
                    ))

                return ProviderRouteResult(
                    provider_name=self.provider_name,
                    distance_m=float(trip.get("summary", {}).get("length", 0.0)) * 1000.0,
                    duration_s=float(trip.get("summary", {}).get("time", 0.0)),
                    geometry=decoded_geom,
                    steps=steps,
                    raw_metadata=body,
                    provenance=DataProvenance(
                        status=DataStatus.ESTIMATED,
                        source_name="Valhalla Routing Engine",
                        source_type=SourceType.STATISTICAL_INFERENCE,
                        source_reference=url,
                        notes="Algorithmic shortest-path calculation over road network topology; not physical telemetry.",
                        observed_at=datetime.now(timezone.utc),
                    ),
                )
        except RoutingProviderError:
            raise
        except Exception as e:
            raise RoutingProviderError("Valhalla", f"Query failed: {e}")
