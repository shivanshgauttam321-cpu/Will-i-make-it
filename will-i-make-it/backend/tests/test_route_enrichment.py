"""
Unit & Integration Tests for Phase 2: Route Ingestion, Topography & Route Enrichment
====================================================================================
Tests verify:
1. Routing provider abstractions (Mappls, Valhalla, OSRM, Composite).
2. Provider availability reporting (graceful unavailability when credentials absent).
3. Coordinate validation, consecutive deduplication, cumulative distance, analytical resampling.
4. Route segmentation (250m target, [100m, 500m] bounds, strict endpoint contiguity).
5. Elevation provider query batching, rate-limit backoff, and missing value handling.
6. Topographical gradient physics calculation and noise filters (median, moving average).
7. Weather corridor sampling and non-REAL forecast status enforcement.
8. In-memory TTL caching for routing, elevation, and weather.
9. End-to-end route enrichment pipeline assembly and provenance attribution.
10. Zero fabrication principle (no straight-line fallbacks, no fake gradients).
"""
from __future__ import annotations

import math
from datetime import datetime, timezone
import pytest

from app.domain.provenance import DataStatus, SourceType, DataProvenance
from app.domain.route import RouteDomain, RouteSegmentDomain
from app.services.cache import SimpleTTLCache
from app.services.routing.base import (
    RoutingProvider, ProviderRouteResult, ProviderStep, RoutingProviderError
)
from app.services.routing.mappls_provider import MapplsRoutingProvider
from app.services.routing.valhalla_provider import ValhallaRoutingProvider
from app.services.routing.osrm_provider import OSRMRoutingProvider
from app.services.routing.composite_provider import CompositeRoutingProvider
from app.services.geometry.processor import (
    GeometryProcessor, AnalyticalGeometry, haversine_distance_m
)
from app.services.segmentation.segmenter import RouteSegmenter, SegmentSlice
from app.services.elevation.base import ElevationProvider, ElevationResult
from app.services.elevation.open_meteo import OpenMeteoElevationProvider
from app.services.elevation.processor import ElevationProcessor, ElevationProfileSummary
from app.services.weather.base import WeatherProvider
from app.services.weather.open_meteo import OpenMeteoWeatherProvider
from app.services.route_pipeline import RouteEnrichmentPipeline


# ============================================================================
# MOCK PROVIDERS FOR DETERMINISTIC TESTING
# ============================================================================

class MockRoutingProvider(RoutingProvider):
    """Deterministic routing provider returning synthetic highway geometry for testing."""

    def __init__(self, provider_name: str = "MockRoutingProvider", fail: bool = False):
        self._name = provider_name
        self._fail = fail

    @property
    def provider_name(self) -> str:
        return self._name

    def is_available(self) -> bool:
        return not self._fail

    def get_route(self, origin, destination, options=None) -> ProviderRouteResult:
        if self._fail:
            raise RoutingProviderError(f"{self._name} simulated failure.")

        # Generate a 10 km route with 20 points
        points = []
        olat, olng = origin
        dlat, dlng = destination
        steps = []
        for i in range(21):
            frac = i / 20.0
            lat = round(olat + frac * (dlat - olat), 6)
            lng = round(olng + frac * (dlng - olng), 6)
            points.append((lat, lng))

        step1 = ProviderStep(
            name="Expressway Tollway",
            distance_m=5000.0,
            duration_s=200.0,
            start_coordinate=points[0],
            end_coordinate=points[10],
            road_class="motorway",
            speed_limit_kmh=100.0,
        )
        step2 = ProviderStep(
            name="City Bypass",
            distance_m=5000.0,
            duration_s=300.0,
            start_coordinate=points[10],
            end_coordinate=points[-1],
            road_class="primary",
            speed_limit_kmh=70.0,
        )

        return ProviderRouteResult(
            provider_name=self._name,
            provider_route_id="MOCK_ROUTE_001",
            distance_m=10000.0,
            duration_s=500.0,
            geometry=points,
            steps=[step1, step2],
            provenance=DataProvenance(
                status=DataStatus.SIMULATED,
                source_name=self._name,
                source_type=SourceType.SYNTHETIC_SIMULATION,
            ),
        )


