"""Exact-clone Mart renewal; no creation, allocation, recycling or sale writes.

Call only from autocommit, never an enclosing caller transaction. The pending
claim commits durably *before* transport. A separate, helper-owned transaction
holds the fresh listing/clone/item/product locks across transport and finalization.
A crash/rollback leaves the committed claim pending: it must be reconciled by a
human/explicit reconciliation workflow, not automatically resent on another day.
These locks are not a remote sale/allocation lease or complete unsold coverage.
"""
from __future__ import annotations

import hashlib
import re
from datetime import datetime, timedelta, timezone as dt_timezone

from django.db import connection, transaction
from django.db.models import Q
from django.utils import timezone

from apps.integrations.models import IntegrationAccount, IntegrationCredential, PaGmailOrderEvent
from apps.inventory.enums import OwnedProductStatus
from apps.inventory.models import OwnedProduct
from apps.listings.enums import ListingStatus
from apps.listings.models import Listing, ListingOwnedProduct
from apps.orders.models import FaultyAccountReturn, Order, OrderReplacement
from apps.posting.models import (
    ManualFaultyPoolTransfer, OfferPool, OfferPoolActiveOffer, OfferPoolActiveOfferStatus, OfferPoolItem,
    OfferPoolItemStatus, OfferPoolStatus, PoolDispatchAttempt,
    PoolDispatchReservationStatus, PoolDispatchStatus, PoolOffer, PoolOfferStatus,
    PoolOfferStrategy, PoolSaleEvent, PlayerAuctionsEditRequest,
    PlayerAuctionsEditRequestStatus,
)
from apps.posting.services.stock.pa_tracking import extract_tracking_code
from apps.sync.models import PaMartRenewalAttempt
from apps.sync.services.shared.feature_flags import SyncFlag, is_sync_feature_enabled, unified_renewal_providers

MART_ACCOUNT_SLUG = 'playerauctions-csgosmurfkings'
_LOCAL_NO_WRITE_PROOF = 'sda_local_pretransport'
_LOCAL_REJECTION_REASONS = frozenset({'renew_invalid_offer_id', 'renew_invalid_request_id'})
_UNRESOLVED = (PaMartRenewalAttempt.Status.PENDING, PaMartRenewalAttempt.Status.UNKNOWN)
_ID_RE = re.compile(r'[1-9][0-9]{0,15}\Z', re.ASCII)
_REQUEST_RE = re.compile(r'[A-Za-z0-9._:-]{12,128}\Z', re.ASCII)


class _Unsafe(Exception):
    """Contains only a code chosen locally; never a provider message."""


def _offer_id(value):
    return value if isinstance(value, str) and _ID_RE.fullmatch(value) else ''


def _aware(value):
    return isinstance(value, datetime) and timezone.is_aware(value)


def mart_renewal_request_id(offer_id: str, expires_at, today=None) -> str:
    """Hash the complete UTC expiry, never the invocation day (compat third arg)."""
    if not _offer_id(offer_id) or not _aware(expires_at):
        raise ValueError('invalid_renewal_cycle')
    cycle = expires_at.astimezone(dt_timezone.utc).isoformat(timespec='microseconds')
    digest = hashlib.sha256(f'{offer_id}|{cycle}'.encode('ascii')).hexdigest()
    return f'sda-renew-{offer_id}-{digest}'


def _enabled():
    # Explicit False also makes the shared helper's DB-exception path fail closed.
    try:
        return (
            is_sync_feature_enabled(SyncFlag.RENEW_EXPIRING_PA, default=False) is True
            or 'playerauctions' in unified_renewal_providers()
        )
    except Exception:
        return False


def _message(reason, request_id=''):
    suffix = f'; request {request_id}' if isinstance(request_id, str) and _REQUEST_RE.fullmatch(request_id) else ''
    return f'Mart renewal: {reason}{suffix}'


