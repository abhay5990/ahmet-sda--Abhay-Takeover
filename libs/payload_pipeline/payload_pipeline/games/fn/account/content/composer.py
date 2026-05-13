"""Listing composition for resolved Fortnite accounts."""

from __future__ import annotations

from .description_generator import FortniteDescriptionGenerator
from .template_content import build_fortnite_context
from .title_generator import FortniteTitleGenerator
from ..models import FortniteResolvedAccount
from .....content_templates import apply_template_overrides
from .....core import context_keys as ctx
from .....core.contracts import (
    ListingContent,
    ListingDraft,
    MarketplaceListingOverride,
    MediaBundle,
    PipelineRequest,
)


class FortniteComposer:
    """Generate listing text from the resolved Fortnite account.

    Always builds a full legacy draft first, then overlays any user-created
    templates as per-marketplace overrides.  draft.default is never replaced
    by a template — it remains the legacy fallback for marketplaces without
    a template.
    """

    def __init__(self) -> None:
        self.title_generator = FortniteTitleGenerator()
        self.description_generator = FortniteDescriptionGenerator()

    def compose(
        self,
        account: FortniteResolvedAccount,
        request: PipelineRequest,
        media: MediaBundle,
    ) -> ListingDraft:
        # Always build legacy draft first
        title = self.title_generator.generate(account, marketplace="default")
        g2g_title = self.title_generator.generate(account, marketplace="g2g")
        description = self.description_generator.generate(
            account, media=media, marketplace="default",
        )

        draft = ListingDraft(
            default=ListingContent(
                title=title,
                description=description,
                tags=["fortnite", "epic-games", "account"],
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
            apply_template_overrides(
                draft,
                build_fortnite_context(account, request, media),
                title_templates=title_templates,
                description_templates=desc_templates,
            )

        return draft
