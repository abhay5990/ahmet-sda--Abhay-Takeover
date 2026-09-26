"""Safely finalize historically received SDA Mart Gmail sale events.

This command repairs only a narrow, durable state gap:

* the signed CodeTracker Gmail event is already stored in SDA;
* it records final automatic delivery;
* it already has one exact SDA Mart listing and order linkage;
* the listing is closed, the clone is DELISTED, and no PoolSaleEvent exists.

It never reads Gmail, calls PlayerAuctions, creates/edits/cancels a marketplace
listing, or replenishes a pool.  In ``--apply`` mode it reuses the normal signed
Gmail finalization helper.  That helper sets the existing order to DELIVERED and
records the exact clone/item as SOLD while passing ``allow_replenish=False``.

The command is dry-run by default and deliberately bounded to a date interval.
"""
from __future__ import annotations

from datetime import datetime, time, timezone as dt_timezone

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction


MART_SLUGS = (
    "csgosmurfkings",
    "ezsmurfmart",
    "playerauctions-csgosmurfkings",
)
DEFAULT_OBSERVED_FROM = "2026-09-01"
DEFAULT_OBSERVED_TO = "2026-10-01"
MAX_LIMIT = 50


def _utc_start_ms(value: str, *, option: str) -> int:
    try:
        parsed = datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError as exc:
        raise CommandError(f"{option} must use YYYY-MM-DD") from exc
    return int(datetime.combine(parsed, time.min, tzinfo=dt_timezone.utc).timestamp() * 1000)


def _event_in_window(event, *, observed_from_ms: int, observed_to_ms: int) -> bool:
    return observed_from_ms <= int(event.observed_at_ms) < observed_to_ms


def _validated_limit(value: int) -> int:
    limit = int(value)
    if not 1 <= limit <= MAX_LIMIT:
        raise CommandError(f"--limit must be between 1 and {MAX_LIMIT}")
    return limit


class Command(BaseCommand):
    help = (
        "Finalize exact historical Mart automatic-delivery Gmail events without "
        "replenishment. Dry-run by default."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--observed-from",
            default=DEFAULT_OBSERVED_FROM,
            help="Inclusive UTC Gmail observation date (YYYY-MM-DD).",
        )
        parser.add_argument(
            "--observed-to",
            default=DEFAULT_OBSERVED_TO,
            help="Exclusive UTC Gmail observation date (YYYY-MM-DD).",
        )
        parser.add_argument(
            "--limit",
            type=int,
            default=MAX_LIMIT,
            help=f"Maximum exact events to inspect/apply (1-{MAX_LIMIT}).",
        )
        parser.add_argument(
            "--apply",
            action="store_true",
            help="Persist the already-proven local sale handoffs.",
        )

    def handle(self, *args, **options):
        from apps.integrations.api.pa_gmail_order_event import (
            SOURCE,
            _finalize_exact_automatic_delivery,
        )
        from apps.integrations.models import PaGmailOrderEvent, Provider
        from apps.listings.enums import ListingStatus
        from apps.orders.enums import OrderStatus
        from apps.posting.models import OfferPoolActiveOffer, OfferPoolActiveOfferStatus, PoolSaleEvent
        from apps.posting.services.stock.pa_tracking import extract_tracking_code

        observed_from_ms = _utc_start_ms(options["observed_from"], option="--observed-from")
        observed_to_ms = _utc_start_ms(options["observed_to"], option="--observed-to")
        if observed_to_ms <= observed_from_ms:
            raise CommandError("--observed-to must be after --observed-from")
        limit = _validated_limit(options["limit"])
        apply = bool(options["apply"])

        candidates = []
        rejected: dict[str, int] = {}
        queryset = (
            PaGmailOrderEvent.objects.filter(
                source=SOURCE,
                automatic_delivery=True,
                observed_at_ms__gte=observed_from_ms,
                observed_at_ms__lt=observed_to_ms,
                integration_account__provider=Provider.PLAYERAUCTIONS,
                integration_account__slug__in=MART_SLUGS,
                listing__isnull=False,
                order__isnull=False,
            )
            .select_related("integration_account", "listing", "order")
            .order_by("observed_at_ms", "pk")
        )

        for event in queryset:
            if len(candidates) >= limit:
                break
            listing = event.listing
            order = event.order
            if listing.status != ListingStatus.CLOSED:
                rejected["listing_not_closed"] = rejected.get("listing_not_closed", 0) + 1
                continue
            if extract_tracking_code(listing.title) != event.tracking_code:
                rejected["tracking_code_mismatch"] = rejected.get("tracking_code_mismatch", 0) + 1
                continue
            if (
                order.integration_account_id != listing.integration_account_id
                or order.listing_id != listing.pk
                or str(order.store_listing_id) != str(listing.store_listing_id)
            ):
                rejected["order_linkage_mismatch"] = rejected.get("order_linkage_mismatch", 0) + 1
                continue
            if order.status != OrderStatus.PENDING:
                rejected["order_not_pending"] = rejected.get("order_not_pending", 0) + 1
                continue
            clones = list(
                OfferPoolActiveOffer.objects.filter(
                    listing=listing,
                    pool_item__isnull=False,
                    status=OfferPoolActiveOfferStatus.DELISTED,
                ).select_related("pool_item")
            )
            if len(clones) != 1:
                rejected["not_one_delisted_clone"] = rejected.get("not_one_delisted_clone", 0) + 1
                continue
            clone = clones[0]
            if PoolSaleEvent.objects.filter(
                pool_item_id=clone.pool_item_id,
            ).exists():
                rejected["pool_sale_exists"] = rejected.get("pool_sale_exists", 0) + 1
                continue
            candidates.append((event.pk, clone.pk))

        self.stdout.write(
            f"Scoped historical Mart Gmail events: candidates={len(candidates)} "
            f"rejected={sum(rejected.values())} window={options['observed_from']}..{options['observed_to']}"
        )
        for event_id, clone_id in candidates:
            event = PaGmailOrderEvent.objects.get(pk=event_id)
            self.stdout.write(
                f"  event={event.event_id} order={event.external_order_id} "
                f"code={event.tracking_code} clone={clone_id}"
            )
        if rejected:
            self.stdout.write("  rejected=" + ", ".join(
                f"{reason}:{count}" for reason, count in sorted(rejected.items())
            ))
        if not apply:
            self.stdout.write(self.style.WARNING(
                "DRY RUN — re-run with --apply only after reviewing the exact candidates."
            ))
            return

        finalized = 0
        for event_id, clone_id in candidates:
            with transaction.atomic():
                event = (
                    PaGmailOrderEvent.objects.select_for_update()
                    .select_related("listing", "order", "integration_account")
                    .get(pk=event_id)
                )
                clone = OfferPoolActiveOffer.objects.select_for_update().get(pk=clone_id)
                if PoolSaleEvent.objects.filter(pool_item_id=clone.pool_item_id).exists():
                    continue
                # This path contains its own exact listing/order/clone checks and
                # calls notify_sale(..., allow_replenish=False) on transaction
                # commit. It has no PlayerAuctions write capability.
                _finalize_exact_automatic_delivery(
                    event=event,
                    listing=event.listing,
                    order=event.order,
                )
            if PoolSaleEvent.objects.filter(pool_item_id=clone.pool_item_id, order_id=event.order_id).exists():
                finalized += 1
            else:
                raise CommandError(
                    f"event {event.event_id} did not produce an exact local PoolSaleEvent; stopped"
                )

        self.stdout.write(self.style.SUCCESS(
            f"Applied: finalized {finalized} exact historical Mart sale handoff(s); "
            "no replenishment or marketplace action was attempted."
        ))
