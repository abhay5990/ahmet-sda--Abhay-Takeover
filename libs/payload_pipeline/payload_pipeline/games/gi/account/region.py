"""Canonical region normalization for miHoYo (Genshin/Honkai/Zenless) accounts.

Sources deliver the account region in inconsistent forms:
  * LZT ``mihoyo_region`` sends short codes — observed values: ``usa``, ``eu``,
    ``asia``, ``cht``.
  * Manual entry may send full names (``America``/``Europe``/...) or anything.

Marketplace builders resolve the region against ``variant_context['region']``,
whose keys are the ``GameVariant.source_key`` values seeded in the DB
(``America`` / ``Europe`` / ``Asia`` / ``TW,HK,MO``).  A raw code like ``eu`` or
``usa`` does not match those keys (``eu`` != ``Europe``), so the lookup returns
None and the builder falls back to an invalid trade environment — Eldorado then
rejects the offer with "Game and Trade Environment ... combination is invalid".

This module maps every known raw form to the canonical ``source_key`` so the
lookup resolves correctly for all miHoYo marketplace builders.
"""

from __future__ import annotations

# canonical source_key (matches GameVariant.source_key) -> known raw aliases.
# Aliases are matched case-insensitively.
_REGION_ALIASES: dict[str, tuple[str, ...]] = {
    "America": ("america", "north america", "na", "usa", "us", "am"),
    "Europe": ("europe", "eu", "eur"),
    "Asia": ("asia", "as", "asian"),
    "TW,HK,MO": ("tw,hk,mo", "tw, hk, mo", "twhkmo", "cht", "tw", "hk", "mo", "taiwan"),
}

_LOOKUP: dict[str, str] = {
    alias: canonical
    for canonical, aliases in _REGION_ALIASES.items()
    for alias in aliases
}


def normalize_region_key(raw: str | None) -> str:
    """Return the canonical region key for *raw*.

    Falls back to the trimmed input when *raw* is not a recognised alias, so
    values that already equal a canonical key (e.g. ``Europe``) still resolve.
    """
    if not raw:
        return ""
    return _LOOKUP.get(raw.strip().lower(), raw.strip())
