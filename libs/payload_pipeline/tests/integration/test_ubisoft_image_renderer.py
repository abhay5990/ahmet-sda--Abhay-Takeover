"""Integration tests for the Ubisoft Connect image renderer.

The renderer normally downloads Ubisoft header art into the shared image cache.
These tests use deterministic in-memory headers so the layout contract is not
coupled to CDN availability.

    pytest tests/integration/test_ubisoft_image_renderer.py -v
"""

from __future__ import annotations

import hashlib
import shutil
from pathlib import Path

import pytest
from PIL import Image, ImageDraw

from payload_pipeline.core import context_keys as ctx
from payload_pipeline.core.contracts import PipelineRequest
from payload_pipeline.games.ubisoft_connect.account.media.image_renderer import (
    UbisoftImageRenderer,
)
from payload_pipeline.games.ubisoft_connect.account.media.strategy import (
    UbisoftMediaStrategy,
)
from payload_pipeline.games.ubisoft_connect.account.resolver import UbisoftResolver
from payload_pipeline.shared.paths import default_media_output_dir

_OUTPUT_ROOT = Path(default_media_output_dir("ubisoft-connect", suffix="test_ubisoft_grid"))


@pytest.fixture()
def fixture_account(load_fixture):
    request = PipelineRequest(
        game="ubisoft-connect",
        category="account",
        kind="stock",
        sources={"lzt": load_fixture("lzt_ubisoft_connect.json")},
    )
    return UbisoftResolver().resolve(request), request


@pytest.fixture(scope="class")
def output_dir() -> Path:
    out = _OUTPUT_ROOT
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True, exist_ok=True)
    return out


class TestUbisoftImageRenderer:
    def test_media_strategy_generates_readable_balanced_grid(
        self,
        fixture_account,
        output_dir,
    ):
        account, request = fixture_account
        request.context[ctx.MEDIA_OUTPUT_DIR] = str(output_dir)

        renderer = UbisoftImageRenderer()
        renderer._load_game_image = _fake_ubisoft_header  # type: ignore[method-assign]
        paths = UbisoftMediaStrategy(renderer=renderer).prepare(account, request)

        assert len(paths) == 1
        output_path = Path(paths[0])
        assert output_path.exists()
        assert output_path.stat().st_size > 0

        with Image.open(output_path) as image:
            image.load()
            assert image.width == 610
            assert image.height == 550
            assert 0.95 <= image.width / image.height <= 1.25

    def test_render_returns_none_for_empty(self, output_dir):
        renderer = UbisoftImageRenderer()

        result = renderer.render({}, str(output_dir / "empty.png"))

        assert result is None

    def test_grid_columns_are_dynamic(self, fixture_account):
        account, _ = fixture_account
        renderer = UbisoftImageRenderer()

        assert len(account.games) == 9
        assert renderer._grid_columns(len(account.games)) == 3

    def test_fixture_account_has_render_fields(self, fixture_account):
        account, _ = fixture_account

        assert account.item_id == "221639380"
        assert len(account.games) == 9

        sample = next(iter(account.games.values()))
        assert sample["gameId"]
        assert sample["title"]
        assert sample["img"]


def _fake_ubisoft_header(url: str, game_id: str) -> Image.Image:
    digest = hashlib.sha1(f"{game_id}:{url}".encode("utf-8")).digest()
    base = tuple(35 + byte % 120 for byte in digest[:3])
    accent = tuple(115 + byte % 120 for byte in digest[3:6])

    image = Image.new("RGB", (150, 70), base)
    draw = ImageDraw.Draw(image)
    draw.rectangle((0, 0, 150, 18), fill=accent)
    draw.rectangle(
        (0, 54, 150, 70),
        fill=tuple(max(0, channel - 25) for channel in base),
    )
    draw.text((8, 28), game_id[:12], fill=(245, 245, 245))
    return image
