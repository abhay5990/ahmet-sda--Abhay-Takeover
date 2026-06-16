"""Tests for the Forza Horizon 6 account slice."""

from __future__ import annotations

import pytest

from payload_pipeline import PayloadPipeline, build_default_registry
from payload_pipeline.core.contracts import BuildContext, PipelineRequest
from payload_pipeline.games.fh6.account import (
    Fh6Composer,
    Fh6EldoradoBuilder,
    Fh6Resolver,
)
from payload_pipeline.games.fh6.account.sources.manual import Fh6ManualSourceAdapter


# ── helpers ──────────────────────────────────────────────────────

def _manual_source(price: float = 18.0, **kwargs) -> dict:
    base = {
        "item_id": "fh6-001",
        "price": price,
        "loginData": {"login": "fh6_user@example.com", "password": "Fh6Pass123"},
    }
    base.update(kwargs)
    return base


def _make_request(kind: str = "stock", raw: dict | None = None) -> PipelineRequest:
    return PipelineRequest(
        game="forza-horizon-6",
        category="account",
        kind=kind,
        sources={"manual": raw or _manual_source()},
        context={"disable_media": True},
    )


# ── source adapter ────────────────────────────────────────────────

class TestFh6ManualSourceAdapter:
    def test_parse_returns_none_for_empty(self):
        adapter = Fh6ManualSourceAdapter()
        assert adapter.parse(None) is None
        assert adapter.parse({}) is None

    def test_parse_extracts_base_fields(self):
        source = Fh6ManualSourceAdapter().parse(_manual_source(price=22.0))
        assert source is not None
        assert source.price == 22.0
        assert source.item_id == "fh6-001"

    def test_parse_extracts_credentials(self):
        source = Fh6ManualSourceAdapter().parse(_manual_source())
        assert source is not None
        assert source.credentials.login == "fh6_user@example.com"

    def test_parse_handles_nested_item_envelope(self):
        raw = {"item": _manual_source(price=11.0)}
        source = Fh6ManualSourceAdapter().parse(raw)
        assert source is not None
        assert source.price == 11.0


# ── resolver ─────────────────────────────────────────────────────

class TestFh6Resolver:
    def test_resolve_stock_populates_credentials(self):
        account = Fh6Resolver().resolve(_make_request(kind="stock"))
        assert not account.credentials.is_empty
        assert account.credentials.login == "fh6_user@example.com"

    def test_resolve_dropshipping_clears_credentials(self):
        account = Fh6Resolver().resolve(_make_request(kind="dropshipping"))
        assert account.credentials.is_empty

    def test_resolve_raises_without_manual_source(self):
        request = PipelineRequest(
            game="forza-horizon-6", category="account", kind="stock", sources={},
        )
        with pytest.raises(Exception, match="manual"):
            Fh6Resolver().resolve(request)


# ── registry ──────────────────────────────────────────────────────

class TestFh6Registration:
    def test_fh6_in_default_registry(self):
        assert build_default_registry().has_game("forza-horizon-6")

    def test_fh6_has_only_eldorado(self):
        defn = build_default_registry().get_game("forza-horizon-6", "account")
        assert set(defn.marketplaces.keys()) == {"eldorado"}


# ── Eldorado payload ──────────────────────────────────────────────

class TestFh6EldoradoPayload:
    def _build(self, kind: str = "stock") -> dict:
        pipeline = PayloadPipeline(registry=build_default_registry())
        prep = pipeline.prepare_once(_make_request(kind=kind))
        assert prep.success
        result = pipeline.build(prep.prepared, BuildContext(kind=kind, marketplace="eldorado"))
        assert result.success, f"build failed: {result.error}"
        return result.payload

    def test_game_id_is_414(self):
        assert self._build()["augmentedGame"]["gameId"] == "414"

    def test_category_is_account(self):
        assert self._build()["augmentedGame"]["category"] == "Account"

    def test_no_trade_environment(self):
        assert self._build()["augmentedGame"]["tradeEnvironmentId"] is None

    def test_no_attributes(self):
        assert "offerAttributes" not in self._build()["augmentedGame"]

    def test_stock_includes_credentials(self):
        payload = self._build(kind="stock")
        assert payload["accountSecretDetails"]
        assert "fh6_user@example.com" in payload["accountSecretDetails"][0]

    def test_dropship_omits_credentials(self):
        assert "accountSecretDetails" not in self._build(kind="dropshipping")

    def test_price_set_correctly(self):
        assert self._build()["details"]["pricing"]["pricePerUnit"]["amount"] == 18.0