def _lock_context(listing_id):
    """Separate locks avoid PostgreSQL FOR UPDATE on nullable outer joins."""
    listing = Listing.objects.select_for_update().get(pk=listing_id)
    if not listing.integration_account_id:
        raise _Unsafe('missing_account')
    account = IntegrationAccount.objects.select_for_update().only('id', 'slug', 'provider', 'role', 'is_active').get(pk=listing.integration_account_id)
    if account.slug != MART_ACCOUNT_SLUG or account.provider != 'playerauctions':
        raise _Unsafe('not_mart')
    if not account.is_active or account.role not in (IntegrationAccount.Role.SELL, IntegrationAccount.Role.BOTH):
        raise _Unsafe('inactive_account')
    credential = IntegrationCredential.objects.only('id', 'is_active').filter(account_id=account.pk).first()
    if credential is None or not credential.is_active:
        raise _Unsafe('inactive_credentials')
    clones = list(OfferPoolActiveOffer.objects.select_for_update().filter(listing_id=listing.pk, status=OfferPoolActiveOfferStatus.ACTIVE))
    if len(clones) != 1:
        raise _Unsafe('no_exact_active_clone')
    clone = clones[0]
    if not clone.pool_item_id or not clone.pool_offer_id:
        raise _Unsafe('missing_clone_linkage')
    item = OfferPoolItem.objects.select_for_update().get(pk=clone.pool_item_id)
    product = OwnedProduct.objects.select_for_update().only('id', 'status', 'game_id', 'ref_key').get(pk=item.owned_product_id)
    lane = PoolOffer.objects.select_for_update().get(pk=clone.pool_offer_id)
    pool = OfferPool.objects.select_for_update().get(pk=clone.pool_id)
    template = Listing.objects.select_for_update().get(pk=lane.listing_id)
    if lane.listing_id == listing.pk:
        raise _Unsafe('root_template_not_stock_clone')
    if lane.pool_id != pool.pk or item.pool_id != pool.pk or item.pool_offer_id != lane.pk:
        raise _Unsafe('pool_lane_mismatch')
    if template.integration_account_id != account.pk:
        raise _Unsafe('template_account_mismatch')
    if pool.status != OfferPoolStatus.ACTIVE or lane.status != PoolOfferStatus.ACTIVE or lane.strategy != PoolOfferStrategy.CLONE:
        raise _Unsafe('inactive_pool_or_lane')
    if not listing.is_instant or listing.dropship_product_id or listing.product_category != 'accounts' or listing.status != ListingStatus.LISTED:
        raise _Unsafe('listing_not_eligible')
    if not listing.game_id or listing.game_id != pool.game_id or template.game_id != pool.game_id or product.game_id != pool.game_id:
        raise _Unsafe('game_mismatch')
    offer_id = _offer_id(listing.store_listing_id)
    if not offer_id or clone.store_listing_id != offer_id or item.target_offer_id != offer_id:
        raise _Unsafe('offer_id_mismatch')
    if item.status != OfferPoolItemStatus.PUSHED:
        raise _Unsafe('item_not_pushed')
    if item.live_owned_product_id != product.pk:
        raise _Unsafe('live_owner_mismatch')
    links = list(ListingOwnedProduct.objects.select_for_update().filter(listing_id=listing.pk).values_list('owned_product_id', flat=True))
    if links != [product.pk]:
        raise _Unsafe('listing_product_mismatch')
    if product.status not in (OwnedProductStatus.DRAFT, OwnedProductStatus.LISTED):
        raise _Unsafe('product_sold_or_protected')
    return listing, clone, item, product, lane, pool


def _stock_history(context):
    """Retain stock evidence across former items, clones, listings and offer IDs."""
    listing, clone, item, product, lane, pool = context
    item_ids = list(OfferPoolItem.objects.filter(Q(owned_product_id=product.pk) | Q(live_owned_product_id=product.pk)).values_list('pk', flat=True))
    listing_ids = set(ListingOwnedProduct.objects.filter(owned_product_id=product.pk).values_list('listing_id', flat=True))
    listing_ids.add(listing.pk)
    listing_ids.update(OfferPoolActiveOffer.objects.filter(pool_item_id__in=item_ids).exclude(listing_id=None).values_list('listing_id', flat=True))
    identities = set(Listing.objects.filter(pk__in=listing_ids).values_list('integration_account_id', 'store_listing_id'))
    identities.update(OfferPoolActiveOffer.objects.filter(pool_item_id__in=item_ids).values_list('pool_offer__listing__integration_account_id', 'store_listing_id'))
    identities.update(OfferPoolItem.objects.filter(pk__in=item_ids).values_list('pool_offer__listing__integration_account_id', 'target_offer_id'))
    identities.update(PoolDispatchAttempt.objects.filter(item_id__in=item_ids).values_list('pool_offer__listing__integration_account_id', 'remote_offer_id'))
    for account_id, old_id, new_id in PaMartRenewalAttempt.objects.filter(listing_id__in=listing_ids).values_list('integration_account_id', 'old_offer_id', 'new_offer_id'):
        identities.update(((account_id, old_id), (account_id, new_id)))
    identities.update(PlayerAuctionsEditRequest.objects.filter(Q(listing_id__in=listing_ids) | Q(pool_item_id__in=item_ids)).values_list('listing__integration_account_id', 'returned_offer_id'))
    codes = {extract_tracking_code(title) for title in Listing.objects.filter(pk__in=listing_ids).values_list('title', flat=True)}
    codes.add(extract_tracking_code(product.ref_key))
    return item_ids, listing_ids, {(a, i) for a, i in identities if a and i}, codes - {''}


