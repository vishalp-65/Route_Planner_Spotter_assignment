"""Shared, framework-agnostic data types used across the service layer.

Keeping these as plain dataclasses (no Django imports) means the core
algorithms (matching, optimization) can be unit-tested in complete
isolation from the database and HTTP layers.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Coordinates:
    """A WGS-84 latitude/longitude pair."""

    latitude: float
    longitude: float
