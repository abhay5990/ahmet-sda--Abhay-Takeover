"""Detect OwnedProducts that have a successful order but still have active listings.

These are products that were sold (delivered/completed) but whose listings
were not removed — likely missed by cross-platform reconciliation.

Usage:
    python manage.py detect_sold_active_listings
    python manage.py detect_sold_active_listings --provider eldorado
    python manage.py detect_sold_active_listings --fix-status
    python manage.py detect_sold_active_listings --remove-listings
    python manage.py detect_sold_active_listings --remove-listings --fix-status
    python manage.py detect_sold_active_listings --json
"""

import json
import logging
import os
from datetime import datetime

from django.core.management.base import BaseCommand
from django.db.models import Q
from django.utils import timezone

from apps.integrations.providers.registry import get_or_build_client, get_provider
from apps.inventory.models import OwnedProduct
from apps.inventory.services import resolve_owned_product_status
from apps.listings.enums import ListingStatus
from apps.listings.models import ListingOwnedProduct
from apps.orders.enums import OrderStatus
from apps.sync.models import RawPayload
from apps.sync.services.cross_platform import (
    _is_multi_account,
    _reconcile_multi_account,
)

logger = logging.getLogger(__name__)

SUCCESS_STATUSES = (OrderStatus.PENDING, OrderStatus.DELIVERED, OrderStatus.COMPLETED)
ACTIVE_LISTING_STATUSES = (ListingStatus.LISTED, ListingStatus.PAUSED)


