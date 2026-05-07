"""Tests for the Roblox account slice."""

from __future__ import annotations

import pytest

from payload_pipeline import PayloadPipeline, build_default_registry
from payload_pipeline.core import context_keys as ctx
from payload_pipeline.core.contracts import BuildContext, MediaBundle, PipelineRequest
from payload_pipeline.games.roblox.account import RobloxResolver
from payload_pipeline.games.roblox.account.sources.lzt import RobloxLztSourceAdapter
from payload_pipeline.marketplaces.g2g import G2GConfig


# -- source adapter tests -------------------------------------------------

class TestRobloxLztSourceAdapter:
    def test_parse_returns_none_for_empty_input(self):
        adapter = RobloxLztSourceAdapter()
        assert adapter.parse(None) is None
        assert adapter.parse({}) is None

    def test_parse_extracts_core_fields(self, load_fixture):
        adapter = RobloxLztSourceAdapter()
        raw = load_fixture("lzt_roblox.json")
        source = adapter.parse(raw)

        assert source is not None
        assert source.item_id == str(raw["item_id"])
        assert source.roblox_id == raw["roblox_id"]
        assert source.robux == raw["roblox_robux"]
        assert source.incoming_robux_total == raw["roblox_incoming_robux_total"]
        assert source.inventory_price == float(raw["roblox_inventory_price"])
        assert source.ugc_limited_price == float(raw["roblox_ugc_limited_price"])
        assert source.limited_price == float(raw["roblox_limited_price"])
        assert source.offsale_count == raw["roblox_offsale_count"]
        assert source.friends == raw["roblox_friends"]
        assert source.followers == raw["roblox_followers"]
        assert source.age_verified is bool(raw["roblox_age_verified"])
        assert source.email_verified is bool(raw["roblox_email_verified"])
        assert source.verified is bool(raw["roblox_verified"])
        assert source.has_subscription is bool(raw["roblox_subscription"])
        assert source.voice_enabled is bool(raw["roblox_voice"])
        assert source.country == raw["roblox_country"].lower()

    def test_parse_extracts_credentials(self, load_fixture):
        adapter = RobloxLztSourceAdapter()
        raw = load_fixture("lzt_roblox.json")
        source = adapter.parse(raw)

        assert source is not None
        assert source.credentials.login == raw["loginData"]["login"]
        assert source.credentials.password == raw["loginData"]["password"]
        assert source.credentials.email_login == raw["emailLoginData"]["login"]


# -- resolver tests --------------------------------------------------------

class TestRobloxResolver:
    def test_resolver_populates_all_fields(self, load_fixture):
        raw = load_fixture("lzt_roblox.json")
        request = PipelineRequest(
            game="roblox",
            category="account",
            kind="stock",
            sources={"lzt": raw},
        )
        account = RobloxResolver().resolve(request)

        assert account.robux == raw["roblox_robux"]
        assert account.inventory_price == float(raw["roblox_inventory_price"])
        assert account.followers == raw["roblox_followers"]
        assert account.verified is bool(raw["roblox_verified"])
        assert account.has_email_access is True

    def test_resolver_rejects_missing_source(self):
        request = PipelineRequest(
            game="roblox",
            category="account",
            kind="stock",
            sources={},
        )
        with pytest.raises(Exception, match="lzt"):
            RobloxResolver().resolve(request)

    def test_resolver_dropshipping_clears_credentials(self, load_fixture):
        request = PipelineRequest(
            game="roblox",
            category="account",
            kind="dropshipping",
            sources={"lzt": load_fixture("lzt_roblox.json")},
        )
        account = RobloxResolver().resolve(request)
        assert account.credentials.is_empty


# -- composer tests --------------------------------------------------------

class TestRobloxComposer:
    def test_compose_produces_listing_draft(self, load_fixture):
        from payload_pipeline.games.roblox.account.content import RobloxComposer

        request = PipelineRequest(
            game="roblox",
            category="account",
            kind="stock",
            sources={"lzt": load_fixture("lzt_roblox.json")},
        )
        account = RobloxResolver().resolve(request)
        draft = RobloxComposer().compose(account, request, MediaBundle())

        assert draft.default.title
        assert "FULL ACCESS" in draft.default.title
        assert f"Robux: {account.robux}" in draft.default.description
        assert "roblox" in draft.default.tags


