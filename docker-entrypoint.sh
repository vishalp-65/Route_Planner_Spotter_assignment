#!/bin/bash
set -e

echo "Running database migrations..."
python manage.py migrate

echo "Importing fuel stations data (this will skip safely if already imported)..."
python manage.py import_fuel_stations

echo "Starting application..."
exec "$@"
