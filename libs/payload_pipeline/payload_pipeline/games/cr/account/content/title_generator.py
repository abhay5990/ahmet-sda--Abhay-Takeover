"""Resolved-model title generation for Clash Royale listings."""

from __future__ import annotations

from ..models import CrResolvedAccount


class CrTitleGenerator:
    """Generate marketplace titles from the resolved CR account."""

    def generate(
        self,
        account: CrResolvedAccount,
        *,
        marketplace: str = "default",
    ) -> str:
        if marketplace.lower() == "g2g":
            return self._build(account, max_length=120, include_suffix=False)
        max_length = 150 if marketplace.lower() == "eldorado" else 140
        return self._build(account, max_length=max_length, include_suffix=True)

    def _build(
        self,
        account: CrResolvedAccount,
        *,
        max_length: int,
        include_suffix: bool,
    ) -> str:
        parts: list[str] = []

        if account.king_level > 0:
            parts.append(f"[KT{account.king_level}]")
        if account.account_level > 0:
            parts.append(f"Level {account.account_level}")
        if account.current_trophies > 0:
            parts.append(f"{account.current_trophies} Trophies")
        if account.arena_name:
            parts.append(account.arena_name)
        if account.cards_found > 0:
            parts.append(f"{account.cards_found}/125 Cards")
        if account.total_wins > 0:
            parts.append(f"{account.total_wins} Wins")
        if account.battle_pass_active:
            parts.append("Battle Pass")

        # Bonus games
        if account.has_brawl_stars and account.brawl_stars_level > 0:
            parts.append(f"BS Lv.{account.brawl_stars_level}")
        if account.has_coc and account.coc_th_level > 0:
            parts.append(f"CoC TH{account.coc_th_level}")

        # Card info
        if account.level_15_cards_count > 0:
            parts.append(f"{account.level_15_cards_count} Elite")
        if account.level_14_cards_count > 0:
            parts.append(f"{account.level_14_cards_count} Max")

        parts.append("Full Access")

        return _assemble(parts, max_length=max_length, include_suffix=include_suffix)


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------

def _assemble(parts: list[str], *, max_length: int, include_suffix: bool) -> str:
    separator = " | "
    suffix = "S4G" if include_suffix else ""
    reserved = (len(suffix) + len(separator)) if suffix else 0

    built: list[str] = []
    current_length = 0
    for part in parts:
        if not part:
            continue
        item_len = len(part) + (len(separator) if built else 0)
        if current_length + item_len > max_length - reserved:
            break
        built.append(part)
        current_length += item_len

    if suffix:
        built.append(suffix)
    return separator.join(built)
