"""Tests for the PSN account slice."""

from __future__ import annotations

import pytest

from payload_pipeline import PayloadPipeline, build_default_registry
from payload_pipeline.core.contracts import BuildContext, PipelineRequest
from payload_pipeline.games.psn.account import (
    PsnComposer,
    PsnEldoradoBuilder,
    PsnPlayerAuctionsBuilder,
    PsnResolver,
)
from payload_pipeline.games.psn.account.sources.manual import PsnManualSourceAdapter


# ── helpers ──────────────────────────────────────────────────────

def _manual_source(price: float = 15.0, **kwargs) -> dict:
    base = {
        "item_id": "psn-001",
        "price": price,
        "loginData": {"login": "psn_user@example.com", "password": "PsnPass123"},
        "emailLoginData": {"login": "email@example.com", "password": "EmailPass"},
    }
    base.update(kwargs)
    return base


def _make_request(kind: str = "stock", raw: dict | None = None) -> PipelineRequest:
    return PipelineRequest(
        game="playstation",
        category="account",
        kind=kind,
        sources={"manual": raw or _manual_source()},
        context={"disable_media": True},
    )


# ── source adapter ────────────────────────────────────────────────

class TestPsnManualSourceAdapter:
    def test_parse_returns_none_for_empty(self):
        adapter = PsnManualSourceAdapter()
        assert adapter.parse(None) is None
        assert adapter.parse({}) is None

    def test_parse_extracts_price(self):
        source = PsnManualSourceAdapter().parse(_manual_source(price=25.0))
        assert source is not None
        assert source.price == 25.0

    def test_parse_extracts_credentials(self):
        source = PsnManualSourceAdapter().parse(_manual_source())
        assert source is not None
        assert source.credentials.login == "psn_user@example.com"
        assert source.credentials.password == "PsnPass123"
        assert source.credentials.email_login == "email@example.com"
        assert source.credentials.email_password == "EmailPass"

    def test_parse_extracts_item_id(self):
        source = PsnManualSourceAdapter().parse(_manual_source())
        assert source is not None
        assert source.item_id == "psn-001"

    def test_parse_handles_nested_item_envelope(self):
        raw = {"item": _manual_source(price=9.99)}
        source = PsnManualSourceAdapter().parse(raw)
        assert source is not None
        assert source.price == 9.99


# ── resolver ─────────────────────────────────────────────────────

class TestPsnResolver:
    def test_resolve_stock_populates_credentials(self):
        request = _make_request(kind="stock")
        account = PsnResolver().resolve(request)

        assert account.price == 15.0
        assert not account.credentials.is_empty
        assert account.credentials.login == "psn_user@example.com"

    def test_resolve_dropshipping_clears_credentials(self):
        request = _make_request(kind="dropshipping")
        account = PsnResolver().resolve(request)
        assert account.credentials.is_empty

    def test_resolve_raises_without_manual_source(self):
        request = PipelineRequest(
            game="playstation", category="account", kind="stock", sources={},
        )
        with pytest.raises(Exception, match="manual"):
            PsnResolver().resolve(request)


# ── registry ──────────────────────────────────────────────────────

class TestPsnRegistration:
    def test_psn_in_default_registry(self):
        registry = build_default_registry()
        assert registry.has_game("playstation")

    def test_psn_has_correct_marketplaces(self):
        registry = build_default_registry()
        defn = registry.get_game("playstation", "account")
        assert set(defn.marketplaces.keys()) == {"eldorado", "playerauctions"}


# ── payload shapes ────────────────────────────────────────────────

class TestPsnEldoradoPayload:
    def _build(self, kind: str = "stock") -> dict:
        pipeline = PayloadPipeline(registry=build_default_registry())
        request = _make_request(kind=kind)
        prep = pipeline.prepare_once(request)
        assert prep.success, f"prepare_once failed: {prep.error}"
        result = pipeline.build(prep.prepared, BuildContext(kind=kind, marketplace="eldorado"))
        assert result.success, f"build failed: {result.error}"
        return result.payload

    def test_game_id_is_104(self):
        payload = self._build()
        assert payload["augmentedGame"]["gameId"] == "104"

    def test_category_is_account(self):
        payload = self._build()
        assert payload["augmentedGame"]["category"] == "Account"

    def test_no_trade_environment(self):
        payload = self._build()
        assert payload["augmentedGame"]["tradeEnvironmentId"] is None

    def test_stock_includes_credentials(self):
        payload = self._build(kind="stock")
        assert payload["accountSecretDetails"]
        assert "psn_user@example.com" in payload["accountSecretDetails"][0]

    def test_dropship_omits_credentials(self):
        payload = self._build(kind="dropshipping")
        assert "accountSecretDetails" not in payload

    def test_price_is_set(self):
        payload = self._build()
        assert payload["details"]["pricing"]["pricePerUnit"]["amount"] == 15.0


class TestPsnPlayerAuctionsPayload:
    def _build(self) -> dict:
        pipeline = PayloadPipeline(registry=build_default_registry())
        request = _make_request()
        prep = pipeline.prepare_once(request)
        assert prep.success
        result = pipeline.build(prep.prepared, BuildContext(kind="stock", marketplace="playerauctions"))
        assert result.success, f"build failed: {result.error}"
        return result.payload

    def test_game_id_is_4880(self):
        payload = self._build()
        assert payload["gameId"] == 4880

    def test_server_id_is_6370(self):
        payload = self._build()
        assert payload["serverId"] == 6370

    def test_auto_delivery_has_credentials(self):
        payload = self._build()
        assert payload["autoDelivery"]["loginName"] == "psn_user@example.com"

    def test_is_auto_delivery(self):
        payload = self._build()
        assert payload["isAuto"] is True
