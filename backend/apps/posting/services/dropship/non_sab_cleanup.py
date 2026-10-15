"""Identify and delist non-SAB Eldorado offers that were posted as SAB items.

Seller-UUID Eldorado fetches previously omitted gameId, so multi-game sellers'
Grow-a-Garden (etc.) offers were listed under steal-a-brainrot on GameBoost.
"""

from __future__ import annotations

import logging
from typing import NamedTuple

from apps.inventory.enums import DropshipProductStatus
from apps.inventory.models import DropshipProduct
from apps.listings.enums import ListingStatus
from apps.listings.models import Listing
from apps.posting.services.dropship.delist import delist_single
from apps.posting.services.dropship.sources.eldorado import SAB_GAME_ID, _coerce_game_id

logger = logging.getLogger(__name__)


class NonSabCleanupResult(NamedTuple):
    scanned: int
    sab_kept: int
    unknown_game_id: int
    non_sab_found: int
    delisted: int
    failed: int
    dry_run: bool
    non_sab_offer_ids: list[str]
    errors: dict[str, str]


def extract_eldorado_game_id(raw_data: dict | None) -> int | None:
    """Read Eldorado gameId from a DropshipProduct.raw_data payload."""
    raw = raw_data or {}
    gid = _coerce_game_id(raw.get("gameId") or raw.get("game_id"))
    if gid is not None:
        return gid
    offer = raw.get("offer") or {}
    if isinstance(offer, dict):
        return _coerce_game_id(offer.get("gameId") or offer.get("game_id"))
    return None


def iter_listed_sab_dropship_products():
    """Yield LISTED steal-a-brainrot DropshipProducts that have a GB listing."""
    return (
        DropshipProduct.objects
        .filter(
            status=DropshipProductStatus.LISTED,
            game__slug="steal-a-brainrot",
            listings__status=ListingStatus.LISTED,
            listings__integration_account__provider="gameboost",
        )
        .distinct()
        .prefetch_related(
            "listings",
            "listings__integration_account",
        )
        .order_by("id")
    )


def gb_offer_ids_for_dp(dp: DropshipProduct) -> list[str]:
    return [
        str(lst.store_listing_id)
        for lst in dp.listings.all()
        if (
            lst.status == ListingStatus.LISTED
            and lst.integration_account
            and lst.integration_account.provider == "gameboost"
            and lst.store_listing_id
        )
    ]


def cleanup_non_sab_item_listings(*, dry_run: bool = True, limit: int | None = None) -> NonSabCleanupResult:
    """Delist SAB-config DropshipProducts whose Eldorado gameId is not SAB (259).

    Args:
        dry_run: When True, only report; do not call marketplace delete.
        limit: Optional max number of non-SAB products to delist (for staged runs).
    """
    scanned = 0
    sab_kept = 0
    unknown_game_id = 0
    non_sab_dps: list[DropshipProduct] = []
    non_sab_offer_ids: list[str] = []

    for dp in iter_listed_sab_dropship_products().iterator(chunk_size=200):
        scanned += 1
        gid = extract_eldorado_game_id(dp.raw_data)
        if gid is None:
            unknown_game_id += 1
            continue
        if gid == SAB_GAME_ID:
            sab_kept += 1
            continue
        non_sab_dps.append(dp)
        non_sab_offer_ids.extend(gb_offer_ids_for_dp(dp))
        if limit is not None and len(non_sab_dps) >= limit:
            break

    if dry_run:
        return NonSabCleanupResult(
            scanned=scanned,
            sab_kept=sab_kept,
            unknown_game_id=unknown_game_id,
            non_sab_found=len(non_sab_dps),
            delisted=0,
            failed=0,
            dry_run=True,
            non_sab_offer_ids=non_sab_offer_ids,
            errors={},
        )

    delisted = 0
    failed = 0
    errors: dict[str, str] = {}
    for dp in non_sab_dps:
        offer_ids = gb_offer_ids_for_dp(dp)
        result = delist_single(dp)
        if result.ok:
            delisted += 1
        else:
            failed += 1
            key = ",".join(offer_ids) or str(dp.id)
            errors[key] = result.error or "delist failed"
            logger.warning(
                "Failed to delist non-SAB DropshipProduct #%s (gameId=%s): %s",
                dp.id, extract_eldorado_game_id(dp.raw_data), result.error,
            )

    return NonSabCleanupResult(
        scanned=scanned,
        sab_kept=sab_kept,
        unknown_game_id=unknown_game_id,
        non_sab_found=len(non_sab_dps),
        delisted=delisted,
        failed=failed,
        dry_run=False,
        non_sab_offer_ids=non_sab_offer_ids,
        errors=errors,
    )