def _stock_guard(context):
    listing, clone, item, product, lane, pool = context
    item_ids, listing_ids, identities, codes = _stock_history(context)
    stock_items = OfferPoolItem.objects.filter(pk__in=item_ids)
    if stock_items.filter(Q(claim_token__isnull=False) | Q(claimed_at__isnull=False) | Q(reservation__status=PoolDispatchReservationStatus.ACTIVE)).exists():
        raise _Unsafe('active_stock_claim')
    if PoolDispatchAttempt.objects.filter(item_id__in=item_ids, status__in=(PoolDispatchStatus.PENDING, PoolDispatchStatus.IN_PROGRESS, PoolDispatchStatus.UNKNOWN)).exists():
        raise _Unsafe('unresolved_stock_dispatch')
    if PlayerAuctionsEditRequest.objects.filter(Q(listing_id__in=listing_ids) | Q(pool_item_id__in=item_ids), status__in=(PlayerAuctionsEditRequestStatus.QUEUED, PlayerAuctionsEditRequestStatus.RUNNING)).exists():
        raise _Unsafe('active_stock_edit')
    if OfferPoolActiveOffer.objects.filter(pool_item_id__in=item_ids, status=OfferPoolActiveOfferStatus.ACTIVE).exclude(pk=clone.pk).exists():
        raise _Unsafe('other_active_stock_clone')
    if OfferPoolActiveOffer.objects.filter(Q(pool_item_id__in=item_ids) | Q(listing_id__in=listing_ids), status=OfferPoolActiveOfferStatus.SOLD).exists():
        raise _Unsafe('sold_stock_clone')
    orders = Q(owned_product_id=product.pk) | Q(listing_id__in=listing_ids)
    for account_id, offer_id in identities:
        orders |= Q(integration_account_id=account_id, store_listing_id=offer_id)
    if Order.objects.filter(orders).exists():
        raise _Unsafe('stock_order_evidence')
    if OrderReplacement.objects.filter(Q(old_product_id=product.pk) | Q(new_product_id=product.pk) | Q(pool_item_id__in=item_ids)).exists():
        raise _Unsafe('stock_replacement_evidence')
    if FaultyAccountReturn.objects.filter(pool_item_id__in=item_ids).exists() or ManualFaultyPoolTransfer.objects.filter(pool_item_id__in=item_ids).exists():
        raise _Unsafe('stock_quarantine_evidence')
    if PoolSaleEvent.objects.filter(Q(pool_item_id__in=item_ids) | Q(listing_id__in=listing_ids)).exists():
        raise _Unsafe('stock_sale_event')
    if PaGmailOrderEvent.objects.filter(Q(listing_id__in=listing_ids) | Q(order__owned_product_id=product.pk) | Q(tracking_code__in=codes)).exists():
        raise _Unsafe('signed_stock_order_event')


def _collision(context, offer_id):
    listing, clone, item, product, lane, pool = context
    account_id = listing.integration_account_id
    if Listing.objects.filter(integration_account_id=account_id, store_listing_id=offer_id).exclude(pk=listing.pk).exists():
        return True
    if OfferPoolActiveOffer.objects.filter(Q(listing__integration_account_id=account_id) | Q(pool_offer__listing__integration_account_id=account_id), store_listing_id=offer_id).exclude(pk=clone.pk).exists():
        return True
    if OfferPoolItem.objects.filter(pool_offer__listing__integration_account_id=account_id, target_offer_id=offer_id).exclude(pk=item.pk).exists():
        return True
    # Both succeeded aliases and verified IDs retained in unknown attempts reserve
    # identity. No remote ID may silently attach to another historical listing.
    return PaMartRenewalAttempt.objects.filter(Q(old_offer_id=offer_id) | Q(new_offer_id=offer_id), integration_account_id=account_id).exclude(listing_id=listing.pk).exists()


