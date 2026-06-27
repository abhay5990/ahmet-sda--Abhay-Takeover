from __future__ import annotations

import pytest
from pathlib import Path

from payload_pipeline.core import context_keys as ctx
from payload_pipeline import PayloadPipeline, build_default_registry
from payload_pipeline.core.contracts import BuildContext, MediaBundle, PipelineRequest
from payload_pipeline.core.manual_fields import manual_field_registry
from payload_pipeline.marketplaces.eldorado import EldoradoConfig
from payload_pipeline.marketplaces.g2g import G2GConfig
from payload_pipeline.shared.paths import default_media_output_dir
from payload_pipeline.games.val.account import (
    ValorantComposer,
    ValorantEldoradoBuilder,
    ValorantG2GBuilder,
    ValorantGameBoostBuilder,
    ValorantLztSourceAdapter,
    ValorantMediaStrategy,
    ValorantPlayerAuctionsBuilder,
    ValorantResolver,
)

from _variant_ctx import (
    valorant_eldorado,
    valorant_gameboost,
    valorant_playerauctions,
)


def test_valorant_manual_field_specs_use_minimum_game_data() -> None:
    build_default_registry()
    fields = manual_field_registry.serialize("valorant")
    by_key = {field["key"]: field for field in fields}

    assert set(by_key) == {
        "region",
        "level",
        "current_rank",
        "peak_rank",
        "valorant_points",
        "radianite_points",
        "agent_count",
        "weapon_skin_count",
        "knife_count",
        "inventory_value",
        "account_tags",
    }
    assert "platform" not in by_key
    assert {option["value"] for option in by_key["region"]["options"]} >= {
        "na", "eu", "la", "br", "ap", "kr", "tr",
    }


def test_valorant_manual_fields_drive_marketplace_payloads() -> None:
    raw = {
        "source": "manual",
        "price": 12.5,
        "loginData": {"login": "valorant-user", "password": "secret-pass"},
        "manual_fields": {
            "region": "la",
            "level": 25,
            "current_rank": "gold",
            "peak_rank": "diamond",
            "valorant_points": 1200,
            "radianite_points": 80,
            "agent_count": 26,
            "weapon_skin_count": 100,
            "knife_count": 20,
            "inventory_value": 35000,
            "account_tags": ["rare_skins"],
        },
    }
    request = PipelineRequest(
        game="valorant",
        category="account",
        kind="stock",
        sources={"manual": raw},
    )

    account = ValorantResolver().resolve(request)
    listing = ValorantComposer().compose(account, request, MediaBundle())

    assert account.region == "la"
    assert account.level == 25
    assert account.current_rank == "Gold"
    assert account.last_rank == "Diamond"
    assert account.rank_type == "ranked"
    assert account.agent_count == 26
    assert account.skin_count == 100
    assert account.knife_count == 20
    assert account.inventory_value == 35000

    eldorado_payload = ValorantEldoradoBuilder().build_payload(
        account,
        listing,
        BuildContext(
            kind="stock",
            marketplace="eldorado",
            variant_context=valorant_eldorado(),
            selected_variants={"platform": "pc"},
        ),
    )
    attrs = {
        item["id"]: item["value"]
        for item in eldorado_payload["augmentedGame"]["offerAttributes"]
    }
    assert eldorado_payload["augmentedGame"]["tradeEnvironmentId"] == "2-0"
    assert attrs["valorant-rank"] == "gold"
    assert attrs["valorant-agents"] == "agents-26plus"
    assert attrs["valorant-weapon-skins"] == "100-plus-skins"
    assert attrs["valorant-knives"] == "knives-20plus"
    assert attrs["valorant-spent-points"] == "spent-35plus"

    gameboost_payload = ValorantGameBoostBuilder().build_payload(
        account,
        listing,
        BuildContext(
            kind="stock",
            marketplace="gameboost",
            variant_context=valorant_gameboost(),
        ),
    )
    assert gameboost_payload["account_data"]["server"] == "Latin America"
    assert gameboost_payload["account_data"]["current_tier"] == "Gold"
    assert gameboost_payload["account_data"]["peak_tier"] == "Diamond"
    assert gameboost_payload["account_data"]["level"] == 25
    assert gameboost_payload["account_data"]["valorant_points"] == 1200
    assert gameboost_payload["account_data"]["radianite_points"] == 80

    pa_payload = ValorantPlayerAuctionsBuilder().build_payload(
        account,
        listing,
        BuildContext(
            kind="stock",
            marketplace="playerauctions",
            variant_context=valorant_playerauctions(),
        ),
    )
    assert pa_payload["serverId"] == 9207
    assert pa_payload["autoDelivery"]["loginName"] == "valorant-user"


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
    result = pipeline.build(prepared, BuildContext(
        kind="stock", marketplace="eldorado",
        variant_context=valorant_eldorado(),
    ))

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
    output_dir = Path(default_media_output_dir("valorant", suffix="tests/valorant_media"))
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