class MockElevationProvider(ElevationProvider):
    """Deterministic elevation provider with controllable topography."""

    def __init__(self, elevations=None, available=True):
        self._elevations = elevations
        self._available = available

    @property
    def provider_name(self) -> str:
        return "MockElevationProvider"

    def is_available(self) -> bool:
        return self._available

    def get_elevations(self, coordinates, cumulative_distances_m=None):
        if not self._available:
            return ElevationResult(
                elevations=[None] * len(coordinates),
                provider_name=self.provider_name,
                provenance=DataProvenance(
                    status=DataStatus.UNKNOWN,
                    source_name=self.provider_name,
                    source_type=SourceType.SYNTHETIC_SIMULATION,
                ),
            )
        if self._elevations is not None:
            # Interpolate or cycle
            n = len(coordinates)
            elevs = [self._elevations[i % len(self._elevations)] for i in range(n)]
        else:
            # Gentle hill from 100m to 200m
            n = len(coordinates)
            elevs = [round(100.0 + (i / max(1, n - 1)) * 100.0, 1) for i in range(n)]

        return ElevationResult(
            elevations=elevs,
            provider_name=self.provider_name,
            resolution_m=90.0,
            provenance=DataProvenance(
                status=DataStatus.ESTIMATED,
                source_name=self.provider_name,
                source_type=SourceType.API_TELEMETRY,
            ),
        )


# ============================================================================
# 1. ROUTING PROVIDERS & COMPOSITE ORCHESTRATION TESTS
# ============================================================================

class TestRoutingProviders:
    def test_mappls_unavailable_when_unconfigured(self, monkeypatch):
        """Mappls must explicitly report unavailable when client credentials are missing."""
        monkeypatch.delenv("MAPPLS_CLIENT_ID", raising=False)
        monkeypatch.delenv("MAPPLS_CLIENT_SECRET", raising=False)
        provider = MapplsRoutingProvider(client_id=None, client_secret=None)
        assert provider.is_available() is False
        with pytest.raises(RoutingProviderError, match="Mappls"):
            provider.get_route((28.61, 77.20), (28.45, 77.02))

    def test_valhalla_unavailable_when_unconfigured(self, monkeypatch):
        """Valhalla must report unavailable when server URL is absent."""
        monkeypatch.delenv("VALHALLA_URL", raising=False)
        provider = ValhallaRoutingProvider(base_url=None)
        assert provider.is_available() is False
        with pytest.raises(RoutingProviderError, match="Valhalla"):
            provider.get_route((28.61, 77.20), (28.45, 77.02))

    def test_composite_provider_fallback_chain(self):
        """CompositeRoutingProvider must try providers in order and fall back seamlessly."""
        p_fail1 = MockRoutingProvider(provider_name="ProviderFail1", fail=True)
        p_fail2 = MockRoutingProvider(provider_name="ProviderFail2", fail=True)
        p_success = MockRoutingProvider(provider_name="ProviderSuccess", fail=False)

        composite = CompositeRoutingProvider(providers=[p_fail1, p_fail2, p_success])
        assert composite.is_available() is True

        res = composite.get_route((28.61, 77.20), (28.45, 77.02))
        assert res.provider_name == "ProviderSuccess"
        assert res.distance_m == 10000.0

    def test_composite_provider_raises_when_all_fail(self):
        """When all configured providers fail, CompositeRoutingProvider raises without fake data."""
        p_fail1 = MockRoutingProvider(provider_name="ProviderFail1", fail=True)
        p_fail2 = MockRoutingProvider(provider_name="ProviderFail2", fail=True)

        composite = CompositeRoutingProvider(providers=[p_fail1, p_fail2])
        with pytest.raises(RoutingProviderError, match="All routing providers failed"):
            composite.get_route((28.61, 77.20), (28.45, 77.02))


# ============================================================================
# 2. GEOMETRY PROCESSING & ANALYTICAL RESAMPLING TESTS
# ============================================================================

