"""Match fuel stations to a route polyline.

Pure-numpy implementation: every candidate station is projected onto its
closest point on the route polyline, producing a "mile marker" (distance
along the route from the origin) for stations within the configured
corridor width. No GIS stack (GeoDjango/PostGIS/scipy) is needed at this
data scale - a fully vectorized point-to-segment distance over a few
thousand stations and a few dozen polyline segments runs in single-digit
milliseconds.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

from routing.constants import EARTH_RADIUS_MILES
from routing.models import FuelStation
from routing.services.types import Coordinates

# Miles per degree of latitude (and of longitude at the equator), derived
# from the same Earth radius used for haversine so the two distance
# computations in this module are internally consistent.
MILES_PER_DEGREE = EARTH_RADIUS_MILES * math.pi / 180.0


@dataclass(frozen=True)
class StationOnRoute:
    """A fuel station matched to a point along the route."""

    station: FuelStation
    mile_marker: float
    distance_from_route_miles: float


def _haversine_miles(
    lat1: np.ndarray, lon1: np.ndarray, lat2: np.ndarray, lon2: np.ndarray
) -> np.ndarray:
    """Vectorized great-circle distance in miles."""
    lat1, lon1, lat2, lon2 = map(np.radians, (lat1, lon1, lat2, lon2))
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    a = np.sin(dlat / 2.0) ** 2 + np.cos(lat1) * np.cos(lat2) * np.sin(dlon / 2.0) ** 2
    return 2 * EARTH_RADIUS_MILES * np.arcsin(np.sqrt(np.clip(a, 0.0, 1.0)))


def _polyline_cumulative_distances(geometry: list[Coordinates]) -> tuple[np.ndarray, np.ndarray]:
    """Return (cumulative_distance_at_vertex, segment_lengths), both in miles."""
    lats = np.array([c.latitude for c in geometry])
    lons = np.array([c.longitude for c in geometry])
    seg_lengths = _haversine_miles(lats[:-1], lons[:-1], lats[1:], lons[1:])
    cumdist = np.concatenate(([0.0], np.cumsum(seg_lengths)))
    return cumdist, seg_lengths


def match_stations_to_route(
    geometry: list[Coordinates],
    total_distance_miles: float,
    stations: list[FuelStation],
    corridor_miles: float,
) -> list[StationOnRoute]:
    """Project geocoded stations onto the route and keep those within the corridor.

    Args:
        geometry: Ordered route polyline vertices (origin -> destination).
        total_distance_miles: The routing provider's reported road distance,
            used to rescale polyline-chord distances (which understate true
            road distance once curves are simplified to straight segments)
            so mile markers line up with the reported total.
        stations: Candidate stations. Must be pre-filtered to those with
            non-null coordinates.
        corridor_miles: Maximum allowed distance from the route polyline.

    Returns:
        Stations within ``corridor_miles`` of the route, sorted by
        ``mile_marker`` ascending. Each station appears at most once, at
        its globally closest point on the route.
    """
    stations = [s for s in stations if s.latitude is not None and s.longitude is not None]
    if len(geometry) < 2 or not stations:
        return []

    vertex_lats = np.array([c.latitude for c in geometry])
    vertex_lons = np.array([c.longitude for c in geometry])
    cumdist, seg_lengths = _polyline_cumulative_distances(geometry)
    polyline_length = cumdist[-1]
    # Align polyline-chord mile markers with the provider's reported total
    # road distance (simplified polylines straighten curves, so the sum of
    # chord lengths is consistently a bit shorter than the real route).
    scale = total_distance_miles / polyline_length if polyline_length > 0 else 1.0

    station_lats = np.array([s.latitude for s in stations])
    station_lons = np.array([s.longitude for s in stations])

    a_lat, b_lat = vertex_lats[:-1], vertex_lats[1:]
    a_lon, b_lon = vertex_lons[:-1], vertex_lons[1:]

    # Local equirectangular projection centered on each station (miles).
    # Accurate near the station; for far-away segments it may distort, but
    # the resulting distance is then clearly >> corridor_miles regardless.
    lon_scale = np.cos(np.radians(station_lats)) * MILES_PER_DEGREE  # (N,)

    ax = (a_lon[None, :] - station_lons[:, None]) * lon_scale[:, None]  # (N, M)
    ay = (a_lat[None, :] - station_lats[:, None]) * MILES_PER_DEGREE  # (N, M)
    bx = (b_lon[None, :] - station_lons[:, None]) * lon_scale[:, None]
    by = (b_lat[None, :] - station_lats[:, None]) * MILES_PER_DEGREE

    ab_x, ab_y = bx - ax, by - ay
    ab_len_sq = ab_x**2 + ab_y**2

    # Project the station (at the local origin) onto each segment, clamped
    # to the segment (t in [0, 1]).
    with np.errstate(divide="ignore", invalid="ignore"):
        t = -(ax * ab_x + ay * ab_y) / ab_len_sq
    t = np.where(ab_len_sq > 1e-12, t, 0.0)
    t = np.clip(t, 0.0, 1.0)

    closest_x = ax + t * ab_x
    closest_y = ay + t * ab_y
    dist_to_segment = np.sqrt(closest_x**2 + closest_y**2)  # (N, M)

    best_segment = np.argmin(dist_to_segment, axis=1)
    row_idx = np.arange(len(stations))
    best_distance = dist_to_segment[row_idx, best_segment]
    best_t = t[row_idx, best_segment]

    raw_mile_marker = cumdist[best_segment] + best_t * seg_lengths[best_segment]
    mile_marker = raw_mile_marker * scale

    matches = [
        StationOnRoute(
            station=station,
            mile_marker=float(mile_marker[i]),
            distance_from_route_miles=float(best_distance[i]),
        )
        for i, station in enumerate(stations)
        if best_distance[i] <= corridor_miles
    ]
    matches.sort(key=lambda m: m.mile_marker)
    return matches
