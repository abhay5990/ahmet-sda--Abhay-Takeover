"""Listing composition for resolved Clash of Clans accounts."""

from __future__ import annotations

from .description_generator import CocDescriptionGenerator
from .title_generator import CocTitleGenerator
from ..models import CocResolvedAccount
from .....core.content_hooks import prefix_ref_key
from .....core.contracts import (
    ListingContent,
    ListingDraft,
    MarketplaceListingOverride,
    MediaBundle,
    PipelineRequest,
)


class CocComposer:
    """Generate listing text from the resolved Clash of Clans account."""

    def __init__(self) -> None:
        self.title_generator = CocTitleGenerator()
        self.description_generator = CocDescriptionGenerator()

    def compose(
        self,
        account: CocResolvedAccount,
        request: PipelineRequest,
        media: MediaBundle,
    ) -> ListingDraft:
        title = self.title_generator.generate(account, marketplace="default")
        g2g_title = self.title_generator.generate(account, marketplace="g2g")
        description = prefix_ref_key(
            self.description_generator.generate(account, media=media, marketplace="default"),
            request,
        )

        return ListingDraft(
            default=ListingContent(
                title=title,
                description=description,
                tags=["clash-of-clans", "coc", "supercell", "account"],
            ),
            media=media,
            marketplace_overrides={
                "g2g": MarketplaceListingOverride(title=g2g_title),
            },
        )
