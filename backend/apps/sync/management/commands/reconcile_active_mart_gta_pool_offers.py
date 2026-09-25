"""Guarded SDA-only recovery for active Mart GTA 5 pool clone state.

This command repairs local pool state only after the protected MCT Mart
Official active-offer snapshot confirms each *existing SDA-known* offer ID is
currently active. It never discovers offers, starts a browser/relay, creates,
edits, cancels, relists, or retries a marketplace request.

The command is dry-run by default. ``--execute`` changes only local SDA records
that still meet all sale, order, reservation, linkage, and remote-presence
checks inside a transaction immediately before the local handoff.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from apps.integrations.providers import registry
from apps.listings.enums import ListingStatus
from apps.listings.models import ListingOwnedProduct
from apps.orders.models import Order
from apps.posting.models import (
    OfferPoolActiveOffer,
    OfferPoolActiveOfferStatus,
    OfferPoolItem,
    OfferPoolItemStatus,
    PoolDispatchReservationStatus,
    PoolSaleEvent,
)

MART_ACCOUNT_SLUG = "playerauctions-csgosmurfkings"
GTA_GAME_SLUG = "grand-theft-auto-5"
DEFAULT_LIMIT = 50
MAX_LIMIT = 100
DEFAULT_SNAPSHOT_MAX_AGE_SECONDS = 600


@dataclass(frozen=True)
class SnapshotProof:
    active_offer_ids: frozenset[str]
    age_seconds: float | None


def _chunked(values: list[str], size: int) -> Iterable[list[str]]:
    for offset in range(0, len(values), size):
        yield values[offset:offset + size]


def _snapshot_is_fresh(age_seconds: Any, max_age_seconds: int) -> bool:
    try:
        return 0 <= float(age_seconds) <= max_age_seconds
    except (TypeError, ValueError):
        return False


def _result_error(result: Any) -> str:
    error = getattr(result, "error", None)
    message = getattr(error, "message", None)
    return str(message or error or "unknown provider error")[:240]


def _uses_mct_official_offer_snapshot(client: Any) -> bool:
    marker = getattr(client, "uses_mct_official_offer_snapshot", None)
    return bool(marker()) if callable(marker) else False


def _active_offer_ids_from_snapshot(
    client: Any,
    offer_ids: list[str],
    *,
    max_age_seconds: int,
) -> SnapshotProof:
    """Return fresh active-state proof for exact SDA-owned offer IDs only."""
    active_ids: set[str] = set()
    snapshot_age: float | None = None

    for batch in _chunked(offer_ids, MAX_LIMIT):
        result = client.list_offers(
            offer_ids=[int(value) for value in batch],
            listing_status="Active",
            page=1,
            page_size=len(batch),
        )
        if not getattr(result, "ok", False):
            raise CommandError(
                "Mart active-offer snapshot unavailable; no pool state was changed: "
                f"{_result_error(result)}"
            )
        meta = getattr(result, "meta", None) or {}
        age = meta.get("snapshot_age_seconds") if isinstance(meta, dict) else None
        if not _snapshot_is_fresh(age, max_age_seconds):
            raise CommandError(
                "Mart active-offer snapshot is stale or has no age proof; "
                "no pool state was changed."
            )
        parsed_age = float(age)
        snapshot_age = parsed_age if snapshot_age is None else max(snapshot_age, parsed_age)
        for offer in getattr(result, "data", None) or []:
            if not isinstance(offer, dict):
                continue
            offer_id = str(offer.get("offerId") or offer.get("offer_id") or "").strip()
            if offer_id:
                active_ids.add(offer_id)

    return SnapshotProof(
        active_offer_ids=frozenset(active_ids),
        age_seconds=snapshot_age,
    )


def _candidate_queryset(*, pool_id: int | None = None):
    """Only locally listed, stale-marked Mart GTA 5 clones are candidates."""
    filters = {
        "listing__integration_account__slug": MART_ACCOUNT_SLUG,
        "listing__game__slug": GTA_GAME_SLUG,
        "listing__status": ListingStatus.LISTED,
        "status__in": (
            OfferPoolActiveOfferStatus.DELISTED,
            OfferPoolActiveOfferStatus.FAILED,
        ),
    }
    if pool_id is not None:
        filters["pool_id"] = pool_id
    return (
        OfferPoolActiveOffer.objects.filter(**filters)
        .select_related(
            "listing__integration_account__credential",
            "pool_offer",
            "pool_item__owned_product",
        )
        .order_by("pk")
    )


def _local_block_reason(active_offer: OfferPoolActiveOffer) -> str | None:
    """Fail closed on every local state that could make revival unsafe."""
    listing = active_offer.listing
    item = active_offer.pool_item
    if listing is None or item is None or active_offer.pool_offer_id is None:
        return "missing local pool/listing linkage"
    if listing.status != ListingStatus.LISTED:
        return "listing is no longer locally listed"
    if listing.integration_account.slug != MART_ACCOUNT_SLUG:
        return "listing is not the Mart account"
    if listing.game.slug != GTA_GAME_SLUG:
        return "listing is not GTA 5"
    if str(active_offer.store_listing_id) != str(listing.store_listing_id):
        return "active-offer ID and listing ID differ"
    if not str(active_offer.store_listing_id).isdigit():
        return "offer ID is not numeric"
    if item.pool_offer_id != active_offer.pool_offer_id:
        return "pool item is assigned to a different pool offer"
    if item.status not in {OfferPoolItemStatus.FAILED, OfferPoolItemStatus.PUSHED}:
        return f"pool item state is {item.status}"
    if item.target_offer_id and item.target_offer_id != str(active_offer.store_listing_id):
        return "pool item target offer ID differs"
    if not ListingOwnedProduct.objects.filter(
        listing=listing,
        owned_product_id=item.owned_product_id,
    ).exists():
        return "listing is not linked to the pool item product"
    if Order.objects.filter(
        integration_account=listing.integration_account,
        store_listing_id=listing.store_listing_id,
    ).exists():
        return "exact listing order exists"
    if PoolSaleEvent.objects.filter(listing=listing).exists():
        return "exact pool sale event exists"
    if OfferPoolActiveOffer.objects.filter(
        listing=listing,
        status=OfferPoolActiveOfferStatus.SOLD,
    ).exists():
        return "a clone for this listing is sold"
    if Order.objects.filter(owned_product_id=item.owned_product_id).exists():
        return "pool item product has an order"
    if PoolSaleEvent.objects.filter(pool_item=item).exists():
        return "pool item has a sale event"
    if OfferPoolItem.objects.filter(
        owned_product_id=item.owned_product_id,
        reservation__status=PoolDispatchReservationStatus.ACTIVE,
    ).exists():
        return "pool item product has an active reservation"
    if OfferPoolActiveOffer.objects.filter(
        pool_item=item,
        status=OfferPoolActiveOfferStatus.ACTIVE,
    ).exclude(pk=active_offer.pk).exists():
        return "pool item already has another active clone"
    return None


def _restore_local_active_state(active_offer_id: int) -> tuple[bool, str]:
    """Recheck and restore one exact local clone inside a DB transaction."""
    with transaction.atomic():
        active_offer = (
            OfferPoolActiveOffer.objects.select_for_update()
            .select_related(
                "listing__integration_account",
                "listing__game",
                "pool_offer",
                "pool_item__owned_product",
            )
            .get(pk=active_offer_id)
        )
        if active_offer.status not in {
            OfferPoolActiveOfferStatus.DELISTED,
            OfferPoolActiveOfferStatus.FAILED,
        }:
            return False, f"active-offer state changed to {active_offer.status}"
        reason = _local_block_reason(active_offer)
        if reason:
            return False, reason

        item = active_offer.pool_item
        assert item is not None
        active_offer.status = OfferPoolActiveOfferStatus.ACTIVE
        active_offer.save(update_fields=["status", "updated_at"])

        item.status = OfferPoolItemStatus.PUSHED
        item.target_offer_id = str(active_offer.store_listing_id)
        item.failure_stage = ""
        item.remote_state = "present"
        item.error_message = ""
        item.save(update_fields=[
            "status",
            "target_offer_id",
            "failure_stage",
            "remote_state",
            "error_message",
            "updated_at",
        ])
        return True, "restored exact active snapshot match"


class Command(BaseCommand):
    help = (
        "Dry-run or restore SDA Mart GTA 5 pool rows only after a fresh exact-ID "
        "Official active-offer snapshot confirms the existing offer is live."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--execute",
            action="store_true",
            help="Apply only the locally safe exact-ID recoveries shown by the dry run.",
        )
        parser.add_argument(
            "--limit",
            type=int,
            default=DEFAULT_LIMIT,
            help=f"Maximum candidate rows to inspect (1-{MAX_LIMIT}, default {DEFAULT_LIMIT}).",
        )
        parser.add_argument(
            "--snapshot-max-age-seconds",
            type=int,
            default=DEFAULT_SNAPSHOT_MAX_AGE_SECONDS,
            help="Reject a snapshot older than this limit (default 600).",
        )
        parser.add_argument(
            "--pool-id",
            type=int,
            default=None,
            help="Restrict recovery to one exact SDA pool ID.",
        )

    def handle(self, *args, **options):
        limit = int(options["limit"])
        if not 1 <= limit <= MAX_LIMIT:
            raise CommandError(f"--limit must be between 1 and {MAX_LIMIT}")
        max_age = int(options["snapshot_max_age_seconds"])
        if max_age < 1:
            raise CommandError("--snapshot-max-age-seconds must be positive")
        pool_id = options.get("pool_id")
        if pool_id is not None and int(pool_id) < 1:
            raise CommandError("--pool-id must be positive")

        candidates = list(_candidate_queryset(pool_id=pool_id)[:limit])
        stats = {
            "selected": len(candidates),
            "snapshot_active": 0,
            "snapshot_absent": 0,
            "local_protected": 0,
            "ready": 0,
            "restored": 0,
            "changed_before_apply": 0,
        }
        if not candidates:
            scope = f" in pool {pool_id}" if pool_id is not None else ""
            self.stdout.write(
                f"No locally listed Mart GTA 5 failed/delisted pool rows found{scope}."
            )
            return

        account = candidates[0].listing.integration_account
        try:
            client = registry.get_or_build_client("playerauctions", account.credential)
        except Exception as exc:
            raise CommandError(
                f"Unable to build Mart snapshot client; no pool state was changed: {exc}"
            ) from exc
        if not _uses_mct_official_offer_snapshot(client):
            raise CommandError(
                "Mart client is not the protected Official snapshot client; "
                "no pool state was changed."
            )

        proof = _active_offer_ids_from_snapshot(
            client,
            [str(row.store_listing_id) for row in candidates],
            max_age_seconds=max_age,
        )
        ready_ids: list[int] = []
        for row in candidates:
            offer_id = str(row.store_listing_id)
            if offer_id not in proof.active_offer_ids:
                stats["snapshot_absent"] += 1
                self.stdout.write(f"SKIP {offer_id}: absent from fresh official active snapshot")
                continue
            stats["snapshot_active"] += 1
            reason = _local_block_reason(row)
            if reason:
                stats["local_protected"] += 1
                self.stdout.write(f"SKIP {offer_id}: {reason}")
                continue
            ready_ids.append(row.pk)
            stats["ready"] += 1
            self.stdout.write(f"READY {offer_id}: exact live snapshot match and local safety checks passed")

        if not options["execute"]:
            self.stdout.write(
                "DRY RUN: " + " ".join(f"{key}={value}" for key, value in stats.items())
                + f" snapshot_age_seconds={proof.age_seconds:g}"
            )
            return

        for active_offer_id in ready_ids:
            restored, result = _restore_local_active_state(active_offer_id)
            if restored:
                stats["restored"] += 1
                self.stdout.write(self.style.SUCCESS(
                    f"RESTORED pool active-offer row {active_offer_id}: {result}"
                ))
            else:
                stats["changed_before_apply"] += 1
                self.stdout.write(f"SKIP pool active-offer row {active_offer_id}: {result}")

        self.stdout.write(
            "EXECUTED: " + " ".join(f"{key}={value}" for key, value in stats.items())
            + f" snapshot_age_seconds={proof.age_seconds:g} at={timezone.now().isoformat()}"
        )
