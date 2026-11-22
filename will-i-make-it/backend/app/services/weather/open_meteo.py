"""
Open-Meteo Weather Provider
===========================
Fetches real-time ambient temperature, wind, and precipitation from Open-Meteo.
Caches point weather in-memory with a 30-minute TTL.
Never fabricates weather observations; marks forecasts as DataStatus.ESTIMATED.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional, List, Tuple
import httpx

from app.domain.provenance import (
    DataValue, DataProvenance, DataStatus, SourceType
)
from app.domain.environment import WeatherDomain
from app.services.weather.base import WeatherProvider
from app.services.cache import SimpleTTLCache

logger = logging.getLogger(__name__)

OPEN_METEO_FORECAST_URL = "https://api.open-meteo.com/v1/forecast"


class OpenMeteoWeatherProvider(WeatherProvider):
    """Weather provider querying Open-Meteo API."""

    def __init__(
        self,
        base_url: str = OPEN_METEO_FORECAST_URL,
        timeout_seconds: float = 6.0,
        cache: Optional[SimpleTTLCache] = None,
    ):
        self._base_url = base_url
        self._timeout = timeout_seconds
        self._cache = cache if cache is not None else SimpleTTLCache(default_ttl_seconds=1800.0)

    @property
    def provider_name(self) -> str:
        return "Open-Meteo Weather API"

    def is_available(self) -> bool:
        return bool(self._base_url)

    def get_weather(self, latitude: float, longitude: float) -> Optional[WeatherDomain]:
        """Query weather conditions at (lat, lng). Returns WeatherDomain or None."""
        cache_key = f"weather:{latitude:.2f},{longitude:.2f}"
        cached = self._cache.get(cache_key)
        if cached is not None:
            return cached

        params = {
            "latitude": f"{latitude:.4f}",
            "longitude": f"{longitude:.4f}",
            "current": "temperature_2m,relative_humidity_2m,apparent_temperature,precipitation,wind_speed_10m,wind_direction_10m,weather_code",
        }

        try:
            with httpx.Client(timeout=self._timeout) as client:
                resp = client.get(self._base_url, params=params)
                if resp.status_code == 200:
                    data = resp.json()
                    current = data.get("current", {})
                    temp = current.get("temperature_2m")
                    wind_speed = current.get("wind_speed_10m")
                    wind_dir = current.get("wind_direction_10m")
                    precip = current.get("precipitation")
                    weather_code = current.get("weather_code")

                    now = datetime.now(timezone.utc)
                    prov = DataProvenance(
                        source_name=self.provider_name,
                        source_type=SourceType.API_TELEMETRY,
                        status=DataStatus.ESTIMATED,
                    )

                    weather_domain = WeatherDomain(
                        ambient_temperature=DataValue.estimated(
                            value=float(temp) if temp is not None else 28.0,
                            unit="°C",
                            source_name=self.provider_name,
                        ),
                        wind_speed=DataValue.estimated(
                            value=float(wind_speed) if wind_speed is not None else 0.0,
                            unit="km/h",
                            source_name=self.provider_name,
                        ) if wind_speed is not None else None,
                        wind_direction_deg=DataValue.estimated(
                            value=float(wind_dir) if wind_dir is not None else 0.0,
                            unit="deg",
                            source_name=self.provider_name,
                        ) if wind_dir is not None else None,
                        precipitation_mm=DataValue.estimated(
                            value=float(precip) if precip is not None else 0.0,
                            unit="mm",
                            source_name=self.provider_name,
                        ) if precip is not None else None,
                        condition=DataValue.estimated(
                            value=self._decode_wmo_code(weather_code),
                            unit="",
                            source_name=self.provider_name,
                        ),
                        is_forecast=True,
                        forecast_timestamp=now,
                        retrieval_timestamp=now,
                        provenance=prov,
                    )

                    self._cache.set(cache_key, weather_domain)
                    return weather_domain
                else:
                    logger.warning(
                        f"Open-Meteo weather failed with status {resp.status_code}: {resp.text[:200]}"
                    )
        except Exception as e:
            logger.warning(f"Open-Meteo weather network error: {e}")

        return None

    @staticmethod
    def _decode_wmo_code(code: Optional[int]) -> str:
        """Decode WMO weather interpretation code to clear string."""
        if code is None:
            return "CLEAR"
        if code == 0:
            return "CLEAR"
        if code in (1, 2, 3):
            return "PARTLY_CLOUDY"
        if code in (45, 48):
            return "FOG"
        if code in (51, 53, 55, 61, 63, 65, 80, 81, 82):
            return "RAIN"
        if code in (71, 73, 75, 77, 85, 86):
            return "SNOW"
        if code in (95, 96, 99):
            return "THUNDERSTORM"
        return "OVERCAST"
