"""Listing composition for resolved League of Legends accounts."""

from __future__ import annotations

from .description_generator import LolDescriptionGenerator
from .title_generator import LolTitleGenerator
from ..models import LolResolvedAccount
from .....core.contracts import (
    ListingContent,
    ListingDraft,
    MarketplaceListingOverride,
    MediaBundle,
    PipelineRequest,
)
from .....core.enums import ListingKind


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
        is_dropshipping = request.kind == ListingKind.DROPSHIPPING
        title = self.title_generator.generate(account, marketplace="default", is_dropshipping=is_dropshipping)
        g2g_title = self.title_generator.generate(account, marketplace="g2g", is_dropshipping=is_dropshipping)
        description = self.description_generator.generate(
            account, media=media, marketplace="default", is_dropshipping=is_dropshipping,
        )

        return ListingDraft(
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
