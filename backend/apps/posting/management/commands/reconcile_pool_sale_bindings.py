"""Retroactively bind orders to pool items that were consumed without an event.

When a pool offer sells but ``notify_sale()`` never fired (e.g. order sync did
not associate the order with the pool listing), the periodic remote sweep marks
the item CONSUMED but no ``PoolSaleEvent`` is created — so the pool UI shows
"Remote reconciliation" with a blank Order ID.

This command repairs that gap SAFELY. For every CONSUMED, append-strategy pool
item with no sale event, it looks for an Order that references the *exact same
account* (``owned_product``) on the pool offer's store. Only when EXACTLY ONE
such order exists does it create the ``PoolSaleEvent`` binding. Ambiguous or
missing matches are left as "Remote reconciliation" — an honest blank beats a
confident wrong binding.

Report-only by default; pass ``--apply`` to write. Idempotent (keyed on the
production ``event_key``), so it is safe to re-run, and a later reactive
notify_sale for the same order will not create a duplicate.

PlayerAuctions clone offers are skipped: their sale identity comes from the
clone/active-offer, and PA order sync must be healthy first (separate issue).

Examples::

    python manage.py reconcile_pool_sale_bindings            # dry-run report
    python manage.py reconcile_pool_sale_bindings --apply     # write bindings
    python manage.py reconcile_pool_sale_bindings --pool 24 --apply
"""
from __future__ import annotations

import hashlib

from django.core.management.base import BaseCommand
from django.utils import timezone


class Command(BaseCommand):
    help = "Bind orders to CONSUMED pool items that never got a PoolSaleEvent."

    def add_arguments(self, parser):
        parser.add_argument(
            "--apply", action="store_true",
            help="Persist the bindings. Without this flag, only report.",
        )
        parser.add_argument(
            "--pool", type=int, default=None,
            help="Restrict to a single OfferPool id.",
        )
        parser.add_argument(
            "--limit", type=int, default=None,
            help="Process at most N items (for a cautious first pass).",
        )

    def handle(self, *args, **options):
        from apps.orders.models import Order
        from apps.posting.models import (
            OfferPoolItem,
            OfferPoolItemStatus,
            PoolSaleEvent,
        )

        apply = options["apply"]
        items = (
            OfferPoolItem.objects
            .filter(
                status=OfferPoolItemStatus.CONSUMED,
                pool_offer__isnull=False,
                sale_events__isnull=True,  # no PoolSaleEvent bound to this item
            )
            .select_related(
                "pool_offer", "pool_offer__listing",
                "pool_offer__listing__integration_account", "owned_product",
            )
            .order_by("id")
        )
        if options["pool"] is not None:
            items = items.filter(pool_id=options["pool"])
        if options["limit"]:
            items = items[: options["limit"]]

        bound = ambiguous = unmatched = skipped_pa = 0

        for item in items:
            pool_offer = item.pool_offer
            listing = pool_offer.listing
            store = listing.integration_account if listing else None
            provider = getattr(store, "provider", "") or ""

            if provider == "playerauctions":
                skipped_pa += 1
                continue
            if store is None or not item.owned_product_id:
                unmatched += 1
                continue

            # Definitive match: an order for THIS exact account on THIS store.
            candidates = list(
                Order.objects.filter(
                    integration_account_id=store.id,
                    owned_product_id=item.owned_product_id,
                )[:2]
            )
            if len(candidates) == 0:
                unmatched += 1
                self.stdout.write(
                    f"  item {item.pk} ({item.owned_product.login}): no matching order"
                )
                continue
            if len(candidates) > 1:
                ambiguous += 1
                self.stderr.write(self.style.WARNING(
                    f"  item {item.pk} ({item.owned_product.login}): "
                    f"{len(candidates)}+ matching orders — left as Remote reconciliation"
                ))
                continue

            order = candidates[0]
            event_key = f"{provider}:{store.id}:{order.store_order_id}:offer:{pool_offer.pk}"
            if len(event_key) > 255:
                digest = hashlib.sha256(event_key.encode()).hexdigest()
                event_key = f"{event_key[:180]}:{digest}"

            self.stdout.write(
                f"  item {item.pk} ({item.owned_product.login}) -> order "
                f"{order.store_order_id} (event_key={event_key})"
            )
            bound += 1
            if not apply:
                continue

            event, created = PoolSaleEvent.objects.get_or_create(
                event_key=event_key,
                defaults={
                    "listing_id": listing.id,
                    "pool_offer": pool_offer,
                    "pool_item_id": item.pk,
                    "order_id": order.pk,
                    "outcome": "processed",
                    "processed_at": timezone.now(),
                },
            )
            if not created:
                # Existing event (e.g. created without the exact item) — fill
                # in the missing references without changing counters.
                update_fields = []
                if not event.pool_item_id:
                    event.pool_item_id = item.pk
                    update_fields.append("pool_item")
                if not event.order_id:
                    event.order_id = order.pk
                    update_fields.append("order_id")
                if update_fields:
                    event.save(update_fields=update_fields)

        verb = "Bound" if apply else "Would bind"
        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS(
            f"{verb} {bound} | ambiguous {ambiguous} | unmatched {unmatched} | "
            f"skipped_pa {skipped_pa}"
        ))
        if not apply and bound:
            self.stdout.write(self.style.WARNING("[dry-run] Re-run with --apply to write."))
