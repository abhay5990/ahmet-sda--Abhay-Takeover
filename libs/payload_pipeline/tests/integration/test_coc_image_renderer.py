"""Integration tests for the Clash of Clans image renderer.

The fixture does not require a local icon cache. The renderer should still
produce readable media from bundled ``resources/image_map`` icons when the
configured image cache is empty.

    pytest tests/integration/test_coc_image_renderer.py -v
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest
from PIL import Image

from payload_pipeline.core.contracts import PipelineRequest
from payload_pipeline.games.coc.account.media.image_renderer import CocImageRenderer
from payload_pipeline.games.coc.account.resolver import CocResolver
from payload_pipeline.shared.paths import default_cache_base_dir, default_media_output_dir

_OUTPUT_ROOT = Path(default_media_output_dir("clash-of-clans", suffix="test_coc_grid"))
_CACHE_ROOT = Path(default_cache_base_dir("clash-of-clans")) / "test-empty-cache"


@pytest.fixture()
def fixture_account(load_fixture):
    request = PipelineRequest(
        game="clash-of-clans",
        category="account",
        kind="stock",
        sources={
            "lzt": load_fixture("lzt_coc.json"),
            "tracker": load_fixture("tracker_coc.json"),
        },
    )
    return CocResolver().resolve(request)


@pytest.fixture(scope="class")
def output_dir() -> Path:
    out = _OUTPUT_ROOT
    if out.exists():
        shutil.rmtree(out)
    if _CACHE_ROOT.exists():
        shutil.rmtree(_CACHE_ROOT)
    out.mkdir(parents=True, exist_ok=True)
    _CACHE_ROOT.mkdir(parents=True, exist_ok=True)
    return out


class TestCocImageRenderer:
    def test_render_generates_account_media_set(self, fixture_account, output_dir):
        renderer = CocImageRenderer(cache_folder=str(_CACHE_ROOT))
        paths = renderer.render(
            heroes=fixture_account.heroes,
            troops=fixture_account.troops,
            spells=fixture_account.spells,
            hero_equipment=fixture_account.hero_equipment,
            super_troops=fixture_account.super_troops,
            player_tag=fixture_account.player_tag,
            output_dir=str(output_dir),
        )

        assert len(paths) == 4
        for path in paths:
            output_path = Path(path)
            assert output_path.exists()
            assert output_path.stat().st_size > 0

            with Image.open(output_path) as image:
                image.load()
                assert image.width >= 550
                assert image.height >= 300
                assert 0.55 <= image.width / image.height <= 2.2

    def test_render_returns_empty_when_no_render_data(self, output_dir):
        renderer = CocImageRenderer(cache_folder=str(_CACHE_ROOT))
        paths = renderer.render(
            heroes=[],
            troops=[],
            spells=[],
            hero_equipment=[],
            super_troops=[],
            player_tag="",
            output_dir=str(output_dir),
        )

        assert paths == []

    def test_grid_columns_match_legacy_layout(self):
        renderer = CocImageRenderer()

        assert renderer.canvas_width == 620
        assert renderer.grid_cols == 8
        assert renderer.icon_size == (64, 64)
        assert renderer.hero_icon_size == (80, 80)

    def test_default_resource_image_map_is_used_when_cache_is_empty(self, output_dir):
        renderer = CocImageRenderer(cache_folder=str(_CACHE_ROOT))

        icon = renderer._load_icon("hero", 0, True)

        assert icon is not None
        assert icon.width <= 80
        assert icon.height <= 80

    def test_fixture_account_has_render_fields(self, fixture_account):
        assert fixture_account.player_tag == "#L0URGJPLV"
        assert len(fixture_account.heroes) == 7
        assert len(fixture_account.troops) == 62
        assert len(fixture_account.spells) == 17
        assert len(fixture_account.hero_equipment) == 31
        assert len(fixture_account.super_troops) == 17
