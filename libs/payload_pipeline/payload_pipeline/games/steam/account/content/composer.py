"""Listing composition for resolved Steam accounts."""

from __future__ import annotations

from datetime import datetime, timezone

from ..models import SteamResolvedAccount
from .....core.contracts import (
    ListingContent,
    ListingDraft,
    MarketplaceListingOverride,
    MediaBundle,
    PipelineRequest,
)

_IMPORTANT_GAMES = [
    "cs2 prime", "rust", "gta", "escape from tarkov", "elden ring",
    "red dead redemption 2", "baldur's gate 3", "god of war",
    "assassin's creed valhalla", "monster hunter", "dune: awakening",
    "ark: survival evolved", "call of duty: modern warfare ii",
    "call of duty warzone", "dayz", "dead by daylight",
    "the forest", "sons of the forest", "team fortress 2",
]

_CS2_RANKS: dict[int, str] = {
    0: "Unranked", 1: "Silver I", 2: "Silver II", 3: "Silver III",
    4: "Silver IV", 5: "Silver Elite", 6: "Silver Elite Master",
    7: "Gold Nova I", 8: "Gold Nova II", 9: "Gold Nova III",
    10: "Gold Nova Master", 11: "Master Guardian I", 12: "Master Guardian II",
    13: "Master Guardian Elite", 14: "Distinguished Master Guardian",
    15: "Legendary Eagle", 16: "Legendary Eagle Master",
    17: "Supreme Master First Class", 18: "Global Elite",
}


class SteamComposer:
    """Generate listing text from the resolved Steam account."""

    def compose(
        self,
        account: SteamResolvedAccount,
        request: PipelineRequest,
        media: MediaBundle,
    ) -> ListingDraft:
        if account.manual_title:
            return ListingDraft(
                default=ListingContent(
                    title=account.manual_title,
                    description=account.manual_description,
                    tags=["steam", "account"],
                ),
                media=media,
                marketplace_overrides={},
            )

        title = self._build_title(account, max_length=160, include_footer=True)
        g2g_title = self._build_title(account, max_length=120, include_footer=False)
        description = self._build_description(account, media)

        return ListingDraft(
            default=ListingContent(
                title=title,
                description=description,
                tags=["steam", "account"],
            ),
            media=media,
            marketplace_overrides={
                "g2g": MarketplaceListingOverride(title=g2g_title),
            },
        )

    def _build_title(
        self,
        account: SteamResolvedAccount,
        max_length: int,
        include_footer: bool,
    ) -> str:
        sorted_games = sorted(
            account.games, key=lambda g: g.get("playtime_forever", 0), reverse=True
        )

        selected: list[str] = []
        over_2000: str | None = None

        for game in account.games:
            title = game.get("title", "")
            playtime = game.get("playtime_forever", 0)
            title_lower = title.lower()

            if playtime >= 2000 and not over_2000:
                over_2000 = f"{title} - {int(playtime)} hrs"

            if any(kw in title_lower for kw in _IMPORTANT_GAMES):
                selected.append(f"{title} - {int(playtime)} hrs")

        top_played = [
            f"{g.get('title', '')} - {int(g.get('playtime_forever', 0))} hrs"
            for g in sorted_games
            if f"{g.get('title', '')} - {int(g.get('playtime_forever', 0))} hrs" not in selected
        ]

        parts = [f"[STEAM] {account.total_games} Games"]

        game_str = ""
        for entry in selected + top_played:
            temp = f"{game_str} | {entry}" if game_str else entry
            candidate = " | ".join(parts + [temp])
            if len(candidate) <= max_length:
                game_str = temp
            else:
                break

        if game_str:
            parts.append(game_str)

        if account.register_date:
            year = datetime.fromtimestamp(account.register_date, tz=timezone.utc).year
            if datetime.now(tz=timezone.utc).year - year >= 10:
                parts.append(f"Registered: {year}")

        if over_2000 and over_2000 not in game_str:
            parts.append(over_2000)

        result = " | ".join(parts)
        if len(result) > max_length:
            result = result[:max_length].rsplit(" | ", 1)[0]
        return result

    def _build_description(
        self,
        account: SteamResolvedAccount,
        media: MediaBundle,
    ) -> str:
        lines: list[str] = []

        if account.steam_level:
            lines.append(f"Steam Level: {account.steam_level}")
        if account.register_date:
            year = datetime.fromtimestamp(account.register_date, tz=timezone.utc).year
            lines.append(f"Registered: {year}")
        if account.country:
            lines.append(f"Country: {account.country.title()}")
        lines.append(f"Email Access: {'Yes' if account.has_email_access else 'No'}")
        if account.is_limited:
            lines.append("Limited Account: Yes")

        sorted_games = sorted(
            account.games, key=lambda g: g.get("playtime_forever", 0), reverse=True
        )
        if sorted_games:
            lines.append("")
            lines.append("Games:")
            for game in sorted_games[:15]:
                title = game.get("title", "")
                if not title:
                    continue
                playtime = int(game.get("playtime_forever", 0))
                time_str = f"{playtime} hrs" if playtime > 0 else "Fresh"
                lines.append(f"{title} - {time_str}")
            if len(sorted_games) > 15:
                lines.append(f"... and {len(sorted_games) - 15} more games")

        has_cs2 = any(g.get("appid") == 730 for g in account.games)
        if has_cs2:
            lines.append("")
            lines.append("CS2 Info:")
            if account.cs2_profile_rank:
                lines.append(f"Level: {account.cs2_profile_rank}")
            if account.cs2_win_count:
                lines.append(f"Wins: {account.cs2_win_count}")
            rank_name = _CS2_RANKS.get(account.cs2_rank_id, "Not Available")
            lines.append(f"Rank: {rank_name}")

        has_dota2 = any(g.get("appid") == 570 for g in account.games)
        if has_dota2 and (account.dota2_mmr or account.dota2_win_count or account.dota2_lose_count):
            lines.append("")
            lines.append("Dota 2 Info:")
            if account.dota2_mmr:
                lines.append(f"MMR: {account.dota2_mmr}")
            if account.dota2_win_count or account.dota2_lose_count:
                lines.append(f"W/L: {account.dota2_win_count}/{account.dota2_lose_count}")

        has_rust = any(g.get("appid") == 252490 for g in account.games)
        if has_rust and (account.rust_kills or account.rust_deaths):
            lines.append("")
            lines.append("Rust Info:")
            lines.append(f"Kills: {account.rust_kills}")
            lines.append(f"Deaths: {account.rust_deaths}")

        if account.market_ban_end_date:
            try:
                dt = datetime.fromtimestamp(
                    account.market_ban_end_date, tz=timezone.utc
                ).strftime("%Y-%m-%d")
                lines.append(f"\nSteam Market Banned Until: {dt}")
            except Exception:
                pass

        if media.album_url:
            lines.append(f"\nAlbum: {media.album_url}")

        description = "\n".join(lines)
        if len(description) > 2000:
            description = description[:2000].rsplit("\n", 1)[0]
        return description