class Command(BaseCommand):
    help = (
        'Detect OwnedProducts with a successful order (delivered/completed) '
        'that still have active listings (listed/paused).'
    )

    def add_arguments(self, parser):
        parser.add_argument(
            '--provider',
            type=str,
            default=None,
            help='Filter listings by provider name (e.g. "eldorado", "gameboost").',
        )
        parser.add_argument(
            '--account',
            type=str,
            default=None,
            help='Filter listings by IntegrationAccount slug.',
        )
        parser.add_argument(
            '--fix-status',
            action='store_true',
            help='Fix OwnedProduct statuses: 1 order -> SOLD, 2+ -> MULTIPLE_SOLD.',
        )
        parser.add_argument(
            '--remove-listings',
            action='store_true',
            help='Remove active listings from marketplace API and mark as DELETED in DB.',
        )
        parser.add_argument(
            '--json',
            action='store_true',
            help='Export results as JSON to /tmp/sold_active_listings_<timestamp>.json',
        )

    def handle(self, *args, **options):
        provider = options['provider']
        account_slug = options['account']
        fix_status = options['fix_status']
        remove_listings = options['remove_listings']
        export_json = options['json']

        # OwnedProducts with at least one successful order
        # AND at least one active listing via ListingOwnedProduct
        listing_q = Q(
            listing_owned_products__listing__status__in=ACTIVE_LISTING_STATUSES,
        )
        if provider:
            listing_q &= Q(
                listing_owned_products__listing__integration_account__provider=provider,
            )
        if account_slug:
            listing_q &= Q(
                listing_owned_products__listing__integration_account__slug=account_slug,
            )

        qs = OwnedProduct.objects.filter(
            orders__status__in=SUCCESS_STATUSES,
        ).filter(
            listing_q,
        ).distinct().prefetch_related(
            'orders',
            'listing_owned_products__listing__integration_account__credential',
        )

        total = qs.count()
        if total == 0:
            self.stdout.write(self.style.SUCCESS(
                'No sold OwnedProducts with active listings found.'
            ))
            return

        self.stdout.write(self.style.WARNING(
            f'Found {total} OwnedProduct(s) with successful orders AND active listings:\n'
        ))

        fixed_count = 0
        removed_count = 0
        failed_count = 0
        json_records = []

        for op in qs:
            self.stdout.write(
                f'  OwnedProduct #{op.id} | {op.login} | status={op.status}'
            )

            # Show successful orders
            order_list = []
            for order in op.orders.filter(status__in=SUCCESS_STATUSES):
                acct_slug = order.integration_account.slug if order.integration_account else '?'
                self.stdout.write(
                    f'    ORDER  #{order.id} | {order.status} | '
                    f'{acct_slug} | store_id={order.store_order_id} | '
                    f'sold_at={order.sold_at}'
                )
                order_list.append({
                    'id': order.id,
                    'status': order.status,
                    'account': acct_slug,
                    'store_order_id': order.store_order_id,
                    'sold_at': str(order.sold_at) if order.sold_at else None,
                })

            # Collect active listings
            active_lops = op.listing_owned_products.filter(
                listing__status__in=ACTIVE_LISTING_STATUSES,
            )
            if provider:
                active_lops = active_lops.filter(
                    listing__integration_account__provider=provider,
                )
            if account_slug:
                active_lops = active_lops.filter(
                    listing__integration_account__slug=account_slug,
                )

            listing_list = []
            for lop in active_lops.select_related('listing__integration_account__credential'):
                lst = lop.listing
                acct = lst.integration_account
                self.stdout.write(
                    f'    LISTING #{lst.id} | {lst.status} | '
                    f'{acct.provider}:{acct.slug} | '
                    f'store_id={lst.store_listing_id} | '
                    f'price={lst.price} {lst.currency}'
                )
                listing_list.append({
                    'id': lst.id,
                    'status': lst.status,
                    'provider': acct.provider,
                    'account': acct.slug,
                    'store_listing_id': lst.store_listing_id,
                    'title': (lst.title or '')[:80],
                    'price': str(lst.price),
                    'currency': lst.currency,
                })

                # Remove from API + DB if requested
                if remove_listings:
                    success = self._remove_listing(lst, op, acct)
                    if success:
                        removed_count += 1
                    else:
                        failed_count += 1

            if export_json:
                json_records.append({
                    'owned_product_id': op.id,
                    'login': op.login,
                    'status': op.status,
                    'orders': order_list,
                    'active_listings': listing_list,
                })

            # Fix status if requested
            if fix_status or remove_listings:
                old_status = op.status
                new_status = resolve_owned_product_status(op)
                if old_status != new_status:
                    fixed_count += 1
                    self.stdout.write(self.style.SUCCESS(
                        f'    FIXED  {old_status} -> {new_status}'
                    ))

            self.stdout.write('')

        self.stdout.write(self.style.SUCCESS(f'Total: {total}'))
        if fix_status or remove_listings:
            self.stdout.write(self.style.SUCCESS(f'Fixed statuses: {fixed_count}'))
        if remove_listings:
            self.stdout.write(self.style.SUCCESS(f'Removed listings: {removed_count}'))
            if failed_count:
                self.stdout.write(self.style.ERROR(f'Failed removals: {failed_count}'))

        if export_json:
            from django.conf import settings
            tmp_dir = settings.ROOT_DIR / 'tmp'
            tmp_dir.mkdir(parents=True, exist_ok=True)
            ts = datetime.now().strftime('%Y%m%d_%H%M%S')
            out_path = str(tmp_dir / f'sold_active_listings_{ts}.json')
            with open(out_path, 'w', encoding='utf-8') as f:
                json.dump(json_records, f, ensure_ascii=False, indent=2)
            self.stdout.write(self.style.SUCCESS(f'JSON exported to: {out_path}'))

    def _remove_listing(self, listing, sold_owned, account):
        """Remove a listing via API, update DB on success. Returns True if successful."""
        try:
            is_multi = _is_multi_account(listing)

            if is_multi:
                # Multi-account: use cross_platform handler (delete credential or recreate offer)
                client = get_or_build_client(account.provider, account.credential)
                # Get first successful order for this owned product (needed for logging)
                order = sold_owned.orders.filter(status__in=SUCCESS_STATUSES).first()
                _reconcile_multi_account(listing, sold_owned, account, client, order)
                self.stdout.write(self.style.SUCCESS(
                    f'    REMOVED (multi-account) {listing.store_listing_id} '
                    f'from {account.provider}:{account.slug}'
                ))
            else:
                # Single-account: delete via provider API
                provider_impl = get_provider(account.provider)
                client = get_or_build_client(account.provider, account.credential)
                result = provider_impl.delete_listing(client, listing.store_listing_id)

                # Check API result before marking as DELETED
                if hasattr(result, 'ok') and not result.ok:
                    error_msg = (
                        result.error.message
                        if hasattr(result, 'error') and result.error
                        else 'unknown'
                    )
                    raise RuntimeError(
                        f"API delete failed for {listing.store_listing_id}: {error_msg}"
                    )

                # API success -> mark as DELETED in DB
                listing.status = ListingStatus.DELETED
                listing.removed_at = timezone.now()
                listing.save(update_fields=['status', 'removed_at', 'updated_at'])

                # Unlink OwnedProduct from listing
                ListingOwnedProduct.objects.filter(
                    listing=listing,
                    owned_product=sold_owned,
                ).delete()

                self.stdout.write(self.style.SUCCESS(
                    f'    REMOVED {listing.store_listing_id} '
                    f'from {account.provider}:{account.slug}'
                ))

            return True

        except Exception as e:
            self.stdout.write(self.style.ERROR(
                f'    FAILED {listing.store_listing_id} '
                f'from {account.provider}:{account.slug}: {e}'
            ))
            logger.exception(
                'Failed to remove listing %s from %s:%s',
                listing.store_listing_id, account.provider, account.slug,
            )
            return False
