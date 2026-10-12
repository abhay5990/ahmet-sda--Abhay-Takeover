"""Authenticated, idempotent U7Buy seller webhook intake.

The callback only verifies and queues an event.  It never accepts credentials,
never creates a listing, and never treats webhook fields as an authoritative
sale; the scheduler later reads the matching order from U7Buy before applying
SDA's normal order and pool safeguards.
"""

from __future__ import annotations

import hashlib
import json
import logging

from django.http import HttpRequest, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from apps.integrations.models import IntegrationAccount
from apps.integrations.providers.u7buy import webhook_signature_is_valid
from apps.sync.models import U7BuyWebhookEvent

logger = logging.getLogger(__name__)
SUPPORTED_EVENTS = {
    "new_order_received",
    "order_completed",
    "stock_reaches_threshold",
    "stock_runs_out",
}


@csrf_exempt
@require_POST
def u7buy_webhook(request: HttpRequest, account_slug: str) -> HttpResponse:
    """Verify one U7Buy callback and persist minimal idempotency state."""
    account = get_object_or_404(
        IntegrationAccount.objects.select_related("credential"),
        slug=account_slug,
        provider="u7buy",
        is_active=True,
        credential__is_active=True,
    )
    credentials = account.credential.credentials or {}
    app_id = str(credentials.get("app_id") or "")
    app_secret = str(credentials.get("webhook_secret") or credentials.get("app_secret") or "")
    signature = request.META.get("HTTP_X_U7BUY_SIGNATURE", "")
    if not webhook_signature_is_valid(
        raw_body=request.body,
        supplied_signature=signature,
        app_id=app_id,
        app_secret=app_secret,
    ):
        logger.warning("U7Buy webhook rejected: invalid signature for account=%s", account.pk)
        return JsonResponse({"error": "invalid signature"}, status=401)

    try:
        payload = json.loads(request.body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return JsonResponse({"error": "invalid JSON"}, status=400)
    if not isinstance(payload, dict):
        return JsonResponse({"error": "invalid event payload"}, status=400)

    topic = str(payload.get("event") or "").strip().lower()
    if topic not in SUPPORTED_EVENTS:
        return HttpResponse(status=204)
    event_data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
    external_order_id = str(event_data.get("orderId") or "").strip()
    if topic in {"new_order_received", "order_completed"} and not external_order_id:
        return JsonResponse({"error": "missing orderId"}, status=400)

    event_hash = hashlib.sha256(
        str(account.pk).encode("ascii") + b":" + request.body,
    ).hexdigest()
    event, created = U7BuyWebhookEvent.objects.get_or_create(
        event_hash=event_hash,
        defaults={
            "integration_account": account,
            "topic": topic,
            "external_order_id": external_order_id,
            "status": U7BuyWebhookEvent.Status.PENDING,
        },
    )
    if not created and event.integration_account_id != account.id:
        logger.error("U7Buy webhook hash collision across accounts")
        return JsonResponse({"error": "event conflict"}, status=409)

    return JsonResponse({"status": "OK"})
