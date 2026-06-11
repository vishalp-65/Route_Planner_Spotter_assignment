"""National-average fuel price.

Used by the optimizer to value the fuel a vehicle is assumed to start a
trip with (see ``routing.services.optimizer``).
"""

from __future__ import annotations

from django.core.cache import cache
from django.db.models import Avg

from routing.models import FuelStation

CACHE_KEY = "fuel_route:national_avg_price_per_gallon"
CACHE_TIMEOUT_SECONDS = 60 * 60 * 24


def get_national_average_price_per_gallon() -> float:
    """Average ``retail_price`` across all imported stations, cached for a
    day since it only changes when the station data is re-imported."""
    cached = cache.get(CACHE_KEY)
    if cached is not None:
        return cached

    average = FuelStation.objects.aggregate(avg=Avg("retail_price"))["avg"]
    value = float(average) if average is not None else 0.0
    cache.set(CACHE_KEY, value, CACHE_TIMEOUT_SECONDS)
    return value
