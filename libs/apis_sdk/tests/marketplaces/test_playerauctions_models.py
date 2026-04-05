"""
Smoke tests for PlayerAuctions SDK models against real API response samples.

These tests validate that the models correctly parse the actual response
shapes captured in _data_samples/playerauctions/response/.
"""

import json
from pathlib import Path

import pytest

from apis_sdk.clients.marketplaces.playerauctions.models import (
    PlayerAuctionsOrderListItem,
    PlayerAuctionsOrder,
    PlayerAuctionsOrderDetail,
)

PROJECT_ROOT = Path(__file__).resolve().parents[4]  # e-commerce-management-system/
SAMPLES_DIR = PROJECT_ROOT / "_data_samples" / "playerauctions"


@pytest.fixture
def orders_list_response():
    with open(SAMPLES_DIR / "response" / "orders.json", encoding="utf-8") as f:
        return json.load(f)


@pytest.fixture
def order_detail_response():
    with open(SAMPLES_DIR / "response" / "example_order.json", encoding="utf-8") as f:
        return json.load(f)


class TestPlayerAuctionsOrderListParsing:
    def test_extracts_items(self, orders_list_response):
        data_wrapper = orders_list_response.get("data", {})
        items = data_wrapper.get("items", [])
        assert len(items) == 10

    def test_extracts_count(self, orders_list_response):
        data_wrapper = orders_list_response.get("data", {})
        count = data_wrapper.get("count")
        assert count == 13133

    def test_parses_all_items(self, orders_list_response):
        items = orders_list_response["data"]["items"]
        orders = [PlayerAuctionsOrderListItem.model_validate(item) for item in items]
        assert len(orders) == 10

    def test_first_order_fields(self, orders_list_response):
        items = orders_list_response["data"]["items"]
        order = PlayerAuctionsOrderListItem.model_validate(items[0])

        assert order.order_id == 15784841
        assert "421 Skins" in order.order_title
        assert order.server_name == "Fortnite - PlayStation"
        assert order.create_time == "Mar-18-2026 10:36:48 PM"
        assert order.name == "Klipzx"
        assert order.price == "$190.00"
        assert order.product_type == "Accounts"
        assert order.quantity == "1"
        assert order.status == "Disputed Delivery Not Completed"
        assert order.is_view_details is True

    def test_pending_order_view_details_false(self, orders_list_response):
        items = orders_list_response["data"]["items"]
        order = PlayerAuctionsOrderListItem.model_validate(items[1])
        assert order.is_view_details is False
        assert order.status == "Pending Payment"

    def test_backward_compat_alias(self, orders_list_response):
        """PlayerAuctionsOrder is an alias for PlayerAuctionsOrderListItem."""
        items = orders_list_response["data"]["items"]
        order = PlayerAuctionsOrder.model_validate(items[0])
        assert isinstance(order, PlayerAuctionsOrderListItem)
        assert order.order_id == 15784841


class TestPlayerAuctionsOrderDetailParsing:
    def test_parse_detail(self, order_detail_response):
        data = order_detail_response.get("data", order_detail_response)
        detail = PlayerAuctionsOrderDetail.model_validate(data)

        assert detail.id == 15784841
        assert detail.status.current == "Disputed Delivery Not Completed"
        assert detail.status.order_status == "Disbursement Complete"
        assert detail.title != ""
        assert detail.tips is not None

    def test_order_info_preserved(self, order_detail_response):
        data = order_detail_response["data"]
        detail = PlayerAuctionsOrderDetail.model_validate(data)

        assert detail.order_info != {}
        assert detail.order_info.get("price") == "190.00"
        assert detail.order_info["user"]["name"] == "Klipzx"
        assert detail.order_info["buyerOrSeller"] == "Seller"

    def test_event_logs_preserved(self, order_detail_response):
        data = order_detail_response["data"]
        detail = PlayerAuctionsOrderDetail.model_validate(data)

        assert len(detail.event_logs) == 9
        assert detail.event_logs[0]["content"] == "Refund sent to buyer"
        assert detail.event_logs[-1]["content"] == "Order created"

    def test_disbursement_info_preserved(self, order_detail_response):
        data = order_detail_response["data"]
        detail = PlayerAuctionsOrderDetail.model_validate(data)

        assert detail.disbursement_info is not None
        assert "refunded" in detail.disbursement_info["status"].lower()

    def test_feedback_info_preserved(self, order_detail_response):
        data = order_detail_response["data"]
        detail = PlayerAuctionsOrderDetail.model_validate(data)

        assert detail.feedback_info is not None
        assert detail.feedback_info["description"] == "Feedback is not allowed for this order."

    def test_delivery_info_null(self, order_detail_response):
        data = order_detail_response["data"]
        detail = PlayerAuctionsOrderDetail.model_validate(data)
        assert detail.delivery_info is None

    def test_actions_preserved(self, order_detail_response):
        data = order_detail_response["data"]
        detail = PlayerAuctionsOrderDetail.model_validate(data)

        assert len(detail.actions) == 1
        assert detail.actions[0]["key"] == "SeeDispute"

    def test_visibility_fields(self, order_detail_response):
        data = order_detail_response["data"]
        detail = PlayerAuctionsOrderDetail.model_validate(data)

        assert detail.is_delivery_info_visible is False
        assert detail.has_message_log is True
        assert detail.view_message_url is not None

    def test_no_critical_data_loss(self, order_detail_response):
        """Verify that all top-level keys from the real response are captured."""
        data = order_detail_response["data"]
        detail = PlayerAuctionsOrderDetail.model_validate(data)

        # Dump the model back and check all original keys are represented
        original_keys = set(data.keys())
        model_dump = detail.model_dump(by_alias=True)

        # These keys should be in the model directly or in extra
        for key in original_keys:
            in_model = key in model_dump
            in_extra = key in model_dump.get("extra", {})
            assert in_model or in_extra, f"Key '{key}' lost during parsing"
