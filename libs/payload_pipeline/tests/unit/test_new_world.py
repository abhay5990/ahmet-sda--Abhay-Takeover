"""Tests for the New World account and item slices."""

from __future__ import annotations

import pytest

from payload_pipeline import PayloadPipeline, build_default_registry
from payload_pipeline.core.contracts import BuildContext, PipelineRequest
from payload_pipeline.core.enums import ListingCategory
from payload_pipeline.games.nw.account import (
    NwAccountComposer,
    NwAccountResolver,
    NwEldoradoBuilder,
    NwManualSourceAdapter,
    NwPlayerAuctionsBuilder,
)
from payload_pipeline.games.nw.item import (
    NwItemComposer,
    NwItemGameBoostBuilder,
    NwItemManualSourceAdapter,
    NwItemResolver,
)

from _variant_ctx import nw_eldorado, nw_playerauctions


# ── helpers ──────────────────────────────────────────────────────

def _account_source(price: float = 25.0, region: str = "US-East", **kwargs) -> dict:
    base = {
        "item_id": "nw-acc-001",
        "price": price,
        "loginData": {"login": "nw_user@example.com", "password": "NwPass123"},
        "offer_details": {"region": region},
    }
    base.update(kwargs)
    return base


def _item_source(price: float = 10.0, region: str = "North America", **kwargs) -> dict:
    base = {
        "item_id": "nw-item-001",
        "price": price,
        "loginData": {"login": "nw_item_user@example.com", "password": "ItemPass123"},
        "offer_details": {"region": region},
    }
    base.update(kwargs)
    return base


def _account_request(kind: str = "stock", raw: dict | None = None) -> PipelineRequest:
    return PipelineRequest(
        game="new-world",
        category="account",
        kind=kind,
        sources={"manual": raw or _account_source()},
        context={"disable_media": True},
    )


def _item_request(kind: str = "stock", raw: dict | None = None) -> PipelineRequest:
    return PipelineRequest(
        game="new-world",
        category="item",
        kind=kind,
        sources={"manual": raw or _item_source()},
        context={"disable_media": True},
    )


# ── account source adapter ────────────────────────────────────────

class TestNwManualSourceAdapter:
    def test_parse_returns_none_for_empty(self):
        adapter = NwManualSourceAdapter()
        assert adapter.parse(None) is None
        assert adapter.parse({}) is None

    def test_parse_extracts_region_from_offer_details(self):
        source = NwManualSourceAdapter().parse(_account_source(region="EU-Central"))
        assert source is not None
        assert source.region == "EU-Central"

    def test_parse_region_fallback_to_root(self):
        raw = {"item_id": "x", "price": 5.0, "region": "US-West"}
        source = NwManualSourceAdapter().parse(raw)
        assert source is not None
        assert source.region == "US-West"

    def test_parse_extracts_credentials(self):
        source = NwManualSourceAdapter().parse(_account_source())
        assert source is not None
        assert source.credentials.login == "nw_user@example.com"
        assert source.credentials.password == "NwPass123"


# ── account resolver ──────────────────────────────────────────────

class TestNwAccountResolver:
    def test_resolve_populates_region(self):
        account = NwAccountResolver().resolve(_account_request(raw=_account_source(region="EU-Central")))
        assert account.region == "EU-Central"

    def test_resolve_stock_keeps_credentials(self):
        account = NwAccountResolver().resolve(_account_request(kind="stock"))
        assert not account.credentials.is_empty

    def test_resolve_dropshipping_clears_credentials(self):
        account = NwAccountResolver().resolve(_account_request(kind="dropshipping"))
        assert account.credentials.is_empty

    def test_resolve_raises_without_manual_source(self):
        request = PipelineRequest(
            game="new-world", category="account", kind="stock", sources={},
        )
        with pytest.raises(Exception, match="manual"):
            NwAccountResolver().resolve(request)


# ── account registry ──────────────────────────────────────────────

class TestNwAccountRegistration:
    def test_nw_account_in_default_registry(self):
        assert build_default_registry().has_game("new-world", ListingCategory.ACCOUNT)

    def test_nw_account_has_correct_marketplaces(self):
        defn = build_default_registry().get_game("new-world", "account")
        assert set(defn.marketplaces.keys()) == {"eldorado", "playerauctions"}


# ── account Eldorado payload ──────────────────────────────────────

class TestNwEldoradoPayload:
    def _build(self, region: str = "US-East", kind: str = "stock") -> dict:
        pipeline = PayloadPipeline(registry=build_default_registry())
        prep = pipeline.prepare_once(_account_request(kind=kind, raw=_account_source(region=region)))
        assert prep.success
        result = pipeline.build(
            prep.prepared,
            BuildContext(kind=kind, marketplace="eldorado", variant_context=nw_eldorado()),
        )
        assert result.success, f"build failed: {result.error}"
        return result.payload

    def test_game_id_is_36(self):
        assert self._build()["augmentedGame"]["gameId"] == "36"

    def test_us_east_maps_to_trade_env_0(self):
        assert self._build(region="US-East")["augmentedGame"]["tradeEnvironmentId"] == "0"

    def test_us_west_maps_to_trade_env_1(self):
        assert self._build(region="US-West")["augmentedGame"]["tradeEnvironmentId"] == "1"

    def test_ap_southeast_maps_to_trade_env_2(self):
        assert self._build(region="AP Southeast")["augmentedGame"]["tradeEnvironmentId"] == "2"

    def test_sa_east_maps_to_trade_env_3(self):
        assert self._build(region="SA East")["augmentedGame"]["tradeEnvironmentId"] == "3"

    def test_eu_central_maps_to_trade_env_4(self):
        assert self._build(region="EU-Central")["augmentedGame"]["tradeEnvironmentId"] == "4"

    def test_no_attributes(self):
        assert "offerAttributes" not in self._build()["augmentedGame"]

    def test_fallback_trade_env_when_no_variant_context(self):
        pipeline = PayloadPipeline(registry=build_default_registry())
        prep = pipeline.prepare_once(_account_request())
        assert prep.success
        result = pipeline.build(
            prep.prepared,
            BuildContext(kind="stock", marketplace="eldorado"),
        )
        assert result.success
        assert result.payload["augmentedGame"]["tradeEnvironmentId"] == "0"

    def test_dropship_omits_credentials(self):
        assert "accountSecretDetails" not in self._build(kind="dropshipping")


