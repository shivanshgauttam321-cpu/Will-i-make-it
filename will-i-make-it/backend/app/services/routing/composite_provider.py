"""
Composite Routing Provider Orchestrator
=======================================
Manages the provider fallback sequence (Mappls -> Valhalla -> OSRM).
Ensures provider failover is transparent, recorded, and never fabricates fake routes.
"""
from __future__ import annotations

from typing import List, Tuple, Optional, Dict, Any

from app.services.routing.base import (
    RoutingProvider,
    ProviderRouteResult,
    RoutingProviderError,
)
from app.services.routing.mappls_provider import MapplsRoutingProvider
from app.services.routing.valhalla_provider import ValhallaRoutingProvider
from app.services.routing.osrm_provider import OSRMRoutingProvider


class CompositeRoutingProvider(RoutingProvider):
    """
    Orchestrator that queries routing providers in priority order.
    By default: Mappls (Primary India) -> Valhalla (Self-hosted/Open-Source) -> OSRM (Operational Baseline).
    """

    def __init__(self, providers: Optional[List[RoutingProvider]] = None):
        self.providers = providers if providers is not None else [
            MapplsRoutingProvider(),
            ValhallaRoutingProvider(),
            OSRMRoutingProvider(),
        ]

    @property
    def provider_name(self) -> str:
        return "Composite Routing Orchestrator"

    def is_available(self) -> bool:
        """True if at least one underlying provider is available."""
        return any(p.is_available() for p in self.providers)

    def get_route(
        self,
        origin: Tuple[float, float],
        destination: Tuple[float, float],
        options: Optional[Dict[str, Any]] = None,
    ) -> ProviderRouteResult:
        attempt_errors: List[str] = []

        for provider in self.providers:
            if not provider.is_available():
                attempt_errors.append(f"{provider.provider_name}: Not configured / unavailable")
                continue

            try:
                result = provider.get_route(origin, destination, options)
                return result
            except RoutingProviderError as e:
                attempt_errors.append(str(e))
            except Exception as e:
                attempt_errors.append(f"{provider.provider_name} unhandled error: {e}")

        # All providers failed or unconfigured
        details = " | ".join(attempt_errors)
        raise RoutingProviderError(
            "CompositeRoutingProvider",
            f"All routing providers failed. Attempts: [{details}]. Real route could not be established."
        )

    def get_route_alternatives(
        self,
        origin: Tuple[float, float],
        destination: Tuple[float, float],
        options: Optional[Dict[str, Any]] = None,
    ) -> List[ProviderRouteResult]:
        attempt_errors: List[str] = []

        for provider in self.providers:
            if not provider.is_available():
                continue
            try:
                return provider.get_route_alternatives(origin, destination, options)
            except Exception as e:
                attempt_errors.append(f"{provider.provider_name}: {e}")

        # Fallback to single route if alternatives call fails
        primary = self.get_route(origin, destination, options)
        return [primary]
