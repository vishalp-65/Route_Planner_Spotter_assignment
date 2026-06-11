"""Translates domain exceptions (``routing.exceptions``) into HTTP responses.

Wired up via ``REST_FRAMEWORK["EXCEPTION_HANDLER"]``. DRF's own exceptions
(serializer ``ValidationError``, ``Throttled``, etc.) are handled first by
the default handler and pass through unchanged.
"""

from __future__ import annotations

import logging

from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import exception_handler

from routing.exceptions import GeocodingError, InfeasibleRouteError, RoutingProviderError

logger = logging.getLogger("routing")


def fuel_route_exception_handler(exc, context):
    response = exception_handler(exc, context)
    if response is not None:
        return response

    if isinstance(exc, GeocodingError):
        return Response(
            {"error": str(exc), "location": exc.query},
            status=status.HTTP_422_UNPROCESSABLE_ENTITY,
        )

    if isinstance(exc, InfeasibleRouteError):
        return Response(
            {
                "error": str(exc),
                "gap_miles": round(exc.gap_miles, 1),
                "range_miles": exc.range_miles,
                "from_mile": round(exc.from_mile, 1),
                "to_mile": round(exc.to_mile, 1),
            },
            status=status.HTTP_422_UNPROCESSABLE_ENTITY,
        )

    if isinstance(exc, RoutingProviderError):
        logger.error("Routing provider error: %s", exc)
        return Response({"error": str(exc)}, status=status.HTTP_502_BAD_GATEWAY)

    return None
