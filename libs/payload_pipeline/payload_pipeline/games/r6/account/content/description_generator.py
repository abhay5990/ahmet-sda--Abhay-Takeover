"""Resolved-model description generation for R6 listings.

Matches the legacy R6DescriptionGenerator output:
  - Header with stats (level, rank, operator/skin counts)
  - Tracker link
  - Inventory category breakdowns (when available)
  - Operator and skin previews
  - Footer with ownership text, warranty, delivery, and Outlook note

Character limit: 1900 (footer is always preserved via smart truncation).
"""

from __future__ import annotations

import re

from .....core.contracts import MediaBundle
from ..models import R6InventoryCategory, R6ResolvedAccount

_DESCRIPTION_LIMIT = 1900


class R6ResolvedDescriptionGenerator:
    """Generate marketplace descriptions directly from the resolved R6 account."""

    def generate(
        self,
        account: R6ResolvedAccount,
        *,
        media: MediaBundle,
        site: str = "default",
    ) -> str:
        if account.inventory.has_data:
            body = self._build_with_inventory(account, media=media, site=site)
        else:
            body = self._build_basic(account, media=media, site=site)

        footer = self._build_footer(account)
        description = self._fit_with_reserved_footer(body, footer, _DESCRIPTION_LIMIT)

        if site == "player":
            description = description.replace("\n", "<br>")

        return description

    # ------------------------------------------------------------------
    # Build paths
    # ------------------------------------------------------------------

    def _build_basic(
        self,
        account: R6ResolvedAccount,
        *,
        media: MediaBundle,
        site: str,
    ) -> str:
        parts: list[str] = []

        album = self._format_album_url(media.album_url, site)
        if album:
            parts.append(album)

        rank_line = self._rank_line(account)
        header = (
            "Rainbow Six Siege Account Details:\n"
            "---------------------------\n"
            f"{rank_line}"
            f"Level: {account.level}\n"
            f"Operator Count: {account.operator_count}\n"
            f"Skin Count: {account.skin_count}\n"
        )

        if account.black_ice_count > 0:
            header += f"Black Ice Skins: {account.black_ice_count}\n"

        parts.append(header)

        if account.tracker_url:
            parts.append(f"Account Tracker Link: \n\t{account.tracker_url}\n")

        op_preview = self._preview("Some Operators", account.operators, limit=15)
        if op_preview:
            parts.append(op_preview)

        skin_preview = self._preview("Some Skins", account.skin_names, limit=15)
        if skin_preview:
            parts.append(skin_preview)

        return "\n".join(parts)

    def _build_with_inventory(
        self,
        account: R6ResolvedAccount,
        *,
        media: MediaBundle,
        site: str,
    ) -> str:
        parts: list[str] = []
        inv = account.inventory

        album = self._format_album_url(media.album_url, site)
        if album:
            parts.append(album)

        header = (
            "Rainbow Six Siege Account Details:\n"
            "---------------------------\n"
            f"Level: {account.level}\n"
            f"Operator Count: {account.operator_count}\n"
            f"Skin Count: {account.skin_count}\n"
        )
        parts.append(header)

        if account.tracker_url:
            parts.append(f"Account Tracker Link: \n\t{account.tracker_url}\n")

        # Inventory categories
        parts.append(self._format_category("Some Rank Charms", inv.ranked_charms, limit=10))
        parts.append(self._format_category("Glacier Count", inv.glaciers, limit=10))
        parts.append(self._format_category("Black Ice Count", inv.black_ices, limit=10))
        parts.append(self._format_category("Dust Line Count", inv.dust_lines, limit=10))

        racer_items = inv.racer_items()
        if racer_items:
            parts.append(
                f"Racer Count: {len(racer_items)}\n"
                f"    - {', '.join(racer_items[:6])}"
                f"{'...' if len(racer_items) > 6 else ''}\n"
            )

        parts.append(self._format_category("Universal Count", inv.universals, limit=6))
        parts.append(self._format_category("Seasonal Count", inv.seasonals, limit=6))
        parts.append(self._format_category("Pro League (Old) Count", inv.pro_leagues_old, limit=6))

        if inv.pro_leagues_new.count > 0:
            parts.append(self._format_category("Pro League Count", inv.pro_leagues_new, limit=6))

        parts.append(self._format_category("Elite Count", inv.elites, limit=6))

        if inv.legendary_skins.count > 0:
            preview = ", ".join(inv.legendary_skins.items[:6])
            if len(inv.legendary_skins.items) > 6:
                preview += "..."
            parts.append(
                f"Legendary Weapon Skins Count: {inv.legendary_skins.count}\n"
                f"    - {preview}\n"
            )

        if inv.other_skins:
            other_list = ", ".join(inv.other_skins[:8])
            if len(inv.other_skins) > 8:
                other_list += "..."
            parts.append(f"Some of Other Skins: {other_list}\n")

        if account.operators:
            op_list = ", ".join(account.operators[:10])
            if len(account.operators) > 10:
                op_list += "..."
            parts.append(f"Some Operators: {op_list}\n")

        return "\n".join(p for p in parts if p)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _rank_line(self, account: R6ResolvedAccount) -> str:
        rank = str(account.current_rank or "").strip()
        if rank and rank.lower() != "unranked":
            return f"Rank: {rank}\n"
        if account.ranked_ready:
            return "Ranked Ready\n"
        return ""

    def _format_album_url(self, album_url: str | None, site: str) -> str:
        if not album_url or site == "g2g":
            return ""
        clean = re.sub(r"^https?://", "", album_url)
        return f"Images Link: \n{clean}\n"

    def _format_category(self, label: str, category: R6InventoryCategory, limit: int) -> str:
        if category.count == 0:
            return ""
        preview = ", ".join(category.items[:limit])
        if len(category.items) > limit:
            preview += "..."
        return f"{label}: {category.count}\n    - {preview}\n"

    def _preview(self, label: str, values: list[str], *, limit: int) -> str:
        cleaned = [v.strip() for v in values if v.strip()]
        if not cleaned:
            return ""
        preview = ", ".join(cleaned[:limit])
        if len(cleaned) > limit:
            preview += "..."
        return f"{label}: {preview}\n"

    def _build_footer(self, account: R6ResolvedAccount) -> str:
        ownership = account.ownership_text
        ownership_block = f"{ownership}\n" if ownership else ""

        instant = "\nInstant Delivery\n" if account.kind != "dropshipping" else ""

        return (
            f"{ownership_block}"
            "This account comes with a variety of operators\n"
            "and skins, giving you more options to customize your gameplay.\n"
            "\n"
            "Full Access\n"
            "\n"
            "Has Warranty\n"
            f"{instant}\n"
        )

    def _fit_with_reserved_footer(self, body: str, footer: str, limit: int) -> str:
        body = body.strip()
        footer = footer.strip()

        if not footer:
            return self._truncate(body, limit)

        sep = "\n\n" if body else ""
        if len(body) + len(sep) + len(footer) <= limit:
            return f"{body}{sep}{footer}\n"

        blocks = [b.strip() for b in body.split("\n\n") if b.strip()]
        if not blocks:
            return self._truncate(footer, limit)

        reserve = len(footer) + 2  # "\n\n" before footer
        composed = blocks[0]

        if len(composed) + reserve > limit:
            allowed = max(0, limit - reserve)
            composed = self._trim_to_line(composed, allowed)

        for block in blocks[1:]:
            candidate = f"{composed}\n\n{block}" if composed else block
            if len(candidate) + reserve <= limit:
                composed = candidate
            else:
                break

        if composed:
            result = f"{composed}\n\n{footer}\n"
        else:
            result = f"{footer}\n"

        if len(result) <= limit:
            return result

        if len(footer) <= limit:
            allowed = max(0, limit - len(footer) - 2)
            prefix = self._trim_to_line(composed, allowed)
            if prefix:
                return f"{prefix}\n\n{footer}\n"
            return f"{footer}\n"

        return self._truncate(footer, limit)

    def _trim_to_line(self, text: str, max_len: int) -> str:
        if len(text) <= max_len:
            return text
        sliced = text[:max_len]
        cut = sliced.rfind("\n")
        if cut > 0:
            return sliced[:cut].rstrip()
        return sliced.rstrip()

    def _truncate(self, text: str, limit: int) -> str:
        if len(text) <= limit:
            return text
        return text[:limit - 3] + "..."
