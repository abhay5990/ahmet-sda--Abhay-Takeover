"""Safe PoolOffer detach workflows with provider-specific remote cleanup."""
from __future__ import annotations

import hashlib
import uuid
from dataclasses import dataclass, field

from django.db import models, transaction
from django.utils import timezone

from apps.integrations.providers.registry import get_or_build_client, get_provider
from apps.integrations.proxy_pool import build_proxy_pool, get_group_name
from apps.listings.enums import ListingStatus
from apps.listings.models import ListingOwnedProduct
from apps.posting.models import (
    OfferPoolActiveOffer,
    OfferPoolActiveOfferStatus,
    OfferPoolItem,
    OfferPoolItemStatus,
    PoolDispatchAttempt,
    PoolDispatchOperation,
    PoolDispatchStatus,
    PoolOffer,
    PoolOfferStatus,
)

from .formatter import format_credential_for_marketplace
from .replenisher import _is_gameboost_legacy_payload


@dataclass
class DetachResult:
    ok: bool
    detached: bool = False
    released: int = 0
    errors: list[str] = field(default_factory=list)


@dataclass
class RemoveItemResult:
    ok: bool
    removed: bool = False
    remote_removed: bool = False
    errors: list[str] = field(default_factory=list)


def remove_pool_item(
    pool_offer: PoolOffer,
    item: OfferPoolItem,
    *,
    listing,
) -> RemoveItemResult:
    """Remove one user-selected key without allowing it to be replenished again."""
    pool_offer = PoolOffer.objects.select_related(
        'pool', 'pool__credential_spec', 'pool__variant',
        'listing', 'listing__integration_account',
        'listing__integration_account__credential',
    ).get(pk=pool_offer.pk)
    item = OfferPoolItem.objects.select_related('owned_product').get(
        pk=item.pk,
        pool_offer=pool_offer,
    )

    listing_is_inactive = listing.status in {
        ListingStatus.CLOSED,
        ListingStatus.DELETED,
    }
    is_known_local_only = (
        listing_is_inactive
        or item.remote_state == 'absent'
        or item.status in {
            OfferPoolItemStatus.PENDING,
            OfferPoolItemStatus.CONSUMED,
            OfferPoolItemStatus.REMOVED,
        }
    )
    if is_known_local_only:
        _finalize_single_item_removal(
            pool_offer,
            item,
            listing=listing,
            attempt=None,
            decrement_remote=False,
        )
        return RemoveItemResult(ok=True, removed=True)

    if item.status == OfferPoolItemStatus.RESERVED:
        return RemoveItemResult(
            ok=False,
            errors=['This key is reserved by an in-progress dispatch. Try again after it finishes.'],
        )
    if item.status not in {
        OfferPoolItemStatus.QUEUED,
        OfferPoolItemStatus.PUSHED,
        OfferPoolItemStatus.FAILED,
    }:
        return RemoveItemResult(
            ok=False,
            errors=[f'Key cannot be removed while its Pool state is {item.status}.'],
        )

    attempts = _start_remove_attempts(pool_offer, [item])
    attempt = attempts[item.pk]
    try:
        if pool_offer.strategy == 'clone':
            removed_ids, errors = _remove_pa(pool_offer, [item])
        elif pool_offer.marketplace == 'eldorado':
            removed_ids, errors = _remove_eldorado(pool_offer, [item])
        elif pool_offer.marketplace == 'gameboost':
            removed_ids, errors = _remove_gameboost(pool_offer, [item])
        else:
            removed_ids, errors = set(), ['Unsupported marketplace']
    except Exception as exc:
        _finish_remove_failures(pool_offer, attempts, str(exc), unknown=True)
        return RemoveItemResult(ok=False, errors=[str(exc)])

    if item.pk not in removed_ids:
        error = '; '.join(errors) or 'Remote removal failed'
        _finish_remove_failures(pool_offer, attempts, error, unknown=False)
        return RemoveItemResult(ok=False, errors=errors or [error])

    _finalize_single_item_removal(
        pool_offer,
        item,
        listing=listing,
        attempt=attempt,
        decrement_remote=True,
    )
    return RemoveItemResult(ok=True, removed=True, remote_removed=True)


