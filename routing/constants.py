"""Domain-wide constants for the routing app.

Numeric trip assumptions (vehicle range, mpg, corridor width) are
configuration, not constants - see ``settings.FUEL_ROUTE_CONFIG``. This
module holds values that are either physical/geographic facts or fixed
reference data, independent of any deployment.
"""

# The 50 US states plus the District of Columbia. Used to scope the bundled
# fuel price dataset to the USA (the assignment is explicitly USA-only; the
# source CSV also contains ~620 Canadian rows that must be excluded).
US_STATE_CODES = frozenset(
    {
        "AL", "AK", "AZ", "AR", "CA", "CO", "CT", "DE", "FL", "GA", "HI", "ID", "IL", "IN", "IA",
        "KS", "KY", "LA", "ME", "MD", "MA", "MI", "MN", "MS", "MO", "MT", "NE", "NV", "NH", "NJ",
        "NM", "NY", "NC", "ND", "OH", "OK", "OR", "PA", "RI", "SC", "SD", "TN", "TX", "UT", "VT",
        "VA", "WA", "WV", "WI", "WY", "DC",
    }
)

# Mean Earth radius in miles, used for haversine distance calculations.
EARTH_RADIUS_MILES = 3958.8
