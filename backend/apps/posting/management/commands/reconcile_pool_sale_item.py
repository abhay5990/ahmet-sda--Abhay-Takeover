"""Reconcile an already-verified PlayerAuctions clone sale with its pool item.

This command is intentionally targeted and dry-run by default. It repairs only
a verified processed sale event whose exact active clone is already SOLD, but
whose linked pool item was left in PUSHED by an older notifier implementation.
"""

from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from apps.posting.models import (
    OfferPoolActiveOffer,
    OfferPoolActiveOfferStatus,
    OfferPoolItem,
    OfferPoolItemStatus,
    PoolSaleEvent,
    PoolOffer,
    PoolOfferStatus,
    PoolOfferStrategy,
    OfferPoolStatus,
)


class Command(BaseCommand):
    help = (
        "Consume the exact pool item for one already-verified PlayerAuctions "
        "clone sale event. Dry-run by default."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--event-key",
            required=True,
            help="Exact PoolSaleEvent event key to reconcile.",
        )
        parser.add_argument(
            "--apply",
            action="store_true",
            help="Persist the consumed state. Without this flag, only report eligibility.",
        )
        parser.add_argument(
            "--restore-lane",
            action="store_true",
            help=(
                "Reactivate only an eligible clone lane left in ERROR by the "
                "historic closed-listing signal. Requires --apply."
            ),
        )

    def handle(self, *args, **options):
        event_key = options["event_key"]
        event = (
            PoolSaleEvent.objects.select_related("pool_item", "pool_offer")
            .filter(event_key=event_key)
            .first()
        )
        if event is None:
            raise CommandError(f"No PoolSaleEvent found for event key: {event_key}")
        if event.pool_item_id is None:
            raise CommandError("Sale event has no exact pool item; refusing reconciliation.")
        if not event.order_id:
            raise CommandError("Sale event has no verified order ID; refusing reconciliation.")
        if event.outcome != "processed":
            raise CommandError(
                f"Sale event outcome is {event.outcome!r}, not 'processed'; refusing reconciliation."
            )

        pool_offer = PoolOffer.objects.select_related("pool").get(
            pk=event.pool_offer_id,
        )
        sold_clone_exists = OfferPoolActiveOffer.objects.filter(
            pool_offer_id=pool_offer.pk,
            pool_item_id=event.pool_item_id,
            listing_id=event.listing_id,
            status=OfferPoolActiveOfferStatus.SOLD,
        ).exists()
        if not sold_clone_exists:
            raise CommandError(
                "No matching SOLD PlayerAuctions clone exists; refusing reconciliation."
            )

        restore_lane = options["restore_lane"]
        if restore_lane:
            expected_error = "Listing status changed to closed"
            if pool_offer.strategy != PoolOfferStrategy.CLONE:
                raise CommandError("Pool offer is not a PlayerAuctions clone lane; refusing restore.")
            if pool_offer.pool.status != OfferPoolStatus.ACTIVE:
                raise CommandError("Parent pool is not active; refusing restore.")
            if pool_offer.status not in {PoolOfferStatus.ACTIVE, PoolOfferStatus.ERROR}:
                raise CommandError(
                    f"Pool offer status is {pool_offer.status!r}; refusing restore."
                )
            if (
                pool_offer.status == PoolOfferStatus.ERROR
                and pool_offer.last_error != expected_error
            ):
                raise CommandError(
                    "Pool offer error is not the historic closed-listing signal; refusing restore."
                )
            if not options["apply"]:
                self.stdout.write(
                    "DRY RUN: verified sold clone and closed-listing error match. "
                    f"Would reactivate pool offer #{pool_offer.pk}."
                )

        item = event.pool_item
        if item.status not in {OfferPoolItemStatus.PUSHED, OfferPoolItemStatus.CONSUMED}:
            raise CommandError(
                f"Pool item #{item.pk} status is {item.status!r}; refusing reconciliation."
            )

        if not options["apply"]:
            action = "consume" if item.status == OfferPoolItemStatus.PUSHED else "leave consumed"
            self.stdout.write(
                "DRY RUN: verified event and SOLD clone match. "
                f"Would {action} pool item #{item.pk}."
            )
            return

        with transaction.atomic():
            locked = OfferPoolItem.objects.select_for_update().get(pk=item.pk)
            locked_offer = PoolOffer.objects.select_for_update().get(pk=pool_offer.pk)
            if locked.status not in {OfferPoolItemStatus.PUSHED, OfferPoolItemStatus.CONSUMED}:
                raise CommandError(
                    f"Pool item #{locked.pk} changed to {locked.status!r}; refusing reconciliation."
                )
            if locked.status == OfferPoolItemStatus.PUSHED:
                locked.status = OfferPoolItemStatus.CONSUMED
                locked.consumed_at = timezone.now()
                locked.remote_state = "sold"
                locked.error_message = ""
                locked.save(update_fields=[
                    "status", "consumed_at", "remote_state", "error_message", "updated_at",
                ])
            if restore_lane and locked_offer.status == PoolOfferStatus.ERROR:
                locked_offer.status = PoolOfferStatus.ACTIVE
                locked_offer.last_error = ""
                locked_offer.current_remote_count = 0
                locked_offer.save(update_fields=[
                    "status", "last_error", "current_remote_count", "updated_at",
                ])

        state = "consumed" if item.status == OfferPoolItemStatus.PUSHED else "already consumed"
        result = f"Reconciled verified sale: pool item #{item.pk} is {state}."
        if restore_lane:
            result += f" Pool offer #{pool_offer.pk} is active for replacement."
        self.stdout.write(self.style.SUCCESS(result))
