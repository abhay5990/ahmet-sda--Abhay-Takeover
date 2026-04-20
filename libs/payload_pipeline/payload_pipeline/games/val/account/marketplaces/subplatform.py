"""Subplatform selection helpers for Valorant Eldorado listings."""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

PLATFORM_IDS: dict[str, str] = {
    "pc": "0",
    "psn": "1",
    "playstation": "1",
    "xbox": "2",
}

DEFAULT_PLATFORM_ID = "0"


def resolve_platform_id(
    *,
    manual_selection: str | None = None,
    subplatform_status: dict[str, Any] | None = None,
) -> str:
    """Pick the best Eldorado platform ID for Valorant.

    Priority:
      1. Explicit manual selection (UI override).
      2. Least-full platform from *subplatform_status*.
      3. Random fallback when no data is available.
    """
    if manual_selection and manual_selection.lower() != "auto":
        pid = PLATFORM_IDS.get(manual_selection.lower())
        if pid is not None:
            return pid
        logger.warning("Unknown manual subplatform %r, falling back", manual_selection)

    selected = _select_least_full(subplatform_status)
    if selected is not None:
        return selected

    return _fallback()


def _select_least_full(status: dict[str, Any] | None) -> str | None:
    if not status:
        return None

    candidates: list[tuple[str, float]] = []
    for platform, info in status.items():
        if not isinstance(info, dict):
            continue
        available = info.get("available", 0)
        pct = info.get("percentage_used", 100.0)
        if available > 0:
            candidates.append((platform.lower(), pct))

    if not candidates:
        return None

    best_platform = min(candidates, key=lambda x: x[1])[0]
    return PLATFORM_IDS.get(best_platform)


def _fallback() -> str:
    logger.warning("No subplatform data for Valorant – using default PC platform")
    return DEFAULT_PLATFORM_ID