def _fresh_checks(context, *, now, lead_hours, attempt=None):
    listing = context[0]
    expiry = listing.marketplace_expires_at
    if not _aware(expiry) or not now < expiry <= now + timedelta(hours=lead_hours):
        raise _Unsafe('outside_unexpired_lead_window')
    if attempt is not None and (listing.integration_account_id != attempt.integration_account_id or listing.store_listing_id != attempt.old_offer_id or expiry != attempt.previous_expires_at):
        raise _Unsafe('renewal_cycle_changed')
    _stock_guard(context)
    _, listing_ids, _, _ = _stock_history(context)
    holds = PaMartRenewalAttempt.objects.filter(listing_id__in=listing_ids, status__in=_UNRESOLVED)
    if attempt is not None:
        holds = holds.exclude(pk=attempt.pk)
    if holds.exists():
        raise _Unsafe('unresolved_stock_renewal')
    if _collision(context, listing.store_listing_id):
        raise _Unsafe('current_identity_collision')


def _verified_result(result, previous_expiry, now):
    data = getattr(result, 'data', None)
    if getattr(result, 'ok', None) is not True or not isinstance(data, dict):
        return '', None, 'remote_outcome_unverified'
    new_id = _offer_id(data.get('offer_id'))
    if not new_id:
        return '', None, 'invalid_returned_offer_id'
    value = data.get('expires_at')
    if not isinstance(value, str) or len(value) > 80:
        return new_id, None, 'missing_verified_expiry'
    try:
        expiry = datetime.fromisoformat(value.replace('Z', '+00:00'))
        if not _aware(expiry):
            return new_id, None, 'invalid_verified_expiry'
        if expiry <= previous_expiry or expiry <= now or expiry > now + timedelta(days=35):
            return new_id, None, 'invalid_verified_extension'
    except (TypeError, ValueError, OverflowError):
        return new_id, None, 'invalid_verified_expiry'
    return new_id, expiry, ''


def _local_rejection(result):
    details = getattr(getattr(result, 'error', None), 'details', None)
    if getattr(result, 'ok', None) is not False or not isinstance(details, dict) or getattr(result, 'data', None):
        return ''
    # Provider strips these proof fields from network responses. Only its local
    # sentinel plus a finite pretransport reason is eligible; extra identity or
    # response content contradicts that proof and remains unknown.
    if set(details) - {'delegation_outcome', 'no_write_proof', 'error_code'}:
        return ''
    if details.get('delegation_outcome') == 'rejected' and details.get('no_write_proof') == _LOCAL_NO_WRITE_PROOF and details.get('error_code') in _LOCAL_REJECTION_REASONS:
        return details['error_code']
    return ''


def _finish(attempt, status, reason, *, new_id='', expiry=None):
    attempt.status = status
    attempt.reason_code = reason
    if new_id:
        attempt.new_offer_id = new_id
    if expiry is not None:
        attempt.verified_expires_at = expiry
    attempt.save(update_fields=['status', 'reason_code', 'new_offer_id', 'verified_expires_at', 'updated_at'])


