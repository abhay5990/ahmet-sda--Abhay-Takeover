"""
Django settings for inventory_manager project.
Base settings shared across all environments.
"""

from pathlib import Path
import os
from decouple import config

# Build paths
BASE_DIR = Path(__file__).resolve().parent.parent.parent
ROOT_DIR = BASE_DIR.parent

# Security
SECRET_KEY = config('DJANGO_SECRET_KEY', default='django-insecure-change-this-in-production')
DEBUG = config('DJANGO_DEBUG', default=False, cast=bool)
ALLOWED_HOSTS = config('DJANGO_ALLOWED_HOSTS', default='localhost,127.0.0.1', cast=lambda v: [s.strip() for s in v.split(',')])

# Application definition
INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',

    # Third-party
    'django_apscheduler',

    # Local apps
    'apps.accounts',
    'apps.inventory',
    'apps.integrations',
    'apps.listings',
    'apps.orders',
    'apps.sync',
    'apps.dashboard',
    'apps.settings',
    'apps.posting',
    'apps.email_checker',
]

# APScheduler
APSCHEDULER_DATETIME_FORMAT = 'Y-m-d H:i:s'
APSCHEDULER_RUN_NOW_TIMEOUT = 600  # seconds
SCHEDULER_DEFAULT_INTERVAL = 5     # minutes

# Custom User Model
AUTH_USER_MODEL = 'accounts.User'
LOGIN_URL = '/accounts/login/'
LOGIN_REDIRECT_URL = '/'
LOGOUT_REDIRECT_URL = '/accounts/login/'

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'config.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [
            ROOT_DIR / 'frontend' / 'templates',
        ],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
                'apps.accounts.context_processors.user_role',
            ],
        },
    },
]

WSGI_APPLICATION = 'config.wsgi.application'

# Database — controlled by DB_ENGINE in .env
# sqlite3 → zero setup, file-based
# mysql    → production-ready, requires mysqlclient
_db_engine = config('DB_ENGINE', default='django.db.backends.sqlite3')

if 'sqlite3' in _db_engine:
    DATABASES = {
        'default': {
            'ENGINE': _db_engine,
            'NAME': BASE_DIR / config('DB_NAME', default='db.sqlite3'),
        }
    }
else:
    DATABASES = {
        'default': {
            'ENGINE': _db_engine,
            'NAME': config('DB_NAME', default='inventory_manager'),
            'USER': config('DB_USER', default='root'),
            'PASSWORD': config('DB_PASSWORD', default=''),
            'HOST': config('DB_HOST', default='localhost'),
            'PORT': config('DB_PORT', default='3306'),
            'CONN_MAX_AGE': 600,
            'OPTIONS': {
                'charset': 'utf8mb4',
                'init_command': "SET sql_mode='STRICT_TRANS_TABLES'",
            },
        }
    }

# Password validation
AUTH_PASSWORD_VALIDATORS = [
    {
        'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator',
    },
]

# Internationalization
LANGUAGE_CODE = 'en-us'
TIME_ZONE = 'UTC'
USE_I18N = True
USE_TZ = True

# Static files (CSS, JavaScript, Images)
STATIC_URL = '/static/'
STATIC_ROOT = BASE_DIR / 'staticfiles'
STATICFILES_DIRS = [
    ROOT_DIR / 'frontend' / 'static',
]

# Media files
MEDIA_URL = '/media/'
MEDIA_ROOT = ROOT_DIR / 'media'

# Default primary key field type
DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

# Credential Encryption (Fernet key for encrypting store credentials in DB)
CREDENTIAL_ENCRYPTION_KEY = config('CREDENTIAL_ENCRYPTION_KEY', default='')

# Provider credentials are stored in DB (IntegrationCredential model)
# No provider-specific API keys in settings
