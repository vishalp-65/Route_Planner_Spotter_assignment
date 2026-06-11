"""
Base Django settings shared by all environments.

Environment-specific overrides live in development.py / production.py.
All values that vary between environments are read from the process
environment (optionally via a local .env file) so that no secrets or
deployment-specific values are hard-coded.
"""

import os
from pathlib import Path

from dotenv import load_dotenv

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
# config/settings/base.py -> config/settings -> config -> <project root>
BASE_DIR = Path(__file__).resolve().parent.parent.parent

load_dotenv(BASE_DIR / ".env")


# ---------------------------------------------------------------------------
# Core security settings
# ---------------------------------------------------------------------------
SECRET_KEY = os.environ.get(
    "DJANGO_SECRET_KEY",
    "django-insecure-dev-only-key-do-not-use-in-production",
)

DEBUG = os.environ.get("DJANGO_DEBUG", "True").lower() == "true"

ALLOWED_HOSTS = [
    host.strip()
    for host in os.environ.get("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1").split(",")
    if host.strip()
]


# ---------------------------------------------------------------------------
# Applications
# ---------------------------------------------------------------------------
INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "rest_framework",
    "routing",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"


# ---------------------------------------------------------------------------
# Database
# ---------------------------------------------------------------------------
# A read-heavy ~7k row reference table does not warrant Postgres/PostGIS;
# SQLite (file-based, zero external services) keeps the project trivial to
# run for review while remaining perfectly adequate for this dataset size.
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": os.environ.get("DJANGO_DB_PATH", str(BASE_DIR / "db.sqlite3")),
    }
}

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"


# ---------------------------------------------------------------------------
# Password validation
# ---------------------------------------------------------------------------
AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]


# ---------------------------------------------------------------------------
# Internationalization
# ---------------------------------------------------------------------------
LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True


# ---------------------------------------------------------------------------
# Static files
# ---------------------------------------------------------------------------
STATIC_URL = "static/"


# ---------------------------------------------------------------------------
# Caching
#
# - "default": short-lived in-memory cache for full route-plan API
#   responses, keyed on (start, finish). Repeated requests for the same
#   trip are served without any external API calls.
# - "geocode": file-based cache for geocoding results. Unlike locmem this
#   survives process restarts, so the (rate-limited) Nominatim fallback is
#   only ever paid once per location, ever.
# ---------------------------------------------------------------------------
CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
        "LOCATION": "route-plan-cache",
        "TIMEOUT": int(os.environ.get("ROUTE_CACHE_TIMEOUT_SECONDS", 60 * 60)),
    },
    "geocode": {
        "BACKEND": "django.core.cache.backends.filebased.FileBasedCache",
        "LOCATION": str(BASE_DIR / "var" / "geocode_cache"),
        "TIMEOUT": None,
    },
}


# ---------------------------------------------------------------------------
# Django REST Framework
# ---------------------------------------------------------------------------
REST_FRAMEWORK = {
    "DEFAULT_RENDERER_CLASSES": ["rest_framework.renderers.JSONRenderer"],
    "EXCEPTION_HANDLER": "routing.api.exceptions.fuel_route_exception_handler",
    "DEFAULT_THROTTLE_RATES": {
        "route-plan": os.environ.get("ROUTE_PLAN_THROTTLE_RATE", "60/minute"),
    },
}


# ---------------------------------------------------------------------------
# Fuel route planner domain configuration
#
# These map directly to the assignment's stated assumptions and are
# deliberately kept in one place, env-overridable, and passed explicitly
# into the (otherwise pure, settings-agnostic) optimizer.
# ---------------------------------------------------------------------------
FUEL_ROUTE_CONFIG = {
    # Assignment assumptions
    "VEHICLE_RANGE_MILES": float(os.environ.get("VEHICLE_RANGE_MILES", "500")),
    "VEHICLE_MPG": float(os.environ.get("VEHICLE_MPG", "10")),
    # How far (miles) a fuel station may be from the route polyline and
    # still be considered "on the route".
    "STATION_CORRIDOR_MILES": float(os.environ.get("STATION_CORRIDOR_MILES", "5")),
    # A later stop must be cheaper than the current one by more than this
    # (USD/gal) to be worth a detour; smaller differences are folded into
    # the next stop that clears the bar. See routing.services.optimizer.
    "MIN_PRICE_DIFFERENTIAL_PER_GALLON": float(
        os.environ.get("MIN_PRICE_DIFFERENTIAL_PER_GALLON", "0.05")
    ),
    # External services (free, keyless)
    "OSRM_BASE_URL": os.environ.get("OSRM_BASE_URL", "https://router.project-osrm.org"),
    "NOMINATIM_BASE_URL": os.environ.get(
        "NOMINATIM_BASE_URL", "https://nominatim.openstreetmap.org"
    ),
    "NOMINATIM_USER_AGENT": os.environ.get(
        "NOMINATIM_USER_AGENT",
        "spotter-fuel-route-planner/1.0 (backend take-home assignment)",
    ),
    "EXTERNAL_API_TIMEOUT_SECONDS": float(os.environ.get("EXTERNAL_API_TIMEOUT_SECONDS", "10")),
}


# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "simple": {
            "format": "[{asctime}] {levelname} {name}: {message}",
            "style": "{",
        },
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "formatter": "simple",
        },
    },
    "root": {
        "handlers": ["console"],
        "level": os.environ.get("DJANGO_LOG_LEVEL", "INFO"),
    },
    "loggers": {
        "django": {
            "handlers": ["console"],
            "level": os.environ.get("DJANGO_LOG_LEVEL", "INFO"),
            "propagate": False,
        },
        "routing": {
            "handlers": ["console"],
            "level": os.environ.get("DJANGO_LOG_LEVEL", "INFO"),
            "propagate": False,
        },
    },
}
