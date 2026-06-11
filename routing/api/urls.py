"""URL routes for the routing JSON API (mounted under /api/v1/)."""

from django.urls import path

from routing.api.views import RoutePlanView

app_name = "routing_api"

urlpatterns = [
    path("routes/plan", RoutePlanView.as_view(), name="route-plan"),
]
