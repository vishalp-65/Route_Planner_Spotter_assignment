"""Import and geocode fuel station prices from the bundled OPIS CSV.

This is the offline preprocessing step referenced throughout the routing
app: it runs once (and is safely re-runnable), turning the raw price list
into a geocoded ``FuelStation`` table that the API can query with zero
external calls at request time.

Pipeline:
    1. Read the source CSV, keep only rows for the 50 US states + DC
       (the source data also includes ~620 Canadian rows).
    2. The source data contains duplicate rows per station (repeated price
       observations). Group by ``OPIS Truckstop ID`` and collapse each
       group to a single record, averaging the price.
    3. Resolve each station's (city, state) to coordinates using a bundled
       offline US cities dataset (no network calls).
    4. Upsert everything into the ``FuelStation`` table in one bulk
       operation, keyed on ``opis_truckstop_id`` so the command is
       idempotent.

A small number of stations reference places absent from the cities
dataset (e.g. unincorporated communities); these are stored with null
coordinates and reported at the end so the gap is visible, never silent.
"""

import csv
from collections import defaultdict
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path
from typing import NamedTuple

from django.conf import settings
from django.core.management.base import BaseCommand, CommandParser

from routing.constants import US_STATE_CODES
from routing.models import FuelStation

DEFAULT_FUEL_CSV_PATH = Path(settings.BASE_DIR) / "routing" / "data" / "fuel_prices.csv"
DEFAULT_CITIES_CSV_PATH = Path(settings.BASE_DIR) / "routing" / "data" / "us_cities.csv"

PRICE_QUANTUM = Decimal("0.0001")


class StationRecord(NamedTuple):
    opis_truckstop_id: int
    name: str
    address: str
    city: str
    state: str
    rack_id: int | None
    retail_price: Decimal


CityLookup = dict[tuple[str, str], tuple[float, float]]


class Command(BaseCommand):
    help = (
        "Clean, deduplicate and geocode the fuel price CSV into the "
        "FuelStation table. Safe to re-run (upserts by OPIS Truckstop ID)."
    )

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument(
            "--csv-path",
            type=Path,
            default=DEFAULT_FUEL_CSV_PATH,
            help="Path to the source fuel prices CSV.",
        )
        parser.add_argument(
            "--cities-path",
            type=Path,
            default=DEFAULT_CITIES_CSV_PATH,
            help="Path to the offline US city/state -> lat,lng CSV.",
        )

    def handle(self, *args, **options) -> None:
        csv_path: Path = options["csv_path"]
        cities_path: Path = options["cities_path"]

        raw_rows = self._read_us_rows(csv_path)
        self.stdout.write(f"Read {len(raw_rows)} US rows from {csv_path.name}")

        stations = self._dedupe(raw_rows)
        self.stdout.write(
            f"Deduplicated to {len(stations)} unique stations "
            f"(by OPIS Truckstop ID, price averaged across duplicates)"
        )

        city_lookup = self._load_city_lookup(cities_path)
        self.stdout.write(f"Loaded {len(city_lookup)} city/state coordinate entries from {cities_path.name}")

        geocoded_count, unresolved = self._persist(stations, city_lookup)

        unresolved_count = len(unresolved)
        self.stdout.write(
            self.style.SUCCESS(
                f"Done. {geocoded_count}/{len(stations)} stations geocoded "
                f"({unresolved_count} unresolved)."
            )
        )
        if unresolved:
            self.stdout.write(
                self.style.WARNING(
                    "Stations with no coordinate match (kept with null lat/lng, "
                    "excluded from route matching):"
                )
            )
            for city, state, opis_id in unresolved:
                self.stdout.write(f"  - OPIS {opis_id}: {city}, {state}")

    @staticmethod
    def _read_us_rows(csv_path: Path) -> list[dict[str, str]]:
        with open(csv_path, newline="", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            return [row for row in reader if row["State"].strip().upper() in US_STATE_CODES]

    @staticmethod
    def _dedupe(rows: list[dict[str, str]]) -> list[StationRecord]:
        groups: dict[int, list[dict[str, str]]] = defaultdict(list)
        for row in rows:
            opis_id = int(row["OPIS Truckstop ID"].strip())
            groups[opis_id].append(row)

        stations = []
        for opis_id, group in groups.items():
            prices = [Decimal(row["Retail Price"].strip()) for row in group]
            avg_price = (sum(prices) / len(prices)).quantize(PRICE_QUANTUM, rounding=ROUND_HALF_UP)

            # Multiple rows for the same station occasionally use slightly
            # different name spellings/casings (e.g. "PILOT #123" vs
            # "PILOT TRAVEL CENTER #123"). Prefer the longest (most
            # descriptive), breaking ties alphabetically for determinism.
            name = sorted({row["Truckstop Name"].strip() for row in group}, key=lambda n: (-len(n), n))[0]

            first = group[0]
            rack_id_raw = first["Rack ID"].strip()
            stations.append(
                StationRecord(
                    opis_truckstop_id=opis_id,
                    name=name,
                    address=first["Address"].strip(),
                    city=first["City"].strip(),
                    state=first["State"].strip().upper(),
                    rack_id=int(rack_id_raw) if rack_id_raw else None,
                    retail_price=avg_price,
                )
            )
        return stations

    @staticmethod
    def _load_city_lookup(cities_path: Path) -> CityLookup:
        lookup: CityLookup = {}
        with open(cities_path, newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                key = (row["CITY"].strip().upper(), row["STATE_CODE"].strip().upper())
                # First match wins; collisions are different cities sharing
                # a name within the same state, which are rare and close
                # enough for ~5 mile corridor matching either way.
                lookup.setdefault(key, (float(row["LATITUDE"]), float(row["LONGITUDE"])))
        return lookup

    @staticmethod
    def _persist(
        stations: list[StationRecord], city_lookup: CityLookup
    ) -> tuple[int, list[tuple[str, str, int]]]:
        geocoded_count = 0
        unresolved: list[tuple[str, str, int]] = []
        objs = []

        for station in stations:
            coords = city_lookup.get((station.city.upper(), station.state))
            if coords:
                latitude, longitude = coords
                geocoded_count += 1
            else:
                latitude, longitude = None, None
                unresolved.append((station.city, station.state, station.opis_truckstop_id))

            objs.append(
                FuelStation(
                    opis_truckstop_id=station.opis_truckstop_id,
                    name=station.name,
                    address=station.address,
                    city=station.city,
                    state=station.state,
                    rack_id=station.rack_id,
                    retail_price=station.retail_price,
                    latitude=latitude,
                    longitude=longitude,
                )
            )

        FuelStation.objects.bulk_create(
            objs,
            update_conflicts=True,
            unique_fields=["opis_truckstop_id"],
            update_fields=[
                "name", "address", "city", "state", "rack_id",
                "retail_price", "latitude", "longitude",
            ],
            batch_size=1000,
        )
        return geocoded_count, unresolved
