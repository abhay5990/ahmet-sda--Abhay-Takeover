"""Tests for the Ubisoft Connect account slice.

Covers source normalization, resolver, composer, and all three
marketplace builders (Eldorado, GameBoost, PlayerAuctions).
"""

from __future__ import annotations

from payload_pipeline import PayloadPipeline, build_default_registry
from payload_pipeline.core.contracts import BuildContext, MediaBundle, PipelineRequest
from payload_pipeline.games.ubisoft_connect.account import (
    UbisoftComposer,
    UbisoftEldoradoBuilder,
    UbisoftGameBoostBuilder,
    UbisoftLztSourceAdapter,
    UbisoftPlayerAuctionsBuilder,
    UbisoftResolver,
)


# ── Source normalization ─────────────────────────────────────────


def test_ubisoft_lzt_source_normalization(load_fixture) -> None:
    source = UbisoftLztSourceAdapter().parse(load_fixture("lzt_ubisoft_connect.json"))

    assert source is not None
    assert source.item_id == "221639380"
    assert source.category_id == 5
    assert source.price == 20.61
    assert source.country == "jp"
    assert source.game_count == 9
    assert source.r6_level == 93
    assert source.r6_ban is False
    assert source.psn_connected is True
    assert source.xbox_connected is False
    assert source.balance == "0.00 $"
    assert source.converted_balance == 0.0
    assert source.has_subscription is False
    assert isinstance(source.games, dict)
    assert len(source.games) == 9
    assert source.credentials.login == "CarlMyers4766@hotmail.com"
    assert source.credentials.password == "lscdCICT6a#"
    assert source.credentials.email_login == "CarlMyers4766@hotmail.com"
    assert source.credentials.email_password == "gwrffh781244"


def test_ubisoft_lzt_source_parses_game_titles(load_fixture) -> None:
    source = UbisoftLztSourceAdapter().parse(load_fixture("lzt_ubisoft_connect.json"))
    assert source is not None

    titles = []
    for game in source.games.values():
        if isinstance(game, dict) and game.get("title"):
            titles.append(game["title"])

    assert "For Honor" in titles
    assert "Tom Clancy's Ghost Recon Wildlands" in titles
    assert "Tom Clancy's Rainbow Six Siege (Steam)" in titles
    assert "WATCH_DOGS 2" in titles
    assert len(titles) == 9


# ── Resolver ─────────────────────────────────────────────────────


def test_ubisoft_resolver_produces_resolved_account(load_fixture) -> None:
    raw = load_fixture("lzt_ubisoft_connect.json")
    request = PipelineRequest(
        game="ubisoft-connect",
        category="account",
        kind="stock",
        sources={"lzt": raw},
    )

    account = UbisoftResolver().resolve(request)

    assert account.item_id == "221639380"
    assert account.country == "jp"
    assert account.game_count == 9
    assert account.r6_level == 93
    assert account.psn_connected is True
    assert account.xbox_connected is False
    assert account.has_subscription is False
    assert account.balance == "0.00 $"
    assert account.has_email_access is True
    assert not account.credentials.is_empty


# ── Composer ─────────────────────────────────────────────────────


def test_ubisoft_composer_generates_listing(load_fixture) -> None:
    raw = load_fixture("lzt_ubisoft_connect.json")
    request = PipelineRequest(
        game="ubisoft-connect",
        category="account",
        kind="stock",
        sources={"lzt": raw},
    )

    account = UbisoftResolver().resolve(request)
    listing = UbisoftComposer().compose(account, request, MediaBundle())

    assert "Ubisoft Connect" in listing.default.title
    assert "9 Games" in listing.default.title
    assert "R6 Lv93" in listing.default.title
    assert "JP" in listing.default.title
    assert "Games: 9" in listing.default.description
    assert "PSN Connected: Yes" in listing.default.description
    assert "Xbox Connected: No" in listing.default.description
    assert "Level: 93" in listing.default.description

    game_titles = account.game_titles
    assert "For Honor" in game_titles
    assert "WATCH_DOGS 2" in game_titles


# ── Eldorado builder ─────────────────────────────────────────────


