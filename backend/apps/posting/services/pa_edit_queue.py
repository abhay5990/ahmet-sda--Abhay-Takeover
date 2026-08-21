"""Durable global queue for manual PlayerAuctions offer edits."""

from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any

from django.db import transaction
from django.utils import timezone

from apps.posting.models import (
    OfferPoolActiveOfferStatus,
    PlayerAuctionsEditRequest,
    PlayerAuctionsEditRequestStatus,
)

logger = logging.getLogger(__name__)
MINIMUM_GAP = timedelta(seconds=60)


def enqueue_pa_edit(
    *,
    listing,
    changes: dict[str, Any],
    pool_offer=None,
    pool_item=None,
    active_offer=None,
) -> PlayerAuctionsEditRequest:
    """Create or return the outstanding request for one exact PA listing."""
    with transaction.atomic():
        outstanding = (
            PlayerAuctionsEditRequest.objects.select_for_update()
            .filter(
                listing=listing,
                status__in=(
                    PlayerAuctionsEditRequestStatus.QUEUED,
                    PlayerAuctionsEditRequestStatus.RUNNING,
                ),
            )
            .order_by('created_at')
            .first()
        )
        if outstanding:
            return outstanding
        return PlayerAuctionsEditRequest.objects.create(
            listing=listing,
            pool_offer=pool_offer,
            pool_item=pool_item,
            active_offer=active_offer,
            changes=dict(changes),
        )


def process_next_pa_edit() -> PlayerAuctionsEditRequest | None:
    """Run no more than one queued PA update, respecting the global gap."""
    now = timezone.now()
    with transaction.atomic():
        last_started = (
            PlayerAuctionsEditRequest.objects.exclude(started_at__isnull=True)
            .order_by('-started_at')
            .values_list('started_at', flat=True)
            .first()
        )
        if last_started and now < last_started + MINIMUM_GAP:
            return None
        request = (
            PlayerAuctionsEditRequest.objects.select_for_update(skip_locked=True)
            .filter(status=PlayerAuctionsEditRequestStatus.QUEUED)
            .order_by('created_at', 'pk')
            .first()
        )
        if request is None:
            return None
        request.status = PlayerAuctionsEditRequestStatus.RUNNING
        request.started_at = now
        request.error_message = ''
        request.save(update_fields=['status', 'started_at', 'error_message'])

    try:
        request = PlayerAuctionsEditRequest.objects.select_related(
            'listing__integration_account__credential',
            'pool_offer__pool',
            'pool_item__owned_product',
            'active_offer',
        ).get(pk=request.pk)
        if request.listing.integration_account.provider != 'playerauctions':
            raise ValueError('Queued listing is not a PlayerAuctions offer')
        if request.active_offer_id and request.active_offer.status != OfferPoolActiveOfferStatus.ACTIVE:
            raise ValueError('Selected PlayerAuctions clone is no longer active')

        from apps.posting.services.offer_editor import _edit_pa_single

        result = _edit_pa_single(
            request.listing,
            request.changes or {},
            request.listing.integration_account,
        )
        if not result.ok:
            raise ValueError(result.error or 'PlayerAuctions update failed')
    except Exception as exc:
        logger.exception('PlayerAuctions edit request %s failed', request.pk)
        request.status = PlayerAuctionsEditRequestStatus.FAILED
        request.error_message = str(exc)[:2000]
        request.finished_at = timezone.now()
        request.save(update_fields=['status', 'error_message', 'finished_at'])
        return request

    request.status = PlayerAuctionsEditRequestStatus.SUCCEEDED
    request.returned_offer_id = str(result.new_offer_id or '')
    request.finished_at = timezone.now()
    request.save(update_fields=['status', 'returned_offer_id', 'finished_at'])
    return request
