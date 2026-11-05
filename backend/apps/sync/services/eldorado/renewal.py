"""Eldorado auto-renewal (5 Nov 2026).

Eldorado offers expire about 21 days after their last save (``expireDate`` on
the seller's private offer view; live: an offer created 5 Nov showed
2026-11-26T18:00). Until now SDA only *paused its own DB row* at 21 days
(``pause_expiring_listings``) and the real offer simply expired.

Renewal = re-save the exact offer, unchanged, with the full PUT the editor
already uses (Eldorado refuses partial PUTs), built from the LIVE private
offer (not a stale local snapshot), while holding the per-offer mutation lease
and the store write budget. It counts as renewed only when a fresh read shows
a LATER ``expireDate``. Anything else is recorded and, for an unproven save,
stops the run (fail closed) so a silent no-op can never loop over the store.

Never: buys, deletes, recreates, changes price/title/credentials, or touches a
listing with local sale/order evidence.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone as dt_timezone
from typing import Any, Callable

from django.db.models import Q
from django.utils import timezone

from apps.listings.enums import ListingStatus
from apps.listings.models import Listing

PROVIDER = 'eldorado'
ACTIVE_STATE = 'active'
GONE_RECHECK_DAYS = 14
NOT_ACTIVE_RECHECK_DAYS = 3
FAILED_RECHECK_HOURS = 6
VERIFY_READ_DELAY_SECONDS = 3.0


def parse_expire_date(value: Any) -> datetime | None:
    """Eldorado sends naive ISO timestamps (UTC). Unparseable → None."""
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.strip().replace('Z', '+00:00'))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=dt_timezone.utc)


@dataclass(frozen=True)
class RenewalDecision:
    outcome: str  # MarketplaceRenewalCheck.Outcome value
    reason: str = ''
    previous: datetime | None = None
    verified: datetime | None = None
    stop_run: bool = False


def decide_from_live_offer(
    *, offer_id: str, read_ok: bool, read_status: int | None, live: dict | None,
    now: datetime, cutoff: datetime,
) -> RenewalDecision | None:
    """Pure: what a live read means. ``None`` = due → save it."""
    if not read_ok:
        if read_status == 404:
            return RenewalDecision('gone', 'offer_not_found')
        return RenewalDecision('failed', 'read_failed')
    live = live or {}
    if str(live.get('id') or '').lower() != str(offer_id).lower():
        return RenewalDecision('failed', 'identity_mismatch')
    expires = parse_expire_date(live.get('expireDate'))
    if str(live.get('offerState') or '').strip().lower() != ACTIVE_STATE:
        return RenewalDecision('not_active', f"state_{str(live.get('offerState') or 'unknown').lower()[:20]}", expires)
    if expires is None:
        return RenewalDecision('failed', 'expiry_unreadable')
    if expires <= now:
        # Active but already past its date: renew right away.
        return None
    if expires > cutoff:
        return RenewalDecision('not_due', 'not_expiring_soon', expires, expires)
    return None


def decide_after_save(*, previous: datetime | None, after_ok: bool, after: dict | None, offer_id: str) -> RenewalDecision:
    """Pure: a save counts only when a fresh read shows a later expiry."""
    if not after_ok:
        return RenewalDecision('failed', 'verify_read_failed', previous, stop_run=True)
    after = after or {}
    if str(after.get('id') or '').lower() != str(offer_id).lower():
        return RenewalDecision('failed', 'verify_identity_mismatch', previous, stop_run=True)
    new_expiry = parse_expire_date(after.get('expireDate'))
    if str(after.get('offerState') or '').strip().lower() != ACTIVE_STATE:
        return RenewalDecision('failed', 'verify_state_changed', previous, new_expiry, stop_run=True)
    if new_expiry is not None and (previous is None or new_expiry > previous):
        return RenewalDecision('renewed', 'verified_expiry_extended', previous, new_expiry)
    return RenewalDecision('unproven', 'saved_but_expiry_unchanged', previous, new_expiry, stop_run=True)


def eldorado_candidates(*, now: datetime, cutoff: datetime, limit: int) -> list[Listing]:
    """Due or unknown-expiry Eldorado listings, soonest first.

    ``paused`` rows are included on purpose: SDA used to mark them paused in
    its own DB at 21 days while many stayed Active on Eldorado. Recently
    checked rows are skipped by ``recently_checked_ids``.
    """
    base = (Listing.objects
            .filter(integration_account__provider=PROVIDER,
                    status__in=[ListingStatus.LISTED, ListingStatus.PAUSED])
            .exclude(store_listing_id__isnull=True).exclude(store_listing_id='')
            .select_related('integration_account__credential'))
    skip = recently_checked_ids(now)
    picked: list[Listing] = []
    # 1) live offers expiring soon (not yet past), soonest first
    # 2) unknown expiry (new rows)  3) already past (mostly gone) last
    for qs in (
        base.filter(marketplace_expires_at__gt=now, marketplace_expires_at__lte=cutoff).order_by('marketplace_expires_at', 'pk'),
        base.filter(marketplace_expires_at__isnull=True).order_by('pk'),
        base.filter(marketplace_expires_at__lte=now).order_by('-marketplace_expires_at', 'pk'),
    ):
        for listing in qs.iterator(chunk_size=200):
            if listing.pk in skip:
                continue
            picked.append(listing)
            if len(picked) >= limit:
                return picked
    return picked


def recently_checked_ids(now: datetime) -> set[int]:
    from apps.sync.models import MarketplaceRenewalCheck as C
    recent = C.objects.filter(provider=PROVIDER).filter(
        Q(outcome__in=[C.Outcome.GONE], created_at__gte=now - timedelta(days=GONE_RECHECK_DAYS))
        | Q(outcome__in=[C.Outcome.NOT_ACTIVE, C.Outcome.HELD_SALE], created_at__gte=now - timedelta(days=NOT_ACTIVE_RECHECK_DAYS))
        | Q(outcome__in=[C.Outcome.FAILED, C.Outcome.UNPROVEN], created_at__gte=now - timedelta(hours=FAILED_RECHECK_HOURS))
    ).values_list('listing_id', flat=True)
    return set(recent)


def _record(listing: Listing, decision: RenewalDecision) -> None:
    from apps.sync.models import MarketplaceRenewalCheck
    MarketplaceRenewalCheck.objects.create(
        listing=listing, provider=PROVIDER, offer_id=str(listing.store_listing_id)[:64],
        outcome=decision.outcome, previous_expires_at=decision.previous,
        verified_expires_at=decision.verified, reason_code=decision.reason[:80],
    )


def _live_dict(result: Any) -> dict:
    data = getattr(result, 'data', None)
    offer = getattr(data, 'offer', None)
    if offer is None:
        return {}
    dumped = offer.model_dump() if hasattr(offer, 'model_dump') else dict(offer)
    extra = getattr(offer, 'model_extra', None) or {}
    return {**extra, **dumped}


def _status_code(result: Any) -> int | None:
    for name in ('status_code', 'http_status'):
        value = getattr(result, name, None)
        if isinstance(value, int):
            return value
    error = getattr(result, 'error', None)
    value = getattr(error, 'status_code', None)
    if isinstance(value, int):
        return value
    category = str(getattr(error, 'category', '') or getattr(result, 'category', '')).lower()
    return 404 if 'not_found' in category else None


def _has_sale_or_open_order(listing: Listing) -> bool:
    from apps.sync.management.commands.renew_expiring_playerauctions import _has_sale_or_open_order as guard
    return guard(listing)


def renew_eldorado_listing(
    listing: Listing, *, now: datetime, cutoff: datetime, execute: bool,
    client_for: Callable[[Listing], Any] | None = None,
    save: Callable[[Listing, Any], Any] | None = None,
    sleep: Callable[[float], None] = time.sleep,
) -> RenewalDecision:
    """Read → (if due) save unchanged → verify a later expiry. Records every outcome when executing."""
    client_for = client_for or _default_client
    client = client_for(listing)
    offer_id = str(listing.store_listing_id)
    first = client.get_private_offer(offer_id)
    live = _live_dict(first)
    decision = decide_from_live_offer(
        offer_id=offer_id, read_ok=bool(getattr(first, 'ok', False)), read_status=_status_code(first),
        live=live, now=now, cutoff=cutoff,
    )
    if decision is not None:
        if execute:
            _record(listing, decision)
            if decision.outcome == 'not_due' and decision.verified:
                _store_expiry(listing, decision.verified, revive=True)
        return decision
    previous = parse_expire_date(live.get('expireDate'))
    if _has_sale_or_open_order(listing):
        decision = RenewalDecision('held_sale', 'local_sale_or_order', previous)
        if execute:
            _record(listing, decision)
        return decision
    if not execute:
        return RenewalDecision('not_due', 'dry_run_would_renew', previous)
    saved = (save or _default_save)(listing, live)
    if not getattr(saved, 'ok', False):
        decision = RenewalDecision('failed', f"save_failed:{str(getattr(saved, 'error', '') or 'unknown')[:60]}", previous,
                                   stop_run=any(w in str(getattr(saved, 'error', '')).lower() for w in ('busy', 'held', 'cowboy', 'rate', '429')))
        _record(listing, decision)
        return decision
    sleep(VERIFY_READ_DELAY_SECONDS)
    after = client.get_private_offer(offer_id)
    decision = decide_after_save(previous=previous, after_ok=bool(getattr(after, 'ok', False)), after=_live_dict(after), offer_id=offer_id)
    _record(listing, decision)
    if decision.outcome == 'renewed' and decision.verified:
        _store_expiry(listing, decision.verified, revive=True)
    return decision


def _store_expiry(listing: Listing, expires: datetime, *, revive: bool) -> None:
    """Keep the verified expiry; a DB-only 'paused' row that is really Active goes back to listed."""
    fields = ['marketplace_expires_at', 'updated_at']
    listing.marketplace_expires_at = expires
    if revive and listing.status == ListingStatus.PAUSED and not _has_sale_or_open_order(listing):
        listing.status = ListingStatus.LISTED
        fields.append('status')
    listing.save(update_fields=fields)


def _default_client(listing: Listing) -> Any:
    from apps.integrations.providers.registry import get_or_build_client
    from apps.integrations.proxy_pool import build_proxy_pool, get_group_name
    store = listing.integration_account
    return get_or_build_client('eldorado', store.credential, proxy_pool=build_proxy_pool(), proxy_group=get_group_name(store))


def _default_save(listing: Listing, live: dict) -> Any:
    """Unchanged full PUT through the editor, from the live offer (in memory only)."""
    from apps.posting.services import offer_editor
    raw = dict(listing.raw_data or {}) if isinstance(listing.raw_data, dict) else {}
    keep = ('pricePerUnit', 'offerTitle', 'description', 'guaranteedDeliveryTime', 'hasOriginalEmail',
            'mainOfferImage', 'offerImages', 'attributes', 'tradeEnvironmentValues', 'gameId', 'category',
            'quantity', 'minQuantity', 'volumeDiscounts', 'expireDate', 'offerState')
    listing.raw_data = {**raw, **{k: live[k] for k in keep if k in live and live[k] is not None}}
    return offer_editor.edit_offer(listing, {})