def test_ubisoft_eldorado_payload_structure(load_fixture) -> None:
    raw = load_fixture("lzt_ubisoft_connect.json")
    pipeline = PayloadPipeline(registry=build_default_registry())
    request = PipelineRequest(
        game="ubisoft-connect",
        category="account",
        kind="stock",
        sources={"lzt": raw},
    )

    _prepare_result = pipeline.prepare_once(request)
    assert _prepare_result.success, f"prepare_once failed: {_prepare_result.error}"
    prepared = _prepare_result.prepared
    result = pipeline.build(prepared, BuildContext(kind="stock", marketplace="eldorado"))

    assert result.success
    assert result.payload["augmentedGame"]["gameId"] == "65"
    assert result.payload["augmentedGame"]["category"] == "Account"
    assert result.payload["accountSecretDetails"]
    assert result.payload["details"]["offerTitle"]
    assert result.payload["details"]["pricing"]["pricePerUnit"]["amount"] > 0
    assert result.payload["details"]["hasOriginalEmail"] is False


# ── GameBoost builder ────────────────────────────────────────────


def test_ubisoft_gameboost_payload_structure(load_fixture) -> None:
    raw = load_fixture("lzt_ubisoft_connect.json")
    pipeline = PayloadPipeline(registry=build_default_registry())
    request = PipelineRequest(
        game="ubisoft-connect",
        category="account",
        kind="stock",
        sources={"lzt": raw},
    )

    _prepare_result = pipeline.prepare_once(request)
    assert _prepare_result.success, f"prepare_once failed: {_prepare_result.error}"
    prepared = _prepare_result.prepared
    result = pipeline.build(prepared, BuildContext(kind="stock", marketplace="gameboost"))

    assert result.success
    assert result.payload["game"] == "ubisoft-connect"
    assert result.payload["title"]
    assert result.payload["slug"]
    assert result.payload["price"] > 0
    assert result.payload["login"]
    assert result.payload["delivery_instructions"]

    ad = result.payload["account_data"]
    assert ad["platform"] == "PC"
    assert ad["game_count"] == 9
    assert ad["country"] == "JP"
    assert ad["r6_level"] == 93
    assert ad["balance"] == 0
    assert ad["subscription"] == ""


def test_ubisoft_gameboost_linked_platforms_from_fixture(load_fixture) -> None:
    """PSN connected=True, Xbox connected=False in fixture data.

    The old builder had an inverted boolean check (== 0 meant connected).
    The new builder uses the resolved model's correct boolean semantics.
    """
    raw = load_fixture("lzt_ubisoft_connect.json")
    request = PipelineRequest(
        game="ubisoft-connect",
        category="account",
        kind="stock",
        sources={"lzt": raw},
    )

    account = UbisoftResolver().resolve(request)
    listing = UbisoftComposer().compose(account, request, MediaBundle())
    build_ctx = BuildContext(kind="stock", marketplace="gameboost")
    payload = UbisoftGameBoostBuilder().build_payload(account, listing, build_ctx)

    linked = payload["account_data"]["linked_platforms"]
    assert "PlayStation" in linked
    assert "Xbox" not in linked


def test_ubisoft_gameboost_dropshipping_mode(load_fixture) -> None:
    raw = load_fixture("lzt_ubisoft_connect.json")
    request = PipelineRequest(
        game="ubisoft-connect",
        category="account",
        kind="dropshipping",
        sources={"lzt": raw},
    )

    account = UbisoftResolver().resolve(request)
    listing = UbisoftComposer().compose(account, request, MediaBundle())
    build_ctx = BuildContext(kind="dropshipping", marketplace="gameboost")
    payload = UbisoftGameBoostBuilder().build_payload(account, listing, build_ctx)

    assert payload["is_manual"] is True
    assert payload["login"] is None
    assert payload["password"] is None
    assert payload["delivery_time"] == {"duration": 10, "unit": "minutes"}


# ── PlayerAuctions builder ───────────────────────────────────────


