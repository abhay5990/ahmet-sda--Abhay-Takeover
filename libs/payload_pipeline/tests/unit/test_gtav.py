"""Tests for the GTA V account slice."""

from __future__ import annotations

import pytest

from payload_pipeline import PayloadPipeline, build_default_registry
from payload_pipeline.core import context_keys as ctx
from payload_pipeline.core.contracts import BuildContext, PipelineRequest
from payload_pipeline.games.gtav.account import GtavResolver
from payload_pipeline.games.gtav.account.sources.lzt import GtavLztSourceAdapter
from payload_pipeline.marketplaces.g2g import G2GConfig


# -- source adapter tests -------------------------------------------------

class TestGtavLztSourceAdapter:
    def test_parse_returns_none_for_empty_input(self):
        adapter = GtavLztSourceAdapter()
        assert adapter.parse(None) is None
        assert adapter.parse({}) is None

    def test_parse_extracts_core_fields(self, load_fixture):
        adapter = GtavLztSourceAdapter()
        source = adapter.parse(load_fixture("lzt_gtav.json"))

        assert source is not None
        assert source.item_id == "330012001"
        assert source.category_id == 22
        assert source.main_platform == "PC - Enhanced"
        assert source.level == 350
        assert source.cash_amount == 120
        assert source.cash_unit == "Million"
        assert source.cars_count == 45
        assert source.tags == ["Modded", "High Level", "Full Access"]

    def test_parse_extracts_credentials(self, load_fixture):
        adapter = GtavLztSourceAdapter()
        source = adapter.parse(load_fixture("lzt_gtav.json"))

        assert source.credentials.login == "rockstar_user@example.com"
        assert source.credentials.password == "RockstarPass123"
        assert source.credentials.email_login == "backup_email@example.com"
        assert source.credentials.email_password == "EmailPass456"

    def test_parse_extracts_security_fields(self, load_fixture):
        adapter = GtavLztSourceAdapter()
        source = adapter.parse(load_fixture("lzt_gtav.json"))

        assert source.security_email == "security@example.com"
        assert source.security_email_password == "SecPass789"
        assert source.birthday == "1995-06-15"
        assert source.email_backup_codes == "CODE1-ABCD\nCODE2-EFGH\nCODE3-IJKL"

    def test_parse_extracts_per_marketplace_pricing(self, load_fixture):
        adapter = GtavLztSourceAdapter()
        source = adapter.parse(load_fixture("lzt_gtav.json"))

        assert source.eldorado_price == 399.99
        assert source.gameboost_price == 449.99
        assert source.playerauctions_price == 379.99

    def test_parse_extracts_title_from_offer_details(self, load_fixture):
        adapter = GtavLztSourceAdapter()
        source = adapter.parse(load_fixture("lzt_gtav.json"))

        assert "Level 350" in source.title
        assert "120M Cash" in source.title


# -- resolver tests --------------------------------------------------------

class TestGtavResolver:
    def test_resolver_populates_all_fields(self, load_fixture):
        request = PipelineRequest(
            game="grand-theft-auto-5",
            category="account",
            kind="stock",
            sources={"lzt": load_fixture("lzt_gtav.json")},
        )
        account = GtavResolver().resolve(request)

        assert account.main_platform == "PC - Enhanced"
        assert account.level == 350
        assert account.cash_amount == 120
        assert account.cash_unit == "Million"
        assert account.cars_count == 45
        assert account.tags == ["Modded", "High Level", "Full Access"]
        assert account.has_email_access is True
        assert account.eldorado_price == 399.99
        assert account.gameboost_price == 449.99
        assert account.playerauctions_price == 379.99
        assert account.security_email == "security@example.com"
        assert account.birthday == "1995-06-15"

    def test_resolver_rejects_missing_source(self):
        request = PipelineRequest(
            game="grand-theft-auto-5",
            category="account",
            kind="stock",
            sources={},
        )
        with pytest.raises(Exception, match="lzt"):
            GtavResolver().resolve(request)

    def test_resolver_dropshipping_clears_credentials(self, load_fixture):
        request = PipelineRequest(
            game="grand-theft-auto-5",
            category="account",
            kind="dropshipping",
            sources={"lzt": load_fixture("lzt_gtav.json")},
        )
        account = GtavResolver().resolve(request)
        assert account.credentials.is_empty


