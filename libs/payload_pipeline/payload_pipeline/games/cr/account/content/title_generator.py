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
            return self._build(account, max_length=120)
        max_length = 150 if marketplace.lower() == "eldorado" else 140
        return self._build(account, max_length=max_length)

    def _build(
        self,
        account: CrResolvedAccount,
        *,
        max_length: int,
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
        if account.evolution_count > 0:
            parts.append(f"{account.evolution_count} Evolutions")
        if account.level_15_cards_count > 0:
            parts.append(f"{account.level_15_cards_count} Elite")
        if account.level_14_cards_count > 0:
            parts.append(f"{account.level_14_cards_count} Max")

        parts.append("Full Access")

        return _assemble(parts, max_length=max_length)


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------

def _assemble(parts: list[str], *, max_length: int) -> str:
    separator = " | "

    built: list[str] = []
    current_length = 0
    for part in parts:
        if not part:
            continue
        item_len = len(part) + (len(separator) if built else 0)
        if current_length + item_len > max_length:
            break
        built.append(part)
        current_length += item_len

    return separator.join(built)
