"""Tests for apps.posting.services.dropship.asset_scrubber module.

Usage:
    cd backend && python -m pytest ../tests/unit/test_asset_scrubber.py -v
"""

from __future__ import annotations

import copy
import json
import math
import os
import sys
from pathlib import Path
from unittest import mock

# Add backend to path so `apps.*` imports resolve
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'backend'))

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings.base')

import django
django.setup()

import pytest

from apps.posting.services.dropship.asset_scrubber import (
    _reduce_float,
    _reduce_int,
    _trim_dict,
    _trim_list,
    _scrub_rate,
    scrub_sources,
)

# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------

FIXTURES_DIR = Path(__file__).resolve().parents[1].parent / "libs" / "payload_pipeline" / "tests" / "fixtures"


def _load_fixture(name: str) -> dict:
    with open(FIXTURES_DIR / name, encoding="utf-8") as f:
        return json.load(f)


# Fixed rate for deterministic assertions
RATE = 0.10


# ---------------------------------------------------------------------------
# Helper unit tests
# ---------------------------------------------------------------------------


class TestReduceInt:
    def test_basic(self):
        assert _reduce_int(100, 0.10) == 90

    def test_zero(self):
        assert _reduce_int(0, 0.10) == 0

    def test_none(self):
        assert _reduce_int(None, 0.10) == 0

    def test_string_number(self):
        assert _reduce_int("200", 0.05) == 190

    def test_never_negative(self):
        assert _reduce_int(1, 0.99) >= 0


class TestReduceFloat:
    def test_basic(self):
        assert _reduce_float(100.0, 0.10) == 90.0

    def test_none(self):
        assert _reduce_float(None, 0.10) == 0.0

    def test_string_number(self):
        assert _reduce_float("50.5", 0.10) == 45.45

    def test_never_negative(self):
        assert _reduce_float(0.01, 0.99) >= 0.0


class TestTrimList:
    def test_basic(self):
        lst = list(range(20))
        result = _trim_list(lst, 0.10)
        assert len(result) == 18  # floor(20*0.10)=2 removed
        assert result == list(range(18))

    def test_empty(self):
        assert _trim_list([], 0.10) == []

    def test_keeps_at_least_one(self):
        result = _trim_list([1], 0.50)
        assert len(result) >= 1

    def test_small_list(self):
        # 3 items * 0.10 = 0.3 → floor = 0 removed
        result = _trim_list([1, 2, 3], 0.10)
        assert len(result) == 3


class TestTrimDict:
    def test_basic(self):
        d = {str(i): i for i in range(20)}
        result = _trim_dict(d, 0.10)
        assert len(result) == 18

    def test_empty(self):
        assert _trim_dict({}, 0.10) == {}

    def test_keeps_at_least_one(self):
        result = _trim_dict({"a": 1}, 0.50)
        assert len(result) >= 1


# ---------------------------------------------------------------------------
# Public API tests
# ---------------------------------------------------------------------------


class TestScrubSourcesAPI:
    def test_disabled_returns_original(self):
        sources = {"lzt": {"riot_valorant_level": 100}}
        with mock.patch("apps.posting.services.dropship.asset_scrubber.SCRUB_ENABLED", False):
            result = scrub_sources(sources, "valorant")
        assert result is sources  # exact same object

    def test_unknown_game_returns_original(self):
        sources = {"lzt": {"some_field": 42}}
        result = scrub_sources(sources, "unknown-game-slug")
        assert result is sources

    def test_does_not_mutate_original(self):
        sources = {"lzt": {"riot_valorant_level": 100}}
        original = copy.deepcopy(sources)
        with mock.patch("apps.posting.services.dropship.asset_scrubber._scrub_rate", return_value=0.10):
            scrub_sources(sources, "valorant")
        assert sources == original

    def test_handler_exception_returns_original(self):
        """If a handler raises, the original sources are returned."""
        sources = {"lzt": {"riot_valorant_level": 100}}

        def _boom(*args, **kwargs):
            raise RuntimeError("kaboom")

        with mock.patch("apps.posting.services.dropship.asset_scrubber._HANDLERS", {"valorant": _boom}):
            result = scrub_sources(sources, "valorant")
        assert result is sources