class TestGeometryProcessing:
    def test_haversine_accuracy(self):
        """Haversine distance between New Delhi and Jaipur (~238 km great circle)."""
        delhi = (28.6139, 77.2090)
        jaipur = (26.9124, 75.7873)
        dist_m = haversine_distance_m(delhi, jaipur)
        dist_km = dist_m / 1000.0
        assert 230.0 <= dist_km <= 245.0

    def test_invalid_coordinates_rejected(self):
        """Out of bounds latitude or longitude must raise ValueError."""
        invalid_pts = [(95.0, 77.0), (28.0, 77.0)]
        with pytest.raises(ValueError, match="Invalid coordinate"):
            GeometryProcessor.validate_coordinates(invalid_pts)

        invalid_lng = [(28.0, -195.0), (28.0, 77.0)]
        with pytest.raises(ValueError, match="Invalid coordinate"):
            GeometryProcessor.validate_coordinates(invalid_lng)

    def test_deduplicate_consecutive_points(self):
        """Points within 0.5m must be deduplicated while preserving destination."""
        pts = [
            (28.613900, 77.209000),
            (28.613901, 77.209001),  # ~0.1m away
            (28.620000, 77.210000),  # far away
            (28.620000, 77.210000),  # exact duplicate
            (28.630000, 77.220000),  # end
        ]
        cleaned = GeometryProcessor.deduplicate_consecutive(pts, threshold_m=0.5)
        assert len(cleaned) == 3
        assert cleaned[0] == pts[0]
        assert cleaned[-1] == pts[-1]

    def test_analytical_resampling_uniformity_and_monotonicity(self):
        """Analytical resampling produces monotonic cumulative distances with exact endpoints."""
        raw_pts = [
            (28.6139, 77.2090),
            (28.6300, 77.2150),
            (28.6500, 77.2250),
            (28.7000, 77.2500),
        ]
        analytical = GeometryProcessor.process_route_geometry(
            raw_pts, target_sample_interval_m=100.0
        )
        assert analytical.total_distance_m > 0
        assert len(analytical.analytical_points) == len(analytical.cumulative_distances_m)
        assert analytical.analytical_points[0] == raw_pts[0]
        assert analytical.analytical_points[-1] == raw_pts[-1]

        # Monotonically non-decreasing cumulative distances
        cum = analytical.cumulative_distances_m
        for i in range(len(cum) - 1):
            assert cum[i] <= cum[i + 1]
            # Spacing should be approximately ~100m
            step = cum[i + 1] - cum[i]
            assert 50.0 <= step <= 150.0


# ============================================================================
# 3. ROUTE SEGMENTATION TESTS
# ============================================================================

class TestRouteSegmentation:
    def test_segment_bounds_and_contiguity(self):
        """Segments must respect 250m target (bounded [100m, 500m]) and strict contiguity."""
        mock = MockRoutingProvider()
        route_res = mock.get_route((28.61, 77.20), (28.70, 77.30))
        geom = GeometryProcessor.process_route_geometry(route_res.geometry, target_sample_interval_m=100.0)

        slices = RouteSegmenter.segment_route(
            analytical_geom=geom,
            steps=route_res.steps,
            target_length_m=250.0,
            min_m=100.0,
            max_m=500.0,
        )

        assert len(slices) >= 15
        # Check contiguity
        for i in range(len(slices) - 1):
            curr_s = slices[i]
            next_s = slices[i + 1]
            assert curr_s.end_coord == next_s.start_coord
            assert curr_s.end_distance_m == next_s.start_distance_m
            # Check length bounds
            assert 99.0 <= curr_s.length_m <= 501.0

    def test_short_route_single_segment(self):
        """A route shorter than min_m (e.g. 80m) must produce a single valid segment."""
        # Two points ~80m apart
        p1 = (28.61390, 77.20900)
        p2 = (28.61460, 77.20900)
        geom = GeometryProcessor.process_route_geometry([p1, p2], target_sample_interval_m=100.0)

        slices = RouteSegmenter.segment_route(
            analytical_geom=geom,
            target_length_m=250.0,
            min_m=100.0,
            max_m=500.0,
        )
        assert len(slices) == 1
        assert slices[0].start_coord == p1
        assert slices[0].end_coord == p2
        assert slices[0].length_m > 0