def _finalize_single_item_removal(
    pool_offer,
    item,
    *,
    listing,
    attempt,
    decrement_remote,
):
    now = timezone.now()
    with transaction.atomic():
        item = OfferPoolItem.objects.select_for_update().get(pk=item.pk)
        ListingOwnedProduct.objects.filter(
            listing=listing,
            owned_product_id=item.owned_product_id,
        ).delete()
        if item.status != OfferPoolItemStatus.CONSUMED:
            item.status = OfferPoolItemStatus.REMOVED
        item.remote_state = 'absent'
        item.remote_credential_id = ''
        item.claim_token = None
        item.claimed_at = None
        item.error_message = ''
        item.failure_stage = ''
        item.save(update_fields=[
            'status', 'remote_state', 'remote_credential_id', 'claim_token',
            'claimed_at', 'error_message', 'failure_stage', 'updated_at',
        ])
        if attempt is not None:
            attempt.status = PoolDispatchStatus.SUCCEEDED
            attempt.finished_at = now
            attempt.save(update_fields=['status', 'finished_at'])
        if decrement_remote and pool_offer.current_remote_count is not None:
            PoolOffer.objects.filter(
                pk=pool_offer.pk,
                current_remote_count__gt=0,
            ).update(
                current_remote_count=models.F('current_remote_count') - 1,
                last_error='',
            )


def detach_pool_offer(pool_offer: PoolOffer, mode: str) -> DetachResult:
    if mode not in {'leave_remote', 'remove_remote'}:
        raise ValueError('Unsupported detach mode')

    pool_offer = PoolOffer.objects.select_related(
        'pool', 'pool__credential_spec', 'pool__variant',
        'listing', 'listing__integration_account',
        'listing__integration_account__credential',
    ).get(pk=pool_offer.pk)
    if mode == 'leave_remote':
        pool_offer.status = PoolOfferStatus.DETACHED
        pool_offer.save(update_fields=['status', 'updated_at'])
        return DetachResult(ok=True, detached=True)

    items = list(
        pool_offer.items.filter(
            status__in=[
                OfferPoolItemStatus.QUEUED,
                OfferPoolItemStatus.PUSHED,
                OfferPoolItemStatus.FAILED,
            ],
        ).select_related('owned_product')
    )
    if not items:
        pool_offer.status = PoolOfferStatus.DETACHED
        pool_offer.save(update_fields=['status', 'updated_at'])
        return DetachResult(ok=True, detached=True)

    pool_offer.status = PoolOfferStatus.PAUSED
    pool_offer.save(update_fields=['status', 'updated_at'])
    attempts = _start_remove_attempts(pool_offer, items)

    try:
        if pool_offer.strategy == 'clone':
            removed_ids, errors = _remove_pa(pool_offer, items)
        elif pool_offer.marketplace == 'eldorado':
            removed_ids, errors = _remove_eldorado(pool_offer, items)
        elif pool_offer.marketplace == 'gameboost':
            removed_ids, errors = _remove_gameboost(pool_offer, items)
        else:
            removed_ids, errors = set(), ['Unsupported marketplace']
    except Exception as exc:
        _finish_remove_failures(pool_offer, attempts, str(exc), unknown=True)
        return DetachResult(ok=False, errors=[str(exc)])

    released = _release_removed_items(
        pool_offer,
        [item for item in items if item.pk in removed_ids],
        attempts,
    )
    failed_items = [item for item in items if item.pk not in removed_ids]
    if failed_items:
        _finish_remove_failures(
            pool_offer,
            {item.pk: attempts[item.pk] for item in failed_items},
            '; '.join(errors) or 'Remote removal failed',
            unknown=False,
        )
        return DetachResult(ok=False, released=released, errors=errors)

    pool_offer.status = PoolOfferStatus.DETACHED
    pool_offer.last_error = ''
    pool_offer.current_remote_count = 0
    pool_offer.save(update_fields=[
        'status', 'last_error', 'current_remote_count', 'updated_at',
    ])
    return DetachResult(ok=True, detached=True, released=released)


