"""Development settings: local SQLite, browsable API, verbose errors."""

from .base import *  # noqa: F401,F403
from .base import REST_FRAMEWORK

DEBUG = True

# Enable the browsable API in development for manual exploration.
REST_FRAMEWORK = {
    **REST_FRAMEWORK,
    "DEFAULT_RENDERER_CLASSES": [
        "rest_framework.renderers.JSONRenderer",
        "rest_framework.renderers.BrowsableAPIRenderer",
    ],
}
