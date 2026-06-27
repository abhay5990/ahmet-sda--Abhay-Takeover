"""Listing composition for resolved Forza Horizon 5 accounts."""

from __future__ import annotations

from ..models import Fh5ResolvedAccount
from .....core.contracts import (
    ListingContent,
    ListingDraft,
    MediaBundle,
    PipelineRequest,
)


class Fh5Composer:
    """Generate listing text from a resolved Forza Horizon 5 account."""

    def compose(
        self,
        account: Fh5ResolvedAccount,
        request: PipelineRequest,
        media: MediaBundle,
    ) -> ListingDraft:
        if account.manual_title:
            return ListingDraft(
                default=ListingContent(
                    title=account.manual_title,
                    description=account.manual_description or "",
                    tags=["forza-horizon-5", "forza", "xbox", "account"],
                ),
                media=media,
                marketplace_overrides={},
            )

        parts = [
            "Forza Horizon 5",
            account.platform if account.platform else "",
            account.edition if account.edition and account.edition != "Standard" else "",
        ]
        title = " | ".join(p for p in parts if p)

        lines = [
            "Forza Horizon 5 Account",
            "---------------------------",
            f"Platform: {account.platform}" if account.platform else "",
            f"Edition: {account.edition}" if account.edition else "",
            f"Cars: {account.cars_count}" if account.cars_count else "",
            f"Credits: {account.credits_count:,}" if account.credits_count else "",
        ]
        description = "\n".join(line for line in lines if line)

        return ListingDraft(
            default=ListingContent(
                title=title,
                description=description,
                tags=["forza-horizon-5", "forza", "xbox", "account"],
            ),
            media=media,
            marketplace_overrides={},
        )
