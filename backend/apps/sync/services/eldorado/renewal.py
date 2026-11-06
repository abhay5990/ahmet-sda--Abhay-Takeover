"""Fail-closed Eldorado renewal with a committed, non-expiring write hold.

The same store client holds the same offer lease from authoritative content
read through delivery read, one-shot update and verification. No network call
runs inside a database transaction. Pending/unknown/unproven attempts are not
retry tickets; separate authorized read-only reconciliation is required.
"""
from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone as dt_timezone
from typing import Any, Callable

from django.db import DEFAULT_DB_ALIAS, IntegrityError, connections, transaction
from django.db.models import Q
from django.utils import timezone

from apps.listings.enums import ListingStatus
from apps.listings.models import Listing

PROVIDER = 'eldorado'
ACTIVE_STATE = 'active'
GONE_RECHECK_DAYS = 14
NOT_ACTIVE_RECHECK_DAYS = 3
FAILED_RECHECK_HOURS = 6  # Read-only/local pre-send observations only.
VERIFY_READ_DELAY_SECONDS = 3.0
MAX_VERIFIED_EXTENSION_DAYS = 60
UNRESOLVED_OUTCOMES = ('pending', 'unknown', 'unproven')


def parse_expire_date(value: Any) -> datetime | None:
    """Eldorado's naive ISO dates are UTC; malformed dates are never proof."""
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.strip().replace('Z', '+00:00'))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=dt_timezone.utc)


@dataclass(frozen=True)
class RenewalDecision:
    outcome: str
    reason: str = ''
    previous: datetime | None = None
    verified: datetime | None = None
    stop_run: bool = False
    writes_attempted: int = 0
    reads_used: int = 0


def decide_from_live_offer(
    *, offer_id: str, read_ok: bool, read_status: int | None, live: dict | None,
    now: datetime, cutoff: datetime,
) -> RenewalDecision | None:
    """Pure read classification: None means eligible for further local checks."""
    if not read_ok:
        if read_status == 404:
            return RenewalDecision('gone', 'offer_not_found')
        return RenewalDecision('failed', 'read_failed')
    live = live or {}
    if str(live.get('id') or '').lower() != str(offer_id).lower():
        return RenewalDecision('failed', 'identity_mismatch')
    expires = parse_expire_date(live.get('expireDate'))
    if str(live.get('offerState') or '').strip().lower() != ACTIVE_STATE:
        return RenewalDecision('not_active', 'remote_not_active', expires)
    if expires is None:
        return RenewalDecision('failed', 'expiry_unreadable')
    if expires > cutoff:
        return RenewalDecision('not_due', 'not_expiring_soon', expires, expires)
    return None


def decide_after_save(
    *, previous: datetime | None, after_ok: bool, after: dict | None,
    offer_id: str, now: datetime | None = None,
) -> RenewalDecision:
    """Require an Active, exact-ID offer with a later, bounded future expiry.

    The optional clock preserves the pure helper interface; execution always
    supplies its explicit clock rather than inferring time from provider data.
    """
    now = now if now is not None else timezone.now()
    if not after_ok:
        return RenewalDecision('unknown', 'verify_read_failed', previous, stop_run=True)
    after = after or {}
    if str(after.get('id') or '').lower() != str(offer_id).lower():
        return RenewalDecision('unknown', 'verify_identity_mismatch', previous, stop_run=True)
    new_expiry = parse_expire_date(after.get('expireDate'))
    if str(after.get('offerState') or '').strip().lower() != ACTIVE_STATE:
        return RenewalDecision('unknown', 'verify_state_changed', previous, new_expiry, stop_run=True)
    if (new_expiry is not None and previous is not None and new_expiry > previous
            and now < new_expiry <= now + timedelta(days=MAX_VERIFIED_EXTENSION_DAYS)):
        return RenewalDecision('renewed', 'verified_expiry_extended', previous, new_expiry)
    return RenewalDecision('unproven', 'saved_but_expiry_unproven', previous, new_expiry, stop_run=True)


