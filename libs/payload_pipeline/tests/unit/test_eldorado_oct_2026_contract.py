"""Eldorado account contract (late Oct 2026): Numeric attributes per game.

Eldorado now requires exact Numeric values next to the dropdown buckets.
Every number must come from the same resolved field the dropdown uses.
"""

from __future__ import annotations

import pytest

from payload_pipeline.marketplaces.eldorado_numeric import (
    ELDORADO_NUMERIC_SPECS,
    EldoradoNumericAttributeError,
    serialize_attributes,
    thousand,
    validate_numeric,
)


def test_thousand_and_validation_rules():
    assert thousand(2650) == 2.7
    assert thousand(73825) == 73.8
    assert thousand(-300) == 0.0  # refunded V-Bucks are 0 spendable
    assert validate_numeric("fortnite-outfits-skins-numeric", 70) == 70
    assert validate_numeric("fortnite-v-bucks-numeric", 1.2) == 1.2
    with pytest.raises(EldoradoNumericAttributeError):
        validate_numeric("fortnite-outfits-skins-numeric", 2801)  # above Eldorado max
    with pytest.raises(EldoradoNumericAttributeError):
        validate_numeric("fortnite-outfits-skins-numeric", 1.5)  # integer field
    with pytest.raises(EldoradoNumericAttributeError):
        validate_numeric("clash-of-clans-town-hall-numeric", 0)  # minimum 1
    with pytest.raises(EldoradoNumericAttributeError):
        validate_numeric("not-a-real-numeric", 1)


def test_serialize_types_select_then_numeric():
    out = serialize_attributes({"fortnite-vbucks": "vbucks-1199"}, {"fortnite-v-bucks-numeric": 1.2})
    assert out == [
        {"id": "fortnite-vbucks", "type": "Select", "value": "vbucks-1199"},
        {"id": "fortnite-v-bucks-numeric", "type": "Numeric", "value": 1.2},
    ]


def _builder_source(game: str) -> str:
    from pathlib import Path
    import payload_pipeline

    root = Path(payload_pipeline.__file__).resolve().parent
    return (root / "games" / game / "account" / "marketplaces" / "eldorado.py").read_text(encoding="utf-8")


EXPECTED = {
    "fn": ["fortnite-emotes-numeric", "fortnite-outfits-skins-numeric", "fortnite-pickaxes-numeric", "fortnite-v-bucks-numeric"],
    "val": ["valorant-agents-numeric", "valorant-knives-numeric", "valorant-spent-points-numeric", "valorant-weapon-skins-numeric"],
    "lol": ["league-of-legends-blue-essence-numeric", "league-of-legends-champion-count-numeric", "league-of-legends-riot-points-numeric", "league-of-legends-skins-numeric"],
    "r6": ["rainbow-six-siege-x-black-ice-skins-numeric", "rainbow-six-siege-x-operators-numeric", "rainbow-six-siege-x-renown-numeric"],
    "coc": ["clash-of-clans-gems-numeric", "clash-of-clans-town-hall-numeric"],
    "bs": ["brawl-stars-brawlers-count-numeric", "brawl-stars-buffies-numeric", "brawl-stars-gems-numeric", "brawl-stars-hypercharge-numeric",
           "brawl-stars-maxed-brawlers-numeric", "brawl-stars-prestige-numeric", "brawl-stars-skins-numeric", "brawl-stars-trophies-numeric"],
    "roblox": ["roblox-inventory-value-numeric", "roblox-offsale-items-numeric", "roblox-robux-balance-numeric"],
    "cs2": ["cs2-faceit-level-numeric", "cs2-medals-numeric", "cs2-premier-rating-numeric"],
    "rust": ["rust-hours-played-numeric", "rust-skins-count-numeric", "rust-steam-account-level-numeric"],
    "gi": ["genshin-impact-adventure-rank-numeric", "genshin-impact-characters-numeric", "genshin-impact-events-count-numeric",
           "genshin-impact-legendary-weapons-numeric", "genshin-impact-primogems-count-numeric"],
}


@pytest.mark.parametrize("game,ids", sorted(EXPECTED.items()))
def test_every_game_builder_sends_its_required_numeric_attributes(game, ids):
    src = _builder_source(game)
    assert "numeric_attributes=" in src
    for attr_id in ids:
        assert attr_id in ELDORADO_NUMERIC_SPECS
        assert f'"{attr_id}"' in src, f"{game} builder does not send {attr_id}"


def test_cs2_faceit_level_comes_from_the_faceit_dropdown():
    from payload_pipeline.games.cs2.account.marketplaces.eldorado import _faceit_level

    assert _faceit_level("faceit-7") == 7
    assert _faceit_level("faceit-10") == 10
    assert _faceit_level("faceit-other") == 0
    assert _faceit_level("") == 0
