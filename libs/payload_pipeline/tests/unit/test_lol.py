"""Tests for the League of Legends account slice."""

from __future__ import annotations

from payload_pipeline import PayloadPipeline, build_default_registry
from payload_pipeline.core import context_keys as ctx
from payload_pipeline.core.contracts import BuildContext, MediaBundle, PipelineRequest
from payload_pipeline.marketplaces.g2g import G2GConfig
from payload_pipeline.games.lol.account import (
    LolComposer,
    LolEldoradoBuilder,
    LolG2GBuilder,
    LolGameBoostBuilder,
    LolPlayerAuctionsBuilder,
    LolLztSourceAdapter,
    LolResolver,
)
from payload_pipeline.games.lol.account import catalog as lol_catalog

from _variant_ctx import lol_eldorado, lol_gameboost, lol_playerauctions


# ── Source normalization ────────────────────────────────────────────


def test_lol_lzt_source_normalization(load_fixture) -> None:
    source = LolLztSourceAdapter().parse(load_fixture("lzt_lol.json"))

    assert source is not None
    assert source.item_id == "157112652"
    assert source.region == "EUN1"
    assert source.region_phrase == "Europe Nordic & East"
    assert source.level == 15
    assert source.skin_count == 1
    assert source.champion_count == 32
    assert source.rank == "Unranked"
    assert source.blue_essence == 2564
    assert source.orange_essence == 500
    assert len(source.champion_ids) == 32
    assert len(source.skin_ids) == 1
    assert 81022 in source.skin_ids


def test_lol_lzt_source_parses_credentials(load_fixture) -> None:
    source = LolLztSourceAdapter().parse(load_fixture("lzt_lol.json"))

    assert source is not None
    assert source.credentials.login == "prajvi1"
    assert source.credentials.password == "Wilk-0001"


# ── Resolver ────────────────────────────────────────────────────────


def test_lol_resolver_produces_resolved_account(load_fixture) -> None:
    raw = load_fixture("lzt_lol.json")
    request = PipelineRequest(
        game="league-of-legends",
        category="account",
        kind="stock",
        sources={"lzt": raw},
    )

    account = LolResolver().resolve(request)

    assert account.region == "EUN1"
    assert account.region_phrase == "Europe Nordic & East"
    assert account.level == 15
    assert account.rank == "Unranked"
    assert account.skin_count == 1
    assert account.champion_count == 32
    assert account.blue_essence == 2564
    assert account.credentials.login == "prajvi1"


# ── Composer ────────────────────────────────────────────────────────


def test_lol_composer_produces_listing_draft(load_fixture) -> None:
    raw = load_fixture("lzt_lol.json")
    request = PipelineRequest(
        game="league-of-legends",
        category="account",
        kind="stock",
        sources={"lzt": raw},
    )

    account = LolResolver().resolve(request)
    listing = LolComposer().compose(account, request, MediaBundle())

    assert "EUN" in listing.default.title
    assert "Handmade" not in listing.default.title
    assert "Full Access" not in listing.default.title
    assert "Instant Delivery" not in listing.default.title
    assert "S4G" not in listing.default.title
    assert "Level: 15" in listing.default.description
    assert "Has Warranty" in listing.default.description
    # G2G override should have a shorter title
    g2g_content = listing.content_for("g2g")
    assert g2g_content.title
    assert len(g2g_content.title) <= 120


# ── Eldorado builder ───────────────────────────────────────────────


def test_lol_pipeline_builds_eldorado_payload(load_fixture) -> None:
    raw = load_fixture("lzt_lol.json")
    pipeline = PayloadPipeline(registry=build_default_registry())
    request = PipelineRequest(
        game="league-of-legends",
        category="account",
        kind="stock",
        sources={"lzt": raw},
    )

    _prepare_result = pipeline.prepare_once(request)
    assert _prepare_result.success, f"prepare_once failed: {_prepare_result.error}"
    prepared = _prepare_result.prepared
    result = pipeline.build(prepared, BuildContext(
        kind="stock", marketplace="eldorado",
        variant_context=lol_eldorado(),
    ))
    assert result.success

    assert result.payload["augmentedGame"]["gameId"] == "17"
    assert result.payload["augmentedGame"]["tradeEnvironmentId"] == "1"  # Europe Nordic & East
    attrs = {a["id"]: a["value"] for a in result.payload["augmentedGame"]["offerAttributes"]}
    assert attrs["lol-current-rank"] == "unranked"
    assert attrs["lol-skins"] == "1-9-skins"  # 1 skin
    assert attrs["lol-blue-essence"] == "0-19k-be"  # 2564 BE
    assert result.payload["accountSecretDetails"]
    assert result.payload["details"]["offerTitle"]


