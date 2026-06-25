"""Simplify status choices: remove PARTIAL from batch, remove PROGRESS from order.

PARTIAL batch status → replaced by PROCESSING (scheduler retries delivery).
PROGRESS order status → merged into QUEUED (no functional difference).

Existing rows with 'partial' are migrated to 'processing'.
Existing rows with 'progress' are migrated to 'queued'.
"""
from django.db import migrations, models


def migrate_statuses_forward(apps, schema_editor):
    RobuxCrateBatch = apps.get_model('tools', 'RobuxCrateBatch')
    RobuxCrateOrder = apps.get_model('tools', 'RobuxCrateOrder')

    RobuxCrateBatch.objects.filter(status='partial').update(status='processing')
    RobuxCrateOrder.objects.filter(status='progress').update(status='queued')


class Migration(migrations.Migration):

    dependencies = [
        ('tools', '0003_batch_marketplace_merchant'),
    ]

    operations = [
        # 1) Data migration: convert existing partial/progress rows
        migrations.RunPython(migrate_statuses_forward, migrations.RunPython.noop),

        # 2) Update batch status choices (remove partial)
        migrations.AlterField(
            model_name='robuxcratebatch',
            name='status',
            field=models.CharField(
                choices=[
                    ('pending', 'Pending'),
                    ('queued', 'Queued'),
                    ('processing', 'Processing'),
                    ('completed', 'Completed'),
                    ('error', 'Error'),
                    ('cancelled', 'Cancelled'),
                ],
                default='pending',
                max_length=20,
            ),
        ),

        # 3) Update order status choices (remove progress)
        migrations.AlterField(
            model_name='robuxcrateorder',
            name='status',
            field=models.CharField(
                choices=[
                    ('pending', 'Pending'),
                    ('queued', 'Queued'),
                    ('completed', 'Completed'),
                    ('error', 'Error'),
                    ('cancelled', 'Cancelled'),
                    ('unknown', 'Unknown'),
                ],
                default='pending',
                max_length=20,
            ),
        ),
    ]
