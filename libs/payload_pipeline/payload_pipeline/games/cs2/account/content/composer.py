"""Listing composition for resolved CS2 accounts."""

from __future__ import annotations

from ..models import CS2ResolvedAccount, RANK_ID_MAP
from .....core.contracts import (
    ListingContent,
    ListingDraft,
    MarketplaceListingOverride,
    MediaBundle,
    PipelineRequest,
)

IMPORTANT_MEDALS = {
    "10 Year Veteran Coin", "5 Year Veteran Coin", "10 Year Birthday Coin",
    "Loyalty Badge", "Global Offensive Badge",
}

IMPORTANT_GAMES = {
    "cs2 prime", "rust", "gta", "escape from tarkov", "elden ring",
    "red dead redemption 2", "baldur's gate 3", "god of war",
    "assassin's creed valhalla", "monster hunter", "dune: awakening",
    "ark: survival evolved", "call of duty", "dayz", "dead by daylight",
    "the forest", "sons of the forest", "team fortress 2", "dota 2",
}


class CS2Composer:
    """Generate listing text from the resolved CS2 account."""

    def compose(
        self,
        account: CS2ResolvedAccount,
        request: PipelineRequest,
        media: MediaBundle,
    ) -> ListingDraft:
        if account.manual_title:
            return ListingDraft(
                default=ListingContent(
                    title=account.manual_title[:160],
                    description=account.manual_description or "",
                    tags=["cs2", "counter-strike-2", "account"],
                ),
                media=media,
                marketplace_overrides={
                    "g2g": MarketplaceListingOverride(title=account.manual_title[:120]),
                },
            )

        title = self._build_title(account, max_length=160)
        g2g_title = self._build_title(account, max_length=120)
        description = self._build_description(account, media)

        return ListingDraft(
            default=ListingContent(
                title=title,
                description=description,
                tags=["cs2", "counter-strike-2", "account"],
            ),
            media=media,
            marketplace_overrides={
                "g2g": MarketplaceListingOverride(title=g2g_title),
            },
        )

    # ------------------------------------------------------------------
    # Title
    # ------------------------------------------------------------------

    def _build_title(self, account: CS2ResolvedAccount, max_length: int) -> str:
        parts: list[str] = ["[CS2]"]

        # Prime status
        parts.append("Prime" if account.is_prime else "No Prime")

        # Hours
        if account.cs2_hours > 0:
            parts.append(f"{account.cs2_hours} Hours")

        # Medals
        if account.medal_count > 0:
            medal_detail = self._medal_summary(account.medal_names, limit=3)
            if medal_detail:
                parts.append(f"{account.medal_count} Medals ({medal_detail})")
            else:
                parts.append(f"{account.medal_count} Medals")

        # Veteran coin highlight (if not already in medal summary)
        veteran = self._find_veteran_coin(account.medal_names)
        if veteran:
            parts.append(veteran)

        # Full Access always last
        access_suffix = " / Full Access"
        core = " / ".join(parts)
        allowed = max_length - len(access_suffix)

        if len(core) > allowed:
            core = core[:allowed].rsplit(" ", 1)[0].rstrip(" /")

        return f"{core}{access_suffix}"

    def _medal_summary(self, medal_names: list[str], limit: int) -> str:
        if not medal_names:
            return ""
        # Important first, then the rest
        important = [m for m in medal_names if m in IMPORTANT_MEDALS]
        others = [m for m in medal_names if m not in IMPORTANT_MEDALS]
        selected = (important + others)[:limit]
        return ", ".join(selected)

    def _find_veteran_coin(self, medal_names: list[str]) -> str:
        for name in medal_names:
            low = name.lower()
            if "10 year" in low:
                return "10 Year Coin"
            if "5 year" in low:
                return "5 Year Coin"
        return ""

    # ------------------------------------------------------------------
    # Description
    # ------------------------------------------------------------------

    def _build_description(
        self, account: CS2ResolvedAccount, media: MediaBundle,
    ) -> str:
        lines: list[str] = []
        add = lines.append

        add("COUNTER STRIKE 2 ACCOUNT\n")
        add("This Account includes:\n")

        # Prime
        add(f"Prime Status: {'YES' if account.is_prime else 'NO'}")

        # Medals
        if account.medal_names:
            add("\nMedals:")
            for name in account.medal_names:
                add(f"  - {name}")
            add("")
        elif account.medal_count > 0:
            add(f"Medals: {account.medal_count}")

        # Hours
        if account.cs2_hours > 0:
            add(f"CS2 Hours: {account.cs2_hours:,}")

        # Ranks
        rank_name = account.rank_name or "Unranked"
        add(f"Competitive Rank: {rank_name}")

        if account.premier_elo:
            add(f"Premier ELO: {account.premier_elo}")
        else:
            add("Premier ELO: Not Ranked")

        wingman = account.wingman_rank_name
        if wingman:
            add(f"Wingman Rank: {wingman}")

        # Steam profile
        if account.steam_level:
            add(f"\nSteam Level: {account.steam_level}")
        if account.country:
            add(f"Steam Country: {account.country}")

        # FaceIT
        if not account.has_faceit:
            add("FaceIT: Not Linked (Linkable)")

        # Games
        game_lines = self._format_games(account)
        if game_lines:
            lines.extend(game_lines)

        # Bans / warnings
        if account.has_vac_ban:
            add("\n[WARNING] CS2 VAC Ban: ACTIVE")
        if account.market_banned:
            add("\n[WARNING] Steam Market: BANNED")

        # Footer
        add("\n[FULL ACCESS GUARANTEED]")
        add("Instant Delivery")

        # Album link
        if media.album_url:
            add(f"\nAlbum: {media.album_url}")

        return "\n".join(lines)[:2000].strip()

    def _format_games(self, account: CS2ResolvedAccount) -> list[str]:
        titles = account.game_titles
        if not titles:
            return []

        # Filter important games
        important = [
            t for t in titles
            if any(key in t.lower() for key in IMPORTANT_GAMES)
        ]

        if important:
            selected = important[:5]
        else:
            # Top 5 by playtime (already sorted)
            selected = titles[:5]

        lines = [f"\nExtra Games ({account.game_count} total):"]
        for title in selected:
            lines.append(f"  - {title}")
        return lines
