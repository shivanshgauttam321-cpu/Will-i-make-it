"""
Open-Meteo DEM Elevation Provider
=================================
Fetches real topographical elevations using Open-Meteo's Copernicus DEM 90m endpoint.
Batches requests up to 100 points, applies rate-limit backoff, and caches point elevations.
For large coordinate sequences (>100 points), samples anchor points to respect external API
rate limits and linearly interpolates intermediate points without fabricating synthetic topography.
"""
from __future__ import annotations

import logging
import time
from typing import List, Tuple, Optional
import httpx

from app.domain.provenance import DataProvenance, DataStatus, SourceType
from app.services.elevation.base import ElevationProvider, ElevationResult
from app.services.cache import SimpleTTLCache

logger = logging.getLogger(__name__)

OPEN_METEO_ELEVATION_URL = "https://api.open-meteo.com/v1/elevation"
DEFAULT_BATCH_SIZE = 100


class OpenMeteoElevationProvider(ElevationProvider):
    """Elevation provider querying Copernicus DEM 90m via Open-Meteo."""

    def __init__(
        self,
        base_url: str = OPEN_METEO_ELEVATION_URL,
        timeout_seconds: float = 6.0,
        cache: Optional[SimpleTTLCache] = None,
        batch_size: int = DEFAULT_BATCH_SIZE,
    ):
        self._base_url = base_url
        self._timeout = timeout_seconds
        self._cache = cache if cache is not None else SimpleTTLCache(default_ttl_seconds=86400.0)
        self._batch_size = min(100, batch_size)
        self._rate_limited_until: float = 0.0

    @property
    def provider_name(self) -> str:
        return "Open-Meteo Copernicus DEM 90m"

    def is_available(self) -> bool:
        return bool(self._base_url)

    def get_elevations(
        self,
        coordinates: List[Tuple[float, float]],
        cumulative_distances_m: Optional[List[float]] = None,
    ) -> ElevationResult:
        """
        Query elevations in meters for coordinates along a route.
        
        Sampling Policy:
        - When total points <= batch_size (100): all coordinates are directly queried from DEM.
        - When total points > batch_size (100): anchor coordinates are selected at uniform
          intervals along cumulative route distance (not coordinate array index).
        - Intermediate points are interpolated based strictly on path distance fraction.
        - Direct queries and interpolated values are tracked and returned separately.
        - Resolution is recorded as 90.0m (Copernicus DEM 90m grid).
        """
        n_coords = len(coordinates)
        if n_coords == 0:
            return ElevationResult(
                elevations=[],
                raw_elevations=[],
                queried_indices=[],
                interpolated_indices=[],
                provider_name=self.provider_name,
                resolution_m=90.0,
                provenance=DataProvenance(
                    source_name=self.provider_name,
                    source_type=SourceType.STATISTICAL_INFERENCE,
                    status=DataStatus.UNKNOWN,
                    notes="No coordinates provided for elevation lookup.",
                ),
            )

        # 1. Ensure cumulative distances along path are available
        cum_dists = cumulative_distances_m
        if not cum_dists or len(cum_dists) != n_coords:
            # Fallback calculate great-circle distances
            cum_dists = [0.0]
            for i in range(1, n_coords):
                # Haversine distance
                from app.services.geometry.processor import haversine_distance_m
                d = haversine_distance_m(coordinates[i - 1], coordinates[i])
                cum_dists.append(cum_dists[-1] + d)

        results: List[Optional[float]] = [None] * n_coords
        queried_indices: List[int] = []
        interpolated_indices: List[int] = []

        # 2. Check cache for all coordinates
        uncached_indices: List[int] = []
        for idx, (lat, lng) in enumerate(coordinates):
            cache_key = f"elev:{lat:.5f},{lng:.5f}"
            cached_val = self._cache.get(cache_key)
            if cached_val is not None:
                results[idx] = cached_val
                queried_indices.append(idx)
            else:
                uncached_indices.append(idx)

        if not uncached_indices:
            return self._build_result(results, results, queried_indices, [])

        # 3. Check if currently rate-limited
        if time.time() < self._rate_limited_until:
            logger.warning("Open-Meteo elevation currently rate-limited; skipping external query.")
            return self._build_result(results, results, queried_indices, [])

        # 4. If uncached indices <= batch_size, fetch all directly
        if len(uncached_indices) <= self._batch_size:
            chunk_coords = [coordinates[i] for i in uncached_indices]
            chunk_elevs = self._fetch_batch(chunk_coords)
            for chunk_pos, elev in enumerate(chunk_elevs):
                orig_idx = uncached_indices[chunk_pos]
                results[orig_idx] = elev
                if elev is not None:
                    lat, lng = coordinates[orig_idx]
                    self._cache.set(f"elev:{lat:.5f},{lng:.5f}", elev)
                    queried_indices.append(orig_idx)
            return self._build_result(results, results, queried_indices, [])

        # 5. If uncached indices > batch_size, select anchors spaced along CUMULATIVE PATH DISTANCE
        total_dist_m = cum_dists[-1]
        num_anchors = min(self._batch_size, len(uncached_indices))

        # Always include first and last point
        anchor_indices: List[int] = [0]
        if total_dist_m > 0 and num_anchors > 2:
            step_dist_m = total_dist_m / (num_anchors - 1)
            for a_idx in range(1, num_anchors - 1):
                target_dist = a_idx * step_dist_m
                # Find coordinate with cumulative distance closest to target_dist
                best_i = min(
                    range(n_coords),
                    key=lambda idx: abs(cum_dists[idx] - target_dist),
                )
                if best_i not in anchor_indices:
                    anchor_indices.append(best_i)

        if (n_coords - 1) not in anchor_indices:
            anchor_indices.append(n_coords - 1)
        anchor_indices.sort()

        # Query anchor coordinates
        anchor_coords = [coordinates[i] for i in anchor_indices]
        anchor_elevs = self._fetch_batch(anchor_coords)

        for a_pos, elev in enumerate(anchor_elevs):
            orig_idx = anchor_indices[a_pos]
            results[orig_idx] = elev
            if elev is not None:
                lat, lng = coordinates[orig_idx]
                self._cache.set(f"elev:{lat:.5f},{lng:.5f}", elev)
                queried_indices.append(orig_idx)

        # 6. Interpolate between anchors using CUMULATIVE ROUTE DISTANCE fraction
        for i in range(len(anchor_indices) - 1):
            idx_start = anchor_indices[i]
            idx_end = anchor_indices[i + 1]
            h_start = results[idx_start]
            h_end = results[idx_end]

            d_start = cum_dists[idx_start]
            d_end = cum_dists[idx_end]
            dist_span = d_end - d_start

            if h_start is not None and h_end is not None and (idx_end - idx_start) > 1 and dist_span > 0:
                for mid_idx in range(idx_start + 1, idx_end):
                    if results[mid_idx] is None:
                        # Path-distance based interpolation fraction
                        frac = (cum_dists[mid_idx] - d_start) / dist_span
                        results[mid_idx] = round(h_start + frac * (h_end - h_start), 1)
                        interpolated_indices.append(mid_idx)

        return self._build_result(results, results, queried_indices, interpolated_indices)

    def _build_result(
        self,
        elevations: List[Optional[float]],
        raw_elevations: List[Optional[float]],
        queried_indices: List[int],
        interpolated_indices: List[int],
    ) -> ElevationResult:
        retrieved_count = sum(1 for e in elevations if e is not None)
        if retrieved_count == len(elevations) and len(elevations) > 0:
            overall_status = DataStatus.ESTIMATED
        elif retrieved_count > 0:
            overall_status = DataStatus.ESTIMATED
        else:
            overall_status = DataStatus.UNKNOWN

        return ElevationResult(
            elevations=elevations,
            raw_elevations=raw_elevations,
            queried_indices=sorted(list(set(queried_indices))),
            interpolated_indices=sorted(list(set(interpolated_indices))),
            provider_name=self.provider_name,
            resolution_m=90.0,
            provenance=DataProvenance(
                source_name=self.provider_name,
                source_type=SourceType.STATISTICAL_INFERENCE,
                status=overall_status,
                processing_method="Copernicus DEM 90m Spatial Sampling (90m grid resolution; sub-90m observations not claimed)",
                notes=f"Retrieved {len(queried_indices)} direct DEM points, {len(interpolated_indices)} path-interpolated points.",
            ),
        )

    def _fetch_batch(self, coords: List[Tuple[float, float]]) -> List[Optional[float]]:
        """Fetch elevation for a batch of up to 100 coordinates."""
        if not coords:
            return []

        lats_str = ",".join(f"{lat:.5f}" for lat, _ in coords)
        lngs_str = ",".join(f"{lng:.5f}" for _, lng in coords)

        params = {
            "latitude": lats_str,
            "longitude": lngs_str,
        }

        try:
            with httpx.Client(timeout=self._timeout) as client:
                resp = client.get(self._base_url, params=params)
                if resp.status_code == 200:
                    data = resp.json()
                    raw_elevs = data.get("elevation", [])
                    if isinstance(raw_elevs, list):
                        return [float(e) if e is not None else None for e in raw_elevs]
                elif resp.status_code == 429:
                    # Back off for 60 seconds
                    self._rate_limited_until = time.time() + 60.0
                    logger.warning("Open-Meteo elevation rate limited (429). Backing off for 60s.")
                else:
                    logger.warning(
                        f"Open-Meteo elevation query failed with status {resp.status_code}: {resp.text[:200]}"
                    )
        except Exception as e:
            logger.warning(f"Open-Meteo elevation query network error: {e}")

        return [None] * len(coords)
