"""
Data migration: auto-create CleanerConfig for every existing source
IntegrationAccount (lzt, eldorado) that doesn't already have one.

This ensures that accounts created before the auto-create logic was added
to create_dropship_config() are properly covered.
"""
from django.db import migrations


SOURCE_PROVIDERS = ('lzt', 'eldorado')


def backfill_cleaner_configs(apps, schema_editor):
    IntegrationAccount = apps.get_model('integrations', 'IntegrationAccount')
    CleanerConfig = apps.get_model('posting', 'CleanerConfig')

    for account in IntegrationAccount.objects.filter(provider__in=SOURCE_PROVIDERS):
        CleanerConfig.objects.get_or_create(
            source_account=account,
            defaults={'enabled': True, 'cycle_interval': 600},
        )


def reverse_migration(apps, schema_editor):
    # No-op: we don't want to delete CleanerConfigs on reverse
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('posting', '0028_add_seller_username_to_target_url'),
        ('integrations', '0010_add_roblox_service_type'),
    ]

    operations = [
        migrations.RunPython(backfill_cleaner_configs, reverse_migration),
    ]
