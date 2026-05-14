"""Load content templates from the Django ContentTemplate model."""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def load_templates_for_posting(
    *,
    game_id: int,
    posting_defaults: dict,
) -> tuple[dict[str, str] | None, dict[str, str] | None]:
    """Load title and description template bodies for a posting job.

    Reads from PostingDefault FK selections per marketplace.

    Args:
        game_id: The game's PK.
        posting_defaults: Marketplace→PostingDefault mapping. Each
            PostingDefault may have title_template and/or
            description_template FKs set.

    Returns:
        (title_templates, description_templates) — each is a
        marketplace→body dict, or None if no templates selected.
    """
    title_templates: dict[str, str] = {}
    description_templates: dict[str, str] = {}

    for marketplace, defaults in posting_defaults.items():
        if hasattr(defaults, 'title_template') and defaults.title_template_id:
            title_templates[marketplace] = defaults.title_template.body
        if hasattr(defaults, 'description_template') and defaults.description_template_id:
            description_templates[marketplace] = defaults.description_template.body

    return (
        title_templates or None,
        description_templates or None,
    )
