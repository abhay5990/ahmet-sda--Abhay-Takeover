from django.db import models


class ResourceType(models.TextChoices):
    ORDERS = 'orders', 'Orders'
    ITEM_ORDERS = 'item_orders', 'Item Orders'
    HISTORICAL_ORDERS = 'historical_orders', 'Historical Orders'
    LISTINGS = 'listings', 'Listings'
    OWNED_PRODUCTS = 'owned_products', 'Owned Products'
    REVIEWS = 'reviews', 'Reviews'
    NOTIFICATIONS = 'notifications', 'Notifications'


class SyncMode(models.TextChoices):
    BACKFILL = 'backfill', 'Backfill'
    INCREMENTAL = 'incremental', 'Incremental'


class ParseStatus(models.TextChoices):
    PENDING = 'pending', 'Pending'
    PARSED = 'parsed', 'Parsed'
    FAILED = 'failed', 'Failed'
    SKIPPED = 'skipped', 'Skipped'  # payload unchanged since last parse


class CheckpointStatus(models.TextChoices):
    ACTIVE = 'active', 'Active'
    COMPLETED = 'completed', 'Completed'  # backfill finished
    STALE = 'stale', 'Stale'  # needs reset


class SyncPhase(models.TextChoices):
    FULL = 'full', 'Full'
    INGEST = 'ingest', 'Ingest Only'
    PROCESS = 'process', 'Process Only'


class SyncRunStatus(models.TextChoices):
    RUNNING = 'running', 'Running'
    COMPLETED = 'completed', 'Completed'
    FAILED = 'failed', 'Failed'
    CANCELLED = 'cancelled', 'Cancelled'


class SyncLogLevel(models.TextChoices):
    INFO = 'info', 'Info'
    WARNING = 'warning', 'Warning'
    ERROR = 'error', 'Error'
    SUCCESS = 'success', 'Success'
