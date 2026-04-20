"""Listing composition for resolved Fortnite accounts."""

from __future__ import annotations

from .description_generator import FortniteDescriptionGenerator
from .title_generator import FortniteTitleGenerator
from ..models import FortniteResolvedAccount
from .....core.contracts import (
    ListingContent,
    ListingDraft,
    MarketplaceListingOverride,
    MediaBundle,
    PipelineRequest,
)


class FortniteComposer:
    """Generate listing text from the resolved Fortnite account."""

    def __init__(self) -> None:
        self.title_generator = FortniteTitleGenerator()
        self.description_generator = FortniteDescriptionGenerator()

    def compose(
        self,
        account: FortniteResolvedAccount,
        request: PipelineRequest,
        media: MediaBundle,
    ) -> ListingDraft:
        title = self.title_generator.generate(account, marketplace="default")
        g2g_title = self.title_generator.generate(account, marketplace="g2g")
        description = self.description_generator.generate(
            account, media=media, marketplace="default",
        )

        return ListingDraft(
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
