"""Tests for the Fortnite account slice."""

from __future__ import annotations

import pytest

from payload_pipeline import PayloadPipeline, build_default_registry
from payload_pipeline.core import context_keys as ctx
from payload_pipeline.core.contracts import BuildContext, MediaBundle, PipelineRequest
from payload_pipeline.games.fn.account import FortniteResolver
from payload_pipeline.games.fn.account.sources.lzt import FortniteLztSourceAdapter
from payload_pipeline.marketplaces.g2g import G2GConfig


# -- source adapter tests -------------------------------------------------

class TestFortniteLztSourceAdapter:
    def test_parse_returns_none_for_empty_input(self):
        adapter = FortniteLztSourceAdapter()
        assert adapter.parse(None) is None
        assert adapter.parse({}) is None

    def test_parse_extracts_core_fields(self, load_fixture):
        adapter = FortniteLztSourceAdapter()
        source = adapter.parse(load_fixture("lzt_fn.json"))

        assert source is not None
        assert source.item_id == "550001001"
        assert source.level == 320
        assert source.platform == "PC"
        assert source.skin_count == 150
        assert source.pickaxe_count == 85
        assert source.dance_count == 60
        assert source.glider_count == 40
        assert source.v_bucks == 2500
        assert source.lifetime_wins == 1200
        assert source.battle_pass_level == 100
        assert source.refund_credits == 3
        assert source.psn_linkable is True
        assert source.xbox_linkable is False
        assert source.has_real_purchases is True

    def test_parse_extracts_credentials(self, load_fixture):
        adapter = FortniteLztSourceAdapter()
        source = adapter.parse(load_fixture("lzt_fn.json"))

        assert source.credentials.login == "epic_user@example.com"
        assert source.credentials.password == "EpicPass123"
        assert source.credentials.email_login == "backup_email@example.com"
        assert source.credentials.email_password == "EmailPass456"

    def test_parse_extracts_cosmetic_titles(self, load_fixture):
        adapter = FortniteLztSourceAdapter()
        source = adapter.parse(load_fixture("lzt_fn.json"))

        assert "Renegade Raider" in source.cosmetic_titles
        assert "Black Knight" in source.cosmetic_titles
        assert "Floss" in source.cosmetic_titles
        assert "Mako" in source.cosmetic_titles


# -- resolver tests --------------------------------------------------------

class TestFortniteResolver:
    def test_resolver_populates_all_fields(self, load_fixture):
        request = PipelineRequest(
            game="fortnite",
            category="account",
            kind="stock",
            sources={"lzt": load_fixture("lzt_fn.json")},
        )
        account = FortniteResolver().resolve(request)

        assert account.level == 320
        assert account.platform == "PC"
        assert account.skin_count == 150
        assert account.v_bucks == 2500
        assert account.has_email_access is True

    def test_resolver_rejects_missing_source(self):
        request = PipelineRequest(
            game="fortnite",
            category="account",
            kind="stock",
            sources={},
        )
        with pytest.raises(Exception, match="lzt"):
            FortniteResolver().resolve(request)

    def test_resolver_dropshipping_clears_credentials(self, load_fixture):
        request = PipelineRequest(
            game="fortnite",
            category="account",
            kind="dropshipping",
            sources={"lzt": load_fixture("lzt_fn.json")},
        )
        account = FortniteResolver().resolve(request)
        assert account.credentials.is_empty


# -- composer tests --------------------------------------------------------

class TestFortniteComposer:
    def test_compose_produces_listing_draft(self, load_fixture):
        from payload_pipeline.games.fn.account.content import FortniteComposer

        request = PipelineRequest(
            game="fortnite",
            category="account",
            kind="stock",
            sources={"lzt": load_fixture("lzt_fn.json")},
        )
        account = FortniteResolver().resolve(request)
        draft = FortniteComposer().compose(account, request, MediaBundle())

        assert draft.default.title
        assert "150 skins" in draft.default.title
        assert "Has Warranty" in draft.default.description
        assert "fortnite" in draft.default.tags


# -- registry tests --------------------------------------------------------

class TestFortniteRegistration:
    def test_fn_in_default_registry(self):
        registry = build_default_registry()
        assert registry.has_game("fortnite")

    def test_fn_has_all_marketplaces(self):
        registry = build_default_registry()
        defn = registry.get_game("fortnite", "account")
        assert set(defn.marketplaces.keys()) == {"eldorado", "gameboost", "g2g"}


# -- end-to-end pipeline tests --------------------------------------------

