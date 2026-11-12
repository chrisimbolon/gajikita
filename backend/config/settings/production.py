# =============================================================================
# === backend/config/settings/production.py ===
# =============================================================================
from decouple import config

from .base import *  # noqa: F401,F403

DEBUG = False

DATABASES = {
    "default": {
        "ENGINE":   "django.db.backends.postgresql",
        "NAME":     config("DB_NAME"),
        "USER":     config("DB_USER"),
        "PASSWORD": config("DB_PASSWORD"),
        "HOST":     config("DB_HOST", default="db"),
        "PORT":     config("DB_PORT", default="5432"),
    }
}

SECURE_SSL_REDIRECT       = True
SESSION_COOKIE_SECURE     = True
CSRF_COOKIE_SECURE        = True
SECURE_HSTS_SECONDS       = 31536000
SECURE_HSTS_INCLUDE_SUBDOMAINS = True

# These three were being written into .env by deploy.yml but never
# actually read anywhere — without them, Django can't correctly
# recognize requests coming through Caddy's TLS termination as
# secure, which combined with SECURE_SSL_REDIRECT above risks a real
# redirect loop, and CSRF_TRUSTED_ORIGINS being unset would reject
# real cross-origin POST requests (login, register) outright.
CSRF_TRUSTED_ORIGINS = config(
    "CSRF_TRUSTED_ORIGINS", default=""
).split(",") if config("CSRF_TRUSTED_ORIGINS", default="") else []

SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
USE_X_FORWARDED_HOST    = True

# Deploy kit (12 Nov 2026): with DEBUG off Django would otherwise only try to e-mail
# errors (no mail is configured), so a 500 left no trace. Now every warning and error,
# with its traceback, lands in `docker logs seegaji_backend`.
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {"plain": {"format": "{asctime} {levelname} {name}: {message}", "style": "{"}},
    "handlers": {"console": {"class": "logging.StreamHandler", "formatter": "plain"}},
    "root": {"handlers": ["console"], "level": "WARNING"},
    "loggers": {"django": {"handlers": ["console"], "level": "WARNING", "propagate": False}},
}