# -- composer tests --------------------------------------------------------

class TestGtavComposer:
    def test_compose_produces_listing_draft(self, load_fixture):
        from payload_pipeline.games.gtav.account.content import GtavComposer
        from payload_pipeline.core.contracts import MediaBundle

        request = PipelineRequest(
            game="grand-theft-auto-5",
            category="account",
            kind="stock",
            sources={"lzt": load_fixture("lzt_gtav.json")},
        )
        account = GtavResolver().resolve(request)
        draft = GtavComposer().compose(account, request, MediaBundle())

        assert draft.default.title
        assert "GTA V" in draft.default.description or "Platform" in draft.default.description
        assert "gta-v" in draft.default.tags

    def test_compose_g2g_override_shorter(self, load_fixture):
        from payload_pipeline.games.gtav.account.content import GtavComposer
        from payload_pipeline.core.contracts import MediaBundle

        request = PipelineRequest(
            game="grand-theft-auto-5",
            category="account",
            kind="stock",
            sources={"lzt": load_fixture("lzt_gtav.json")},
        )
        account = GtavResolver().resolve(request)
        draft = GtavComposer().compose(account, request, MediaBundle())

        g2g_content = draft.content_for("g2g")
        assert len(g2g_content.title) <= 120 or g2g_content.title == draft.default.title


# -- registry tests --------------------------------------------------------

class TestGtavRegistration:
    def test_gtav_in_default_registry(self):
        registry = build_default_registry()
        assert registry.has_game("grand-theft-auto-5")

    def test_gtav_has_all_marketplaces(self):
        registry = build_default_registry()
        defn = registry.get_game("grand-theft-auto-5", "account")
        assert set(defn.marketplaces.keys()) == {
            "eldorado", "gameboost", "g2g", "playerauctions",
        }


# -- end-to-end pipeline tests --------------------------------------------

