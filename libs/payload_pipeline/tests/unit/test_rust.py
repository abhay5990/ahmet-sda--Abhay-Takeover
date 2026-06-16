"""Tests for the Rust account slice."""

from __future__ import annotations

import pytest

from payload_pipeline import PayloadPipeline, build_default_registry
from payload_pipeline.core.contracts import BuildContext, PipelineRequest
from payload_pipeline.games.rust.account import (
    RustComposer,
    RustEldoradoBuilder,
    RustGameBoostBuilder,
    RustPlayerAuctionsBuilder,
    RustResolver,
)
from payload_pipeline.games.rust.account.sources.manual import RustManualSourceAdapter

from _variant_ctx import rust_eldorado, rust_gameboost


# ── helpers ──────────────────────────────────────────────────────

def _manual_source(
    price: float = 30.0,
    platform: str = "PC",
    premium_status: str = "premium-no",
    hours_range: str = "hours-099",
    skins_range: str = "skins-014",
    steam_level_range: str = "level-05",
    real_hours: int = 50,
    skins_count: int = 5,
    **kwargs,
) -> dict:
    base = {
        "item_id": "rust-001",
        "price": price,
        "loginData": {"login": "rust_user@example.com", "password": "RustPass123"},
        "emailLoginData": {"login": "email@example.com", "password": "EmailPass"},
        "offer_details": {
            "platform": platform,
            "premium_status": premium_status,
            "hours_range": hours_range,
            "skins_range": skins_range,
            "steam_level_range": steam_level_range,
            "real_hours": real_hours,
            "skins_count": skins_count,
        },
    }
    base.update(kwargs)
    return base


def _make_request(kind: str = "stock", raw: dict | None = None) -> PipelineRequest:
    return PipelineRequest(
        game="rust",
        category="account",
        kind=kind,
        sources={"manual": raw or _manual_source()},
        context={"disable_media": True},
    )


# ── source adapter ────────────────────────────────────────────────

class TestRustManualSourceAdapter:
    def test_parse_returns_none_for_empty(self):
        adapter = RustManualSourceAdapter()
        assert adapter.parse(None) is None
        assert adapter.parse({}) is None

    def test_parse_extracts_platform(self):
        source = RustManualSourceAdapter().parse(_manual_source(platform="PlayStation"))
        assert source is not None
        assert source.platform == "PlayStation"

    def test_parse_extracts_attribute_ids(self):
        source = RustManualSourceAdapter().parse(_manual_source(
            premium_status="premium-yes",
            hours_range="hours-100499",
            skins_range="skins-1549",
            steam_level_range="level-624",
        ))
        assert source is not None
        assert source.premium_status == "premium-yes"
        assert source.hours_range == "hours-100499"
        assert source.skins_range == "skins-1549"
        assert source.steam_level_range == "level-624"

    def test_parse_extracts_gameboost_numerics(self):
        source = RustManualSourceAdapter().parse(_manual_source(real_hours=1200, skins_count=80))
        assert source is not None
        assert source.real_hours == 1200
        assert source.skins_count == 80

    def test_parse_extracts_credentials(self):
        source = RustManualSourceAdapter().parse(_manual_source())
        assert source is not None
        assert source.credentials.login == "rust_user@example.com"
        assert source.credentials.password == "RustPass123"

    def test_parse_defaults_applied_for_missing_fields(self):
        raw = {"item_id": "x", "price": 5.0}
        source = RustManualSourceAdapter().parse(raw)
        assert source is not None
        assert source.premium_status == "premium-no"
        assert source.hours_range == "hours-099"
        assert source.skins_range == "skins-014"
        assert source.steam_level_range == "level-05"

    def test_parse_platform_fallback_to_root(self):
        raw = {"item_id": "x", "price": 5.0, "platform": "Xbox"}
        source = RustManualSourceAdapter().parse(raw)
        assert source is not None
        assert source.platform == "Xbox"


# ── resolver ─────────────────────────────────────────────────────

class TestRustResolver:
    def test_resolve_populates_all_fields(self):
        account = RustResolver().resolve(_make_request(raw=_manual_source(
            platform="PC",
            premium_status="premium-yes",
            hours_range="hours-5001999",
            skins_range="skins-5099",
            steam_level_range="level-25",
            real_hours=800,
            skins_count=60,
        )))
        assert account.platform == "PC"
        assert account.premium_status == "premium-yes"
        assert account.hours_range == "hours-5001999"
        assert account.skins_range == "skins-5099"
        assert account.steam_level_range == "level-25"
        assert account.real_hours == 800
        assert account.skins_count == 60

    def test_resolve_stock_keeps_credentials(self):
        account = RustResolver().resolve(_make_request(kind="stock"))
        assert not account.credentials.is_empty

    def test_resolve_dropshipping_clears_credentials(self):
        account = RustResolver().resolve(_make_request(kind="dropshipping"))
        assert account.credentials.is_empty

    def test_resolve_raises_without_manual_source(self):
        request = PipelineRequest(
            game="rust", category="account", kind="stock", sources={},
        )
        with pytest.raises(Exception, match="manual"):
            RustResolver().resolve(request)


# ── registry ──────────────────────────────────────────────────────

class TestRustRegistration:
    def test_rust_in_default_registry(self):
        assert build_default_registry().has_game("rust")

    def test_rust_has_correct_marketplaces(self):
        defn = build_default_registry().get_game("rust", "account")
        assert set(defn.marketplaces.keys()) == {"eldorado", "gameboost", "playerauctions"}


# ── Eldorado payload ──────────────────────────────────────────────

