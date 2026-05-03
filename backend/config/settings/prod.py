"""Production settings."""

from .base import *

DEBUG = False

# Domain is the single source of truth — set DOMAIN in .env
_domain = config('DOMAIN', default='admin4gamers.com')

ALLOWED_HOSTS = config(
    'DJANGO_ALLOWED_HOSTS',
    default=f'{_domain},www.{_domain}',
    cast=lambda v: [s.strip() for s in v.split(',')],
)

CSRF_TRUSTED_ORIGINS = [
    f'https://{_domain}',
    f'https://www.{_domain}',
]

# Security
SECURE_SSL_REDIRECT = True
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
SECURE_BROWSER_XSS_FILTER = True
SECURE_CONTENT_TYPE_NOSNIFF = True
X_FRAME_OPTIONS = 'DENY'
SECURE_HSTS_SECONDS = 31536000
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_HSTS_PRELOAD = True

# Static files — Nginx serves /static/ directly, so no WhiteNoise middleware.
# CompressedManifestStaticFilesStorage creates hashed + pre-gzipped files
# which Nginx's gzip_static can serve without Django involvement.
STATICFILES_STORAGE = 'whitenoise.storage.CompressedManifestStaticFilesStorage'

# Logging
LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'formatters': {
        'verbose': {
            'format': '{levelname} {asctime} {module} {process:d} {thread:d} {message}',
            'style': '{',
        },
    },
    'handlers': {
        'file': {
            'level': 'INFO',
            'class': 'logging.FileHandler',
            'filename': BASE_DIR / 'logs' / 'django.log',
            'formatter': 'verbose',
        },
        'console': {
            'class': 'logging.StreamHandler',
            'formatter': 'verbose',
        },
    },
    'root': {
        'handlers': ['file', 'console'],
        'level': 'INFO',
    },
    'loggers': {
        'django': {
            'handlers': ['file', 'console'],
            'level': 'WARNING',
            'propagate': False,
        },
    },
}
