"""Variant context lookup helpers.

Pure-Python utilities for reading marketplace external IDs and display names
from the ``variant_context`` dict injected into :class:`BuildContext`.

Variant context shape (built by Django ``build_variant_context``)::

    {
        "platform": {
            "pc":  {"slug": "pc",  "external_id": "0", "external_name": "PC", ...},
            "psn": {"slug": "psn", "external_id": "1", "external_name": "PlayStation", ...},
        },
        "region": {
            "North America": {"slug": "na", "external_id": "9", ...},
        },
    }

Dict keys are ``source_key`` (if set) or ``slug`` — callers pass the raw
account field value (e.g. ``account.region_phrase``) and these helpers do
a case-insensitive fallback when an exact match is not found.
"""

from __future__ import annotations

from typing import Any


def _lookup(
    variant_ctx: dict[str, Any] | None,
    variant_type: str,
    key: str | None,
) -> dict[str, Any] | None:
    """Find the variant entry matching *key* inside *variant_ctx[variant_type]*.

    Lookup order:
    1. Exact match on *key*.
    2. Case-insensitive fallback (``key.lower()`` vs each dict key lowered).
    3. ``None`` — no match.
    """
    if not variant_ctx or not key:
        return None

    type_map = variant_ctx.get(variant_type)
    if not type_map:
        return None

    # 1. Exact match
    entry = type_map.get(key)
    if entry is not None:
        return entry

    # 2. Case-insensitive fallback
    key_lower = key.lower()
    for k, v in type_map.items():
        if k.lower() == key_lower:
            return v

    return None


def get_external_id(
    variant_ctx: dict[str, Any] | None,
    variant_type: str,
    key: str | None,
) -> str | None:
    """Return the marketplace ``external_id`` for a variant lookup.

    Returns ``None`` when *variant_ctx* is missing, *key* is empty, or
    no matching entry exists — the caller must supply its own fallback.
    """
    entry = _lookup(variant_ctx, variant_type, key)
    if entry is None:
        return None
    return entry.get("external_id")


def get_external_name(
    variant_ctx: dict[str, Any] | None,
    variant_type: str,
    key: str | None,
) -> str | None:
    """Return the marketplace ``external_name`` for a variant lookup.

    Returns ``None`` when no matching entry exists.
    """
    entry = _lookup(variant_ctx, variant_type, key)
    if entry is None:
        return None
    return entry.get("external_name")
