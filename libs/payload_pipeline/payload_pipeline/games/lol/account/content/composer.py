"""Listing composition for resolved League of Legends accounts.

Always builds a full legacy draft first, then overlays any user-created
templates as per-marketplace overrides.  draft.default is never replaced
by a template — it remains the legacy fallback for marketplaces without
a template.
"""

from __future__ import annotations

from .description_generator import LolDescriptionGenerator
from .template_content import build_lol_context
from .title_generator import LolTitleGenerator
from ..models import LolResolvedAccount
from .....content_templates import apply_template_overrides
from .....core import context_keys as ctx
from .....core.contracts import (
    ListingContent,
    ListingDraft,
    MarketplaceListingOverride,
    MediaBundle,
    PipelineRequest,
)


class LolComposer:
    """Generate listing text from the resolved League of Legends account."""

    def __init__(self) -> None:
        self.title_generator = LolTitleGenerator()
        self.description_generator = LolDescriptionGenerator()

    def compose(
        self,
        account: LolResolvedAccount,
        request: PipelineRequest,
        media: MediaBundle,
    ) -> ListingDraft:
        title = self.title_generator.generate(account, marketplace="default")
        g2g_title = self.title_generator.generate(account, marketplace="g2g")
        description = self.description_generator.generate(
            account, media=media, marketplace="default",
        )

        draft = ListingDraft(
            default=ListingContent(
                title=title,
                description=description,
                tags=["league-of-legends", "lol", "riot", "account"],
            ),
            media=media,
            marketplace_overrides={
                "g2g": MarketplaceListingOverride(title=g2g_title),
            },
        )

        # Overlay templates as per-marketplace overrides (draft.default untouched)
        title_templates = ctx.TITLE_TEMPLATES.get(request)
        desc_templates = ctx.DESCRIPTION_TEMPLATES.get(request)
        if title_templates or desc_templates:
            cosmetic_lists = ctx.COSMETIC_LISTS.get(request)
            apply_template_overrides(
                draft,
                build_lol_context(
                    account, request, media,
                    cosmetic_lists=cosmetic_lists,
                ),
                title_templates=title_templates,
                description_templates=desc_templates,
            )

        return draft
