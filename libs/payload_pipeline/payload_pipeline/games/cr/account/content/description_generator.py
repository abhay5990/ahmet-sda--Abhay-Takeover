"""Resolved-model description generation for Clash Royale listings."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from .....core.contracts import MediaBundle
from ..models import CrResolvedAccount

logger = logging.getLogger(__name__)

_RESOURCES_DIR = Path(__file__).resolve().parent.parent / "resources"
_DEFAULT_SPELLS_PATH = _RESOURCES_DIR / "spells_data.json"

_PREMIUM_RARITIES = ("Champion", "Legendary", "Epic")

_spells_rarity_cache: dict[str, str] | None = None


def _load_spells_rarity() -> dict[str, str]:
    """Return card_id (str) → rarity mapping from spells_data.json."""
    global _spells_rarity_cache
    if _spells_rarity_cache is not None:
        return _spells_rarity_cache
    try:
        spells = json.loads(_DEFAULT_SPELLS_PATH.read_text(encoding="utf-8"))
        result = {
            str(spell["id"]): str(spell.get("rarity", ""))
            for spell in spells
            if isinstance(spell, dict) and "id" in spell
        }
        _spells_rarity_cache = result
        return result
    except Exception as exc:
        logger.warning("CR description: failed to load spells rarity data: %s", exc)
        _spells_rarity_cache = {}
        return {}


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

        # Core stats
        lines.extend([
            f"King Level: {account.king_level}",
            f"Current Trophies: {account.current_trophies}"
            + (f" (Peak: {account.peak_trophies})" if account.peak_trophies > account.current_trophies else ""),
            f"Arena: {account.arena_name}" if account.arena_name else "",
        ])

        if account.cards_found > 0:
            pct = account.cards_found / 125 * 100
            lines.append(f"Cards Unlocked: {account.cards_found}/125 ({pct:.1f}% complete)")

        # Win/loss stats
        if account.total_wins > 0 or account.total_losses > 0:
            win_loss = f"Wins: {account.total_wins} | Losses: {account.total_losses}"
            if account.win_rate > 0:
                win_loss += f" | Win Rate: {account.win_rate:.1f}%"
            lines.append(win_loss)

        # Evolution + level 14/15 counts
        card_stat_parts: list[str] = []
        if account.evolution_count > 0:
            card_stat_parts.append(f"Evolutions: {account.evolution_count}")
        if account.level_15_cards_count > 0:
            card_stat_parts.append(f"Level 15: {account.level_15_cards_count}")
        if account.level_14_cards_count > 0:
            card_stat_parts.append(f"Level 14: {account.level_14_cards_count}")
        if card_stat_parts:
            lines.append(" | ".join(card_stat_parts))

        if account.battle_pass_active:
            lines.append("Battle Pass: Active")

        # Bonus games
        bonus = self._bonus_games_text(account)
        if bonus:
            lines.extend(["", bonus])

        # Elite cards
        if account.elite_cards:
            lines.extend(["", f"Elite (Level 15+) -> {', '.join(account.elite_cards)}"])

        # Champion / Legendary / Epic card listing
        premium = _premium_cards_section(account.cards_data)
        if premium:
            lines.append(premium)

        # Footer
        lines.extend([
            "",
            "Full Access",
            "",
            "Has Warranty",
        ])
        if not is_dropshipping:
            lines.extend(["", "Instant Delivery"])


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


def _premium_cards_section(cards_data: dict[str, dict[str, Any]]) -> str:
    """Build Champion / Legendary / Epic card lines from cards_data."""
    if not cards_data:
        return ""

    rarity_map = _load_spells_rarity()
    if not rarity_map:
        return ""

    buckets: dict[str, list[str]] = {r: [] for r in _PREMIUM_RARITIES}
    for card_id, info in cards_data.items():
        rarity = rarity_map.get(str(card_id), "")
        if rarity in buckets and isinstance(info, dict):
            name = str(info.get("name") or "").strip()
            if name:
                buckets[rarity].append(name)

    lines: list[str] = []
    for rarity in _PREMIUM_RARITIES:
        if buckets[rarity]:
            lines.append(f"{rarity} -> {', '.join(buckets[rarity])}")

    return ("\n" + "\n".join(lines)) if lines else ""
