"""
Token Broker API — endpoint + auth decorator + IP helpers.

Provides a secure API for external apps to request marketplace tokens
without needing direct access to credentials or Cognito.
"""

from __future__ import annotations

import hashlib
import ipaddress
import logging
from functools import wraps

from django.conf import settings
from django.http import JsonResponse
from django.views.decorators.http import require_GET

from apis_sdk.core.exceptions import AuthenticationError

from apps.integrations.models import TokenApiClient
from apps.integrations.services.token_broker import (
    TokenBrokerService,
    StoreNotFound,
    UnsupportedMarketplace,
    CognitoThrottled,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# IP helpers
# ---------------------------------------------------------------------------

_TRUSTED_PROXIES: list[ipaddress.IPv4Network | ipaddress.IPv6Network] | None = None


def _get_trusted_proxies():
    global _TRUSTED_PROXIES
    if _TRUSTED_PROXIES is None:
        raw = getattr(settings, 'TRUSTED_PROXY_IPS', [])
        _TRUSTED_PROXIES = [ipaddress.ip_network(p, strict=False) for p in raw]
    return _TRUSTED_PROXIES


def _is_trusted(ip: str) -> bool:
    proxies = _get_trusted_proxies()
    if not proxies:
        return False
    try:
        addr = ipaddress.ip_address(ip)
        return any(addr in net for net in proxies)
    except ValueError:
        return False


def get_client_ip(request) -> str:
    """Extract real client IP, respecting trusted proxies only."""
    remote = request.META.get('REMOTE_ADDR', '')
    if _get_trusted_proxies() and _is_trusted(remote):
        xff = request.META.get('HTTP_X_FORWARDED_FOR', '')
        if xff:
            return xff.split(',')[0].strip()
    return remote


def check_ip_allowed(client_ip: str, client: TokenApiClient) -> bool:
    """Check if client_ip is allowed for this API client."""
    if client.allow_any_ip:
        return True
    if not client.allowed_ips:
        return False  # empty list = no IP accepted (secure default)
    try:
        addr = ipaddress.ip_address(client_ip)
        return any(
            addr in ipaddress.ip_network(entry, strict=False)
            for entry in client.allowed_ips
        )
    except ValueError:
        return False


# ---------------------------------------------------------------------------
# Auth decorator
# ---------------------------------------------------------------------------

def token_api_auth_required(view_func):
    """Authenticate requests via API key (Bearer token) + IP whitelist."""

    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        # 1. Extract API key from Authorization header
        auth_header = request.META.get('HTTP_AUTHORIZATION', '')
        if not auth_header.startswith('Bearer '):
            return JsonResponse({'error': 'Missing or invalid Authorization header'}, status=401)

        api_key = auth_header[7:]  # strip "Bearer "
        if not api_key:
            return JsonResponse({'error': 'Empty API key'}, status=401)

        # 2. Hash and lookup
        key_hash = hashlib.sha256(api_key.encode()).hexdigest()
        try:
            client = TokenApiClient.objects.get(api_key_hash=key_hash, is_active=True)
        except TokenApiClient.DoesNotExist:
            logger.warning("Token broker: invalid API key (prefix: %s...)", api_key[:8])
            return JsonResponse({'error': 'Invalid API key'}, status=401)

        # 3. IP check
        client_ip = get_client_ip(request)
        if not check_ip_allowed(client_ip, client):
            logger.warning(
                "Token broker: IP %s not allowed for client '%s'",
                client_ip, client.name,
            )
            return JsonResponse({'error': 'IP not allowed'}, status=403)

        request.token_api_client = client
        return view_func(request, *args, **kwargs)

    return wrapper


# ---------------------------------------------------------------------------
# Endpoint
# ---------------------------------------------------------------------------

@require_GET
@token_api_auth_required
def token_view(request):
    """
    GET /integrations/api/token/?marketplace=eldorado&store=eldorado-store4gamers

    Returns a valid marketplace token. Refreshes from Cognito only when expired.
    """
    marketplace = request.GET.get('marketplace', '').strip()
    store = request.GET.get('store', '').strip()

    if not marketplace or not store:
        return JsonResponse(
            {'error': 'Both "marketplace" and "store" query parameters are required'},
            status=400,
        )

    service = TokenBrokerService()
    try:
        result = service.get_token(marketplace, store)
    except UnsupportedMarketplace as e:
        return JsonResponse({'error': str(e)}, status=400)
    except StoreNotFound as e:
        return JsonResponse({'error': str(e)}, status=404)
    except CognitoThrottled as e:
        logger.warning("Token broker: cooldown active for %s/%s — %s", marketplace, store, e)
        return JsonResponse(
            {'error': str(e), 'retry_after': e.remaining_seconds},
            status=429,
        )
    except AuthenticationError as e:
        logger.error("Token broker: refresh failed for %s/%s — %s", marketplace, store, e)
        return JsonResponse({'error': f'Token refresh failed: {e}'}, status=502)

    response = JsonResponse(result)
    response['Cache-Control'] = 'no-store'
    return response
