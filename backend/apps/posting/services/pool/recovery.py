"""Staff-initiated recovery for pool keys that are verified not sold.

The recovery operation is intentionally conservative: confirmed sale evidence
always wins, and a remote API error never becomes permission to reuse a key.
When the credential is still live remotely it is restored to ``PUSHED``;
when it is absent remotely it is detached and returned to ``PENDING`` stock.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from django.db import transaction

from apps.integrations.providers.registry import get_or_build_client
from apps.integrations.proxy_pool import build_proxy_pool, get_group_name
from apps.listings.models import ListingOwnedProduct
from apps.posting.models import (
    OfferPoolActiveOffer,
    OfferPoolActiveOfferStatus,
    OfferPoolItem,
    OfferPoolItemStatus,
    PoolSaleEvent,
)

from .formatter import format_credential_for_marketplace
from .replenisher import _PoolOfferContext


@dataclass
class RecoverUnsoldResult:
    ok: bool
    state: str = ""
    message: str = ""
    errors: list[str] = field(default_factory=list)


def recover_verified_unsold_item(*, pool_id: int, item_id: int) -> RecoverUnsoldResult:
    """Safely restore an unsold pool key after checking local and remote evidence."""
    try:
        item = (
            OfferPoolItem.objects.select_related(
                "pool_offer__pool",
                "pool_offer__listing",
                "pool_offer__listing__integration_account",
                "pool_offer__listing__integration_account__credential",
                "owned_product",
            )
            .get(pk=item_id, pool_id=pool_id)
        )
    except OfferPoolItem.DoesNotExist:
        return RecoverUnsoldResult(ok=False, errors=["Item not found"])

    if item.status == OfferPoolItemStatus.PENDING and not item.pool_offer_id:
        return RecoverUnsoldResult(
            ok=True,
            state="available",
            message="This key is already available in the pool.",
        )
    if item.status in {OfferPoolItemStatus.RESERVED, OfferPoolItemStatus.QUEUED}:
        return RecoverUnsoldResult(
            ok=False,
            errors=["This key is currently being dispatched and cannot be recovered."],
        )
    if PoolSaleEvent.objects.filter(pool_item_id=item.pk).exists():
        return RecoverUnsoldResult(
            ok=False,
            errors=["Confirmed marketplace sale evidence exists for this key; it cannot be returned to the pool."],
        )

    if not item.pool_offer_id:
        return _make_available(item, "No marketplace assignment remains; key returned to available pool stock.")

    pool_offer = item.pool_offer
    if (
        pool_offer.marketplace == "playerauctions"
        and item.remote_state == "absent"
    ):
        return _make_available(
            item,
            "The PlayerAuctions clone was already confirmed absent locally; key returned to available pool stock.",
        )
    if pool_offer.marketplace == "playerauctions":
        return _recover_playerauctions_item(item)
    return _recover_append_item(item)


def _recover_append_item(item: OfferPoolItem) -> RecoverUnsoldResult:
    """Verify Eldorado/GameBoost credential presence using remote IDs first."""
    from .checker import _get_remote_credentials

    pool_offer = item.pool_offer
    pool_ctx = _PoolOfferContext(pool_offer)
    try:
        remote_count, remote_credentials, remote_credential_ids = _get_remote_credentials(
            pool_ctx, pool_offer.marketplace,
        )
    except Exception as exc:  # Remote failure must never make stock available.
        return RecoverUnsoldResult(ok=False, errors=[f"Remote verification failed: {exc}"])

    if remote_count is None:
        return RecoverUnsoldResult(
            ok=False,
            errors=["Remote verification was unavailable; the key was not changed."],
        )
    if remote_count == -1:
        return RecoverUnsoldResult(
            ok=False,
            errors=["The marketplace offer no longer exists; recreate or relink the offer before recovering this key."],
        )

    remote_id = str(item.remote_credential_id or "").strip()
    is_live = bool(remote_id and remote_credential_ids is not None and remote_id in remote_credential_ids)
    # Legacy GameBoost offers expose one credential through get_offer() but no
    # immutable ID or list payload.  Such an offer can only contain this item,
    # so a positive verified stock count is safe live-presence evidence.
    if (
        not is_live
        and pool_offer.marketplace == "gameboost"
        and remote_credentials is None
        and remote_credential_ids is None
        and remote_count > 0
    ):
        is_live = True
    if not is_live and remote_credential_ids is None and remote_credentials is not None:
        expected = format_credential_for_marketplace(
            item.owned_product, pool_offer.marketplace, pool=pool_offer.pool,
        )
        is_live = expected in remote_credentials

    if is_live:
        return _restore_live_item(item, "Remote credential is still live; restored to active pool stock.")
    return _make_available(
        item,
        "No remote credential or sale evidence was found; key returned to available pool stock.",
    )


def _recover_playerauctions_item(item: OfferPoolItem) -> RecoverUnsoldResult:
    """Verify the exact PA clone for this key before changing its pool state."""
    active_offers = list(
        OfferPoolActiveOffer.objects.filter(
            pool_item_id=item.pk,
            status=OfferPoolActiveOfferStatus.ACTIVE,
        ).select_related("pool_offer__listing__integration_account", "pool_offer__listing__integration_account__credential")
    )
    if OfferPoolActiveOffer.objects.filter(
        pool_item_id=item.pk,
        status=OfferPoolActiveOfferStatus.SOLD,
    ).exists():
        return RecoverUnsoldResult(
            ok=False,
            errors=["This key has a PlayerAuctions offer marked sold and cannot be returned to the pool."],
        )
    if not active_offers:
        return _make_available(
            item,
            "No active PlayerAuctions clone or sale evidence was found; key returned to available pool stock.",
        )

    pool_offer = item.pool_offer
    store = pool_offer.store
    proxy_pool = build_proxy_pool()
    proxy_group = get_group_name(store)
    client = get_or_build_client(
        "playerauctions",
        store.credential,
        proxy_pool=proxy_pool,
        proxy_group=proxy_group,
    )

    live_offer_found = False
    missing_offers: list[OfferPoolActiveOffer] = []
    for active_offer in active_offers:
        try:
            result = client.get_offer_details(
                active_offer.store_listing_id,
                proxy_group=proxy_group,
            )
        except Exception as exc:
            return RecoverUnsoldResult(ok=False, errors=[f"Remote verification failed: {exc}"])
        if result.ok:
            live_offer_found = True
            continue
        status_code = getattr(getattr(result, "error", None), "status_code", None)
        if status_code != 404:
            return RecoverUnsoldResult(
                ok=False,
                errors=[f"Remote verification failed: {getattr(result, 'error', 'unknown error')}"],
            )
        missing_offers.append(active_offer)

    if live_offer_found:
        return _restore_live_item(
            item,
            "PlayerAuctions clone is still live; restored to active pool stock.",
        )

    with transaction.atomic():
        for active_offer in missing_offers:
            OfferPoolActiveOffer.objects.filter(
                pk=active_offer.pk,
                status=OfferPoolActiveOfferStatus.ACTIVE,
            ).update(status=OfferPoolActiveOfferStatus.DELISTED)
    return _make_available(
        item,
        "The PlayerAuctions clone is absent and no sale evidence was found; key returned to available pool stock.",
    )


def _restore_live_item(item: OfferPoolItem, message: str) -> RecoverUnsoldResult:
    """Restore a falsely-consumed key without re-posting a credential already live."""
    with transaction.atomic():
        locked = OfferPoolItem.objects.select_for_update().get(pk=item.pk)
        if PoolSaleEvent.objects.filter(pool_item_id=locked.pk).exists():
            return RecoverUnsoldResult(
                ok=False,
                errors=["Confirmed marketplace sale evidence appeared during verification; the key was not changed."],
            )
        locked.status = OfferPoolItemStatus.PUSHED
        locked.consumed_at = None
        locked.failure_stage = ""
        locked.error_message = ""
        locked.remote_state = "present"
        locked.claim_token = None
        locked.claimed_at = None
        locked.reservation = None
        locked.save(update_fields=[
            "status", "consumed_at", "failure_stage", "error_message",
            "remote_state", "claim_token", "claimed_at", "reservation", "updated_at",
        ])
    return RecoverUnsoldResult(ok=True, state="live", message=message)


def _make_available(item: OfferPoolItem, message: str) -> RecoverUnsoldResult:
    """Detach a remotely absent, unsold key and return it to the pending pool."""
    with transaction.atomic():
        locked = OfferPoolItem.objects.select_for_update().select_related("pool_offer__listing").get(pk=item.pk)
        if PoolSaleEvent.objects.filter(pool_item_id=locked.pk).exists():
            return RecoverUnsoldResult(
                ok=False,
                errors=["Confirmed marketplace sale evidence appeared during verification; the key was not changed."],
            )
        active_offers = OfferPoolActiveOffer.objects.select_for_update().filter(
            pool_item_id=locked.pk,
        )
        if active_offers.filter(status=OfferPoolActiveOfferStatus.SOLD).exists():
            return RecoverUnsoldResult(
                ok=False,
                errors=["Confirmed marketplace sale evidence appeared during verification; the key was not changed."],
            )
        linked_listing_ids = set(
            active_offers.exclude(listing_id__isnull=True).values_list("listing_id", flat=True),
        )
        if locked.pool_offer_id and locked.pool_offer.listing_id:
            linked_listing_ids.add(locked.pool_offer.listing_id)
        if linked_listing_ids:
            ListingOwnedProduct.objects.filter(
                listing_id__in=linked_listing_ids,
                owned_product_id=locked.owned_product_id,
            ).delete()
        active_offers.filter(status=OfferPoolActiveOfferStatus.ACTIVE).update(
            status=OfferPoolActiveOfferStatus.DELISTED,
        )
        locked.status = OfferPoolItemStatus.PENDING
        locked.pool_offer = None
        locked.reservation = None
        locked.pushed_at = None
        locked.consumed_at = None
        locked.error_message = ""
        locked.target_offer_id = ""
        locked.remote_credential_id = ""
        locked.claim_token = None
        locked.claimed_at = None
        locked.failure_stage = ""
        locked.remote_state = "absent"
        locked.save(update_fields=[
            "status", "pool_offer", "reservation", "pushed_at", "consumed_at",
            "error_message", "target_offer_id", "remote_credential_id",
            "claim_token", "claimed_at", "failure_stage", "remote_state", "updated_at",
        ])
    return RecoverUnsoldResult(ok=True, state="available", message=message)
