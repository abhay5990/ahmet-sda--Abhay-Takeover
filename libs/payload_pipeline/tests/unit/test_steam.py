"""Tests for the Steam account slice."""

from __future__ import annotations

import pytest

from payload_pipeline import PayloadPipeline, build_default_registry
from payload_pipeline.core.contracts import BuildContext, MediaBundle, PipelineRequest
from payload_pipeline.games.steam.account import SteamResolver
from payload_pipeline.games.steam.account.sources.lzt import SteamLztSourceAdapter
from payload_pipeline.marketplaces.g2g import G2GConfig


# -- source adapter tests -------------------------------------------------

class TestSteamLztSourceAdapter:
    def test_parse_returns_none_for_empty_input(self):
        adapter = SteamLztSourceAdapter()
        assert adapter.parse(None) is None
        assert adapter.parse({}) is None

    def test_parse_extracts_core_fields(self, load_fixture):
        adapter = SteamLztSourceAdapter()
        source = adapter.parse(load_fixture("lzt_steam.json"))

        assert source is not None
        assert source.item_id == "770001001"
        assert source.steam_id == "76561198012345678"
        assert source.country == "de"
        assert source.steam_level == 25
        assert source.total_games == 5

    def test_parse_extracts_games_list(self, load_fixture):
        adapter = SteamLztSourceAdapter()
        source = adapter.parse(load_fixture("lzt_steam.json"))

        assert len(source.games) == 5
        titles = [g.get("title") for g in source.games]
        assert "Counter-Strike 2" in titles
        assert "Rust" in titles

    def test_parse_extracts_credentials(self, load_fixture):
        adapter = SteamLztSourceAdapter()
        source = adapter.parse(load_fixture("lzt_steam.json"))

        assert source.credentials.login == "steam_user"
        assert source.credentials.password == "SteamPass123"
        assert source.credentials.email_login == "steam_email@example.com"


# -- resolver tests --------------------------------------------------------

class TestSteamResolver:
    def test_resolver_populates_all_fields(self, load_fixture):
        request = PipelineRequest(
            game="steam",
            category="account",
            kind="stock",
            sources={"lzt": load_fixture("lzt_steam.json")},
        )
        account = SteamResolver().resolve(request)

        assert account.steam_id == "76561198012345678"
        assert account.steam_level == 25
        assert account.total_games == 5
        assert account.country == "de"
        assert account.has_email_access is True

    def test_resolver_rejects_missing_source(self):
        request = PipelineRequest(
            game="steam",
            category="account",
            kind="stock",
            sources={},
        )
        with pytest.raises(Exception, match="lzt"):
            SteamResolver().resolve(request)

    def test_resolver_dropshipping_clears_credentials(self, load_fixture):
        request = PipelineRequest(
            game="steam",
            category="account",
            kind="dropshipping",
            sources={"lzt": load_fixture("lzt_steam.json")},
        )
        account = SteamResolver().resolve(request)
        assert account.credentials.is_empty


# -- composer tests --------------------------------------------------------

class TestSteamComposer:
    def test_compose_produces_listing_draft(self, load_fixture):
        from payload_pipeline.games.steam.account.content import SteamComposer

        request = PipelineRequest(
            game="steam",
            category="account",
            kind="stock",
            sources={"lzt": load_fixture("lzt_steam.json")},
        )
        account = SteamResolver().resolve(request)
        draft = SteamComposer().compose(account, request, MediaBundle())

        assert draft.default.title
        assert "5 Games" in draft.default.title
        assert "Games: 5" in draft.default.description
        assert "steam" in draft.default.tags

    def test_compose_includes_game_titles(self, load_fixture):
        from payload_pipeline.games.steam.account.content import SteamComposer

        request = PipelineRequest(
            game="steam",
            category="account",
            kind="stock",
            sources={"lzt": load_fixture("lzt_steam.json")},
        )
        account = SteamResolver().resolve(request)
        draft = SteamComposer().compose(account, request, MediaBundle())

        assert "Counter-Strike 2" in draft.default.description


# -- registry tests --------------------------------------------------------

