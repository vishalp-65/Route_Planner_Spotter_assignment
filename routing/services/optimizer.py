"""Cost-optimal fuel stop planning along a route.

Given stations matched to the route (see ``routing.services.matching``) and
the vehicle's tank range, this computes which stations to refuel at - and
how much to buy at each - to minimize total fuel spend for the trip.

Cost model
----------
The trip is assumed to consume exactly ``total_distance_miles / mpg``
gallons, all of which counts as "purchased" for this trip - there is no
free starting tank, since that would make short trips cost $0 and
under-represent the fuel actually used. Concretely, the route is bookended
with two virtual stops:

- An origin stop (mile 0) priced at ``national_avg_price_per_gallon``,
  standing in for "wherever the driver last filled up".
- A destination stop (mile ``total_distance_miles``) priced at $0, a sink
  that stops the vehicle from topping off more than it needs at the very
  end.

With the tank starting and ending empty (relative to these bookends), the
classic optimal greedy for the gas-station problem is applied: at the
current stop, buy just enough fuel to reach the *next* stop (real or
virtual) that is both reachable on a full tank and meaningfully cheaper
(see "Minimum price differential" below); if no such stop exists, fill the
tank to capacity. This guarantees ``total gallons purchased ==
total_distance_miles / mpg`` for every route - including short trips that
never need a "real" refuel, whose entire cost is the initial-fill gallons
(at ``national_avg_price_per_gallon``, possibly undercut by a cheap station
near the origin).

Minimum price differential
---------------------------
A later station only counts as "cheaper" if it undercuts the current price
by more than ``min_price_differential`` (``MIN_PRICE_DIFFERENTIAL_PER_GALLON``,
default $0.05/gal). Without this, a string of stations a few cents apart and
only a handful of miles from each other each become their own "stop", buying
a fraction of a gallon to inch ahead to the next slightly-cheaper station -
mathematically optimal, but not a real driver would ever do (or a dispatcher
would want listed). Requiring a real-world-meaningful saving collapses these
chains into one stop at the best price in the cluster, at the cost of a few
cents of theoretical optimality.

Co-located stations
--------------------
Several stations commonly match to the exact same ``mile_marker`` - e.g. a
cluster of truck stops at one interchange all project onto the same vertex
of the (simplified) route polyline. There is no detour between them, so
``plan_fuel_stops`` first collapses each such cluster down to its cheapest
station (see ``_dedupe_colocated_stations``). Without this step, a pricier
station could sit "in front of" its cheaper neighbor in the waypoint order
and - if the gap between the two is under ``min_price_differential`` - end
up making a large purchase at its own higher price instead of yielding to
the cheaper station right next to it.

Feasibility
-----------
If any two consecutive stops (including the origin/destination bookends)
are farther apart than ``vehicle_range_miles``, no strategy can bridge that
gap and ``InfeasibleRouteError`` is raised before any plan is computed. This
check is independent of ``min_price_differential`` - it always uses raw
distance.
"""

from __future__ import annotations

from dataclasses import dataclass

from routing.exceptions import InfeasibleRouteError
from routing.models import FuelStation
from routing.services.matching import StationOnRoute

# Purchases below this many gallons are floating-point noise from a station
# landing (almost) exactly at a "switch to the next stop" point - the
# driver has no real reason to stop there, so it is dropped from the plan.
_NEGLIGIBLE_GALLONS = 1e-6

# Stations whose mile markers differ by less than this are treated as the
# same point on the route - see "Co-located stations" above.
_COLOCATED_TOLERANCE_MILES = 1e-6

# Retail prices have 4 decimal places (see FuelStation.retail_price); price
# differences are rounded to the same precision before comparison so that
# float64 noise (e.g. 2.849 - 2.799 == 0.050000000000000044) can't push an
# exact-cent differential over ``min_price_differential``.
_PRICE_COMPARISON_DECIMALS = 4


@dataclass(frozen=True)
class FuelStop:
    """A planned refuel at a real station along the route."""

    station: FuelStation
    mile_marker: float
    gallons_purchased: float
    price_per_gallon: float
    cost: float


@dataclass(frozen=True)
class FuelPlan:
    """A complete cost-optimal fueling plan for a route.

    ``initial_fuel_*`` is the fuel the vehicle is assumed to start the trip
    with, valued at ``national_avg_price_per_gallon`` (see module
    docstring). ``stops`` are the real stations to refuel at along the way.
    ``total_*`` are the sums across both.
    """

    stops: list[FuelStop]
    initial_fuel_gallons: float
    initial_fuel_cost: float
    total_gallons: float
    total_cost: float


@dataclass(frozen=True)
class _Waypoint:
    """An internal fueling candidate: a real station or a virtual bookend."""

    mile_marker: float
    price_per_gallon: float
    station: FuelStation | None