def renew_mart_listing(listing_id, client, *, lead_hours=96) -> tuple[str, str]:
    """Return renewed/rejected/unknown, with a bounded local-only reason message."""
    if connection.in_atomic_block or not connection.get_autocommit():
        return 'rejected', _message('enclosing_transaction_refused')
    if not _enabled():
        return 'rejected', _message('renewal_feature_disabled')
    if isinstance(lead_hours, bool) or not isinstance(lead_hours, (int, float)) or not 0 < lead_hours <= 96:
        return 'rejected', _message('invalid_lead_hours')
    attempt = None
    try:
        with transaction.atomic(durable=True):
            listing = Listing.objects.select_for_update().get(pk=listing_id)
            hold = PaMartRenewalAttempt.objects.filter(listing_id=listing.pk, status__in=_UNRESOLVED).order_by('pk').first()
            if hold is not None:
                return 'unknown', _message('existing_unresolved_attempt', hold.request_id)
            previous_expiry = listing.marketplace_expires_at
            if not _offer_id(listing.store_listing_id) or not _aware(previous_expiry):
                return 'rejected', _message('invalid_recorded_cycle')
            existing = PaMartRenewalAttempt.objects.filter(listing_id=listing.pk, old_offer_id=listing.store_listing_id, previous_expires_at=previous_expiry).first()
            if existing is not None:
                outcome = 'renewed' if existing.status == PaMartRenewalAttempt.Status.SUCCEEDED else 'rejected'
                return outcome, _message('cycle_already_recorded', existing.request_id)
            context = _lock_context(listing_id)
            _fresh_checks(context, now=timezone.now(), lead_hours=lead_hours)
            if not _enabled():
                raise _Unsafe('renewal_feature_disabled')
            fingerprint = tuple(obj.pk for obj in context)
            attempt = PaMartRenewalAttempt.objects.create(
                listing_id=listing.pk, integration_account_id=listing.integration_account_id,
                request_id=mart_renewal_request_id(listing.store_listing_id, previous_expiry),
                old_offer_id=listing.store_listing_id, previous_expires_at=previous_expiry,
                status=PaMartRenewalAttempt.Status.PENDING, reason_code='claimed_before_transport',
            )
        # The only send site is after the durable claim has committed. Never call
        # this helper from ATOMIC_REQUESTS / TestCase / legacy command atomic.
    except _Unsafe as exc:
        return 'rejected', _message(str(exc))
    except Exception:
        return 'unknown', _message('claim_database_or_validation_failure')

    new_id, verified_expiry = '', None
    sent = False
    try:
        with transaction.atomic():
            context = _lock_context(listing_id)
            attempt = PaMartRenewalAttempt.objects.select_for_update().get(pk=attempt.pk)
            if attempt.status != PaMartRenewalAttempt.Status.PENDING:
                return 'unknown', _message('attempt_no_longer_pending', attempt.request_id)
            try:
                if not _enabled():
                    raise _Unsafe('renewal_feature_disabled')
                if tuple(obj.pk for obj in context) != fingerprint:
                    raise _Unsafe('stock_linkage_changed')
                _fresh_checks(context, now=timezone.now(), lead_hours=lead_hours, attempt=attempt)
            except _Unsafe as exc:
                _finish(attempt, PaMartRenewalAttempt.Status.REJECTED, str(exc))
                return 'rejected', _message(str(exc), attempt.request_id)
            sent = True
            try:
                result = client.renew_offer(attempt.old_offer_id, request_id=attempt.request_id)
            except Exception:
                _finish(attempt, PaMartRenewalAttempt.Status.UNKNOWN, 'transport_outcome_unknown')
                return 'unknown', _message('transport_outcome_unknown', attempt.request_id)
            new_id, verified_expiry, reason = _verified_result(result, attempt.previous_expires_at, timezone.now())
            local_reason = _local_rejection(result)
            # Re-read every ownership/sale check after transport. The remote
            # marketplace cannot participate in these database locks.
            try:
                fresh = _lock_context(listing_id)
                if tuple(obj.pk for obj in fresh) != fingerprint:
                    raise _Unsafe('stock_linkage_changed')
                _fresh_checks(fresh, now=timezone.now(), lead_hours=lead_hours, attempt=attempt)
                if not _enabled():
                    raise _Unsafe('renewal_feature_disabled')
                if new_id and _collision(fresh, new_id):
                    raise _Unsafe('replacement_identity_collision')
            except _Unsafe as exc:
                _finish(attempt, PaMartRenewalAttempt.Status.UNKNOWN, str(exc), new_id=new_id, expiry=verified_expiry)
                return 'unknown', _message(str(exc), attempt.request_id)
            if local_reason:
                _finish(attempt, PaMartRenewalAttempt.Status.REJECTED, local_reason)
                return 'rejected', _message(local_reason, attempt.request_id)
            if reason:
                _finish(attempt, PaMartRenewalAttempt.Status.UNKNOWN, reason, new_id=new_id)
                return 'unknown', _message(reason, attempt.request_id)
            listing, clone, item, _, _, _ = fresh
            now = timezone.now()
            # QuerySet updates deliberately bypass product/listing status signals
            # and OfferPoolItem.save's live-owner rewrite. Only these exact rows.
            Listing.objects.filter(pk=listing.pk).update(store_listing_id=new_id, marketplace_expires_at=verified_expiry, listed_at=now, updated_at=now)
            OfferPoolActiveOffer.objects.filter(pk=clone.pk).update(store_listing_id=new_id, updated_at=now)
            OfferPoolItem.objects.filter(pk=item.pk).update(target_offer_id=new_id, updated_at=now)
            _finish(attempt, PaMartRenewalAttempt.Status.SUCCEEDED, 'verified_renewal', new_id=new_id, expiry=verified_expiry)
            return 'renewed', _message('verified_renewal', attempt.request_id)
    except Exception:
        # If finalization rolled back, the first committed pending row still
        # fences retries. Best-effort sanitized evidence helps reconciliation.
        try:
            with transaction.atomic():
                locked = PaMartRenewalAttempt.objects.select_for_update().get(pk=attempt.pk)
                if locked.status == PaMartRenewalAttempt.Status.PENDING:
                    _finish(locked, PaMartRenewalAttempt.Status.UNKNOWN, 'post_send_database_or_guard_failure' if sent else 'pre_send_database_or_guard_failure', new_id=new_id, expiry=verified_expiry)
        except Exception:
            pass
        return 'unknown', _message('durable_attempt_requires_reconciliation', attempt.request_id)
