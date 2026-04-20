"""Listing composition for resolved Clash Royale accounts."""

from __future__ import annotations

from .description_generator import CrDescriptionGenerator
from .title_generator import CrTitleGenerator
from ..models import CrResolvedAccount
from .....core.contracts import (
    ListingContent,
    ListingDraft,
    MarketplaceListingOverride,
    MediaBundle,
    PipelineRequest,
)
from .....core.enums import ListingKind


class CrComposer:
    """Generate listing text from the resolved Clash Royale account."""

    def __init__(self) -> None:
        self.title_generator = CrTitleGenerator()
        self.description_generator = CrDescriptionGenerator()

    def compose(
        self,
        account: CrResolvedAccount,
        request: PipelineRequest,
        media: MediaBundle,
    ) -> ListingDraft:
        is_dropshipping = request.kind == ListingKind.DROPSHIPPING
        title = self.title_generator.generate(account, marketplace="default")
        g2g_title = self.title_generator.generate(account, marketplace="g2g")
        description = self.description_generator.generate(
            account, media=media, marketplace="default", is_dropshipping=is_dropshipping,
        )

        return ListingDraft(
            default=ListingContent(
                title=title,
                description=description,
                tags=["clash-royale", "cr", "supercell", "account"],
            ),
            media=media,
            marketplace_overrides={
                "g2g": MarketplaceListingOverride(title=g2g_title),
            },
        )
