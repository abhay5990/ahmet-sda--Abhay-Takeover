"""Resolved-model title generation for Roblox listings."""

from __future__ import annotations

from datetime import datetime, timezone

from ..models import RobloxResolvedAccount


class RobloxTitleGenerator:
    """Generate marketplace titles from the resolved Roblox account."""

    def generate(
        self,
        account: RobloxResolvedAccount,
        *,
        marketplace: str = "default",
    ) -> str:
        if marketplace.lower() == "gameboost":
            return self._build_gameboost(account)
        if marketplace.lower() in ("playerauctions", "player"):
            return self._build_playerauctions(account)
        return self._build_eldorado(account)

    def _build_eldorado(self, account: RobloxResolvedAccount) -> str:
        letter_tag = _letter_tag(account.username)
        year = _register_year(account.register_date)

        title = (
            f"{letter_tag}\u25c6 Registered: {year} \u25c6 "
            f"Total Spent: {account.incoming_robux_total} R$ \u25c6 "
            f"Inventory: {int(account.inventory_price)} R$ \u25c6 "
            f"{account.offsale_count} Offsale Items \u25c6 "
            f"Gamepass: {account.game_pass_total_robux} R$ \u25c6 "
            f"FULL ACCESS"
        )
        return title[:255]

    def _build_gameboost(self, account: RobloxResolvedAccount) -> str:
        letter_tag = _letter_tag(account.username)
        year = _register_year(account.register_date)

        title = (
            f"{letter_tag}Registered {year} | "
            f"Spent: {account.incoming_robux_total} R$ | "
            f"Inventory: {int(account.inventory_price)} R$ | "
            f"Full Access"
        )
        return title[:255]

    def _build_playerauctions(self, account: RobloxResolvedAccount) -> str:
        features: list[str] = []
        if account.username and len(account.username) in (3, 4):
            features.append(f"{len(account.username)} Letter")
        if account.incoming_robux_total > 0:
            features.append(f"{account.incoming_robux_total} R$ Spent")
        if account.inventory_price > 0:
            features.append(f"{int(account.inventory_price)} R$ Inv")
        if account.offsale_count > 0:
            features.append(f"{account.offsale_count} Offsale")

        features_str = " | ".join(features) if features else "Full Access Account"
        return f"Roblox Account - {features_str}"[:100]


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------

def _letter_tag(username: str) -> str:
    if username and len(username) == 3:
        return "3 Letter, "
    if username and len(username) == 4:
        return "4 Letter, "
    return ""


def _register_year(timestamp: int) -> str:
    try:
        return str(datetime.fromtimestamp(int(timestamp), tz=timezone.utc).year)
    except Exception:
        return "Unknown"
