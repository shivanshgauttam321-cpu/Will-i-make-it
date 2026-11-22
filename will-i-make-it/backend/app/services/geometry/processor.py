"""
Route Geometry Processing Pipeline
==================================
Transforms raw provider polylines into validated, monotonic analytical representations
suitable for spatial elevation sampling and physics segmentation.

Key Responsibilities:
1. Coordinate bounds validation (-90 <= lat <= 90, -180 <= lng <= 180).
2. Sequential deduplication (< 1mm threshold).
3. Accurate great-circle cumulative distance calculation.
4. Resampling at controlled spatial intervals (e.g. 50-100m) to generate Analytical Geometry.
5. Preserving exact Provider Display Geometry for interactive UI map rendering.
"""
from __future__ import annotations

import math
from typing import List, Tuple, Optional
from pydantic import BaseModel, Field

EARTH_RADIUS_METERS = 6371000.0


def haversine_distance_m(p1: Tuple[float, float], p2: Tuple[float, float]) -> float:
    """Great-circle distance between two (lat, lng) points in meters."""
    lat1, lon1 = p1
    lat2, lon2 = p2
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    delta_phi = math.radians(lat2 - lat1)
    delta_lambda = math.radians(lon2 - lon1)

    a = (
        math.sin(delta_phi / 2.0) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(delta_lambda / 2.0) ** 2
    )
    c = 2.0 * math.atan2(math.sqrt(max(0.0, a)), math.sqrt(max(0.0, 1.0 - a)))
    return EARTH_RADIUS_METERS * c


def interpolate_point(p1: Tuple[float, float], p2: Tuple[float, float], fraction: float) -> Tuple[float, float]:
    """Linear interpolation between two (lat, lng) points by fraction in [0, 1]."""
    lat = p1[0] + (p2[0] - p1[0]) * fraction
    lng = p1[1] + (p2[1] - p1[1]) * fraction
    return (round(lat, 6), round(lng, 6))


class AnalyticalGeometry(BaseModel):
    """Processed route geometry separating display representation from analytical points."""
    display_points: List[Tuple[float, float]] = Field(
        ...,
        description="Original turn-by-turn road polyline for UI map display"
    )
    analytical_points: List[Tuple[float, float]] = Field(
        ...,
        description="Controlled, resampled spatial coordinate sequence for elevation and physics"
    )
    cumulative_distances_m: List[float] = Field(
        ...,
        description="Cumulative distance in meters for each analytical point (monotonically non-decreasing)"
    )
    total_distance_m: float = Field(..., ge=0.0)
    point_count: int = Field(..., ge=1)


class GeometryProcessor:
    """Validates, cleans, and resamples route coordinates."""

    @staticmethod
    def validate_coordinates(points: List[Tuple[float, float]]) -> List[Tuple[float, float]]:
        """Filter out points with out-of-range coordinates."""
        validated = []
        for lat, lng in points:
            if -90.0 <= lat <= 90.0 and -180.0 <= lng <= 180.0:
                validated.append((lat, lng))
            else:
                raise ValueError(f"Invalid coordinate: ({lat}, {lng})")
        if len(validated) < 2:
            raise ValueError("Geometry must contain at least two valid coordinates.")
        return validated

    @staticmethod
    def deduplicate_consecutive(points: List[Tuple[float, float]], threshold_m: float = 0.5) -> List[Tuple[float, float]]:
        """Remove consecutive duplicate points that are closer than threshold_m."""
        if not points:
            return []
        cleaned = [points[0]]
        for pt in points[1:]:
            dist = haversine_distance_m(cleaned[-1], pt)
            if dist >= threshold_m:
                cleaned.append(pt)
        # Ensure the last destination point is preserved
        if cleaned[-1] != points[-1]:
            cleaned.append(points[-1])
        return cleaned

    @classmethod
    def process_route_geometry(
        cls,
        raw_points: List[Tuple[float, float]],
        target_sample_interval_m: float = 100.0,
    ) -> AnalyticalGeometry:
        """
        Produce a validated AnalyticalGeometry from a raw provider polyline.
        Resamples the path at controlled distances (target_sample_interval_m)
        to allow regular DEM elevation sampling and unbiased gradient calculation.
        """
        valid_points = cls.validate_coordinates(raw_points)
        display_points = cls.deduplicate_consecutive(valid_points)

        # 1. Compute cumulative distance along the display geometry
        display_cum_dists = [0.0]
        for i in range(1, len(display_points)):
            d = haversine_distance_m(display_points[i - 1], display_points[i])
            display_cum_dists.append(display_cum_dists[-1] + d)

        total_distance_m = display_cum_dists[-1]

        # 2. Resample at regular intervals for analytical points
        if total_distance_m <= 0.0 or target_sample_interval_m <= 0.0 or len(display_points) < 2:
            return AnalyticalGeometry(
                display_points=display_points,
                analytical_points=display_points,
                cumulative_distances_m=[0.0] * len(display_points),
                total_distance_m=0.0,
                point_count=len(display_points),
            )

        num_samples = max(2, math.ceil(total_distance_m / target_sample_interval_m) + 1)
        actual_step_m = total_distance_m / (num_samples - 1)

        analytical_points: List[Tuple[float, float]] = [display_points[0]]
        analytical_cum_dists: List[float] = [0.0]

        curr_disp_idx = 0
        for step in range(1, num_samples - 1):
            target_dist = step * actual_step_m
            # Advance along display segments until target_dist falls between curr and curr+1
            while curr_disp_idx < len(display_cum_dists) - 2 and display_cum_dists[curr_disp_idx + 1] < target_dist:
                curr_disp_idx += 1

            seg_start_dist = display_cum_dists[curr_disp_idx]
            seg_end_dist = display_cum_dists[curr_disp_idx + 1]
            seg_len = seg_end_dist - seg_start_dist

            if seg_len > 0.0:
                fraction = (target_dist - seg_start_dist) / seg_len
                fraction = max(0.0, min(1.0, fraction))
                interp = interpolate_point(display_points[curr_disp_idx], display_points[curr_disp_idx + 1], fraction)
            else:
                interp = display_points[curr_disp_idx]

            analytical_points.append(interp)
            analytical_cum_dists.append(target_dist)

        # Append final endpoint
        analytical_points.append(display_points[-1])
        analytical_cum_dists.append(total_distance_m)

        return AnalyticalGeometry(
            display_points=display_points,
            analytical_points=analytical_points,
            cumulative_distances_m=analytical_cum_dists,
            total_distance_m=round(total_distance_m, 2),
            point_count=len(analytical_points),
        )
