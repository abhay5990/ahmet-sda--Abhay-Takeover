"""GameBoost builder for resolved Clash Royale accounts."""

from __future__ import annotations

import re
from typing import Any

from ..models import CrResolvedAccount
from .....core.contracts import BuildContext, ListingDraft
from .....marketplaces.gameboost import BaseGameBoostBuilder


_DEFAULT_IMAGE_URL = (
    "https://www.dropbox.com/scl/fi/a7ihoudpz8aznxpmuhzmc/"
    "unnamed.webp?rlkey=qhek3zth6179rbs0hzy3z72p9&e=1&st=vzfs10as&dl=1"
)


class CrGameBoostBuilder(BaseGameBoostBuilder):
    """Build GameBoost payloads for the Clash Royale account slice."""

    @property
    def game_slug(self) -> str:
        return "clash-royale"

    @property
    def _platform_name(self) -> str:
        return "Supercell ID"

    def _build_account_data(self, account: CrResolvedAccount, ctx=None) -> dict[str, Any]:
        return {
            "arena_level": self._extract_arena_level(account.arena_name),
            "king_tower_level": account.king_level,
            "gems_count": 0,
            "trophies_count": account.current_trophies,
            "max_cards_count": account.max_cards_count,
            "emotes_count": 0,
            "gold_count": 0,
            "best_trophies_count": account.peak_trophies,
            "evolution_count": account.evolution_count,
            "unlocked_cards_count": account.cards_found,
            "account_level": account.account_level,
        }

    def _build_dump(self, account: CrResolvedAccount) -> str | None:
        return self._generate_tags(account)

    def build_payload(
        self,
        subject: Any,
        listing: ListingDraft,
        ctx: BuildContext,
    ) -> dict[str, Any]:
        payload = super().build_payload(subject, listing, ctx)
        if not payload["image_urls"]:
            payload["image_urls"] = [_DEFAULT_IMAGE_URL]
        return payload

    # ------------------------------------------------------------------
    # Game-specific helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _extract_arena_level(arena_name: str) -> int:
        if not arena_name:
            return 0

        numbers = re.findall(r"\d+", arena_name)
        if numbers:
            return int(numbers[0])

        arena_mapping = {
            "Training Camp": 0,
            "Goblin Stadium": 1,
            "Bone Pit": 2,
            "Barbarian Bowl": 3,
            "Spell Valley": 4,
            "Builder's Workshop": 5,
            "P.E.K.K.A's Playhouse": 6,
            "Royal Arena": 7,
            "Frozen Peak": 8,
            "Jungle Arena": 9,
            "Hog Mountain": 10,
            "Electro Valley": 11,
            "Spooky Town": 12,
            "Rascal's Hideout": 13,
            "Serenity Peak": 14,
            "Miner's Mine": 15,
            "Executioner's Kitchen": 16,
            "Royal Crypt": 17,
            "Silent Sanctuary": 18,
            "Dragon Spa": 19,
            "Boot Camp": 20,
            "Clash Fest": 21,
            "PANCAKES!": 22,
            "Valkalla": 23,
            "Legendary Arena": 24,
            "Lumberlove Cabin": 23,
        }
        return arena_mapping.get(arena_name, 0)

    @staticmethod
    def _generate_tags(account: CrResolvedAccount) -> str:
        tags = [
            f"King Level {account.king_level}",
            f"{account.current_trophies} Trophies",
            account.arena_name,
            f"{account.cards_found} Cards Unlocked",
            f"{account.total_wins} Wins",
        ]

        if account.current_trophies >= 5000:
            tags.append("Master League")
        elif account.current_trophies >= 4000:
            tags.append("Challenger")
        elif account.current_trophies >= 3000:
            tags.append("Arena 10+")

        if account.battle_pass_active:
            tags.append("Battle Pass Active")
        if account.has_brawl_stars:
            tags.append(f"Brawl Stars Level {account.brawl_stars_level}")
        if account.has_coc:
            tags.append(f"Clash of Clans TH{account.coc_th_level}")

        tags.extend(
            [
                "Full Access",
                "Instant Delivery",
                "Mail Changeable",
                "Supercell Account",
            ]
        )

        final_tags: list[str] = []
        total_length = 0
        for tag in tags:
            cleaned = str(tag).translate(str.maketrans("\u0131\u0130", "ii"))
            item_length = len(cleaned) + (2 if final_tags else 0)
            if total_length + item_length > 2000:
                break
            final_tags.append(cleaned)
            total_length += item_length
        return ", ".join(final_tags)
