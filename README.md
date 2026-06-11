# Fuel Route Planner

This is my submission for the "Remote Backend Django Engineer - AI & Algorithmic
Systems" take-home. The brief, boiled down: take a start and a finish location
anywhere in the US, plan a route between them, and figure out where the driver
should stop for fuel along the way so the trip costs as little as possible -
then report the total fuel bill, assuming a 500-mile tank range and 10 mpg.

The fuel prices come straight from the OPIS CSV that was attached to the
assignment (`routing/data/fuel_prices.csv`, ~8,150 rows / ~6,600 unique truck
stops). For routing and maps, the brief said to "find a free API yourself," so
I went with [OSRM](http://project-osrm.org/)'s public demo server for the
route itself and [OpenStreetMap Nominatim](https://nominatim.openstreetmap.org/)
to turn "Los Angeles, CA" into coordinates - both are free and don't need an
API key, which matters for a take-home that someone else needs to run without
signing up for anything.

It's a Django 6 / DRF project with one real endpoint
(`POST /api/v1/routes/plan`) plus a small Leaflet page so you can actually
_see_ the route and stops on a map instead of squinting at JSON.

## Getting it running

You'll need Python 3.12+. From the project root:

```powershell
# 1. Create and activate a virtual environment
python -m venv venv
.\venv\Scripts\activate

# 2. Install dependencies
pip install -r requirements.txt

# 3. Copy the env file (the defaults are fine for local dev)
copy .env.example .env

# 4. Apply migrations
python manage.py migrate

# 5. Load the fuel price data
python manage.py import_fuel_stations

# 6. Run it
python manage.py runserver
```

The map demo is at `http://127.0.0.1:8000/`, and the API is at
`http://127.0.0.1:8000/api/v1/routes/plan`.

That import command in step 5 is worth a word, because it's doing more than a
plain CSV load. The raw OPIS file has no coordinates - just truck stop name,
address, city and state. So the command de-duplicates the ~8,150 price rows
down to ~6,600 distinct stations and geocodes each one against a bundled table
of US city centroids (`routing/data/us_cities.csv`, sourced from
[kelvins/US-Cities-Database](https://github.com/kelvins/US-Cities-Database)).
That gets ~99.8% of stations a usable lat/lon (6,614 of 6,626) without making
a single network call, and it runs in a couple of seconds. The handful that
don't match just get skipped - city names in the OPIS file occasionally don't
line up cleanly with the reference table, and it wasn't worth chasing the last
0.2% with a live geocoder for every row.

## Calling the API

Send a `POST` to `/api/v1/routes/plan` with two free-form locations:

```json
{
  "start": "Los Angeles, CA",
  "finish": "Chicago, IL"
}
```

You can put basically anything Nominatim can resolve in there - a city and
state, a full address, a landmark name. You'll get back something like this
(trimmed for readability - the real `geometry` array has dozens of points):

```json
{
  "origin": { "latitude": 34.05, "longitude": -118.24 },
  "destination": { "latitude": 41.88, "longitude": -87.63 },
  "distance_miles": 2018.1,
  "duration_seconds": 127584,
  "geometry": [
    { "latitude": 34.05, "longitude": -118.24 },
    { "latitude": 34.06, "longitude": -118.1 }
  ],
  "fuel_plan": {
    "stops": [
      {
        "station": {
          "opis_truckstop_id": 12345,
          "name": "PILOT TRAVEL CENTER #123",
          "address": "123 Main St",
          "city": "Kingman",
          "state": "AZ",
          "latitude": 35.19,
          "longitude": -114.05
        },
        "mile_marker": 268.4,
        "gallons_purchased": 50.0,
        "price_per_gallon": 2.899,
        "cost": 144.95
      }
    ],
    "initial_fuel_gallons": 26.844,
    "initial_fuel_cost": 91.74,
    "total_gallons": 201.815,
    "total_cost": 633.81
  }
}
```

`geometry` is the route polyline, ready to hand straight to a mapping library.
`fuel_plan.stops` is the ordered list of truck stops to pull into, each with
the mile marker (distance from the start), how many gallons to buy, the price
there, and the cost. `fuel_plan.total_cost` is the number the assignment asks
for - the full fuel bill for the trip - and `total_gallons` will always equal
`distance_miles / 10`, which is a nice sanity check that the math is internally
consistent (more on why in the next section).

If you send the same `start`/`finish` pair again (case and whitespace don't
matter), you get the cached response back - no geocoding, no routing call,
just a dict lookup. That's deliberate: see "keeping the API calls down" below.

A few things can go wrong, and I tried to make the responses for each
reasonably specific rather than a generic 500:

- Missing or blank `start`/`finish` -> `400`, standard DRF field errors.
- A location Nominatim can't resolve -> `422`, with an `error` message and
  the offending `location`.
- A route where two consecutive points (or the start/end and the nearest
  usable station) are more than 500 miles apart, with nothing to bridge the
  gap -> `422`, with `gap_miles`, `range_miles`, `from_mile` and `to_mile` so
  you can see exactly where the trip becomes infeasible.
- OSRM itself failing or timing out -> `502`.
- Too many requests -> `429` (60/minute by default, see configuration below).

## The map page

`GET /` is a single page with a form on the left and a Leaflet map on the
right. Type in a start and finish, hit "Plan Route," and it just calls the API
above from JavaScript and draws the result: the route as a blue line, green/red
pins for the start and finish, and numbered amber pins for each fuel stop
(click one for the station name, address, gallons, price and cost). The
sidebar also fills in with a trip summary - distance, drive time, total fuel
cost, total gallons - and a list of the stops in order. I built this mostly so
I could sanity-check the routing and fuel-stop logic visually while developing,
but it doubles as a nice demo.

## How the fuel-stop planning actually works

This is the part of the assignment with the most room for interpretation, so
here's the reasoning.

First, every fuel station in the database gets projected onto the route line.
I treat the route as a sequence of line segments and, for each station,
compute the distance to the nearest segment (vectorized with numpy, since
there are ~6,600 stations and doing this in a Python loop would be painfully
slow). Anything within 5 miles of the route (`STATION_CORRIDOR_MILES`) is kept
and tagged with a "mile marker" - how far along the route it sits, measured
from the origin.

Then comes the actual optimization, which is the classic "gas station problem"
greedy algorithm with one twist. The twist is about the start of the trip: the
vehicle presumably already has _some_ fuel in the tank when the trip begins -
the assignment doesn't say how much, and there's no way to know. Rather than
guess, I add a **virtual stop at mile 0**, priced at the national average price
per gallon, representing "wherever the driver last filled up." I also add a
**virtual stop at the destination, priced at $0**. That second one is just a
bookkeeping trick - it gives the algorithm a "free" place to dump exactly the
fuel needed to finish the trip, which guarantees the total gallons purchased
across the whole plan always works out to exactly `distance_miles / 10`. Without
it, the optimizer could leave an arbitrary amount of fuel in the tank at the
end, and "total money spent on fuel" would depend on that arbitrary leftover.

With those two bookends in place, the algorithm walks the route from start to
finish. At each stop, it looks at every station reachable within 500 miles
(`VEHICLE_RANGE_MILES`). If any of them is _strictly cheaper_ than the current
stop, it buys just enough fuel to reach the cheapest such stop - no more,
because topping off here would mean carrying expensive fuel further than it
needs to. If nothing cheaper is reachable, it fills the tank, since this is the
best price available for a while and the tank has room. This greedy rule is
provably optimal for this problem: you never pass up cheap fuel you'll need,
and you never buy more expensive fuel than necessary.

If at any point the gap to the next stop - including the bookends - is wider
than 500 miles, the trip genuinely can't be done with this vehicle, and the
API returns the `422` described above instead of pretending a plan exists.

A real example from testing: LA to Chicago is about 2,018 miles. The optimizer
picked 11 stops, started with ~26.8 gallons already "in the tank" (at the
national average price, ~$91.74), and the whole trip - 201.8 gallons total -
came to $633.81.

## Keeping the external API calls down

The assignment specifically asks for the route/map API to be called as little
as possible - one call ideally, two or three acceptable. Here's how that shakes
out in practice:

- **OSRM (routing): exactly one call per request**, full stop. One request
  returns the simplified route geometry _and_ the total distance, so there's
  never a reason to call it twice.
- **Nominatim (geocoding): up to two calls** - one for `start`, one for
  `finish` - but only on a cache miss. Geocoding results are cached to disk
  forever, since "Los Angeles, CA" is always going to resolve to the same
  coordinates. In practice, after the first time someone plans a route between
  two cities, neither city needs to be geocoded again.
- **On a repeat `(start, finish)` request, zero external calls happen at all** -
  the whole response is cached for an hour (`ROUTE_CACHE_TIMEOUT_SECONDS`) and
  served straight from memory.

So worst case it's 1 OSRM call + 2 Nominatim calls (3 total, within the
"two or three acceptable" range), and the common case - repeat lookups, or
either endpoint already geocoded - is fewer. This also happens to be why the
API is fast: a cold request to a cross-country route comes back in around a
second, and a cached one comes back in tens of milliseconds.

## Configuration

Everything tunable lives in `.env` (copy `.env.example` to get started):

| Variable                      | Default                               | What it does                                           |
| ----------------------------- | ------------------------------------- | ------------------------------------------------------ |
| `VEHICLE_RANGE_MILES`         | `500`                                 | Max distance on a full tank                            |
| `VEHICLE_MPG`                 | `10`                                  | Fuel economy used for the cost calculation             |
| `STATION_CORRIDOR_MILES`      | `5`                                   | How far off the route a station can be and still count |
| `OSRM_BASE_URL`               | `https://router.project-osrm.org`     | Routing server                                         |
| `NOMINATIM_BASE_URL`          | `https://nominatim.openstreetmap.org` | Geocoding server                                       |
| `ROUTE_CACHE_TIMEOUT_SECONDS` | `3600`                                | How long a route plan stays cached                     |
| `ROUTE_PLAN_THROTTLE_RATE`    | `60/minute`                           | Per-client rate limit on the endpoint                  |

The first two are the assignment's stated assumptions (500 mi range, 10 mpg),
but I made them configurable rather than hardcoded - it's the kind of thing
that's trivial to do up front and saves someone a code change later if those
assumptions turn out to be per-vehicle rather than fixed.

## How the code is laid out

```
config/                 Django settings, root URLs, WSGI/ASGI
routing/
  api/                  DRF serializers, the view, urls, exception handler
  data/                 Bundled CSVs (fuel prices, US city coordinates)
  management/commands/  import_fuel_stations
  migrations/
  services/             The actual logic, kept independent of Django/DRF
    geocoding.py          Nominatim client (GeocodingProvider)
    routing_provider.py   OSRM client (RoutingProvider)
    matching.py           Projects stations onto the route
    optimizer.py          The fuel-stop algorithm described above
    pricing.py             National-average price lookup (cached)
    orchestrator.py        Wires the above together (RoutePlannerService)
  models.py             FuelStation
  urls.py / views.py    The map demo page
templates/routing/      map.html
```

The reason `services/` is split out and kept Django-light is mostly so the
pieces can be reasoned about (and replaced) independently - `geocoding.py` and
`routing_provider.py` are written against small abstract base classes
(`GeocodingProvider`, `RoutingProvider`), and `RoutePlannerService` takes its
dependencies through its constructor. If OSRM's demo server ever goes down or
rate-limits hard, swapping in a different routing provider means writing one
new class, not touching the view or the optimizer.

## Data sources & credit

- **Fuel prices** (`routing/data/fuel_prices.csv`) - the OPIS dataset provided
  with the assignment.
- **US city coordinates** (`routing/data/us_cities.csv`) -
  [kelvins/US-Cities-Database](https://github.com/kelvins/US-Cities-Database)
  (MIT License, Copyright (c) 2017 Kelvin S. do Prado), used to geocode the
  fuel stations offline.
- **Routing** - [OSRM](http://project-osrm.org/) public demo server, free and
  keyless.
- **Geocoding** - [OpenStreetMap Nominatim](https://nominatim.openstreetmap.org/),
  used within its [usage policy](https://operations.osmfoundation.org/policies/nominatim/)
  (results cached indefinitely, so each distinct location is only ever looked
  up once).

## What I'd look at next with more time

A few things I'm aware of but didn't think were worth the time for a 3-day
take-home:

- The ~12 stations that don't geocode (out of 6,626) are silently skipped
  during import. They're a rounding error against 6,614 matched stations, but
  a production version would probably log them somewhere so a human can fix
  the source data.
- OSRM's public server is great for development but isn't meant for production
  traffic - it's rate-limited and has no uptime guarantee. The
  `RoutingProvider` abstraction means swapping to a self-hosted OSRM instance
  or a paid provider (Mapbox, Google) would be a one-file change.
- Right now the cache is Django's in-memory `LocMemCache`, which is fine for a
  single dev server but won't share state across multiple workers/processes -
  Redis would be the obvious next step for anything resembling production.
- The optimizer assumes a station's posted price is current. Real fuel prices
  drift daily; if this were a live service, refreshing the price data on a
  schedule (rather than a one-time import) would matter a lot more than it
  does for a take-home using a static CSV.
