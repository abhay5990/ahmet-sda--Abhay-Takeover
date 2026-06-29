"""Add PoolDispatchReservation + RESERVED status for new-offer dispatch.

- Adds PoolDispatchReservation model (group-level reservation for creating
  a brand-new PoolOffer from a pool).
- Adds OfferPoolItemStatus.RESERVED choice.
- Adds OfferPoolItem.reservation FK (nullable).
- Drops pending_pool_item_unassigned constraint, replaces with:
    pending_item_unassigned   (PENDING -> pool_offer IS NULL AND reservation IS NULL)
    reserved_item_no_pool_offer (RESERVED -> pool_offer IS NULL)
    reserved_item_has_reservation (RESERVED -> reservation IS NOT NULL)
- Adds pool_item_reservation_idx index.
"""

import uuid

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('integrations', '0001_initial'),
        ('posting', '0026_dropship_url_stats_v2'),
    ]

    operations = [
        # 1. Create PoolDispatchReservation
        migrations.CreateModel(
            name='PoolDispatchReservation',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('token', models.UUIDField(default=uuid.uuid4, editable=False, unique=True)),
                ('pool', models.ForeignKey(
                    on_delete=django.db.models.deletion.PROTECT,
                    related_name='dispatch_reservations',
                    to='posting.offerpool',
                )),
                ('store', models.ForeignKey(
                    on_delete=django.db.models.deletion.PROTECT,
                    related_name='pool_dispatch_reservations',
                    to='integrations.integrationaccount',
                )),
                ('job', models.OneToOneField(
                    blank=True,
                    null=True,
                    on_delete=django.db.models.deletion.SET_NULL,
                    related_name='pool_dispatch_reservation',
                    to='posting.postingjob',
                )),
                ('status', models.CharField(
                    choices=[
                        ('active', 'Active'),
                        ('finalized', 'Finalized'),
                        ('released', 'Released'),
                        ('failed', 'Failed'),
                    ],
                    default='active',
                    max_length=16,
                )),
                ('item_count', models.PositiveIntegerField(default=0)),
                ('reason', models.TextField(blank=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('finalized_at', models.DateTimeField(blank=True, null=True)),
                ('released_at', models.DateTimeField(blank=True, null=True)),
            ],
            options={
                'db_table': 'pool_dispatch_reservations',
            },
        ),
        migrations.AddIndex(
            model_name='pooldispatchreservation',
            index=models.Index(
                fields=['pool', 'status'],
                name='dispatch_res_pool_status_idx',
            ),
        ),
        migrations.AddIndex(
            model_name='pooldispatchreservation',
            index=models.Index(
                fields=['status', 'created_at'],
                name='dispatch_res_stale_idx',
            ),
        ),

        # 2. Add RESERVED to OfferPoolItemStatus choices
        migrations.AlterField(
            model_name='offerpoolitem',
            name='status',
            field=models.CharField(
                choices=[
                    ('pending', 'Pending'),
                    ('reserved', 'Reserved'),
                    ('queued', 'Queued'),
                    ('pushed', 'Pushed'),
                    ('failed', 'Failed'),
                    ('consumed', 'Consumed'),
                ],
                default='pending',
                max_length=10,
            ),
        ),

        # 3. Add reservation FK to OfferPoolItem
        migrations.AddField(
            model_name='offerpoolitem',
            name='reservation',
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name='items',
                to='posting.pooldispatchreservation',
            ),
        ),

        # 4. Drop old pending constraint, add new ones
        migrations.RemoveConstraint(
            model_name='offerpoolitem',
            name='pending_pool_item_unassigned',
        ),
        migrations.AddConstraint(
            model_name='offerpoolitem',
            constraint=models.CheckConstraint(
                condition=(
                    ~models.Q(status='pending')
                    | models.Q(pool_offer__isnull=True, reservation__isnull=True)
                ),
                name='pending_item_unassigned',
            ),
        ),
        migrations.AddConstraint(
            model_name='offerpoolitem',
            constraint=models.CheckConstraint(
                condition=(
                    ~models.Q(status='reserved')
                    | models.Q(pool_offer__isnull=True)
                ),
                name='reserved_item_no_pool_offer',
            ),
        ),
        migrations.AddConstraint(
            model_name='offerpoolitem',
            constraint=models.CheckConstraint(
                condition=(
                    ~models.Q(status='reserved')
                    | models.Q(reservation__isnull=False)
                ),
                name='reserved_item_has_reservation',
            ),
        ),

        # 5. Add reservation index
        migrations.AddIndex(
            model_name='offerpoolitem',
            index=models.Index(
                fields=['reservation', 'pool', 'status'],
                name='pool_item_reservation_idx',
            ),
        ),
    ]
