"""Integration tests for the Valorant generated image renderer.

The renderer downloads Valorant API icons into the shared image cache when
available. If the network is unavailable, it still produces placeholder cards.

    pytest tests/integration/test_val_image_renderer.py -v
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest
from PIL import Image

from payload_pipeline.core import context_keys as ctx
from payload_pipeline.core.contracts import PipelineRequest
from payload_pipeline.games.val.account.media.strategy import ValorantMediaStrategy
from payload_pipeline.games.val.account.resolver import ValorantResolver
from payload_pipeline.shared.paths import default_media_output_dir

_OUTPUT_ROOT = Path(default_media_output_dir("valorant", suffix="test_val_grid"))


@pytest.fixture()
def fixture_account(load_fixture):
    request = PipelineRequest(
        game="valorant",
        category="account",
        kind="stock",
        sources={"lzt": load_fixture("lzt_val.json")},
        context={ctx.MEDIA_SOURCE_POLICY: "generated"},
    )
    return ValorantResolver().resolve(request), request


@pytest.fixture(scope="class")
def output_dir() -> Path:
    out = _OUTPUT_ROOT
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True, exist_ok=True)
    return out


class TestValorantImageRenderer:
    def test_media_strategy_generates_inventory_grids(self, fixture_account, output_dir):
        account, request = fixture_account
        request.context[ctx.MEDIA_OUTPUT_DIR] = str(output_dir)

        paths = ValorantMediaStrategy().prepare(account, request)

        assert len(paths) == 3
        manifest = {"item_id": account.item_id, "files": []}
        for path in paths:
            output_path = Path(path)
            assert output_path.exists()
            assert output_path.stat().st_size > 0

            with Image.open(output_path) as image:
                image.load()
                assert image.width >= 300
                assert image.height >= 200
                assert 0.65 <= image.width / image.height <= 1.85
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

    def test_fixture_account_has_render_fields(self, fixture_account):
        account, _ = fixture_account

        assert account.skin_count == 81
        assert account.agent_count == 22
        assert account.buddy_count == 73
        assert len(account.skin_names) > 0
        assert len(account.agent_names) > 0
        assert len(account.buddy_names) > 0
