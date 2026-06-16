"""Tests for the Forza Horizon 5 account slice."""

from __future__ import annotations

import pytest

from payload_pipeline import PayloadPipeline, build_default_registry
from payload_pipeline.core.contracts import BuildContext, PipelineRequest
from payload_pipeline.games.fh5.account import (
    Fh5Composer,
    Fh5EldoradoBuilder,
    Fh5GameBoostBuilder,
    Fh5PlayerAuctionsBuilder,
    Fh5Resolver,
)
from payload_pipeline.games.fh5.account.sources.manual import Fh5ManualSourceAdapter

from _variant_ctx import fh5_eldorado, fh5_gameboost, fh5_playerauctions


# ── helpers ──────────────────────────────────────────────────────

def _manual_source(
    price: float = 20.0,
    platform: str = "PC",
    edition: str = "Standard",
    cars_count: int = 100,
    credits_count: int = 5000000,
    **kwargs,
) -> dict:
    base = {
        "item_id": "fh5-001",
        "price": price,
        "loginData": {"login": "fh5_user@example.com", "password": "Fh5Pass123"},
        "offer_details": {
            "platform": platform,
            "edition": edition,
            "cars_count": cars_count,
            "credits_count": credits_count,
        },
    }
    base.update(kwargs)
    return base


def _make_request(kind: str = "stock", raw: dict | None = None) -> PipelineRequest:
    return PipelineRequest(
        game="forza-horizon-5",
        category="account",
        kind=kind,
        sources={"manual": raw or _manual_source()},
        context={"disable_media": True},
    )


# ── source adapter ────────────────────────────────────────────────

class TestFh5ManualSourceAdapter:
    def test_parse_returns_none_for_empty(self):
        adapter = Fh5ManualSourceAdapter()
        assert adapter.parse(None) is None
        assert adapter.parse({}) is None

    def test_parse_extracts_base_fields(self):
        source = Fh5ManualSourceAdapter().parse(_manual_source())
        assert source is not None
        assert source.price == 20.0
        assert source.item_id == "fh5-001"

    def test_parse_extracts_platform_from_offer_details(self):
        source = Fh5ManualSourceAdapter().parse(_manual_source(platform="Xbox"))
        assert source is not None
        assert source.platform == "Xbox"

    def test_parse_extracts_edition(self):
        source = Fh5ManualSourceAdapter().parse(_manual_source(edition="Premium"))
        assert source is not None
        assert source.edition == "Premium"

    def test_parse_extracts_car_and_credits(self):
        source = Fh5ManualSourceAdapter().parse(_manual_source(cars_count=250, credits_count=10_000_000))
        assert source is not None
        assert source.cars_count == 250
        assert source.credits_count == 10_000_000

    def test_parse_platform_fallback_to_root(self):
        raw = {"item_id": "x", "price": 5.0, "platform": "PS5"}
        source = Fh5ManualSourceAdapter().parse(raw)
        assert source is not None
        assert source.platform == "PS5"

    def test_parse_edition_defaults_to_standard(self):
        raw = {"item_id": "x", "price": 5.0}
        source = Fh5ManualSourceAdapter().parse(raw)
        assert source is not None
        assert source.edition == "Standard"


# ── resolver ─────────────────────────────────────────────────────

class TestFh5Resolver:
    def test_resolve_populates_all_fields(self):
        account = Fh5Resolver().resolve(_make_request())
        assert account.price == 20.0
        assert account.platform == "PC"
        assert account.edition == "Standard"
        assert account.cars_count == 100
        assert account.credits_count == 5_000_000

    def test_resolve_stock_keeps_credentials(self):
        account = Fh5Resolver().resolve(_make_request(kind="stock"))
        assert not account.credentials.is_empty

    def test_resolve_dropshipping_clears_credentials(self):
        account = Fh5Resolver().resolve(_make_request(kind="dropshipping"))
        assert account.credentials.is_empty

    def test_resolve_raises_without_manual_source(self):
        request = PipelineRequest(
            game="forza-horizon-5", category="account", kind="stock", sources={},
        )
        with pytest.raises(Exception, match="manual"):
            Fh5Resolver().resolve(request)


# ── registry ──────────────────────────────────────────────────────

class TestFh5Registration:
    def test_fh5_in_default_registry(self):
        assert build_default_registry().has_game("forza-horizon-5")

    def test_fh5_has_correct_marketplaces(self):
        defn = build_default_registry().get_game("forza-horizon-5", "account")
        assert set(defn.marketplaces.keys()) == {"eldorado", "gameboost", "playerauctions"}