def test_lol_eldorado_rank_mapping() -> None:
    assert LolEldoradoBuilder._resolve_rank_attribute("Gold IV") == "gold"
    assert LolEldoradoBuilder._resolve_rank_attribute("Diamond I") == "diamond"
    assert LolEldoradoBuilder._resolve_rank_attribute("Challenger") == "other"
    assert LolEldoradoBuilder._resolve_rank_attribute("Emerald II") == "emerald"
    assert LolEldoradoBuilder._resolve_rank_attribute("") == "unranked"
    assert LolEldoradoBuilder._resolve_rank_attribute("Unranked") == "unranked"


def test_lol_eldorado_skin_count_mapping() -> None:
    assert LolEldoradoBuilder._resolve_skin_attribute(0) == "0-skins"
    assert LolEldoradoBuilder._resolve_skin_attribute(5) == "1-9-skins"
    assert LolEldoradoBuilder._resolve_skin_attribute(15) == "10-24-skins"
    assert LolEldoradoBuilder._resolve_skin_attribute(30) == "25-49-skins"
    assert LolEldoradoBuilder._resolve_skin_attribute(75) == "50-99-skins"
    assert LolEldoradoBuilder._resolve_skin_attribute(150) == "100-199-skins"
    assert LolEldoradoBuilder._resolve_skin_attribute(250) == "200-299-skins"


def test_lol_eldorado_blue_essence_mapping() -> None:
    assert LolEldoradoBuilder._resolve_blue_essence_attribute(5000) == "0-19k-be"
    assert LolEldoradoBuilder._resolve_blue_essence_attribute(30000) == "20-40k-be"
    assert LolEldoradoBuilder._resolve_blue_essence_attribute(50000) == "41-60k-be"
    assert LolEldoradoBuilder._resolve_blue_essence_attribute(70000) == "61-80k-be"
    assert LolEldoradoBuilder._resolve_blue_essence_attribute(90000) == "81-100k-be"
    assert LolEldoradoBuilder._resolve_blue_essence_attribute(150000) == "100k-plus-be"


# ── GameBoost builder ──────────────────────────────────────────────


def test_lol_pipeline_builds_gameboost_payload(load_fixture) -> None:
    raw = load_fixture("lzt_lol.json")
    pipeline = PayloadPipeline(registry=build_default_registry())
    request = PipelineRequest(
        game="league-of-legends",
        category="account",
        kind="stock",
        sources={"lzt": raw},
    )

    _prepare_result = pipeline.prepare_once(request)
    assert _prepare_result.success, f"prepare_once failed: {_prepare_result.error}"
    prepared = _prepare_result.prepared
    result = pipeline.build(prepared, BuildContext(
        kind="stock", marketplace="gameboost",
        variant_context=lol_gameboost(),
    ))
    assert result.success

    assert result.payload["game"] == "league-of-legends"
    assert result.payload["title"]
    assert result.payload["slug"]
    assert result.payload["price"] > 0
    assert result.payload["account_data"]["server"] == "Europe Nordic & East"
    assert result.payload["account_data"]["level"] == "15"
    assert result.payload["account_data"]["current_tier"] == "Unranked"
    assert result.payload["account_data"]["is_ranked_ready"] is False  # level 15 < 30
    assert result.payload["login"]
    assert result.payload["delivery_instructions"]


def test_lol_gameboost_dropshipping_mode(load_fixture) -> None:
    raw = load_fixture("lzt_lol.json")
    request = PipelineRequest(
        game="league-of-legends",
        category="account",
        kind="dropshipping",
        sources={"lzt": raw},
    )

    account = LolResolver().resolve(request)
    listing = LolComposer().compose(account, request, MediaBundle())
    build_ctx = BuildContext(kind="dropshipping", marketplace="gameboost", variant_context=lol_gameboost())
    payload = LolGameBoostBuilder().build_payload(account, listing, build_ctx)

    assert payload["is_manual"] is True
    assert payload["login"] is None
    assert payload["password"] is None
    assert payload["delivery_time"] == {"duration": 10, "unit": "minutes"}


# ── G2G builder ────────────────────────────────────────────────────


