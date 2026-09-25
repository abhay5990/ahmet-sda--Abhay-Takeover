"""Guarded, SDA-only recovery for expired Mart PlayerAuctions account offers.

This command deliberately considers only listings already owned by SDA Django.
It uses the fresh MCT-backed Official API *active-offer snapshot* solely as an
absence proof.  It never searches MCT listings, starts a browser/relay session,
or infers a sale from a title, game, or credential.

The command is dry-run by default.  ``--execute`` makes one official create
attempt per candidate only after every selected offer has been confirmed absent
from a fresh active-offer snapshot.  An unknown create outcome is not retried.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable

from django.core.management.base import BaseCommand, CommandError
from django.db.models import Count
from django.utils import timezone

from apps.integrations.providers import registry
from apps.integrations.providers.playerauctions import _normalize_official_account_payload
from apps.listings.enums import ListingStatus
from apps.listings.models import Listing
from apps.orders.models import Order
from apps.posting.models import (
    OfferPoolActiveOffer,
    OfferPoolActiveOfferStatus,
    OfferPoolItem,
    PoolDispatchReservationStatus,
    PoolSaleEvent,
)
from apps.posting.services.relist import (
    _extract_offer_id,
    _extract_payload,
    _replace_in_db,
)

MART_ACCOUNT_SLUG = "playerauctions-csgosmurfkings"
DEFAULT_LIMIT = 50
MAX_LIMIT = 100
DEFAULT_SNAPSHOT_MAX_AGE_SECONDS = 600


@dataclass(frozen=True)
class SnapshotProof:
    active_offer_ids: frozenset[str]
    age_seconds: float | None


def _is_official_mart_client(client: Any) -> bool:
    marker = getattr(client, "uses_mct_official_offer_snapshot", None)
    return bool(marker()) if callable(marker) else False


def _snapshot_is_fresh(age_seconds: Any, max_age_seconds: int) -> bool:
    try:
        return 0 <= float(age_seconds) <= max_age_seconds
    except (TypeError, ValueError):
        return False


def _result_error(result: Any) -> str:
    error = getattr(result, "error", None)
    message = getattr(error, "message", None)
    return str(message or error or "unknown provider error")[:240]


def _chunked(values: list[str], size: int) -> Iterable[list[str]]:
    for offset in range(0, len(values), size):
        yield values[offset : offset + size]


def _active_offer_ids_from_snapshot(client: Any, offer_ids: list[str], *, max_age_seconds: int) -> SnapshotProof:
    """Obtain fresh active-state proof for known SDA IDs only.

    The snapshot endpoint is intentionally exact-ID based.  A candidate absent
    from a complete fresh response is eligible to be considered for recreation;
    snapshot errors and stale responses fail closed.
    """
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
                "Mart active-offer snapshot unavailable; no relist was attempted: "
                f"{_result_error(result)}"
            )
        meta = getattr(result, "meta", None) or {}
        age = meta.get("snapshot_age_seconds") if isinstance(meta, dict) else None
        if not _snapshot_is_fresh(age, max_age_seconds):
            raise CommandError(
                "Mart active-offer snapshot is stale or has no age proof; no relist was attempted."
            )
        parsed_age = float(age)
        snapshot_age = parsed_age if snapshot_age is None else max(snapshot_age, parsed_age)
        for offer in getattr(result, "data", None) or []:
            if not isinstance(offer, dict):
                continue
            offer_id = str(offer.get("offerId") or offer.get("offer_id") or "").strip()
            if offer_id:
                active_ids.add(offer_id)
    return SnapshotProof(active_offer_ids=frozenset(active_ids), age_seconds=snapshot_age)


def _has_local_sale_or_reservation_evidence(listing: Listing) -> bool:
    """Fail closed on exact local sale, clone-sale, or active reservation evidence."""
    if Order.objects.filter(
        integration_account=listing.integration_account,
        store_listing_id=listing.store_listing_id,
    ).exists():
        return True
    if PoolSaleEvent.objects.filter(listing=listing).exists():
        return True
    if OfferPoolActiveOffer.objects.filter(
        listing=listing,
        status=OfferPoolActiveOfferStatus.SOLD,
    ).exists():
        return True
    owned_product_ids = list(
        listing.listing_owned_products.values_list("owned_product_id", flat=True)
    )
    if len(owned_product_ids) != 1:
        return True
    if Order.objects.filter(owned_product_id=owned_product_ids[0]).exists():
        return True
    return OfferPoolItem.objects.filter(
        owned_product_id=owned_product_ids[0],
        reservation__status=PoolDispatchReservationStatus.ACTIVE,
    ).exists()


def _candidate_queryset():
    """Return expired SDA Mart records with only structural safe preconditions.

    Remote absence proof, full create payload validation, and exact local guard
    rechecks are intentionally performed later for every selected record.
    """
    return (
        Listing.objects.filter(
            integration_account__slug=MART_ACCOUNT_SLUG,
            status=ListingStatus.LISTED,
            marketplace_expires_at__isnull=False,
            marketplace_expires_at__lte=timezone.now(),
        )
        .annotate(owned_product_count=Count("listing_owned_products", distinct=True))
        .filter(owned_product_count=1, store_listing_id__regex=r"^[0-9]+$")
        .filter(orders__isnull=True, pool_sale_events__isnull=True)
        .exclude(pool_active_offers__status=OfferPoolActiveOfferStatus.SOLD)
        .exclude(
            listing_owned_products__owned_product__orders__isnull=False,
        )
        .exclude(
            listing_owned_products__owned_product__pool_items__reservation__status=(
                PoolDispatchReservationStatus.ACTIVE
            ),
        )
        .select_related("integration_account__credential")
        .prefetch_related("listing_owned_products__owned_product")
        .distinct()
        .order_by("marketplace_expires_at", "pk")
    )


class Command(BaseCommand):
    help = (
        "Dry-run or recreate SDA-owned expired PA Mart offers only after fresh "
        "Official active-snapshot absence and exact local safety checks."
    )

    def add_arguments(self, parser):
        parser.add_argument("--execute", action="store_true", help="Perform one non-retryable create per ready record.")
        parser.add_argument(
            "--limit",
            type=int,
            default=DEFAULT_LIMIT,
            help=f"Maximum records to inspect per run (1-{MAX_LIMIT}, default {DEFAULT_LIMIT}).",
        )
        parser.add_argument(
            "--snapshot-max-age-seconds",
            type=int,
            default=DEFAULT_SNAPSHOT_MAX_AGE_SECONDS,
            help="Reject the active-offer snapshot when older than this value (default 600).",
        )

    def handle(self, *args, **options):
        limit = int(options["limit"])
        if not 1 <= limit <= MAX_LIMIT:
            raise CommandError(f"--limit must be between 1 and {MAX_LIMIT}")
        max_age = int(options["snapshot_max_age_seconds"])
        if max_age < 1:
            raise CommandError("--snapshot-max-age-seconds must be positive")

        candidates = list(_candidate_queryset()[:limit])
        stats = {
            "selected": len(candidates),
            "remote_active": 0,
            "local_protected": 0,
            "payload_invalid": 0,
            "ready": 0,
            "created": 0,
            "failed": 0,
        }
        if not candidates:
            self.stdout.write("No structurally eligible expired SDA Mart listings found.")
            return

        account = candidates[0].integration_account
        try:
            client = registry.get_or_build_client("playerauctions", account.credential)
        except Exception as exc:
            raise CommandError(f"Unable to build Mart client; no relist was attempted: {exc}") from exc
        if not _is_official_mart_client(client):
            raise CommandError("Mart client is not the protected Official snapshot/delegation client; no relist was attempted.")

        proof = _active_offer_ids_from_snapshot(
            client,
            [str(listing.store_listing_id) for listing in candidates],
            max_age_seconds=max_age,
        )
        provider = registry.get_provider("playerauctions")
        ready: list[tuple[Listing, dict[str, Any]]] = []
        for listing in candidates:
            offer_id = str(listing.store_listing_id)
            if offer_id in proof.active_offer_ids:
                stats["remote_active"] += 1
                self.stdout.write(f"SKIP {offer_id}: confirmed active in fresh official snapshot")
                continue
            if _has_local_sale_or_reservation_evidence(listing):
                stats["local_protected"] += 1
                self.stdout.write(f"SKIP {offer_id}: exact local sale, order, or reservation evidence exists")
                continue
            payload = _extract_payload(listing, "playerauctions", client=client)
            if not payload:
                stats["payload_invalid"] += 1
                self.stdout.write(f"SKIP {offer_id}: complete create payload is unavailable")
                continue
            # Validate against the official Account Offer contract without
            # retaining or printing any delivery fields. A create always uses
            # this normalized shape, never a partial historical payload.
            official_payload = _normalize_official_account_payload(payload, None)
            if official_payload is None:
                stats["payload_invalid"] += 1
                self.stdout.write(f"SKIP {offer_id}: complete official create payload is unavailable")
                continue
            ready.append((listing, official_payload))
            stats["ready"] += 1
            self.stdout.write(f"READY {offer_id}: expired, snapshot-absent, and locally unprotected")

        if not options["execute"]:
            self.stdout.write(
                "DRY RUN: " + " ".join(f"{key}={value}" for key, value in stats.items())
                + f" snapshot_age_seconds={proof.age_seconds:g}"
            )
            return

        for listing, payload in ready:
            offer_id = str(listing.store_listing_id)
            # Recheck immediately before each non-idempotent create so prior
            # records in this bounded run cannot invalidate its safety proof.
            if _has_local_sale_or_reservation_evidence(listing):
                stats["local_protected"] += 1
                self.stdout.write(f"SKIP {offer_id}: local safety state changed before create")
                continue
            try:
                result = provider.create_listing(client, {"payload": payload})
            except Exception as exc:
                stats["failed"] += 1
                self.stdout.write(self.style.ERROR(
                    f"FAILED {offer_id}: create transport outcome is unknown; not retried ({exc})"
                ))
                continue
            if not getattr(result, "ok", False):
                stats["failed"] += 1
                self.stdout.write(self.style.ERROR(
                    f"FAILED {offer_id}: create outcome not confirmed; not retried ({_result_error(result)})"
                ))
                continue
            new_offer_id = _extract_offer_id(result, "playerauctions")
            if not new_offer_id or not str(new_offer_id).isdigit():
                stats["failed"] += 1
                self.stdout.write(self.style.ERROR(
                    f"FAILED {offer_id}: create response lacks a confirmed numeric offer ID; not retried"
                ))
                continue
            try:
                response_data = getattr(result, "data", result)
                new_listing = _replace_in_db(
                    listing,
                    str(new_offer_id),
                    response_data,
                    payload,
                    client=client,
                )
            except Exception as exc:
                stats["failed"] += 1
                self.stdout.write(self.style.ERROR(
                    f"FAILED {offer_id}: new offer {new_offer_id} was confirmed but SDA handoff needs manual reconciliation ({exc})"
                ))
                continue
            stats["created"] += 1
            self.stdout.write(self.style.SUCCESS(
                f"RELISTED {offer_id} -> {new_listing.store_listing_id}: official create confirmed"
            ))

        self.stdout.write(
            "EXECUTED: " + " ".join(f"{key}={value}" for key, value in stats.items())
            + f" snapshot_age_seconds={proof.age_seconds:g}"
        )
