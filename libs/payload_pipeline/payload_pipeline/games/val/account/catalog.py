"""Static catalog loading for Valorant inventory titles."""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
import json
from pathlib import Path


def _load_mapping(path: str) -> dict[str, str]:
    try:
        with open(path, "r", encoding="utf-8") as handle:
            rows = json.load(handle)
    except (OSError, json.JSONDecodeError):
        return {}

    if not isinstance(rows, list):
        return {}

    mapping: dict[str, str] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        key = str(row.get("data_id") or "").strip()
        title = str(row.get("alt") or "").strip()
        if key and title and key not in mapping:
            mapping[key] = title
    return mapping


@dataclass(frozen=True, slots=True)
class ValorantCatalog:
    """Resolve Valorant inventory IDs into stable display titles."""

    agents_by_id: dict[str, str]
    skins_by_id: dict[str, str]
    buddies_by_id: dict[str, str]

    def resolve_agents(self, agent_ids: list[str]) -> list[str]:
        return [self.agents_by_id[agent_id] for agent_id in agent_ids if agent_id in self.agents_by_id]

    def resolve_skins(self, skin_ids: list[str]) -> list[str]:
        return [self.skins_by_id[skin_id] for skin_id in skin_ids if skin_id in self.skins_by_id]

    def resolve_buddies(self, buddy_ids: list[str]) -> list[str]:
        return [self.buddies_by_id[buddy_id] for buddy_id in buddy_ids if buddy_id in self.buddies_by_id]


_RESOURCES_DIR = Path(__file__).resolve().parent / "resources"


@lru_cache(maxsize=1)
def load_default_catalog() -> ValorantCatalog:
    """Load the bundled Valorant catalogs once per process."""

    return ValorantCatalog(
        agents_by_id=_load_mapping(str(_RESOURCES_DIR / "dataAgents.json")),
        skins_by_id=_load_mapping(str(_RESOURCES_DIR / "dataSkins.json")),
        buddies_by_id=_load_mapping(str(_RESOURCES_DIR / "dataBuddies.json")),
    )
