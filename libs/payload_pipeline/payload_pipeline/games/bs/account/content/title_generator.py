"""Resolved-model title generation for Brawl Stars listings."""

from __future__ import annotations

from ..models import BSResolvedAccount


class BrawlStarsTitleGenerator:
    """Generate marketplace titles directly from the resolved Brawl Stars account."""

    MAX_BRAWLER_DISPLAY = 60

    def generate(
        self,
        account: BSResolvedAccount,
        *,
        site: str = "default",
    ) -> str:
        max_length = 120 if site.lower() == "g2g" else self._get_max_length(site)
        parts = self._build_parts(account)
        return self._assemble_title(parts, max_length=max_length)

    def _build_parts(self, account: BSResolvedAccount) -> list[str]:
        parts: list[str] = []

        if account.brawler_count > 0:
            parts.append(f"{account.brawler_count} BRAWLERS")

        if account.trophies > 0:
            parts.append(f"\U0001f3c6 {account.trophies} TROPHIES")

        special = self._format_special_rarity(account)
        if special:
            parts.append(special)

        brawler_names = self._format_brawler_names(account.brawler_names)
        if brawler_names:
            parts.append(f"\u2b50\ufe0f{brawler_names}")

        if account.kind != "dropshipping":
            parts.append("\u2b50\ufe0fINSTANT DELIVERY")

        return parts

    def _format_special_rarity(self, account: BSResolvedAccount) -> str:
        if account.legendary_brawler_count > 0:
            return f"\u2b50\ufe0f{account.legendary_brawler_count} LEGENDARY BRAWLERS"
        if account.mythic_count > 0:
            return f"\u2b50\ufe0f{account.mythic_count} MYTHIC BRAWLERS"
        return ""

    def _format_brawler_names(self, names: list[str]) -> str:
        result = ""
        for name in names:
            candidate = f"{result} + {name}".strip() if result else name
            if len(candidate) <= self.MAX_BRAWLER_DISPLAY:
                result = candidate
            else:
                break
        return result

    def _get_max_length(self, site: str) -> int:
        limits = {
            "eldorado": 150,
            "player": 140,
            "gameboost": 140,
            "g2g": 120,
        }
        return limits.get(site.lower(), 140)

    def _assemble_title(
        self, parts: list[str], max_length: int
    ) -> str:
        final_parts: list[str] = []
        current_length = 0
        separator = " | "
        separator_length = len(separator)

        for part in parts:
            part_length = len(part) + (separator_length if final_parts else 0)
            if current_length + part_length > max_length:
                break
            final_parts.append(part)
            current_length += part_length

        return separator.join(final_parts)