# ── Eldorado platform selection tests ────────────────────────────────


def test_eldorado_selected_platform_overrides_default(load_fixture) -> None:
    """When selected_variants['platform'] is set, Eldorado uses that platform ID."""
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
        kind="stock", marketplace="eldorado",
        variant_context=valorant_eldorado(),
        selected_variants={"platform": "psn"},
    ))

    assert result.success
    # EU = region_id "1", PSN = platform "1"  →  "1-1"
    assert result.payload["augmentedGame"]["tradeEnvironmentId"] == "1-1"


def test_eldorado_backend_selected_platform_is_used(load_fixture) -> None:
    """When backend passes selected_variants, builder uses that platform slug."""
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
    # Platform selection now happens in the backend (VariantRouter);
    # pipeline receives the already-selected variant slug.
    result = pipeline.build(prepared, BuildContext(
        kind="stock",
        marketplace="eldorado",
        variant_context=valorant_eldorado(),
        selected_variants={"platform": "psn"},  # backend chose PSN
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
    result = pipeline.build(prepared, BuildContext(
        kind="stock", marketplace="eldorado",
        variant_context=valorant_eldorado(),
    ))

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
    result = pipeline.build(prepared, BuildContext(
        kind="stock", marketplace="gameboost",
        variant_context=valorant_gameboost(),
    ))

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
    build_ctx = BuildContext(
        kind="dropshipping", marketplace="gameboost",
        variant_context=valorant_gameboost(),
    )
    payload = ValorantGameBoostBuilder().build_payload(account, listing, build_ctx)

    assert payload["is_manual"] is True
    assert payload["login"] is None
    assert payload["password"] is None
    assert payload["delivery_time"] == {"duration": 10, "unit": "minutes"}


# ── PlayerAuctions builder tests ─────────────────────────────────


def test_valorant_pipeline_builds_playerauctions_payload(load_fixture) -> None:
    """Full pipeline with marketplace='playerauctions' produces a valid single-post payload."""
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
        kind="stock", marketplace="playerauctions",
        variant_context=valorant_playerauctions(),
    ))

    assert result.success
    assert result.payload["gameId"] == 9078
    assert result.payload["price"] > 0
    assert result.payload["title"]
    assert result.payload["isAuto"] is True
    assert result.payload["autoDelivery"]["loginName"]
    assert result.payload["autoDelivery"]["password"]


def test_valorant_playerauctions_description_includes_album_url(load_fixture) -> None:
    """PA uses description-hosted image links instead of screenshot fields."""
    raw = load_fixture("lzt_val.json")
    request = PipelineRequest(
        game="valorant",
        category="account",
        kind="stock",
        sources={"lzt": raw},
    )
    account = ValorantResolver().resolve(request)
    listing = ValorantComposer().compose(
        account,
        request,
        MediaBundle(album_url="https://imageshack.com/a/test-album"),
    )
    build_ctx = BuildContext(
        kind="stock",
        marketplace="playerauctions",
        variant_context=valorant_playerauctions(),
    )

    builder = ValorantPlayerAuctionsBuilder()
    payload = builder.build_payload(account, listing, build_ctx)
    row = builder.build_bulk_payload(account, listing, build_ctx)

    assert "Images Link" in payload["offerDesc"]
    assert "imageshack.com/a/test-album" in payload["offerDesc"]
    assert "Images Link" in row["Description"]
    assert "imageshack.com/a/test-album" in row["Description"]
    assert payload["screenShot"] == ""
    assert row["Cover image (PA hosted)"] == ""


def test_valorant_pipeline_builds_playerauctions_bulk_payload(load_fixture) -> None:
    """Full pipeline build_bulk produces Excel row dict matching PA template columns."""
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
    result = pipeline.build_bulk(prepared, BuildContext(
        kind="stock", marketplace="playerauctions",
        variant_context=valorant_playerauctions(),
    ))

    assert result.success
    row = result.payload

    # PA template column keys
    assert row["Game"] == "Valorant"
    assert row["Server"] == "EU"
    assert row["Listing Price"] > 0
    assert row["Title"]
    assert row["Description"]
    assert row["Delivery Method"] == "Automatic"
    assert row["Login name  (Auto)"]  # double space is PA requirement
    assert row["Password"]
    assert row["First name"]
    assert row["Last name"]
    assert row["Email"]
    assert row["Country"]
    assert row["Birth Date"] == "1995/1/1"
    assert row["Seller After-Sale Protection"] == 7
    assert row["Offer Duration"] == 30

    # Stock mode: auto delivery fields populated, manual delivery empty
    assert row["Login name"] == ""
    assert row["Delivery info"] == ""


