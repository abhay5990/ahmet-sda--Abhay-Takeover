"""Shared rank parsing helpers for the R6 slice."""

from __future__ import annotations

import re
from typing import Iterable


_RANK_ORDER = [
    "Champion",
    "Diamond",
    "Emerald",
    "Platinum",
    "Gold",
    "Silver",
    "Bronze",
    "Copper",
]

_RANK_PRIORITY = {rank.lower(): index for index, rank in enumerate(_RANK_ORDER)}
_RANK_PRIORITY["ranked ready"] = len(_RANK_ORDER)
_RANK_PRIORITY["unranked"] = len(_RANK_ORDER) + 1


def extract_rank_mentions(value: object) -> list[tuple[str, int]]:
    """Extract ordered rank mentions with optional explicit counts."""
    text = str(value or "").strip()
    if not text:
        return []

    mentions: list[tuple[str, int]] = []
    pattern = re.compile(
        r"(?:(?P<count_before>\d+)\s*x?\s*)?"
        r"(?P<rank>Champions?|Diamond|Emerald|Platinum|Gold|Silver|Bronze|Copper)"
        r"(?:\s*x?\s*(?P<count_after>\d+))?",
        re.IGNORECASE,
    )

    for match in pattern.finditer(text):
        rank = normalize_rank(match.group("rank") or match.group())
        if not rank:
            continue

        count_text = match.group("count_before") or match.group("count_after") or "1"
        mentions.append((rank, max(1, int(count_text))))

    return mentions


def extract_rank_mentions_from_title(value: object) -> list[tuple[str, int, str]]:
    """Extract rank-like title segments while ignoring unrelated listing tokens."""
    text = str(value or "").strip()
    if not text:
        return []

    mentions: list[tuple[str, int, str]] = []
    for raw_segment in (segment.strip() for segment in text.split("|")):
        segment = raw_segment.strip()
        if not segment:
            continue

        lowered = segment.lower()
        if any(token in lowered for token in ("gold dust", "black ice", "proleague", "elite")):
            continue

        match = re.search(
            r"(?:(?P<count_before>\d+)\s*x?\s*)?"
            r"(?P<rank>Champions?|Diamond|Emerald|Platinum|Gold|Silver|Bronze|Copper)"
            r"(?:\s*x?\s*(?P<count_after>\d+))?",
            segment,
            re.IGNORECASE,
        )
        if match is None:
            continue

        rank = normalize_rank(match.group("rank"))
        if not rank:
            continue

        count_text = match.group("count_before") or match.group("count_after") or "1"
        prefix = segment[:match.start()].strip()
        suffix = segment[match.end():].strip()
        season = prefix or suffix
        mentions.append((rank, max(1, int(count_text)), season))

    return mentions


def normalize_rank(value: object) -> str:
    """Normalize a free-form rank value into the canonical slice vocabulary."""
    text = str(value or "").strip()
    if not text:
        return ""

    lowered = text.lower()
    aliases = {
        "champ": "Champion",
        "champion": "Champion",
        "diamond": "Diamond",
        "dia": "Diamond",
        "dmd": "Diamond",
        "emerald": "Emerald",
        "eme": "Emerald",
        "platinum": "Platinum",
        "plat": "Platinum",
        "gold": "Gold",
        "silver": "Silver",
        "bronze": "Bronze",
        "copper": "Copper",
        "ranked ready": "Ranked Ready",
        "unranked": "Unranked",
    }
    for token, normalized in aliases.items():
        if token in lowered:
            return normalized

    return ""


def extract_rank_from_text(value: object) -> str:
    """Extract the best rank mention from listing text."""
    return pick_best_rank(*(rank for rank, _ in extract_rank_mentions(value)))


def extract_rank_from_title_text(value: object) -> str:
    """Extract the best rank-like segment from listing titles."""
    return pick_best_rank(*(rank for rank, _, _ in extract_rank_mentions_from_title(value)))


def extract_rank_count_from_text(value: object, *, target_rank: object = "") -> int:
    """Extract an explicit count hint for a rank mention in free-form text."""
    mentions = extract_rank_mentions(value)
    if not mentions:
        return 0

    normalized_target = normalize_rank(target_rank)
    if not normalized_target:
        normalized_target = pick_best_rank(*(rank for rank, _ in mentions))
    if not normalized_target:
        return 0

    counts = [count for rank, count in mentions if rank == normalized_target]
    return max(counts, default=0)


def extract_rank_count_from_title_text(value: object, *, target_rank: object = "") -> int:
    """Extract the total explicit count for a rank-like title segment."""
    mentions = extract_rank_mentions_from_title(value)
    if not mentions:
        return 0

    normalized_target = normalize_rank(target_rank)
    if not normalized_target:
        normalized_target = pick_best_rank(*(rank for rank, _, _ in mentions))
    if not normalized_target:
        return 0

    return sum(count for rank, count, _ in mentions if rank == normalized_target)


def extract_rank_sequence(values: Iterable[object]) -> list[str]:
    """Extract normalized rank mentions while preserving the original order."""
    ranks: list[str] = []
    for value in values:
        rank = extract_rank_from_text(value)
        if rank:
            ranks.append(rank)
    return ranks


def extract_rank_from_names(values: Iterable[object]) -> str:
    """Extract the best rank mention from multiple inventory item names."""
    return pick_best_rank(*extract_rank_sequence(values))


def extract_latest_rank_from_names(values: Iterable[object]) -> str:
    """Extract the last valid rank mention from ordered inventory item names."""
    sequence = extract_rank_sequence(values)
    return sequence[-1] if sequence else ""


def count_rank_occurrences(values: Iterable[object], target_rank: object) -> int:
    """Count how many ordered values resolve to the target rank."""
    normalized_target = normalize_rank(target_rank)
    if not normalized_target:
        return 0
    return sum(1 for rank in extract_rank_sequence(values) if rank == normalized_target)


def pick_best_rank(*values: object) -> str:
    """Return the highest rank among free-form values."""
    normalized = [normalize_rank(value) for value in values if normalize_rank(value)]
    if not normalized:
        return ""
    return min(normalized, key=lambda value: _RANK_PRIORITY.get(value.lower(), 999))
