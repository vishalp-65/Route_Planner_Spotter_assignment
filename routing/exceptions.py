"""Domain-level exceptions for the routing app.

These are framework-agnostic (no Django/DRF imports) so the service layer
remains independently unit-testable. They are translated to HTTP responses
by ``routing.api.exceptions.fuel_route_exception_handler``.
"""

from __future__ import annotations


class FuelRouteError(Exception):
    """Base class for all domain errors raised by the routing services."""


class GeocodingError(FuelRouteError):
    """A location string could not be resolved to coordinates."""

    def __init__(self, query: str, message: str | None = None):
        self.query = query
        super().__init__(message or f"Could not resolve location: {query!r}")


class RoutingProviderError(FuelRouteError):
    """The external routing provider failed or returned no usable route."""


class InfeasibleRouteError(FuelRouteError):
    """A route has a gap between consecutive fuel stops exceeding vehicle range."""

    def __init__(self, gap_miles: float, range_miles: float, from_mile: float, to_mile: float):
        self.gap_miles = gap_miles
        self.range_miles = range_miles
        self.from_mile = from_mile
        self.to_mile = to_mile
        super().__init__(
            f"No fuel station within range between mile {from_mile:.1f} and "
            f"mile {to_mile:.1f} of the route (gap of {gap_miles:.1f} mi "
            f"exceeds the {range_miles:.0f} mi vehicle range)."
        )
