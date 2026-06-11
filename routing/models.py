from django.db import models


class FuelStation(models.Model):
    """A truck-stop fuel price observation from the bundled OPIS dataset.

    ``latitude``/``longitude`` are populated at import time by resolving
    ``city``/``state`` against a bundled offline US cities dataset (see
    ``import_fuel_stations``). A small fraction of stations reference
    places not present in that dataset (e.g. unincorporated areas); these
    are kept with null coordinates for transparency but are excluded from
    route matching, which requires coordinates.
    """

    opis_truckstop_id = models.PositiveIntegerField(
        unique=True,
        db_index=True,
        help_text="Unique station identifier from the source OPIS dataset.",
    )
    name = models.CharField(max_length=255)
    address = models.CharField(max_length=255)
    city = models.CharField(max_length=100)
    state = models.CharField(max_length=2, db_index=True)
    rack_id = models.PositiveIntegerField(null=True, blank=True)
    retail_price = models.DecimalField(
        max_digits=6,
        decimal_places=4,
        help_text="Retail price per gallon in USD, averaged across duplicate "
        "observations for this station in the source dataset.",
    )
    latitude = models.FloatField(null=True, blank=True, db_index=True)
    longitude = models.FloatField(null=True, blank=True, db_index=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["state", "city", "name"]
        indexes = [
            models.Index(fields=["latitude", "longitude"], name="fuelstation_lat_lng_idx"),
        ]

    def __str__(self) -> str:
        return f"{self.name} ({self.city}, {self.state}) - ${self.retail_price}/gal"

    @property
    def is_geocoded(self) -> bool:
        return self.latitude is not None and self.longitude is not None
