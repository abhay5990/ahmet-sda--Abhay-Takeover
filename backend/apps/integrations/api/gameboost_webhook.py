"""Verified, fast-acknowledging GameBoost purchase webhook endpoint.

The provider may redeliver events, so this endpoint only authenticates and
persists a unique event ID.  The scheduler processes it later through SDA's
existing GameBoost order ingestion and strict sale-binding safeguards.
"""

from __future__ import annotations

import hashlib
import hmac
import logging

from django.http import HttpRequest, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from apps.integrations.models import IntegrationAccount
from apps.sync.models import GameBoostWebhookEvent

logger = logging.getLogger(__name__)

PURCHASE_TOPIC = 'account.order.purchased'


def signature_is_valid(*, raw_body: bytes, supplied_signature: str, secret: str) -> bool:
    """Validate GameBoost's lowercase hexadecimal HMAC-SHA256 signature."""
    if not supplied_signature or not secret:
        return False
    expected = hmac.new(secret.encode('utf-8'), raw_body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, supplied_signature.strip().lower())


@csrf_exempt
@require_POST
def gameboost_purchase_webhook(request: HttpRequest, account_slug: str) -> HttpResponse:
    """Accept one authenticated GameBoost purchase event without inline sync work."""
    account = get_object_or_404(
        IntegrationAccount.objects.select_related('credential'),
        slug=account_slug,
        provider='gameboost',
        is_active=True,
        credential__is_active=True,
    )
    secret = (account.credential.credentials or {}).get('webhook_secret', '')
    signature = request.META.get('HTTP_X_GAMEBOOST_SIGNATURE', '')
    if not signature_is_valid(
        raw_body=request.body,
        supplied_signature=signature,
        secret=secret,
    ):
        logger.warning('GameBoost webhook rejected: invalid signature for %s', account.slug)
        return JsonResponse({'error': 'invalid signature'}, status=401)

    event_id = request.META.get('HTTP_X_GAMEBOOST_EVENT_ID', '').strip()
    topic = request.META.get('HTTP_X_GAMEBOOST_TOPIC', '').strip()
    if not event_id or not topic:
        return JsonResponse({'error': 'missing required event metadata'}, status=400)

    if topic != PURCHASE_TOPIC:
        # The signed callback is valid but not an account purchase. Acknowledge
        # it quickly; this receiver deliberately has no side effects for other
        # provider events.
        return HttpResponse(status=204)

    event, created = GameBoostWebhookEvent.objects.get_or_create(
        event_id=event_id,
        defaults={
            'integration_account': account,
            'topic': topic,
            'status': GameBoostWebhookEvent.Status.PENDING,
        },
    )
    if not created and event.integration_account_id != account.id:
        logger.error('GameBoost webhook event ID collision across accounts')
        return JsonResponse({'error': 'event conflict'}, status=409)

    return JsonResponse(
        {'accepted': True, 'duplicate': not created},
        status=202,
    )
