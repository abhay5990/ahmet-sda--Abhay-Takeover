"""fix_pool_order_links — backfill PoolSaleEvent.order_id and fix wrongly-consumed pool items.

Two problems this command fixes:

1. BACKFILL ORDER IDs
   PoolSaleEvents created before the order_id field was populated (or before the
   order was fully synced) have order_id=NULL.  This causes the pool detail page
   to show "Remote reconciliation — Waiting for a verified marketplace order sync."
   Fix: for each PoolSaleEvent with order_id=NULL, look up the Order by matching
   listing + integration_account and fill in order_id.

2. FIX WRONGLY-SOLD PA ITEMS (pending-payment trigger bug)
   Before the fix in base.py (only notify on non-PENDING orders), PA orders with
   status "payment received" / "order processing" / "delivery in progress" /
   "verifying payment" would trigger notify_sale and mark pool items as SOLD.
   Fix: find PoolSaleEvents whose linked Order has status=PENDING (i.e. the order
   never progressed to DELIVERED/COMPLETED) and whose OfferPoolActiveOffer is SOLD
   (not DELISTED or CONSUMED), then revert those active offers back to ACTIVE.

Usage:
    python manage.py fix_pool_order_links
    python manage.py fix_pool_order_links --dry-run
    python manage.py fix_pool_order_links --fix-pending-only
    python manage.py fix_pool_order_links --backfill-only
"""
from __future__ import annotations

import logging

