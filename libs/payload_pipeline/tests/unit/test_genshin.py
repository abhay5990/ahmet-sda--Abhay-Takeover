"""Tests for the Genshin Impact (gi) account slice."""

from __future__ import annotations

from payload_pipeline import PayloadPipeline
from payload_pipeline.core.contracts import BuildContext, MediaBundle, PipelineRequest
from payload_pipeline.core.registry import PipelineRegistry
from payload_pipeline.games.gi.account import (
    GenshinComposer,
    GenshinImpactEldoradoBuilder,
    GenshinImpactGameBoostBuilder,
    GenshinImpactPlayerAuctionsBuilder,
    GenshinLztSourceAdapter,
    GenshinResolver,
    register,
)


def _build_registry() -> PipelineRegistry:
    """Build a registry containing only the Genshin slice."""
    registry = PipelineRegistry()
    register(registry)
    return registry


# ── Source normalization ──────────────────────────────────────────


def test_lzt_source_parses_core_genshin_fields(load_fixture) -> None:
    source = GenshinLztSourceAdapter().parse(load_fixture("lzt_gi.json"))

    assert source is not None
    assert source.region == "eu"
    assert source.genshin_level == 50
    assert source.genshin_character_count == 42
    assert source.genshin_legendary_characters == 7
    assert source.genshin_constellations == 2
    assert source.genshin_legendary_weapons == 4
    assert source.genshin_achievement_count == 459
    assert source.genshin_activity_days == 266
    assert source.genshin_currency == 0


def test_lzt_source_parses_honkai_fields(load_fixture) -> None:
    source = GenshinLztSourceAdapter().parse(load_fixture("lzt_gi.json"))

    assert source is not None
    assert source.honkai_level == 54
    assert source.honkai_character_count == 25
    assert source.honkai_legendary_characters == 7
    assert source.honkai_eidolons == 0
    assert source.honkai_legendary_weapons == 1


def test_lzt_source_parses_zenless_fields(load_fixture) -> None:
    source = GenshinLztSourceAdapter().parse(load_fixture("lzt_gi.json"))

    assert source is not None
    assert source.zenless_level == 0
    assert source.zenless_character_count == 0


def test_lzt_source_parses_credentials(load_fixture) -> None:
    source = GenshinLztSourceAdapter().parse(load_fixture("lzt_gi.json"))

    assert source is not None
    assert source.credentials.login == "popatemaran2dk7@outlook.com"
    assert source.credentials.password == "Rfhbyf1717"
    assert source.credentials.email_login == "popatemaran2dk7@outlook.com"
    assert source.credentials.email_password == "yd2YFsI8fsuY"


def test_lzt_source_returns_none_for_empty_data() -> None:
    assert GenshinLztSourceAdapter().parse(None) is None
    assert GenshinLztSourceAdapter().parse({}) is None


# ── Resolver ─────────────────────────────────────────────────────


def test_resolver_produces_resolved_account(load_fixture) -> None:
    raw = load_fixture("lzt_gi.json")
    request = PipelineRequest(
        game="genshin-impact",
        category="account",
        kind="stock",
        sources={"lzt": raw},
    )

    account = GenshinResolver().resolve(request)

    assert account.region == "eu"
    assert account.genshin_level == 50
    assert account.genshin_character_count == 42
    assert account.genshin_legendary_characters == 7
    assert account.genshin_legendary_weapons == 4
    assert account.honkai_level == 54
    assert account.zenless_level == 0
    assert account.has_email_access is True
    assert account.price == 10.64
    assert account.credentials.login == "popatemaran2dk7@outlook.com"


# ── Composer ─────────────────────────────────────────────────────


def test_composer_generates_title_and_description(load_fixture) -> None:
    raw = load_fixture("lzt_gi.json")
    request = PipelineRequest(
        game="genshin-impact",
        category="account",
        kind="stock",
        sources={"lzt": raw},
    )

    account = GenshinResolver().resolve(request)
    listing = GenshinComposer().compose(account, request, MediaBundle())

    assert "AR50" in listing.default.title
    assert "7 Legendary" in listing.default.title
    assert "S4G" in listing.default.title
    assert "Adventure Experience: 50" in listing.default.description
    assert "Legendary Characters: 7" in listing.default.description
    assert "Honkai Star Rail" in listing.default.description
    assert "Trailblaze Level: 54" in listing.default.description


