# =============================================================================
# === backend/config/settings/local.py ===
# =============================================================================
from decouple import config

from .base import *  # noqa: F401,F403

DEBUG = True

DATABASES = {
    "default": {
        "ENGINE":   "django.db.backends.postgresql",
        "NAME":     config("DB_NAME", default="gajikita"),
        "USER":     config("DB_USER", default="gajikita"),
        "PASSWORD": config("DB_PASSWORD", default="gajikita"),
        "HOST":     config("DB_HOST", default="localhost"),
        "PORT":     config("DB_PORT", default="5432"),
    }
}
