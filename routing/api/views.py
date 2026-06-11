"""POST /api/v1/routes/plan - the core fuel route planning endpoint."""

from __future__ import annotations

import hashlib

from django.core.cache import cache
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView

from routing.api.serializers import RoutePlanRequestSerializer, RoutePlanResponseSerializer
from routing.services.orchestrator import RoutePlannerService

CACHE_KEY_PREFIX = "fuel_route:plan"


class RoutePlanView(APIView):
    """Plan a cost-optimal fuel route between two US locations.

    Identical ``(start, finish)`` requests are served from the ``default``
    cache, so repeats make no external geocoding/routing calls at all.
    """

    # Public, anonymous endpoint: no session/basic auth, so a browser
    # session that happens to be logged into /admin can't trigger
    # SessionAuthentication's CSRF enforcement on this POST.
    authentication_classes: list = []
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "route-plan"

    def post(self, request, *args, **kwargs):
        request_serializer = RoutePlanRequestSerializer(data=request.data)
        request_serializer.is_valid(raise_exception=True)
        start = request_serializer.validated_data["start"]
        finish = request_serializer.validated_data["finish"]

        cache_key = _cache_key(start, finish)
        cached = cache.get(cache_key)
        if cached is not None:
            return Response(cached)

        plan = RoutePlannerService().plan_route(start, finish)
        data = dict(RoutePlanResponseSerializer(plan).data)
        cache.set(cache_key, data)
        return Response(data)


def _cache_key(start: str, finish: str) -> str:
    normalized = f"{start.strip().lower()}|{finish.strip().lower()}"
    digest = hashlib.sha256(normalized.encode("utf-8")).hexdigest()
    return f"{CACHE_KEY_PREFIX}:{digest}"
