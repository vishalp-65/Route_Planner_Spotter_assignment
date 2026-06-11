"""Driving-route retrieval from an external routing provider."""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass

import requests
from django.conf import settings

from routing.exceptions import RoutingProviderError
from routing.services.types import Coordinates

logger = logging.getLogger("routing")

METERS_PER_MILE = 1609.344


@dataclass(frozen=True)
class RouteResult:
    """A driving route from origin to destination."""

    distance_miles: float
    duration_seconds: float
    geometry: list[Coordinates]  # ordered polyline vertices, origin -> destination


class RoutingProvider(ABC):
    """Fetches a driving route between two points."""

    @abstractmethod
    def get_route(self, origin: Coordinates, destination: Coordinates) -> RouteResult:
        """
        Raises:
            RoutingProviderError: if no route can be found or the provider fails.
        """


class OSRMRoutingProvider(RoutingProvider):
    """Routing via the free, keyless OSRM demo server.

    A single GET request returns both the route geometry and distance, so
    one call to this provider per planning request is all that's needed.
    ``overview=simplified`` (OSRM's Douglas-Peucker simplified geometry) is
    used deliberately: it keeps the polyline compact (fast to transfer and
    fast to match stations against) while still representing the route's
    shape closely enough for ~5 mile corridor matching.
    """

    def __init__(self, base_url: str | None = None, timeout: float | None = None):
        config = settings.FUEL_ROUTE_CONFIG
        self.base_url = (base_url or config["OSRM_BASE_URL"]).rstrip("/")
        self.timeout = timeout or config["EXTERNAL_API_TIMEOUT_SECONDS"]

    def get_route(self, origin: Coordinates, destination: Coordinates) -> RouteResult:
        coords = (
            f"{origin.longitude},{origin.latitude};"
            f"{destination.longitude},{destination.latitude}"
        )
        url = f"{self.base_url}/route/v1/driving/{coords}"

        try:
            response = requests.get(
                url,
                params={"overview": "simplified", "geometries": "geojson"},
                timeout=self.timeout,
            )
            response.raise_for_status()
        except requests.RequestException as exc:
            logger.error("OSRM routing request failed: %s", exc)
            raise RoutingProviderError(f"Routing service error: {exc}") from exc

        try:
            payload = response.json()
        except ValueError as exc:
            raise RoutingProviderError("Routing service returned invalid JSON.") from exc

        if payload.get("code") != "Ok" or not payload.get("routes"):
            raise RoutingProviderError(
                f"Routing service could not find a route (code={payload.get('code')!r})."
            )

        route = payload["routes"][0]
        geometry = [
            Coordinates(latitude=lat, longitude=lon) for lon, lat in route["geometry"]["coordinates"]
        ]
        return RouteResult(
            distance_miles=route["distance"] / METERS_PER_MILE,
            duration_seconds=route["duration"],
            geometry=geometry,
        )
