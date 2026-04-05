"""Retroactive cleanup: delete listings where ALL linked OwnedProducts are SOLD.

Multi-account protection: if a listing has any non-sold OwnedProduct, it is
skipped — only listings where every linked account has been sold are deleted.

Usage:
    python manage.py cleanup_stale_listings                 # dry-run (default)
    python manage.py cleanup_stale_listings --execute       # actually delete via API
    python manage.py cleanup_stale_listings --account gameboost-store4gamers --execute
"""

import time

from django.db.models import Count, Q
from django.core.management.base import BaseCommand
from django.utils import timezone

from apps.integrations.providers.registry import get_or_build_client, get_provider
from apps.inventory.enums import OwnedProductStatus
from apps.listings.enums import ListingStatus
from apps.listings.models import Listing
from apps.sync.enums import SyncLogLevel
from apps.sync.services.shared.sync_log import log_sync, log_sync_error

SOLD_STATUSES = (OwnedProductStatus.SOLD, OwnedProductStatus.MULTIPLE_SOLD)
SUCCESS_ORDER_STATUSES = ('pending', 'delivered', 'completed')


class Command(BaseCommand):
    help = (
        'Find LISTED listings where ALL linked OwnedProducts are SOLD '
        'and delete them via marketplace API. Multi-account offers with '
        'any non-sold account are skipped.'
    )

    def add_arguments(self, parser):
        parser.add_argument(
            '--execute',
            action='store_true',
            help='Actually delete via API. Without this flag, only shows what would be deleted (dry-run).',
        )
        parser.add_argument(
            '--account',
            type=str,
            default=None,
            help='Filter by IntegrationAccount slug (e.g. "gameboost-store4gamers").',
        )
        parser.add_argument(
            '--limit',
            type=int,
            default=0,
            help='Max number of listings to process (0 = all).',
        )
        parser.add_argument(
            '--delay',
            type=float,
            default=0.5,
            help='Seconds to wait between API calls (rate limit protection). Default: 0.5',
        )

    def handle(self, *args, **options):
        execute = options['execute']
        account_slug = options['account']
        limit = options['limit']
        delay = options['delay']

        # Multi-account safe query:
        # - Listing is LISTED
        # - Has at least 1 linked OwnedProduct
        # - ALL linked OwnedProducts are sold (no non-sold remain)
        qs = Listing.objects.filter(
            status=ListingStatus.LISTED,
        ).annotate(
            total_linked=Count('listing_owned_products'),
            non_sold_count=Count(
                'listing_owned_products',
                filter=~Q(listing_owned_products__owned_product__status__in=SOLD_STATUSES),
            ),
        ).filter(
            total_linked__gt=0,     # has linked OwnedProducts
            non_sold_count=0,       # ALL are sold → safe to delete
        ).select_related(
            'integration_account__credential',
        )

        if account_slug:
            qs = qs.filter(integration_account__slug=account_slug)

        qs = qs.order_by('integration_account__slug', 'id')

        total = qs.count()
        if total == 0:
            self.stdout.write(self.style.SUCCESS('No fully-sold stale listings found.'))
            return

        if limit:
            qs = qs[:limit]
            self.stdout.write(f'Found {total} fully-sold stale listings, processing first {limit}.')
        else:
            self.stdout.write(f'Found {total} fully-sold stale listings to process.')

        if not execute:
            self.stdout.write(self.style.WARNING(
                'DRY RUN — add --execute to actually delete. Showing first 20:'
            ))
            for listing in qs[:20]:
                acct = listing.integration_account
                sold_info = self._get_sold_info(listing)
                self.stdout.write(
                    f'  [{acct.provider}] {acct.slug} | '
                    f'store_id={listing.store_listing_id} | '
                    f'linked={listing.total_linked} | '
                    f'price={listing.price} {listing.currency} | '
                    f'{listing.title[:50]}'
                )
                if sold_info:
                    self.stdout.write(f'    SOLD: {sold_info}')
            if total > 20:
                self.stdout.write(f'  ... and {total - 20} more')
            return

        # Execute mode
        success = 0
        failed = 0
        current_account_id = None
        client = None

        for listing in qs.iterator():
            account = listing.integration_account

            # Build client once per account
            if account.id != current_account_id:
                current_account_id = account.id
                try:
                    client = get_or_build_client(account.provider, account.credential)
                except Exception as e:
                    self.stdout.write(self.style.ERROR(
                        f'Failed to build client for {account.slug}: {e}'
                    ))
                    client = None

            if client is None:
                failed += 1
                continue

            provider = get_provider(account.provider)

            try:
                provider.delete_listing(client, listing.store_listing_id)

                # API success → DB update
                listing.status = ListingStatus.DELETED
                listing.removed_at = timezone.now()
                listing.save(update_fields=['status', 'removed_at', 'updated_at'])

                success += 1
                log_sync(
                    'stale_cleanup', SyncLogLevel.SUCCESS,
                    f'Deleted stale listing {listing.store_listing_id} from {account.slug}',
                    listing=listing,
                    integration_account=account,
                )
                sold_info = self._get_sold_info(listing)
                self.stdout.write(
                    f'  OK  [{account.provider}] {listing.store_listing_id}'
                    f'{" | SOLD: " + sold_info if sold_info else ""}'
                )

            except Exception as e:
                failed += 1
                log_sync_error(
                    'stale_cleanup',
                    f'Failed to delete {listing.store_listing_id} from {account.slug}: {e}',
                    exc=e,
                    listing=listing,
                    integration_account=account,
                )
                self.stdout.write(self.style.ERROR(
                    f'  FAIL [{account.provider}] {listing.store_listing_id}: {e}'
                ))

            # Rate limit protection
            if delay:
                time.sleep(delay)

        self.stdout.write('')
        self.stdout.write(self.style.SUCCESS(
            f'Done. Success: {success}, Failed: {failed}, Total: {success + failed}'
        ))

    @staticmethod
    def _get_sold_info(listing) -> str:
        """Return a short string describing where this listing's OwnedProducts were sold."""
        from apps.listings.models import ListingOwnedProduct
        from apps.orders.models import Order

        lops = ListingOwnedProduct.objects.filter(
            listing=listing,
        ).select_related('owned_product')

        parts = []
        for lop in lops:
            order = Order.objects.filter(
                owned_product=lop.owned_product,
                status__in=SUCCESS_ORDER_STATUSES,
            ).select_related('integration_account').first()
            if order and order.integration_account:
                parts.append(
                    f'{lop.owned_product.login} -> '
                    f'{order.integration_account.provider}:{order.integration_account.slug} '
                    f'({order.status})'
                )
        return ' | '.join(parts)
