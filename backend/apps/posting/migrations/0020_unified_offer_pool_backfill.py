from django.db import migrations, models
from django.db.models import Count, Q


def _resolve_variant(GameVariant, pool, listing):
    value = str(getattr(listing, 'variant', '') or '').strip()
    if not value:
        return None

    exact = GameVariant.objects.filter(game_id=pool.game_id).filter(
        Q(slug__iexact=value)
        | Q(label__iexact=value)
        | Q(source_key__iexact=value)
    ).first()
    if exact:
        return exact

    # Composite legacy values can contain more than one semantic dimension.
    # Do not guess between e.g. region and platform during a data migration.
    return None


def backfill_unified_pools(apps, schema_editor):
    OfferPool = apps.get_model('posting', 'OfferPool')
    PoolOffer = apps.get_model('posting', 'PoolOffer')
    OfferPoolItem = apps.get_model('posting', 'OfferPoolItem')
    OfferPoolActiveOffer = apps.get_model('posting', 'OfferPoolActiveOffer')
    GameVariant = apps.get_model('posting', 'GameVariant')

    duplicates = list(
        OfferPoolItem.objects.values('owned_product_id')
        .annotate(pool_count=Count('pool_id', distinct=True))
        .filter(pool_count__gt=1)
        .values_list('owned_product_id', flat=True)[:20]
    )
    if duplicates:
        raise RuntimeError(
            'Unified pool migration blocked: OwnedProducts occur in multiple pools: '
            f'{duplicates}'
        )

    orphan_active_offers = list(
        OfferPoolActiveOffer.objects.filter(status='active')
        .filter(Q(listing__isnull=True) | Q(pool_item__isnull=True))
        .values_list('pk', flat=True)[:20]
    )
    if orphan_active_offers:
        raise RuntimeError(
            'Unified pool migration blocked: active PA offers lack listing/item: '
            f'{orphan_active_offers}'
        )

    for pool in OfferPool.objects.select_related('listing', 'store').iterator():
        listing = pool.listing
        if listing is None:
            raise RuntimeError(f'Pool #{pool.pk} has no legacy listing')
        if pool.store_id != listing.integration_account_id:
            raise RuntimeError(
                f'Pool #{pool.pk} store/listing integration account mismatch'
            )
        if listing.game_id and pool.game_id != listing.game_id:
            raise RuntimeError(f'Pool #{pool.pk} game/listing mismatch')

        provider = pool.store.provider
        expected_strategy = 'clone' if provider == 'playerauctions' else 'append'
        if provider not in {'playerauctions', 'eldorado', 'gameboost'}:
            raise RuntimeError(f'Pool #{pool.pk} has unsupported provider {provider}')
        if pool.strategy != expected_strategy:
            raise RuntimeError(f'Pool #{pool.pk} provider/strategy mismatch')

        if expected_strategy == 'clone':
            max_concurrent = max(1, min(int(pool.max_concurrent or 1), 10))
            target_count = max_concurrent
            threshold = min(max(1, int(pool.threshold or 1)), target_count)
        else:
            max_concurrent = None
            target_count = max(1, int(pool.target_count or 1))
            threshold = min(max(1, int(pool.threshold or 1)), target_count)

        pool_offer, _ = PoolOffer.objects.update_or_create(
            listing_id=listing.pk,
            defaults={
                'pool_id': pool.pk,
                'strategy': expected_strategy,
                'target_count': target_count,
                'threshold': threshold,
                'max_concurrent': max_concurrent,
                'current_remote_count': pool.current_remote_count,
                'last_checked_at': pool.last_checked_at,
                'last_replenished_at': pool.last_replenished_at,
                'status': 'paused' if pool.status == 'paused' else 'active',
            },
        )

        pool.name = (listing.title or f'Pool #{pool.pk}')[:255]
        variant = _resolve_variant(GameVariant, pool, listing)
        pool.variant_id = variant.pk if variant else None
        if pool.status == 'depleted':
            pool.status = 'active'
        pool.save(update_fields=['name', 'variant', 'status', 'updated_at'])

        OfferPoolItem.objects.filter(
            pool_id=pool.pk,
            status__in=['pushed', 'consumed', 'queued'],
        ).update(pool_offer_id=pool_offer.pk)
        OfferPoolItem.objects.filter(
            pool_id=pool.pk,
            status='failed',
        ).exclude(target_offer_id='').update(pool_offer_id=pool_offer.pk)

        cross_pool = OfferPoolActiveOffer.objects.filter(pool_id=pool.pk).exclude(
            Q(pool_item__isnull=True) | Q(pool_item__pool_id=pool.pk)
        )
        if cross_pool.exists():
            raise RuntimeError(f'Pool #{pool.pk} has cross-pool ActiveOffer items')
        OfferPoolActiveOffer.objects.filter(pool_id=pool.pk).update(
            pool_offer_id=pool_offer.pk,
        )


def reverse_backfill(apps, schema_editor):
    OfferPool = apps.get_model('posting', 'OfferPool')
    OfferPoolItem = apps.get_model('posting', 'OfferPoolItem')
    OfferPoolActiveOffer = apps.get_model('posting', 'OfferPoolActiveOffer')
    PoolOffer = apps.get_model('posting', 'PoolOffer')

    OfferPoolActiveOffer.objects.update(pool_offer_id=None)
    OfferPoolItem.objects.update(pool_offer_id=None)
    for pool in OfferPool.objects.all().iterator():
        if not OfferPoolItem.objects.filter(pool_id=pool.pk, status='pending').exists():
            pool.status = 'depleted'
            pool.save(update_fields=['status', 'updated_at'])
    PoolOffer.objects.all().delete()


class Migration(migrations.Migration):
    dependencies = [
        ('posting', '0019_unified_offer_pool_expand'),
    ]

    operations = [
        migrations.RunPython(backfill_unified_pools, reverse_backfill),
        migrations.AddConstraint(
            model_name='offerpoolitem',
            constraint=models.UniqueConstraint(
                fields=('owned_product',),
                name='unique_owned_product_across_pools',
            ),
        ),
        migrations.AddConstraint(
            model_name='offerpoolactiveoffer',
            constraint=models.UniqueConstraint(
                fields=('pool_offer', 'store_listing_id'),
                name='unique_pool_offer_remote_clone',
            ),
        ),
        migrations.AddConstraint(
            model_name='offerpoolactiveoffer',
            constraint=models.CheckConstraint(
                condition=(
                    ~Q(status='active')
                    | (Q(listing__isnull=False) & Q(pool_item__isnull=False))
                ),
                name='active_clone_requires_listing_item',
            ),
        ),
    ]
