"""Listing composition for resolved Valorant accounts."""

from __future__ import annotations

from .description_generator import ValorantDescriptionGenerator
from .title_generator import ValorantTitleGenerator
from ..models import ValorantResolvedAccount
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
        tags = [
            "valorant",
            account.region.lower() if account.region else "riot-account",
            "account",
            *account.account_tags,
        ]

        # Manual entries have pre-defined title/description
        if account.manual_title:
            return ListingDraft(
                default=ListingContent(
                    title=account.manual_title[:160],
                    description=account.manual_description or "",
                    tags=tags,
                ),
                media=media,
                marketplace_overrides={
                    "g2g": MarketplaceListingOverride(title=account.manual_title[:120]),
                },
            )

        title = self.title_generator.generate(account, marketplace="default")
        g2g_title = self.title_generator.generate(account, marketplace="g2g")
        is_dropshipping = request.kind == ListingKind.DROPSHIPPING
        description = self.description_generator.generate(
            account, media=media, marketplace="default", is_dropshipping=is_dropshipping,
        )

        return ListingDraft(
            default=ListingContent(
                title=title,
                description=description,
                tags=tags,
            ),
            media=media,
            marketplace_overrides={
                "g2g": MarketplaceListingOverride(title=g2g_title),
            },
        )
