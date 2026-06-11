"""Views for non-API pages (the Leaflet map demo)."""

from __future__ import annotations

from django.views.generic import TemplateView


class RoutePlannerMapView(TemplateView):
    """Renders the Leaflet map demo page.

    The page itself contains no server-rendered route data - it calls
    ``POST /api/v1/routes/plan`` from JavaScript and draws the result.
    """

    template_name = "routing/map.html"
