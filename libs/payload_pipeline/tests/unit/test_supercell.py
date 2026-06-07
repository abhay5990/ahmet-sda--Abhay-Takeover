from __future__ import annotations

from payload_pipeline import PayloadPipeline, build_default_registry
from payload_pipeline.core.contracts import BuildContext, PipelineRequest
from payload_pipeline.games.bs.account import BSResolver
from payload_pipeline.games.coc.account import CocResolver
from payload_pipeline.games.cr.account import CrResolver
from payload_pipeline.marketplaces.g2g import G2GConfig


def test_supercell_registrations_include_all_marketplaces() -> None:
    registry = build_default_registry()

    assert set(registry.get_game("brawl-stars", "account").marketplaces.keys()) == {
        "eldorado",
        "g2g",
        "gameboost",
        "playerauctions",
    }
    assert set(registry.get_game("clash-of-clans", "account").marketplaces.keys()) == {
        "eldorado",
        "g2g",
        "gameboost",
        "playerauctions",
    }
    assert set(registry.get_game("clash-royale", "account").marketplaces.keys()) == {
        "eldorado",
        "g2g",
        "gameboost",
        "playerauctions",
    }


def test_bs_pipeline_builds_all_marketplaces(load_fixture) -> None:
    pipeline = PayloadPipeline(registry=build_default_registry())
    request = PipelineRequest(
        game="brawl-stars",
        category="account",
        kind="stock",
        sources={"lzt": load_fixture("lzt_bs.json")},
    )
    _prepare_result = pipeline.prepare_once(request)
    assert _prepare_result.success, f"prepare_once failed: {_prepare_result.error}"
    prepared = _prepare_result.prepared
    results = {}
    for mp in ("eldorado", "gameboost", "g2g", "playerauctions"):
        mc = G2GConfig(seller_id="1000959019") if mp == "g2g" else None
        result = pipeline.build(prepared, BuildContext(kind="stock", marketplace=mp, marketplace_config=mc))
        assert result.success
        results[mp] = result.payload

    assert set(results.keys()) == {"eldorado", "gameboost", "g2g", "playerauctions"}
    assert results["eldorado"]["augmentedGame"]["gameId"] == "56"
    assert results["gameboost"]["game"] == "brawl-stars"
    assert results["gameboost"]["account_data"]["trophies_count"] == 33190
    assert results["g2g"]["brand_id"] == "lgc_game_24333"
    assert results["g2g"]["softpin_data"]
    assert results["playerauctions"]["game_id"] == 8463


def test_coc_resolver_prefers_tracker_stats(load_fixture) -> None:
    request = PipelineRequest(
        game="clash-of-clans",
        category="account",
        kind="stock",
        sources={
            "lzt": load_fixture("lzt_coc.json"),
            "tracker": load_fixture("tracker_coc.json"),
        },
    )

    account = CocResolver().resolve(request)

    assert account.town_hall_level == 14
    assert account.builder_hall_level == 10
    assert account.barbarian_king_level == 48
    assert account.archer_queen_level == 49
    assert account.grand_warden_level == 35
    assert account.royal_champion_level == 24
    assert account.player_tag == "#L0URGJPLV"
    assert account.has_email_access is True


def test_coc_pipeline_builds_all_marketplaces(load_fixture) -> None:
    pipeline = PayloadPipeline(registry=build_default_registry())
    request = PipelineRequest(
        game="clash-of-clans",
        category="account",
        kind="stock",
        sources={
            "lzt": load_fixture("lzt_coc.json"),
            "tracker": load_fixture("tracker_coc.json"),
        },
    )
    _prepare_result = pipeline.prepare_once(request)
    assert _prepare_result.success, f"prepare_once failed: {_prepare_result.error}"
    prepared = _prepare_result.prepared
    results = {}
    for mp in ("eldorado", "gameboost", "g2g", "playerauctions"):
        mc = G2GConfig(seller_id="1000959019") if mp == "g2g" else None
        result = pipeline.build(prepared, BuildContext(kind="stock", marketplace=mp, marketplace_config=mc))
        assert result.success
        results[mp] = result.payload

    assert set(results.keys()) == {"eldorado", "gameboost", "g2g", "playerauctions"}
    assert results["eldorado"]["augmentedGame"]["gameId"] == "18"
    assert results["gameboost"]["game"] == "clash-of-clans"
    assert results["gameboost"]["image_urls"]
    assert len(results["g2g"]["offer_attributes"]) == 5
    assert results["playerauctions"]["game_id"] == 8455
    assert results["playerauctions"]["server_id"] == ["8455", "8456"]


