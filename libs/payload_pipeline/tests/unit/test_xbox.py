"""Tests for the Xbox account slice."""

from __future__ import annotations

import pytest

from payload_pipeline import PayloadPipeline, build_default_registry
from payload_pipeline.core.contracts import BuildContext, PipelineRequest
from payload_pipeline.games.xbox.account import (
    XboxComposer,
    XboxEldoradoBuilder,
    XboxPlayerAuctionsBuilder,
    XboxResolver,
)
from payload_pipeline.games.xbox.account.sources.manual import XboxManualSourceAdapter


# ── helpers ──────────────────────────────────────────────────────

def _manual_source(price: float = 12.0, **kwargs) -> dict:
    base = {
        "item_id": "xbox-001",
        "price": price,
        "loginData": {"login": "xbox_user@example.com", "password": "XboxPass123"},
        "emailLoginData": {"login": "email@example.com", "password": "EmailPass"},
    }
    base.update(kwargs)
    return base


def _make_request(kind: str = "stock", raw: dict | None = None) -> PipelineRequest:
    return PipelineRequest(
        game="xbox",
        category="account",
        kind=kind,
        sources={"manual": raw or _manual_source()},
        context={"disable_media": True},
    )


# ── source adapter ────────────────────────────────────────────────

class TestXboxManualSourceAdapter:
    def test_parse_returns_none_for_empty(self):
        adapter = XboxManualSourceAdapter()
        assert adapter.parse(None) is None
        assert adapter.parse({}) is None

    def test_parse_extracts_price_and_credentials(self):
        source = XboxManualSourceAdapter().parse(_manual_source(price=18.0))
        assert source is not None
        assert source.price == 18.0
        assert source.credentials.login == "xbox_user@example.com"
        assert source.credentials.password == "XboxPass123"

    def test_parse_handles_nested_item_envelope(self):
        raw = {"item": _manual_source(price=7.5)}
        source = XboxManualSourceAdapter().parse(raw)
        assert source is not None
        assert source.price == 7.5


# ── resolver ─────────────────────────────────────────────────────

class TestXboxResolver:
    def test_resolve_stock_populates_credentials(self):
        account = XboxResolver().resolve(_make_request(kind="stock"))
        assert not account.credentials.is_empty
        assert account.credentials.login == "xbox_user@example.com"

    def test_resolve_dropshipping_clears_credentials(self):
        account = XboxResolver().resolve(_make_request(kind="dropshipping"))
        assert account.credentials.is_empty

    def test_resolve_raises_without_manual_source(self):
        request = PipelineRequest(
            game="xbox", category="account", kind="stock", sources={},
        )
        with pytest.raises(Exception, match="manual"):
            XboxResolver().resolve(request)


# ── registry ──────────────────────────────────────────────────────

class TestXboxRegistration:
    def test_xbox_in_default_registry(self):
        assert build_default_registry().has_game("xbox")

    def test_xbox_has_correct_marketplaces(self):
        defn = build_default_registry().get_game("xbox", "account")
        assert set(defn.marketplaces.keys()) == {"eldorado", "playerauctions"}


# ── payload shapes ────────────────────────────────────────────────

class TestXboxEldoradoPayload:
    def _build(self, kind: str = "stock") -> dict:
        pipeline = PayloadPipeline(registry=build_default_registry())
        prep = pipeline.prepare_once(_make_request(kind=kind))
        assert prep.success
        result = pipeline.build(prep.prepared, BuildContext(kind=kind, marketplace="eldorado"))
        assert result.success
        return result.payload

    def test_game_id_is_103(self):
        assert self._build()["augmentedGame"]["gameId"] == "103"

    def test_no_trade_environment(self):
        assert self._build()["augmentedGame"]["tradeEnvironmentId"] is None

    def test_stock_includes_credentials(self):
        payload = self._build(kind="stock")
        assert payload["accountSecretDetails"]
        assert "xbox_user@example.com" in payload["accountSecretDetails"][0]

    def test_dropship_omits_credentials(self):
        assert "accountSecretDetails" not in self._build(kind="dropshipping")


class TestXboxPlayerAuctionsPayload:
    def _build(self) -> dict:
        pipeline = PayloadPipeline(registry=build_default_registry())
        prep = pipeline.prepare_once(_make_request())
        assert prep.success
        result = pipeline.build(prep.prepared, BuildContext(kind="stock", marketplace="playerauctions"))
        assert result.success
        return result.payload

    def test_game_id_is_4876(self):
        assert self._build()["gameId"] == 4876

    def test_server_id_is_4877(self):
        assert self._build()["serverId"] == 4877

    def test_auto_delivery_has_credentials(self):
        assert self._build()["autoDelivery"]["loginName"] == "xbox_user@example.com"
