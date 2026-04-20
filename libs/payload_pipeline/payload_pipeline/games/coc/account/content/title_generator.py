"""Resolved-model title generation for Clash of Clans listings."""

from __future__ import annotations

from ..models import CocResolvedAccount


class CocTitleGenerator:
    """Generate marketplace titles from the resolved CoC account."""

    def generate(
        self,
        account: CocResolvedAccount,
        *,
        marketplace: str = "default",
    ) -> str:
        if marketplace.lower() == "g2g":
            return self._build(account, max_length=120, include_suffix=False)
        return self._build(account, max_length=140, include_suffix=True)

    def _build(
        self,
        account: CocResolvedAccount,
        *,
        max_length: int,
        include_suffix: bool,
    ) -> str:
        parts: list[str] = []

        if account.town_hall_level > 0:
            parts.append(f"[TH{account.town_hall_level}]")
        if account.builder_hall_level > 0:
            parts.append(f"BH{account.builder_hall_level}")
        if account.account_level > 0:
            parts.append(f"Lvl {account.account_level}")
        if account.trophies > 0:
            parts.append(f"{account.trophies} Trophies")

        # Hero levels (BK-AQ-GW-RC)
        hero_str = _format_heroes(account)
        if hero_str:
            parts.append(hero_str)

        if account.total_troops_level > 0:
            parts.append(f"Troops(TL {account.total_troops_level})")
        if account.war_stars > 0:
            parts.append(f"{account.war_stars} War Stars")

        return _assemble(parts, max_length=max_length, include_suffix=include_suffix)


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------

def _format_heroes(account: CocResolvedAccount) -> str:
    levels = [
        account.barbarian_king_level,
        account.archer_queen_level,
        account.grand_warden_level,
        account.royal_champion_level,
    ]
    if any(lvl > 0 for lvl in levels):
        return f"Heroes({'-'.join(str(l) for l in levels)})"
    if account.total_heroes_level > 0:
        return f"Heroes(TL {account.total_heroes_level})"
    return ""


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
