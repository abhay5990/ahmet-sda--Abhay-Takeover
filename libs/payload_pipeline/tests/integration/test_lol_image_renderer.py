"""Integration tests for the League of Legends image renderer.

The renderer fetches champion and skin splash art from external CDNs and
caches them on disk. These tests require network access on the first run;
subsequent runs use the persistent cache.

    pytest tests/integration/test_lol_image_renderer.py -v
"""

from __future__ import annotations

import json
import os
import shutil
from pathlib import Path

import pytest
from PIL import Image

from payload_pipeline.core.contracts import PipelineRequest
from payload_pipeline.games.lol.account.media.strategy import LolMediaStrategy
from payload_pipeline.games.lol.account.resolver import LolResolver
from payload_pipeline.shared.paths import default_media_output_dir
from payload_pipeline.core import context_keys as ctx

_OUTPUT_ROOT = Path(default_media_output_dir("league-of-legends", suffix="test_lol_grid"))
_COMPARISON_ROOT = Path(
    default_media_output_dir("league-of-legends", suffix="lol_renderer_comparison")
)


@pytest.fixture()
def fixture_account(load_fixture):
    request = PipelineRequest(
        game="league-of-legends",
        category="account",
        kind="stock",
        sources={
            "lzt": load_fixture("lzt_lol.json"),
        },
    )
    return LolResolver().resolve(request), request


@pytest.fixture(scope="class")
def output_dir() -> Path:
    out = _OUTPUT_ROOT
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True, exist_ok=True)
    return out


class TestLolImageRenderer:
    def test_media_strategy_generates_images(self, fixture_account, output_dir):
        account, request = fixture_account
        request.context[ctx.MEDIA_OUTPUT_DIR] = str(output_dir)

        strategy = LolMediaStrategy()
        paths = strategy.prepare(account, request)

        assert len(paths) > 0
        for p in paths:
            output_path = Path(p)
            assert output_path.exists()
            assert output_path.stat().st_size > 0

            with Image.open(output_path) as image:
                image.load()
                assert image.width >= 300
                assert image.height >= 200
                assert 0.75 <= image.width / image.height <= 1.75

    def test_account_has_champions_and_skins(self, fixture_account):
        account, _ = fixture_account
        assert len(account.champion_ids) > 0
        assert len(account.skin_ids) > 0

    def test_render_snapshot_for_visual_comparison(self, fixture_account):
        account, request = fixture_account
        label = os.environ.get("LOL_RENDER_COMPARISON_LABEL", "current").strip() or "current"
        output_dir = _COMPARISON_ROOT / label
        if output_dir.exists():
            shutil.rmtree(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)

        request.context[ctx.MEDIA_OUTPUT_DIR] = str(output_dir)
        paths = LolMediaStrategy().prepare(account, request)

        assert len(paths) == 2
        manifest = {
            "label": label,
            "item_id": account.item_id,
            "files": [],
        }
        for path in paths:
            output_path = Path(path)
            assert output_path.exists()
            assert output_path.stat().st_size > 0

            with Image.open(output_path) as image:
                image.load()
                manifest["files"].append(
                    {
                        "name": output_path.name,
                        "width": image.width,
                        "height": image.height,
                        "bytes": output_path.stat().st_size,
                    }
                )

        (output_dir / "manifest.json").write_text(
            json.dumps(manifest, indent=2, sort_keys=True),
            encoding="utf-8",
        )
