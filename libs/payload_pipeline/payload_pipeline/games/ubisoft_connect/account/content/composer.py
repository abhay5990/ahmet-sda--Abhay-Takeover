"""Listing composition for resolved Ubisoft Connect accounts."""

from __future__ import annotations

from ..models import UbisoftResolvedAccount
from .....core.content_hooks import prefix_ref_key
from .....core.contracts import (
    ListingContent,
    ListingDraft,
    MarketplaceListingOverride,
    MediaBundle,
    PipelineRequest,
)


class UbisoftComposer:
    """Generate listing text from the resolved Ubisoft Connect account."""

    def compose(
        self,
        account: UbisoftResolvedAccount,
        request: PipelineRequest,
        media: MediaBundle,
    ) -> ListingDraft:
        parts = [
            "Ubisoft Connect",
            f"{account.game_count} Games" if account.game_count else "",
            f"R6 Lv{account.r6_level}" if account.r6_level else "",
            "Ubisoft+" if account.has_subscription else "",
            account.country.upper() if account.country else "",
        ]

        title = self._join_parts(parts, 160)
        g2g_title = self._join_parts(parts, 120)

        lines = [
            "Ubisoft Connect Account",
            "---------------------------",
            f"Games: {account.game_count}",
            f"Country: {account.country.upper()}" if account.country else "",
            f"Subscription: {'Ubisoft+' if account.has_subscription else 'No'}",
            f"Xbox Connected: {'Yes' if account.xbox_connected else 'No'}",
            f"PSN Connected: {'Yes' if account.psn_connected else 'No'}",
            f"Balance: {account.balance}" if account.balance else "",
        ]

        if account.r6_level:
            lines.extend([
                "",
                "--- Rainbow Six Siege ---",
                f"Level: {account.r6_level}",
                f"Banned: {'Yes' if account.r6_ban else 'No'}",
            ])

        game_titles = account.game_titles[:10]
        if game_titles:
            lines.append("")
            lines.append("Games:")
            for game_title in game_titles:
                lines.append(f"  - {game_title}")

        lines = [line for line in lines if line is not None]

        if media.album_url:
            lines.append(f"\nAlbum: {media.album_url}")

        description = prefix_ref_key("\n".join(lines), request)

        return ListingDraft(
            default=ListingContent(
                title=title,
                description=description,
                tags=["ubisoft", "uplay", "ubisoft-connect", "account"],
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
