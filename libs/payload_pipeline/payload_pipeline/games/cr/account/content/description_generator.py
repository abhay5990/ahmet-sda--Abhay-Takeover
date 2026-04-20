"""Resolved-model description generation for Clash Royale listings."""

from __future__ import annotations

from .....core.contracts import MediaBundle
from ..models import CrResolvedAccount


class CrDescriptionGenerator:
    """Generate marketplace descriptions from the resolved CR account."""

    def generate(
        self,
        account: CrResolvedAccount,
        *,
        media: MediaBundle,
        marketplace: str = "default",
        is_dropshipping: bool = False,
    ) -> str:
        lines = [
            "Clash Royale Account Details:",
            "---------------------------",
        ]

        # Tracker link
        if account.account_tracker_link:
            url = account.account_tracker_link.removeprefix("https://").removeprefix("http://")
            lines.append(f"Account Tracker Link:\n\t{url}")

        lines.extend([
            f"King Level: {account.king_level}",
            f"Current Trophies: {account.current_trophies}"
            + (f" (Peak: {account.peak_trophies})" if account.peak_trophies > account.current_trophies else ""),
            f"Arena: {account.arena_name}" if account.arena_name else "",
            f"Cards Unlocked: {account.cards_found}/125" if account.cards_found > 0 else "",
        ])

        # Win/loss stats
        if account.total_wins > 0 or account.total_losses > 0:
            win_loss = f"Wins: {account.total_wins} | Losses: {account.total_losses}"
            if account.win_rate > 0:
                win_loss += f" | Win Rate: {account.win_rate:.1f}%"
            lines.append(win_loss)

        if account.battle_pass_active:
            lines.append("Battle Pass: Active")

        # Bonus games
        bonus = self._bonus_games_text(account)
        if bonus:
            lines.extend(["", bonus])

        # Elite/max cards
        if account.elite_cards:
            lines.extend(["", f"Elite (Level 15+) -> {', '.join(account.elite_cards)}"])

        # Footer
        lines.extend([
            "",
            "Full Access",
            "",
            "Has Warranty",
        ])
        if not is_dropshipping:
            lines.extend(["", "Instant Delivery"])

        lines.extend([
            "",
            "Note: If the linked email is on Outlook, you must add your own security email after first login.",
            "Failure to do so may result in loss of access, and we won't be responsible.",
        ])

        # Filter empty lines
        description = "\n".join(line for line in lines if line is not None)

        if marketplace == "player":
            description = description.replace("\n", "<br>")

        if len(description) > 1900:
            description = description[:1897] + "..."

        return description

    @staticmethod
    def _bonus_games_text(account: CrResolvedAccount) -> str:
        games: list[str] = []
        if account.has_brawl_stars and account.brawl_stars_level > 0:
            bs = f"+ Brawl Stars: Level {account.brawl_stars_level}"
            if account.brawl_stars_trophies > 0:
                bs += f" | {account.brawl_stars_trophies} Trophies"
            if account.brawl_stars_tracker_link:
                link = account.brawl_stars_tracker_link.removeprefix("https://").removeprefix("http://")
                bs += f"\n\t{link}"
            games.append(bs)

        if account.has_coc and account.coc_th_level > 0:
            coc = f"+ Clash of Clans: Town Hall {account.coc_th_level}"
            if account.coc_trophies > 0:
                coc += f" | {account.coc_trophies} Trophies"
            if account.coc_tracker_link:
                link = account.coc_tracker_link.removeprefix("https://").removeprefix("http://")
                coc += f"\n\t{link}"
            games.append(coc)

        if games:
            return "[Bonus Games Included]\n" + "\n".join(games)
        return ""
