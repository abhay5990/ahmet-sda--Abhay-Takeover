from __future__ import annotations

RARITY_EMOJI = {
    "common": "⚪",
    "uncommon": "🟢",
    "rare": "🔵",
    "epic": "🟣",
    "legendary": "🟠",
    "mythical": "🔮",
    "secret": "🔴",
    "brainrot god": "👑",
    "og": "✨",
    "ultra-rare": "💎",
}


class SabItemComposer:
    def compose(self, subject, request, media=None):
        title = self._build_title(subject)
        description = self._build_description(subject)
        return {"gameboost": {"title": title, "description": description}}

    def _build_title(self, s):
        rarity_key = s.rarity.lower().strip() if s.rarity else ""
        emoji = RARITY_EMOJI.get(rarity_key, "")
        parts = []
        if emoji:
            parts.append(emoji)
        if s.item_name:
            parts.append(s.item_name)
        if s.rarity:
            parts.append(f"[{s.rarity.capitalize()}]")
        if s.ms_min > 0:
            if s.ms_max > s.ms_min:
                parts.append(f"{s.ms_min:.1f}-{s.ms_max:.1f} M/s")
            else:
                parts.append(f"{s.ms_min:.1f} M/s")
        return " ".join(parts) if parts else "Steal-A-Brainrot Item"

    def _build_description(self, s):
        lines = ["🎮 Steal-A-Brainrot Item", ""]
        if s.item_name:
            lines.append(f"Item: {s.item_name}")
        if s.rarity:
            rarity_key = s.rarity.lower().strip()
            emoji = RARITY_EMOJI.get(rarity_key, "")
            lines.append(f"Rarity: {emoji} {s.rarity.capitalize()}")
        if s.ms_min > 0:
            if s.ms_max > s.ms_min:
                lines.append(f"M/s: {s.ms_min:.1f} - {s.ms_max:.1f}")
            else:
                lines.append(f"M/s: {s.ms_min:.1f}")
        if s.mutations:
            lines.append(f"Mutations: {', '.join(s.mutations)}")
        lines.extend(["", "Fast delivery | 24/7 support"])
        return "\n".join(lines)
