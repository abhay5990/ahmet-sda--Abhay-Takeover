"""Signed, minimal PlayerAuctions Gmail order-event receiver for SDA Mart.

CodeTracker owns Gmail OAuth and sends a strict, idempotent event.  SDA accepts
only an order ID, visible tracking code, market, delivery type, and observation
time.  It never receives an email body, customer data, credentials, tokens, or
marketplace action authority.  This receiver creates an SDA order report only
when the code matches exactly one active SDA-owned Mart listing.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import re
import uuid
from datetime import datetime, timezone as dt_timezone
from decimal import Decimal
from typing import Any

from django.conf import settings
from django.db import IntegrityError, transaction
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from apps.integrations.models import IntegrationAccount, PaGmailOrderEvent, Provider
from apps.listings.enums import ListingStatus
from apps.listings.models import Listing
from apps.orders.enums import OrderStatus
from apps.orders.models import Order
from apps.posting.services.stock.pa_tracking import extract_tracking_code

logger = logging.getLogger(__name__)

SOURCE = 'codetracker-pa-gmail'
SIGNATURE_VERSION = 'v1'
MAX_AGE_MS = 10 * 60 * 1000
_CODE_RE = re.compile(r'^#[A-Z0-9]{6,8}$')
# Covers both known Mart store identifiers during their controlled transition.
_MART_STORE_SLUGS = ('csgosmurfkings', 'ezsmurfmart', 'playerauctions-csgosmurfkings')
# CodeTracker owns these games. SDA must never create an order report for one
# even if a manual configuration mistake exposes a matching listing here.
_CODETRACKER_OWNED_GAME_SLUGS = ('fortnite', 'valorant', 'league-of-legends', 'league-of-legends-wild-rift', 'lol', 'rainbow-six-siege', 'r6')


def canonical_payload_json(payload: dict[str, Any]) -> bytes:
    """Return the exact stable JSON string signed by CodeTracker."""
    canonical = {
        'eventId': payload['eventId'],
        'source': payload['source'],
        'orderId': payload['orderId'],
        'code': payload['code'],
        'market': payload['market'],
        'automaticDelivery': payload['automaticDelivery'],
        'observedAt': payload['observedAt'],
    }
    return json.dumps(canonical, separators=(',', ':'), ensure_ascii=False).encode('utf-8')


def signature_is_valid(*, payload: dict[str, Any], timestamp: str, supplied_signature: str, secret: str) -> bool:
    if not secret or not supplied_signature or not timestamp:
        return False
    expected = hmac.new(
        secret.encode('utf-8'),
        f'{SIGNATURE_VERSION}.{timestamp}.'.encode('utf-8') + canonical_payload_json(payload),
        hashlib.sha256,
    ).hexdigest()
    return hmac.compare_digest(expected, supplied_signature.strip().lower())


def parse_payload(raw_body: bytes) -> dict[str, Any]:
    """Validate the intentionally small cross-application event contract."""
    try:
        payload = json.loads(raw_body.decode('utf-8'))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError('invalid JSON body') from exc
    if not isinstance(payload, dict):
        raise ValueError('JSON object required')
    if set(payload) != {'eventId', 'source', 'orderId', 'code', 'market', 'automaticDelivery', 'observedAt'}:
        raise ValueError('unexpected event fields')
    try:
        uuid.UUID(str(payload['eventId']))
    except (ValueError, TypeError, AttributeError) as exc:
        raise ValueError('invalid event ID') from exc
    if payload['source'] != SOURCE:
        raise ValueError('invalid event source')
    if not isinstance(payload['orderId'], str) or not payload['orderId'].isdigit() or len(payload['orderId']) > 128:
        raise ValueError('invalid order ID')
    code = str(payload['code']).strip().upper()
    if not _CODE_RE.fullmatch(code):
        raise ValueError('invalid tracking code')
    if payload['market'] is not None and (not isinstance(payload['market'], str) or len(payload['market']) > 160):
        raise ValueError('invalid market')
    if payload['automaticDelivery'] is not None and not isinstance(payload['automaticDelivery'], bool):
        raise ValueError('invalid delivery type')
    if not isinstance(payload['observedAt'], int) or payload['observedAt'] <= 0:
        raise ValueError('invalid observed time')
    return {
        **payload,
        'eventId': str(payload['eventId']),
        'code': code,
        'market': payload['market'].strip() if isinstance(payload['market'], str) else None,
    }


def find_unique_mart_listing(code: str) -> Listing | None:
    """Resolve only an exact visible code on a current SDA Mart listing."""
    candidates = Listing.objects.select_related('integration_account', 'game').filter(
        integration_account__provider=Provider.PLAYERAUCTIONS,
        integration_account__slug__in=_MART_STORE_SLUGS,
        integration_account__is_active=True,
        status=ListingStatus.LISTED,
        title__icontains=code,
    ).exclude(game__slug__in=_CODETRACKER_OWNED_GAME_SLUGS)
    matches = [listing for listing in candidates if extract_tracking_code(listing.title) == code]
    return matches[0] if len(matches) == 1 else None


def create_order_report(*, event: PaGmailOrderEvent, listing: Listing) -> tuple[Order, bool]:
    sold_at = datetime.fromtimestamp(event.observed_at_ms / 1000, tz=dt_timezone.utc)
    order, created = Order.objects.get_or_create(
        integration_account=listing.integration_account,
        store_order_id=event.external_order_id,
        defaults={
            'is_instant': listing.is_instant,
            'product_category': listing.product_category,
            'listing': listing,
            'game': listing.game,
            'store_listing_id': listing.store_listing_id,
            'status': OrderStatus.PENDING,
            'price': listing.price or Decimal('0'),
            'currency': listing.currency or 'USD',
            'sold_at': sold_at,
            'raw_data': {
                'source': SOURCE,
                'tracking_code': event.tracking_code,
                'market': event.market,
                'automatic_delivery': event.automatic_delivery,
                'observed_at_ms': event.observed_at_ms,
            },
        },
    )
    # The exact tracking-code match is now durably sold in SDA. Close the local
    # listing record so renewal/relist logic cannot offer that dedicated stock
    # again. This is a local state change only: no PA offer mutation or deletion.
    if listing.status != ListingStatus.CLOSED:
        listing.status = ListingStatus.CLOSED
        listing.removed_at = timezone.now()
        listing.save(update_fields=['status', 'removed_at', 'updated_at'])
    return order, created


def recover_unmatched_event(*, event: PaGmailOrderEvent) -> tuple[Order, bool] | None:
    """Re-evaluate a prior unmatched event only after a receiver routing correction.

    The event ID, external order ID, and visible tracking code are immutable.  This
    never searches historical rows or changes a marketplace offer; it can only bind
    the same event to exactly one current SDA-owned Mart listing.
    """
    if event.disposition != PaGmailOrderEvent.Disposition.UNMATCHED or event.order_id:
        return None
    listing = find_unique_mart_listing(event.tracking_code)
    if listing is None:
        return None
    order, created = create_order_report(event=event, listing=listing)
    event.integration_account = listing.integration_account
    event.listing = listing
    event.order = order
    event.disposition = PaGmailOrderEvent.Disposition.CREATED if created else PaGmailOrderEvent.Disposition.DUPLICATE
    event.save(update_fields=['integration_account', 'listing', 'order', 'disposition', 'updated_at'])
    return order, created


@csrf_exempt
@require_POST
def pa_gmail_order_event(request: HttpRequest) -> HttpResponse:
    """Accept an idempotent signed event without marketplace-side actions."""
    secret = getattr(settings, 'CT_PA_GMAIL_EVENT_SECRET', '')
    try:
        payload = parse_payload(request.body)
    except ValueError as exc:
        return JsonResponse({'error': str(exc)}, status=400)

    event_id_header = request.META.get('HTTP_X_PA_GMAIL_EVENT_ID', '').strip()
    timestamp = request.META.get('HTTP_X_PA_GMAIL_TIMESTAMP', '').strip()
    signature = request.META.get('HTTP_X_PA_GMAIL_SIGNATURE', '').strip()
    if event_id_header != payload['eventId']:
        return JsonResponse({'error': 'event ID mismatch'}, status=400)
    try:
        age_ms = abs(int(timezone.now().timestamp() * 1000) - int(timestamp))
    except ValueError:
        return JsonResponse({'error': 'invalid event timestamp'}, status=400)
    if age_ms > MAX_AGE_MS:
        return JsonResponse({'error': 'stale event timestamp'}, status=401)
    if not signature_is_valid(payload=payload, timestamp=timestamp, supplied_signature=signature, secret=secret):
        logger.warning('PA Gmail order event rejected: invalid signature')
        return JsonResponse({'error': 'invalid signature'}, status=401)

    with transaction.atomic():
        existing = PaGmailOrderEvent.objects.select_related('order').filter(event_id=payload['eventId']).first()
        if existing:
            repaired = recover_unmatched_event(event=existing)
            if repaired:
                _, created = repaired
                return JsonResponse(
                    {'accepted': True, 'disposition': 'created' if created else 'duplicate'},
                    status=202 if created else 200,
                )
            return JsonResponse({'accepted': True, 'disposition': 'duplicate'}, status=200)

        listing = find_unique_mart_listing(payload['code'])
        try:
            event = PaGmailOrderEvent.objects.create(
                event_id=payload['eventId'],
                source=payload['source'],
                external_order_id=payload['orderId'],
                tracking_code=payload['code'],
                market=payload['market'] or '',
                automatic_delivery=payload['automaticDelivery'],
                observed_at_ms=payload['observedAt'],
                disposition=PaGmailOrderEvent.Disposition.UNMATCHED,
                integration_account=listing.integration_account if listing else None,
                listing=listing,
            )
        except IntegrityError:
            return JsonResponse({'accepted': True, 'disposition': 'duplicate'}, status=200)

        if listing is None:
            return JsonResponse({'accepted': True, 'disposition': 'unmatched'}, status=202)

        order, created = create_order_report(event=event, listing=listing)
        event.order = order
        event.disposition = PaGmailOrderEvent.Disposition.CREATED if created else PaGmailOrderEvent.Disposition.DUPLICATE
        event.save(update_fields=['order', 'disposition', 'updated_at'])
        return JsonResponse(
            {'accepted': True, 'disposition': 'created' if created else 'duplicate'},
            status=202 if created else 200,
        )
