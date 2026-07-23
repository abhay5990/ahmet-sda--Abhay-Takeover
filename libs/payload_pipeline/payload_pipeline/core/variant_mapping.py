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


def _normalise_lookup_key(value: str | None) -> str:
    """Return a punctuation-insensitive identity for source platform aliases.

    Marketplace records can use human labels such as ``PC - Enhanced`` while
    source feeds use canonical slugs such as ``pc-enhanced``. Exact and
    case-insensitive matching remain preferred; this is a final compatibility
    fallback for the same platform identity.
    """
    return ''.join(char for char in str(value or '').lower() if char.isalnum())


def _lookup(
    variant_ctx: dict[str, Any] | None,
    variant_type: str,
    key: str | None,
) -> dict[str, Any] | None:
    """Find the variant entry matching *key* inside *variant_ctx[variant_type]*.

    Lookup order:
    1. Exact match on *key*.
    2. Case-insensitive fallback (``key.lower()`` vs each dict key lowered).
    3. Case-insensitive match on each entry's identity fields (``slug``,
       ``source_key``). The dict key may be the display label/``source_key``
       while callers pass the internal ``slug`` (or vice versa); without this
       the lookup misses and the caller falls back to the raw internal value,
       which marketplaces reject (e.g. sending ``pc-enhanced`` to GameBoost
       instead of the configured ``PC · Enhanced``).
    4. ``None`` — no match.
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

    # 2. Case-insensitive fallback on the dict key
    key_lower = key.lower()
    for k, v in type_map.items():
        if k.lower() == key_lower:
            return v

    # 3. Case-insensitive match on each entry's identity fields
    for v in type_map.values():
        if not isinstance(v, dict):
            continue
        for field in ('slug', 'source_key'):
            val = v.get(field)
            if val and str(val).lower() == key_lower:
                return v

    # 4. Punctuation-insensitive identity. This reconciles a source slug such
    # as ``pc-enhanced`` with the configured human label ``PC - Enhanced``.
    normalized_key = _normalise_lookup_key(key)
    if normalized_key:
        for source_key, entry in type_map.items():
            if _normalise_lookup_key(source_key) == normalized_key:
                return entry
            if not isinstance(entry, dict):
                continue
            for field in ('slug', 'source_key'):
                if _normalise_lookup_key(entry.get(field)) == normalized_key:
                    return entry

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
