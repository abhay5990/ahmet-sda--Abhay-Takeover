"""Integration tests for the CS2 media strategy and game-grid renderer.

CS2 media reuses the shared Steam game-grid renderer. These tests keep CDN
availability out of the layout contract by rendering deterministic headers.

    pytest tests/integration/test_cs2_image_renderer.py -v
"""

from __future__ import annotations

import hashlib
import shutil
from pathlib import Path

import pytest
from PIL import Image, ImageDraw

from payload_pipeline.core import context_keys as ctx
from payload_pipeline.core.contracts import PipelineRequest
from payload_pipeline.games.cs2.account.media.strategy import CS2MediaStrategy
from payload_pipeline.games.cs2.account.models import CS2ResolvedAccount
from payload_pipeline.games.cs2.account.resolver import CS2Resolver
from payload_pipeline.shared.paths import default_media_output_dir
from payload_pipeline.shared.steam_game_grid import SteamGameGridRenderer

_OUTPUT_ROOT = Path(default_media_output_dir("counter-strike-2", suffix="test_cs2_grid"))


@pytest.fixture()
def fixture_account(load_fixture):
    request = PipelineRequest(
        game="counter-strike-2",
        category="account",
        kind="stock",
        sources={"lzt": load_fixture("lzt_steam.json")},
    )
    return CS2Resolver().resolve(request), request


@pytest.fixture(scope="class")
def output_dir() -> Path:
    out = _OUTPUT_ROOT
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True, exist_ok=True)
    return out


class TestCS2ImageRenderer:
    def test_media_strategy_generates_readable_balanced_grid(
        self,
        fixture_account,
        output_dir,
    ):
        account, request = fixture_account
        request.context[ctx.MEDIA_OUTPUT_DIR] = str(output_dir)

        renderer = SteamGameGridRenderer()
        renderer._load_game_image = _fake_steam_header  # type: ignore[method-assign]
        paths = CS2MediaStrategy(renderer=renderer).prepare(account, request)

        assert len(paths) == 1
        output_path = Path(paths[0])
        assert output_path.exists()
        assert output_path.stat().st_size > 0

        with Image.open(output_path) as image:
            image.load()
            assert image.width > 1200
            assert image.height > 1200
            assert 0.85 <= image.width / image.height <= 1.15

    def test_media_strategy_uses_cs2_fallback_when_games_are_missing(self, output_dir):
        request = PipelineRequest(
            game="counter-strike-2",
            category="account",
            kind="stock",
            context={ctx.MEDIA_OUTPUT_DIR: str(output_dir)},
        )
        account = CS2ResolvedAccount(item_id="fallback", hours_played=123, games=[])

        renderer = SteamGameGridRenderer()
        renderer._load_game_image = _fake_steam_header  # type: ignore[method-assign]
        paths = CS2MediaStrategy(renderer=renderer).prepare(account, request)

        assert len(paths) == 1
        output_path = Path(paths[0])
        assert output_path.exists()

        with Image.open(output_path) as image:
            image.load()
            assert image.width == 950
            assert image.height == 250

    def test_fixture_account_has_render_fields(self, fixture_account):
        account, _ = fixture_account

        assert account.item_id == "218341709"
        assert len(account.games) == 78

        sample = account.games[0]
        assert sample["appid"]
        assert sample["title"]
        assert sample["img"]
        assert "playtime_forever" in sample


def _fake_steam_header(url: str, app_id: str) -> Image.Image:
    digest = hashlib.sha1(f"{app_id}:{url}".encode("utf-8")).digest()
    base = tuple(35 + byte % 120 for byte in digest[:3])
    accent = tuple(115 + byte % 120 for byte in digest[3:6])

    image = Image.new("RGB", (150, 70), base)
    draw = ImageDraw.Draw(image)
    draw.rectangle((0, 0, 150, 16), fill=accent)
    draw.rectangle(
        (0, 54, 150, 70),
        fill=tuple(max(0, channel - 25) for channel in base),
    )
    draw.text((8, 27), str(app_id)[:12], fill=(245, 245, 245))
    return image
