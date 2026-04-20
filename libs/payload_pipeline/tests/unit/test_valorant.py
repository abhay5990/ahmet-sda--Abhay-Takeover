from __future__ import annotations

import pytest
from pathlib import Path

from payload_pipeline.core import context_keys as ctx
from payload_pipeline import PayloadPipeline, build_default_registry
from payload_pipeline.core.contracts import BuildContext, MediaBundle, PipelineRequest
from payload_pipeline.marketplaces.eldorado import EldoradoConfig
from payload_pipeline.marketplaces.g2g import G2GConfig
from payload_pipeline.games.val.account import (
    ValorantComposer,
    ValorantG2GBuilder,
    ValorantGameBoostBuilder,
    ValorantLztSourceAdapter,
    ValorantMediaStrategy,
    ValorantPlayerAuctionsBuilder,
    ValorantResolver,
)


def test_valorant_lzt_source_normalization_resolves_catalog_titles(load_fixture) -> None:
    source = ValorantLztSourceAdapter().parse(load_fixture("lzt_val.json"))

    assert source is not None
    assert source.region == "EU"
    assert source.level == 136
    assert source.skin_count == 81
    assert source.agent_count == 22
    assert source.buddy_count == 73
    assert source.tracker_url.startswith("https://tracker.gg/valorant/")
    assert "Kuronami no Yaiba" in source.skin_names
    assert "Viper" in source.agent_names


def test_valorant_resolver_and_composer_use_resolved_contract(load_fixture) -> None:
    raw = load_fixture("lzt_val.json")
    request = PipelineRequest(
        game="valorant",
        category="account",
        kind="stock",
        sources={"lzt": raw},
    )

    account = ValorantResolver().resolve(request)
    listing = ValorantComposer().compose(account, request, MediaBundle())

    assert account.display_rank == "Exp Gold 1"
    assert account.skin_count == 81
    assert account.agent_count == 22
    assert "EU" in listing.default.title
    assert "81 Skins" in listing.default.title
    assert "Exp Gold 1" in listing.default.title
    assert "Skin Count: 81" in listing.default.description
    assert "Has Warranty" in listing.default.description


def test_valorant_pipeline_builds_eldorado_payload(load_fixture) -> None:
    raw = load_fixture("lzt_val.json")
    pipeline = PayloadPipeline(registry=build_default_registry())

    _prepare_result = pipeline.prepare_once(
        PipelineRequest(
            game="valorant",
            category="account",
            kind="stock",
            sources={"lzt": raw},
        ),
    )
    assert _prepare_result.success, f"prepare_once failed: {_prepare_result.error}"
    prepared = _prepare_result.prepared
    result = pipeline.build(prepared, BuildContext(kind="stock", marketplace="eldorado"))

    assert result.success
    assert prepared.subject.region == "EU"
    assert result.payload["augmentedGame"]["gameId"] == "32"
    assert result.payload["augmentedGame"]["tradeEnvironmentId"] == "1-0"
    attrs = {a["id"]: a["value"] for a in result.payload["augmentedGame"]["offerAttributes"]}
    assert attrs["valorant-rank"] == "gold"
    assert result.payload["accountSecretDetails"]
    assert result.payload["details"]["offerTitle"]


def test_valorant_media_strategy_uses_resolved_preview_urls(load_fixture) -> None:
    raw = load_fixture("lzt_val.json")
    output_dir = Path("output/payload_pipeline/tests/valorant_media")
    request = PipelineRequest(
        game="valorant",
        category="account",
        kind="stock",
        sources={"lzt": raw},
        context={ctx.MEDIA_OUTPUT_DIR: str(output_dir)},
    )
    account = ValorantResolver().resolve(request)

    class StubDownloader:
        def download(self, preview_urls: dict[str, str], output_dir: str, item_id: str = "") -> list[str]:
            output_path = Path(output_dir)
            output_path.mkdir(parents=True, exist_ok=True)
            saved_paths: list[str] = []
            for category in sorted(preview_urls):
                file_path = output_path / f"{category}.png"
                file_path.write_bytes(b"stub")
                saved_paths.append(str(file_path))
            return saved_paths

    paths = ValorantMediaStrategy(downloader=StubDownloader()).prepare(account, request)

    assert len(paths) == 3
    assert all(Path(path).exists() for path in paths)


# ── G2G builder tests ──────────────────────────────────────────────