def plan_fuel_stops(
    stations: list[StationOnRoute],
    total_distance_miles: float,
    vehicle_range_miles: float,
    mpg: float,
    national_avg_price_per_gallon: float,
    min_price_differential: float = 0.0,
) -> FuelPlan:
    """Compute the cost-minimizing fuel plan for a route.

    Args:
        stations: Candidate stations matched to the route (see
            ``match_stations_to_route``), sorted by ``mile_marker``
            ascending.
        total_distance_miles: Total road distance of the route.
        vehicle_range_miles: Maximum distance the vehicle can travel on a
            full tank.
        mpg: Vehicle fuel economy in miles per gallon.
        national_avg_price_per_gallon: Price used to value the fuel the
            vehicle is assumed to start the trip with.
        min_price_differential: A later waypoint must be cheaper than the
            current one by more than this (in dollars per gallon) to be
            treated as a worthwhile stop; otherwise it is skipped in favor
            of filling up now or continuing to the next stop that clears
            the bar. See "Minimum price differential" above. Defaults to
            ``0.0`` (any price decrease counts, matching the pure greedy).

    Returns:
        The cost-optimal ``FuelPlan``.

    Raises:
        InfeasibleRouteError: if any gap between consecutive stops (real or
            the origin/destination bookends) exceeds ``vehicle_range_miles``.
    """
    stations = _dedupe_colocated_stations(stations)

    waypoints = [_Waypoint(0.0, national_avg_price_per_gallon, None)]
    waypoints += [
        _Waypoint(s.mile_marker, float(s.station.retail_price), s.station) for s in stations
    ]
    waypoints.append(_Waypoint(total_distance_miles, 0.0, None))

    _check_feasible(waypoints, vehicle_range_miles)

    stops: list[FuelStop] = []
    initial_fuel_gallons = 0.0
    initial_fuel_cost = 0.0
    tank_miles = 0.0  # fuel currently in tank, expressed as miles of range

    for i in range(len(waypoints) - 1):
        current = waypoints[i]
        next_waypoint = waypoints[i + 1]

        target_mile = _next_cheaper_within_range(
            waypoints, i, vehicle_range_miles, min_price_differential
        )
        miles_to_buy = max(0.0, (target_mile - current.mile_marker) - tank_miles)
        gallons = miles_to_buy / mpg
        cost = gallons * current.price_per_gallon

        if i == 0:
            initial_fuel_gallons = gallons
            initial_fuel_cost = cost
        elif gallons > _NEGLIGIBLE_GALLONS:
            stops.append(
                FuelStop(
                    station=current.station,
                    mile_marker=current.mile_marker,
                    gallons_purchased=gallons,
                    price_per_gallon=current.price_per_gallon,
                    cost=cost,
                )
            )

        tank_miles += miles_to_buy - (next_waypoint.mile_marker - current.mile_marker)

    total_gallons = initial_fuel_gallons + sum(stop.gallons_purchased for stop in stops)
    total_cost = initial_fuel_cost + sum(stop.cost for stop in stops)
    return FuelPlan(
        stops=stops,
        initial_fuel_gallons=initial_fuel_gallons,
        initial_fuel_cost=initial_fuel_cost,
        total_gallons=total_gallons,
        total_cost=total_cost,
    )


def _dedupe_colocated_stations(stations: list[StationOnRoute]) -> list[StationOnRoute]:
    """Collapse stations at (effectively) the same point on the route down
    to the cheapest one - see "Co-located stations" above.

    Assumes ``stations`` is sorted by ``mile_marker`` ascending, as
    documented on ``plan_fuel_stops``.
    """
    deduped: list[StationOnRoute] = []
    for candidate in stations:
        if deduped and candidate.mile_marker - deduped[-1].mile_marker < _COLOCATED_TOLERANCE_MILES:
            if candidate.station.retail_price < deduped[-1].station.retail_price:
                deduped[-1] = candidate
        else:
            deduped.append(candidate)
    return deduped


def _check_feasible(waypoints: list[_Waypoint], vehicle_range_miles: float) -> None:
    for current, nxt in zip(waypoints, waypoints[1:]):
        gap = nxt.mile_marker - current.mile_marker
        if gap > vehicle_range_miles:
            raise InfeasibleRouteError(
                gap_miles=gap,
                range_miles=vehicle_range_miles,
                from_mile=current.mile_marker,
                to_mile=nxt.mile_marker,
            )


def _next_cheaper_within_range(
    waypoints: list[_Waypoint], index: int, vehicle_range_miles: float, min_price_differential: float
) -> float:
    """Mile marker of the nearest later waypoint that is both reachable from
    ``waypoints[index]`` on a full tank and cheaper than it by more than
    ``min_price_differential``.

    Returns ``waypoints[index].mile_marker + vehicle_range_miles`` (i.e.
    "fill to full") if no such waypoint exists.
    """
    current = waypoints[index]
    for later in waypoints[index + 1 :]:
        if later.mile_marker - current.mile_marker > vehicle_range_miles:
            break
        differential = round(current.price_per_gallon - later.price_per_gallon, _PRICE_COMPARISON_DECIMALS)
        if differential > min_price_differential:
            return later.mile_marker
    return current.mile_marker + vehicle_range_miles
