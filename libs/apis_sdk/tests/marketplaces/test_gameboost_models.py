"""
Smoke tests for GameBoost SDK models against real API response samples.

These tests validate that the models correctly parse the actual response
shapes captured in _data_samples/gameboost/response/.
"""

import json
from pathlib import Path

import pytest

from apis_sdk.clients.marketplaces.gameboost.models import (
    GameBoostOrder,
    GameBoostPaginationMeta,
)
from apis_sdk.clients.marketplaces.gameboost.mapper import GameBoostMapper

PROJECT_ROOT = Path(__file__).resolve().parents[4]  # e-commerce-management-system/
SAMPLES_DIR = PROJECT_ROOT / "_data_samples" / "gameboost"


@pytest.fixture
def orders_list_response():
    with open(SAMPLES_DIR / "response" / "orders.json", encoding="utf-8") as f:
        return json.load(f)


@pytest.fixture
def order_detail_response():
    with open(SAMPLES_DIR / "response" / "example_order_new.json", encoding="utf-8") as f:
        return json.load(f)


@pytest.fixture
def currency_order_response():
    with open(SAMPLES_DIR / "gameboost_currency_order.json", encoding="utf-8") as f:
        return json.load(f)


class TestGameBoostOrderListParsing:
    def test_extracts_data_list(self, orders_list_response):
        items = GameBoostMapper.extract_list_data(orders_list_response)
        assert len(items) > 0

    def test_parses_all_orders(self, orders_list_response):
        items = GameBoostMapper.extract_list_data(orders_list_response)
        orders = [GameBoostOrder.model_validate(item) for item in items]
        assert len(orders) == len(items)

    def test_first_order_fields(self, orders_list_response):
        items = GameBoostMapper.extract_list_data(orders_list_response)
        order = GameBoostOrder.model_validate(items[0])

        assert order.id == 2637001
        assert order.account_offer_id == 3810453
        assert order.game.name == "Fortnite"
        assert order.game.slug == "fortnite"
        assert order.buyer.username == "98*****ty"
        assert order.status == "refunded"
        assert order.title != ""
        assert order.description != ""
        assert isinstance(order.parameters, dict)
        assert order.parameters.get("platform") == "PC"
        assert order.delivery_time.format == "Instant"
        assert order.is_manual_delivery is False
        assert isinstance(order.credentials, str)
        assert order.delivery_instructions != ""
        assert order.price is not None
        assert order.price.value > 0
        assert order.price.currency.code == "EUR"
        assert order.price_usd is not None
        assert order.price_usd.currency.code == "USD"
        assert len(order.image_urls) > 0
        assert order.created_at is not None
        assert order.updated_at is not None


class TestGameBoostOrderDetailParsing:
    def test_parse_detail(self, order_detail_response):
        data = order_detail_response.get("data", order_detail_response)
        order = GameBoostOrder.model_validate(data)

        assert order.id == 2639072
        assert order.account_offer_id == 4317740
        assert order.status == "in_delivery"
        assert order.game.name == "Fortnite"
        assert order.buyer.id == 1030831
        assert order.price is not None
        assert order.price.format == "€5,99"
        assert order.price.value == 5.99
        assert order.price_usd is not None
        assert order.price_usd.value == 6.92
        assert isinstance(order.credentials, str)
        assert len(order.image_urls) == 4
        assert order.purchased_at == 1774514097
        assert order.completed_at is None


class TestGameBoostCurrencyOrderParsing:
    def test_parse_currency_order(self, currency_order_response):
        order = GameBoostOrder.model_validate(currency_order_response)

        assert order.id == 195436
        assert order.currency_offer_id == 19876
        assert order.account_offer_id is None
        assert order.game.name == "Roblox"
        assert order.status == "delivered"
        assert order.quantity == 1000
        assert order.currency_unit is not None
        assert order.currency_unit.name == "Robux"
        assert order.currency_unit.symbol == "R$"
        # Currency orders use price_eur instead of price
        assert order.price is None  # account-order field not present
        # Credentials is a dict for currency orders
        assert isinstance(order.credentials, dict)
        assert order.credentials.get("username") == "DClac"


class TestGameBoostPaginationMeta:
    def test_extract_pagination(self, orders_list_response):
        meta = GameBoostMapper.extract_pagination_meta(orders_list_response)
        assert meta is not None
        assert meta.current_page == 1
        assert meta.last_page == 932
        assert meta.per_page == 15
        assert meta.total == 13966
        assert meta.from_ == 1
        assert meta.to == 15
        assert meta.has_next is True
        assert meta.has_prev is False
        assert meta.total_pages == 932

    def test_no_pagination_returns_none(self):
        result = GameBoostMapper.extract_pagination_meta({"data": []})
        assert result is None
