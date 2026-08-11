"""Bind already-verified marketplace orders to pool items sold via reconciliation.

When a pool account sells but the reactive ``notify_sale`` path could not link
the exact order (e.g. a direct PlayerAuctions sale whose offer id did not match
the pool listing, or an order ingested after the item was already consumed by
the remote-count sweep), the item is left CONSUMED with **no** ``PoolSaleEvent``.
On the pool "Sold / reconciled" page these rows show:

    Remote reconciliation — Waiting for a verified marketplace order sync.

…with no order id, even though the sale is real and the order exists locally.

This command repairs that gap. For every sold-but-unbound pool item it finds the
matching local ``Order`` through the account's ``OwnedProduct`` (a definitive
1:1 account↔order link — the PA order sync resolves the same ``OwnedProduct`` by
login), and records a ``PoolSaleEvent`` so the verified order id renders on the
page. It is dry-run by default, idempotent (deterministic event key +
get_or_create), never reuses one order for two items, and only binds
non-cancelled/non-refunded orders.

Examples::

    python manage.py reconcile_pool_sale_bindings --pool 30
    python manage.py reconcile_pool_sale_bindings --pool 30 --apply
    python manage.py reconcile_pool_sale_bindings --account playerauctions-csgosmurfkings --apply
    python manage.py reconcile_pool_sale_bindings --game grand-theft-auto --apply
"""
from __future__ import annotations

from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone


class Command(BaseCommand):
    help = (
        "Bind verified marketplace orders to pool items sold via remote "
        "reconciliation (no PoolSaleEvent). Dry-run by default."
    )

    def add_arguments(self, parser):
        parser.add_argument("--pool", type=int, default=None, help="Restrict to one OfferPool id.")
        parser.add_argument(
            "--account", default=None,
            help="Restrict to pools whose offer listings use this IntegrationAccount slug.",
        )
        parser.add_argument(
            "--game", default=None,
            help="Restrict to pools whose game slug starts with this prefix.",
        )
        parser.add_argument(
            "--apply", action="store_true",
            help="Persist the bindings. Without this flag, only report what would bind.",
        )

    def handle(self, *args, **options):
        from apps.orders.enums import OrderStatus
        from apps.orders.models import Order
        from apps.posting.models import (
            OfferPool,
            OfferPoolActiveOffer,
            OfferPoolActiveOfferStatus,
            OfferPoolItem,
            OfferPoolItemStatus,
            PoolSaleEvent,
        )

        apply = options["apply"]

        pools = OfferPool.objects.all()
        if options["pool"]:
            pools = pools.filter(pk=options["pool"])
        if options["account"]:
            pools = pools.filter(
                pool_offers__listing__integration_account__slug=options["account"],
            )
        if options["game"]:
            pools = pools.filter(game__slug__startswith=options["game"])
        pool_ids = list(pools.values_list("pk", flat=True).distinct())
        if not pool_ids:
            self.stdout.write(self.style.WARNING("No pools match the given scope."))
            return

        # Sold pool items: CONSUMED (append remote-reconciliation) or tied to a
        # SOLD PlayerAuctions clone.
        sold_clone_item_ids = set(
            OfferPoolActiveOffer.objects.filter(
                pool_offer__pool_id__in=pool_ids,
                status=OfferPoolActiveOfferStatus.SOLD,
                pool_item__isnull=False,
            ).values_list("pool_item_id", flat=True)
        )
        items = list(
            OfferPoolItem.objects.filter(pool_id__in=pool_ids)
            .filter(
                models_q_sold(OfferPoolItemStatus, sold_clone_item_ids),
            )
            .select_related("owned_product", "pool_offer", "pool_offer__listing")
        )

        # Orders already bound to any pool item (never reuse one order twice).
        bound_order_ids = set(
            PoolSaleEvent.objects.filter(order_id__isnull=False)
            .values_list("order_id", flat=True)
        )
        # Existing (possibly order-less) sale events per item.
        events_by_item: dict[int, list] = {}
        for ev in PoolSaleEvent.objects.filter(pool_item_id__in=[i.pk for i in items]):
            events_by_item.setdefault(ev.pool_item_id, []).append(ev)

        bindable, filled, no_order, no_offer, already = [], [], [], [], 0

        for item in items:
            existing = events_by_item.get(item.pk, [])
            if any(ev.order_id for ev in existing):
                already += 1
                continue

            if not item.owned_product_id:
                no_order.append((item, "item has no OwnedProduct"))
                continue

            candidates = list(
                Order.objects.filter(owned_product_id=item.owned_product_id)
                .exclude(status__in=[OrderStatus.CANCELLED, OrderStatus.REFUNDED])
                .exclude(pk__in=bound_order_ids)
                .select_related("integration_account", "listing")
                .order_by("-sold_at", "-created_at")
            )
            if not candidates:
                no_order.append((item, "no unbound non-cancelled order for this account"))
                continue

            order = _closest_order(candidates, item.consumed_at)

            # An order-less event already exists for this item → just fill it.
            orderless = next((ev for ev in existing if not ev.order_id), None)
            if orderless is not None:
                filled.append((item, order, orderless))
            else:
                if not item.pool_offer_id:
                    no_offer.append((item, order))
                    continue
                bindable.append((item, order))
            bound_order_ids.add(order.pk)  # reserve so it is not reused this run

        self._report(bindable, filled, no_order, no_offer, already, apply)

        if not apply:
            self.stdout.write(self.style.WARNING(
                "\nDRY RUN — re-run with --apply to persist these bindings."
            ))
            return

        created = 0
        with transaction.atomic():
            for item, order in bindable:
                listing = order.listing or item.pool_offer.listing
                _bind_event(
                    PoolSaleEvent, item=item, order=order,
                    pool_offer=item.pool_offer, listing=listing,
                )
                _confirm_item_sold(item, order)
                created += 1
            for item, order, ev in filled:
                ev.order_id = order.pk
                ev.outcome = ev.outcome or "processed"
                ev.processed_at = ev.processed_at or timezone.now()
                if ev.pool_item_id is None:
                    ev.pool_item = item
                ev.save(update_fields=["order_id", "outcome", "processed_at", "pool_item"])
                _confirm_item_sold(item, order)
                created += 1

        self.stdout.write(self.style.SUCCESS(
            f"\nApplied: bound {created} pool item(s) to verified orders."
        ))

    def _report(self, bindable, filled, no_order, no_offer, already, apply):
        verb = "Will bind" if apply else "Would bind"
        self.stdout.write(self.style.MIGRATE_HEADING(
            f"{verb} {len(bindable) + len(filled)} sold-but-unbound pool item(s)"
        ))
        for item, order in bindable:
            self.stdout.write(
                f"  item #{item.pk} {_login(item)} -> Order #{order.pk} "
                f"({order.store_order_id} / {getattr(order.integration_account, 'provider', '?')})"
            )
        for item, order, _ev in filled:
            self.stdout.write(
                f"  item #{item.pk} {_login(item)} -> fill existing event with "
                f"Order #{order.pk} ({order.store_order_id})"
            )
        if already:
            self.stdout.write(f"  ({already} item(s) already bound — skipped)")
        if no_offer:
            self.stdout.write(self.style.WARNING(
                f"\n{len(no_offer)} item(s) have a matching order but no pool_offer lane "
                "(cannot attribute to a store card):"
            ))
            for item, order in no_offer:
                self.stdout.write(f"  item #{item.pk} {_login(item)} <- Order #{order.pk}")
        if no_order:
            self.stdout.write(self.style.WARNING(
                f"\n{len(no_order)} sold item(s) have NO local order to bind "
                "(likely the marketplace order was never ingested — re-run order sync "
                "or recover the order by id):"
            ))
            for item, reason in no_order:
                self.stdout.write(f"  item #{item.pk} {_login(item)} — {reason}")


