"""Variant routing — capacity-aware variant selection for stock + dropship.

Replaces the legacy SubplatformCache / select_best_subplatform helpers.
Works entirely from the variant_context dict built by build_variant_context()
so there are zero per-item DB queries once the router is initialised.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

# Default limits when no GameVariantLimit exists for a variant.
DEFAULT_MAX_OFFERS = 300
DEFAULT_MAX_OFFERS_REGION = 200
DEFAULT_STOCK_RESERVE = 300
DEFAULT_STOCK_RESERVE_REGION = 200

# Priority tiers per game — tier 0 is checked first, then 1, then 2.
# Fortnite / R6: console slots are scarce, fill them first.
# Valorant: PC is the primary slot (K7 decision — PC > PSN > Xbox).
PLATFORM_PRIORITY: dict[str, list[set[str]]] = {
    'fortnite': [
        {'psn', 'xbox'},                   # Tier 0: console (scarce)
        {'pc'},                            # Tier 1: PC
        {'ios', 'android', 'switch'},      # Tier 2: mobile/switch
    ],
    'valorant': [
        {'pc'},                            # Tier 0: PC (primary)
        {'psn', 'xbox'},                   # Tier 1: console
    ],
    'rainbow-six-siege': [
        {'psn', 'xbox'},                   # Tier 0: console (scarce)
        {'pc'},                            # Tier 1: PC
    ],
}


def get_eligible_variants(game_slug: str, subject: Any) -> set[str] | None:
    """Return variant slugs this account is eligible for, or None (= all).

    None means the game has no per-account compatibility constraints
    (e.g. GTA V — platform comes from the account, not from selection).
    """
    if game_slug == 'fortnite':
        allowed = {'pc', 'android', 'ios', 'switch'}
        if getattr(subject, 'psn_linkable', False):
            allowed.add('psn')
        if getattr(subject, 'xbox_linkable', False):
            allowed.add('xbox')
        return allowed

    if game_slug == 'rainbow-six-siege':
        # R6 source reports "connected" (already linked) — opposite of FN's "linkable".
        # If NOT connected → slot is free → account can be sold on that platform.
        allowed: set[str] = {'pc'}
        if not getattr(subject, 'psn_connected', True):
            allowed.add('psn')
        if not getattr(subject, 'xbox_connected', True):
            allowed.add('xbox')
        return allowed

    # Valorant: all accounts eligible for all platforms
    # LoL/Genshin/GTA: fixed variants (no selection)
    return None


class VariantRouter:
    """Cycle-level variant selection + in-memory counter.

    Replaces SubplatformCache. Operates on the variant_context dict so there
    are no per-item DB queries after initialisation.

    Usage::

        ctx = build_variant_context(store=store, game=game, marketplace=mp)
        router = VariantRouter(ctx, mode='stock')

        slug = router.select('platform', allowed={'pc', 'psn'}, game_slug='fortnite')
        if slug is None:
            skip("all slots full")

        # after successful post:
        router.record_post('platform', slug)
    """

    def __init__(self, variant_ctx: dict | None, *, mode: str = 'stock') -> None:
        self._ctx = variant_ctx or {}
        self._mode = mode
        # In-memory post counter: {variant_type: {slug: count}}
        self._posted: dict[str, dict[str, int]] = {}

    def select(
        self,
        variant_type: str,
        *,
        allowed: set[str] | None = None,
        game_slug: str = '',
        manual: str = '',
    ) -> str | None:
        """Select the best variant slug given capacity and eligibility.

        Args:
            variant_type: 'platform' or 'region'.
            allowed: Eligible slugs for this account (None = all).
            game_slug: Used to look up priority tiers.
            manual: Manually chosen slug (overrides auto if it has capacity).

        Returns:
            Variant slug, empty string if no limits configured, or None if
            all slots are full.
        """
        type_ctx = self._ctx.get(variant_type)
        if not type_ctx:
            return ''  # game has no variants of this type

        # Check if any entry has limit info — if none do, no capacity management
        has_limits = any('limit' in entry for entry in type_ctx.values())
        if not has_limits:
            # No limits configured: return manual or empty (let caller use account default)
            if manual:
                return manual
            return ''

        # Manual override: use it if it has capacity
        if manual and manual.lower() != 'auto':
            avail = self._available(variant_type, manual)
            if avail is not None and avail > 0:
                return manual
            # Manual slug is full — fall through to auto selection

        # Auto selection with priority tiers
        tiers = PLATFORM_PRIORITY.get(game_slug)
        if tiers:
            return self._select_tiered(variant_type, allowed=allowed, tiers=tiers)
        return self._select_best(variant_type, allowed=allowed)

    def select_fixed(self, variant_type: str, source_key: str) -> str:
        """Return the slug for a fixed (non-selectable) variant.

        Used for games like GTA V / LoL / Genshin where the variant is
        determined by the account data, not by capacity.

        Returns the slug from variant_context, or the source_key itself
        if not found (passthrough).
        """
        type_ctx = self._ctx.get(variant_type, {})

        # 1. Exact match on source_key
        entry = type_ctx.get(source_key)
        if entry is not None:
            return entry.get('slug', source_key)

        # 2. Case-insensitive fallback (key or slug)
        key_lower = source_key.lower()
        for k, v in type_ctx.items():
            if k.lower() == key_lower:
                return v.get('slug', source_key)
            if str(v.get('slug') or '').lower() == key_lower:
                return v.get('slug', source_key)

        return source_key

    def record_post(self, variant_type: str, slug: str) -> None:
        """Increment in-memory counter after a successful post."""
        if variant_type not in self._posted:
            self._posted[variant_type] = {}
        self._posted[variant_type][slug] = (
            self._posted[variant_type].get(slug, 0) + 1
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _available(self, variant_type: str, slug: str) -> int | None:
        """Return available slots for a slug, or None if slug not found."""
        type_ctx = self._ctx.get(variant_type, {})
        # Find entry by slug (entries are keyed by source_key or slug)
        entry = None
        for v in type_ctx.values():
            if v.get('slug') == slug:
                entry = v
                break
        if entry is None:
            return None

        limit = entry.get('limit', DEFAULT_MAX_OFFERS)
        active = entry.get('active', 0)
        posted = self._posted.get(variant_type, {}).get(slug, 0)

        if self._mode == 'dropship':
            reserve = entry.get('stock_reserve', DEFAULT_STOCK_RESERVE)
            effective_max = limit - reserve
        else:
            effective_max = limit

        return effective_max - active - posted

    def _select_best(
        self,
        variant_type: str,
        allowed: set[str] | None = None,
    ) -> str | None:
        """Pick the slug with the most available slots."""
        type_ctx = self._ctx.get(variant_type, {})
        best_slug: str | None = None
        best_avail = -1

        for entry in type_ctx.values():
            slug = entry.get('slug', '')
            if allowed is not None and slug not in allowed:
                continue
            avail = self._available(variant_type, slug)
            if avail is not None and avail > 0 and avail > best_avail:
                best_slug = slug
                best_avail = avail

        return best_slug

    def _select_tiered(
        self,
        variant_type: str,
        *,
        allowed: set[str] | None = None,
        tiers: list[set[str]],
    ) -> str | None:
        """Try each priority tier in order; return first slug with capacity."""
        for tier in tiers:
            tier_filter = tier & allowed if allowed is not None else tier
            if not tier_filter:
                continue
            result = self._select_best(variant_type, allowed=tier_filter)
            if result:
                return result
        return None
