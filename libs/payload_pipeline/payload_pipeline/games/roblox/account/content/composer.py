"""Listing composition for resolved Roblox accounts."""

from __future__ import annotations

from .description_generator import RobloxDescriptionGenerator
from .title_generator import RobloxTitleGenerator
from ..models import RobloxResolvedAccount
from .....core.contracts import (
    ListingContent,
    ListingDraft,
    MarketplaceListingOverride,
    MediaBundle,
    PipelineRequest,
)
from .....core.enums import ListingKind


class RobloxComposer:
    """Generate listing text from the resolved Roblox account."""

    def __init__(self) -> None:
        self.title_generator = RobloxTitleGenerator()
        self.description_generator = RobloxDescriptionGenerator()

    def compose(
        self,
        account: RobloxResolvedAccount,
        request: PipelineRequest,
        media: MediaBundle,
    ) -> ListingDraft:
        is_dropshipping = request.kind == ListingKind.DROPSHIPPING
        title = self.title_generator.generate(account, marketplace="default")
        gameboost_title = self.title_generator.generate(account, marketplace="gameboost")
        player_title = self.title_generator.generate(account, marketplace="playerauctions")
        description = self.description_generator.generate(
            account, media=media, marketplace="default", is_dropshipping=is_dropshipping,
        )

        return ListingDraft(
            default=ListingContent(
                title=title,
                description=description,
                tags=["roblox", "account"],
            ),
            media=media,
            marketplace_overrides={
                "gameboost": MarketplaceListingOverride(title=gameboost_title),
                "playerauctions": MarketplaceListingOverride(title=player_title),
            },
        )