def test_lol_pipeline_builds_g2g_payload(load_fixture) -> None:
    raw = load_fixture("lzt_lol.json")
    pipeline = PayloadPipeline(registry=build_default_registry())
    request = PipelineRequest(
        game="league-of-legends",
        category="account",
        kind="stock",
        sources={"lzt": raw},
        context={ctx.G2G_SELLER_ID: "1000959019"},
    )

    _prepare_result = pipeline.prepare_once(request)
    assert _prepare_result.success, f"prepare_once failed: {_prepare_result.error}"
    prepared = _prepare_result.prepared
    result = pipeline.build(prepared, BuildContext(kind="stock", marketplace="g2g", marketplace_config=G2GConfig(seller_id="1000959019")))
    assert result.success

    assert result.payload["brand_id"] == "lgc_game_22666"
    assert result.payload["delivery_speed"] == "instant"
    assert result.payload["currency"] == "USD"
    assert result.payload["title"]
    assert result.payload["unit_price"] > 0
    # Verified: only 2 required attributes (Server + Account Type)
    attrs = result.payload["offer_attributes"]
    assert len(attrs) == 2
    # Server: EUNE → dataset_id 1a87dd85
    server_attr = attrs[0]
    assert server_attr["collection_id"] == "e80c30d1"
    assert server_attr["dataset_id"] == "1a87dd85"
    # Account Type: Unranked → Smurf Accounts (6380c8dd)
    account_type_attr = attrs[1]
    assert account_type_attr["collection_id"] == "319340f0"
    assert account_type_attr["dataset_id"] == "6380c8dd"
    assert result.payload["softpin_data"]


def test_lol_g2g_uses_marketplace_override_title(load_fixture) -> None:
    raw = load_fixture("lzt_lol.json")
    request = PipelineRequest(
        game="league-of-legends",
        category="account",
        kind="stock",
        sources={"lzt": raw},
        context={ctx.G2G_SELLER_ID: "1000959019"},
    )

    account = LolResolver().resolve(request)
    listing = LolComposer().compose(account, request, MediaBundle())
    build_ctx = BuildContext(kind="stock", marketplace="g2g", marketplace_config=G2GConfig(seller_id="1000959019"))
    payload = LolG2GBuilder().build_payload(account, listing, build_ctx)

    g2g_content = listing.content_for("g2g")
    assert payload["title"] == g2g_content.title


# ── PlayerAuctions builder ─────────────────────────────────────────


def test_lol_pipeline_builds_playerauctions_payload(load_fixture) -> None:
    raw = load_fixture("lzt_lol.json")
    pipeline = PayloadPipeline(registry=build_default_registry())
    request = PipelineRequest(
        game="league-of-legends",
        category="account",
        kind="stock",
        sources={"lzt": raw},
    )

    _prepare_result = pipeline.prepare_once(request)
    assert _prepare_result.success, f"prepare_once failed: {_prepare_result.error}"
    prepared = _prepare_result.prepared
    result = pipeline.build(prepared, BuildContext(
        kind="stock", marketplace="playerauctions",
        variant_context=lol_playerauctions(),
    ))
    assert result.success

    assert result.payload["gameId"] == 3637
    assert result.payload["serverId"] == 4144  # Europe Nordic & East
    assert result.payload["categoryId"] == 4144
    assert result.payload["title"]
    assert result.payload["price"] > 0
    assert result.payload["isAuto"] is True
    assert result.payload["autoDelivery"]["loginName"] == "prajvi1"
    assert result.payload["autoDelivery"]["instruction"]
    assert result.payload["screenShot"] == ""
    assert result.payload["freeInsurance"] == 7
    assert result.payload["offerDuration"] == 30


def test_lol_playerauctions_bulk_payload(load_fixture) -> None:
    raw = load_fixture("lzt_lol.json")
    request = PipelineRequest(
        game="league-of-legends",
        category="account",
        kind="stock",
        sources={"lzt": raw},
    )

    account = LolResolver().resolve(request)
    listing = LolComposer().compose(account, request, MediaBundle())
    build_ctx = BuildContext(kind="stock", marketplace="playerauctions", variant_context=lol_playerauctions())
    row = LolPlayerAuctionsBuilder().build_bulk_payload(account, listing, build_ctx)

    assert row["Game"] == "League of Legends"
    assert row["Server"] == "EU Nordic and East"
    assert row["Listing Price"] > 0
    assert row["Title"]
    assert row["Delivery Method"] == "Automatic"
    assert row["Login name  (Auto)"] == "prajvi1"
    assert row["Password"]


# ── Pipeline builds all marketplaces ───────────────────────────────