def test_cr_lzt_source_extracts_player_tag_from_json_string(load_fixture) -> None:
    """CrLztSourceAdapter must parse player_tag from supercell_systems JSON string."""
    from payload_pipeline.games.cr.account.sources.lzt import CrLztSourceAdapter

    raw = load_fixture("lzt_cr.json")
    source = CrLztSourceAdapter().parse(raw)

    assert source is not None
    assert source.player_tag == "U2VCCG0P0"
    assert source.evolved_count == 7


def test_cr_resolver_lzt_only_populates_tracker_link(load_fixture) -> None:
    """CrResolver builds account_tracker_link from LZT-only source (no tracker needed)."""
    request = PipelineRequest(
        game="clash-royale",
        category="account",
        kind="stock",
        sources={"lzt": load_fixture("lzt_cr.json")},
    )

    account = CrResolver().resolve(request)

    assert account.player_tag == "U2VCCG0P0"
    assert "U2VCCG0P0" in account.account_tracker_link
    # LZT-only: evolution_count falls back to LZT evolved_count
    assert account.evolution_count == 7


def test_cr_resolver_populates_builder_ready_fields(load_fixture) -> None:
    request = PipelineRequest(
        game="clash-royale",
        category="account",
        kind="stock",
        sources={
            "lzt": load_fixture("lzt_cr.json"),
            "tracker": load_fixture("tracker_cr.json"),
        },
    )

    account = CrResolver().resolve(request)

    assert account.current_trophies == 10639
    assert account.trophies == 10639
    assert account.arena_name == "Royal Road"
    assert account.has_brawl_stars is True
    assert account.brawl_stars_level == 69
    assert account.has_coc is True
    assert account.coc_th_level == 11
    assert account.level_15_cards_count == 6
    assert account.level_14_cards_count == 39
    # Tracker has 16 evolutions from cards, takes priority over LZT's 7
    assert account.evolution_count == 16
    assert account.max_cards_count == 39
    assert account.account_tracker_link.endswith("U2VCCG0P0")


def test_cr_pipeline_builds_all_marketplaces(load_fixture) -> None:
    pipeline = PayloadPipeline(registry=build_default_registry())
    request = PipelineRequest(
        game="clash-royale",
        category="account",
        kind="stock",
        sources={
            "lzt": load_fixture("lzt_cr.json"),
            "tracker": load_fixture("tracker_cr.json"),
        },
    )
    _prepare_result = pipeline.prepare_once(request)
    assert _prepare_result.success, f"prepare_once failed: {_prepare_result.error}"
    prepared = _prepare_result.prepared
    results = {}
    for mp in ("gameboost", "g2g", "playerauctions"):
        mc = G2GConfig(seller_id="1000959019") if mp == "g2g" else None
        result = pipeline.build(prepared, BuildContext(kind="stock", marketplace=mp, marketplace_config=mc))
        assert result.success, f"{mp} failed: {result.error}"
        results[mp] = result.payload

    assert results["gameboost"]["game"] == "clash-royale"
    assert results["gameboost"]["account_data"]["evolution_count"] == 16
    assert "Clash of Clans TH11" in results["gameboost"]["dump"]
    assert len(results["g2g"]["offer_attributes"]) == 4
    assert results["playerauctions"]["gameId"] == 7293