# ---------------------------------------------------------------------------
# Per-game integration tests (using real fixture data)
# ---------------------------------------------------------------------------


class TestScrubValorant:
    @pytest.fixture()
    def sources(self):
        return {"lzt": _load_fixture("lzt_val.json")}

    def test_numeric_fields_reduced(self, sources):
        original_level = sources["lzt"]["riot_valorant_level"]
        with mock.patch("apps.posting.services.dropship.asset_scrubber._scrub_rate", return_value=RATE):
            result = scrub_sources(sources, "valorant")
        assert result["lzt"]["riot_valorant_level"] == math.floor(original_level * 0.90)

    def test_inventory_skins_trimmed(self, sources):
        inv = sources["lzt"].get("valorantInventory")
        if not isinstance(inv, dict):
            pytest.skip("No valorantInventory dict in fixture")
        skins = inv.get("WeaponSkins")
        if not skins:
            pytest.skip("No WeaponSkins in fixture")
        original_count = len(skins) if isinstance(skins, (list, dict)) else 0
        with mock.patch("apps.posting.services.dropship.asset_scrubber._scrub_rate", return_value=RATE):
            result = scrub_sources(sources, "valorant")
        new_skins = result["lzt"]["valorantInventory"]["WeaponSkins"]
        expected = max(1, original_count - math.floor(original_count * RATE))
        assert len(new_skins) == expected

    def test_skin_count_synced(self, sources):
        inv = sources["lzt"].get("valorantInventory")
        if not isinstance(inv, dict) or not inv.get("WeaponSkins"):
            pytest.skip("No WeaponSkins in fixture")
        with mock.patch("apps.posting.services.dropship.asset_scrubber._scrub_rate", return_value=RATE):
            result = scrub_sources(sources, "valorant")
        new_skins = result["lzt"]["valorantInventory"]["WeaponSkins"]
        assert result["lzt"]["riot_valorant_skin_count"] == len(new_skins)


class TestScrubFortnite:
    @pytest.fixture()
    def sources(self):
        return {"lzt": _load_fixture("lzt_fn.json")}

    def test_skins_trimmed_and_sorted_by_rarity(self, sources):
        original_skins = sources["lzt"].get("fortniteSkins", [])
        if not original_skins:
            pytest.skip("No fortniteSkins in fixture")
        with mock.patch("apps.posting.services.dropship.asset_scrubber._scrub_rate", return_value=RATE):
            result = scrub_sources(sources, "fortnite")
        trimmed = result["lzt"]["fortniteSkins"]
        assert len(trimmed) < len(original_skins)
        assert result["lzt"]["fortnite_skin_count"] == len(trimmed)

    def test_numeric_fields_reduced(self, sources):
        original_level = sources["lzt"]["fortnite_level"]
        with mock.patch("apps.posting.services.dropship.asset_scrubber._scrub_rate", return_value=RATE):
            result = scrub_sources(sources, "fortnite")
        assert result["lzt"]["fortnite_level"] == math.floor(original_level * 0.90)

    def test_shop_counts_synced(self, sources):
        if not sources["lzt"].get("fortniteSkins"):
            pytest.skip("No fortniteSkins in fixture")
        with mock.patch("apps.posting.services.dropship.asset_scrubber._scrub_rate", return_value=RATE):
            result = scrub_sources(sources, "fortnite")
        trimmed = result["lzt"]["fortniteSkins"]
        shop_items = [x for x in trimmed if isinstance(x, dict) and x.get("from_shop")]
        assert result["lzt"]["fortnite_shop_skins_count"] == len(shop_items)


