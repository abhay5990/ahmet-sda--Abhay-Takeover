"""Listing composition for resolved Brawl Stars accounts."""

from __future__ import annotations

from .description_generator import BrawlStarsDescriptionGenerator
from .title_generator import BrawlStarsTitleGenerator

from ..models import BSResolvedAccount
from .....core.contracts import (
    ListingContent,
    ListingDraft,
    MarketplaceListingOverride,
    MediaBundle,
    PipelineRequest,
)


class BrawlStarsComposer:
    """Compose Brawl Stars listing text from the resolved account model.

    All marketplace variants are generated statically so that the composer
    never branches on ``request.marketplace``.
    """

    def __init__(self) -> None:
        self.title_generator = BrawlStarsTitleGenerator()
        self.description_generator = BrawlStarsDescriptionGenerator()

    def compose(
        self,
        account: BSResolvedAccount,
        request: PipelineRequest,
        media: MediaBundle,
    ) -> ListingDraft:
        title = self.title_generator.generate(account, site="default")
        g2g_title = self.title_generator.generate(account, site="g2g")

        description = self.description_generator.generate(account, media=media, site="default")
        g2g_description = self.description_generator.generate(account, media=media, site="g2g")
        eldorado_description = self.description_generator.generate(account, media=media, site="eldorado")

        return ListingDraft(
            default=ListingContent(
                title=title,
                description=description,
                tags=["brawl-stars", "supercell", "account"],
            ),
            media=media,
            marketplace_overrides={
                "g2g": MarketplaceListingOverride(
                    title=g2g_title,
                    description=g2g_description,
                ),
                "eldorado": MarketplaceListingOverride(
                    description=eldorado_description,
                ),
            },
        )
