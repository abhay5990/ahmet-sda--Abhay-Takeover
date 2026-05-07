"""Resolved-model title generation for Valorant listings."""

from __future__ import annotations

from ..models import ValorantResolvedAccount


VALUABLE_SKINS = [
    "Champions 2021 Karambit", "Champions 2021 Vandal", "Arcane Sheriff",
    "Champions 2022 Butterfly Knife", "Champions 2022 Phantom", "Ignite Fan",
    "VCT LOCK//IN Misericórdia", "Ruin Dagger", "Champions 2023 Kunai",
    "Champions 2023 Vandal", "Kuronami no Yaiba", "Power Fist",
    "Reaver Karambit", "Reaver Knife", "RGX 11z Pro Firefly",
    "RGX 11z Pro Blade", "Glitchpop Dagger", "Glitchpop Axe",
    "Prime//2.0 Karambit", "Ion Karambit", "Prime Axe",
    "Black.Market Butterfly Knife", "Xenohunter Knife", "Singularity Knife",
    "Araxys Bio Harvester", "Blade of the Ruined King", "XERØFANG Knife",
    "Neo Frontier Axe", "Magepunk Sparkswitch", "Gaia's Wrath",
    "Sovereign Sword", "Gaia's Fury", "Relic Stone Daggers",
    "Onimaru Kunitsuna", "Elderflame Dagger", "Overdrive Blade",
    "Recon Balisong", "Magepunk Electroblade", "Oni Claw",
    "Forsaken Ritual Blade", "Blade of Chaos", "Soulstrife Scythe",
    "Terminus A Quo", "BlastX Polymer KnifeTech Coated Knife",
    "Origin Crescent Blade", "Winterwunderland Candy Cane", "Prism III Axe",
    "Equilibrium", "K/TAC Blade", "Hivemind Sword",
    "RGX 11z Pro Vandal", "Prime Vandal", "Glitchpop Vandal",
    "Reaver Vandal", "Elderflame Vandal", "Gaia's Vengeance Vandal",
    "Araxys Vandal", "ChronoVoid Vandal", "Ion Vandal", "Forsaken Vandal",
    "Oni Vandal", "Sentinels of Light Vandal", "Prelude to Chaos Vandal",
    "XERØFANG Vandal", "Origin Vandal", "Kuronami Vandal", "Neptune Vandal",
    "Overdrive Vandal", "Valiant Hero Vandal", "Black.Market Vandal",
    "Magepunk Vandal", "Ruin Vandal", "Valorant GO! Vol. 2 Vandal",
    "Radiant Entertainment System Phantom", "Spectrum Phantom",
    "Protocol 781-A Phantom", "Radiant Crisis 001 Phantom", "Oni Phantom",
    "Ruination Phantom", "Reaver Phantom", "RGX 11z Pro Phantom",
    "Singularity Phantom", "Neo Frontier Phantom", "Prime//2.0 Phantom",
    "Ion Phantom", "Sentinels of Light Phantom", "Recon Phantom",
    "Magepunk Phantom", "Gaia's Vengeance Phantom", "Glitchpop Phantom",
    "BlastX Phantom", "ChronoVoid Phantom",
    "Elderflame Operator", "Forsaken Operator", "Ion Operator",
    "RGX 11z Pro Operator", "Reaver Operator", "Araxys Operator",
    "Spline Operator", "Origin Operator", "Sentinels of Light Operator",
    "Cryostasis Operator", "VALORANT GO! Vol. 2 Operator", "Magepunk Operator",
    "Radiant Entertainment System Operator", "Imperium Operator",
    "Ruination Spectre", "Ion Spectre", "Kuronami Spectre", "Reaver Spectre",
    "Sentinels of Light Spectre", "Magepunk Spectre", "RGX 11z Pro Spectre",
    "BlastX Spectre", "Spline Spectre", "Forsaken Spectre",
    "Singularity Spectre", "VALORANT GO! Vol. 1 Spectre",
    "Neo Frontier Sheriff", "Kuronami Sheriff", "Singularity Sheriff",
    "Protocol 781-A Sheriff", "Reaver Sheriff", "Ion Sheriff",
    "Magepunk Sheriff", "Sentinels of Light Sheriff", "ChronoVoid Sheriff",
    "Overdrive Sheriff", "Imperium Sheriff",
    "Ruination Ghost", "Sovereign Ghost", "Reaver Ghost",
    "Gaia's Vengeance Ghost", "XERØFANG Ghost", "Magepunk Ghost",
    "Valiant Hero Ghost", "Radiant Entertainment System Ghost",
    "VALORANT GO! Vol. 1 Ghost", "Recon Ghost",
    "RGX 11z Pro Classic", "Prime Classic", "Forsaken Classic",
    "Spectrum Classic", "Radiant Crisis 001 Classic", "Glitchpop Classic",
    "Gravitational Uranium Neuroblaster Classic",
    "Neo Frontier Marshal", "Gaia's Vengeance Marshal", "Kuronami Marshal",
    "Sovereign Marshal", "Black.Market Marshal", "Magepunk Marshal",
    "Prime//2.0 Frenzy", "Ion Frenzy", "Origin Frenzy", "Xenohunter Frenzy",
    "Elderflame Frenzy", "Oni Frenzy", "Glitchpop Frenzy",
    "Araxys Shorty", "Prelude to Chaos Shorty", "Neptune Shorty",
    "Oni Shorty", "Gaia's Vengeance Shorty", "Sentinels of Light Shorty",
    "Sovereign Guardian", "Composite Knife", "Tilde Knife",
    "Sandswept Dagger", "Genesis Arc", "Task Force 809 Knife",
    "Outpost Melee", ".SYS Melee", "Guardrail Hammer", "Transition Knife",
    "Artisan Foil", "Immortalized Vandal", "Imperium Vandal", ".EXE Vandal",
    "Sandswept Vandal", "Nitro Vandal", ".SYS Vandal", "Schema Vandal",
    "Transition Vandal", "Hivemind Vandal", "Venturi Vandal",
    "Lycan's Bane Vandal", "K/TAC Vandal", "Monstrocity Vandal",
    "Guardrail Vandal", "Starlit Odyssey Vandal",
    "Infinity Phantom", "Bound Phantom", "Tactiplay Phantom",
    "Task Force 809 Phantom", "Nebula Phantom", "Serenity Phantom",
    "Artisan Phantom", "Piedra del Sol Phantom", "9 Lives Phantom",
    "Aero Phantom", "RDVR Phantom", "Velocity Phantom", "Kingdom Phantom",
    "Composite Phantom", "Topotek Phantom",
    "Red Alert Operator", "Spitfire Operator", "Blush Operator",
    "Striker Operator", "K/TAC Operator", "Iridian Thorn Operator",
    "Libretto Operator", "Tilde Operator", "Nitro Operator",
    "Aerosol Operator", "Genesis Operator",
    "Guardrail Frenzy", "Coalition: Cobra Frenzy", "Aero Frenzy",
    "Silhouette Frenzy", "Moondash Frenzy", "Couture Frenzy",
    "Spitfire Frenzy", "Venturi Frenzy", "Monarch Frenzy", "Swooping Frenzy",
    "Blush Frenzy", "Hydrodip Frenzy", "Task Force 809 Frenzy",
    "Divine Swine Frenzy", "RagnaRocker Frenzy",
    "Ruin Marshal", "Divine Swine Marshal", "Fiber Optic Marshal",
    "Monarch Marshal", "Couture Marshal", "Composite Marshal",
    "Sandswept Marshal", "Coalition: Cobra Marshal",
    "Task Force 809 Marshal", "Signature Marshal", "Venturi Marshal",
    "Rune Stone Marshal",
    "Digihex Ghost", "Goldwing Ghost", ".EXE Ghost", "Artisan Ghost",
    "Jigsaw Ghost", "Outpost Ghost", "Spitfire Ghost", "Serenity Ghost",
    "Piedra del Sol Ghost", "Fiber Optic Ghost", "Freehand Ghost",
    "Hush Ghost", "Eclipse Ghost", "Starlit Odyssey Ghost",
    "Goldwing Classic", "Striker Classic", "Surge Classic", "9 Lives Classic",
    "Red Alert Classic", "Fiber Optic Classic", "Kingdom Classic",
    "Infinity Classic", "Panoramic Classic",
]

