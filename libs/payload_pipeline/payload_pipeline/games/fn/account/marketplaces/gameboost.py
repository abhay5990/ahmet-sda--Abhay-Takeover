"""GameBoost builder for resolved Fortnite accounts."""

from __future__ import annotations

from typing import Any

from ..models import FortniteResolvedAccount
from .....core.contracts import BuildContext, ListingDraft
from .....marketplaces.gameboost import BaseGameBoostBuilder

_VALUABLE_ITEMS = [
    "Renegade Raider", "OG Ghoul Trooper", "OG Skull Trooper", "Aerial Assault Trooper",
    "Wildcat", "Wonder", "Black Knight", "Honor Guard", "IKONIK", "Travis Scott",
    "Galaxy", "Sparkle Specialist", "Royale Knight", "The Reaper", "Elite Agent",
    "Blue Squire", "Omega", "Lara Croft",
    "Leviathan Axe", "Merry Mint Axe", "Raider's Revenge",
    "Floss", "Take The L",
    "Mako",
]


class FortniteGameBoostBuilder(BaseGameBoostBuilder):
    """Build GameBoost payloads for the Fortnite account slice."""

    @property
    def game_slug(self) -> str:
        return "fortnite"

    @property
    def _platform_name(self) -> str:
        return "Epic Games Account"

    def _build_account_data(self, account: FortniteResolvedAccount) -> dict[str, Any]:
        other_count = (
            (account.skin_count + account.pickaxe_count + account.glider_count + account.dance_count) // 4
            if (account.skin_count + account.pickaxe_count + account.glider_count + account.dance_count)
            else 0
        )

        platforms = ["PC"]
        if account.psn_linkable:
            platforms.append("PlayStation")
        if account.xbox_linkable:
            platforms.append("Xbox")

        return {
            "platform": "PC",
            "linkable_platforms": platforms,
            "account_tags": ["OG Account"],
            "outfits_count": account.skin_count,
            "emotes_count": account.dance_count,
            "pickaxes_count": account.pickaxe_count,
            "backblings_count": other_count,
            "gliders_count": account.glider_count,
            "wraps_count": other_count,
            "loadings_count": other_count,
            "sprays_count": other_count,
            "account_level": account.level,
            "v_bucks_count": account.v_bucks,
        }

    def _build_dump(self, account: FortniteResolvedAccount) -> str | None:
        return self._generate_tags(account)

    def build_payload(
        self,
        subject: Any,
        listing: ListingDraft,
        ctx: BuildContext,
    ) -> dict[str, Any]:
        # Custom description trimming before base builds payload
        content = listing.content_for(self.marketplace)
        desc = content.description
        if "Full Access" in desc:
            for i, line in enumerate(desc.splitlines()):
                if "Full Access" in line:
                    desc = "\n".join(desc.splitlines()[i:]).strip()
                    break
        # Temporarily patch description for base builder
        original_desc = content.description
        content.description = desc

        payload = super().build_payload(subject, listing, ctx)

        # Restore original description
        content.description = original_desc

        # Custom price formatting: round down to int, then add .99
        payload["price"] = int(payload["price"]) + 0.99
        return payload

    # ------------------------------------------------------------------
    # Game-specific helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _generate_tags(account: FortniteResolvedAccount) -> str:
        titles_lower = {t.lower(): t for t in account.cosmetic_titles}

        valuable = [v for v in _VALUABLE_ITEMS if v.lower() in titles_lower]
        rest = [t for t in account.cosmetic_titles if t not in valuable]
        rest = [t.translate(str.maketrans("\u0131\u0130", "ii")) for t in rest]

        all_tags, total = valuable + rest, 0
        final: list[str] = []
        for tag in all_tags:
            length = len(tag) + (2 if final else 0)
            if total + length > 2000:
                break
            final.append(tag)
            total += length
        return ", ".join(final)
