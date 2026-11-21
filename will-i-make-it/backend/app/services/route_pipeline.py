"""
Route Ingestion & Topographical Enrichment Pipeline
===================================================
Orchestrates real-world route ingestion from external routing engines (Mappls, Valhalla, OSRM),
analytical geometry resampling, 250m physics-aligned segmentation, DEM elevation enrichment,
and corridor weather sampling.

Strictly preserves provenance: NEVER fabricates routes or elevations on external failures.
"""
from __future__ import annotations

import uuid
import json
import logging
from datetime import datetime, timezone
from typing import Tuple, List, Optional, Dict, Any

from app.domain.provenance import (
    DataValue, DataProvenance, DataStatus, SourceType, DataQuality
)
from app.domain.route import RouteDomain, RouteSegmentDomain
from app.domain.environment import WeatherDomain
from app.services.cache import SimpleTTLCache
from app.services.routing.base import RoutingProvider, ProviderRouteResult, RoutingProviderError
from app.services.routing.composite_provider import CompositeRoutingProvider
from app.services.geometry.processor import GeometryProcessor, AnalyticalGeometry, haversine_distance_m
from app.services.segmentation.segmenter import RouteSegmenter, SegmentSlice
from app.services.elevation.base import ElevationProvider, ElevationResult
from app.services.elevation.open_meteo import OpenMeteoElevationProvider
from app.services.elevation.processor import ElevationProcessor, ElevationProfileSummary
from app.services.weather.base import WeatherProvider
from app.services.weather.open_meteo import OpenMeteoWeatherProvider

logger = logging.getLogger(__name__)


