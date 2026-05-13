"""Listing composition for resolved R6 accounts."""

from __future__ import annotations

from .description_generator import R6ResolvedDescriptionGenerator
from .template_content import build_r6_context
from .title_generator import R6ResolvedTitleGenerator

from ..models import R6ResolvedAccount
from .....content_templates import apply_template_overrides
from .....core import context_keys as ctx
from .....core.contracts import (
    ListingContent,
    ListingDraft,
    MarketplaceListingOverride,
    MediaBundle,
    PipelineRequest,
)


class R6Composer:
    """Compose R6 listing text from the resolved account model.

    Always builds a full legacy draft first, then overlays any user-created
    templates as per-marketplace overrides.  draft.default is never replaced
    by a template — it remains the legacy fallback for marketplaces without
    a template.
    """

    def __init__(self) -> None:
        self.title_generator = R6ResolvedTitleGenerator()
        self.description_generator = R6ResolvedDescriptionGenerator()

    def compose(
        self,
        account: R6ResolvedAccount,
        request: PipelineRequest,
        media: MediaBundle,
    ) -> ListingDraft:
        # Always build legacy draft first
        title = self.title_generator.generate(account, site="default")
        g2g_title = self.title_generator.generate(account, site="g2g")
        eldorado_title = self.title_generator.generate(account, site="eldorado")
        description = self.description_generator.generate(account, media=media, site="default")
        player_description = self.description_generator.generate(account, media=media, site="player")

        draft = ListingDraft(
            default=ListingContent(
                title=title,
                description=description,
                tags=["r6", "rainbow-six", "account"],
            ),
            media=media,
            marketplace_overrides={
                "g2g": MarketplaceListingOverride(title=g2g_title),
                "eldorado": MarketplaceListingOverride(title=eldorado_title),
                "player": MarketplaceListingOverride(description=player_description),
            },
        )

        # Overlay templates as per-marketplace overrides (draft.default untouched)
        title_templates = ctx.TITLE_TEMPLATES.get(request)
        desc_templates = ctx.DESCRIPTION_TEMPLATES.get(request)
        if title_templates or desc_templates:
            apply_template_overrides(
                draft,
                build_r6_context(account, request, media),
                title_templates=title_templates,
                description_templates=desc_templates,
            )

        return draft
