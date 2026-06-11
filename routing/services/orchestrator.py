"""Top-level orchestration: turns a (origin, destination) pair into a
complete route + cost-optimal fuel plan.

This is the only service that talks to Django (settings, ORM) and wires
the other services together. Each step's failure mode maps to one of the
domain exceptions in ``routing.exceptions``, which
``routing.api.exceptions.fuel_route_exception_handler`` translates to HTTP
responses.
"""

from __future__ import annotations

from dataclasses import dataclass

from django.conf import settings

from routing.models import FuelStation
from routing.services.geocoding import GeocodingProvider
from routing.services.matching import match_stations_to_route
from routing.services.optimizer import FuelPlan, plan_fuel_stops
from routing.services.pricing import get_national_average_price_per_gallon
from routing.services.providers import get_geocoding_provider, get_routing_provider
from routing.services.routing_provider import RoutingProvider
from routing.services.types import Coordinates


@dataclass(frozen=True)
class RoutePlan:
    """A complete route plus its cost-optimal fuel plan."""

    origin: Coordinates
    destination: Coordinates
    distance_miles: float
    duration_seconds: float
    geometry: list[Coordinates]
    fuel_plan: FuelPlan


class RoutePlannerService:
    """Coordinates geocoding, routing, station matching, and fuel planning.

    Depends only on the ``GeocodingProvider`` / ``RoutingProvider``
    abstractions (constructor-injected, defaulting to the configured
    providers via ``routing.services.providers``), so it can be tested with
    fakes that make no network calls.
    """

    def __init__(
        self,
        geocoding_provider: GeocodingProvider | None = None,
        routing_provider: RoutingProvider | None = None,
    ):
        self.geocoding_provider = geocoding_provider or get_geocoding_provider()
        self.routing_provider = routing_provider or get_routing_provider()

    def plan_route(self, origin: str, destination: str) -> RoutePlan:
        """Build a full route + fuel plan from two free-form locations.

        Raises:
            GeocodingError: if either location cannot be resolved.
            RoutingProviderError: if no driving route can be found.
            InfeasibleRouteError: if the route has a gap between fuel stops
                (including its endpoints) wider than the vehicle's range.
        """
        config = settings.FUEL_ROUTE_CONFIG

        origin_coords = self.geocoding_provider.geocode(origin)
        destination_coords = self.geocoding_provider.geocode(destination)
        route = self.routing_provider.get_route(origin_coords, destination_coords)

        candidates = list(
            FuelStation.objects.exclude(latitude__isnull=True).exclude(longitude__isnull=True)
        )
        stations_on_route = match_stations_to_route(
            geometry=route.geometry,
            total_distance_miles=route.distance_miles,
            stations=candidates,
            corridor_miles=config["STATION_CORRIDOR_MILES"],
        )

        fuel_plan = plan_fuel_stops(
            stations=stations_on_route,
            total_distance_miles=route.distance_miles,
            vehicle_range_miles=config["VEHICLE_RANGE_MILES"],
            mpg=config["VEHICLE_MPG"],
            national_avg_price_per_gallon=get_national_average_price_per_gallon(),
        )

        return RoutePlan(
            origin=origin_coords,
            destination=destination_coords,
            distance_miles=route.distance_miles,
            duration_seconds=route.duration_seconds,
            geometry=route.geometry,
            fuel_plan=fuel_plan,
        )
