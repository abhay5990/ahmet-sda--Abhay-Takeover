"""Seed default sync feature flags — all enabled by default."""

from django.db import migrations


_FLAGS = [
    ('sync.lzt', 'LZT owned products sync'),
    ('sync.offers', 'Offer sync (all marketplaces)'),
    ('sync.orders', 'Order sync (all marketplaces)'),
    ('sync.reconcile', 'Cross-platform reconciliation (offer removal after sale)'),
    ('sync.unlinked_notify', 'Unlinked order warning logs'),
    ('sync.eldorado_notifications', 'Eldorado notification → order status sync'),
    ('sync.review_monitor', 'Eldorado negative review → Telegram alerts'),
    ('sync.order_status_refresh', 'Periodic non-final order status refresh'),
    ('sync.pool_sweep', 'Offer pool auto-restock sweep'),
    ('sync.pause_expiring', 'Auto-pause expiring listings'),
]


def seed_flags(apps, schema_editor):
    SyncFeatureFlag = apps.get_model('sync', 'SyncFeatureFlag')
    for key, description in _FLAGS:
        SyncFeatureFlag.objects.get_or_create(
            key=key,
            defaults={'is_enabled': True, 'description': description},
        )


def remove_flags(apps, schema_editor):
    SyncFeatureFlag = apps.get_model('sync', 'SyncFeatureFlag')
    SyncFeatureFlag.objects.filter(key__in=[k for k, _ in _FLAGS]).delete()


class Migration(migrations.Migration):

    dependencies = [
        ('sync', '0005_sync_feature_flags'),
    ]

    operations = [
        migrations.RunPython(seed_flags, remove_flags),
    ]