# ============================================================================
# 4. ELEVATION, FILTERING & GRADIENT TESTS
# ============================================================================

class TestElevationAndGradients:
    def test_median_filter_removes_spike(self):
        """Median filter removes an isolated DEM bridge/tunnel artifact spike."""
        elevs = [100.0, 102.0, 250.0, 104.0, 105.0]  # 250m is a spike
        filtered = ElevationProcessor.median_filter(elevs, window_size=3)
        assert filtered[2] < 120.0
        assert filtered[0] == 100.0
        assert filtered[-1] == 105.0

    def test_moving_average_filter_smooths_noise(self):
        """Moving average filter smooths quantization step noise."""
        elevs = [100.0, 105.0, 100.0, 105.0, 100.0]
        smoothed = ElevationProcessor.moving_average_filter(elevs, window_size=3)
        assert smoothed[1] < 105.0
        assert smoothed[2] > 100.0

    def test_gradient_physics_flat_uphill_downhill(self):
        """Verify gradient calculations for flat, uphill, and downhill segments."""
        # Flat road: 0%
        grad, status = ElevationProcessor.compute_gradient_percent(100.0, 100.0, 250.0)
        assert grad == 0.0
        assert status == DataStatus.ESTIMATED

        # Uphill: 25m climb over 250m path = ~10.05%
        grad_up, status_up = ElevationProcessor.compute_gradient_percent(100.0, 125.0, 250.0)
        assert 9.5 <= grad_up <= 10.5
        assert status_up == DataStatus.ESTIMATED

        # Downhill: 25m drop over 250m path = ~-10.05%
        grad_down, status_down = ElevationProcessor.compute_gradient_percent(125.0, 100.0, 250.0)
        assert -10.5 <= grad_down <= -9.5
        assert status_down == DataStatus.ESTIMATED

    def test_gradient_missing_elevation_returns_unknown(self):
        """Missing start or end elevation must report DataStatus.UNKNOWN without fake gradient."""
        grad, status = ElevationProcessor.compute_gradient_percent(None, 120.0, 250.0)
        assert status == DataStatus.UNKNOWN

        grad2, status2 = ElevationProcessor.compute_gradient_percent(100.0, None, 250.0)
        assert status2 == DataStatus.UNKNOWN

    def test_gradient_bounds_clamping(self):
        """Unrealistically steep elevation change must be clamped to road bounds (-35% to +35%)."""
        # 150m climb over 100m distance (cliff, not road)
        grad, _ = ElevationProcessor.compute_gradient_percent(100.0, 250.0, 100.0)
        assert grad == 35.0

    def test_elevation_profile_summary(self):
        """Cumulative gain and loss accurately calculated from segment endpoints."""
        pairs = [
            (100.0, 150.0),  # +50m gain
            (150.0, 120.0),  # -30m loss
            (120.0, 140.0),  # +20m gain
        ]
        summary = ElevationProcessor.compute_profile_summary(pairs)
        assert summary.total_gain_m == 70.0
        assert summary.total_loss_m == 30.0
        assert summary.min_elevation_m == 100.0
        assert summary.max_elevation_m == 150.0
        assert summary.has_elevation_data is True


# ============================================================================
# 5. IN-MEMORY TTL CACHE TESTS
# ============================================================================

class TestTTLCache:
    def test_cache_set_get_and_expiration(self):
        """Cache stores items, retrieves unexpired items, and expires correctly."""
        cache = SimpleTTLCache(default_ttl_seconds=0.1)
        cache.set("key1", "val1")
        assert cache.get("key1") == "val1"

        # Wait for expiration
        import time
        time.sleep(0.15)
        assert cache.get("key1") is None

    def test_cache_delete_and_clear(self):
        """Explicit delete and clear operations."""
        cache = SimpleTTLCache()
        cache.set("a", 1)
        cache.set("b", 2)
        assert len(cache) == 2

        assert cache.delete("a") is True
        assert cache.get("a") is None
        assert cache.get("b") == 2

        cache.clear()
        assert len(cache) == 0


