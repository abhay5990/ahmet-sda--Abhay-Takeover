"""Integration tests for the Fortnite grid renderer.

These tests hit the Fortnite API to fetch cosmetic icons, so they
require network access and are slower than unit tests.

    pytest tests/integration/test_fn_grid_renderer.py -v
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from payload_pipeline.games.fn.account.models import CosmeticItem
from payload_pipeline.games.fn.account.sources.lzt import FortniteLztSourceAdapter
from payload_pipeline.games.fn.account.media.grid_renderer import FortniteGridRenderer
from payload_pipeline.shared.paths import default_media_output_dir

_OUTPUT_ROOT = Path(default_media_output_dir("fortnite", suffix="test_fn_grid"))


@pytest.fixture()
def fixture_cosmetics(load_fixture) -> dict[str, list[CosmeticItem]]:
    adapter = FortniteLztSourceAdapter()
    source = adapter.parse(load_fixture("lzt_fn.json"))
    assert source is not None
    return source.cosmetic_items


@pytest.fixture(scope="class")
def output_dir() -> str:
    out = _OUTPUT_ROOT
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True, exist_ok=True)
    return str(out)


class TestFortniteGridRenderer:
    def test_render_all_generates_four_images(self, fixture_cosmetics, output_dir):
        renderer = FortniteGridRenderer()
        paths = renderer.render_all(fixture_cosmetics, output_dir)

        assert len(paths) == 4
        for p in paths:
            assert Path(p).exists()
            assert Path(p).stat().st_size > 0

    def test_render_type_returns_path_on_success(self, fixture_cosmetics, output_dir):
        renderer = FortniteGridRenderer()
        items = fixture_cosmetics.get("outfit", [])
        assert len(items) > 0

        result = renderer.render_type(items, "outfit", f"{output_dir}/skins.png")
        assert result is not None
        assert Path(result).exists()

    def test_render_type_returns_none_for_empty(self, output_dir):
        renderer = FortniteGridRenderer()
        result = renderer.render_type([], "outfit", f"{output_dir}/empty.png")
        assert result is None

    def test_items_sorted_by_rarity(self, fixture_cosmetics):
        renderer = FortniteGridRenderer()
        items = fixture_cosmetics.get("outfit", [])
        sorted_items = sorted(items, key=renderer._rarity_sort_key)

        rarities = [it.rarity for it in sorted_items]
        # Legendary items should come before epic, epic before rare, etc.
        first_legendary = next((i for i, r in enumerate(rarities) if r == "legendary"), -1)
        first_epic = next((i for i, r in enumerate(rarities) if r == "epic"), -1)
        first_rare = next((i for i, r in enumerate(rarities) if r == "rare"), -1)

        if first_legendary >= 0 and first_epic >= 0:
            assert first_legendary < first_epic
        if first_epic >= 0 and first_rare >= 0:
            assert first_epic < first_rare

    def test_cosmetic_item_extraction(self, fixture_cosmetics):
        assert "outfit" in fixture_cosmetics
        assert "pickaxe" in fixture_cosmetics
        assert "emote" in fixture_cosmetics
        assert "glider" in fixture_cosmetics

        for ctype, items in fixture_cosmetics.items():
            assert len(items) > 0
            for item in items:
                assert item.id
                assert item.title
                assert item.rarity
                assert item.type == ctype