class TestScrubR6:
    @pytest.fixture()
    def sources(self):
        return {
            "lzt": _load_fixture("lzt_r6.json"),
            "tracker": _load_fixture("tracker_r6.json"),
        }

    def test_operators_json_string_trimmed(self, sources):
        ops_raw = sources["lzt"].get("uplay_r6_operators")
        if not isinstance(ops_raw, str):
            pytest.skip("operators not a JSON string in fixture")
        original_list = json.loads(ops_raw)
        with mock.patch("apps.posting.services.dropship.asset_scrubber._scrub_rate", return_value=RATE):
            result = scrub_sources(sources, "rainbow-six-siege")
        new_ops = json.loads(result["lzt"]["uplay_r6_operators"])
        expected = max(1, len(original_list) - math.floor(len(original_list) * RATE))
        assert len(new_ops) == expected
        assert result["lzt"]["uplay_r6_operators_count"] == len(new_ops)

    def test_tracker_inventory_trimmed(self, sources):
        inventory = sources["tracker"].get("inventory")
        if not isinstance(inventory, dict) or not inventory:
            pytest.skip("No tracker inventory")
        for cat, items in inventory.items():
            if isinstance(items, list) and len(items) > 10:
                original_len = len(items)
                break
        else:
            pytest.skip("No large enough category in tracker inventory")
        with mock.patch("apps.posting.services.dropship.asset_scrubber._scrub_rate", return_value=RATE):
            result = scrub_sources(sources, "rainbow-six-siege")
        new_items = result["tracker"]["inventory"][cat]
        expected = max(1, original_len - math.floor(original_len * RATE))
        assert len(new_items) == expected

    def test_tracker_numeric_reduced(self, sources):
        original_level = sources["tracker"].get("level")
        if original_level is None:
            pytest.skip("No level in tracker fixture")
        with mock.patch("apps.posting.services.dropship.asset_scrubber._scrub_rate", return_value=RATE):
            result = scrub_sources(sources, "rainbow-six-siege")
        assert result["tracker"]["level"] == math.floor(int(original_level) * 0.90)

    def test_tracker_currency_reduced(self, sources):
        currency = sources["tracker"].get("currency")
        if not isinstance(currency, dict):
            pytest.skip("No currency in tracker fixture")
        original_renown = currency.get("renown")
        if original_renown is None:
            pytest.skip("No renown in currency")
        with mock.patch("apps.posting.services.dropship.asset_scrubber._scrub_rate", return_value=RATE):
            result = scrub_sources(sources, "rainbow-six-siege")
        assert result["tracker"]["currency"]["renown"] == math.floor(int(original_renown) * 0.90)

    def test_lzt_level_reduced(self, sources):
        original = sources["lzt"].get("uplay_r6_level")
        if original is None:
            pytest.skip("No uplay_r6_level")
        with mock.patch("apps.posting.services.dropship.asset_scrubber._scrub_rate", return_value=RATE):
            result = scrub_sources(sources, "rainbow-six-siege")
        assert result["lzt"]["uplay_r6_level"] == math.floor(int(original) * 0.90)


class TestScrubLoL:
    @pytest.fixture()
    def sources(self):
        return {"lzt": _load_fixture("lzt_lol.json")}

    def test_champions_trimmed(self, sources):
        inv = sources["lzt"].get("lolInventory")
        if not isinstance(inv, dict):
            pytest.skip("No lolInventory dict")
        champs = inv.get("Champion") or inv.get("Champions")
        if not isinstance(champs, list) or len(champs) < 5:
            pytest.skip("Not enough champions")
        original_len = len(champs)
        with mock.patch("apps.posting.services.dropship.asset_scrubber._scrub_rate", return_value=RATE):
            result = scrub_sources(sources, "league-of-legends")
        key = "Champion" if "Champion" in result["lzt"]["lolInventory"] else "Champions"
        new_champs = result["lzt"]["lolInventory"][key]
        expected = max(1, original_len - math.floor(original_len * RATE))
        assert len(new_champs) == expected
        assert result["lzt"]["riot_lol_champion_count"] == len(new_champs)

    def test_numeric_fields_reduced(self, sources):
        original = sources["lzt"]["riot_lol_level"]
        if not original:
            pytest.skip("LoL level is 0")
        with mock.patch("apps.posting.services.dropship.asset_scrubber._scrub_rate", return_value=RATE):
            result = scrub_sources(sources, "league-of-legends")
        assert result["lzt"]["riot_lol_level"] == math.floor(int(original) * 0.90)


