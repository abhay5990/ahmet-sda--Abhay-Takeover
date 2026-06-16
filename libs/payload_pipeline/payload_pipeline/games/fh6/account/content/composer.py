"""Listing composition for resolved Forza Horizon 6 accounts."""

from __future__ import annotations

from ..models import Fh6ResolvedAccount
from .....core.contracts import (
    ListingContent,
    ListingDraft,
    MediaBundle,
    PipelineRequest,
)


class Fh6Composer:
    """Generate listing text from a resolved Forza Horizon 6 account."""

    def compose(
        self,
        account: Fh6ResolvedAccount,
        request: PipelineRequest,
        media: MediaBundle,
    ) -> ListingDraft:
        title = "Forza Horizon 6 Account"
        description = "Forza Horizon 6 Account\n---------------------------\nFull access included."

        return ListingDraft(
            default=ListingContent(
                title=title,
                description=description,
                tags=["forza-horizon-6", "forza", "xbox", "account"],
            ),
            media=media,
            marketplace_overrides={},
        )
