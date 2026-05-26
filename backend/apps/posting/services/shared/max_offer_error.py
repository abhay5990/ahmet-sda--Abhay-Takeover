"""Detect Eldorado 'Maximum of N active offers is allowed' error."""

from __future__ import annotations

from typing import Any


def is_max_offer_error(api_result: Any) -> bool:
    """Return True if api_result is an Eldorado max-offer-limit error.

    Expected error response:
        {"code": 400, "messages": ["Maximum of 300 active offers is allowed."]}

    The SDK places this in api_result.error.details as a dict.
    """
    if api_result.ok:
        return False
    err = api_result.error
    if err is None:
        return False
    details = getattr(err, 'details', None)
    if isinstance(details, dict):
        messages = details.get('messages', [])
        if isinstance(messages, list):
            return any(
                'active offers is allowed' in str(m).lower()
                for m in messages
            )
    return False