def test_lol_pipeline_builds_all_marketplace_payloads(load_fixture) -> None:
    raw = load_fixture("lzt_lol.json")
    pipeline = PayloadPipeline(registry=build_default_registry())
    marketplaces = ["eldorado", "gameboost", "g2g", "playerauctions"]
    request = PipelineRequest(
        game="league-of-legends",
        category="account",
        kind="stock",
        sources={"lzt": raw},
        context={ctx.G2G_SELLER_ID: "1000959019"},
    )

    _prepare_result = pipeline.prepare_once(request)
    assert _prepare_result.success, f"prepare_once failed: {_prepare_result.error}"
    prepared = _prepare_result.prepared
    _variant_ctxs = {
        "eldorado": lol_eldorado(),
        "gameboost": lol_gameboost(),
        "playerauctions": lol_playerauctions(),
    }
    for mp in marketplaces:
        build_ctx = BuildContext(kind="stock", marketplace=mp, variant_context=_variant_ctxs.get(mp))
        if mp == "g2g":
            build_ctx = BuildContext(kind="stock", marketplace=mp, marketplace_config=G2GConfig(seller_id="1000959019"))
        result = pipeline.build(prepared, build_ctx)
        assert result.success
        assert result.payload


# ── Catalog ───────────────────────────────────────────────────────


def test_lol_catalog_champion_title_lookup() -> None:
    assert lol_catalog.champion_title(1) == "Annie"
    assert lol_catalog.champion_title(999999) is None


def test_lol_catalog_skin_title_lookup() -> None:
    assert lol_catalog.skin_title(81022) == "PsyOps Ezreal"
    assert lol_catalog.skin_title(999999) is None


def test_lol_catalog_champion_titles_batch() -> None:
    titles = lol_catalog.champion_titles([1, 22, 999999])
    assert "Annie" in titles
    assert "Ashe" in titles
    assert len(titles) == 2  # 999999 skipped


def test_lol_catalog_skin_titles_filters_defaults() -> None:
    titles = lol_catalog.skin_titles([81022])
    assert titles == ["PsyOps Ezreal"]


# ── G2G attribute mapping ─────────────────────────────────────────


def test_lol_g2g_ranked_account_gets_ranked_dataset(load_fixture) -> None:
    raw = load_fixture("lzt_lol.json")
    request = PipelineRequest(
        game="league-of-legends", category="account", kind="stock", sources={"lzt": raw},
        context={ctx.G2G_SELLER_ID: "1000959019"},
    )
    account = LolResolver().resolve(request)
    # Override rank to a real ranked tier
    account.rank = "Gold IV"

    listing = LolComposer().compose(account, request, MediaBundle())
    build_ctx = BuildContext(kind="stock", marketplace="g2g", marketplace_config=G2GConfig(seller_id="1000959019"))
    payload = LolG2GBuilder().build_payload(account, listing, build_ctx)

    account_type = payload["offer_attributes"][1]
    assert account_type["dataset_id"] == "65ec9642"  # Ranked Accounts


def test_lol_g2g_no_server_attr_for_unknown_region() -> None:
    from payload_pipeline.games.lol.account.models import LolResolvedAccount

    account = LolResolvedAccount(region="XX", region_phrase="Unknown Land")
    attrs = LolG2GBuilder()._build_offer_attributes(account)
    # Only Account Type should be present; no server for unknown region
    assert len(attrs) == 1
    assert attrs[0]["collection_id"] == "319340f0"


# ── GameBoost dump & game_items ───────────────────────────────────


def test_lol_gameboost_dump_contains_titles(load_fixture) -> None:
    raw = load_fixture("lzt_lol.json")
    request = PipelineRequest(
        game="league-of-legends", category="account", kind="stock", sources={"lzt": raw},
    )
    account = LolResolver().resolve(request)
    listing = LolComposer().compose(account, request, MediaBundle())
    build_ctx = BuildContext(kind="stock", marketplace="gameboost", variant_context=lol_gameboost())
    payload = LolGameBoostBuilder().build_payload(account, listing, build_ctx)

    dump = payload["dump"]
    assert dump != "Handmade"
    assert "Champions:" in dump
    assert "Skins:" in dump
    assert "PsyOps Ezreal" in dump
    assert "Annie" in dump  # champion ID 1 is in fixture


def test_lol_gameboost_game_items_populated(load_fixture) -> None:
    raw = load_fixture("lzt_lol.json")
    request = PipelineRequest(
        game="league-of-legends", category="account", kind="stock", sources={"lzt": raw},
    )
    account = LolResolver().resolve(request)
    listing = LolComposer().compose(account, request, MediaBundle())
    build_ctx = BuildContext(kind="stock", marketplace="gameboost", variant_context=lol_gameboost())
    payload = LolGameBoostBuilder().build_payload(account, listing, build_ctx)

    game_items = payload["game_items"]
    assert len(game_items["champions"]) > 0
    assert "Annie" in game_items["champions"]
    assert game_items["skins"] == ["PsyOps Ezreal"]
    assert game_items["roles"] == ["Top", "Mid", "Jungle"]
