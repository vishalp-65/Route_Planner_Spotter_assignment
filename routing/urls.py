"""URL routes for non-API pages (e.g. the Leaflet map demo)."""

from django.urls import path

from routing.views import RoutePlannerMapView

app_name = "routing"

urlpatterns = [
    path("", RoutePlannerMapView.as_view(), name="map"),
]