# ── Eldorado builder ─────────────────────────────────────────────


def test_eldorado_payload_has_correct_game_id(load_fixture) -> None:
    raw = load_fixture("lzt_gi.json")
    pipeline = PayloadPipeline(registry=_build_registry())
    request = PipelineRequest(
        game="genshin-impact",
        category="account",
        kind="stock",
        sources={"lzt": raw},
    )

    _prepare_result = pipeline.prepare_once(request)
    assert _prepare_result.success, f"prepare_once failed: {_prepare_result.error}"
    prepared = _prepare_result.prepared
    result = pipeline.build(prepared, BuildContext(kind="stock", marketplace="eldorado"))
    assert result.success

    assert result.payload["augmentedGame"]["gameId"] == "39"
    assert result.payload["augmentedGame"]["category"] == "Account"


def test_eldorado_trade_environment_maps_eu_region(load_fixture) -> None:
    raw = load_fixture("lzt_gi.json")
    pipeline = PayloadPipeline(registry=_build_registry())
    request = PipelineRequest(
        game="genshin-impact",
        category="account",
        kind="stock",
        sources={"lzt": raw},
    )

    _prepare_result = pipeline.prepare_once(request)
    assert _prepare_result.success, f"prepare_once failed: {_prepare_result.error}"
    prepared = _prepare_result.prepared
    result = pipeline.build(prepared, BuildContext(kind="stock", marketplace="eldorado"))
    assert result.success

    assert result.payload["augmentedGame"]["tradeEnvironmentId"] == "1"


def test_eldorado_payload_includes_credentials(load_fixture) -> None:
    raw = load_fixture("lzt_gi.json")
    pipeline = PayloadPipeline(registry=_build_registry())
    request = PipelineRequest(
        game="genshin-impact",
        category="account",
        kind="stock",
        sources={"lzt": raw},
    )

    _prepare_result = pipeline.prepare_once(request)
    assert _prepare_result.success, f"prepare_once failed: {_prepare_result.error}"
    prepared = _prepare_result.prepared
    result = pipeline.build(prepared, BuildContext(kind="stock", marketplace="eldorado"))
    assert result.success

    assert result.payload["accountSecretDetails"]
    assert result.payload["details"]["hasOriginalEmail"] is False
    assert result.payload["details"]["offerTitle"]
    assert result.payload["details"]["description"]


# ── GameBoost builder ────────────────────────────────────────────


def test_gameboost_payload_core_fields(load_fixture) -> None:
    raw = load_fixture("lzt_gi.json")
    pipeline = PayloadPipeline(registry=_build_registry())
    request = PipelineRequest(
        game="genshin-impact",
        category="account",
        kind="stock",
        sources={"lzt": raw},
    )

    _prepare_result = pipeline.prepare_once(request)
    assert _prepare_result.success, f"prepare_once failed: {_prepare_result.error}"
    prepared = _prepare_result.prepared
    result = pipeline.build(prepared, BuildContext(kind="stock", marketplace="gameboost"))
    assert result.success

    assert result.payload["game"] == "genshin-impact"
    assert result.payload["title"]
    assert result.payload["slug"]
    assert result.payload["price"] > 0
    assert result.payload["login"]
    assert result.payload["delivery_instructions"]


def test_gameboost_account_data_fields(load_fixture) -> None:
    raw = load_fixture("lzt_gi.json")
    request = PipelineRequest(
        game="genshin-impact",
        category="account",
        kind="stock",
        sources={"lzt": raw},
    )

    account = GenshinResolver().resolve(request)
    listing = GenshinComposer().compose(account, request, MediaBundle())
    build_ctx = BuildContext(kind="stock", marketplace="gameboost")
    payload = GenshinImpactGameBoostBuilder().build_payload(account, listing, build_ctx)

    ad = payload["account_data"]
    assert ad["server"] == "Europe"
    assert ad["adventure_rank"] == 50
    assert ad["email_not_linked"] is False
    assert "characters" not in ad
    assert "five_star_characters" not in ad
    assert "five_star_weapons" not in ad
    assert "honkai_trailblaze_level" not in ad


