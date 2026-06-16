"""Listing composition for resolved New World accounts."""

from __future__ import annotations

from ..models import NwResolvedAccount
from .....core.contracts import (
    ListingContent,
    ListingDraft,
    MediaBundle,
    PipelineRequest,
)


class NwAccountComposer:
    """Generate listing text from a resolved New World account."""

    def compose(
        self,
        account: NwResolvedAccount,
        request: PipelineRequest,
        media: MediaBundle,
    ) -> ListingDraft:
        parts = [
            "New World Account",
            account.region if account.region else "",
        ]
        title = " | ".join(p for p in parts if p)

        lines = [
            "New World Account",
            "---------------------------",
            f"Region: {account.region}" if account.region else "",
        ]
        description = "\n".join(line for line in lines if line)

        return ListingDraft(
            default=ListingContent(
                title=title,
                description=description,
                tags=["new-world", "account"],
            ),
            media=media,
            marketplace_overrides={},
        )
