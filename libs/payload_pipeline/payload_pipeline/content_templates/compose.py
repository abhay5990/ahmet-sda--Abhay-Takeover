"""Generic template-based content composition.

Provides ``compose_with_templates`` that any game composer can call to
render title/description from user-created templates.  Falls back to
``None`` for marketplaces without a template, so the caller can mix
template output with legacy generators.

Usage in a composer::

    title_templates = ctx.TITLE_TEMPLATES.get(request)
    desc_templates = ctx.DESCRIPTION_TEMPLATES.get(request)

    if title_templates or desc_templates:
        result = compose_with_templates(
            context=build_context(account, media),
            title_templates=title_templates,
            description_templates=desc_templates,
            marketplaces=["eldorado", "g2g", "gameboost", "playerauctions"],
        )
        # result.default_title, result.default_description
        # result.overrides["g2g"].title, etc.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ..core.contracts import (
    ListingContent,
    ListingDraft,
    MarketplaceListingOverride,
    MediaBundle,
)
from .renderer import SimpleTemplateRenderer


@dataclass(slots=True)
class TemplateComposeResult:
    """Result of template-based content generation."""

    default_title: str | None = None
    default_description: str | None = None
    marketplace_titles: dict[str, str] = field(default_factory=dict)
    marketplace_descriptions: dict[str, str] = field(default_factory=dict)


def compose_with_templates(
    context: dict[str, Any],
    *,
    title_templates: dict[str, str] | None = None,
    description_templates: dict[str, str] | None = None,
    default_marketplace: str = "eldorado",
) -> TemplateComposeResult:
    """Render all marketplace templates and return structured results.

    Parameters:
        context: Flat field→value dict from the resolved account model.
        title_templates: Marketplace→template body mapping for titles.
        description_templates: Same for descriptions.
        default_marketplace: Which marketplace template to use as the
            default title/description (typically the first marketplace
            in the posting job).

    Returns:
        A ``TemplateComposeResult`` with rendered strings per marketplace.
        Fields are ``None`` when no template was provided for that slot.
    """
    renderer = SimpleTemplateRenderer()
    result = TemplateComposeResult()

    if title_templates:
        for marketplace, body in title_templates.items():
            rendered = renderer.render(body, context)
            result.marketplace_titles[marketplace] = rendered
        if default_marketplace in result.marketplace_titles:
            result.default_title = result.marketplace_titles[default_marketplace]
        elif result.marketplace_titles:
            result.default_title = next(iter(result.marketplace_titles.values()))

    if description_templates:
        for marketplace, body in description_templates.items():
            rendered = renderer.render(body, context)
            result.marketplace_descriptions[marketplace] = rendered
        if default_marketplace in result.marketplace_descriptions:
            result.default_description = result.marketplace_descriptions[default_marketplace]
        elif result.marketplace_descriptions:
            result.default_description = next(iter(result.marketplace_descriptions.values()))

    return result


def compose_listing_draft(
    context: dict[str, Any],
    *,
    title_templates: dict[str, str] | None,
    description_templates: dict[str, str] | None,
    media: MediaBundle,
    tags: list[str],
) -> ListingDraft:
    """Render templates and build a ListingDraft in one step.

    Shared helper that eliminates the identical compose→override→draft
    boilerplate in every game's template_content.py.
    """
    result = compose_with_templates(
        context,
        title_templates=title_templates,
        description_templates=description_templates,
    )

    overrides: dict[str, MarketplaceListingOverride] = {}
    all_marketplaces = set(result.marketplace_titles) | set(result.marketplace_descriptions)
    for mp in all_marketplaces:
        title = result.marketplace_titles.get(mp)
        desc = result.marketplace_descriptions.get(mp)
        if title is not None or desc is not None:
            overrides[mp] = MarketplaceListingOverride(title=title, description=desc)

    return ListingDraft(
        default=ListingContent(
            title=result.default_title or "",
            description=result.default_description or "",
            tags=tags,
        ),
        media=media,
        marketplace_overrides=overrides,
    )


def apply_template_overrides(
    draft: ListingDraft,
    context: dict[str, Any],
    *,
    title_templates: dict[str, str] | None = None,
    description_templates: dict[str, str] | None = None,
) -> ListingDraft:
    """Render templates and patch them into draft as per-marketplace overrides.

    draft.default is never modified — legacy content remains as the fallback.
    Only marketplaces that have a template get an override entry written.
    """
    rendered = compose_with_templates(
        context,
        title_templates=title_templates,
        description_templates=description_templates,
    )

    for mp, title in rendered.marketplace_titles.items():
        override = draft.marketplace_overrides.setdefault(mp, MarketplaceListingOverride())
        override.title = title

    for mp, desc in rendered.marketplace_descriptions.items():
        override = draft.marketplace_overrides.setdefault(mp, MarketplaceListingOverride())
        override.description = desc

    return draft