class RouteEnrichmentPipeline:
    """End-to-end pipeline for ingesting, resampling, segmenting, and enriching road routes."""

    def __init__(
        self,
        routing_provider: Optional[RoutingProvider] = None,
        elevation_provider: Optional[ElevationProvider] = None,
        weather_provider: Optional[WeatherProvider] = None,
        cache: Optional[SimpleTTLCache] = None,
    ):
        self._cache = cache if cache is not None else SimpleTTLCache()
        self.routing_provider = (
            routing_provider if routing_provider is not None else CompositeRoutingProvider()
        )
        self.elevation_provider = (
            elevation_provider if elevation_provider is not None else OpenMeteoElevationProvider(cache=self._cache)
        )
        self.weather_provider = (
            weather_provider if weather_provider is not None else OpenMeteoWeatherProvider(cache=self._cache)
        )

    def enrich_route(
        self,
        origin: Tuple[float, float],
        destination: Tuple[float, float],
        origin_name: Optional[str] = None,
        dest_name: Optional[str] = None,
        fetch_elevation: bool = True,
        fetch_weather: bool = True,
        target_segment_length_m: float = 250.0,
        options: Optional[Dict[str, Any]] = None,
    ) -> RouteDomain:
        """
        Execute full route ingestion and topographical enrichment.
        
        Args:
            origin: (latitude, longitude) of starting point.
            destination: (latitude, longitude) of destination.
            origin_name: Optional label for origin.
            dest_name: Optional label for destination.
            fetch_elevation: Whether to enrich with DEM elevation data.
            fetch_weather: Whether to enrich with corridor weather data.
            target_segment_length_m: Desired segment length (default 250m).
            options: Optional routing engine parameters (alternatives, avoidances, etc.).
            
        Returns:
            Fully enriched RouteDomain object.
            
        Raises:
            RoutingProviderError: When route cannot be retrieved from any configured provider.
        """
        # Check in-memory route cache first with complete options identity
        opts_canonical = json.dumps(options or {}, sort_keys=True)
        cache_key = (
            f"route:{origin[0]:.4f},{origin[1]:.4f}->{destination[0]:.4f},{destination[1]:.4f}:"
            f"{fetch_elevation}:{fetch_weather}:{target_segment_length_m}:{opts_canonical}"
        )
        cached_route = self._cache.get(cache_key)
        if cached_route is not None:
            return cached_route

        # 1. Ingest Route Geometry from Routing Provider
        logger.info(f"Ingesting route from {origin} to {destination}")
        provider_result: ProviderRouteResult = self.routing_provider.get_route(
            origin, destination, options=options
        )

        if not provider_result.geometry or len(provider_result.geometry) < 2:
            raise RoutingProviderError("Routing provider returned insufficient geometry points.")

        # 2. Process & Resample Geometry for Analytical Uniformity
        analytical_geom: AnalyticalGeometry = GeometryProcessor.process_route_geometry(
            provider_result.geometry,
            target_sample_interval_m=100.0,
        )

        # 3. Segment Route into Contiguous Physics Slices (~250m)
        segment_slices: List[SegmentSlice] = RouteSegmenter.segment_route(
            analytical_geom=analytical_geom,
            steps=provider_result.steps,
            target_length_m=target_segment_length_m,
        )

        # 4. Topographical DEM Elevation Enrichment
        smoothed_elevations: List[Optional[float]] = [None] * len(analytical_geom.analytical_points)
        profile_summary = ElevationProfileSummary()

        if fetch_elevation and self.elevation_provider and self.elevation_provider.is_available():
            try:
                try:
                    elev_result: ElevationResult = self.elevation_provider.get_elevations(
                        coordinates=analytical_geom.analytical_points,
                        cumulative_distances_m=analytical_geom.cumulative_distances_m,
                    )
                except TypeError:
                    elev_result = self.elevation_provider.get_elevations(
                        analytical_geom.analytical_points
                    )
                raw_elevs = elev_result.elevations
                # Filter DEM noise with median and moving-average filters
                med_filtered = ElevationProcessor.median_filter(raw_elevs, window_size=3)
                smoothed_elevations = ElevationProcessor.moving_average_filter(med_filtered, window_size=3)
            except Exception as e:
                logger.warning(f"Elevation enrichment failed: {e}")
                smoothed_elevations = [None] * len(analytical_geom.analytical_points)

        # 5. Meteorological Corridor Weather Enrichment
        weather_by_segment: List[Optional[WeatherDomain]] = [None] * len(segment_slices)
        if fetch_weather and self.weather_provider and self.weather_provider.is_available():
            try:
                weather_by_segment = self._sample_corridor_weather(segment_slices)
            except Exception as e:
                logger.warning(f"Weather enrichment failed: {e}")
                weather_by_segment = [None] * len(segment_slices)

        # 6. Assemble Segment Domains with Complete Provenance
        route_segments: List[RouteSegmentDomain] = []
        seg_elev_pairs: List[Tuple[Optional[float], Optional[float]]] = []

        now = datetime.now(timezone.utc)
        for i, s_slice in enumerate(segment_slices):
            h_start = smoothed_elevations[s_slice.start_index]
            h_end = smoothed_elevations[s_slice.end_index]
            seg_elev_pairs.append((h_start, h_end))

            grad_res = ElevationProcessor.compute_gradient_percent(
                start_elevation=h_start,
                end_elevation=h_end,
                path_distance_m=s_slice.length_m,
            )

            # Build provenance-attributed segment values
            seg_distance_km = round(s_slice.length_m / 1000.0, 3)
            if seg_distance_km <= 0:
                seg_distance_km = 0.001  # enforce strictly positive distance

            # Separate statutory speed limit from estimated driving speed
            speed_limit_dv = (
                DataValue.estimated(
                    value=s_slice.speed_limit_kmh,
                    unit="km/h",
                    source_name=f"{provider_result.provider_name} Speed Limit",
                    notes="Statutory speed limit from road provider; not actual driving speed.",
                )
                if s_slice.speed_limit_kmh is not None
                else None
            )

            # Gradient provenance: distinguish raw vs clamped vs unknown
            if grad_res.status == DataStatus.ESTIMATED:
                grad_dv = DataValue.estimated(
                    value=grad_res.gradient,
                    unit="%",
                    source_name="Copernicus DEM Delta",
                    processing_method="Topographical gradient formula",
                    notes=grad_res.warning,
                )
                raw_grad_dv = DataValue.estimated(
                    value=grad_res.raw_gradient,
                    unit="%",
                    source_name="Copernicus DEM Raw Delta",
                )
            else:
                grad_dv = DataValue.unknown(
                    unit="%",
                    notes=grad_res.warning or "Elevation unavailable; gradient is unverified",
                )
                raw_grad_dv = None

            segment_domain = RouteSegmentDomain(
                segment_id=f"seg_{i:04d}",
                sequence_order=s_slice.sequence_order,
                name=s_slice.road_name,
                distance=DataValue.estimated(
                    value=seg_distance_km,
                    unit="km",
                    source_name=provider_result.provider_name,
                ),
                speed=DataValue(
                    value=s_slice.speed_kmh,
                    unit="km/h",
                    provenance=DataProvenance(
                        status=s_slice.speed_status,
                        source_name=f"{provider_result.provider_name} Speed Estimation",
                        source_type=provider_result.provenance.source_type,
                        processing_method=s_slice.speed_method,
                    ),
                ),
                speed_limit=speed_limit_dv,
                elevation_start=(
                    DataValue.estimated(
                        value=h_start,
                        unit="m",
                        source_name=self.elevation_provider.provider_name if self.elevation_provider else "DEM",
                    )
                    if h_start is not None
                    else DataValue.unknown(unit="m")
                ),
                elevation_end=(
                    DataValue.estimated(
                        value=h_end,
                        unit="m",
                        source_name=self.elevation_provider.provider_name if self.elevation_provider else "DEM",
                    )
                    if h_end is not None
                    else DataValue.unknown(unit="m")
                ),
                gradient=grad_dv,
                raw_gradient=raw_grad_dv,
                gradient_is_clamped=grad_res.is_clamped,
                road_type=DataValue.estimated(
                    value=s_slice.road_type,
                    unit="",
                    source_name=provider_result.provider_name,
                ),
                raw_road_class=s_slice.raw_road_class,
                road_condition=DataValue.estimated(
                    value=s_slice.road_condition,
                    unit="",
                    source_name="Model Baseline",
                ),
                traffic=None,
                weather=weather_by_segment[i] if i < len(weather_by_segment) else None,
                energy_prediction_kwh=None,
                geometry=s_slice.points,
            )
            route_segments.append(segment_domain)

        # 7. Compute Profile Summary Statistics
        if fetch_elevation:
            profile_summary = ElevationProcessor.compute_profile_summary(seg_elev_pairs)

        # 8. Build Normalized RouteDomain
        total_dist_km = round(analytical_geom.total_distance_m / 1000.0, 2)
        total_duration_min = round(provider_result.duration_s / 60.0, 1)

        route_id = str(uuid.uuid4())[:12]
        route_domain = RouteDomain(
            route_id=route_id,
            origin_coordinates=origin,
            destination_coordinates=destination,
            origin_name=origin_name,
            dest_name=dest_name,
            distance=DataValue.estimated(
                value=total_dist_km,
                unit="km",
                source_name=provider_result.provider_name,
            ),
            duration=DataValue.estimated(
                value=total_duration_min,
                unit="min",
                source_name=provider_result.provider_name,
            ),
            route_provider=provider_result.provider_name,
            route_provider_reference=provider_result.provider_route_id,
            retrieval_timestamp=now,
            segments=route_segments,
            geometry=analytical_geom.display_points,
            elevation_gain_m=profile_summary.total_gain_m if profile_summary.has_elevation_data else None,
            elevation_loss_m=profile_summary.total_loss_m if profile_summary.has_elevation_data else None,
            alternatives=[],
            provenance=provider_result.provenance,
        )

        self._cache.set(cache_key, route_domain, ttl_seconds=3600.0)
        return route_domain

    def _sample_corridor_weather(
        self,
        segment_slices: List[SegmentSlice],
        spatial_sample_interval_m: float = 75000.0,  # ~75 km
    ) -> List[Optional[WeatherDomain]]:
        """Sample weather at key intervals along the corridor and map to slices."""
        if not segment_slices or not self.weather_provider:
            return [None] * len(segment_slices)

        total_length_m = segment_slices[-1].end_distance_m
        num_samples = max(1, int(total_length_m / spatial_sample_interval_m) + 1)

        # Pick sample points along the route
        sampled_weather_points: List[Tuple[float, WeatherDomain]] = []  # (route_dist_m, WeatherDomain)

        sample_distances = [
            (i * (total_length_m / max(1, num_samples - 1))) for i in range(num_samples)
        ]

        for target_d in sample_distances:
            # Find closest segment slice for coordinate
            closest_slice = min(
                segment_slices,
                key=lambda s: abs(s.start_distance_m - target_d),
            )
            lat, lng = closest_slice.start_coord
            weather_data = self.weather_provider.get_weather(lat, lng)
            if weather_data:
                sampled_weather_points.append((target_d, weather_data))

        if not sampled_weather_points:
            return [None] * len(segment_slices)

        # Assign closest sampled weather to each segment slice
        assigned: List[Optional[WeatherDomain]] = []
        for s in segment_slices:
            mid_d = (s.start_distance_m + s.end_distance_m) / 2.0
            best_weather = min(
                sampled_weather_points,
                key=lambda item: abs(item[0] - mid_d),
            )[1]
            assigned.append(best_weather)

        return assigned
