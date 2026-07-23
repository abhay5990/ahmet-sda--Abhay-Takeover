from django.db import migrations, models


def backfill_pool_sale_event_items(apps, schema_editor):
    """Attach historical sale events to the exact consumed pool account.

    PlayerAuctions clone sales have a durable active-offer → pool-item mapping.
    Append-marketplace events can be matched through the synchronized order's
    owned product and the destination PoolOffer.
    """
    PoolSaleEvent = apps.get_model('posting', 'PoolSaleEvent')
    OfferPoolActiveOffer = apps.get_model('posting', 'OfferPoolActiveOffer')
    OfferPoolItem = apps.get_model('posting', 'OfferPoolItem')
    Order = apps.get_model('orders', 'Order')

    events = (
        PoolSaleEvent.objects
        .filter(pool_item__isnull=True, pool_offer__isnull=False)
        .only('pk', 'pool_offer_id', 'listing_id', 'order_id')
        .iterator()
    )
    for event in events:
        pool_item_id = (
            OfferPoolActiveOffer.objects
            .filter(
                pool_offer_id=event.pool_offer_id,
                listing_id=event.listing_id,
                pool_item_id__isnull=False,
            )
            .order_by('-updated_at')
            .values_list('pool_item_id', flat=True)
            .first()
        )
        if pool_item_id is None and event.order_id:
            owned_product_id = (
                Order.objects.filter(pk=event.order_id)
                .values_list('owned_product_id', flat=True)
                .first()
            )
            if owned_product_id:
                pool_item_id = (
                    OfferPoolItem.objects.filter(
                        pool_offer_id=event.pool_offer_id,
                        owned_product_id=owned_product_id,
                    )
                    .values_list('pk', flat=True)
                    .first()
                )
        if pool_item_id:
            PoolSaleEvent.objects.filter(pk=event.pk).update(
                pool_item_id=pool_item_id,
            )


class Migration(migrations.Migration):

    dependencies = [
        ('orders', '0003_fee_rule'),
        ('posting', '0031_add_removed_to_offerpoolitemstatus'),
    ]

    operations = [
        migrations.AddField(
            model_name='poolsaleevent',
            name='pool_item',
            field=models.ForeignKey(
                blank=True,
                help_text='Exact pool account consumed by this marketplace sale, when known.',
                null=True,
                on_delete=models.SET_NULL,
                related_name='sale_events',
                to='posting.offerpoolitem',
            ),
        ),
        migrations.AddIndex(
            model_name='poolsaleevent',
            index=models.Index(
                fields=['pool_item', '-created_at'],
                name='pool_sale_item_created_idx',
            ),
        ),
        migrations.RunPython(
            backfill_pool_sale_event_items,
            migrations.RunPython.noop,
        ),
    ]
