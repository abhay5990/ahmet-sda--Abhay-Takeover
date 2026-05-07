"""Listing composition for resolved Genshin Impact accounts."""

from __future__ import annotations

from .description_generator import GenshinDescriptionGenerator
from .title_generator import GenshinTitleGenerator
from ..models import GenshinResolvedAccount
from .....core.content_hooks import prefix_ref_key
from .....core.contracts import (
    ListingContent,
    ListingDraft,
    MarketplaceListingOverride,
    MediaBundle,
    PipelineRequest,
)


class GenshinComposer:
    """Generate listing text from the resolved miHoYo account."""

    def __init__(self) -> None:
        self.title_generator = GenshinTitleGenerator()
        self.description_generator = GenshinDescriptionGenerator()

    def compose(
        self,
        account: GenshinResolvedAccount,
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
                tags=["genshin-impact", "mihoyo", "hoyoverse", "account"],
            ),
            media=media,
            marketplace_overrides={
                "g2g": MarketplaceListingOverride(title=g2g_title),
            },
        )
