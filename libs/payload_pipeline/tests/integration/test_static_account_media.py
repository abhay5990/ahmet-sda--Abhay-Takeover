"""Integration tests for bundled static account media strategies."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest
from PIL import Image

from payload_pipeline import PayloadPipeline, build_default_registry
from payload_pipeline.core import context_keys as ctx
from payload_pipeline.core.contracts import PipelineRequest


@pytest.mark.parametrize(
    ("game", "fixture_name", "resource_path"),
    [
        (
            "roblox",
            "lzt_roblox.json",
            Path("libs/payload_pipeline/payload_pipeline/games/roblox/account/resources/media/account.png"),
        ),
        (
            "genshin-impact",
            "lzt_gi.json",
            Path("libs/payload_pipeline/payload_pipeline/games/gi/account/resources/media/account.png"),
        ),
        (
            "grand-theft-auto-5",
            "lzt_gtav.json",
            Path("libs/payload_pipeline/payload_pipeline/games/gtav/account/resources/media/account.png"),
        ),
    ],
)
def test_static_account_media_uses_bundled_resource_path(
    load_fixture,
    game: str,
    fixture_name: str,
    resource_path: Path,
) -> None:
    output_dir = Path("output") / "static-media-unused" / game
    if output_dir.exists():
        shutil.rmtree(output_dir)

    request = PipelineRequest(
        game=game,
        category="account",
        kind="stock",
        sources={"lzt": load_fixture(fixture_name)},
        context={ctx.MEDIA_OUTPUT_DIR: str(output_dir)},
    )

    result = PayloadPipeline(registry=build_default_registry()).prepare_once(request)

    assert result.success, result.error
    assert result.prepared is not None
    assert len(result.prepared.media.local_paths) == 1

    media_path = Path(result.prepared.media.local_paths[0])
    assert media_path.resolve() == resource_path.resolve()
    assert media_path.name == "account.png"
    assert media_path.suffix == ".png"
    assert media_path.exists()
    assert media_path.stat().st_size > 0
    assert not output_dir.exists()

    with Image.open(media_path) as image:
        image.load()
        assert image.width == 1280
        assert image.height == 720


def test_static_account_media_respects_disable_media(load_fixture) -> None:
    request = PipelineRequest(
        game="roblox",
        category="account",
        kind="stock",
        sources={"lzt": load_fixture("lzt_roblox.json")},
        context={ctx.DISABLE_MEDIA: True},
    )

    result = PayloadPipeline(registry=build_default_registry()).prepare_once(request)

    assert result.success, result.error
    assert result.prepared is not None
    assert result.prepared.media.local_paths == []
