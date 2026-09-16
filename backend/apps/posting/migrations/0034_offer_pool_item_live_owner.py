from django.db import migrations, models


def backfill_live_pool_owner(apps, schema_editor):
    OfferPoolItem = apps.get_model('posting', 'OfferPoolItem')
    PoolSaleEvent = apps.get_model('posting', 'PoolSaleEvent')
    OfferPoolActiveOffer = apps.get_model('posting', 'OfferPoolActiveOffer')

    sold_item_ids = set(
        PoolSaleEvent.objects.exclude(pool_item_id__isnull=True)
        .values_list('pool_item_id', flat=True)
    )
    sold_clone_item_ids = set(
        OfferPoolActiveOffer.objects.filter(status='sold')
        .exclude(pool_item_id__isnull=True)
        .values_list('pool_item_id', flat=True)
    )
    protected_sale_ids = sold_item_ids | sold_clone_item_ids

    for item in OfferPoolItem.objects.all().iterator():
        safely_removed = (
            item.status == 'removed'
            and item.pk not in protected_sale_ids
            and item.pool_offer_id is None
            and item.reservation_id is None
            and not item.target_offer_id
            and not item.remote_credential_id
            and item.remote_state in {'', 'absent'}
        )
        item.live_owned_product_id = None if safely_removed else item.owned_product_id
        item.save(update_fields=['live_owned_product'])


class Migration(migrations.Migration):

    dependencies = [
        ('posting', '0033_playerauctions_edit_request'),
    ]

    operations = [
        migrations.AddField(
            model_name='offerpoolitem',
            name='live_owned_product',
            field=models.ForeignKey(
                blank=True,
                editable=False,
                help_text='Current exclusive pool ownership. Cleared only after a guarded unsold removal so historical removed rows can be retained safely.',
                null=True,
                on_delete=models.deletion.PROTECT,
                related_name='live_pool_items',
                to='inventory.ownedproduct',
            ),
        ),
        migrations.RunPython(backfill_live_pool_owner, migrations.RunPython.noop),
        migrations.RemoveConstraint(
            model_name='offerpoolitem',
            name='unique_owned_product_across_pools',
        ),
        migrations.AddConstraint(
            model_name='offerpoolitem',
            constraint=models.UniqueConstraint(
                fields=('live_owned_product',),
                name='unique_live_owned_product_across_pools',
            ),
        ),
    ]
