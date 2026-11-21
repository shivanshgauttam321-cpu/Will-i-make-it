"""
Route Segmentation Engine
=========================
Divides analytical route geometry into contiguous physical road segments.
Targets 250m segment length (bounded [100m, 500m]) and aligns with step transitions.
Guarantees strict contiguity: segment[i].end == segment[i+1].start.
"""
from __future__ import annotations

from typing import List, Tuple, Optional
from pydantic import BaseModel, Field

from app.domain.provenance import (
    DataValue, DataProvenance, DataStatus, SourceType, DataQuality,
    DataFloat, DataStr
)
from app.services.geometry.processor import AnalyticalGeometry
from app.services.routing.base import ProviderStep


class SegmentSlice(BaseModel):
    """Raw slice of analytical geometry forming a segment."""
    sequence_order: int
    start_index: int
    end_index: int
    start_coord: Tuple[float, float]
    end_coord: Tuple[float, float]
    start_distance_m: float
    end_distance_m: float
    length_m: float
    points: List[Tuple[float, float]]
    road_name: Optional[str] = None
    road_type: str = "highway"
    raw_road_class: Optional[str] = None
    road_condition: str = "SMOOTH_ASPHALT"
    speed_kmh: float = 60.0
    speed_status: DataStatus = DataStatus.ESTIMATED
    speed_limit_kmh: Optional[float] = None
    speed_method: str = "Step duration/distance calculation"


