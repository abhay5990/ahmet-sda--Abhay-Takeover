"""Listing composition for New World items (GameBoost)."""

from __future__ import annotations

from ..models import NwResolvedItem
from .....core.contracts import (
    ListingContent,
    ListingDraft,
    MediaBundle,
    PipelineRequest,
)


class NwItemComposer:
    """Generate listing text for a New World item."""

    def compose(
        self,
        item: NwResolvedItem,
        request: PipelineRequest,
        media: MediaBundle,
    ) -> ListingDraft:
        parts = [
            "New World",
            item.region if item.region else "",
        ]
        title = " | ".join(p for p in parts if p)

        lines = [
            "New World",
            "---------------------------",
            f"Region: {item.region}" if item.region else "",
        ]
        description = "\n".join(line for line in lines if line)

        return ListingDraft(
            default=ListingContent(
                title=title,
                description=description,
                tags=["new-world", "item"],
            ),
            media=media,
            marketplace_overrides={},
        )