def _start_remove_attempts(
    pool_offer: PoolOffer,
    items: list[OfferPoolItem],
) -> dict[int, PoolDispatchAttempt]:
    attempts = {}
    now = timezone.now()
    for item in items:
        key = uuid.uuid4()
        fingerprint = hashlib.sha256(
            f'pool-remove:{pool_offer.pk}:{item.pk}:{key}'.encode(),
        ).hexdigest()
        attempts[item.pk] = PoolDispatchAttempt.objects.create(
            idempotency_key=key,
            item=item,
            pool_offer=pool_offer,
            operation=PoolDispatchOperation.REMOVE,
            status=PoolDispatchStatus.IN_PROGRESS,
            request_fingerprint=fingerprint,
            remote_offer_id=pool_offer.listing.store_listing_id,
            remote_credential_id=item.remote_credential_id,
            started_at=now,
        )
    return attempts


def _client(pool_offer: PoolOffer):
    store = pool_offer.store
    proxy_pool = build_proxy_pool()
    proxy_group = get_group_name(store)
    client = get_or_build_client(
        store.provider,
        store.credential,
        proxy_pool=proxy_pool,
        proxy_group=proxy_group,
    )
    return client, proxy_group


def _remove_pa(pool_offer, items):
    client, _proxy_group = _client(pool_offer)
    provider = get_provider('playerauctions')
    removed = set()
    errors = []
    active_offers = {
        ao.pool_item_id: ao
        for ao in OfferPoolActiveOffer.objects.filter(
            pool_offer=pool_offer,
            pool_item_id__in=[item.pk for item in items],
            status=OfferPoolActiveOfferStatus.ACTIVE,
        ).select_related('listing')
    }
    for item in items:
        active_offer = active_offers.get(item.pk)
        if not active_offer:
            errors.append(f'Item #{item.pk}: active PA offer not found')
            continue
        try:
            result = provider.delete_listing(client, active_offer.store_listing_id)
            if result is not None and hasattr(result, 'ok') and not result.ok:
                errors.append(f'Item #{item.pk}: {result.error}')
                continue
            active_offer.status = OfferPoolActiveOfferStatus.DELISTED
            active_offer.save(update_fields=['status', 'updated_at'])
            if active_offer.listing:
                active_offer.listing.status = ListingStatus.DELETED
                active_offer.listing.removed_at = timezone.now()
                active_offer.listing.save(update_fields=[
                    'status', 'removed_at', 'updated_at',
                ])
            removed.add(item.pk)
        except Exception as exc:
            errors.append(f'Item #{item.pk}: {exc}')
    return removed, errors


def _remove_eldorado(pool_offer, items):
    client, proxy_group = _client(pool_offer)
    offer_id = pool_offer.listing.store_listing_id
    details = client.get_offer_account_details(offer_id, proxy_group=proxy_group)
    if not details.ok:
        return set(), [str(details.error)]

    response = details.data
    entries = getattr(response, 'secretDetails', None) or getattr(
        response, 'accountsDetails', None,
    ) or []
    existing = [entry.secretDetails for entry in entries if entry.secretDetails]
    remove_values = [
        format_credential_for_marketplace(
            item.owned_product, 'eldorado', pool=pool_offer.pool,
        ).strip()
        for item in items
    ]
    remaining = list(existing)
    removed = set()
    for item, value in zip(items, remove_values):
        match = next((entry for entry in remaining if entry.strip() == value), None)
        if match is not None:
            remaining.remove(match)
            removed.add(item.pk)

    if not removed:
        return set(), ['No managed Eldorado credentials matched remote state']
    if remaining:
        result = client.update_offer(
            offer_id,
            {'accountSecretDetails': remaining},
            proxy_group=proxy_group,
        )
    else:
        result = client.delete_offer(offer_id, proxy_group=proxy_group)
    if not result.ok:
        return set(), [str(result.error)]
    return removed, []