class TestFortnitePipeline:
    def test_pipeline_builds_all_marketplaces(self, load_fixture):
        sources = {"lzt": load_fixture("lzt_fn.json")}
        pipeline = PayloadPipeline(registry=build_default_registry())
        request = PipelineRequest(
            game="fortnite",
            category="account",
            kind="stock",
            sources=sources,
            context={ctx.G2G_SELLER_ID: "1000959019"},
        )
        _prepare_result = pipeline.prepare_once(request)
        assert _prepare_result.success, f"prepare_once failed: {_prepare_result.error}"
        prepared = _prepare_result.prepared
        marketplaces = ["eldorado", "gameboost", "g2g"]
        results = {}
        for mp in marketplaces:
            build_ctx = BuildContext(kind="stock", marketplace=mp)
            if mp == "g2g":
                build_ctx = BuildContext(kind="stock", marketplace=mp, marketplace_config=G2GConfig(seller_id="1000959019"))
            result = pipeline.build(prepared, build_ctx)
            assert result.success
            results[mp] = result.payload
        assert set(results.keys()) == {"eldorado", "gameboost", "g2g"}

    def test_eldorado_payload_shape(self, load_fixture):
        sources = {"lzt": load_fixture("lzt_fn.json")}
        pipeline = PayloadPipeline(registry=build_default_registry())
        request = PipelineRequest(
            game="fortnite",
            category="account",
            kind="stock",
            sources=sources,
            context={ctx.G2G_SELLER_ID: "1000959019"},
        )
        _prepare_result = pipeline.prepare_once(request)
        assert _prepare_result.success, f"prepare_once failed: {_prepare_result.error}"
        prepared = _prepare_result.prepared
        result = pipeline.build(prepared, BuildContext(kind="stock", marketplace="eldorado"))
        assert result.success

        assert result.payload["augmentedGame"]["gameId"] == "16"
        assert result.payload["augmentedGame"]["category"] == "Account"
        assert result.payload["details"]["pricing"]["pricePerUnit"]["currency"] == "USD"
        assert result.payload["accountSecretDetails"]

    def test_gameboost_payload_shape(self, load_fixture):
        sources = {"lzt": load_fixture("lzt_fn.json")}
        pipeline = PayloadPipeline(registry=build_default_registry())
        request = PipelineRequest(
            game="fortnite",
            category="account",
            kind="stock",
            sources=sources,
            context={ctx.G2G_SELLER_ID: "1000959019"},
        )
        _prepare_result = pipeline.prepare_once(request)
        assert _prepare_result.success, f"prepare_once failed: {_prepare_result.error}"
        prepared = _prepare_result.prepared
        result = pipeline.build(prepared, BuildContext(kind="stock", marketplace="gameboost"))
        assert result.success

        assert result.payload["game"] == "fortnite"
        assert result.payload["account_data"]["outfits_count"] == 150
        assert result.payload["account_data"]["v_bucks_count"] == 2500
        assert result.payload["account_data"]["account_level"] == 320
        assert result.payload["login"]

    def test_g2g_payload_shape(self, load_fixture):
        sources = {"lzt": load_fixture("lzt_fn.json")}
        pipeline = PayloadPipeline(registry=build_default_registry())
        request = PipelineRequest(
            game="fortnite",
            category="account",
            kind="stock",
            sources=sources,
            context={ctx.G2G_SELLER_ID: "1000959019"},
        )
        _prepare_result = pipeline.prepare_once(request)
        assert _prepare_result.success, f"prepare_once failed: {_prepare_result.error}"
        prepared = _prepare_result.prepared
        result = pipeline.build(prepared, BuildContext(kind="stock", marketplace="g2g", marketplace_config=G2GConfig(seller_id="1000959019")))
        assert result.success

        assert result.payload["brand_id"] == "lgc_game_24742"
        assert result.payload["currency"] == "USD"
        assert result.payload["title"]
        assert result.payload["offer_attributes"]
        assert result.payload["unit_price"] > 0

    def test_prepare_once_populates_subject(self, load_fixture):
        sources = {"lzt": load_fixture("lzt_fn.json")}
        pipeline = PayloadPipeline(registry=build_default_registry())
        request = PipelineRequest(
            game="fortnite",
            category="account",
            kind="stock",
            sources=sources,
            context={ctx.G2G_SELLER_ID: "1000959019"},
        )
        _prepare_result = pipeline.prepare_once(request)
        assert _prepare_result.success, f"prepare_once failed: {_prepare_result.error}"
        prepared = _prepare_result.prepared
        subject = prepared.subject

        assert subject.skin_count == 150
        assert subject.level == 320
