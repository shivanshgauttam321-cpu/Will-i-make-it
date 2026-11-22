"""
OSRM (Open Source Routing Machine) Routing Provider
===================================================
Baseline open-source routing provider tested and operational across India.
Fetches real turn-by-turn road driving geometry, step maneuvers, distance, and duration.
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


class OSRMRoutingProvider(RoutingProvider):
    """Client for OSRM v5 HTTP route service."""

    DEFAULT_BASE_URL = "https://router.project-osrm.org"

    def __init__(self, base_url: Optional[str] = None, timeout_seconds: float = 8.0):
        self.base_url = (base_url or os.environ.get("OSRM_URL", self.DEFAULT_BASE_URL)).strip().rstrip("/")
        self.timeout_seconds = timeout_seconds

    @property
    def provider_name(self) -> str:
        return "OSRM (Open Source Routing Machine)"

    def is_available(self) -> bool:
        """OSRM is available by default via public or configured self-hosted endpoint."""
        return bool(self.base_url)

    def get_route(
        self,
        origin: Tuple[float, float],
        destination: Tuple[float, float],
        options: Optional[Dict[str, Any]] = None,
    ) -> ProviderRouteResult:
        olat, olng = origin
        dlat, dlng = destination
        opts = options or {}
        alternatives = "true" if opts.get("alternatives", False) else "false"

        # Coordinates format in OSRM: {lng},{lat};{lng},{lat}
        coords = f"{olng:.6f},{olat:.6f};{dlng:.6f},{dlat:.6f}"
        url = (
            f"{self.base_url}/route/v1/driving/{coords}"
            f"?overview=full&geometries=geojson&steps=true&alternatives={alternatives}"
        )

        req = urllib.request.Request(url, headers={"User-Agent": "WillIMakeIt-EV/1.0"})
        try:
            with urllib.request.urlopen(req, timeout=self.timeout_seconds) as resp:
                data = json.loads(resp.read().decode())
                if data.get("code") != "Ok" or not data.get("routes"):
                    msg = data.get("message", "No route found between specified coordinates.")
                    raise RoutingProviderError("OSRM", msg)

                routes_data = data["routes"]
                primary_route = routes_data[0]

                raw_coords = primary_route.get("geometry", {}).get("coordinates", [])
                # Convert GeoJSON [lng, lat] to [(lat, lng)]
                lat_lng_geom = [(float(pt[1]), float(pt[0])) for pt in raw_coords]
                if not lat_lng_geom:
                    lat_lng_geom = [(olat, olng), (dlat, dlng)]

                steps: List[ProviderStep] = []
                for leg in primary_route.get("legs", []):
                    for st in leg.get("steps", []):
                        st_coords = st.get("geometry", {}).get("coordinates", [])
                        st_pts = [(float(p[1]), float(p[0])) for p in st_coords] if st_coords else None
                        st_start = st_pts[0] if st_pts else (olat, olng)
                        st_end = st_pts[-1] if st_pts else (dlat, dlng)
                        maneuver = st.get("maneuver", {})
                        instruction = f"{maneuver.get('type', '')} {maneuver.get('modifier', '')}".strip()

                        steps.append(ProviderStep(
                            name=st.get("name") or None,
                            instruction=instruction or None,
                            distance_m=float(st.get("distance", 0.0)),
                            duration_s=float(st.get("duration", 0.0)),
                            start_coordinate=st_start,
                            end_coordinate=st_end,
                            geometry=st_pts,
                            road_class=st.get("ref"),
                        ))

                # Parse alternatives if returned
                alt_results: List[ProviderRouteResult] = []
                for alt in routes_data[1:]:
                    alt_coords = alt.get("geometry", {}).get("coordinates", [])
                    alt_pts = [(float(pt[1]), float(pt[0])) for pt in alt_coords]
                    alt_results.append(ProviderRouteResult(
                        provider_name=self.provider_name,
                        distance_m=float(alt.get("distance", 0.0)),
                        duration_s=float(alt.get("duration", 0.0)),
                        geometry=alt_pts,
                        provenance=DataProvenance(
                            status=DataStatus.ESTIMATED,
                            source_name="OSRM Route Engine Alternative",
                            source_type=SourceType.STATISTICAL_INFERENCE,
                            source_reference=url,
                            notes="Algorithmic shortest-path calculation over OpenStreetMap road network; not physical telemetry.",
                            observed_at=datetime.now(timezone.utc),
                        ),
                    ))

                return ProviderRouteResult(
                    provider_name=self.provider_name,
                    distance_m=float(primary_route.get("distance", 0.0)),
                    duration_s=float(primary_route.get("duration", 0.0)),
                    geometry=lat_lng_geom,
                    steps=steps,
                    alternatives=alt_results,
                    raw_metadata=data,
                    provenance=DataProvenance(
                        status=DataStatus.ESTIMATED,
                        source_name="OSRM Route Engine",
                        source_type=SourceType.STATISTICAL_INFERENCE,
                        source_reference=url,
                        notes="Algorithmic shortest-path calculation over OpenStreetMap road network; not physical telemetry.",
                        observed_at=datetime.now(timezone.utc),
                    ),
                )
        except RoutingProviderError:
            raise
        except Exception as e:
            raise RoutingProviderError("OSRM", f"HTTP query failed: {e}")
