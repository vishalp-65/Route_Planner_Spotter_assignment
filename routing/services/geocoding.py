"""Geocoding for user-supplied start/finish locations.

This is deliberately separate from the offline city-centroid lookup used
by ``import_fuel_stations`` for the ~6,600 fuel stations: here we only ever
geocode at most two free-form strings per request, so an online geocoder
with a persistent cache is simple, accurate, and well within any
reasonable rate limit.
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod

import requests
from django.conf import settings
from django.core.cache import caches

from routing.exceptions import GeocodingError
from routing.services.types import Coordinates

logger = logging.getLogger("routing")


class GeocodingProvider(ABC):
    """Resolves a free-form location string to coordinates."""

    @abstractmethod
    def geocode(self, location: str) -> Coordinates:
        """
        Raises:
            GeocodingError: if the location cannot be resolved.
        """


class NominatimGeocodingProvider(GeocodingProvider):
    """Geocodes via the free, keyless OpenStreetMap Nominatim API.

    Results are cached indefinitely in a persistent (file-based) cache, so
    a given location string triggers at most one network call across the
    lifetime of the deployment - including across process restarts.
    """

    SEARCH_PATH = "/search"
    CACHE_ALIAS = "geocode"

    def __init__(
        self,
        base_url: str | None = None,
        user_agent: str | None = None,
        timeout: float | None = None,
    ):
        config = settings.FUEL_ROUTE_CONFIG
        self.base_url = (base_url or config["NOMINATIM_BASE_URL"]).rstrip("/")
        self.user_agent = user_agent or config["NOMINATIM_USER_AGENT"]
        self.timeout = timeout or config["EXTERNAL_API_TIMEOUT_SECONDS"]
        self._cache = caches[self.CACHE_ALIAS]

    def geocode(self, location: str) -> Coordinates:
        normalized = " ".join(location.strip().split())
        if not normalized:
            raise GeocodingError(location, "Location must not be empty.")

        cache_key = f"geocode:{normalized.lower()}"
        cached = self._cache.get(cache_key)
        if cached is not None:
            return Coordinates(*cached)

        coordinates = self._fetch(normalized)
        self._cache.set(cache_key, (coordinates.latitude, coordinates.longitude))
        return coordinates

    def _fetch(self, query: str) -> Coordinates:
        try:
            response = requests.get(
                f"{self.base_url}{self.SEARCH_PATH}",
                params={
                    "q": query,
                    "format": "jsonv2",
                    "countrycodes": "us",
                    "limit": 1,
                },
                headers={"User-Agent": self.user_agent},
                timeout=self.timeout,
            )
            response.raise_for_status()
        except requests.RequestException as exc:
            logger.warning("Geocoding request failed for %r: %s", query, exc)
            raise GeocodingError(query, f"Geocoding service error for {query!r}: {exc}") from exc

        try:
            results = response.json()
        except ValueError as exc:
            raise GeocodingError(query, f"Geocoding service returned invalid JSON for {query!r}") from exc

        if not results:
            raise GeocodingError(query)

        try:
            return Coordinates(latitude=float(results[0]["lat"]), longitude=float(results[0]["lon"]))
        except (KeyError, ValueError, TypeError) as exc:
            raise GeocodingError(query, f"Unexpected geocoding response for {query!r}") from exc
