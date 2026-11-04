"""Fenced local finalization of one Mart create claim; never retries HTTP writes."""
import re

from django.db import transaction
from django.utils import timezone

from apps.inventory.enums import OwnedProductStatus
from apps.orders.models import Order
from apps.posting.models import (
    OfferPoolItem, OfferPoolItemStatus, PoolDispatchAttempt, PoolDispatchOperation,
    PoolDispatchStatus, PoolSaleEvent, OfferPoolActiveOffer, OfferPoolActiveOfferStatus,
)


def finalize_mart_claim_failure(candidate, *, expected_token, local_pretransport=False, request_id=''):
    """Only the exact in-flight claim may be changed by its failure response.

    A local pretransport refusal can release a provably unsubmitted claim. Every
    external/ambiguous failure remains FAILED/unknown. Sale evidence wins even
    when the local call never reached transport. No raw provider text is stored.
    """
    if not expected_token:
        return False
    with transaction.atomic():
        item = OfferPoolItem.objects.select_for_update().select_related('owned_product', 'pool_offer__listing__integration_account').get(pk=candidate.pk)
        if (
            item.status != OfferPoolItemStatus.QUEUED
            or item.claim_token != expected_token
            or item.pool_offer_id != candidate.pool_offer_id
            or item.pool_id != candidate.pool_id
            or item.owned_product_id != candidate.owned_product_id
            or item.pool_offer is None
            or item.pool_offer.pool_id != item.pool_id
            or item.pool_offer.listing.integration_account.slug != 'playerauctions-csgosmurfkings'
            or item.pool_offer.listing.integration_account.provider != 'playerauctions'
        ):
            return False
        attempt = PoolDispatchAttempt.objects.select_for_update().filter(
            idempotency_key=expected_token, item=item, pool_offer_id=item.pool_offer_id,
            operation=PoolDispatchOperation.PUSH, status=PoolDispatchStatus.IN_PROGRESS,
        ).first()
        if attempt is None:
            return False
        protected = (
            item.owned_product is None
            or item.owned_product.status not in {OwnedProductStatus.DRAFT, OwnedProductStatus.LISTED}
            or Order.objects.filter(owned_product_id=item.owned_product_id).exists()
            or PoolSaleEvent.objects.filter(pool_item=item).exists()
            or OfferPoolActiveOffer.objects.filter(pool_item__owned_product_id=item.owned_product_id, status__in=[OfferPoolActiveOfferStatus.ACTIVE, OfferPoolActiveOfferStatus.SOLD]).exists()
        )
        release = local_pretransport is True and not protected
        message = (
            'Mart claim not submitted: locally refused before transport; deferred.'
            if release else 'Mart create outcome unverified or stock protected; reconcile the exact attempt before retry.'
        )
        if isinstance(request_id, str) and re.fullmatch(r'[0-9a-f]{40}', request_id):
            message += ' Request ID: ' + request_id
        item.status = OfferPoolItemStatus.PENDING if release else OfferPoolItemStatus.FAILED
        if release:
            item.pool_offer = None
        item.claim_token = None
        item.claimed_at = None
        item.failure_stage = 'known_safe_failure' if release else 'remote_push'
        item.remote_state = 'absent' if release else 'unknown'
        item.error_message = message
        item.save(update_fields=['status', 'pool_offer', 'claim_token', 'claimed_at', 'failure_stage', 'remote_state', 'error_message', 'updated_at'])
        attempt.status = PoolDispatchStatus.FAILED if release else PoolDispatchStatus.UNKNOWN
        attempt.error_code = item.failure_stage
        attempt.error_message = message
        attempt.finished_at = timezone.now()
        attempt.save(update_fields=['status', 'error_code', 'error_message', 'finished_at'])
        return True
