"""Listing composition for resolved Xbox accounts."""

from __future__ import annotations

from ..models import XboxResolvedAccount
from .....core.contracts import (
    ListingContent,
    ListingDraft,
    MediaBundle,
    PipelineRequest,
)


class XboxComposer:
    """Generate listing text from a resolved Xbox account."""

    def compose(
        self,
        account: XboxResolvedAccount,
        request: PipelineRequest,
        media: MediaBundle,
    ) -> ListingDraft:
        title = "Xbox Account"
        description = "Xbox Account\n---------------------------\nFull access included."

        return ListingDraft(
            default=ListingContent(
                title=title,
                description=description,
                tags=["xbox", "microsoft", "account"],
            ),
            media=media,
            marketplace_overrides={},
        )