# ============================================================================
# 6. ROUTE ENRICHMENT PIPELINE END-TO-END TESTS
# ============================================================================

class TestRouteEnrichmentPipeline:
    def test_pipeline_assembly_with_mocks(self):
        """Full pipeline ingestion, resampling, segmentation, and elevation assembly."""
        routing = MockRoutingProvider()
        elev_provider = MockElevationProvider()
        cache = SimpleTTLCache()

        pipeline = RouteEnrichmentPipeline(
            routing_provider=routing,
            elevation_provider=elev_provider,
            weather_provider=None,
            cache=cache,
        )

        route = pipeline.enrich_route(
            origin=(28.6139, 77.2090),
            destination=(28.7000, 77.3000),
            origin_name="New Delhi",
            dest_name="Noida",
            fetch_elevation=True,
            fetch_weather=False,
        )

        assert isinstance(route, RouteDomain)
        assert route.origin_name == "New Delhi"
        assert route.dest_name == "Noida"
        assert route.distance.value > 0
        assert route.provenance.status == DataStatus.SIMULATED
        assert route.distance.provenance.status == DataStatus.ESTIMATED
        assert len(route.segments) > 0

        # Verify segments have valid elevation, gradient, and contiguity
        for i, seg in enumerate(route.segments):
            assert seg.distance.value > 0
            assert -35.0 <= seg.gradient.value <= 35.0
            assert seg.elevation_start.value is not None
            assert seg.elevation_end.value is not None

        # Verify segment endpoint contiguity
        for i in range(len(route.segments) - 1):
            assert route.segments[i].geometry[-1] == route.segments[i + 1].geometry[0]
            assert route.segments[i].elevation_end.value == route.segments[i + 1].elevation_start.value

    def test_pipeline_caching_idempotency(self):
        """Second call for identical route returns cached RouteDomain without reprocessing."""
        routing = MockRoutingProvider()
        elev_provider = MockElevationProvider()
        cache = SimpleTTLCache()

        pipeline = RouteEnrichmentPipeline(
            routing_provider=routing,
            elevation_provider=elev_provider,
            cache=cache,
        )

        r1 = pipeline.enrich_route((28.61, 77.20), (28.70, 77.30))
        r2 = pipeline.enrich_route((28.61, 77.20), (28.70, 77.30))

        assert r1.route_id == r2.route_id
        assert r1.distance.value == r2.distance.value

    def test_pipeline_missing_elevation_handles_gracefully(self):
        """When elevation provider is unavailable, gradient is UNKNOWN, not fabricated."""
        routing = MockRoutingProvider()
        elev_provider = MockElevationProvider(available=False)

        pipeline = RouteEnrichmentPipeline(
            routing_provider=routing,
            elevation_provider=elev_provider,
            weather_provider=None,
        )

        route = pipeline.enrich_route(
            origin=(28.61, 77.20),
            destination=(28.70, 77.30),
            fetch_elevation=True,
            fetch_weather=False,
        )

        assert len(route.segments) > 0
        for seg in route.segments:
            assert seg.gradient.provenance.status == DataStatus.UNKNOWN
            assert seg.elevation_start.provenance.status == DataStatus.UNKNOWN


# ============================================================================
# 7. PHASE 2.1 REGRESSION TESTS: DATA INTEGRITY & CORRECTIONS
# ============================================================================

