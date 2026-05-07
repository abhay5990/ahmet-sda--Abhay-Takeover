"""Resolved-model title generation for League of Legends listings."""

from __future__ import annotations

import re

from ..models import LolResolvedAccount


class LolTitleGenerator:
    """Generate marketplace titles from the resolved LOL account."""

    def generate(
        self,
        account: LolResolvedAccount,
        *,
        marketplace: str = "default",
        is_dropshipping: bool = False,
    ) -> str:
        if marketplace.lower() == "g2g":
            return self._build(account, max_length=120, is_dropshipping=is_dropshipping)
        return self._build(account, max_length=138, is_dropshipping=is_dropshipping)

    def _build(
        self,
        account: LolResolvedAccount,
        *,
        max_length: int,
        is_dropshipping: bool,
    ) -> str:
        region = _format_region(account.region)
        champion_str = _format_champion_count(account.champion_count)
        be_str = f"{account.blue_essence} BE" if account.blue_essence > 5000 else ""
        oe_str = f"{account.orange_essence} OE" if account.orange_essence > 3000 else ""
        rp_str = f"{account.riot_points} RP" if account.riot_points > 500 else ""

        parts = [
            region,
            account.rank or "UNRANKED",
            "Handmade",
            f"Level {account.level}" if account.level else "",
            f"{account.skin_count} Skins",
            champion_str,
            be_str,
            oe_str,
            rp_str,
            "Full Access",
        ]
        if not is_dropshipping:
            parts.append("Instant Delivery")

        return _assemble(parts, max_length=max_length)


# ------------------------------------------------------------------
# Module-level helpers
# ------------------------------------------------------------------

def _format_region(region: str) -> str:
    if not region or region == "UNKNOWN":
        return "UNKNOWN"
    return re.sub(r"\d+", "", region)


def _format_champion_count(count: int) -> str:
    if count >= 160:
        return "All Champs"
    if count > 90:
        return f"Nearly All Champs ({count})"
    return f"{count} Champions"


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
