"""Subplatform selection — pick the least-occupied sub-platform."""

from __future__ import annotations

from django.db.models import Count

from apps.listings.enums import ListingStatus
from apps.listings.models import Listing
from apps.posting.models import SubplatformLimit

# ---------------------------------------------------------------------------
# Subplatform registry — which games support which sub-platforms
# Keys are Game.slug values (must match payload_pipeline GameSlug enum).
# ---------------------------------------------------------------------------

GAME_SUBPLATFORMS: dict[str, list[str]] = {
    'valorant': ['PC', 'PlayStation', 'Xbox'],
    'fortnite': ['PC', 'PlayStation', 'Xbox', 'Android', 'iOS', 'Switch'],
    'rainbow-six-siege': ['PC', 'PlayStation', 'Xbox'],
}


def get_subplatforms(game_slug: str) -> list[str]:
    """Return the list of sub-platforms for a game, or empty list if none."""
    return GAME_SUBPLATFORMS.get(game_slug, [])


def has_subplatforms(game_slug: str) -> bool:
    """Return True if the game supports sub-platform selection."""
    return game_slug in GAME_SUBPLATFORMS


def resolve_subplatform(
    store, game, *, mode: str = 'stock', fallback: str = '',
) -> str | None:
    """High-level helper: query limits + counts, return best sub-platform.

    Returns:
        Sub-platform name, empty string if no limits configured (use fallback),
        or None if all slots are full.
    """
    limits = SubplatformLimit.objects.filter(store=store, game=game)
    if not limits.exists():
        return fallback
    counts = get_active_offer_counts(store, game)
    return select_best_subplatform(limits, counts, mode=mode)


def get_active_offer_counts(store, game) -> dict[str, int]:
    """Return {sub_platform: count} for active listings on a store+game."""
    return dict(
        Listing.objects.filter(
            integration_account=store,
            game=game,
            status=ListingStatus.LISTED,
        )
        .values('sub_platform')
        .annotate(count=Count('id'))
        .values_list('sub_platform', 'count')
    )


def get_allowed_platforms(game_slug: str, subject) -> set[str] | None:
    """Return sub-platforms this account is eligible for, or None if no filtering.

    None means the game has no per-account compatibility constraints.
    """
    if game_slug == 'fortnite':
        allowed = {'PC', 'Android', 'iOS', 'Switch'}
        if getattr(subject, 'psn_linkable', False):
            allowed.add('PlayStation')
        if getattr(subject, 'xbox_linkable', False):
            allowed.add('Xbox')
        return allowed
    if game_slug == 'rainbow-six-siege':
        allowed: set[str] = {'PC'}
        if not getattr(subject, 'psn_connected', True):
            allowed.add('PlayStation')
        if not getattr(subject, 'xbox_connected', True):
            allowed.add('Xbox')
        return allowed
    return None


def select_best_subplatform(
    limits,
    counts: dict[str, int],
    mode: str = 'stock',
    allowed_platforms: set[str] | None = None,
) -> str | None:
    """Select the sub-platform with the most available slots.

    Args:
        limits: QuerySet of SubplatformLimit objects.
        counts: Current active offer counts per sub-platform.
        mode: 'stock' or 'dropship'. Dropship mode subtracts stock_reserve.
        allowed_platforms: If given, only consider sub-platforms in this set.

    Returns:
        Sub-platform name, or None if no slots available.
    """
    best = None
    best_available = -1

    for limit in limits:
        if allowed_platforms is not None and limit.sub_platform not in allowed_platforms:
            continue
        current = counts.get(limit.sub_platform, 0)
        effective_max = limit.max_offers
        if mode == 'dropship':
            effective_max -= limit.stock_reserve

        available = effective_max - current
        if available > 0 and available > best_available:
            best = limit.sub_platform
            best_available = available

    return best


# ---------------------------------------------------------------------------
# Cycle-level cache for poster loop (avoids per-item DB queries)
# ---------------------------------------------------------------------------

class SubplatformCache:
    """Caches limits + counts for a (store, game) pair within a poster cycle.

    Usage:
        cache = SubplatformCache(store, game, mode='dropship')
        sub = cache.resolve(fallback='')   # first call hits DB
        sub = cache.resolve(fallback='')   # subsequent calls use cache
        cache.record_post(sub)             # increment in-memory counter after successful post
    """

    def __init__(self, store, game, *, mode: str = 'stock') -> None:
        self._store = store
        self._game = game
        self._mode = mode
        self._limits = list(SubplatformLimit.objects.filter(store=store, game=game))
        self._counts: dict[str, int] = (
            get_active_offer_counts(store, game) if self._limits else {}
        )

    def resolve(
        self,
        fallback: str = '',
        allowed_platforms: set[str] | None = None,
    ) -> str | None:
        """Return best sub-platform using cached data.

        Args:
            fallback: Returned when no limits are configured.
            allowed_platforms: If given, only consider sub-platforms in this set.
        """
        if not self._limits:
            return fallback
        return select_best_subplatform(
            self._limits, self._counts, mode=self._mode,
            allowed_platforms=allowed_platforms,
        )

    def record_post(self, sub_platform: str) -> None:
        """Increment in-memory count after a successful post."""
        self._counts[sub_platform] = self._counts.get(sub_platform, 0) + 1