# -- registry tests --------------------------------------------------------

class TestRobloxRegistration:
    def test_roblox_in_default_registry(self):
        registry = build_default_registry()
        assert registry.has_game("roblox")

    def test_roblox_has_all_marketplaces(self):
        registry = build_default_registry()
        defn = registry.get_game("roblox", "account")
        assert set(defn.marketplaces.keys()) == {"eldorado", "gameboost", "g2g"}


# -- end-to-end pipeline tests --------------------------------------------

class TestRobloxPipeline:
    def test_pipeline_builds_all_marketplaces(self, load_fixture):
        pipeline = PayloadPipeline(registry=build_default_registry())
        request = PipelineRequest(
            game="roblox",
            category="account",
            kind="stock",
            sources={"lzt": load_fixture("lzt_roblox.json")},
            context={ctx.DISABLE_MEDIA: True},
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
            game="roblox",
            category="account",
            kind="stock",
            sources={"lzt": load_fixture("lzt_roblox.json")},
            context={ctx.DISABLE_MEDIA: True},
        )
        _prepare_result = pipeline.prepare_once(request)
        assert _prepare_result.success, f"prepare_once failed: {_prepare_result.error}"
        prepared = _prepare_result.prepared
        result = pipeline.build(prepared, BuildContext(kind="stock", marketplace="eldorado"))
        assert result.success

        assert result.payload["augmentedGame"]["gameId"] == "70"
        assert result.payload["augmentedGame"]["category"] == "Account"
        assert result.payload["details"]["pricing"]["pricePerUnit"]["currency"] == "USD"
        assert result.payload["accountSecretDetails"]

    def test_gameboost_payload_shape(self, load_fixture):
        raw = load_fixture("lzt_roblox.json")
        pipeline = PayloadPipeline(registry=build_default_registry())
        request = PipelineRequest(
            game="roblox",
            category="account",
            kind="stock",
            sources={"lzt": raw},
            context={ctx.DISABLE_MEDIA: True},
        )
        _prepare_result = pipeline.prepare_once(request)
        assert _prepare_result.success, f"prepare_once failed: {_prepare_result.error}"
        prepared = _prepare_result.prepared
        result = pipeline.build(prepared, BuildContext(kind="stock", marketplace="gameboost"))
        assert result.success

        assert result.payload["game"] == "roblox"
        assert result.payload["account_data"]["robux_count"] == raw["roblox_robux"]
        assert "inventory_value" not in result.payload["account_data"]
        assert "age_verified" not in result.payload["account_data"]
        assert result.payload["login"]

    def test_g2g_payload_shape(self, load_fixture):
        pipeline = PayloadPipeline(registry=build_default_registry())
        request = PipelineRequest(
            game="roblox",
            category="account",
            kind="stock",
            sources={"lzt": load_fixture("lzt_roblox.json")},
            context={ctx.DISABLE_MEDIA: True},
        )
        _prepare_result = pipeline.prepare_once(request)
        assert _prepare_result.success, f"prepare_once failed: {_prepare_result.error}"
        prepared = _prepare_result.prepared
        result = pipeline.build(prepared, BuildContext(kind="stock", marketplace="g2g", marketplace_config=G2GConfig(seller_id="1000959019")))
        assert result.success

        assert result.payload["brand_id"] == "lgc_game_24333"
        assert result.payload["currency"] == "USD"
        assert result.payload["title"]
        assert result.payload["unit_price"] > 0

    def test_run_many_populates_subject(self, load_fixture):
        raw = load_fixture("lzt_roblox.json")
        pipeline = PayloadPipeline(registry=build_default_registry())
        request = PipelineRequest(
            game="roblox",
            category="account",
            kind="stock",
            sources={"lzt": raw},
            context={ctx.DISABLE_MEDIA: True},
        )
        _prepare_result = pipeline.prepare_once(request)
        assert _prepare_result.success, f"prepare_once failed: {_prepare_result.error}"
        prepared = _prepare_result.prepared
        subject = prepared.subject

        assert subject.robux == raw["roblox_robux"]
        assert subject.followers == raw["roblox_followers"]