class TestRustEldoradoPayload:
    def _build(
        self,
        platform: str = "PC",
        premium_status: str = "premium-no",
        hours_range: str = "hours-099",
        skins_range: str = "skins-014",
        steam_level_range: str = "level-05",
        kind: str = "stock",
    ) -> dict:
        pipeline = PayloadPipeline(registry=build_default_registry())
        prep = pipeline.prepare_once(_make_request(kind=kind, raw=_manual_source(
            platform=platform,
            premium_status=premium_status,
            hours_range=hours_range,
            skins_range=skins_range,
            steam_level_range=steam_level_range,
        )))
        assert prep.success
        result = pipeline.build(
            prep.prepared,
            BuildContext(kind=kind, marketplace="eldorado", variant_context=rust_eldorado()),
        )
        assert result.success, f"build failed: {result.error}"
        return result.payload

    def test_game_id_is_37(self):
        assert self._build()["augmentedGame"]["gameId"] == "37"

    def test_pc_maps_to_trade_env_0(self):
        assert self._build(platform="PC")["augmentedGame"]["tradeEnvironmentId"] == "0"

    def test_playstation_maps_to_trade_env_1(self):
        assert self._build(platform="PlayStation")["augmentedGame"]["tradeEnvironmentId"] == "1"

    def test_xbox_maps_to_trade_env_2(self):
        assert self._build(platform="Xbox")["augmentedGame"]["tradeEnvironmentId"] == "2"

    def test_four_attributes_present(self):
        payload = self._build(
            premium_status="premium-yes",
            hours_range="hours-100499",
            skins_range="skins-1549",
            steam_level_range="level-624",
        )
        attrs = {a["id"]: a["value"] for a in payload["augmentedGame"]["offerAttributes"]}
        assert attrs["premium-status"] == "premium-yes"
        assert attrs["rust-hours"] == "hours-100499"
        assert attrs["rust-skins"] == "skins-1549"
        assert attrs["steam-account-level"] == "level-624"

    def test_attributes_type_is_select(self):
        payload = self._build()
        for attr in payload["augmentedGame"]["offerAttributes"]:
            assert attr["type"] == "Select"

    def test_fallback_trade_env_when_no_variant_context(self):
        pipeline = PayloadPipeline(registry=build_default_registry())
        prep = pipeline.prepare_once(_make_request())
        assert prep.success
        result = pipeline.build(
            prep.prepared,
            BuildContext(kind="stock", marketplace="eldorado"),
        )
        assert result.success
        assert result.payload["augmentedGame"]["tradeEnvironmentId"] == "0"

    def test_stock_includes_credentials(self):
        payload = self._build(kind="stock")
        assert payload["accountSecretDetails"]
        assert "rust_user@example.com" in payload["accountSecretDetails"][0]

    def test_dropship_omits_credentials(self):
        assert "accountSecretDetails" not in self._build(kind="dropshipping")


# ── GameBoost payload ─────────────────────────────────────────────

class TestRustGameBoostPayload:
    def _build(self, platform: str = "PC", real_hours: int = 200, skins_count: int = 30) -> dict:
        pipeline = PayloadPipeline(registry=build_default_registry())
        prep = pipeline.prepare_once(_make_request(raw=_manual_source(
            platform=platform,
            real_hours=real_hours,
            skins_count=skins_count,
        )))
        assert prep.success
        result = pipeline.build(
            prep.prepared,
            BuildContext(kind="stock", marketplace="gameboost", variant_context=rust_gameboost()),
        )
        assert result.success, f"build failed: {result.error}"
        return result.payload

    def test_game_slug_is_rust(self):
        assert self._build()["game"] == "rust"

    def test_platform_in_account_data(self):
        payload = self._build(platform="PC")
        assert payload["account_data"]["platform"] == "PC"

    def test_playstation_platform_mapped(self):
        payload = self._build(platform="PlayStation")
        assert payload["account_data"]["platform"] == "PlayStation"

    def test_real_hours_in_account_data(self):
        assert self._build(real_hours=500)["account_data"]["real_hours_count"] == 500

    def test_skins_count_in_account_data(self):
        assert self._build(skins_count=25)["account_data"]["skins_count"] == 25

    def test_zero_hours_omitted(self):
        pipeline = PayloadPipeline(registry=build_default_registry())
        prep = pipeline.prepare_once(_make_request(raw=_manual_source(real_hours=0, skins_count=0)))
        assert prep.success
        result = pipeline.build(
            prep.prepared,
            BuildContext(kind="stock", marketplace="gameboost", variant_context=rust_gameboost()),
        )
        assert result.success
        assert "real_hours_count" not in result.payload["account_data"]
        assert "skins_count" not in result.payload["account_data"]


# ── PlayerAuctions payload ────────────────────────────────────────

class TestRustPlayerAuctionsPayload:
    def _build(self) -> dict:
        pipeline = PayloadPipeline(registry=build_default_registry())
        prep = pipeline.prepare_once(_make_request())
        assert prep.success
        result = pipeline.build(
            prep.prepared,
            BuildContext(kind="stock", marketplace="playerauctions"),
        )
        assert result.success, f"build failed: {result.error}"
        return result.payload

    def test_game_id_is_6141(self):
        assert self._build()["gameId"] == 6141

    def test_server_id_is_6142(self):
        assert self._build()["serverId"] == 6142

    def test_auto_delivery_has_credentials(self):
        assert self._build()["autoDelivery"]["loginName"] == "rust_user@example.com"

    def test_is_auto_delivery(self):
        assert self._build()["isAuto"] is True