def _remove_gameboost(pool_offer, items):
    client, proxy_group = _client(pool_offer)
    offer_id = pool_offer.listing.store_listing_id
    if _is_gameboost_legacy_payload(pool_offer.listing):
        result = client.delete_offer(offer_id, proxy_group=proxy_group)
        return (
            ({item.pk for item in items}, [])
            if result.ok else (set(), [str(result.error)])
        )

    result = client.list_offer_credentials(offer_id, proxy_group=proxy_group)
    if not result.ok:
        return set(), [str(result.error)]
    entries = list(result.data or [])
    by_text = {
        str(getattr(entry, 'credentials', '')).strip(): str(getattr(entry, 'id', ''))
        for entry in entries
    }
    remote_ids: list[int] = []
    item_by_remote = {}
    for item in items:
        remote_id = item.remote_credential_id
        if not remote_id:
            rendered = format_credential_for_marketplace(
                item.owned_product, 'gameboost', pool=pool_offer.pool,
            )
            remote_id = by_text.get(str(rendered).strip(), '')
        if remote_id:
            numeric_id = int(remote_id)
            remote_ids.append(numeric_id)
            item_by_remote[numeric_id] = item.pk
    if not remote_ids:
        return set(), ['No managed GameBoost credential IDs matched remote state']
    deleted = client.bulk_delete_offer_credentials(
        offer_id,
        remote_ids,
        proxy_group=proxy_group,
    )
    if not deleted.ok:
        return set(), [str(deleted.error)]
    return {item_by_remote[remote_id] for remote_id in remote_ids}, []


def _release_removed_items(pool_offer, items, attempts):
    now = timezone.now()
    released = 0
    with transaction.atomic():
        for candidate in items:
            item = OfferPoolItem.objects.select_for_update().get(pk=candidate.pk)
            ListingOwnedProduct.objects.filter(
                owned_product_id=item.owned_product_id,
            ).filter(
                models.Q(listing=pool_offer.listing)
                | models.Q(listing__pool_active_offers__pool_offer=pool_offer)
            ).delete()
            item.status = OfferPoolItemStatus.PENDING
            item.pool_offer = None
            item.target_offer_id = ''
            item.remote_credential_id = ''
            item.remote_state = 'absent'
            item.pushed_at = None
            item.claim_token = None
            item.claimed_at = None
            item.error_message = ''
            item.failure_stage = ''
            item.save(update_fields=[
                'status', 'pool_offer', 'target_offer_id', 'remote_credential_id',
                'remote_state', 'pushed_at', 'claim_token', 'claimed_at',
                'error_message', 'failure_stage', 'updated_at',
            ])
            attempts[item.pk].status = PoolDispatchStatus.SUCCEEDED
            attempts[item.pk].finished_at = now
            attempts[item.pk].save(update_fields=['status', 'finished_at'])
            released += 1
    return released


def _finish_remove_failures(pool_offer, attempts, error, *, unknown):
    now = timezone.now()
    status = PoolDispatchStatus.UNKNOWN if unknown else PoolDispatchStatus.FAILED
    for attempt in attempts.values():
        attempt.status = status
        attempt.error_code = 'remote_remove'
        attempt.error_message = error[:2000]
        attempt.finished_at = now
        attempt.save(update_fields=[
            'status', 'error_code', 'error_message', 'finished_at',
        ])
    pool_offer.status = PoolOfferStatus.ERROR
    pool_offer.last_error = error[:2000]
    pool_offer.save(update_fields=['status', 'last_error', 'updated_at'])
