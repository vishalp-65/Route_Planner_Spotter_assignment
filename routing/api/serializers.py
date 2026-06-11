"""Request/response serializers for the routing JSON API."""

from __future__ import annotations

from rest_framework import serializers


class RoutePlanRequestSerializer(serializers.Serializer):
    """Validates the two free-form locations for ``POST /routes/plan``."""

    start = serializers.CharField(max_length=255, trim_whitespace=True)
    finish = serializers.CharField(max_length=255, trim_whitespace=True)

    def validate_start(self, value: str) -> str:
        return _require_non_blank(value, "start")

    def validate_finish(self, value: str) -> str:
        return _require_non_blank(value, "finish")


def _require_non_blank(value: str, field_name: str) -> str:
    if not value.strip():
        raise serializers.ValidationError(f"{field_name} must not be blank.")
    return value


class CoordinatesSerializer(serializers.Serializer):
    latitude = serializers.FloatField()
    longitude = serializers.FloatField()


class FuelStationSerializer(serializers.Serializer):
    opis_truckstop_id = serializers.IntegerField()
    name = serializers.CharField()
    address = serializers.CharField()
    city = serializers.CharField()
    state = serializers.CharField()
    latitude = serializers.FloatField()
    longitude = serializers.FloatField()


class FuelStopSerializer(serializers.Serializer):
    station = FuelStationSerializer()
    mile_marker = serializers.FloatField()
    gallons_purchased = serializers.FloatField()
    price_per_gallon = serializers.FloatField()
    cost = serializers.FloatField()

    def to_representation(self, instance):
        data = super().to_representation(instance)
        data["mile_marker"] = round(data["mile_marker"], 1)
        data["gallons_purchased"] = round(data["gallons_purchased"], 3)
        data["price_per_gallon"] = round(data["price_per_gallon"], 4)
        data["cost"] = round(data["cost"], 2)
        return data


class FuelPlanSerializer(serializers.Serializer):
    stops = FuelStopSerializer(many=True)
    initial_fuel_gallons = serializers.FloatField()
    initial_fuel_cost = serializers.FloatField()
    total_gallons = serializers.FloatField()
    total_cost = serializers.FloatField()

    def to_representation(self, instance):
        data = super().to_representation(instance)
        data["initial_fuel_gallons"] = round(data["initial_fuel_gallons"], 3)
        data["initial_fuel_cost"] = round(data["initial_fuel_cost"], 2)
        data["total_gallons"] = round(data["total_gallons"], 3)
        data["total_cost"] = round(data["total_cost"], 2)
        return data


class RoutePlanResponseSerializer(serializers.Serializer):
    origin = CoordinatesSerializer()
    destination = CoordinatesSerializer()
    distance_miles = serializers.FloatField()
    duration_seconds = serializers.FloatField()
    geometry = CoordinatesSerializer(many=True)
    fuel_plan = FuelPlanSerializer()

    def to_representation(self, instance):
        data = super().to_representation(instance)
        data["distance_miles"] = round(data["distance_miles"], 1)
        data["duration_seconds"] = round(data["duration_seconds"])
        return data
