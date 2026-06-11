"""Factory functions for external service providers.

The orchestrator (``RoutePlannerService``) depends only on the
``GeocodingProvider`` / ``RoutingProvider`` abstractions, obtained through
these factories. Swapping implementations (e.g. OSRM -> OpenRouteService)
means changing this one module, not any calling code.
"""

from __future__ import annotations

from routing.services.geocoding import GeocodingProvider, NominatimGeocodingProvider
from routing.services.routing_provider import OSRMRoutingProvider, RoutingProvider


def get_geocoding_provider() -> GeocodingProvider:
    return NominatimGeocodingProvider()


def get_routing_provider() -> RoutingProvider:
    return OSRMRoutingProvider()
