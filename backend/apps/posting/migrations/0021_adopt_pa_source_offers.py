from django.db import migrations


def adopt_pa_sources(apps, schema_editor):
    PoolOffer = apps.get_model('posting', 'PoolOffer')
    OfferPoolItem = apps.get_model('posting', 'OfferPoolItem')
    OfferPoolActiveOffer = apps.get_model('posting', 'OfferPoolActiveOffer')
    ListingOwnedProduct = apps.get_model('listings', 'ListingOwnedProduct')

    for pool_offer in PoolOffer.objects.filter(strategy='clone').iterator():
        if OfferPoolActiveOffer.objects.filter(
            pool_offer_id=pool_offer.pk,
            listing_id=pool_offer.listing_id,
        ).exists():
            continue

        links = list(
            ListingOwnedProduct.objects.filter(listing_id=pool_offer.listing_id)
            .values_list('owned_product_id', flat=True)[:2]
        )
        if not links:
            continue  # Explicit template-only source.
        if len(links) > 1:
            raise RuntimeError(
                f'PA PoolOffer #{pool_offer.pk} source listing has multiple credentials'
            )

        owned_product_id = links[0]
        item = OfferPoolItem.objects.filter(
            owned_product_id=owned_product_id,
        ).first()
        if item and item.pool_id != pool_offer.pool_id:
            raise RuntimeError(
                f'PA source credential #{owned_product_id} belongs to another pool'
            )
        if item is None:
            item = OfferPoolItem.objects.create(
                pool_id=pool_offer.pool_id,
                owned_product_id=owned_product_id,
                pool_offer_id=pool_offer.pk,
                status='pushed',
                target_offer_id=pool_offer.listing.store_listing_id,
                remote_state='present',
            )
        else:
            if item.pool_offer_id and item.pool_offer_id != pool_offer.pk:
                raise RuntimeError(
                    f'PA source credential #{owned_product_id} is assigned elsewhere'
                )
            item.pool_offer_id = pool_offer.pk
            item.status = 'pushed'
            item.target_offer_id = pool_offer.listing.store_listing_id
            item.remote_state = 'present'
            item.save(update_fields=[
                'pool_offer', 'status', 'target_offer_id', 'remote_state',
                'updated_at',
            ])

        OfferPoolActiveOffer.objects.create(
            pool_id=pool_offer.pool_id,
            pool_offer_id=pool_offer.pk,
            store_listing_id=pool_offer.listing.store_listing_id,
            listing_id=pool_offer.listing_id,
            pool_item_id=item.pk,
            status='active',
        )
        pool_offer.current_remote_count = OfferPoolActiveOffer.objects.filter(
            pool_offer_id=pool_offer.pk,
            status='active',
        ).count()
        pool_offer.save(update_fields=['current_remote_count', 'updated_at'])


class Migration(migrations.Migration):
    dependencies = [
        ('posting', '0020_unified_offer_pool_backfill'),
    ]

    operations = [
        migrations.RunPython(adopt_pa_sources, migrations.RunPython.noop),
    ]