class TestSteamRegistration:
    def test_steam_in_default_registry(self):
        registry = build_default_registry()
        assert registry.has_game("steam")

    def test_steam_has_all_marketplaces(self):
        registry = build_default_registry()
        defn = registry.get_game("steam", "account")
        assert set(defn.marketplaces.keys()) == {"eldorado", "gameboost", "g2g"}


# -- end-to-end pipeline tests --------------------------------------------

class TestSteamPipeline:
    def test_pipeline_builds_all_marketplaces(self, load_fixture):
        pipeline = PayloadPipeline(registry=build_default_registry())
        request = PipelineRequest(
            game="steam",
            category="account",
            kind="stock",
            sources={"lzt": load_fixture("lzt_steam.json")},
        )
        _prepare_result = pipeline.prepare_once(request)
        assert _prepare_result.success, f"prepare_once failed: {_prepare_result.error}"
        prepared = _prepare_result.prepared
        built = {}
        for mp in ("eldorado", "gameboost", "g2g"):
            mc = G2GConfig(seller_id="1000959019") if mp == "g2g" else None
            result = pipeline.build(prepared, BuildContext(kind="stock", marketplace=mp, marketplace_config=mc))
            assert result.success
            built[mp] = result.payload
        assert set(built.keys()) == {"eldorado", "gameboost", "g2g"}

    def test_eldorado_payload_shape(self, load_fixture):
        pipeline = PayloadPipeline(registry=build_default_registry())
        request = PipelineRequest(
            game="steam",
            category="account",
            kind="stock",
            sources={"lzt": load_fixture("lzt_steam.json")},
        )
        _prepare_result = pipeline.prepare_once(request)
        assert _prepare_result.success, f"prepare_once failed: {_prepare_result.error}"
        prepared = _prepare_result.prepared
        result = pipeline.build(prepared, BuildContext(kind="stock", marketplace="eldorado"))
        assert result.success

        assert result.payload["augmentedGame"]["gameId"] == "42"
        assert result.payload["augmentedGame"]["category"] == "Account"
        assert result.payload["details"]["pricing"]["pricePerUnit"]["currency"] == "USD"
        assert result.payload["accountSecretDetails"]

    def test_gameboost_payload_shape(self, load_fixture):
        pipeline = PayloadPipeline(registry=build_default_registry())
        request = PipelineRequest(
            game="steam",
            category="account",
            kind="stock",
            sources={"lzt": load_fixture("lzt_steam.json")},
        )
        _prepare_result = pipeline.prepare_once(request)
        assert _prepare_result.success, f"prepare_once failed: {_prepare_result.error}"
        prepared = _prepare_result.prepared
        result = pipeline.build(prepared, BuildContext(kind="stock", marketplace="gameboost"))
        assert result.success

        assert result.payload["game"] == "steam"
        assert result.payload["account_data"]["steam_level"] == 25
        assert result.payload["account_data"]["games_count"] == 5
        assert result.payload["account_data"]["country"] == "DE"
        assert result.payload["login"]

    def test_g2g_payload_shape(self, load_fixture):
        pipeline = PayloadPipeline(registry=build_default_registry())
        request = PipelineRequest(
            game="steam",
            category="account",
            kind="stock",
            sources={"lzt": load_fixture("lzt_steam.json")},
        )
        _prepare_result = pipeline.prepare_once(request)
        assert _prepare_result.success, f"prepare_once failed: {_prepare_result.error}"
        prepared = _prepare_result.prepared
        result = pipeline.build(prepared, BuildContext(kind="stock", marketplace="g2g", marketplace_config=G2GConfig(seller_id="1000959019")))
        assert result.success

        assert result.payload["brand_id"] == "lgc_game_22539"
        assert result.payload["currency"] == "USD"
        assert result.payload["title"]
        assert result.payload["unit_price"] > 0
        assert result.payload["offer_attributes"] == []

    def test_run_many_populates_subject(self, load_fixture):
        pipeline = PayloadPipeline(registry=build_default_registry())
        request = PipelineRequest(
            game="steam",
            category="account",
            kind="stock",
            sources={"lzt": load_fixture("lzt_steam.json")},
        )
        _prepare_result = pipeline.prepare_once(request)
        assert _prepare_result.success, f"prepare_once failed: {_prepare_result.error}"
        prepared = _prepare_result.prepared
        subject = prepared.subject

        assert subject.steam_level == 25
        assert subject.total_games == 5
