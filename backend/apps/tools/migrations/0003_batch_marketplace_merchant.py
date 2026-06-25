"""Add marketplace, marketplace_order_id, marketplace_store FK, merchant FK,
delivery tracking fields, and updated status choices to RobuxCrateBatch.
"""
import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('tools', '0002_batch_idempotency_hardening'),
        ('integrations', '0001_initial'),
    ]

    operations = [
        # 1) Add marketplace fields
        migrations.AddField(
            model_name='robuxcratebatch',
            name='marketplace',
            field=models.CharField(
                choices=[('eldorado', 'Eldorado'), ('gameboost', 'GameBoost')],
                default='eldorado',
                max_length=20,
            ),
            preserve_default=False,
        ),
        migrations.AddField(
            model_name='robuxcratebatch',
            name='marketplace_order_id',
            field=models.CharField(default='', help_text='Order ID on the marketplace (e.g. Eldorado order ID)', max_length=100),
            preserve_default=False,
        ),
        migrations.AddField(
            model_name='robuxcratebatch',
            name='marketplace_store',
            field=models.ForeignKey(
                help_text='Which marketplace store/account to use for delivery',
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='robuxcrate_batches',
                to='integrations.integrationcredential',
            ),
        ),

        # 2) Add merchant FK
        migrations.AddField(
            model_name='robuxcratebatch',
            name='merchant',
            field=models.ForeignKey(
                help_text='Which RbxCrate merchant (API key) to use',
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='robuxcrate_batches',
                to='integrations.servicecredential',
            ),
        ),

        # 3) Add delivery tracking fields
        migrations.AddField(
            model_name='robuxcratebatch',
            name='delivery_attempted_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='robuxcratebatch',
            name='delivery_error',
            field=models.TextField(blank=True, default=''),
            preserve_default=False,
        ),

        # 4) Update batch status choices (add queued, error, cancelled; remove failed)
        migrations.AlterField(
            model_name='robuxcratebatch',
            name='status',
            field=models.CharField(
                choices=[
                    ('pending', 'Pending'),
                    ('queued', 'Queued'),
                    ('processing', 'Processing'),
                    ('completed', 'Completed'),
                    ('partial', 'Partial'),
                    ('error', 'Error'),
                    ('cancelled', 'Cancelled'),
                ],
                default='pending',
                max_length=20,
            ),
        ),
    ]