# ── Eldorado payload ──────────────────────────────────────────────

class TestFh5EldoradoPayload:
    def _build(self, platform: str = "PC", kind: str = "stock") -> dict:
        pipeline = PayloadPipeline(registry=build_default_registry())
        prep = pipeline.prepare_once(_make_request(kind=kind, raw=_manual_source(platform=platform)))
        assert prep.success
        result = pipeline.build(
            prep.prepared,
            BuildContext(kind=kind, marketplace="eldorado", variant_context=fh5_eldorado()),
        )
        assert result.success, f"build failed: {result.error}"
        return result.payload

    def test_game_id_is_106(self):
        assert self._build()["augmentedGame"]["gameId"] == "106"

    def test_pc_maps_to_trade_env_0(self):
        assert self._build(platform="PC")["augmentedGame"]["tradeEnvironmentId"] == "0"

    def test_xbox_maps_to_trade_env_1(self):
        assert self._build(platform="Xbox")["augmentedGame"]["tradeEnvironmentId"] == "1"

    def test_ps5_maps_to_trade_env_2(self):
        assert self._build(platform="PS5")["augmentedGame"]["tradeEnvironmentId"] == "2"

    def test_no_attributes(self):
        payload = self._build()
        assert "offerAttributes" not in payload["augmentedGame"]

    def test_fallback_trade_env_when_no_variant_context(self):
        pipeline = PayloadPipeline(registry=build_default_registry())
        prep = pipeline.prepare_once(_make_request())
        assert prep.success
        result = pipeline.build(
            prep.prepared,
            BuildContext(kind="stock", marketplace="eldorado"),  # no variant_context
        )
        assert result.success
        assert result.payload["augmentedGame"]["tradeEnvironmentId"] == "0"

    def test_dropship_omits_credentials(self):
        assert "accountSecretDetails" not in self._build(kind="dropshipping")


# ── GameBoost payload ─────────────────────────────────────────────

class TestFh5GameBoostPayload:
    def _build(self, platform: str = "PC") -> dict:
        pipeline = PayloadPipeline(registry=build_default_registry())
        prep = pipeline.prepare_once(_make_request(raw=_manual_source(platform=platform, cars_count=200, credits_count=8_000_000)))
        assert prep.success
        result = pipeline.build(
            prep.prepared,
            BuildContext(kind="stock", marketplace="gameboost", variant_context=fh5_gameboost()),
        )
        assert result.success
        return result.payload

    def test_game_slug_is_forza_horizon_5(self):
        assert self._build()["game"] == "forza-horizon-5"

    def test_platforms_is_array(self):
        payload = self._build(platform="PC")
        assert isinstance(payload["account_data"]["platforms"], list)
        assert "PC" in payload["account_data"]["platforms"]

    def test_edition_in_account_data(self):
        assert self._build()["account_data"]["edition"] == "Standard"

    def test_cars_count_in_account_data(self):
        assert self._build()["account_data"]["cars_count"] == 200

    def test_credits_count_in_account_data(self):
        assert self._build()["account_data"]["credits_count"] == 8_000_000


# ── PlayerAuctions payload ────────────────────────────────────────

class TestFh5PlayerAuctionsPayload:
    def _build(self, platform: str = "PC") -> dict:
        pipeline = PayloadPipeline(registry=build_default_registry())
        prep = pipeline.prepare_once(_make_request(raw=_manual_source(platform=platform)))
        assert prep.success
        result = pipeline.build(
            prep.prepared,
            BuildContext(kind="stock", marketplace="playerauctions", variant_context=fh5_playerauctions()),
        )
        assert result.success
        return result.payload

    def test_game_id_is_10635(self):
        assert self._build()["gameId"] == 10635

    def test_pc_server_id_is_10636(self):
        assert self._build(platform="PC")["serverId"] == 10636

    def test_xbox_server_id_is_10637(self):
        assert self._build(platform="Xbox")["serverId"] == 10637

    def test_ps5_server_id_is_14295(self):
        assert self._build(platform="PS5")["serverId"] == 14295

    def test_fallback_server_id_when_no_variant_context(self):
        pipeline = PayloadPipeline(registry=build_default_registry())
        prep = pipeline.prepare_once(_make_request())
        assert prep.success
        result = pipeline.build(
            prep.prepared,
            BuildContext(kind="stock", marketplace="playerauctions"),
        )
        assert result.success
        assert result.payload["serverId"] == 10636  # PC fallback
