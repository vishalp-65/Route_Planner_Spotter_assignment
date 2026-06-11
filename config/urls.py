"""URL configuration for the spotter_fuel project."""

from django.contrib import admin
from django.urls import include, path

urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/v1/", include("routing.api.urls")),
    path("", include("routing.urls")),
]