def eldorado_candidates(*, now: datetime, cutoff: datetime, limit: int) -> list[Listing]:
    """Read-only candidate selection; durable admission is repeated at claim."""
    base = (Listing.objects
            .filter(integration_account__provider=PROVIDER,
                    status__in=[ListingStatus.LISTED, ListingStatus.PAUSED])
            .exclude(store_listing_id__isnull=True).exclude(store_listing_id='')
            .select_related('integration_account__credential'))
    skip = recently_checked_ids(now)
    picked: list[Listing] = []
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
    checks = C.objects.filter(provider=PROVIDER)
    recent = checks.filter(
        Q(outcome=C.Outcome.GONE, created_at__gte=now - timedelta(days=GONE_RECHECK_DAYS))
        | Q(outcome__in=[C.Outcome.NOT_ACTIVE, C.Outcome.HELD_SALE], created_at__gte=now - timedelta(days=NOT_ACTIVE_RECHECK_DAYS))
        | Q(outcome=C.Outcome.FAILED, created_at__gte=now - timedelta(hours=FAILED_RECHECK_HOURS))
        | Q(outcome__in=UNRESOLVED_OUTCOMES)
    ).values_list('listing_id', flat=True)
    held_ids = set(recent)
    # An alias/new local row or changed expiry cannot bypass an unresolved offer.
    for account_id, offer_id in checks.filter(outcome__in=UNRESOLVED_OUTCOMES).values_list('integration_account_id', 'offer_id').distinct():
        held_ids.update(Listing.objects.filter(
            integration_account_id=account_id, store_listing_id__iexact=offer_id,
        ).values_list('pk', flat=True))
    return held_ids


def _db(listing: Listing) -> str:
    return listing._state.db or DEFAULT_DB_ALIAS


def _offer_id(listing: Listing) -> str:
    return str(listing.store_listing_id or '').strip().lower()


def renewal_cycle_key(account_id: int, offer_id: str, previous: datetime) -> str:
    """Exact UTC-expiry identity, stable across dates and local listing aliases."""
    identity = f'{PROVIDER}:{account_id}:{offer_id.strip().lower()}:{previous.astimezone(dt_timezone.utc).isoformat()}'
    return hashlib.sha256(identity.encode('utf-8')).hexdigest()


def unresolved_offer_key(account_id: int, offer_id: str) -> str:
    """Portable unique pending slot, independent of expiry or local aliases."""
    identity = f'{PROVIDER}:{account_id}:{offer_id.strip().lower()}'
    return hashlib.sha256(identity.encode('utf-8')).hexdigest()


def _safe_reason(reason: str) -> str:
    from apps.sync.models import MarketplaceRenewalCheck as C
    return reason if reason in C.REASON_CODES else 'local_safety_refusal'


def _record(listing: Listing, decision: RenewalDecision) -> None:
    """Observation only: never used instead of a pre-send attempt claim."""
    from apps.sync.models import MarketplaceRenewalCheck as C
    C.objects.using(_db(listing)).create(
        listing=listing, integration_account_id=listing.integration_account_id,
        provider=PROVIDER, offer_id=_offer_id(listing), outcome=decision.outcome,
        previous_expires_at=decision.previous, verified_expires_at=decision.verified,
        reason_code=_safe_reason(decision.reason),
    )


def _live_dict(result: Any) -> dict:
    """Keep raw types/keys: parsed/coerced model dumps are not live evidence."""
    data = getattr(result, 'data', None)
    snapshot = getattr(data, 'raw_offer_snapshot', None)
    if callable(snapshot):
        raw = snapshot()
        return raw if isinstance(raw, dict) else {}
    offer = data.get('offer') if isinstance(data, dict) else getattr(data, 'offer', None)
    if isinstance(offer, dict):
        return dict(offer)
    return {}


def _status_code(result: Any) -> int | None:
    for name in ('status_code', 'http_status'):
        value = getattr(result, name, None)
        if isinstance(value, int):
            return value
    error = getattr(result, 'error', None)
    value = getattr(error, 'status_code', None)
    return value if isinstance(value, int) else None


def _has_sale_or_open_order(listing: Listing) -> bool:
    """Any sale/order evidence, including an alias or a direct listing link."""
    from apps.inventory.enums import OwnedProductStatus
    from apps.listings.models import ListingOwnedProduct
    from apps.orders.models import Order
    from apps.posting.models import OfferPoolActiveOffer, OfferPoolActiveOfferStatus, PoolSaleEvent
    db = _db(listing)
    aliases = Listing.objects.using(db).filter(
        integration_account_id=listing.integration_account_id,
        store_listing_id__iexact=_offer_id(listing),
    ).values_list('pk', flat=True)
    products = ListingOwnedProduct.objects.using(db).filter(listing_id__in=aliases)
    if products.exclude(owned_product__status__in=[OwnedProductStatus.DRAFT, OwnedProductStatus.LISTED]).exists():
        return True
    if PoolSaleEvent.objects.using(db).filter(listing_id__in=aliases).exists():
        return True
    if OfferPoolActiveOffer.objects.using(db).filter(
        listing_id__in=aliases, status=OfferPoolActiveOfferStatus.SOLD,
    ).exists():
        return True
    return Order.objects.using(db).filter(
        Q(listing_id__in=aliases) | Q(owned_product_id__in=products.values_list('owned_product_id', flat=True))
        | Q(integration_account_id=listing.integration_account_id,
            store_listing_id__iexact=_offer_id(listing))
    ).exists()