def test_ubisoft_playerauctions_payload_structure(load_fixture) -> None:
    raw = load_fixture("lzt_ubisoft_connect.json")
    pipeline = PayloadPipeline(registry=build_default_registry())
    request = PipelineRequest(
        game="ubisoft-connect",
        category="account",
        kind="stock",
        sources={"lzt": raw},
    )

    _prepare_result = pipeline.prepare_once(request)
    assert _prepare_result.success, f"prepare_once failed: {_prepare_result.error}"
    prepared = _prepare_result.prepared
    result = pipeline.build(prepared, BuildContext(kind="stock", marketplace="playerauctions"))

    assert result.success
    assert result.payload["gameId"] == 8485
    assert result.payload["serverId"] == 8485  # PC server
    assert result.payload["categoryId"] == 8485
    assert result.payload["title"]
    assert result.payload["price"] > 0
    assert result.payload["isAuto"] is True
    assert result.payload["autoDelivery"]["loginName"]
    assert result.payload["autoDelivery"]["instruction"]
    assert result.payload["screenShot"] == ""
    assert result.payload["freeInsurance"] == 7
    assert result.payload["offerDuration"] == 30


def test_ubisoft_playerauctions_dropshipping_mode(load_fixture) -> None:
    raw = load_fixture("lzt_ubisoft_connect.json")
    request = PipelineRequest(
        game="ubisoft-connect",
        category="account",
        kind="dropshipping",
        sources={"lzt": raw},
    )

    account = UbisoftResolver().resolve(request)
    listing = UbisoftComposer().compose(account, request, MediaBundle())
    build_ctx = BuildContext(kind="dropshipping", marketplace="playerauctions")
    payload = UbisoftPlayerAuctionsBuilder().build_payload(account, listing, build_ctx)

    assert payload["isAuto"] is False


def test_ubisoft_playerauctions_bulk_payload_structure(load_fixture) -> None:
    raw = load_fixture("lzt_ubisoft_connect.json")
    request = PipelineRequest(
        game="ubisoft-connect",
        category="account",
        kind="stock",
        sources={"lzt": raw},
    )

    account = UbisoftResolver().resolve(request)
    listing = UbisoftComposer().compose(account, request, MediaBundle())
    build_ctx = BuildContext(kind="stock", marketplace="playerauctions")
    row = UbisoftPlayerAuctionsBuilder().build_bulk_payload(account, listing, build_ctx)

    assert row["Game"] == "Ubisoft Connect"
    assert row["Server"] == "PC"
    assert row["Listing Price"] > 0
    assert row["Title"]
    assert row["Delivery Method"] == "Automatic"
    assert row["Login name  (Auto)"]
    assert row["Password"]


def test_ubisoft_playerauctions_bulk_dropshipping_mode(load_fixture) -> None:
    raw = load_fixture("lzt_ubisoft_connect.json")
    request = PipelineRequest(
        game="ubisoft-connect",
        category="account",
        kind="dropshipping",
        sources={"lzt": raw},
    )

    account = UbisoftResolver().resolve(request)
    listing = UbisoftComposer().compose(account, request, MediaBundle())
    build_ctx = BuildContext(kind="dropshipping", marketplace="playerauctions")
    row = UbisoftPlayerAuctionsBuilder().build_bulk_payload(account, listing, build_ctx)

    assert row["Delivery Method"] == "Manual"
    assert row["Login name  (Auto)"] == ""


# ── Pipeline builds all marketplaces ─────────────────────────────


def test_ubisoft_pipeline_builds_all_marketplace_payloads(load_fixture) -> None:
    raw = load_fixture("lzt_ubisoft_connect.json")
    pipeline = PayloadPipeline(registry=build_default_registry())
    marketplaces = ["eldorado", "gameboost", "playerauctions"]
    request = PipelineRequest(
        game="ubisoft-connect",
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


# ── Registry ─────────────────────────────────────────────────────


def test_ubisoft_in_default_registry() -> None:
    registry = build_default_registry()
    assert registry.has_game("ubisoft-connect")

    definition = registry.get_game("ubisoft-connect")
    assert "eldorado" in definition.marketplaces
    assert "gameboost" in definition.marketplaces
    assert "playerauctions" in definition.marketplaces
