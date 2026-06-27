"""Listing composition for resolved CS2 accounts."""

from __future__ import annotations

from ..models import CS2ResolvedAccount
from .....core.contracts import (
    ListingContent,
    ListingDraft,
    MarketplaceListingOverride,
    MediaBundle,
    PipelineRequest,
)


class CS2Composer:
    """Generate listing text from the resolved CS2 account."""

    def compose(
        self,
        account: CS2ResolvedAccount,
        request: PipelineRequest,
        media: MediaBundle,
    ) -> ListingDraft:
        # Manual entries have pre-defined title/description
        if account.manual_title:
            return ListingDraft(
                default=ListingContent(
                    title=account.manual_title[:160],
                    description=account.manual_description or "",
                    tags=["cs2", "counter-strike-2", "account"],
                ),
                media=media,
                marketplace_overrides={
                    "g2g": MarketplaceListingOverride(title=account.manual_title[:120]),
                },
            )

        parts = [
            "CS2",
            account.rank,
            f"{account.premier_elo} Premier" if account.premier_elo else "",
            "Prime" if account.is_prime else "Non-Prime",
            f"{account.medal_count} Medals" if account.medal_count else "",
        ]

        title = self._join_parts(parts, 160)
        g2g_title = self._join_parts(parts, 120)

        lines = [
            "Counter-Strike 2 Account",
            "---------------------------",
            f"Rank: {account.rank or 'Unknown'}",
            f"Premier Elo: {account.premier_elo}",
            f"Prime: {'Yes' if account.is_prime else 'No'}",
            f"Medals: {account.medal_count}",
        ]

        if media.album_url:
            lines.append(f"Album: {media.album_url}")

        description = "\n".join(lines)

        return ListingDraft(
            default=ListingContent(
                title=title,
                description=description,
                tags=["cs2", "counter-strike-2", "account"],
            ),
            media=media,
            marketplace_overrides={
                "g2g": MarketplaceListingOverride(title=g2g_title),
            },
        )

    def _join_parts(self, parts: list[str], max_length: int) -> str:
        result: list[str] = []
        current = ""
        for part in [part for part in parts if part]:
            candidate = part if not current else f"{current} | {part}"
            if len(candidate) > max_length:
                break
            current = candidate
            result.append(part)
        return " | ".join(result)
