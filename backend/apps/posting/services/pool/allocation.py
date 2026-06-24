"""Concurrency-safe allocation primitives for unified offer pools."""
from __future__ import annotations

import hashlib
import uuid
from collections.abc import Iterable
from datetime import timedelta

from django.db import connection, transaction
from django.utils import timezone

from apps.posting.models import (
    OfferPoolItem,
    OfferPoolItemStatus,
    PoolDispatchAttempt,
    PoolDispatchOperation,
    PoolDispatchStatus,
    PoolOffer,
)


def _request_fingerprint(pool_offer_id: int, item_id: int, token: uuid.UUID) -> str:
    value = f'pool-push:{pool_offer_id}:{item_id}:{token}'
    return hashlib.sha256(value.encode()).hexdigest()


def claim_pending_items(pool_offer: PoolOffer, limit: int) -> list[OfferPoolItem]:
    """Atomically reserve up to ``limit`` unassigned items for one PoolOffer.

    The database transaction ends before callers perform remote I/O. A durable
    attempt and claim token make a lost/unknown remote response reconcilable.
    """
    if limit <= 0:
        return []

    with transaction.atomic():
        locked_offer = (
            PoolOffer.objects.select_for_update()
            .select_related('pool')
            .get(pk=pool_offer.pk)
        )
        if not locked_offer.can_replenish:
            return []

        items_qs = (
            OfferPoolItem.objects
            .filter(
                pool_id=locked_offer.pool_id,
                status=OfferPoolItemStatus.PENDING,
                pool_offer__isnull=True,
            )
            .select_related('owned_product')
            .order_by('order', 'created_at')
        )
        if connection.features.has_select_for_update:
            lock_kwargs = {}
            if connection.features.has_select_for_update_skip_locked:
                lock_kwargs['skip_locked'] = True
            items_qs = items_qs.select_for_update(**lock_kwargs)

        items = list(items_qs[:limit])
        now = timezone.now()
        for item in items:
            token = uuid.uuid4()
            item.pool_offer_id = locked_offer.pk
            item.status = OfferPoolItemStatus.QUEUED
            item.claim_token = token
            item.claimed_at = now
            item.failure_stage = ''
            item.remote_state = ''
            item.error_message = ''
            item.save(update_fields=[
                'pool_offer', 'status', 'claim_token', 'claimed_at',
                'failure_stage', 'remote_state', 'error_message', 'updated_at',
            ])
            PoolDispatchAttempt.objects.create(
                idempotency_key=token,
                item=item,
                pool_offer=locked_offer,
                operation=PoolDispatchOperation.PUSH,
                status=PoolDispatchStatus.IN_PROGRESS,
                request_fingerprint=_request_fingerprint(locked_offer.pk, item.pk, token),
                started_at=now,
            )
        return items


def mark_items_pushed(
    items: Iterable[OfferPoolItem],
    *,
    pool_offer: PoolOffer,
    remote_offer_id: str,
    remote_credential_ids: dict[int, str] | None = None,
) -> int:
    """Finalize successfully pushed claims and their durable attempts."""
    count = 0
    now = timezone.now()
    remote_credential_ids = remote_credential_ids or {}
    for candidate in items:
        with transaction.atomic():
            item = OfferPoolItem.objects.select_for_update().get(pk=candidate.pk)
            if (
                item.status != OfferPoolItemStatus.QUEUED
                or item.pool_offer_id != pool_offer.pk
                or not item.claim_token
            ):
                continue
            token = item.claim_token
            remote_credential_id = remote_credential_ids.get(item.pk, '')
            item.status = OfferPoolItemStatus.PUSHED
            item.pushed_at = now
            item.target_offer_id = remote_offer_id  # transitional compatibility
            item.remote_credential_id = remote_credential_id
            item.claim_token = None
            item.claimed_at = None
            item.failure_stage = ''
            item.remote_state = 'present'
            item.error_message = ''
            item.save(update_fields=[
                'status', 'pushed_at', 'target_offer_id', 'remote_credential_id',
                'claim_token', 'claimed_at', 'failure_stage', 'remote_state',
                'error_message', 'updated_at',
            ])
            PoolDispatchAttempt.objects.filter(idempotency_key=token).update(
                status=PoolDispatchStatus.SUCCEEDED,
                remote_offer_id=remote_offer_id,
                remote_credential_id=remote_credential_id,
                finished_at=now,
            )
            count += 1
    return count


def mark_item_failed(
    item: OfferPoolItem,
    *,
    error_message: str,
    failure_stage: str,
    remote_state: str,
    retryable: bool = False,
) -> None:
    """Finish a failed claim without risking an automatic duplicate push."""
    now = timezone.now()
    with transaction.atomic():
        locked = OfferPoolItem.objects.select_for_update().get(pk=item.pk)
        token = locked.claim_token
        if retryable and remote_state == 'absent':
            locked.status = OfferPoolItemStatus.PENDING
            locked.pool_offer = None
        else:
            locked.status = OfferPoolItemStatus.FAILED
        locked.claim_token = None
        locked.claimed_at = None
        locked.failure_stage = failure_stage[:30]
        locked.remote_state = remote_state[:20]
        locked.error_message = error_message[:2000]
        locked.save(update_fields=[
            'status', 'pool_offer', 'claim_token', 'claimed_at', 'failure_stage',
            'remote_state', 'error_message', 'updated_at',
        ])
        if token:
            PoolDispatchAttempt.objects.filter(idempotency_key=token).update(
                status=(
                    PoolDispatchStatus.UNKNOWN
                    if remote_state == 'unknown'
                    else PoolDispatchStatus.FAILED
                ),
                error_code=failure_stage[:64],
                error_message=error_message[:2000],
                finished_at=now,
            )


def release_claims_as_pending(items: Iterable[OfferPoolItem], reason: str) -> None:
    for item in items:
        mark_item_failed(
            item,
            error_message=reason,
            failure_stage='known_safe_failure',
            remote_state='absent',
            retryable=True,
        )


def quarantine_stale_claims(max_age: timedelta = timedelta(minutes=15)) -> int:
    """Move abandoned QUEUED claims to FAILED/unknown before another sweep."""
    cutoff = timezone.now() - max_age
    stale_ids = list(
        OfferPoolItem.objects.filter(
            status=OfferPoolItemStatus.QUEUED,
            claimed_at__lt=cutoff,
        ).values_list('pk', flat=True)
    )
    for item_id in stale_ids:
        mark_item_failed(
            OfferPoolItem(pk=item_id),
            error_message='Dispatch claim expired before completion',
            failure_stage='stale_claim',
            remote_state='unknown',
        )
    return len(stale_ids)
