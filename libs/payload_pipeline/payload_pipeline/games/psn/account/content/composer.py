"""Listing composition for resolved PSN accounts."""

from __future__ import annotations

from ..models import PsnResolvedAccount
from .....core.contracts import (
    ListingContent,
    ListingDraft,
    MediaBundle,
    PipelineRequest,
)


class PsnComposer:
    """Generate listing text from a resolved PSN account."""

    def compose(
        self,
        account: PsnResolvedAccount,
        request: PipelineRequest,
        media: MediaBundle,
    ) -> ListingDraft:
        title = "PSN Account"
        description = "PSN Account\n---------------------------\nFull access included."

        return ListingDraft(
            default=ListingContent(
                title=title,
                description=description,
                tags=["psn", "playstation", "account"],
            ),
            media=media,
            marketplace_overrides={},
        )
