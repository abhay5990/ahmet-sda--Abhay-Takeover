"""Credential entry formatting helpers.

These functions are intentionally pure: callers fetch marketplace data,
this module only normalizes the shape stored in ``Listing.raw_data``.
"""

from __future__ import annotations

from typing import Any


def collect_credential_entries(source: list[Any]) -> list[dict[str, Any]]:
    """Convert credential entry models or dicts to plain dictionaries."""
    entries: list[dict[str, Any]] = []
    for entry in source:
        if hasattr(entry, "model_dump"):
            entries.append(entry.model_dump())
        elif isinstance(entry, dict):
            entries.append(entry)
        else:
            entries.append(dict(entry))
    return entries


def build_eldorado_credential_entries(
    account_secret_details: list[str] | str,
) -> list[dict[str, str]]:
    """Build Eldorado sync-style credential entries from create payload secrets."""
    if isinstance(account_secret_details, str):
        account_secret_details = [account_secret_details]
    return [
        {"id": "", "secretDetails": secret}
        for secret in account_secret_details
        if secret
    ]


def build_gameboost_credential_entries(
    credentials: list[str],
    account_offer_id: int | str = 0,
) -> list[dict[str, Any]]:
    """Build Gameboost sync-style credential entries from create payload credentials."""
    offer_id = _to_int(account_offer_id)
    return [
        {
            "id": 0,
            "credentials": credential,
            "account_offer_id": offer_id,
            "account_order_id": None,
            "is_sold": False,
        }
        for credential in credentials
        if credential
    ]


def _to_int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0