from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from apps.orders.enums import OrderStatus
from apps.orders.models import Order
from apps.posting.models import (
    OfferPoolActiveOffer,
    OfferPoolActiveOfferStatus,
    OfferPoolItem,
    OfferPoolItemStatus,
    PoolSaleEvent,
)

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = (
        'Backfill PoolSaleEvent.order_id from matched Orders and '
        'revert pool items wrongly consumed by pending-payment PA orders.'
    )

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run',
            action='store_true',
            default=False,
            help='Report what would be changed without writing anything.',
        )
        parser.add_argument(
            '--backfill-only',
            action='store_true',
            default=False,
            help='Only backfill order IDs, skip the pending-payment revert.',
        )
        parser.add_argument(
            '--fix-pending-only',
            action='store_true',
            default=False,
            help='Only revert wrongly-sold items, skip order ID backfill.',
        )

    def handle(self, *args, **options):
        dry_run = options['dry_run']
        backfill_only = options['backfill_only']
        fix_pending_only = options['fix_pending_only']

        if dry_run:
            self.stdout.write(self.style.WARNING('DRY RUN — no changes will be written.'))

        if not fix_pending_only:
            self._backfill_order_ids(dry_run)

        if not backfill_only:
            self._revert_pending_payment_sales(dry_run)

    # ── Part 1: Backfill order IDs ────────────────────────────────────────────

    def _backfill_order_ids(self, dry_run: bool) -> None:
        self.stdout.write('\n=== Part 1: Backfill PoolSaleEvent.order_id ===')

        # Find all sale events with no order_id
        events_without_order = list(
            PoolSaleEvent.objects
            .filter(order_id__isnull=True)
            .select_related('listing', 'listing__integration_account')
            .order_by('created_at')
        )
        self.stdout.write(f'Found {len(events_without_order)} PoolSaleEvents with order_id=NULL')

        filled = 0
        for event in events_without_order:
            if not event.listing_id:
                continue
            listing = event.listing
            if not listing or not listing.integration_account_id:
                continue

            # Find the best matching order: same listing + integration_account,
            # prefer non-PENDING statuses (confirmed sales), newest first
            order = (
                Order.objects
                .filter(
                    listing=listing,
                    integration_account=listing.integration_account,
                )
                .exclude(status=OrderStatus.CANCELLED)
                .order_by(
                    # Prefer confirmed statuses first
                    'status',  # COMPLETED < DELIVERED < DISPUTED < PENDING alphabetically
                    '-sold_at',
                )
                .first()
            )

            if not order:
                # Fallback: match by store_listing_id
                order = (
                    Order.objects
                    .filter(
                        store_listing_id=listing.store_listing_id,
                        integration_account=listing.integration_account,
                    )
                    .exclude(status=OrderStatus.CANCELLED)
                    .order_by('-sold_at')
                    .first()
                )

            if not order:
                continue

            self.stdout.write(
                f'  Event {event.pk} (listing {listing.store_listing_id}): '
                f'order_id={order.pk} store_order_id={order.store_order_id} '
                f'status={order.status}'
            )

            if not dry_run:
                event.order_id = order.pk
                event.save(update_fields=['order_id'])
            filled += 1

        self.stdout.write(
            self.style.SUCCESS(
                f'{"Would fill" if dry_run else "Filled"} order_id for {filled} PoolSaleEvents'
            )
        )

    # ── Part 2: Revert wrongly-sold items from pending-payment orders ─────────

    def _revert_pending_payment_sales(self, dry_run: bool) -> None:
        self.stdout.write('\n=== Part 2: Revert wrongly-sold PA pool items ===')

        # Find PoolSaleEvents linked to PENDING orders (not yet confirmed sales)
        # that have caused an OfferPoolActiveOffer to be marked SOLD
        pending_events = list(
            PoolSaleEvent.objects
            .filter(
                order_id__isnull=False,
            )
            .select_related(
                'pool_offer',
                'pool_offer__listing',
                'pool_offer__listing__integration_account',
            )
            .order_by('created_at')
        )

        reverted = 0
        for event in pending_events:
            if not event.order_id:
                continue

            # Check if the linked order is still PENDING
            try:
                order = Order.objects.get(pk=event.order_id)
            except Order.DoesNotExist:
                continue

            if order.status != OrderStatus.PENDING:
                # Order has progressed to DELIVERED/COMPLETED — this is a real sale
                continue

            # Check if this event caused an active offer to be marked SOLD
            sold_offer = (
                OfferPoolActiveOffer.objects
                .filter(
                    pool_offer=event.pool_offer,
                    status=OfferPoolActiveOfferStatus.SOLD,
                )
                .first()
            )

            if not sold_offer:
                continue

            provider = ''
            if event.pool_offer and event.pool_offer.listing:
                account = event.pool_offer.listing.integration_account
                provider = getattr(account, 'provider', '') if account else ''

            self.stdout.write(
                f'  Event {event.pk}: order {order.store_order_id} '
                f'(status={order.status}, provider={provider}) '
                f'→ active_offer {sold_offer.pk} wrongly SOLD → reverting to ACTIVE'
            )

            if not dry_run:
                with transaction.atomic():
                    locked_offer = OfferPoolActiveOffer.objects.select_for_update().get(
                        pk=sold_offer.pk,
                    )
                    if locked_offer.status == OfferPoolActiveOfferStatus.SOLD:
                        locked_offer.status = OfferPoolActiveOfferStatus.ACTIVE
                        locked_offer.save(update_fields=['status', 'updated_at'])

                        # Also update the pool_offer remote count
                        if event.pool_offer:
                            from apps.posting.models import PoolOffer
                            locked_pool_offer = PoolOffer.objects.select_for_update().get(
                                pk=event.pool_offer.pk,
                            )
                            if locked_pool_offer.marketplace == 'playerauctions':
                                new_count = locked_pool_offer.active_offers.filter(
                                    status=OfferPoolActiveOfferStatus.ACTIVE,
                                ).count()
                            else:
                                current = locked_pool_offer.current_remote_count or 0
                                new_count = current + 1
                            locked_pool_offer.current_remote_count = new_count
                            locked_pool_offer.last_checked_at = timezone.now()
                            locked_pool_offer.save(update_fields=[
                                'current_remote_count', 'last_checked_at', 'updated_at',
                            ])

                        # Delete the erroneous sale event so it doesn't block future sales
                        event.delete()
            reverted += 1

        self.stdout.write(
            self.style.SUCCESS(
                f'{"Would revert" if dry_run else "Reverted"} {reverted} wrongly-sold pool items'
            )
        )
        if reverted > 0 and not dry_run:
            self.stdout.write(
                self.style.WARNING(
                    'Pool remote counts updated. Run the pool checker sweep to verify.'
                )
            )