def test_gameboost_dropshipping_mode(load_fixture) -> None:
    raw = load_fixture("lzt_gi.json")
    request = PipelineRequest(
        game="genshin-impact",
        category="account",
        kind="dropshipping",
        sources={"lzt": raw},
    )

    account = GenshinResolver().resolve(request)
    listing = GenshinComposer().compose(account, request, MediaBundle())
    build_ctx = BuildContext(kind="dropshipping", marketplace="gameboost")
    payload = GenshinImpactGameBoostBuilder().build_payload(account, listing, build_ctx)

    assert payload["is_manual"] is True
    assert payload["login"] is None
    assert payload["password"] is None
    assert payload["delivery_time"] == {"duration": 10, "unit": "minutes"}


# ── PlayerAuctions builder ───────────────────────────────────────


def test_playerauctions_payload_core_fields(load_fixture) -> None:
    raw = load_fixture("lzt_gi.json")
    pipeline = PayloadPipeline(registry=_build_registry())
    request = PipelineRequest(
        game="genshin-impact",
        category="account",
        kind="stock",
        sources={"lzt": raw},
    )

    _prepare_result = pipeline.prepare_once(request)
    assert _prepare_result.success, f"prepare_once failed: {_prepare_result.error}"
    prepared = _prepare_result.prepared
    result = pipeline.build(prepared, BuildContext(kind="stock", marketplace="playerauctions"))
    assert result.success

    assert result.payload["game_name"] == "genshin-impact"
    assert result.payload["game_id"] == 8480
    assert result.payload["server"] == ["EU"]
    assert result.payload["title"]
    assert result.payload["price"] > 0
    assert result.payload["delivery_method"] == "instant"
    assert result.payload["delivery_instructions"]
    assert result.payload["cover_image_url"]


def test_playerauctions_dropshipping_uses_manual_delivery(load_fixture) -> None:
    raw = load_fixture("lzt_gi.json")
    request = PipelineRequest(
        game="genshin-impact",
        category="account",
        kind="dropshipping",
        sources={"lzt": raw},
    )

    account = GenshinResolver().resolve(request)
    listing = GenshinComposer().compose(account, request, MediaBundle())
    build_ctx = BuildContext(kind="dropshipping", marketplace="playerauctions")
    payload = GenshinImpactPlayerAuctionsBuilder().build_payload(account, listing, build_ctx)

    assert payload["delivery_method"] == "manual"


# ── Pipeline builds all marketplaces ─────────────────────────────


def test_pipeline_builds_all_marketplace_payloads(load_fixture) -> None:
    raw = load_fixture("lzt_gi.json")
    pipeline = PayloadPipeline(registry=_build_registry())
    marketplaces = ["eldorado", "gameboost", "playerauctions"]
    request = PipelineRequest(
        game="genshin-impact",
        category="account",
        kind="stock",
        sources={"lzt": raw},
    )

    _prepare_result = pipeline.prepare_once(request)
    assert _prepare_result.success, f"prepare_once failed: {_prepare_result.error}"
    prepared = _prepare_result.prepared
    for mp in marketplaces:
        result = pipeline.build(prepared, BuildContext(kind="stock", marketplace=mp))
        assert result.success
        assert result.payload


def test_build_raises_for_unsupported_marketplace(load_fixture) -> None:
    raw = load_fixture("lzt_gi.json")
    pipeline = PayloadPipeline(registry=_build_registry())
    request = PipelineRequest(
        game="genshin-impact",
        category="account",
        kind="stock",
        sources={"lzt": raw},
    )

    _prepare_result = pipeline.prepare_once(request)
    assert _prepare_result.success, f"prepare_once failed: {_prepare_result.error}"
    prepared = _prepare_result.prepared
    result = pipeline.build(prepared, BuildContext(kind="stock", marketplace="nonexistent_marketplace"))
    assert result.success is False
