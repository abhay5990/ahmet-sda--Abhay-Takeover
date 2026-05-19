"""Resolved-model title generation for R6 listings.

Matches the legacy R6TitleGenerator output format from src/games.
Two build paths: basic (no tracker inventory) and with-inventory.
"""

from __future__ import annotations

from ..models import R6ResolvedAccount

_PLATFORM_LABELS = {"PC": "PC", "PlayStation": "PSN", "Xbox": "XBOX"}

_SITE_MAX_LENGTHS: dict[str, int] = {
    "eldorado": 150,
    "player": 140,
    "gameboost": 140,
    "g2g": 120,
}
_DEFAULT_MAX_LENGTH = 140


class R6ResolvedTitleGenerator:
    """Generate marketplace titles directly from the resolved R6 account."""

    def generate(
        self,
        account: R6ResolvedAccount,
        *,
        site: str = "default",
    ) -> str:
        max_length = _SITE_MAX_LENGTHS.get(site.lower(), _DEFAULT_MAX_LENGTH)

        if account.inventory.has_data:
            parts = self._build_with_inventory(account)
        else:
            parts = self._build_basic(account)

        return self._assemble(parts, max_length=max_length)

    # ------------------------------------------------------------------
    # Build paths
    # ------------------------------------------------------------------

    def _build_basic(self, account: R6ResolvedAccount) -> list[str]:
        parts: list[str] = []
        parts.append(self._platform_string(account))

        if account.level > 0:
            parts.append(f"Level {account.level}")

        rank = self._rank_text(account)
        if rank:
            parts.append(rank)

        if account.operator_count > 0:
            parts.append(f"{account.operator_count} Operators")
        if account.skin_count > 0:
            parts.append(f"{account.skin_count} Skins")
        if account.black_ice_count > 0:
            parts.append(f"{account.black_ice_count}xBlack Ice")

        parts.append(account.platform_type_text)
        parts.append("Full Access")
        if account.kind != "dropshipping":
            parts.append("Instant Delivery")
        parts.append("Mail Changeable")

        return parts

    def _build_with_inventory(self, account: R6ResolvedAccount) -> list[str]:
        parts: list[str] = []
        inv = account.inventory

        parts.append(self._platform_string(account))

        if account.level > 0:
            parts.append(f"Level {account.level}")

        rank = self._rank_text(account)
        if rank:
            parts.append(rank)

        peak = self._peak_rank_text(account)
        if peak:
            parts.append(peak)

        if account.skin_count > 0:
            parts.append(f"{account.skin_count} Skins")
        if account.operator_count > 0:
            parts.append(f"{account.operator_count} Operators")

        if inv.glaciers.count > 0:
            parts.append(f"{inv.glaciers.count}xGlacier")

        if inv.black_ices.count > 0:
            parts.append(f"{inv.black_ices.count}xBlack Ice")
            weapons = inv.find_weapons(inv.black_ices, ["R4C", "MP5"])
            if weapons:
                parts.append(f"({'-'.join(weapons)})")

        if inv.dust_lines.count > 0:
            parts.append(f"{inv.dust_lines.count}xDust Line")

        racer_count = inv.racer_count()
        if racer_count > 0:
            parts.append(f"{racer_count}xRacer")

        if inv.universals.count > 0:
            parts.append(f"{inv.universals.count}xUniversal")
            specials = inv.find_items(inv.universals, ["Fire", "Blue Nebula"])
            if specials:
                parts.append(f"({','.join(specials[:2])})")

        if inv.seasonals.count > 0:
            parts.append(f"{inv.seasonals.count}xSeasonals")
            specials = inv.find_items(inv.seasonals, ["Obsidian", "El Dorado", "Aki No Tsuru", "Onami"])
            if specials:
                parts.append(f"({','.join(specials[:3])})")

        if inv.pro_leagues_old.count > 0:
            parts.append(f"{inv.pro_leagues_old.count}xPro League (Old)")
        elif inv.pro_leagues_new.count > 0:
            parts.append(f"{inv.pro_leagues_new.count}xPro League")

        if inv.pilot_program.count > 0:
            parts.append(f"{inv.pilot_program.count}xPilot Program")

        parts.append(account.platform_type_text)
        parts.append("Full Access")
        if account.kind != "dropshipping":
            parts.append("Instant Delivery")
        parts.append("Mail Changeable")

        return parts

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _platform_string(self, account: R6ResolvedAccount) -> str:
        labels = [_PLATFORM_LABELS.get(p, p.upper()) for p in account.linkable_platforms]
        return f"[{'/'.join(labels)}]"

    def _rank_text(self, account: R6ResolvedAccount) -> str:
        rank = str(account.current_rank or "").strip()
        if rank and rank.lower() != "unranked":
            return rank
        if account.ranked_ready:
            return "Ranked Ready"
        return ""

    def _peak_rank_text(self, account: R6ResolvedAccount) -> str:
        peak = str(account.peak_rank or "").strip()
        if not peak or peak.lower() == "unranked":
            return ""
        current = str(account.current_rank or "").strip()
        count = max(1, account.peak_rank_count)
        if peak == current and count <= 1:
            return ""
        if count > 1:
            return f"{count}x{peak}"
        return peak

    def _assemble(self, parts: list[str], max_length: int) -> str:
        final: list[str] = []
        current_length = 0
        sep = " | "
        sep_len = len(sep)

        for part in parts:
            if not part:
                continue
            part_len = len(part) + (sep_len if final else 0)
            if current_length + part_len > max_length:
                break
            final.append(part)
            current_length += part_len

        return sep.join(final)
