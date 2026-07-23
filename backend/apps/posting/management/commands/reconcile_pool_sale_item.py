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

        sold_clone_exists = OfferPoolActiveOffer.objects.filter(
            pool_offer_id=event.pool_offer_id,
            pool_item_id=event.pool_item_id,
            listing_id=event.listing_id,
            status=OfferPoolActiveOfferStatus.SOLD,
        ).exists()
        if not sold_clone_exists:
            raise CommandError(
                "No matching SOLD PlayerAuctions clone exists; refusing reconciliation."
            )

        item = event.pool_item
        if item.status == OfferPoolItemStatus.CONSUMED:
            self.stdout.write(self.style.SUCCESS(
                f"Event is already reconciled: pool item #{item.pk} is consumed."
            ))
            return
        if item.status != OfferPoolItemStatus.PUSHED:
            raise CommandError(
                f"Pool item #{item.pk} status is {item.status!r}, not 'pushed'; refusing reconciliation."
            )

        if not options["apply"]:
            self.stdout.write(
                "DRY RUN: verified event and SOLD clone match. "
                f"Would consume pool item #{item.pk}."
            )
            return

        with transaction.atomic():
            locked = OfferPoolItem.objects.select_for_update().get(pk=item.pk)
            if locked.status == OfferPoolItemStatus.CONSUMED:
                self.stdout.write(self.style.SUCCESS(
                    f"Event is already reconciled: pool item #{locked.pk} is consumed."
                ))
                return
            if locked.status != OfferPoolItemStatus.PUSHED:
                raise CommandError(
                    f"Pool item #{locked.pk} changed to {locked.status!r}; refusing reconciliation."
                )
            locked.status = OfferPoolItemStatus.CONSUMED
            locked.consumed_at = timezone.now()
            locked.remote_state = "sold"
            locked.error_message = ""
            locked.save(update_fields=[
                "status", "consumed_at", "remote_state", "error_message", "updated_at",
            ])

        self.stdout.write(self.style.SUCCESS(
            f"Reconciled verified sale: pool item #{item.pk} is now consumed."
        ))
