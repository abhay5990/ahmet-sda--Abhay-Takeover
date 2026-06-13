"""Listing composition for resolved GTA V accounts."""

from __future__ import annotations

from ..models import GtavResolvedAccount
from .....core.contracts import (
    ListingContent,
    ListingDraft,
    MarketplaceListingOverride,
    MediaBundle,
    PipelineRequest,
)


class GtavComposer:
    """Generate listing text from the resolved GTA V account."""

    def compose(
        self,
        account: GtavResolvedAccount,
        request: PipelineRequest,
        media: MediaBundle,
    ) -> ListingDraft:
        parts = [
            "GTA V",
            f"Lv{account.level}" if account.level else "",
            f"{account.cash_amount} {account.cash_unit} Cash" if account.cash_amount else "",
            account.main_platform if account.main_platform else "",
        ]

        title = account.title if account.title and account.title != "GTA V Account" else self._join_parts(parts, 160)
        g2g_title = self._join_parts(parts, 120)

        lines = [
            "GTA V Account",
            "---------------------------",
            f"Platform: {account.main_platform}" if account.main_platform else "",
            f"Level: {account.level}" if account.level else "",
            f"Cash: {account.cash_amount} {account.cash_unit}" if account.cash_amount else "",
            f"Cars: {account.cars_count}" if account.cars_count else "",
        ]

        if account.tags:
            lines.append(f"Tags: {', '.join(account.tags)}")

        if account.description:
            lines.append("")
            lines.append(account.description)

        lines = [line for line in lines if line]

        if media.album_url:
            clean_url = media.album_url.removeprefix("https://").removeprefix("http://")
            lines.append(f"\nAlbum: {clean_url}")

        description = "\n".join(lines)

        return ListingDraft(
            default=ListingContent(
                title=title,
                description=description,
                tags=["gta-v", "rockstar", "account"],
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