class RouteSegmenter:
    """Segments an AnalyticalGeometry into contiguous physics-ready slices."""

    TARGET_LENGTH_M = 250.0
    MIN_LENGTH_M = 100.0
    MAX_LENGTH_M = 500.0

    @classmethod
    def segment_route(
        cls,
        analytical_geom: AnalyticalGeometry,
        steps: Optional[List[ProviderStep]] = None,
        target_length_m: float = TARGET_LENGTH_M,
        min_m: float = MIN_LENGTH_M,
        max_m: float = MAX_LENGTH_M,
    ) -> List[SegmentSlice]:
        """
        Segment the analytical geometry into contiguous slices.
        
        Args:
            analytical_geom: Processed geometry containing coordinates and cumulative distances.
            steps: Optional list of provider maneuver steps to enrich segments with road names and types.
            target_length_m: Desired nominal segment length (default 250m).
            min_m: Minimum segment length allowed before merging (default 100m).
            max_m: Maximum segment length allowed before forcing a split (default 500m).
            
        Returns:
            List of SegmentSlice items strictly contiguous along the route.
        """
        pts = analytical_geom.analytical_points
        cum_dists = analytical_geom.cumulative_distances_m
        total_dist = analytical_geom.total_distance_m
        n_points = len(pts)

        if n_points < 2 or total_dist <= 0:
            return []

        # If the entire route is shorter than min_m, return a single segment spanning it
        if total_dist <= min_m or n_points == 2:
            road_name, road_type, raw_road_class, speed_kmh, speed_status, speed_limit_kmh, speed_method = cls._find_step_attributes(
                0.0, total_dist, steps
            )
            return [
                SegmentSlice(
                    sequence_order=0,
                    start_index=0,
                    end_index=n_points - 1,
                    start_coord=pts[0],
                    end_coord=pts[-1],
                    start_distance_m=0.0,
                    end_distance_m=total_dist,
                    length_m=total_dist,
                    points=pts,
                    road_name=road_name,
                    road_type=road_type,
                    raw_road_class=raw_road_class,
                    road_condition="SMOOTH_ASPHALT",
                    speed_kmh=speed_kmh,
                    speed_status=speed_status,
                    speed_limit_kmh=speed_limit_kmh,
                    speed_method=speed_method,
                )
            ]

        # Precompute step distance ranges if available
        step_ranges: List[Tuple[float, float, ProviderStep]] = []
        if steps:
            s_cum = 0.0
            for step in steps:
                s_start = s_cum
                s_end = s_cum + step.distance_m
                step_ranges.append((s_start, s_end, step))
                s_cum = s_end

        slices: List[SegmentSlice] = []
        curr_start_idx = 0
        seg_seq = 0

        while curr_start_idx < n_points - 1:
            start_dist = cum_dists[curr_start_idx]
            target_dist = start_dist + target_length_m

            # Find best split index j > curr_start_idx
            best_idx = curr_start_idx + 1
            min_diff = float("inf")

            for j in range(curr_start_idx + 1, n_points):
                seg_len = cum_dists[j] - start_dist
                rem_len = cum_dists[-1] - cum_dists[j]

                # Check if this point aligns with a step transition
                step_boundary_bonus = 0.0
                if step_ranges and seg_len >= min_m and seg_len <= max_m:
                    for s_start, s_end, _ in step_ranges:
                        if abs(cum_dists[j] - s_end) <= 15.0:  # within 15m of a turn
                            step_boundary_bonus = 50.0  # prefer breaking at turn
                            break

                diff = abs(seg_len - target_length_m) - step_boundary_bonus

                # Check if we should stop at this point
                if seg_len >= min_m and diff < min_diff:
                    min_diff = diff
                    best_idx = j

                # If remaining distance after j would be < min_m, we should merge tail unless exceeding max_m
                if rem_len < min_m and rem_len > 0:
                    total_candidate = cum_dists[-1] - start_dist
                    if total_candidate <= max_m:
                        best_idx = n_points - 1
                        break

                if seg_len >= max_m:
                    if best_idx <= curr_start_idx:
                        best_idx = j
                    break

            # Fallback if best_idx didn't advance
            if best_idx <= curr_start_idx:
                best_idx = min(curr_start_idx + 1, n_points - 1)

            # Ensure the very last segment reaches the final point
            if best_idx == n_points - 1 or (cum_dists[-1] - cum_dists[best_idx]) < min_m:
                best_idx = n_points - 1

            seg_pts = pts[curr_start_idx : best_idx + 1]
            s_dist = cum_dists[curr_start_idx]
            e_dist = cum_dists[best_idx]
            s_len = e_dist - s_dist

            road_name, road_type, raw_road_class, speed_kmh, speed_status, speed_limit_kmh, speed_method = cls._find_step_attributes(
                s_dist, e_dist, steps
            )

            slices.append(
                SegmentSlice(
                    sequence_order=seg_seq,
                    start_index=curr_start_idx,
                    end_index=best_idx,
                    start_coord=pts[curr_start_idx],
                    end_coord=pts[best_idx],
                    start_distance_m=round(s_dist, 2),
                    end_distance_m=round(e_dist, 2),
                    length_m=round(s_len, 2),
                    points=seg_pts,
                    road_name=road_name,
                    road_type=road_type,
                    raw_road_class=raw_road_class,
                    road_condition="SMOOTH_ASPHALT",
                    speed_kmh=speed_kmh,
                    speed_status=speed_status,
                    speed_limit_kmh=speed_limit_kmh,
                    speed_method=speed_method,
                )
            )

            curr_start_idx = best_idx
            seg_seq += 1

        return slices

    @classmethod
    def _find_step_attributes(
        cls,
        start_dist: float,
        end_dist: float,
        steps: Optional[List[ProviderStep]],
    ) -> Tuple[Optional[str], str, Optional[str], float, DataStatus, Optional[float], str]:
        """Find matching road name, road type, raw road class, speed, and speed limit from steps."""
        if not steps:
            speed, status, speed_limit, method = cls._determine_speed(None, "highway")
            return None, "highway", None, speed, status, speed_limit, method

        mid_dist = (start_dist + end_dist) / 2.0
        cum = 0.0
        for step in steps:
            s_start = cum
            s_end = cum + step.distance_m
            cum = s_end
            if s_start <= mid_dist <= s_end:
                road_name = step.name if (step.name and step.name.strip()) else None
                road_type = cls._normalize_road_class(step.road_class)
                raw_road_class = step.road_class
                speed, status, speed_limit, method = cls._determine_speed(step, road_type)
                return road_name, road_type, raw_road_class, speed, status, speed_limit, method

        # Fallback if midpoint falls outside step ranges
        speed, status, speed_limit, method = cls._determine_speed(None, "highway")
        return None, "highway", None, speed, status, speed_limit, method

    @staticmethod
    def _normalize_road_class(road_class: Optional[str]) -> str:
        """Map provider road class to domain road types: expressway, highway, urban, rural."""
        if not road_class:
            return "highway"
        rc = road_class.lower()
        if any(k in rc for k in ["motorway", "expressway", "freeway"]):
            return "expressway"
        if any(k in rc for k in ["primary", "trunk", "secondary"]):
            return "highway"
        if any(k in rc for k in ["residential", "living_street", "service", "tertiary"]):
            return "urban"
        if any(k in rc for k in ["track", "unclassified", "rural"]):
            return "rural"
        return "highway"

    @classmethod
    def _determine_speed(
        cls, step: Optional[ProviderStep], road_type: str
    ) -> Tuple[float, DataStatus, Optional[float], str]:
        """
        Determine estimated vehicle driving speed and separate it strictly from speed limit.
        
        Rules:
        1. Prefer step distance and duration when both are valid.
        2. Never assign statutory speed limits as actual driving speeds.
        3. If unavailable, use category baseline heuristic, explicitly marked ESTIMATED.
        
        Returns:
            Tuple of (estimated_speed_kmh, speed_status, speed_limit_kmh, method_note).
        """
        speed_limit = None
        if step and step.speed_limit_kmh is not None and step.speed_limit_kmh > 0:
            speed_limit = float(step.speed_limit_kmh)

        # 1. Prefer step distance and duration when both are valid
        if step and step.duration_s > 0 and step.distance_m > 0:
            avg_speed = (step.distance_m / 1000.0) / (step.duration_s / 3600.0)
            if 5.0 <= avg_speed <= 140.0:
                return round(avg_speed, 1), DataStatus.ESTIMATED, speed_limit, "Step duration/distance calculation"

        # 2. Heuristic fallback when step duration is unavailable or invalid
        defaults = {
            "expressway": 75.0,
            "highway": 60.0,
            "urban": 30.0,
            "rural": 40.0,
        }
        fallback_speed = defaults.get(road_type, 50.0)
        return fallback_speed, DataStatus.ESTIMATED, speed_limit, "Category baseline heuristic (unverified)"
