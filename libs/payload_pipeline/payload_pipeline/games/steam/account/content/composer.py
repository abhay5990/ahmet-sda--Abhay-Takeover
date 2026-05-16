"""Listing composition for resolved Steam accounts."""

from __future__ import annotations

from ..models import SteamResolvedAccount
from .....core.contracts import (
    ListingContent,
    ListingDraft,
    MarketplaceListingOverride,
    MediaBundle,
    PipelineRequest,
)


class SteamComposer:
    """Generate listing text from the resolved Steam account."""

    def compose(
        self,
        account: SteamResolvedAccount,
        request: PipelineRequest,
        media: MediaBundle,
    ) -> ListingDraft:
        parts = [
            "Steam",
            f"{account.total_games} Games" if account.total_games else "",
            account.country.upper() if account.country else "",
        ]

        title = self._join_parts(parts, 160)
        g2g_title = self._join_parts(parts, 120)

        lines = [
            "Steam Account",
            "---------------------------",
            f"Games: {account.total_games}",
            f"Country: {account.country.upper()}" if account.country else "",
        ]

        top_games = account.game_titles[:10]
        if top_games:
            lines.append("")
            lines.append("Games:")
            for game_title in top_games:
                lines.append(f"  - {game_title}")

        lines = [line for line in lines if line is not None]

        if media.album_url:
            lines.append(f"\nAlbum: {media.album_url}")

        description = "\n".join(lines)

        return ListingDraft(
            default=ListingContent(
                title=title,
                description=description,
                tags=["steam", "account"],
            ),
            media=media,
            marketplace_overrides={
                "g2g": MarketplaceListingOverride(title=g2g_title),
            },
        )

    def _join_parts(self, parts: list[str], max_length: int) -> str:
        result: list[str] = []
        current = ""
        for part in [p for p in parts if p]:
            candidate = part if not current else f"{current} | {part}"
            if len(candidate) > max_length:
                break
            current = candidate
            result.append(part)
        return " | ".join(result)
