"""Integration tests for the shared Steam game-grid renderer.

The renderer normally downloads Steam header art into the shared image cache.
These tests use deterministic in-memory headers so the layout contract is not
coupled to CDN availability.

    pytest tests/integration/test_steam_image_renderer.py -v
"""

from __future__ import annotations

import hashlib
import shutil
from pathlib import Path
from typing import Any

import pytest
from PIL import Image, ImageDraw

from payload_pipeline.games.steam.account.sources.lzt import SteamLztSourceAdapter
from payload_pipeline.shared.paths import default_media_output_dir
from payload_pipeline.shared.steam_game_grid import SteamGameGridRenderer

_OUTPUT_ROOT = Path(default_media_output_dir("steam", suffix="test_steam_grid"))


@pytest.fixture()
def fixture_games(load_fixture) -> list[dict[str, Any]]:
    adapter = SteamLztSourceAdapter()
    source = adapter.parse(load_fixture("lzt_steam.json"))
    assert source is not None
    return source.games


@pytest.fixture(scope="class")
def output_dir() -> Path:
    out = _OUTPUT_ROOT
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True, exist_ok=True)
    return out


class TestSteamGameGridRenderer:
    def test_render_generates_readable_balanced_grid(self, fixture_games, output_dir):
        renderer = SteamGameGridRenderer()
        renderer._load_game_image = _fake_steam_header  # type: ignore[method-assign]

        result = renderer.render(fixture_games, str(output_dir / "steam_games.png"))

        assert result is not None
        output_path = Path(result)
        assert output_path.exists()
        assert output_path.stat().st_size > 0

        with Image.open(output_path) as image:
            image.load()
            assert image.width > 1200
            assert image.height > 1200
            assert 0.85 <= image.width / image.height <= 1.15

    def test_render_returns_none_for_empty(self, output_dir):
        renderer = SteamGameGridRenderer()

        result = renderer.render([], str(output_dir / "empty.png"))

        assert result is None

    def test_grid_columns_are_dynamic(self, fixture_games):
        renderer = SteamGameGridRenderer()
        item_count = len(fixture_games)

        assert item_count == 78
        assert renderer._grid_columns(item_count) == 8
        assert renderer._grid_columns(item_count) > 5

    def test_fixture_games_have_render_fields(self, fixture_games):
        assert len(fixture_games) == 78

        sample = fixture_games[0]
        assert sample["appid"]
        assert sample["title"]
        assert sample["img"]
        assert "playtime_forever" in sample


def _fake_steam_header(url: str, app_id: str) -> Image.Image:
    digest = hashlib.sha1(f"{app_id}:{url}".encode("utf-8")).digest()
    base = tuple(40 + byte % 130 for byte in digest[:3])
    accent = tuple(110 + byte % 120 for byte in digest[3:6])

    image = Image.new("RGB", (150, 70), base)
    draw = ImageDraw.Draw(image)
    draw.rectangle((0, 0, 150, 16), fill=accent)
    draw.rectangle(
        (0, 54, 150, 70),
        fill=tuple(max(0, channel - 25) for channel in base),
    )
    draw.text((8, 27), str(app_id)[:12], fill=(245, 245, 245))
    return image
