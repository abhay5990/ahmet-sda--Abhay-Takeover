"""Shared tracker data fetcher — resolves tracker source for supported games.

Given a game_slug and LZT raw_data, extracts the tracker identifier,
calls the appropriate tracker API, and returns the raw tracker response
dict suitable for use as sources['tracker'] in the payload pipeline.

Supported games:
  - rainbow-six-siege  → R6Locker  (CurlCffi, Cloudflare-protected)
  - clash-royale       → StatsRoyale (Requests, no Cloudflare)
  - clash-of-clans     → ClashOfStats (CurlCffi, Cloudflare-protected)

Usage (both stock and dropship):
    tracker_data = fetch_tracker_data(game.slug, raw_data, proxy_group=proxy_group)
    sources = {'lzt': raw_data}
    if tracker_data is not None:
        sources['tracker'] = tracker_data
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

# Lazy module-level facade singletons — built on first use, reused across calls.
_r6locker_facade = None
_statsroyale_facade = None
_clashofstats_facade = None

_TRACKER_GAMES = frozenset({"rainbow-six-siege", "clash-royale", "clash-of-clans"})


def fetch_tracker_data(
    game_slug: str,
    raw_data: dict[str, Any],
    *,
    proxy_group: str | None = None,
) -> dict[str, Any] | None:
    """Fetch tracker data for supported games.

    Returns the raw tracker response dict on success, or None if:
    - Game does not support tracker
    - No tracker identifier found in raw_data
    - Tracker API call fails (error is logged, not raised)

    Args:
        game_slug:   Canonical game slug (e.g. 'rainbow-six-siege').
        raw_data:    LZT raw_data dict from OwnedProduct or dropship item.
        proxy_group: Optional proxy group name for the tracker request.
    """
    if game_slug not in _TRACKER_GAMES:
        return None

    if game_slug == "rainbow-six-siege":
        return _fetch_r6(raw_data, proxy_group=proxy_group)
    if game_slug == "clash-royale":
        return _fetch_cr(raw_data, proxy_group=proxy_group)
    if game_slug == "clash-of-clans":
        return _fetch_coc(raw_data, proxy_group=proxy_group)

    return None


# ---------------------------------------------------------------------------
# Per-game fetch helpers
# ---------------------------------------------------------------------------

def _fetch_r6(
    raw_data: dict[str, Any],
    *,
    proxy_group: str | None,
) -> dict[str, Any] | None:
    account_id = _extract_r6_account_id(raw_data)
    if not account_id:
        logger.debug("R6 tracker: no tracker_link in raw_data, skipping")
        return None

    facade = _get_r6locker_facade()
    if facade is None:
        return None

    try:
        result = facade.get_account_data(account_id, proxy_group=proxy_group)
    except Exception:
        logger.warning("R6Locker API call raised unexpectedly for %s", account_id, exc_info=True)
        return None

    if not result.ok:
        logger.debug(
            "R6Locker returned error for %s: %s",
            account_id,
            result.error.message if result.error else "unknown",
        )
        return None

    return result.data


def _fetch_cr(
    raw_data: dict[str, Any],
    *,
    proxy_group: str | None,
) -> dict[str, Any] | None:
    player_tag = _extract_supercell_tag(raw_data, tag_key="scroll")
    if not player_tag:
        logger.debug("CR tracker: no player_tag (scroll) in raw_data, skipping")
        return None

    facade = _get_statsroyale_facade()
    if facade is None:
        return None

    try:
        result = facade.get_profile(player_tag, proxy_group=proxy_group)
    except Exception:
        logger.warning("StatsRoyale API call raised unexpectedly for %s", player_tag, exc_info=True)
        return None

    if not result.ok:
        logger.debug(
            "StatsRoyale returned error for %s: %s",
            player_tag,
            result.error.message if result.error else "unknown",
        )
        return None

    return result.data


def _fetch_coc(
    raw_data: dict[str, Any],
    *,
    proxy_group: str | None,
) -> dict[str, Any] | None:
    player_tag = _extract_supercell_tag(raw_data, tag_key="magic")
    if not player_tag:
        logger.debug("CoC tracker: no player_tag (magic) in raw_data, skipping")
        return None

    facade = _get_clashofstats_facade()
    if facade is None:
        return None

    try:
        result = facade.get_player_data(player_tag, proxy_group=proxy_group)
    except Exception:
        logger.warning("ClashOfStats API call raised unexpectedly for %s", player_tag, exc_info=True)
        return None

    if not result.ok:
        logger.debug(
            "ClashOfStats returned error for %s: %s",
            player_tag,
            result.error.message if result.error else "unknown",
        )
        return None

    return result.data


# ---------------------------------------------------------------------------
# Identifier extractors
# ---------------------------------------------------------------------------

def _extract_r6_account_id(raw_data: dict[str, Any]) -> str:
    """Extract R6Locker account_id (Ubisoft UUID).

    Priority:
    1. uplay_id field — direct UUID, no parsing needed
    2. tracker_link field — 'r6skins.locker/profile/<uuid>', last path segment

    Returns the UUID string, or '' if not found in either field.
    """
    payload = raw_data.get("item") if isinstance(raw_data.get("item"), dict) else raw_data

    uplay_id = str(payload.get("uplay_id") or "").strip()
    if uplay_id:
        return uplay_id

    tracker_link = str(payload.get("tracker_link") or "").strip()
    if tracker_link:
        return tracker_link.rstrip("/").rsplit("/", 1)[-1]

    return ""


def _extract_supercell_tag(raw_data: dict[str, Any], *, tag_key: str) -> str:
    """Extract Supercell player tag from systems dict in LZT raw_data.

    LZT stores CR tag under 'scroll', CoC tag under 'magic'.
    Returns '' if not found.
    """
    payload = raw_data.get("item") if isinstance(raw_data.get("item"), dict) else raw_data
    systems = payload.get("supercell_systems") or payload.get("systems") or {}
    if isinstance(systems, dict):
        tag = str(systems.get(tag_key) or "").strip()
        if tag:
            return tag
    return ""


# ---------------------------------------------------------------------------
# Lazy facade builders
# ---------------------------------------------------------------------------

def _get_r6locker_facade():
    global _r6locker_facade
    if _r6locker_facade is not None:
        return _r6locker_facade
    try:
        from apis_sdk.clients.trackers.r6locker.facade import R6LockerFacade  # noqa: F401
        from apis_sdk.factories.r6locker_factory import R6LockerFactory
        from apis_sdk.infrastructure.http.curl_cffi_transport import CurlCffiTransport

        transport = CurlCffiTransport()
        _r6locker_facade = R6LockerFactory.create(transport=transport)
        logger.debug("R6LockerFacade initialised")
    except Exception:
        logger.warning("Could not build R6LockerFacade", exc_info=True)
        return None
    return _r6locker_facade


def _get_statsroyale_facade():
    global _statsroyale_facade
    if _statsroyale_facade is not None:
        return _statsroyale_facade
    try:
        from apis_sdk.factories.statsroyale_factory import StatsRoyaleFactory
        from apis_sdk.factories.transport_factory import TransportFactory

        transport = TransportFactory.create_requests_transport()
        _statsroyale_facade = StatsRoyaleFactory.create(transport=transport)
        logger.debug("StatsRoyaleFacade initialised")
    except Exception:
        logger.warning("Could not build StatsRoyaleFacade", exc_info=True)
        return None
    return _statsroyale_facade


def _get_clashofstats_facade():
    global _clashofstats_facade
    if _clashofstats_facade is not None:
        return _clashofstats_facade
    try:
        from apis_sdk.factories.clashofstats_factory import ClashOfStatsFactory
        from apis_sdk.infrastructure.http.curl_cffi_transport import CurlCffiTransport

        transport = CurlCffiTransport()
        _clashofstats_facade = ClashOfStatsFactory.create(transport=transport)
        logger.debug("ClashOfStatsFacade initialised")
    except Exception:
        logger.warning("Could not build ClashOfStatsFacade", exc_info=True)
        return None
    return _clashofstats_facade
