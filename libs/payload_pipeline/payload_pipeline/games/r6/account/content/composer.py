"""Listing composition for resolved R6 accounts."""

from __future__ import annotations

from .description_generator import R6ResolvedDescriptionGenerator
from .title_generator import R6ResolvedTitleGenerator

from ..models import R6ResolvedAccount
from .....core.contracts import (
    ListingContent,
    ListingDraft,
    MarketplaceListingOverride,
    MediaBundle,
    PipelineRequest,
)


class R6Composer:
    """Compose R6 listing text from the resolved account model."""

    def __init__(self) -> None:
        self.title_generator = R6ResolvedTitleGenerator()
        self.description_generator = R6ResolvedDescriptionGenerator()

    def compose(
        self,
        account: R6ResolvedAccount,
        request: PipelineRequest,
        media: MediaBundle,
    ) -> ListingDraft:
        title = self.title_generator.generate(account, site="default")
        g2g_title = self.title_generator.generate(account, site="g2g")
        eldorado_title = self.title_generator.generate(account, site="eldorado")
        description = self.description_generator.generate(account, media=media, site="default")
        player_description = self.description_generator.generate(account, media=media, site="player")

        return ListingDraft(
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