def _execute_enabled() -> bool:
    from apps.sync.services.shared.feature_flags import unified_renewal_providers
    try:
        return PROVIDER in unified_renewal_providers()
    except Exception:
        return False


def _fresh_listing(listing: Listing, *, lock: bool = False) -> Listing | None:
    qs = Listing.objects.using(_db(listing))
    if lock:
        # Lock only the exact Listing, not a nullable select_related outer join.
        qs = qs.select_for_update()
    fresh = qs.filter(
        pk=listing.pk, integration_account_id=listing.integration_account_id,
        store_listing_id=listing.store_listing_id,
        status__in=[ListingStatus.LISTED, ListingStatus.PAUSED],
    ).first()
    if fresh is None or fresh.removed_at is not None:
        return None
    store = fresh.integration_account
    if (not store or store.provider != PROVIDER or not store.is_active
            or store.role not in ('sell', 'both')):
        return None
    from apps.integrations.models import IntegrationCredential
    if not IntegrationCredential.objects.using(_db(listing)).filter(account_id=store.pk, is_active=True).exists():
        return None
    return fresh


def _unresolved(listing: Listing) -> bool:
    from apps.sync.models import MarketplaceRenewalCheck as C
    return C.objects.using(_db(listing)).filter(
        provider=PROVIDER, integration_account_id=listing.integration_account_id,
        offer_id=_offer_id(listing), outcome__in=UNRESOLVED_OUTCOMES,
    ).exists()


def _claim(listing: Listing, previous: datetime) -> tuple[Any, RenewalDecision | None]:
    """Commit a durable pending row, with exact DB-identity and sale locks."""
    from apps.sync.models import MarketplaceRenewalCheck as C
    db = _db(listing)
    if connections[db].in_atomic_block or not connections[db].get_autocommit():
        return None, RenewalDecision('failed', 'transaction_active', previous, stop_run=True)
    with transaction.atomic(using=db):
        fresh = _fresh_listing(listing, lock=True)
        if fresh is None:
            return None, RenewalDecision('failed', 'listing_changed', previous)
        if _has_sale_or_open_order(fresh):
            return None, RenewalDecision('held_sale', 'local_sale_or_order', previous)
        if _unresolved(fresh):
            return None, RenewalDecision('unknown', 'unresolved_attempt', previous, stop_run=True)
        cycle = renewal_cycle_key(fresh.integration_account_id, _offer_id(fresh), previous)
        if C.objects.using(db).filter(cycle_key=cycle).exists():
            return None, RenewalDecision('not_due', 'cycle_already_checked', previous)
        attempt = C.objects.using(db).create(
            listing=fresh, integration_account_id=fresh.integration_account_id,
            provider=PROVIDER, offer_id=_offer_id(fresh), cycle_key=cycle,
            unresolved_key=unresolved_offer_key(fresh.integration_account_id, _offer_id(fresh)),
            outcome=C.Outcome.PENDING, previous_expires_at=previous,
            reason_code='attempt_pending',
        )
    return attempt, None


class _LocalPreSendRefusal(Exception):
    """Only controlled local stages use this, never provider error labels."""
    def __init__(self, reason: str, *, outcome: str = 'failed'):
        self.reason = _safe_reason(reason)
        self.outcome = outcome
        super().__init__(self.reason)


def _pre_send_check(listing: Listing) -> None:
    db = _db(listing)
    if connections[db].in_atomic_block or not connections[db].get_autocommit():
        raise _LocalPreSendRefusal('transaction_active')
    if not _execute_enabled():
        raise _LocalPreSendRefusal('renewal_disabled')
    # This short lock is released before any provider transport.
    with transaction.atomic(using=db):
        fresh = _fresh_listing(listing, lock=True)
        if fresh is None:
            raise _LocalPreSendRefusal('listing_changed')
        if _has_sale_or_open_order(fresh):
            raise _LocalPreSendRefusal('local_sale_or_order', outcome='held_sale')


