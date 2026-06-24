"""Add RobuxCrateBatch model, refactor RobuxCrateOrder to use batch FK,
add idempotency, UNKNOWN status, provider tracking fields.

Migrates existing orders by creating a batch for each one.
"""
import uuid

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


def create_batches_for_existing_orders(apps, schema_editor):
    """For each existing RobuxCrateOrder, create a wrapping RobuxCrateBatch."""
    Order = apps.get_model('tools', 'RobuxCrateOrder')
    Batch = apps.get_model('tools', 'RobuxCrateBatch')

    for order in Order.objects.all():
        batch = Batch.objects.create(
            client_request_id=uuid.uuid4(),
            created_by=order.created_by,
            roblox_username=order.roblox_username,
            roblox_user_id=order.roblox_user_id,
            place_id=order.place_id,
            place_name=order.place_name,
            robux_amount=order.robux_amount,
            quantity=1,
            status='completed',
        )
        order.batch_id = batch.id
        order.save(update_fields=['batch_id'])


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ('tools', '0001_initial'),
    ]

    operations = [
        # 1) Create RobuxCrateBatch table
        migrations.CreateModel(
            name='RobuxCrateBatch',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('client_request_id', models.UUIDField(unique=True, help_text='Idempotency key from client')),
                ('roblox_username', models.CharField(max_length=50)),
                ('roblox_user_id', models.BigIntegerField(blank=True, null=True)),
                ('place_id', models.BigIntegerField()),
                ('place_name', models.CharField(blank=True, max_length=200)),
                ('robux_amount', models.PositiveIntegerField()),
                ('quantity', models.PositiveSmallIntegerField(default=1)),
                ('status', models.CharField(
                    choices=[
                        ('pending', 'Pending'),
                        ('processing', 'Processing'),
                        ('completed', 'Completed'),
                        ('partial', 'Partial Success'),
                        ('failed', 'Failed'),
                    ],
                    default='pending',
                    max_length=20,
                )),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('created_by', models.ForeignKey(
                    null=True,
                    on_delete=django.db.models.deletion.SET_NULL,
                    related_name='robuxcrate_batches',
                    to=settings.AUTH_USER_MODEL,
                )),
            ],
            options={
                'ordering': ['-created_at'],
            },
        ),

        # 2) Add batch FK as nullable first
        migrations.AddField(
            model_name='robuxcrateorder',
            name='batch',
            field=models.ForeignKey(
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name='orders',
                to='tools.robuxcratebatch',
            ),
            preserve_default=False,
        ),

        # 3) Migrate existing orders → create batches
        migrations.RunPython(
            create_batches_for_existing_orders,
            migrations.RunPython.noop,
        ),

        # 4) Make batch non-nullable
        migrations.AlterField(
            model_name='robuxcrateorder',
            name='batch',
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.CASCADE,
                related_name='orders',
                to='tools.robuxcratebatch',
            ),
        ),

        # 5) Remove fields moved to batch (and unused rate)
        migrations.RemoveField(model_name='robuxcrateorder', name='roblox_username'),
        migrations.RemoveField(model_name='robuxcrateorder', name='roblox_user_id'),
        migrations.RemoveField(model_name='robuxcrateorder', name='place_id'),
        migrations.RemoveField(model_name='robuxcrateorder', name='place_name'),
        migrations.RemoveField(model_name='robuxcrateorder', name='robux_amount'),
        migrations.RemoveField(model_name='robuxcrateorder', name='rate'),

        # 6) Add new tracking fields
        migrations.AddField(
            model_name='robuxcrateorder',
            name='raw_provider_status',
            field=models.CharField(blank=True, max_length=50, default=''),
            preserve_default=False,
        ),
        migrations.AddField(
            model_name='robuxcrateorder',
            name='last_status_checked_at',
            field=models.DateTimeField(null=True, blank=True),
        ),

        # 7) Update status choices to include UNKNOWN
        migrations.AlterField(
            model_name='robuxcrateorder',
            name='status',
            field=models.CharField(
                choices=[
                    ('pending', 'Pending'),
                    ('queued', 'Queued'),
                    ('progress', 'In Progress'),
                    ('completed', 'Completed'),
                    ('error', 'Error'),
                    ('cancelled', 'Cancelled'),
                    ('unknown', 'Unknown'),
                ],
                default='pending',
                max_length=20,
            ),
        ),

        # 8) Add indexes
        migrations.AddIndex(
            model_name='robuxcrateorder',
            index=models.Index(fields=['status'], name='idx_rbxorder_status'),
        ),
        migrations.AddIndex(
            model_name='robuxcrateorder',
            index=models.Index(fields=['created_at'], name='idx_rbxorder_created'),
        ),
    ]
