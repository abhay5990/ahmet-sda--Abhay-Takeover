"""Shared helpers for the tools app — JSON parsing, auth decorators, lookup tokens."""
from __future__ import annotations

import json
import logging
from functools import wraps

from django.core import signing
from django.http import JsonResponse

logger = logging.getLogger(__name__)

# ── JSON parsing ──────────────────────────────────────────────────

def parse_json_body(request) -> tuple[dict | None, JsonResponse | None]:
    """Parse request body as JSON dict.

    Returns (body_dict, None) on success or (None, error_response) on failure.
    """
    if not request.body:
        return None, JsonResponse({'error': 'Request body is empty'}, status=400)
    try:
        body = json.loads(request.body)
    except (json.JSONDecodeError, ValueError):
        return None, JsonResponse({'error': 'Invalid JSON'}, status=400)
    if not isinstance(body, dict):
        return None, JsonResponse({'error': 'Request body must be a JSON object'}, status=400)
    return body, None


# ── Auth / role decorator for JSON APIs ───────────────────────────

def api_role_required(*allowed_roles):
    """Combined authentication + role check for JSON API endpoints.

    Unlike ``@login_required`` (which redirects to login page) and
    ``@role_required`` (which returns HTML 403), this returns proper JSON
    error responses suitable for AJAX callers.
    """
    def decorator(view_func):
        @wraps(view_func)
        def _wrapped(request, *args, **kwargs):
            if not request.user.is_authenticated:
                return JsonResponse({'error': 'Authentication required'}, status=401)
            if request.user.is_superuser:
                return view_func(request, *args, **kwargs)
            if allowed_roles and request.user.role not in allowed_roles:
                return JsonResponse({'error': 'Permission denied'}, status=403)
            return view_func(request, *args, **kwargs)
        return _wrapped
    return decorator


# ── Signed lookup token ──────────────────────────────────────────

_LOOKUP_SALT = 'robuxcrate-lookup-v1'
LOOKUP_TOKEN_MAX_AGE = 1800  # 30 minutes


def create_lookup_token(roblox_user_id: int, username: str, place_ids: list[int]) -> str:
    """Create a signed token containing Roblox lookup results."""
    return signing.dumps(
        {'uid': roblox_user_id, 'un': username, 'pids': place_ids},
        salt=_LOOKUP_SALT,
    )


def verify_lookup_token(token: str) -> dict | None:
    """Verify and decode a lookup token.

    Returns the payload dict on success, None on any failure
    (bad signature, expired, tampered).
    """
    try:
        return signing.loads(token, salt=_LOOKUP_SALT, max_age=LOOKUP_TOKEN_MAX_AGE)
    except (signing.BadSignature, signing.SignatureExpired):
        return None