def _finalize(listing: Listing, attempt: Any, decision: RenewalDecision) -> RenewalDecision:
    """Lock exact local ownership again; never revive a sold/reassigned row."""
    from apps.sync.models import MarketplaceRenewalCheck as C
    db = _db(listing)
    with transaction.atomic(using=db):
        fresh = _fresh_listing(listing, lock=True)
        held_sale = fresh is not None and _has_sale_or_open_order(fresh)
        if decision.writes_attempted and (fresh is None or held_sale):
            decision = replace(decision, outcome='unknown',
                               reason='local_state_changed_after_send', stop_run=True)
        claimed = C.objects.using(db).select_for_update().get(
            pk=attempt.pk, listing_id=listing.pk,
            integration_account_id=listing.integration_account_id,
            provider=PROVIDER, offer_id=_offer_id(listing), cycle_key=attempt.cycle_key,
            outcome=C.Outcome.PENDING,
        )
        claimed.outcome = decision.outcome
        claimed.reason_code = _safe_reason(decision.reason)
        claimed.verified_expires_at = decision.verified
        if decision.outcome not in UNRESOLVED_OUTCOMES:
            claimed.unresolved_key = None
        claimed.save(using=db, update_fields=[
            'outcome', 'reason_code', 'verified_expires_at', 'unresolved_key', 'updated_at',
        ])
        if decision.outcome == 'renewed' and decision.verified and fresh is not None:
            _store_expiry(fresh, decision.verified, revive=True)
    return decision


def renew_eldorado_listing(
    listing: Listing, *, now: datetime, cutoff: datetime, execute: bool,
    client_for: Callable[[Listing], Any] | None = None,
    save: Callable[[Listing, dict, Any], Any] | None = None,
    sleep: Callable[[float], None] = time.sleep,
    read_budget: int | None = None,
) -> RenewalDecision:
    """Independently gated; callbacks have the (listing, live, same_client) contract."""
    db = _db(listing)
    if execute and (connections[db].in_atomic_block or not connections[db].get_autocommit()):
        return RenewalDecision('failed', 'transaction_active', stop_run=True)
    if execute and not _execute_enabled():
        return RenewalDecision('failed', 'renewal_disabled', stop_run=True)
    offer_id = _offer_id(listing)
    if read_budget is not None and read_budget <= 0:
        return RenewalDecision('not_due', 'read_budget_exhausted', stop_run=True)
    if not listing.pk or not listing.integration_account_id or not offer_id or len(offer_id) > 64:
        return RenewalDecision('failed', 'listing_changed')

    attempt = None
    previous = None
    writes_attempted = 0
    reads_used = 0

    def count_read() -> None:
        nonlocal reads_used
        reads_used += 1

    try:
        fresh = _fresh_listing(listing)
        if fresh is None:
            return RenewalDecision('failed', 'listing_changed')
        if _unresolved(fresh):
            return RenewalDecision('unknown', 'unresolved_attempt', stop_run=True)
        client = (client_for or _default_client)(fresh)
        mutation = getattr(client, 'offer_mutation', None)
        if not callable(mutation):
            return RenewalDecision('failed', 'serialization_unavailable', stop_run=True)
        if execute and save is None and not callable(getattr(client, 'update_offer_once', None)):
            return RenewalDecision('failed', 'one_shot_update_unavailable', stop_run=True)
        with mutation(offer_id) as admitted:
            if not admitted:
                return RenewalDecision('failed', 'mutation_not_admitted', stop_run=True)
            count_read()
            first = client.get_private_offer(offer_id, renewal_safe=True)
            live = _live_dict(first)
            decision = decide_from_live_offer(
                offer_id=offer_id, read_ok=bool(getattr(first, 'ok', False)),
                read_status=_status_code(first), live=live, now=now, cutoff=cutoff,
            )
            if decision is None:
                previous = parse_expire_date(live.get('expireDate'))
                fresh = _fresh_listing(listing)
                if fresh is None:
                    decision = RenewalDecision('failed', 'listing_changed', previous)
                elif _has_sale_or_open_order(fresh):
                    decision = RenewalDecision('held_sale', 'local_sale_or_order', previous)
                elif not execute:
                    decision = RenewalDecision('not_due', 'dry_run_would_renew', previous)
                elif read_budget is not None and read_budget - reads_used < 2:
                    decision = RenewalDecision('not_due', 'read_budget_exhausted', previous, stop_run=True)
                else:
                    attempt, decision = _claim(fresh, previous)
                    if attempt is not None:
                        try:
                            _pre_send_check(fresh)
                            writes_attempted = 1
                            if save is None:
                                saved = _default_save(fresh, live, client, on_read=count_read)
                            else:
                                # Injected saves reserve one logical delivery read.
                                count_read()
                                try:
                                    saved = save(fresh, live, client)
                                except Exception:
                                    # Only _default_save's controlled pre-send
                                    # stages establish certainty of no transport.
                                    raise RuntimeError('send_outcome_unknown') from None
                        except _LocalPreSendRefusal as refusal:
                            writes_attempted = 0
                            decision = RenewalDecision(refusal.outcome, refusal.reason, previous)
                        else:
                            # No remote no_write/error label is authority to retry.
                            if not getattr(saved, 'ok', False):
                                decision = RenewalDecision('unknown', 'send_failed_unknown', previous, stop_run=True)
                            else:
                                sleep(VERIFY_READ_DELAY_SECONDS)
                                count_read()
                                after = client.get_private_offer(offer_id, renewal_safe=True)
                                decision = decide_after_save(
                                    previous=previous, after_ok=bool(getattr(after, 'ok', False)),
                                    after=_live_dict(after), offer_id=offer_id, now=now,
                                )
    except IntegrityError:
        decision = RenewalDecision('unknown' if attempt else 'failed',
                                   'ledger_unavailable', previous, stop_run=True)
    except Exception:
        # Never persist/log exception text (it may contain credentials/payload).
        decision = RenewalDecision('unknown' if attempt else 'failed',
                                   'attempt_exception' if attempt else 'local_check_failed',
                                   previous, stop_run=True)

    decision = replace(decision, writes_attempted=writes_attempted, reads_used=reads_used)
    if execute:
        try:
            if attempt is not None:
                return _finalize(listing, attempt, decision)
            _record(listing, decision)
            if decision.outcome == 'not_due' and decision.verified:
                _store_expiry(listing, decision.verified, revive=True)
        except Exception:
            # If finalization fails, the already committed pending hold survives.
            return RenewalDecision('unknown' if attempt else 'failed', 'ledger_unavailable',
                                   previous, stop_run=True, writes_attempted=writes_attempted,
                                   reads_used=reads_used)
    return decision