class TestScrubBrawlStars:
    @pytest.fixture()
    def sources(self):
        return {"lzt": _load_fixture("lzt_bs.json")}

    def test_brawlers_trimmed(self, sources):
        brawlers = sources["lzt"].get("supercellBrawlers")
        if not isinstance(brawlers, dict) or not brawlers:
            pytest.skip("No supercellBrawlers dict")
        original_len = len(brawlers)
        with mock.patch("apps.posting.services.dropship.asset_scrubber._scrub_rate", return_value=RATE):
            result = scrub_sources(sources, "brawl-stars")
        new_brawlers = result["lzt"]["supercellBrawlers"]
        expected = max(1, original_len - math.floor(original_len * RATE))
        assert len(new_brawlers) == expected
        assert result["lzt"]["supercell_brawler_count"] == len(new_brawlers)

    def test_legendary_count_recalculated(self, sources):
        brawlers = sources["lzt"].get("supercellBrawlers")
        if not isinstance(brawlers, dict):
            pytest.skip("No supercellBrawlers dict")
        with mock.patch("apps.posting.services.dropship.asset_scrubber._scrub_rate", return_value=RATE):
            result = scrub_sources(sources, "brawl-stars")
        new_brawlers = result["lzt"]["supercellBrawlers"]
        expected_legendary = sum(
            1 for b in new_brawlers.values()
            if isinstance(b, dict) and str(b.get("class", "")).lower() == "legendary"
        )
        assert result["lzt"]["supercell_legendary_brawler_count"] == expected_legendary

    def test_numeric_fields_reduced(self, sources):
        original = sources["lzt"]["supercell_laser_trophies"]
        with mock.patch("apps.posting.services.dropship.asset_scrubber._scrub_rate", return_value=RATE):
            result = scrub_sources(sources, "brawl-stars")
        assert result["lzt"]["supercell_laser_trophies"] == math.floor(int(original) * 0.90)


class TestScrubCoC:
    @pytest.fixture()
    def sources(self):
        return {"lzt": _load_fixture("lzt_coc.json")}

    def test_numeric_fields_reduced(self, sources):
        field = "supercell_magic_level"
        original = sources["lzt"].get(field)
        if not original:
            pytest.skip(f"No {field} in fixture")
        with mock.patch("apps.posting.services.dropship.asset_scrubber._scrub_rate", return_value=RATE):
            result = scrub_sources(sources, "clash-of-clans")
        assert result["lzt"][field] == math.floor(int(original) * 0.90)


class TestScrubCR:
    @pytest.fixture()
    def sources(self):
        return {
            "lzt": _load_fixture("lzt_cr.json"),
            "tracker": _load_fixture("tracker_cr.json"),
        }

    def test_lzt_numeric_fields_reduced(self, sources):
        field = "supercell_scroll_trophies"
        original = sources["lzt"].get(field)
        if not original:
            pytest.skip(f"No {field}")
        with mock.patch("apps.posting.services.dropship.asset_scrubber._scrub_rate", return_value=RATE):
            result = scrub_sources(sources, "clash-royale")
        assert result["lzt"][field] == math.floor(int(original) * 0.90)


class TestScrubGenshin:
    @pytest.fixture()
    def sources(self):
        return {"lzt": _load_fixture("lzt_gi.json")}

    def test_numeric_fields_reduced(self, sources):
        field = "mihoyo_genshin_level"
        original = sources["lzt"].get(field)
        if not original:
            pytest.skip(f"No {field}")
        with mock.patch("apps.posting.services.dropship.asset_scrubber._scrub_rate", return_value=RATE):
            result = scrub_sources(sources, "genshin-impact")
        assert result["lzt"][field] == math.floor(int(original) * 0.90)


class TestScrubGTAV:
    @pytest.fixture()
    def sources(self):
        return {"lzt": _load_fixture("lzt_gtav.json")}

    def test_level_reduced(self, sources):
        original = sources["lzt"].get("level")
        if not original:
            od = sources["lzt"].get("offer_details", {})
            original = od.get("level")
        if not original:
            pytest.skip("No level field")
        with mock.patch("apps.posting.services.dropship.asset_scrubber._scrub_rate", return_value=RATE):
            result = scrub_sources(sources, "grand-theft-auto-5")
        if "level" in result["lzt"] and result["lzt"]["level"]:
            assert result["lzt"]["level"] == math.floor(int(original) * 0.90)
        elif isinstance(result["lzt"].get("offer_details"), dict):
            assert result["lzt"]["offer_details"]["level"] == math.floor(int(original) * 0.90)


