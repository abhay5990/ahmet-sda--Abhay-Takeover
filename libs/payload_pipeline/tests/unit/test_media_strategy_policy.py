from __future__ import annotations

from payload_pipeline.core import context_keys as ctx
from payload_pipeline.core.contracts import PipelineRequest
from payload_pipeline.games.fn.account.media.strategy import FortniteMediaStrategy
from payload_pipeline.games.fn.account.models import CosmeticItem, FortniteResolvedAccount
from payload_pipeline.games.val.account.media.strategy import ValorantMediaStrategy
from payload_pipeline.games.val.account.models import ValorantResolvedAccount


class StubDownloader:
    def download(
        self,
        preview_urls: dict[str, str],
        output_dir: str,
        item_id: str = "",
    ) -> list[str]:
        return [f"{output_dir}/lzt.png"]


class StubRenderer:
    def render_all(
        self,
        cosmetics: dict[str, list[CosmeticItem]],
        output_dir: str,
    ) -> list[str]:
        return [f"{output_dir}/generated.png"]


def test_fortnite_stock_prefers_lzt_media() -> None:
    account = FortniteResolvedAccount(
        item_id="fn-1",
        cosmetic_items={
            "outfit": [
                CosmeticItem(
                    id="cid_1",
                    title="Skin",
                    rarity="rare",
                    type="outfit",
                )
            ]
        },
        preview_urls={"skins": "https://example.test/skins.png"},
    )
    request = PipelineRequest(
        game="fortnite",
        kind="stock",
        context={ctx.MEDIA_OUTPUT_DIR: "out"},
    )

    paths = FortniteMediaStrategy(
        downloader=StubDownloader(),
        renderer=StubRenderer(),
    ).prepare(account, request)

    assert paths == ["out/lzt.png"]


def test_fortnite_dropshipping_prefers_generated_media() -> None:
    account = FortniteResolvedAccount(
        item_id="fn-1",
        cosmetic_items={
            "outfit": [
                CosmeticItem(
                    id="cid_1",
                    title="Skin",
                    rarity="rare",
                    type="outfit",
                )
            ]
        },
        preview_urls={"skins": "https://example.test/skins.png"},
    )
    request = PipelineRequest(
        game="fortnite",
        kind="dropshipping",
        context={ctx.MEDIA_OUTPUT_DIR: "out"},
    )

    paths = FortniteMediaStrategy(
        downloader=StubDownloader(),
        renderer=StubRenderer(),
    ).prepare(account, request)

    assert paths == ["out/generated.png"]


def test_valorant_generated_only_does_not_fall_back_to_lzt() -> None:
    account = ValorantResolvedAccount(
        item_id="val-1",
        preview_urls={"weapons": "https://example.test/weapons.png"},
    )
    request = PipelineRequest(
        game="valorant",
        kind="stock",
        context={ctx.MEDIA_SOURCE_POLICY: "generated"},
    )

    paths = ValorantMediaStrategy(downloader=StubDownloader()).prepare(account, request)

    assert paths == []