# ── account PlayerAuctions payload ────────────────────────────────

class TestNwPlayerAuctionsPayload:
    def _build(self, region: str = "US-East") -> dict:
        pipeline = PayloadPipeline(registry=build_default_registry())
        prep = pipeline.prepare_once(_account_request(raw=_account_source(region=region)))
        assert prep.success
        result = pipeline.build(
            prep.prepared,
            BuildContext(kind="stock", marketplace="playerauctions", variant_context=nw_playerauctions()),
        )
        assert result.success, f"build failed: {result.error}"
        return result.payload

    def test_game_id_is_9045(self):
        assert self._build()["gameId"] == 9045

    def test_us_east_server_id_is_9920(self):
        assert self._build(region="US-East")["serverId"] == 9920

    def test_us_west_server_id_is_9916(self):
        assert self._build(region="US-West")["serverId"] == 9916

    def test_eu_central_server_id_is_9919(self):
        assert self._build(region="EU-Central")["serverId"] == 9919

    def test_fallback_server_id_when_no_variant_context(self):
        pipeline = PayloadPipeline(registry=build_default_registry())
        prep = pipeline.prepare_once(_account_request())
        assert prep.success
        result = pipeline.build(
            prep.prepared,
            BuildContext(kind="stock", marketplace="playerauctions"),
        )
        assert result.success
        assert result.payload["serverId"] == 9920  # US East fallback


# ── item source adapter ───────────────────────────────────────────

class TestNwItemManualSourceAdapter:
    def test_parse_returns_none_for_empty(self):
        adapter = NwItemManualSourceAdapter()
        assert adapter.parse(None) is None
        assert adapter.parse({}) is None

    def test_parse_extracts_region(self):
        source = NwItemManualSourceAdapter().parse(_item_source(region="Europe"))
        assert source is not None
        assert source.region == "Europe"

    def test_parse_extracts_price_and_credentials(self):
        source = NwItemManualSourceAdapter().parse(_item_source(price=8.5))
        assert source is not None
        assert source.price == 8.5
        assert source.credentials.login == "nw_item_user@example.com"


# ── item resolver ─────────────────────────────────────────────────

class TestNwItemResolver:
    def test_resolve_populates_region(self):
        item = NwItemResolver().resolve(_item_request(raw=_item_source(region="Europe")))
        assert item.region == "Europe"

    def test_resolve_stock_keeps_credentials(self):
        item = NwItemResolver().resolve(_item_request(kind="stock"))
        assert not item.credentials.is_empty

    def test_resolve_dropshipping_clears_credentials(self):
        item = NwItemResolver().resolve(_item_request(kind="dropshipping"))
        assert item.credentials.is_empty

    def test_resolve_raises_without_manual_source(self):
        request = PipelineRequest(
            game="new-world", category="item", kind="stock", sources={},
        )
        with pytest.raises(Exception, match="manual"):
            NwItemResolver().resolve(request)


# ── item registry ─────────────────────────────────────────────────

class TestNwItemRegistration:
    def test_nw_item_in_default_registry(self):
        assert build_default_registry().has_game("new-world", ListingCategory.ITEM)

    def test_nw_item_has_gameboost_only(self):
        defn = build_default_registry().get_game("new-world", "item")
        assert set(defn.marketplaces.keys()) == {"gameboost"}


# ── item GameBoost payload ────────────────────────────────────────

class TestNwItemGameBoostPayload:
    def _build(self, region: str = "North America", kind: str = "stock") -> dict:
        pipeline = PayloadPipeline(registry=build_default_registry())
        prep = pipeline.prepare_once(_item_request(kind=kind, raw=_item_source(region=region)))
        assert prep.success
        result = pipeline.build(
            prep.prepared,
            BuildContext(kind=kind, marketplace="gameboost"),
        )
        assert result.success, f"build failed: {result.error}"
        return result.payload

    def test_game_is_new_world(self):
        assert self._build()["game"] == "new-world"

    def test_item_data_server_matches_region(self):
        assert self._build(region="Europe")["item_data"]["server"] == "Europe"

    def test_item_data_server_fallback_when_empty(self):
        pipeline = PayloadPipeline(registry=build_default_registry())
        prep = pipeline.prepare_once(_item_request(raw=_item_source(region="")))
        assert prep.success
        result = pipeline.build(prep.prepared, BuildContext(kind="stock", marketplace="gameboost"))
        assert result.success
        assert result.payload["item_data"]["server"] == "North America"

    def test_stock_sets_delivery_instructions_with_credentials(self):
        payload = self._build(kind="stock")
        assert payload["delivery_instructions"]
        assert "nw_item_user@example.com" in payload["delivery_instructions"]

    def test_dropship_uses_generic_delivery(self):
        payload = self._build(kind="dropshipping")
        # dropshipping delivery instructions should NOT contain account credentials
        assert "nw_item_user@example.com" not in payload["delivery_instructions"]

    def test_stock_field_is_1(self):
        assert self._build()["stock"] == 1

    def test_title_and_description_are_set(self):
        payload = self._build()
        assert payload["title"]
        assert payload["description"]
