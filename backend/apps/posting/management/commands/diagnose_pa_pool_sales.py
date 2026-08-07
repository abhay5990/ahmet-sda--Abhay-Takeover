"""Read-only report of PlayerAuctions pool sales the system likely MISSED.

PlayerAuctions order fetching (and clone posting) go through the browser-session
relay, which fails with 401/Unauthorized far more than the direct REST APIs used
by Eldorado/GameBoost. When PA order sync fails, no Order rows are ingested, so
``notify_sale`` never fires and the pool is neither marked sold nor replenished
(no new stock). The backup pool sweep also aborts on Unauthorized.

This command surfaces, from LOCAL data only (no marketplace calls), the likely
missed PA sales for a game (default GTA) in the last N hours, so an operator can
see exactly what was missed and act (re-run order sync, warm the relay session,
then reconcile/replenish). Nothing is mutated.

Examples::

    python manage.py diagnose_pa_pool_sales                 # GTA, last 48h
    python manage.py diagnose_pa_pool_sales --hours 72
    python manage.py diagnose_pa_pool_sales --game grand-theft-auto-5 --account playerauctions-csgosmurfkings
"""
from __future__ import annotations

import json
from datetime import timedelta

from django.core.management.base import BaseCommand
from django.db.models import Exists, OuterRef, Q
from django.utils import timezone


