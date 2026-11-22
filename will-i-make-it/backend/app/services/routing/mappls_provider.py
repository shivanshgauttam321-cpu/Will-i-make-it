"""
Mappls (MapmyIndia) Routing Provider
====================================
Primary India-focused routing engine integration.
Handles OAuth2 token exchange and Advanced Direction API requests.

Engineering Rules Compliance:
- If credentials are not configured, is_available() explicitly returns False.
- Never fabricates fake routes if credentials or access are missing.
"""
from __future__ import annotations

import os
import json
import urllib.request
import urllib.parse
from datetime import datetime, timezone
from typing import Tuple, Optional, Dict, Any, List

from app.domain.provenance import DataProvenance, DataStatus, SourceType
from app.services.routing.base import (
    RoutingProvider,
    ProviderRouteResult,
    ProviderStep,
    RoutingProviderError,
)


class MapplsRoutingProvider(RoutingProvider):
    """
    Routing provider client for Mappls (MapmyIndia) Advanced Direction API.
    Supports driving profiles, alternatives, turn-by-turn steps, and toll/ferry flags.
    """

    OAUTH_URL = "https://outpost.mappls.com/api/security/oauth/token"
    DIRECTIONS_BASE = "https://apis.mappls.com/advancedmaps/v1"

    def __init__(
        self,
        client_id: Optional[str] = None,
        client_secret: Optional[str] = None,
        rest_api_key: Optional[str] = None,
        timeout_seconds: float = 8.0,
    ):
        self.client_id = client_id or os.environ.get("MAPPLS_CLIENT_ID", "").strip()
        self.client_secret = client_secret or os.environ.get("MAPPLS_CLIENT_SECRET", "").strip()
        self.rest_api_key = rest_api_key or os.environ.get("MAPPLS_REST_API_KEY", "").strip()
        self.timeout_seconds = timeout_seconds
        self._access_token: Optional[str] = None
        self._token_expires_at: Optional[float] = None

    @property
    def provider_name(self) -> str:
        return "Mappls (MapmyIndia)"

    def is_available(self) -> bool:
        """True only if valid credentials are present in configuration/environment."""
        return bool(self.rest_api_key or (self.client_id and self.client_secret))

    def _get_access_token(self) -> str:
        """Obtain OAuth2 bearer token if using Client ID / Client Secret credentials."""
        if self._access_token and self._token_expires_at and (datetime.now(timezone.utc).timestamp() < self._token_expires_at - 60):
            return self._access_token

        data = urllib.parse.urlencode({
            "grant_type": "client_credentials",
            "client_id": self.client_id,
            "client_secret": self.client_secret,
        }).encode("utf-8")

        req = urllib.request.Request(self.OAUTH_URL, data=data, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=self.timeout_seconds) as resp:
                payload = json.loads(resp.read().decode())
                self._access_token = payload.get("access_token")
                expires_in = payload.get("expires_in", 3600)
                self._token_expires_at = datetime.now(timezone.utc).timestamp() + expires_in
                return self._access_token
        except Exception as e:
            raise RoutingProviderError("Mappls", f"OAuth authentication failed: {e}")

    def get_route(
        self,
        origin: Tuple[float, float],
        destination: Tuple[float, float],
        options: Optional[Dict[str, Any]] = None,
    ) -> ProviderRouteResult:
        if not self.is_available():
            raise RoutingProviderError(
                "Mappls",
                "Mappls API credentials (MAPPLS_CLIENT_ID/MAPPLS_CLIENT_SECRET or MAPPLS_REST_API_KEY) are not configured."
            )

        olat, olng = origin
        dlat, dlng = destination
        opts = options or {}
        alternatives = "true" if opts.get("alternatives", False) else "false"

        # Coordinates formatted as lng,lat;lng,lat per Mappls REST API convention
        coords = f"{olng},{olat};{dlng},{dlat}"

        if self.rest_api_key:
            url = f"{self.DIRECTIONS_BASE}/{self.rest_api_key}/route_adv/driving/{coords}?overview=full&geometries=geojson&steps=true&alternatives={alternatives}"
            headers = {"User-Agent": "WillIMakeIt-EV/1.0"}
        else:
            token = self._get_access_token()
            url = f"{self.DIRECTIONS_BASE}/route_adv/driving/{coords}?overview=full&geometries=geojson&steps=true&alternatives={alternatives}"
            headers = {
                "User-Agent": "WillIMakeIt-EV/1.0",
                "Authorization": f"Bearer {token}",
            }

        req = urllib.request.Request(url, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=self.timeout_seconds) as resp:
                body = json.loads(resp.read().decode())
                routes = body.get("routes", [])
                if not routes:
                    raise RoutingProviderError("Mappls", "No driving routes found between specified coordinates.")

                primary = routes[0]
                geometry_geojson = primary.get("geometry", {}).get("coordinates", [])
                # GeoJSON coordinates are [lng, lat]; convert to [(lat, lng)]
                lat_lng_geom = [(float(pt[1]), float(pt[0])) for pt in geometry_geojson]

                steps: List[ProviderStep] = []
                for leg in primary.get("legs", []):
                    for st in leg.get("steps", []):
                        st_geom = st.get("geometry", {}).get("coordinates", [])
                        st_pts = [(float(p[1]), float(p[0])) for p in st_geom] if st_geom else None
                        st_start = st_pts[0] if st_pts else (olat, olng)
                        st_end = st_pts[-1] if st_pts else (dlat, dlng)
                        steps.append(ProviderStep(
                            name=st.get("name"),
                            instruction=st.get("maneuver", {}).get("instruction"),
                            distance_m=float(st.get("distance", 0.0)),
                            duration_s=float(st.get("duration", 0.0)),
                            start_coordinate=st_start,
                            end_coordinate=st_end,
                            geometry=st_pts,
                            road_class=st.get("class"),
                            surface=st.get("surface"),
                        ))

                return ProviderRouteResult(
                    provider_name=self.provider_name,
                    provider_route_id=body.get("uuid"),
                    distance_m=float(primary.get("distance", 0.0)),
                    duration_s=float(primary.get("duration", 0.0)),
                    geometry=lat_lng_geom,
                    steps=steps,
                    raw_metadata=body,
                    provenance=DataProvenance(
                        status=DataStatus.ESTIMATED,
                        source_name="Mappls Directions Engine",
                        source_type=SourceType.STATISTICAL_INFERENCE,
                        source_reference=url,
                        notes="Algorithmic route graph calculation over MapmyIndia road network; not physical telemetry.",
                        observed_at=datetime.now(timezone.utc),
                    ),
                )
        except RoutingProviderError:
            raise
        except Exception as e:
            raise RoutingProviderError("Mappls", f"Network or API query error: {e}")