_VALUABLE_SET = set(VALUABLE_SKINS)


class ValorantTitleGenerator:
    """Generate marketplace titles from the resolved Valorant account."""

    def generate(self, account: ValorantResolvedAccount, *, marketplace: str = "default") -> str:
        max_length = 120 if marketplace.lower() == "g2g" else 150

        parts: list[str | list[str]] = [
            account.region.upper() if account.region else "",
            f"{account.skin_count} Skins" if account.skin_count > 0 else "",
            account.display_rank if account.display_rank != "Unranked" else "",
        ]

        buddy_parts = self._buddy_parts(account.buddy_names)
        if buddy_parts:
            parts.extend(buddy_parts)

        skin_list = self._prioritized_skins(account.skin_names)
        if skin_list:
            parts.append(skin_list)

        return self._assemble(parts, max_length=max_length)

    # ------------------------------------------------------------------
    # Buddies
    # ------------------------------------------------------------------

    @staticmethod
    def _buddy_parts(buddies: list[str]) -> list[str]:
        """Return radiant buddy count and riot gun buddy as separate parts."""
        result: list[str] = []
        radiant_count = sum(
            1 for b in buddies if "Radiant" in b and "Buddy" in b
        )
        if radiant_count > 0:
            result.append(f"{radiant_count}xRadiant Buddy")
        if any("Riot Gun Buddy" in b for b in buddies):
            result.append("Riot Gun Buddy")
        return result

    # ------------------------------------------------------------------
    # Skins
    # ------------------------------------------------------------------

    @staticmethod
    def _prioritized_skins(skins: list[str]) -> list[str]:
        """Order skins: valuable first (preserving VALUABLE_SKINS order), then remainder."""
        valuable = [s for s in VALUABLE_SKINS if s in skins]
        remaining = [s for s in skins if s not in _VALUABLE_SET]
        return valuable + remaining

    # ------------------------------------------------------------------
    # Assembly
    # ------------------------------------------------------------------

    @staticmethod
    def _assemble(
        parts: list[str | list[str]],
        *,
        max_length: int,
    ) -> str:
        separator = " | "

        built: list[str] = []
        current_length = 0

        for part in parts:
            if isinstance(part, list):
                for skin in part:
                    if not skin:
                        continue
                    item_len = len(skin) + (len(separator) if built else 0)
                    if current_length + item_len > max_length:
                        break
                    built.append(skin)
                    current_length += item_len
            else:
                if not part or not part.strip():
                    continue
                item_len = len(part) + (len(separator) if built else 0)
                if current_length + item_len > max_length:
                    break
                built.append(part)
                current_length += item_len

        return separator.join(built)
