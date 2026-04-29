"""Integration tests for the Rainbow Six Siege image renderer.

The renderer fetches skin and operator art from external CDNs and caches
them on disk. These tests require network access on the first run; subsequent
runs use the persistent cache.

    pytest tests/integration/test_r6_image_renderer.py -v
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest
from PIL import Image

from payload_pipeline.core.contracts import PipelineRequest
from payload_pipeline.core import context_keys as ctx
from payload_pipeline.games.r6.account.media.image_renderer import (
    R6ImageRenderer,
    R6ImageRenderEntry,
    _OPERATOR_LAYOUT,
    _SKIN_LAYOUT,
)
from payload_pipeline.games.r6.account.media.strategy import R6MediaStrategy
from payload_pipeline.games.r6.account.resolver import R6Resolver
from payload_pipeline.shared.paths import default_media_output_dir

_OUTPUT_ROOT = Path(default_media_output_dir("rainbow-six-siege", suffix="test_r6_grid"))


def _assert_readable_inventory_image(path: str | Path) -> None:
    output_path = Path(path)
    assert output_path.exists()
    assert output_path.stat().st_size > 0

    with Image.open(output_path) as image:
        image.load()
        assert image.width > 500
        assert image.height > 300
        assert image.width <= 4000
        assert image.height <= 6500
        assert 0.45 <= image.width / image.height <= 2.2


@pytest.fixture()
def fixture_account_both(load_fixture):
    """Resolve R6 account with both lzt + tracker sources."""
    request = PipelineRequest(
        game="rainbow-six-siege",
        category="account",
        kind="stock",
        sources={
            "lzt": load_fixture("lzt_r6.json"),
            "tracker": load_fixture("tracker_r6.json"),
        },
    )
    return R6Resolver().resolve(request), request


@pytest.fixture()
def fixture_account_lzt_only(load_fixture):
    """Resolve R6 account with lzt source only."""
    request = PipelineRequest(
        game="rainbow-six-siege",
        category="account",
        kind="stock",
        sources={
            "lzt": load_fixture("lzt_r6.json"),
        },
    )
    return R6Resolver().resolve(request), request


@pytest.fixture(scope="class")
def output_dir() -> Path:
    out = _OUTPUT_ROOT
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True, exist_ok=True)
    return out


class TestR6ImageRenderer:
    def test_media_strategy_both_sources(self, fixture_account_both, output_dir):
        account, request = fixture_account_both
        request.context[ctx.MEDIA_OUTPUT_DIR] = str(output_dir)

        strategy = R6MediaStrategy()
        paths = strategy.prepare(account, request)

        assert len(paths) > 0
        for p in paths:
            _assert_readable_inventory_image(p)

    def test_media_strategy_lzt_only(self, fixture_account_lzt_only, output_dir):
        account, request = fixture_account_lzt_only
        lzt_out = output_dir / "lzt_only"
        lzt_out.mkdir(parents=True, exist_ok=True)
        request.context[ctx.MEDIA_OUTPUT_DIR] = str(lzt_out)

        strategy = R6MediaStrategy()
        paths = strategy.prepare(account, request)

        assert len(paths) > 0
        for p in paths:
            _assert_readable_inventory_image(p)

    def test_account_has_weapon_skins(self, fixture_account_both):
        account, _ = fixture_account_both
        assert account.skin_count > 0

    def test_account_has_operators(self, fixture_account_both):
        account, _ = fixture_account_both
        assert account.operator_count > 0

    def test_grid_columns_are_dynamic_and_compact(self):
        renderer = R6ImageRenderer()

        assert renderer._grid_columns(341, _SKIN_LAYOUT) == 15
        assert renderer._grid_columns(389, _SKIN_LAYOUT) == 15
        assert renderer._grid_columns(73, _OPERATOR_LAYOUT) == 8
        assert renderer._grid_columns(10, _SKIN_LAYOUT) == 3

    def test_placeholder_render_preserves_unicode_titles(self, output_dir):
        class NoImageRenderer(R6ImageRenderer):
            def _load_or_download_cached(self, entry: R6ImageRenderEntry) -> Image.Image | None:
                return None

        renderer = NoImageRenderer(cache_base_dir=str(output_dir / "placeholder_cache"))
        output_path = renderer.render_operator_entries(
            [
                R6ImageRenderEntry("operator:tubarao", "Tubarão", []),
                R6ImageRenderEntry("operator:capitao", "CAPITÃO", []),
                R6ImageRenderEntry("operator:jager", "Jäger", []),
                R6ImageRenderEntry("operator:ace", "Ace", []),
                R6ImageRenderEntry("operator:iq", "IQ", []),
                R6ImageRenderEntry("operator:doc", "Doc", []),
                R6ImageRenderEntry("operator:frost", "Frost", []),
                R6ImageRenderEntry("operator:lesion", "Lesion", []),
            ],
            product_id="unicode",
            output_folder=str(output_dir / "placeholder_unicode"),
        )

        assert output_path is not None
        _assert_readable_inventory_image(output_path)
