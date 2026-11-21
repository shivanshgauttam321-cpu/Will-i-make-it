"""
Weather Provider Base Interface
===============================
Abstract interface for querying ambient meteorological conditions along route corridors.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Optional, List, Tuple
from app.domain.environment import WeatherDomain


class WeatherProvider(ABC):
    """Abstract interface for ambient weather lookups."""

    @property
    @abstractmethod
    def provider_name(self) -> str:
        """Name of the meteorological service."""
        pass

    @abstractmethod
    def is_available(self) -> bool:
        """Check if provider endpoint is configured."""
        pass

    @abstractmethod
    def get_weather(self, latitude: float, longitude: float) -> Optional[WeatherDomain]:
        """Query weather conditions at a specific (lat, lng) point."""
        pass