def models_q_sold(OfferPoolItemStatus, sold_clone_item_ids):
    """Q filter: CONSUMED items OR items tied to a SOLD PlayerAuctions clone."""
    from django.db.models import Q

    return Q(status=OfferPoolItemStatus.CONSUMED) | Q(pk__in=sold_clone_item_ids)


def _closest_order(candidates, when):
    """Pick the order whose sold_at is nearest ``when`` (fallback: newest)."""
    if when is None:
        return candidates[0]
    def _distance(order):
        ref = order.sold_at or order.created_at
        return abs((ref - when).total_seconds()) if ref else float("inf")
    return min(candidates, key=_distance)


def _bind_event(PoolSaleEvent, *, item, order, pool_offer, listing):
    PoolSaleEvent.objects.get_or_create(
        event_key=f"reconcile-binding:item:{item.pk}:order:{order.pk}",
        defaults={
            "listing": listing,
            "pool_offer": pool_offer,
            "pool_item": item,
            "order_id": order.pk,
            "outcome": "processed",
            "processed_at": timezone.now(),
        },
    )


def _confirm_item_sold(item, order):
    """Promote a reconciliation-consumed item to a verified sold state."""
    from apps.posting.models import OfferPoolItemStatus

    fields = []
    if item.status != OfferPoolItemStatus.CONSUMED:
        item.status = OfferPoolItemStatus.CONSUMED
        fields.append("status")
    if item.consumed_at is None:
        item.consumed_at = order.sold_at or timezone.now()
        fields.append("consumed_at")
    if item.remote_state != "sold":
        item.remote_state = "sold"
        fields.append("remote_state")
    if fields:
        fields.append("updated_at")
        item.save(update_fields=fields)


def _login(item):
    return getattr(getattr(item, "owned_product", None), "login", "—")
