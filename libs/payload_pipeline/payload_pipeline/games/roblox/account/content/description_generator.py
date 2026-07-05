"""Resolved-model description generation for Roblox listings."""

from __future__ import annotations

from datetime import datetime, timezone

from .....core.contracts import MediaBundle
from ..models import RobloxResolvedAccount


class RobloxDescriptionGenerator:
    """Generate marketplace descriptions from the resolved Roblox account."""

    def generate(
        self,
        account: RobloxResolvedAccount,
        *,
        media: MediaBundle,
        marketplace: str = "default",
        is_dropshipping: bool = False,
    ) -> str:
        register_date = _format_register_date(account.register_date)
        profile_url = f"www.roblox.com/users/{account.roblox_id}/profile" if account.roblox_id else "N/A"

        instant_delivery = "\n\U0001f538\u2728 INSTANT DELIVERY\n" if not is_dropshipping else ""

        description = (
            f"\U0001f539 Username: {account.username or 'Unknown'}\n"
            f"{instant_delivery}"
            f"\U0001f539 Profile: {profile_url}\n"
            f"\n"
            f"\U0001f538 Account Details:\n"
            f"\U0001f539 Registered: {register_date}\n"
            f"\U0001f539 Robux: {account.robux}\n"
            f"\U0001f539 Total Robux Spent: {account.incoming_robux_total} R$\n"
            f"\U0001f539 Inventory Value (Classic): {int(account.inventory_price)} R$\n"
            f"\U0001f539 UGC Limited Value: {int(account.ugc_limited_price)} R$\n"
            f"\U0001f539 Gamepass Total: {account.game_pass_total_robux} R$\n"
            f"\U0001f539 Offsale Items: {account.offsale_count}\n"
            f"\U0001f539 Age Verified: {'Yes' if account.age_verified else 'No'}"
        )

        return description[:2000]


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------

def _format_register_date(timestamp: int) -> str:
    try:
        return datetime.fromtimestamp(int(timestamp), tz=timezone.utc).strftime("%Y-%m-%d")
    except Exception:
        return "Unknown"