class Command(BaseCommand):
    help = "Report PlayerAuctions pool sales the system likely missed (read-only)."

    def add_arguments(self, parser):
        parser.add_argument("--hours", type=int, default=48)
        parser.add_argument(
            "--game", default="grand-theft-auto",
            help="Game slug prefix (default: grand-theft-auto).",
        )
        parser.add_argument(
            "--account", default=None,
            help="Optional PlayerAuctions IntegrationAccount slug to scope to.",
        )
        parser.add_argument(
            "--json", default=None, dest="json_path",
            help="Optional path to write a machine-readable JSON report.",
        )

    def handle(self, *args, **options):
        from apps.orders.models import Order
        from apps.posting.models import (
            OfferPoolActiveOffer,
            OfferPoolActiveOfferStatus,
            OfferPoolItem,
            OfferPoolItemStatus,
            PoolOffer,
            PoolSaleEvent,
        )

        hours = max(1, options["hours"])
        since = timezone.now() - timedelta(hours=hours)
        prefix = options["game"]
        account = options["account"]

        pa = {"integration_account__provider": "playerauctions"}
        pa_offer = {"pool_offer__listing__integration_account__provider": "playerauctions"}
        pool_game = {"pool_offer__pool__game__slug__startswith": prefix}
        if account:
            pa["integration_account__slug"] = account
            pa_offer["pool_offer__listing__integration_account__slug"] = account

        report: dict = {"hours": hours, "game_prefix": prefix, "account": account}

        # ── A. PA orders in window: bound to a pool sale event? listing matched? ──
        gta_order_q = (
            Q(game__slug__startswith=prefix)
            | Q(listing__game__slug__startswith=prefix)
        )
        orders = (
            Order.objects.filter(created_at__gte=since, **pa)
            .filter(gta_order_q)
            .annotate(bound=Exists(PoolSaleEvent.objects.filter(order_id=OuterRef("pk"))))
            .select_related("integration_account", "listing", "game")
            .order_by("-created_at")
        )
        unbound = [o for o in orders if not o.bound]
        # PA orders with a store_listing_id that never matched a Listing → the
        # reactive notify_sale path literally cannot fire for these.
        no_listing = [
            o for o in orders if o.store_listing_id and o.listing_id is None
        ]

        self.stdout.write(self.style.MIGRATE_HEADING(
            f"A. PlayerAuctions {prefix}* orders in last {hours}h: {orders.count()}"
        ))
        for o in unbound:
            self.stdout.write(
                f"  MISSED order {o.store_order_id} (id {o.pk}) offer={o.store_listing_id or '—'} "
                f"listing={'—' if o.listing_id is None else o.listing_id} "
                f"sold_at={o.sold_at or o.created_at:%Y-%m-%d %H:%M} — no PoolSaleEvent"
            )
        if not unbound:
            self.stdout.write("  (every PA order in window is bound to a pool sale event)")
        report["orders_total"] = orders.count()
        report["orders_unbound"] = [
            {"order_id": o.pk, "store_order_id": o.store_order_id,
             "store_listing_id": o.store_listing_id, "listing_id": o.listing_id}
            for o in unbound
        ]
        report["orders_no_listing_match"] = [o.store_order_id for o in no_listing]

        # ── B. PA clones DELISTED/SOLD in window with NO sale event = missed sale ──
        clones = (
            OfferPoolActiveOffer.objects.filter(
                updated_at__gte=since,
                status__in=[
                    OfferPoolActiveOfferStatus.DELISTED,
                    OfferPoolActiveOfferStatus.SOLD,
                ],
                **pa_offer, **pool_game,
            )
            .annotate(bound=Exists(
                PoolSaleEvent.objects.filter(
                    Q(listing_id=OuterRef("listing_id"))
                    | Q(pool_item_id=OuterRef("pool_item_id"))
                )
            ))
            .select_related("listing", "pool_offer", "pool_item__owned_product")
            .order_by("-updated_at")
        )
        missed_clones = [c for c in clones if not c.bound]
        self.stdout.write("")
        self.stdout.write(self.style.MIGRATE_HEADING(
            f"B. PA {prefix}* clones gone from marketplace (delisted/sold) with NO sale "
            f"event: {len(missed_clones)}"
        ))
        for c in missed_clones:
            login = getattr(getattr(c.pool_item, "owned_product", None), "login", "—")
            self.stdout.write(
                f"  MISSED sale: offer {c.store_listing_id} account {login} "
                f"status={c.status} at {c.updated_at:%Y-%m-%d %H:%M} — not recorded/replenished"
            )
        report["clones_missed"] = [
            {"store_listing_id": c.store_listing_id, "status": c.status,
             "login": getattr(getattr(c.pool_item, "owned_product", None), "login", None)}
            for c in missed_clones
        ]

        # ── C. PA GTA pool offers that look starved / auth-failing ──
        offers = (
            PoolOffer.objects.filter(
                listing__integration_account__provider="playerauctions",
                pool__game__slug__startswith=prefix,
            )
            .select_related("listing", "pool", "listing__integration_account")
        )
        if account:
            offers = offers.filter(listing__integration_account__slug=account)
        starved = []
        for po in offers:
            below = (
                po.current_remote_count is not None
                and po.current_remote_count <= po.threshold
            )
            stale = po.last_checked_at is None or po.last_checked_at < since
            if below or po.last_error or stale:
                starved.append(po)
        self.stdout.write("")
        self.stdout.write(self.style.MIGRATE_HEADING(
            f"C. PA {prefix}* pool offers that look starved / auth-failing: {len(starved)}"
        ))
        for po in starved:
            self.stdout.write(
                f"  pool_offer {po.pk} remote={po.current_remote_count} thr={po.threshold} "
                f"last_checked={po.last_checked_at:%Y-%m-%d %H:%M}" if po.last_checked_at
                else f"  pool_offer {po.pk} remote={po.current_remote_count} thr={po.threshold} last_checked=never"
            )
            if po.last_error:
                self.stdout.write(f"      last_error: {po.last_error[:160]}")
        report["offers_starved"] = [
            {"pool_offer_id": po.pk, "remote": po.current_remote_count,
             "threshold": po.threshold, "last_error": (po.last_error or "")[:200]}
            for po in starved
        ]

        # ── D. PUSHED items tied to SOLD/DELISTED clones (never consumed) ──
        stale_pushed = (
            OfferPoolItem.objects.filter(
                status=OfferPoolItemStatus.PUSHED,
                active_offers__status__in=[
                    OfferPoolActiveOfferStatus.SOLD,
                    OfferPoolActiveOfferStatus.DELISTED,
                ],
                **pa_offer, **pool_game,
            )
            .select_related("owned_product")
            .distinct()
        )
        self.stdout.write("")
        self.stdout.write(self.style.MIGRATE_HEADING(
            f"D. PA {prefix}* PUSHED items whose clone is already sold/delisted: "
            f"{stale_pushed.count()}"
        ))
        for it in stale_pushed:
            self.stdout.write(f"  item {it.pk} account {it.owned_product.login} still PUSHED")
        report["stale_pushed_items"] = [it.pk for it in stale_pushed]

        # ── Summary ──
        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS(
            f"SUMMARY (PA {prefix}*, last {hours}h): "
            f"unbound_orders={len(unbound)} | no_listing_match={len(no_listing)} | "
            f"missed_clone_sales={len(missed_clones)} | starved_offers={len(starved)} | "
            f"stale_pushed_items={stale_pushed.count()}"
        ))
        self.stdout.write(
            "Likely root cause if these are non-zero: PlayerAuctions relay/session "
            "auth failing (order sync throws → no orders → no notify_sale; pool sweep "
            "aborts on Unauthorized). Fix: restore the PA relay session for the store, "
            "then re-run `sync_orders <pa-account> --mode incremental` and "
            "`reconcile_pool_sale_bindings --apply`."
        )

        if options["json_path"]:
            with open(options["json_path"], "w", encoding="utf-8") as fh:
                json.dump(report, fh, indent=2, default=str)
            self.stdout.write(f"JSON written to {options['json_path']}")
