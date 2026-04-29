"""Integration tests for the Brawl Stars image renderer.

These tests may hit the BrawlTime CDN to fetch missing brawler icons, so
they require network access when the local icon cache is cold.

    pytest tests/integration/test_bs_image_renderer.py -v
"""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

import pytest
from PIL import Image

from payload_pipeline.games.bs.account.media.image_renderer import BSImageRenderer
from payload_pipeline.games.bs.account.sources.lzt import BSLztSourceAdapter
from payload_pipeline.shared.paths import default_media_output_dir

_OUTPUT_ROOT = Path(default_media_output_dir("brawl-stars", suffix="test_bs_grid"))


@pytest.fixture()
def fixture_brawlers(load_fixture) -> dict[str, Any]:
    adapter = BSLztSourceAdapter()
    source = adapter.parse(load_fixture("lzt_bs.json"))
    assert source is not None
    return source.brawlers


@pytest.fixture(scope="class")
def output_dir() -> str:
    out = _OUTPUT_ROOT
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True, exist_ok=True)
    return str(out)


class TestBSImageRenderer:
    def test_render_generates_readable_grid(self, fixture_brawlers, output_dir):
        renderer = BSImageRenderer()
        result = renderer.render(fixture_brawlers, f"{output_dir}/brawlers.png")

        assert result is not None
        output_path = Path(result)
        assert output_path.exists()
        assert output_path.stat().st_size > 0

        with Image.open(output_path) as image:
            image.load()
            assert image.width > 1000
            assert image.height > 1000
            assert 0.75 <= image.width / image.height <= 1.35

    def test_render_returns_none_for_empty(self, output_dir):
        renderer = BSImageRenderer()
        result = renderer.render({}, f"{output_dir}/empty.png")

        assert result is None

    def test_grid_columns_are_dynamic(self, fixture_brawlers):
        renderer = BSImageRenderer()
        item_count = len(fixture_brawlers)

        assert item_count == 96
        assert renderer._grid_columns(item_count) == 11
        assert renderer._grid_columns(item_count) > 4

    def test_brawler_extraction_has_render_fields(self, fixture_brawlers):
        assert len(fixture_brawlers) == 96

        sample = next(iter(fixture_brawlers.values()))
        assert sample["name"]
        assert sample["path"]
        assert "power" in sample
        assert "rank" in sample
        assert "trophies" in sample