class TestScrubSteam:
    @pytest.fixture()
    def sources(self):
        return {"lzt": _load_fixture("lzt_steam.json")}

    def test_games_list_trimmed(self, sources):
        full_games = sources["lzt"].get("steam_full_games")
        if not isinstance(full_games, dict):
            pytest.skip("No steam_full_games")
        games_list = full_games.get("list")
        if not games_list:
            pytest.skip("No games list")
        original_len = len(games_list)
        with mock.patch("apps.posting.services.dropship.asset_scrubber._scrub_rate", return_value=RATE):
            result = scrub_sources(sources, "steam")
        new_list = result["lzt"]["steam_full_games"]["list"]
        expected = max(1, original_len - math.floor(original_len * RATE))
        assert len(new_list) == expected

    def test_level_reduced(self, sources):
        original = sources["lzt"].get("steam_level")
        if not original:
            pytest.skip("No steam_level")
        with mock.patch("apps.posting.services.dropship.asset_scrubber._scrub_rate", return_value=RATE):
            result = scrub_sources(sources, "steam")
        assert result["lzt"]["steam_level"] == math.floor(int(original) * 0.90)


class TestScrubCS2:
    def test_rank_not_scrubbed(self):
        """rank and premier_elo should NOT be scrubbed."""
        sources = {"lzt": {
            "rank": 15,
            "premier_elo": 20000,
            "hours_played": 500,
            "medals": [{"id": 1}, {"id": 2}, {"id": 3}],
        }}
        with mock.patch("apps.posting.services.dropship.asset_scrubber._scrub_rate", return_value=RATE):
            result = scrub_sources(sources, "counter-strike-2")
        assert result["lzt"]["rank"] == 15
        assert result["lzt"]["premier_elo"] == 20000
        assert result["lzt"]["hours_played"] == math.floor(500 * 0.90)


class TestScrubRoblox:
    @pytest.fixture()
    def sources(self):
        return {"lzt": _load_fixture("lzt_roblox.json")}

    def test_int_fields_reduced(self, sources):
        field = "roblox_robux"
        original = sources["lzt"].get(field)
        if not original:
            pytest.skip(f"No {field}")
        with mock.patch("apps.posting.services.dropship.asset_scrubber._scrub_rate", return_value=RATE):
            result = scrub_sources(sources, "roblox")
        assert result["lzt"][field] == math.floor(int(original) * 0.90)

    def test_float_fields_reduced(self, sources):
        field = "roblox_inventory_price"
        original = sources["lzt"].get(field)
        if not original:
            pytest.skip(f"No {field}")
        with mock.patch("apps.posting.services.dropship.asset_scrubber._scrub_rate", return_value=RATE):
            result = scrub_sources(sources, "roblox")
        expected = round(float(original) * 0.90, 2)
        assert result["lzt"][field] == expected


class TestScrubUbisoft:
    @pytest.fixture()
    def sources(self):
        return {"lzt": _load_fixture("lzt_ubisoft_connect.json")}

    def test_games_trimmed(self, sources):
        games = sources["lzt"].get("uplay_games")
        if not isinstance(games, dict) or not games:
            pytest.skip("No uplay_games dict")
        original_len = len(games)
        with mock.patch("apps.posting.services.dropship.asset_scrubber._scrub_rate", return_value=RATE):
            result = scrub_sources(sources, "ubisoft-connect")
        new_games = result["lzt"]["uplay_games"]
        expected = max(1, original_len - math.floor(original_len * RATE))
        assert len(new_games) == expected
        assert result["lzt"]["uplay_game_count"] == len(new_games)


# ---------------------------------------------------------------------------
# Scrub rate range test
# ---------------------------------------------------------------------------


class TestScrubRate:
    def test_rate_in_range(self):
        for _ in range(100):
            rate = _scrub_rate()
            assert 0.05 <= rate <= 0.10