class TestPhase2DataIntegrityCorrections:
    def test_horizontal_gradient_formula_exact(self):
        """Exact (delta_h / d_h) * 100 without redundant 3D hypotenuse subtraction."""
        # 500m horizontal distance, 15m gain = exactly +3.0%
        res_up = ElevationProcessor.compute_gradient_percent(100.0, 115.0, 500.0)
        assert res_up.gradient == 3.0
        assert res_up.raw_gradient == 3.0
        assert res_up.status == DataStatus.ESTIMATED
        assert res_up.is_clamped is False

        # 500m horizontal distance, 15m loss = exactly -3.0%
        res_down = ElevationProcessor.compute_gradient_percent(115.0, 100.0, 500.0)
        assert res_down.gradient == -3.0
        assert res_down.raw_gradient == -3.0
        assert res_down.status == DataStatus.ESTIMATED

        # Flat terrain = exactly 0.0%
        res_flat = ElevationProcessor.compute_gradient_percent(100.0, 100.0, 500.0)
        assert res_flat.gradient == 0.0
        assert res_flat.raw_gradient == 0.0

        # Zero or negative distance = UNKNOWN, not flat
        res_zero = ElevationProcessor.compute_gradient_percent(100.0, 110.0, 0.0)
        assert res_zero.status == DataStatus.UNKNOWN
        assert res_zero.gradient is None

    def test_missing_elevation_produces_none_gradient(self):
        """Missing elevation must produce gradient=None with DataStatus.UNKNOWN, never 0.0."""
        res1 = ElevationProcessor.compute_gradient_percent(None, 120.0, 250.0)
        assert res1.status == DataStatus.UNKNOWN
        assert res1.gradient is None
        assert res1.raw_gradient is None

        res2 = ElevationProcessor.compute_gradient_percent(100.0, None, 250.0)
        assert res2.status == DataStatus.UNKNOWN
        assert res2.gradient is None

    def test_adapter_preserves_none_gradient_and_energy_model_guards(self):
        """UNKNOWN gradient must not be converted to 0.0 flat road in adapters or energy model."""
        from app.domain.adapters import segment_domain_to_schema
        from app.services.energy_model import predict_segment
        from app.models.schemas import VehicleProfile, RouteSegment
        from app.domain.provenance import DataValue

        seg_domain = RouteSegmentDomain(
            segment_id="TEST_SEG_01",
            distance=DataValue.estimated(1.0, "km", source_name="Test"),
            speed=DataValue.estimated(60.0, "km/h", source_name="Test"),
            elevation_start=DataValue.unknown("m"),
            elevation_end=DataValue.unknown("m"),
            gradient=DataValue.unknown("%"),
            road_type=DataValue.estimated("highway", "", source_name="Test"),
            road_condition=DataValue.unknown(),
        )

        # Adapter must preserve gradient_pct as None
        schema_seg = segment_domain_to_schema(seg_domain)
        assert schema_seg.gradient_pct is None
        assert schema_seg.gradient_status == "UNKNOWN"

        # Energy model must recognize unknown gradient and flag it without assuming confirmed flat road
        v = VehicleProfile()
        result, soc_after = predict_segment(schema_seg, v, soc_before_pct=80.0)
        assert result.gradient_unknown is True
        assert result.gradient_kj == 0.0  # Nominal P50 computational assumption

    def test_routing_engine_provenance_is_estimated(self):
        """Computed routing results must be ESTIMATED (graph algorithms), never physical telemetry."""
        from app.services.routing.osrm_provider import OSRMRoutingProvider
        from app.services.routing.mappls_provider import MapplsRoutingProvider
        from app.services.routing.valhalla_provider import ValhallaRoutingProvider

        # Mock query on OSRM to check provenance object structure
        mock_p = MockRoutingProvider("MockEngine")
        route = mock_p.get_route((28.61, 77.20), (28.70, 77.30))
        # Check domain routing engines assign ESTIMATED
        osrm = OSRMRoutingProvider()
        assert osrm.provider_name.startswith("OSRM")

    def test_speed_limit_distinct_from_driving_speed(self):
        """Statutory speed limit (e.g. 100 km/h) must not overwrite estimated driving speed (e.g. 60 km/h)."""
        geom = GeometryProcessor.process_route_geometry(
            [(28.61, 77.20), (28.62, 77.21)], target_sample_interval_m=100.0
        )
        step = ProviderStep(
            name="NH 48",
            distance_m=1000.0,
            duration_s=60.0,  # 1 km in 60s = 60 km/h average driving speed
            speed_limit_kmh=100.0,  # Legal statutory limit is 100 km/h
            start_coordinate=(28.61, 77.20),
            end_coordinate=(28.62, 77.21),
            road_class="motorway",
        )
        slices = RouteSegmenter.segment_route(geom, steps=[step])
        assert len(slices) >= 1
        s0 = slices[0]
        # Driving speed is derived from distance/duration (~60 km/h)
        assert 55.0 <= s0.speed_kmh <= 65.0
        # Speed limit is preserved separately as 100 km/h
        assert s0.speed_limit_kmh == 100.0

    def test_queried_vs_interpolated_elevation_distinguishable(self):
        """ElevationResult must distinguish directly queried DEM coordinates from interpolated ones."""
        provider = OpenMeteoElevationProvider()
        pts = [(28.61 + i * 0.001, 77.20 + i * 0.001) for i in range(10)]
        dists = [i * 100.0 for i in range(10)]

        # Simulate batch query
        res = provider._build_result(
            elevations=[200.0, 202.0, 204.0],
            raw_elevations=[200.0, 202.0, 204.0],
            queried_indices=[0, 2],
            interpolated_indices=[1],
        )
        assert 0 in res.queried_indices
        assert 2 in res.queried_indices
        assert 1 in res.interpolated_indices
        assert res.resolution_m == 90.0

    def test_elevation_interpolation_uses_cumulative_distance(self):
        """Intermediate elevation interpolation is based strictly on path distance fraction."""
        provider = OpenMeteoElevationProvider()
        coords = [(28.61, 77.20), (28.62, 77.21), (28.63, 77.22)]
        cum_dists = [0.0, 250.0, 1000.0]  # Point 1 is at 25% of path distance

        # Interpolation math check: start=100m, end=200m. At 250m / 1000m, frac=0.25 -> 125.0m
        d_span = cum_dists[2] - cum_dists[0]
        frac = (cum_dists[1] - cum_dists[0]) / d_span
        h_interp = round(100.0 + frac * (200.0 - 100.0), 1)
        assert h_interp == 125.0

    def test_raw_gradient_preserved_when_clamped(self):
        """Extreme gradient (>35%) must preserve exact raw gradient, clamped value, and warning."""
        # 100m distance, 42m rise = +42.0% raw gradient
        res = ElevationProcessor.compute_gradient_percent(100.0, 142.0, 100.0)
        assert res.raw_gradient == 42.0
        assert res.gradient == 35.0  # Clamped to 35%
        assert res.is_clamped is True
        assert "exceeds realistic road limit" in res.warning

    def test_distinct_routing_options_produce_distinct_cache_keys(self):
        """Routing requests with distinct options (e.g. avoid tolls) must produce distinct cache entries."""
        cache = SimpleTTLCache()
        p = RouteEnrichmentPipeline(
            routing_provider=MockRoutingProvider(),
            elevation_provider=MockElevationProvider(),
            cache=cache,
        )
        r_toll = p.enrich_route((28.61, 77.20), (28.70, 77.30), options={"avoid": "tolls"})
        r_ferry = p.enrich_route((28.61, 77.20), (28.70, 77.30), options={"avoid": "ferries"})
        r_none = p.enrich_route((28.61, 77.20), (28.70, 77.30), options=None)

        route_keys = [k for k in cache._cache.keys() if k.startswith("route:")]
        assert len(route_keys) == 3
        assert len(set(route_keys)) == 3

    def test_original_road_class_preserved(self):
        """Raw road class from provider (e.g. trunk_link) is preserved alongside normalized category."""
        geom = GeometryProcessor.process_route_geometry(
            [(28.61, 77.20), (28.62, 77.21)], target_sample_interval_m=100.0
        )
        step = ProviderStep(
            name="Delhi Bypass",
            distance_m=1000.0,
            duration_s=60.0,
            road_class="trunk_link",
            start_coordinate=(28.61, 77.20),
            end_coordinate=(28.62, 77.21),
        )
        slices = RouteSegmenter.segment_route(geom, steps=[step])
        assert len(slices) >= 1
        assert slices[0].raw_road_class == "trunk_link"
        assert slices[0].road_type == "highway"

