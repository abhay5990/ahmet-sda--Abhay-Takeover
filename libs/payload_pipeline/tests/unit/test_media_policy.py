from __future__ import annotations

from payload_pipeline.core import context_keys as ctx
from payload_pipeline.core.contracts import PipelineRequest
from payload_pipeline.shared.media_policy import MediaSource, media_source_order


def test_stock_defaults_to_lzt_first() -> None:
    request = PipelineRequest(game="fortnite", kind="stock")

    assert media_source_order(request) == (MediaSource.LZT, MediaSource.GENERATED)


def test_dropshipping_defaults_to_generated_first() -> None:
    request = PipelineRequest(game="fortnite", kind="dropshipping")

    assert media_source_order(request) == (MediaSource.GENERATED, MediaSource.LZT)


def test_policy_accepts_lolz_alias() -> None:
    request = PipelineRequest(
        game="fortnite",
        kind="dropshipping",
        context={ctx.MEDIA_SOURCE_POLICY: "lolz"},
    )

    assert media_source_order(request) == (MediaSource.LZT,)


def test_policy_accepts_generated_only_override() -> None:
    request = PipelineRequest(
        game="fortnite",
        kind="stock",
        context={ctx.MEDIA_SOURCE_POLICY: "generated"},
    )

    assert media_source_order(request) == (MediaSource.GENERATED,)
