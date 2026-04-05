"""Development settings."""

from .base import *

DEBUG = True

# Development-specific apps
INSTALLED_APPS += [
    # 'debug_toolbar',  # Uncomment after installing django-debug-toolbar
    # 'django_extensions',
]

# Debug toolbar middleware (add after installing)
# MIDDLEWARE += ['debug_toolbar.middleware.DebugToolbarMiddleware']

# Debug toolbar config
INTERNAL_IPS = [
    '127.0.0.1',
    'localhost',
]

# Email backend (console for development)
EMAIL_BACKEND = 'django.core.mail.backends.console.EmailBackend'

# Logging
LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'handlers': {
        'console': {
            'class': 'logging.StreamHandler',
        },
    },
    'root': {
        'handlers': ['console'],
        'level': 'INFO',
    },
    'loggers': {
        'django': {
            'handlers': ['console'],
            'level': 'INFO',
            'propagate': False,
        },
        'apps': {
            'handlers': ['console'],
            'level': 'DEBUG',
            'propagate': False,
        },
    },
}
