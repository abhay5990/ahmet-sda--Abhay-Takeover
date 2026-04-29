"""Integration tests for the Clash Royale image renderer.

The renderer fetches card art from the StatsRoyale CDN and caches it on disk.
These tests require network access on the first run; subsequent runs use the
persistent card cache.

    pytest tests/integration/test_cr_image_renderer.py -v
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest
from PIL import Image

from payload_pipeline.core.contracts import PipelineRequest
from payload_pipeline.games.cr.account.media.image_renderer import CrImageRenderer
from payload_pipeline.games.cr.account.resolver import CrResolver
from payload_pipeline.shared.paths import default_cache_base_dir, default_media_output_dir

_OUTPUT_ROOT = Path(default_media_output_dir("clash-royale", suffix="test_cr_grid"))
_CACHE_ROOT = Path(default_cache_base_dir("clash-royale")) / "cards"


@pytest.fixture()
def fixture_account(load_fixture):
    request = PipelineRequest(
        game="clash-royale",
        category="account",
        kind="stock",
        sources={
            "lzt": load_fixture("lzt_cr.json"),
            "tracker": load_fixture("tracker_cr.json"),
        },
    )
    return CrResolver().resolve(request)


@pytest.fixture(scope="class")
def output_dir() -> Path:
    out = _OUTPUT_ROOT
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True, exist_ok=True)
    return out


class TestCrImageRenderer:
    def test_render_generates_readable_grid(self, fixture_account, output_dir):
        renderer = CrImageRenderer(cache_dir=str(_CACHE_ROOT))

        result = renderer.render(fixture_account.cards_data, str(output_dir / "cards.png"))

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
        renderer = CrImageRenderer(cache_dir=str(_CACHE_ROOT))
        result = renderer.render({}, str(output_dir / "empty.png"))

        assert result is None

    def test_grid_columns_are_dynamic(self, fixture_account):
        renderer = CrImageRenderer()
        item_count = len(fixture_account.cards_data)

        assert item_count == 121
        assert renderer._grid_columns(item_count) == 13
        assert renderer._grid_columns(item_count) > 4

    def test_fixture_account_has_render_fields(self, fixture_account):
        assert len(fixture_account.cards_data) == 121
        assert fixture_account.level_15_cards_count == 6
        assert fixture_account.level_14_cards_count == 39
        assert fixture_account.evolution_count == 16

        sample = next(iter(fixture_account.cards_data.values()))
        assert sample["name"]
        assert "normalizedLevel" in sample