def test_valorant_pipeline_builds_g2g_payload(load_fixture) -> None:
    """Full pipeline with marketplace='g2g' produces a valid G2G payload."""
    raw = load_fixture("lzt_val.json")
    pipeline = PayloadPipeline(registry=build_default_registry())

    _prepare_result = pipeline.prepare_once(
        PipelineRequest(
            game="valorant",
            category="account",
            kind="stock",
            sources={"lzt": raw},
        ),
    )
    assert _prepare_result.success, f"prepare_once failed: {_prepare_result.error}"
    prepared = _prepare_result.prepared
    result = pipeline.build(prepared, BuildContext(kind="stock", marketplace="g2g", marketplace_config=G2GConfig(seller_id="1000959019")))

    assert result.success
    assert result.payload["brand_id"] == "lgc_game_24333"
    assert result.payload["delivery_speed"] == "instant"
    assert result.payload["currency"] == "USD"
    assert result.payload["title"]  # not empty
    assert result.payload["offer_attributes"]
    assert result.payload["unit_price"] > 0


def test_g2g_payload_uses_marketplace_override_title(load_fixture) -> None:
    """G2G builder picks up the g2g title override from the composer."""
    raw = load_fixture("lzt_val.json")
    request = PipelineRequest(
        game="valorant",
        category="account",
        kind="stock",
        sources={"lzt": raw},
    )

    account = ValorantResolver().resolve(request)
    listing = ValorantComposer().compose(account, request, MediaBundle())
    build_ctx = BuildContext(kind="stock", marketplace="g2g", marketplace_config=G2GConfig(seller_id="1000959019"))
    payload = ValorantG2GBuilder().build_payload(account, listing, build_ctx)

    g2g_content = listing.content_for("g2g")
    assert payload["title"] == g2g_content.title
    assert payload["title"]  # not empty


# ── Eldorado subplatform tests ──────────────────────────────────────


def test_eldorado_current_subplatform_overrides_environment(load_fixture) -> None:
    """When CURRENT_SUBPLATFORM is set, Eldorado uses that platform ID."""
    raw = load_fixture("lzt_val.json")
    pipeline = PayloadPipeline(registry=build_default_registry())

    _prepare_result = pipeline.prepare_once(
        PipelineRequest(
            game="valorant",
            category="account",
            kind="stock",
            sources={"lzt": raw},
        ),
    )
    assert _prepare_result.success, f"prepare_once failed: {_prepare_result.error}"
    prepared = _prepare_result.prepared
    result = pipeline.build(prepared, BuildContext(kind="stock", marketplace="eldorado", marketplace_config=EldoradoConfig(current_subplatform="PSN")))

    assert result.success
    # EU = region_id "1", PSN = platform "1"  →  "1-1"
    assert result.payload["augmentedGame"]["tradeEnvironmentId"] == "1-1"


def test_eldorado_subplatform_status_auto_selects_least_full(load_fixture) -> None:
    """When SUBPLATFORM_STATUS is provided, builder picks the least-full platform."""
    raw = load_fixture("lzt_val.json")
    pipeline = PayloadPipeline(registry=build_default_registry())

    _prepare_result = pipeline.prepare_once(
        PipelineRequest(
            game="valorant",
            category="account",
            kind="stock",
            sources={"lzt": raw},
        ),
    )
    assert _prepare_result.success, f"prepare_once failed: {_prepare_result.error}"
    prepared = _prepare_result.prepared
    result = pipeline.build(prepared, BuildContext(
        kind="stock",
        marketplace="eldorado",
        marketplace_config=EldoradoConfig(subplatform_status={
            "pc": {"available": 5, "percentage_used": 90.0},
            "psn": {"available": 40, "percentage_used": 20.0},
            "xbox": {"available": 20, "percentage_used": 60.0},
        }),
    ))

    assert result.success
    # PSN has lowest percentage_used → platform "1", EU region "1" → "1-1"
    assert result.payload["augmentedGame"]["tradeEnvironmentId"] == "1-1"


def test_eldorado_no_context_falls_back_to_default_platform(load_fixture) -> None:
    """Without any subplatform context, builder falls back to PC (platform 0)."""
    raw = load_fixture("lzt_val.json")
    pipeline = PayloadPipeline(registry=build_default_registry())

    _prepare_result = pipeline.prepare_once(
        PipelineRequest(
            game="valorant",
            category="account",
            kind="stock",
            sources={"lzt": raw},
        ),
    )
    assert _prepare_result.success, f"prepare_once failed: {_prepare_result.error}"
    prepared = _prepare_result.prepared
    result = pipeline.build(prepared, BuildContext(kind="stock", marketplace="eldorado"))

    assert result.success
    # EU = "1", default PC = "0" → "1-0"
    assert result.payload["augmentedGame"]["tradeEnvironmentId"] == "1-0"


# ── GameBoost builder tests ──────────────────────────────────────


