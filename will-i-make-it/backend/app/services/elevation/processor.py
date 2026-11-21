"""
Elevation & Gradient Processing Pipeline
========================================
Applies topographical filtering (median, moving average) to raw DEM points,
computes horizontal road gradient, and calculates cumulative elevation gain/loss.
"""
from __future__ import annotations

import math
from typing import List, Tuple, Optional
from pydantic import BaseModel, Field

from app.domain.provenance import DataStatus


class GradientResult(BaseModel):
    """
    Structured outcome of road gradient calculation.
    Preserves raw calculated gradient, accepted (clamped) gradient, clamping indicator,
    and validation warning without concealing extreme values.
    """
    raw_gradient: Optional[float] = None
    gradient: Optional[float] = None
    status: DataStatus
    is_clamped: bool = False
    warning: Optional[str] = None

    def __iter__(self):
        """Enable backward-compatible tuple unpacking: grad_val, grad_status = compute_gradient_percent(...)"""
        return iter((self.gradient if self.gradient is not None else 0.0, self.status))


class ElevationProfileSummary(BaseModel):
    """Statistical summary of a route's elevation profile."""
    min_elevation_m: Optional[float] = None
    max_elevation_m: Optional[float] = None
    total_gain_m: float = 0.0
    total_loss_m: float = 0.0
    has_elevation_data: bool = False


class ElevationProcessor:
    """Processes elevation points, smooths noise, and computes physical gradients."""

    MAX_REALISTIC_GRADIENT_PERCENT = 35.0

    @classmethod
    def median_filter(
        cls,
        elevations: List[Optional[float]],
        window_size: int = 3,
    ) -> List[Optional[float]]:
        """
        Apply 1D median filter over known elevation points to remove DEM spikes.
        Preserves None values where elevation was missing.
        """
        n = len(elevations)
        if n < 3 or window_size < 3:
            return list(elevations)

        radius = window_size // 2
        filtered: List[Optional[float]] = []

        for i in range(n):
            if elevations[i] is None:
                filtered.append(None)
                continue

            # Preserve route boundary points
            if i == 0 or i == n - 1:
                filtered.append(elevations[i])
                continue

            window_vals = [
                elevations[j]
                for j in range(max(0, i - radius), min(n, i + radius + 1))
                if elevations[j] is not None
            ]

            if window_vals:
                window_vals.sort()
                mid = len(window_vals) // 2
                filtered.append(round(window_vals[mid], 1))
            else:
                filtered.append(elevations[i])

        return filtered

    @classmethod
    def moving_average_filter(
        cls,
        elevations: List[Optional[float]],
        window_size: int = 3,
    ) -> List[Optional[float]]:
        """
        Smooth DEM quantization steps using a moving average window.
        Preserves None values.
        """
        n = len(elevations)
        if n < 3 or window_size < 3:
            return list(elevations)

        radius = window_size // 2
        smoothed: List[Optional[float]] = []

        for i in range(n):
            if elevations[i] is None:
                smoothed.append(None)
                continue

            window_vals = [
                elevations[j]
                for j in range(max(0, i - radius), min(n, i + radius + 1))
                if elevations[j] is not None
            ]

            if window_vals:
                avg = sum(window_vals) / len(window_vals)
                smoothed.append(round(avg, 1))
            else:
                smoothed.append(elevations[i])

        return smoothed

    @classmethod
    def compute_gradient_percent(
        cls,
        start_elevation: Optional[float],
        end_elevation: Optional[float],
        path_distance_m: float,
    ) -> GradientResult:
        """
        Compute road gradient percentage from horizontal distance and elevation change:
            gradient = ((end_elevation - start_elevation) / horizontal_distance_m) * 100

        Args:
            start_elevation: Starting elevation above sea level in meters.
            end_elevation: Ending elevation above sea level in meters.
            path_distance_m: Horizontal distance in meters (from great-circle Haversine).

        Returns:
            GradientResult containing raw_gradient, accepted clamped gradient,
            provenance status, clamping flag, and validation warning.
            If elevation is missing or distance <= 0, returns status=DataStatus.UNKNOWN
            with gradient=None and raw_gradient=None.
        """
        if start_elevation is None or end_elevation is None or path_distance_m <= 0.0:
            return GradientResult(
                raw_gradient=None,
                gradient=None,
                status=DataStatus.UNKNOWN,
                is_clamped=False,
                warning="Missing elevation or non-positive segment distance",
            )

        delta_h = end_elevation - start_elevation
        # Direct horizontal gradient (exact, removing redundant 3D hypotenuse subtraction)
        raw_gradient = (delta_h / path_distance_m) * 100.0

        is_clamped = abs(raw_gradient) > cls.MAX_REALISTIC_GRADIENT_PERCENT
        clamped_gradient = max(
            -cls.MAX_REALISTIC_GRADIENT_PERCENT,
            min(cls.MAX_REALISTIC_GRADIENT_PERCENT, raw_gradient),
        )
        warning = (
            f"Raw gradient {raw_gradient:.1f}% exceeds realistic road limit (±{cls.MAX_REALISTIC_GRADIENT_PERCENT:.1f}%) and was clamped"
            if is_clamped
            else None
        )

        return GradientResult(
            raw_gradient=round(raw_gradient, 2),
            gradient=round(clamped_gradient, 2),
            status=DataStatus.ESTIMATED,
            is_clamped=is_clamped,
            warning=warning,
        )

    @classmethod
    def compute_profile_summary(
        cls,
        segment_elevations: List[Tuple[Optional[float], Optional[float]]],
    ) -> ElevationProfileSummary:
        """
        Calculate total gain, loss, min, and max elevation from segment endpoint elevations.
        """
        valid_elevs: List[float] = []
        total_gain = 0.0
        total_loss = 0.0

        for h_start, h_end in segment_elevations:
            if h_start is not None:
                valid_elevs.append(h_start)
            if h_end is not None:
                valid_elevs.append(h_end)

            if h_start is not None and h_end is not None:
                diff = h_end - h_start
                if diff > 0:
                    total_gain += diff
                else:
                    total_loss += abs(diff)

        if not valid_elevs:
            return ElevationProfileSummary(
                min_elevation_m=None,
                max_elevation_m=None,
                total_gain_m=0.0,
                total_loss_m=0.0,
                has_elevation_data=False,
            )

        return ElevationProfileSummary(
            min_elevation_m=round(min(valid_elevs), 1),
            max_elevation_m=round(max(valid_elevs), 1),
            total_gain_m=round(total_gain, 1),
            total_loss_m=round(total_loss, 1),
            has_elevation_data=True,
        )
