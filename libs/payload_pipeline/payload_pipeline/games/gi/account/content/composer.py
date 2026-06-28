"""Listing composition for resolved Genshin Impact accounts."""

from __future__ import annotations

from .description_generator import GenshinDescriptionGenerator
from .template_content import build_genshin_context
from .title_generator import GenshinTitleGenerator
from ..models import GenshinResolvedAccount
from .....content_templates import apply_template_overrides
from .....core import context_keys as ctx
from .....core.contracts import (
    ListingContent,
    ListingDraft,
    MarketplaceListingOverride,
    MediaBundle,
    PipelineRequest,
)


class GenshinComposer:
    """Generate listing text from the resolved miHoYo account.

    Always builds a full legacy draft first, then overlays any user-created
    templates as per-marketplace overrides.  draft.default is never replaced
    by a template -- it remains the legacy fallback for marketplaces without
    a template.
    """

    def __init__(self) -> None:
        self.title_generator = GenshinTitleGenerator()
        self.description_generator = GenshinDescriptionGenerator()

    def compose(
        self,
        account: GenshinResolvedAccount,
        request: PipelineRequest,
        media: MediaBundle,
    ) -> ListingDraft:
        # Manual entries have pre-defined title/description
        if account.manual_title:
            return ListingDraft(
                default=ListingContent(
                    title=account.manual_title,
                    description=account.manual_description,
                    tags=["genshin-impact", "mihoyo", "hoyoverse", "account"],
                ),
                media=media,
                marketplace_overrides={},
            )

        title = self.title_generator.generate(account, marketplace="default")
        g2g_title = self.title_generator.generate(account, marketplace="g2g")
        description = self.description_generator.generate(account, media=media, marketplace="default")

        draft = ListingDraft(
            default=ListingContent(
                title=title,
                description=description,
                tags=["genshin-impact", "mihoyo", "hoyoverse", "account"],
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
                build_genshin_context(account, request, media),
                title_templates=title_templates,
                description_templates=desc_templates,
            )

        return draft