# ── Phase C: composite ID correctness ────────────────────────────


def test_eldorado_composite_id_na_plus_pc() -> None:
    """NA + PC → '0-0'."""
    from payload_pipeline.games.val.account.marketplaces.eldorado import (
        ValorantEldoradoBuilder,
    )
    ctx = BuildContext(
        kind="stock", marketplace="eldorado",
        variant_context=valorant_eldorado(),
        selected_variants={"platform": "pc"},
    )
    assert ValorantEldoradoBuilder._resolve_trade_environment_id("NA", ctx) == "0-0"


def test_eldorado_composite_id_ap_plus_xbox() -> None:
    """AP + Xbox → '5-2'."""
    from payload_pipeline.games.val.account.marketplaces.eldorado import (
        ValorantEldoradoBuilder,
    )
    ctx = BuildContext(
        kind="stock", marketplace="eldorado",
        variant_context=valorant_eldorado(),
        selected_variants={"platform": "xbox"},
    )
    assert ValorantEldoradoBuilder._resolve_trade_environment_id("AP", ctx) == "5-2"


def test_eldorado_composite_id_kr_plus_psn() -> None:
    """KR + PSN → '6-1'."""
    from payload_pipeline.games.val.account.marketplaces.eldorado import (
        ValorantEldoradoBuilder,
    )
    ctx = BuildContext(
        kind="stock", marketplace="eldorado",
        variant_context=valorant_eldorado(),
        selected_variants={"platform": "psn"},
    )
    assert ValorantEldoradoBuilder._resolve_trade_environment_id("KR", ctx) == "6-1"


def test_eldorado_composite_id_unknown_region_returns_sentinel() -> None:
    """Unknown region → '1-999' sentinel regardless of platform."""
    from payload_pipeline.games.val.account.marketplaces.eldorado import (
        ValorantEldoradoBuilder,
    )
    ctx = BuildContext(
        kind="stock", marketplace="eldorado",
        variant_context=valorant_eldorado(),
        selected_variants={"platform": "pc"},
    )
    assert ValorantEldoradoBuilder._resolve_trade_environment_id("XX", ctx) == "1-999"


def test_pa_builder_ignores_selected_platform(load_fixture) -> None:
    """PA builder output is unaffected by selected_variants['platform'] — uses region only."""
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
    assert _prepare_result.success
    prepared = _prepare_result.prepared

    result_no_platform = pipeline.build(prepared, BuildContext(
        kind="stock", marketplace="playerauctions",
        variant_context=valorant_playerauctions(),
    ))
    result_with_platform = pipeline.build(prepared, BuildContext(
        kind="stock", marketplace="playerauctions",
        variant_context=valorant_playerauctions(),
        selected_variants={"platform": "psn"},
    ))

    assert result_no_platform.success
    assert result_with_platform.success
    # Both payloads must be identical — platform has no effect on PA
    assert result_no_platform.payload == result_with_platform.payload


def test_gb_builder_ignores_selected_platform(load_fixture) -> None:
    """GB builder output is unaffected by selected_variants['platform'] — uses region only."""
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
    assert _prepare_result.success
    prepared = _prepare_result.prepared

    result_no_platform = pipeline.build(prepared, BuildContext(
        kind="stock", marketplace="gameboost",
        variant_context=valorant_gameboost(),
    ))
    result_with_platform = pipeline.build(prepared, BuildContext(
        kind="stock", marketplace="gameboost",
        variant_context=valorant_gameboost(),
        selected_variants={"platform": "psn"},
    ))

    assert result_no_platform.success
    assert result_with_platform.success
    assert result_no_platform.payload == result_with_platform.payload


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

    _variant_ctxs = {
        "eldorado": valorant_eldorado(),
        "gameboost": valorant_gameboost(),
        "playerauctions": valorant_playerauctions(),
    }
    results = {}
    for mp in marketplaces:
        if mp == "g2g":
            build_ctx = BuildContext(kind="stock", marketplace=mp, marketplace_config=G2GConfig(seller_id="1000959019"))
        else:
            build_ctx = BuildContext(kind="stock", marketplace=mp, variant_context=_variant_ctxs.get(mp))
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