def _store_expiry(listing: Listing, expires: datetime, *, revive: bool) -> None:
    """Update only exact, freshly safe ownership; never stale-instance save()."""
    db = _db(listing)
    with transaction.atomic(using=db):
        fresh = _fresh_listing(listing, lock=True)
        if fresh is None or _has_sale_or_open_order(fresh):
            return
        fresh.marketplace_expires_at = expires
        fields = ['marketplace_expires_at', 'updated_at']
        if revive and fresh.status == ListingStatus.PAUSED:
            fresh.status = ListingStatus.LISTED
            fields.append('status')
        fresh.save(using=db, update_fields=fields)


def _default_client(listing: Listing) -> Any:
    from apps.integrations.providers.registry import get_or_build_client
    from apps.integrations.proxy_pool import build_proxy_pool, get_group_name
    store = listing.integration_account
    return get_or_build_client(PROVIDER, store.credential, proxy_pool=build_proxy_pool(), proxy_group=get_group_name(store))


def _default_save(
    listing: Listing, live: dict, client: Any, *, on_read: Callable[[], None] | None = None,
) -> Any:
    """Read current delivery inside the outer lease; send exactly once, no editor."""
    try:
        from apps.integrations.proxy_pool import get_group_name
        from apps.sync.services.eldorado.renewal_payload import build_renewal_payload
        proxy_group = get_group_name(listing.integration_account)
        update_once = getattr(client, 'update_offer_once', None)
        if not callable(update_once):
            raise _LocalPreSendRefusal('one_shot_update_unavailable')
    except _LocalPreSendRefusal:
        raise
    except Exception:
        raise _LocalPreSendRefusal('save_configuration_missing') from None
    try:
        if on_read is not None:
            on_read()
        credentials = client.get_offer_account_details(
            _offer_id(listing), proxy_group=proxy_group, renewal_safe=True,
        )
    except Exception:
        raise _LocalPreSendRefusal('credential_read_failed') from None
    if not getattr(credentials, 'ok', False):
        raise _LocalPreSendRefusal('credential_read_failed')
    try:
        payload = build_renewal_payload(live, credentials.data)
    except Exception:
        raise _LocalPreSendRefusal('payload_invalid') from None
    try:
        # The final ownership/sale refresh happens AFTER the delivery read too.
        _pre_send_check(listing)
    except _LocalPreSendRefusal:
        raise
    except Exception:
        raise _LocalPreSendRefusal('local_check_failed') from None
    try:
        return update_once(_offer_id(listing), payload, proxy_group=proxy_group)
    except Exception:
        # Nothing raised by the SDK/transport may masquerade as local proof.
        raise RuntimeError('send_outcome_unknown') from None
