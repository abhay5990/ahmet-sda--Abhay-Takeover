"""Listing composition for resolved Rust accounts."""

from __future__ import annotations

from ..models import RustResolvedAccount
from .....core.contracts import (
    ListingContent,
    ListingDraft,
    MediaBundle,
    PipelineRequest,
)

# Human-readable labels for attribute IDs
_HOURS_LABELS: dict[str, str] = {
    "hours-099": "0-99 hours",
    "hours-100499": "100-499 hours",
    "hours-5001999": "500-1999 hours",
    "hours-2000": "2000+ hours",
}

_SKINS_LABELS: dict[str, str] = {
    "skins-014": "0-14 skins",
    "skins-1549": "15-49 skins",
    "skins-5099": "50-99 skins",
    "skins-100": "100+ skins",
}


class RustComposer:
    """Generate listing text from a resolved Rust account."""

    def compose(
        self,
        account: RustResolvedAccount,
        request: PipelineRequest,
        media: MediaBundle,
    ) -> ListingDraft:
        parts = [
            "Rust Account",
            account.platform if account.platform else "",
            _HOURS_LABELS.get(account.hours_range, ""),
        ]
        title = " | ".join(p for p in parts if p)

        lines = [
            "Rust Account",
            "---------------------------",
            f"Platform: {account.platform}" if account.platform else "",
            f"Hours: {_HOURS_LABELS.get(account.hours_range, account.hours_range)}" if account.hours_range else "",
            f"Skins: {_SKINS_LABELS.get(account.skins_range, account.skins_range)}" if account.skins_range else "",
            f"Premium: {'Yes' if account.premium_status == 'premium-yes' else 'No'}" if account.premium_status else "",
        ]
        description = "\n".join(line for line in lines if line)

        return ListingDraft(
            default=ListingContent(
                title=title,
                description=description,
                tags=["rust", "steam", "account"],
            ),
            media=media,
            marketplace_overrides={},
        )
