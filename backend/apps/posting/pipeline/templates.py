"""Django-backed content template overrides for payload_pipeline."""

from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import Any

from payload_pipeline.core.contracts import ListingKind

logger = logging.getLogger(__name__)


def load_content_template_overrides(
    *,
    game_slug: str,
    kind: ListingKind | str,
    category: str = 'account',
) -> dict[str, dict[str, Any]]:
    """Return enabled DB template overrides in payload_pipeline map shape."""
    try:
        from apps.posting.models import ContentTemplateOverride

        kind_value = kind.value if hasattr(kind, 'value') else str(kind)
        rows = ContentTemplateOverride.objects.filter(
            enabled=True,
            game__slug=game_slug,
            category=category,
            kind=kind_value,
        ).only(
            'marketplace',
            'title_template',
            'description_template',
        )
        return _rows_to_template_map(rows)
    except Exception as exc:
        logger.warning(
            "Could not load content template overrides for %s/%s: %s",
            game_slug,
            kind,
            exc,
        )
        return {}


def _rows_to_template_map(rows) -> dict[str, dict[str, Any]]:
    overrides: dict[str, dict[str, Any]] = {}
    for row in rows:
        entry = overrides.setdefault(row.marketplace, {})
        if _has_template(row.title_template):
            entry['title'] = row.title_template
        if _has_template(row.description_template):
            entry['description'] = row.description_template

    return {
        marketplace: entry
        for marketplace, entry in overrides.items()
        if entry
    }


def _has_template(value: Any) -> bool:
    return isinstance(value, Mapping) and bool(value)