class TestGtavPipeline:
    def test_pipeline_builds_all_marketplaces(self, load_fixture):
        sources = {"lzt": load_fixture("lzt_gtav.json")}
        pipeline = PayloadPipeline(registry=build_default_registry())
        request = PipelineRequest(
            game="grand-theft-auto-5",
            category="account",
            kind="stock",
            sources=sources,
            context={ctx.G2G_SELLER_ID: "1000959019"},
        )
        _prepare_result = pipeline.prepare_once(request)
        assert _prepare_result.success, f"prepare_once failed: {_prepare_result.error}"
        prepared = _prepare_result.prepared
        marketplaces = ["eldorado", "gameboost", "g2g", "playerauctions"]
        results = {}
        for mp in marketplaces:
            build_ctx = BuildContext(kind="stock", marketplace=mp)
            if mp == "g2g":
                build_ctx = BuildContext(kind="stock", marketplace=mp, marketplace_config=G2GConfig(seller_id="1000959019"))
            result = pipeline.build(prepared, build_ctx)
            assert result.success
            results[mp] = result.payload
        assert set(results.keys()) == {"eldorado", "gameboost", "g2g", "playerauctions"}

    def test_eldorado_payload_shape(self, load_fixture):
        sources = {"lzt": load_fixture("lzt_gtav.json")}
        pipeline = PayloadPipeline(registry=build_default_registry())
        request = PipelineRequest(
            game="grand-theft-auto-5",
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

        assert result.payload["augmentedGame"]["gameId"] == "25"
        assert result.payload["augmentedGame"]["category"] == "Account"
        assert result.payload["augmentedGame"]["tradeEnvironmentId"] == "0"  # PC - Enhanced -> 0
        assert result.payload["details"]["pricing"]["pricePerUnit"]["amount"] == 399.99
        assert result.payload["accountSecretDetails"]  # has security info

    def test_gameboost_payload_shape(self, load_fixture):
        sources = {"lzt": load_fixture("lzt_gtav.json")}
        pipeline = PayloadPipeline(registry=build_default_registry())
        request = PipelineRequest(
            game="grand-theft-auto-5",
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

        assert result.payload["game"] == "grand-theft-auto-v"
        assert result.payload["account_data"]["platform"] == "PC - Enhanced"
        assert result.payload["account_data"]["account_level"] == 350
        assert result.payload["account_data"]["cars_count"] == 45
        assert result.payload["account_data"]["cash_amount"] == "120 Million"
        assert result.payload["image_urls"]  # static image URL

    def test_g2g_payload_shape(self, load_fixture):
        sources = {"lzt": load_fixture("lzt_gtav.json")}
        pipeline = PayloadPipeline(registry=build_default_registry())
        request = PipelineRequest(
            game="grand-theft-auto-5",
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

        assert result.payload["brand_id"] == "lgc_game_24333"
        assert result.payload["softpin_data"]
        assert len(result.payload["offer_attributes"]) == 1
        assert result.payload["offer_attributes"][0]["dataset_id"] == "lgc_24333_platform_26098"

    def test_playerauctions_payload_shape(self, load_fixture):
        sources = {"lzt": load_fixture("lzt_gtav.json")}
        pipeline = PayloadPipeline(registry=build_default_registry())
        request = PipelineRequest(
            game="grand-theft-auto-5",
            category="account",
            kind="stock",
            sources=sources,
            context={ctx.G2G_SELLER_ID: "1000959019"},
        )
        _prepare_result = pipeline.prepare_once(request)
        assert _prepare_result.success, f"prepare_once failed: {_prepare_result.error}"
        prepared = _prepare_result.prepared
        result = pipeline.build(prepared, BuildContext(kind="stock", marketplace="playerauctions"))
        assert result.success

        assert result.payload["game_id"] == 8458
        assert result.payload["game_name"] == "grand-theft-auto-5"
        assert result.payload["cover_image_url"]
        assert result.payload["server"] == ["IOS", "Android"]
        assert result.payload["server_id"] == ["8458", "8459"]

    def test_prepare_once_populates_subject(self, load_fixture):
        sources = {"lzt": load_fixture("lzt_gtav.json")}
        pipeline = PayloadPipeline(registry=build_default_registry())
        request = PipelineRequest(
            game="grand-theft-auto-5",
            category="account",
            kind="stock",
            sources=sources,
            context={ctx.G2G_SELLER_ID: "1000959019"},
        )
        _prepare_result = pipeline.prepare_once(request)
        assert _prepare_result.success, f"prepare_once failed: {_prepare_result.error}"
        prepared = _prepare_result.prepared
        subject = prepared.subject

        assert subject.main_platform == "PC - Enhanced"
        assert subject.level == 350


# -- determinism & mapping intent tests ------------------------------------

class TestGtavG2GDeterminism:
    """G2G payloads must be identical across repeated builds for the same input."""

    def test_g2g_payload_is_deterministic(self, load_fixture):
        sources = {"lzt": load_fixture("lzt_gtav.json")}
        payloads = []
        for _ in range(5):
            pipeline = PayloadPipeline(registry=build_default_registry())
            request = PipelineRequest(game="grand-theft-auto-5", category="account", kind="stock", sources=sources, context={ctx.G2G_SELLER_ID: "1000959019"})
            _prepare_result = pipeline.prepare_once(request)
            assert _prepare_result.success, f"prepare_once failed: {_prepare_result.error}"
            prepared = _prepare_result.prepared
            result = pipeline.build(prepared, BuildContext(kind="stock", marketplace="g2g", marketplace_config=G2GConfig(seller_id="1000959019")))
            assert result.success
            payloads.append(result.payload)
        first = payloads[0]
        for p in payloads[1:]:
            assert p == first, "G2G payload must be deterministic across invocations"

    def test_g2g_platform_is_always_android(self, load_fixture):
        """Legacy fallback: always Android (lgc_24333_platform_26098)."""
        sources = {"lzt": load_fixture("lzt_gtav.json")}
        for _ in range(5):
            pipeline = PayloadPipeline(registry=build_default_registry())
            request = PipelineRequest(game="grand-theft-auto-5", category="account", kind="stock", sources=sources, context={ctx.G2G_SELLER_ID: "1000959019"})
            _prepare_result = pipeline.prepare_once(request)
            assert _prepare_result.success, f"prepare_once failed: {_prepare_result.error}"
            prepared = _prepare_result.prepared
            result = pipeline.build(prepared, BuildContext(kind="stock", marketplace="g2g", marketplace_config=G2GConfig(seller_id="1000959019")))
            assert result.success
            attrs = result.payload["offer_attributes"]
            assert len(attrs) == 1
            assert attrs[0]["collection_id"] == "lgc_24333_platform"
            assert attrs[0]["dataset_id"] == "lgc_24333_platform_26098"


class TestGtavPlayerAuctionsMappingIntent:
    """PlayerAuctions mapping values are intentional legacy defaults."""

    def test_server_values_are_legacy_defaults(self, load_fixture):
        """server/server_id are seller-wide PA defaults, not mobile-specific."""
        sources = {"lzt": load_fixture("lzt_gtav.json")}
        pipeline = PayloadPipeline(registry=build_default_registry())
        request = PipelineRequest(game="grand-theft-auto-5", category="account", kind="stock", sources=sources, context={ctx.G2G_SELLER_ID: "1000959019"})
        _prepare_result = pipeline.prepare_once(request)
        assert _prepare_result.success, f"prepare_once failed: {_prepare_result.error}"
        prepared = _prepare_result.prepared
        result = pipeline.build(prepared, BuildContext(kind="stock", marketplace="playerauctions"))
        assert result.success
        assert result.payload["server"] == ["IOS", "Android"]
        assert result.payload["server_id"] == ["8458", "8459"]

    def test_game_id_matches_legacy(self, load_fixture):
        sources = {"lzt": load_fixture("lzt_gtav.json")}
        pipeline = PayloadPipeline(registry=build_default_registry())
        request = PipelineRequest(game="grand-theft-auto-5", category="account", kind="stock", sources=sources, context={ctx.G2G_SELLER_ID: "1000959019"})
        _prepare_result = pipeline.prepare_once(request)
        assert _prepare_result.success, f"prepare_once failed: {_prepare_result.error}"
        prepared = _prepare_result.prepared
        result = pipeline.build(prepared, BuildContext(kind="stock", marketplace="playerauctions"))
        assert result.success
        assert result.payload["game_id"] == 8458
        assert result.payload["game_name"] == "grand-theft-auto-5"

    def test_playerauctions_payload_is_deterministic(self, load_fixture):
        sources = {"lzt": load_fixture("lzt_gtav.json")}
        payloads = []
        for _ in range(5):
            pipeline = PayloadPipeline(registry=build_default_registry())
            request = PipelineRequest(game="grand-theft-auto-5", category="account", kind="stock", sources=sources, context={ctx.G2G_SELLER_ID: "1000959019"})
            _prepare_result = pipeline.prepare_once(request)
            assert _prepare_result.success, f"prepare_once failed: {_prepare_result.error}"
            prepared = _prepare_result.prepared
            result = pipeline.build(prepared, BuildContext(kind="stock", marketplace="playerauctions"))
            assert result.success
            payloads.append(result.payload)
        first = payloads[0]
        for p in payloads[1:]:
            assert p == first, "PA payload must be deterministic across invocations"
