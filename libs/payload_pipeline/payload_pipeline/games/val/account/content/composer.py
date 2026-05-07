"""Listing composition for resolved Valorant accounts."""

from __future__ import annotations

from .description_generator import ValorantDescriptionGenerator
from .title_generator import ValorantTitleGenerator
from ..models import ValorantResolvedAccount
from .....core.content_hooks import prefix_ref_key
from .....core.contracts import (
    ListingContent,
    ListingDraft,
    MarketplaceListingOverride,
    MediaBundle,
    PipelineRequest,
)
from .....core.enums import ListingKind


class ValorantComposer:
    """Compose Valorant listing text from the resolved account model."""

    def __init__(self) -> None:
        self.title_generator = ValorantTitleGenerator()
        self.description_generator = ValorantDescriptionGenerator()

    def compose(
        self,
        account: ValorantResolvedAccount,
        request: PipelineRequest,
        media: MediaBundle,
    ) -> ListingDraft:
        title = self.title_generator.generate(account, marketplace="default")
        g2g_title = self.title_generator.generate(account, marketplace="g2g")
        is_dropshipping = request.kind == ListingKind.DROPSHIPPING
        description = prefix_ref_key(
            self.description_generator.generate(
                account, media=media, marketplace="default", is_dropshipping=is_dropshipping,
            ),
            request,
        )

        return ListingDraft(
            default=ListingContent(
                title=title,
                description=description,
                tags=["valorant", account.region.lower() if account.region else "riot-account", "account"],
            ),
            media=media,
            marketplace_overrides={
                "g2g": MarketplaceListingOverride(title=g2g_title),
            },
        )