def test_valorant_pipeline_builds_gameboost_payload(load_fixture) -> None:
    """Full pipeline with marketplace='gameboost' produces a valid GameBoost payload."""
    raw = load_fixture("lzt_val.json")
    pipeline = PayloadPipeline(registry=build_default_registry())

    _prepare_result = pipeline.prepare_once(
        PipelineRequest(
            game="valorant",
            category="account",
            kind="stock",
            sources={"lzt": raw},
        ),
    )
    assert _prepare_result.success, f"prepare_once failed: {_prepare_result.error}"
    prepared = _prepare_result.prepared
    result = pipeline.build(prepared, BuildContext(kind="stock", marketplace="gameboost"))

    assert result.success
    assert result.payload["game"] == "valorant"
    assert result.payload["title"]
    assert result.payload["slug"]
    assert result.payload["price"] > 0
    assert result.payload["account_data"]["server"] == "Europe"
    assert result.payload["account_data"]["level"] == 136
    assert result.payload["account_data"]["platforms"] == ["PC"]
    assert result.payload["game_items"]["agents"]
    assert result.payload["game_items"]["weapon-skins"]
    assert isinstance(result.payload["dump"], str)
    assert result.payload["login"]
    assert result.payload["delivery_instructions"]


def test_gameboost_dropshipping_mode_uses_manual_delivery(load_fixture) -> None:
    """Dropshipping mode sets is_manual=True and omits credentials."""
    raw = load_fixture("lzt_val.json")
    request = PipelineRequest(
        game="valorant",
        category="account",
        kind="dropshipping",
        sources={"lzt": raw},
    )

    account = ValorantResolver().resolve(request)
    listing = ValorantComposer().compose(account, request, MediaBundle())
    build_ctx = BuildContext(kind="dropshipping", marketplace="gameboost")
    payload = ValorantGameBoostBuilder().build_payload(account, listing, build_ctx)

    assert payload["is_manual"] is True
    assert payload["login"] is None
    assert payload["password"] is None
    assert payload["delivery_time"] == {"duration": 10, "unit": "minutes"}


# ── PlayerAuctions builder tests ─────────────────────────────────


def test_valorant_pipeline_builds_playerauctions_payload(load_fixture) -> None:
    """Full pipeline with marketplace='playerauctions' produces a valid payload."""
    raw = load_fixture("lzt_val.json")
    pipeline = PayloadPipeline(registry=build_default_registry())

    _prepare_result = pipeline.prepare_once(
        PipelineRequest(
            game="valorant",
            category="account",
            kind="stock",
            sources={"lzt": raw},
        ),
    )
    assert _prepare_result.success, f"prepare_once failed: {_prepare_result.error}"
    prepared = _prepare_result.prepared
    result = pipeline.build(prepared, BuildContext(kind="stock", marketplace="playerauctions"))

    assert result.success
    assert result.payload["game_name"] == "valorant"
    assert result.payload["game_id"] == 8470
    assert result.payload["server"] == ["EU"]
    assert result.payload["server_id"] == ["9128"]
    assert result.payload["title"]
    assert result.payload["price"] > 0
    assert result.payload["delivery_method"] == "instant"
    assert result.payload["delivery_instructions"]
    assert result.payload["cover_image_url"]


# ── Multi-marketplace / error tests ──────────────────────────────


def test_pipeline_builds_all_marketplace_payloads(load_fixture) -> None:
    """Building for every marketplace produces payloads for each."""
    raw = load_fixture("lzt_val.json")
    pipeline = PayloadPipeline(registry=build_default_registry())
    marketplaces = ["eldorado", "gameboost", "g2g", "playerauctions"]

    _prepare_result = pipeline.prepare_once(
        PipelineRequest(
            game="valorant",
            category="account",
            kind="stock",
            sources={"lzt": raw},
        ),
    )
    assert _prepare_result.success, f"prepare_once failed: {_prepare_result.error}"
    prepared = _prepare_result.prepared

    results = {}
    for mp in marketplaces:
        if mp == "g2g":
            build_ctx = BuildContext(kind="stock", marketplace=mp, marketplace_config=G2GConfig(seller_id="1000959019"))
        else:
            build_ctx = BuildContext(kind="stock", marketplace=mp)
        results[mp] = pipeline.build(prepared, build_ctx)

    assert set(results.keys()) == set(marketplaces)
    for mp, result in results.items():
        assert result.success
        assert result.payload  # not empty


def test_build_returns_error_for_unknown_marketplace(load_fixture) -> None:
    """Building for an unknown marketplace returns a failed PipelineResult."""
    raw = load_fixture("lzt_val.json")
    pipeline = PayloadPipeline(registry=build_default_registry())

    _prepare_result = pipeline.prepare_once(
        PipelineRequest(
            game="valorant",
            category="account",
            kind="stock",
            sources={"lzt": raw},
        ),
    )
    assert _prepare_result.success, f"prepare_once failed: {_prepare_result.error}"
    prepared = _prepare_result.prepared

    result = pipeline.build(prepared, BuildContext(kind="stock", marketplace="nonexistent"))
    assert not result.success
    assert result.error is not None
    assert result.error_stage == "registry"
    assert result.payload is None
