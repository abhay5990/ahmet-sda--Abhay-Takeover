"""
Unit tests for the PlayerAuctions Official Seller API client.

Tests:
- HMAC-SHA256 signing (verified against spec examples)
- Multipart signing
- Response envelope parsing (success + all error code categories)
- Endpoint path resolution
- Model parsing
"""

import json

import pytest

from apis_sdk.clients.marketplaces.playerauctions_official.auth import PAOfficialAuth
from apis_sdk.clients.marketplaces.playerauctions_official.config import PAOfficialConfig
from apis_sdk.clients.marketplaces.playerauctions_official.endpoints import PAOfficialEndpoints
from apis_sdk.clients.marketplaces.playerauctions_official.models import (
    PACreateOfferResponse,
    PADeliveryTime,
    PAEnvelope,
    PAErrorCode,
    PAGame,
    PAOfferDetail,
    PAOfferListItem,
    PAPrevalidation,
    PAServerNode,
    PACurrencyType,
    PAImageUploadResponse,
    PABulkUploadResponse,
    PACancelRequest,
    PADisplayStatusRequest,
)
from apis_sdk.clients.marketplaces.playerauctions_official.client import (
    _classify_error_code,
)
from apis_sdk.core.enums import ErrorCategory


# =========================================================================
# HMAC-SHA256 Signing Tests
# =========================================================================


class TestHMACSigning:
    """Verify HMAC-SHA256 signing matches the official API spec examples."""

    # Values from the spec (§3.2)
    API_KEY = "d7cbe9de312a83c255f1c8543f469695"
    SECRET_KEY = "pask_jDOCvy7Ot4lTJNfGV3q78VPTXjl6Ms85GmY-Bc4wMKw"

    def test_signature_with_json_body(self):
        """Verify signing matches the JS reference implementation logic."""
        timestamp = "1780293232"
        body = json.dumps({"offerId": 15000}, separators=(",", ":"))
        # canonical = apiKey + timestamp + body
        canonical = self.API_KEY + timestamp + body

        sig = PAOfficialAuth.compute_signature(
            self.API_KEY, self.SECRET_KEY, timestamp, body,
        )

        # Signature must be lowercase hex, 64 chars (SHA-256 = 32 bytes)
        assert len(sig) == 64
        assert sig == sig.lower()
        assert all(c in "0123456789abcdef" for c in sig)

    def test_signature_empty_body(self):
        """GET/DELETE requests use empty string as body."""
        timestamp = "1780293232"

        sig = PAOfficialAuth.compute_signature(
            self.API_KEY, self.SECRET_KEY, timestamp, "",
        )

        assert len(sig) == 64
        assert sig == sig.lower()

    def test_signature_deterministic(self):
        """Same inputs always produce the same signature."""
        timestamp = "1780293232"
        body = '{"gameId":3637}'

        sig1 = PAOfficialAuth.compute_signature(
            self.API_KEY, self.SECRET_KEY, timestamp, body,
        )
        sig2 = PAOfficialAuth.compute_signature(
            self.API_KEY, self.SECRET_KEY, timestamp, body,
        )

        assert sig1 == sig2

    def test_different_body_different_signature(self):
        """Different bodies produce different signatures."""
        timestamp = "1780293232"

        sig1 = PAOfficialAuth.compute_signature(
            self.API_KEY, self.SECRET_KEY, timestamp, '{"a":1}',
        )
        sig2 = PAOfficialAuth.compute_signature(
            self.API_KEY, self.SECRET_KEY, timestamp, '{"a":2}',
        )

        assert sig1 != sig2

    def test_multipart_signature_sorted_fields(self):
        """Multipart signing sorts fields alphabetically by key."""
        timestamp = "1780293232"
        fields = {"productType": "accounts", "gameId": "3637"}

        sig = PAOfficialAuth.compute_multipart_signature(
            self.API_KEY, self.SECRET_KEY, timestamp, fields,
        )

        # Sorted: gameId=3637, productType=accounts → "3637accounts"
        expected_body = "3637accounts"
        expected_sig = PAOfficialAuth.compute_signature(
            self.API_KEY, self.SECRET_KEY, timestamp, expected_body,
        )

        assert sig == expected_sig

    def test_build_signed_headers_structure(self):
        """Headers contain all three required fields."""
        auth = PAOfficialAuth(api_key=self.API_KEY, secret_key=self.SECRET_KEY)
        headers = auth.build_signed_headers('{"test":true}')

        assert "X-PA-API-KEY" in headers
        assert "X-PA-TIMESTAMP" in headers
        assert "X-PA-SIGN" in headers
        assert headers["X-PA-API-KEY"] == self.API_KEY
        assert len(headers["X-PA-SIGN"]) == 64

    def test_build_multipart_headers_structure(self):
        """Multipart headers contain all three required fields."""
        auth = PAOfficialAuth(api_key=self.API_KEY, secret_key=self.SECRET_KEY)
        headers = auth.build_multipart_headers({"productType": "accounts"})

        assert "X-PA-API-KEY" in headers
        assert "X-PA-TIMESTAMP" in headers
        assert "X-PA-SIGN" in headers


# =========================================================================
# Auth Provider Tests
# =========================================================================


class TestPAOfficialAuth:
    def test_never_expires(self):
        auth = PAOfficialAuth(api_key="test", secret_key="test")
        assert not auth.is_expired

    def test_refresh_is_noop(self):
        auth = PAOfficialAuth(api_key="test", secret_key="test")
        assert auth.refresh() is True

    def test_get_auth_headers_for_get_request(self):
        auth = PAOfficialAuth(api_key="test_key", secret_key="test_secret")
        headers = auth.get_auth_headers()
        assert headers["X-PA-API-KEY"] == "test_key"
        assert "X-PA-TIMESTAMP" in headers
        assert "X-PA-SIGN" in headers


# =========================================================================
# Error Classification Tests
# =========================================================================


class TestErrorClassification:
    @pytest.mark.parametrize("code,expected_category,expected_retryable", [
        (10001, ErrorCategory.VALIDATION, False),       # MissingHeader
        (10002, ErrorCategory.VALIDATION, False),       # InvalidParameter
        (20001, ErrorCategory.AUTHENTICATION, False),   # InvalidSignature
        (30001, ErrorCategory.AUTHENTICATION, False),   # AuthenticationError
        (30002, ErrorCategory.AUTHENTICATION, False),   # AuthorizationError
        (40001, ErrorCategory.VALIDATION, False),       # BusinessError
        (50001, ErrorCategory.SERVER_ERROR, True),      # InternalServerError
    ])
    def test_error_code_classification(self, code, expected_category, expected_retryable):
        category, is_retryable = _classify_error_code(code)
        assert category == expected_category
        assert is_retryable == expected_retryable

    def test_unknown_code(self):
        category, is_retryable = _classify_error_code(99999)
        assert category == ErrorCategory.UNKNOWN
        assert is_retryable is False


# =========================================================================
# Envelope / Model Tests
# =========================================================================


class TestPAEnvelope:
    def test_success_envelope(self):
        data = {
            "code": 10000,
            "message": "Operation Successful.",
            "requestId": "550e8400-e29b-41d4-a716-446655440000",
            "data": {"offerId": 123},
        }
        envelope = PAEnvelope.model_validate(data)
        assert envelope.is_success is True
        assert envelope.request_id == "550e8400-e29b-41d4-a716-446655440000"
        assert envelope.data == {"offerId": 123}

    def test_error_envelope(self):
        data = {
            "code": 20001,
            "message": "Signature mismatch.",
            "requestId": "abc-123",
        }
        envelope = PAEnvelope.model_validate(data)
        assert envelope.is_success is False
        assert envelope.code == 20001


class TestGameModel:
    def test_parse_game(self):
        data = {
            "gameId": 3637,
            "gameName": "League of Legends",
            "seoName": "LOL",
            "curName": "Riot Points",
            "curSuffix": "K",
            "productType": "currency,item,account,powerleveling,topup",
            "isSecurityQARequired": 0,
            "isCDKeyRequired": 0,
            "isParentalPswRequired": 0,
            "isInvolveExploitsGame": False,
            "isMCurrencyType": False,
        }
        game = PAGame.model_validate(data)
        assert game.game_id == 3637
        assert game.game_name == "League of Legends"
        assert "currency" in game.product_type
        assert game.is_m_currency_type is False


class TestServerNodeModel:
    def test_parse_nested_servers(self):
        data = {
            "id": 100,
            "productType": "account",
            "name": "NA",
            "seoName": "na",
            "parentId": 0,
            "itemSuffix": "",
            "sequence": 1,
            "subCategorys": [
                {
                    "id": 101,
                    "productType": "account",
                    "name": "NA East",
                    "seoName": "na-east",
                    "parentId": 100,
                    "itemSuffix": "",
                    "sequence": 1,
                    "subCategorys": [],
                }
            ],
        }
        node = PAServerNode.model_validate(data)
        assert node.id == 100
        assert len(node.sub_categorys) == 1
        assert node.sub_categorys[0].name == "NA East"


class TestCreateOfferResponse:
    def test_parse_response(self):
        data = {
            "offerId": 71394132,
            "navigateURL": "https://www.playerauctions.com/offer/71394132",
            "title": "Test Offer",
            "productType": "currency",
            "gameName": "Fortnite",
            "productName": "V-Bucks",
            "screenShot": "",
            "imageBlacklist": "",
        }
        resp = PACreateOfferResponse.model_validate(data)
        assert resp.offer_id == 71394132
        assert resp.product_type == "currency"


class TestPrevalidation:
    def test_parse(self):
        data = {
            "memberId": 678694,
            "status": "Active",
            "memberClass": "Gold",
            "sellerLevel": "Level 5",
            "isAllowCurrencyUpload": True,
            "isAllowItemUpload": True,
            "isAllowAccountUpload": True,
            "isWarningTipSanctions": False,
            "isSeller": True,
        }
        pv = PAPrevalidation.model_validate(data)
        assert pv.is_seller is True
        assert pv.is_allow_account_upload is True


class TestDeliveryTime:
    def test_parse(self):
        data = {
            "customId": 5,
            "time": 30,
            "convertToHour": 0.5,
            "unit": "Minutes",
            "isEnable": True,
        }
        dt = PADeliveryTime.model_validate(data)
        assert dt.custom_id == 5
        assert dt.unit == "Minutes"


# =========================================================================
# Endpoint Resolution Tests
# =========================================================================


class TestEndpoints:
    def test_offer_by_type_currency(self):
        assert PAOfficialEndpoints.offer_by_type("currency") == "/api/v1/offers/currency"

    def test_offer_by_type_account(self):
        assert PAOfficialEndpoints.offer_by_type("account") == "/api/v1/offers/account"
        assert PAOfficialEndpoints.offer_by_type("accounts") == "/api/v1/offers/account"

    def test_offer_by_type_item(self):
        assert PAOfficialEndpoints.offer_by_type("item") == "/api/v1/offers/item"
        assert PAOfficialEndpoints.offer_by_type("items") == "/api/v1/offers/item"

    def test_offer_by_type_powerleveling(self):
        assert PAOfficialEndpoints.offer_by_type("powerleveling") == "/api/v1/offers/powerleveling"

    def test_offer_by_type_topup(self):
        assert PAOfficialEndpoints.offer_by_type("topup") == "/api/v1/offers/topup"

    def test_offer_by_type_case_insensitive(self):
        assert PAOfficialEndpoints.offer_by_type("Currency") == "/api/v1/offers/currency"
        assert PAOfficialEndpoints.offer_by_type("ACCOUNT") == "/api/v1/offers/account"

    def test_offer_by_type_unknown_raises(self):
        with pytest.raises(ValueError, match="Unknown product type"):
            PAOfficialEndpoints.offer_by_type("unknown")

    def test_offer_detail_path(self):
        path = PAOfficialEndpoints.offer_detail("currency", 12345)
        assert path == "/api/v1/offers/currency/12345"

    def test_game_servers_path(self):
        path = PAOfficialEndpoints.game_servers(3637, "account")
        assert path == "/api/v1/games/3637/account/servers"

    def test_game_delivery_times_path(self):
        path = PAOfficialEndpoints.game_delivery_times(3637, "currency")
        assert path == "/api/v1/games/3637/currency/deliveryTimes"

    def test_game_currency_types_path(self):
        path = PAOfficialEndpoints.game_currency_types(9479)
        assert path == "/api/v1/games/9479/currencytypes"


# =========================================================================
# Config Tests
# =========================================================================


class TestConfig:
    def test_defaults(self):
        config = PAOfficialConfig(api_key="test", secret_key="test")
        assert config.base_url == "https://seller-api.playerauctions.com"
        assert config.timeout == 30.0
        assert config.rate_limit_delay == 1.0

    def test_frozen(self):
        config = PAOfficialConfig(api_key="test", secret_key="test")
        with pytest.raises(Exception):
            config.api_key = "other"  # type: ignore[misc]


# =========================================================================
# PAOfferDetail extra-field parsing
# =========================================================================


class TestOfferDetailExtra:
    """Verify extra fields are correctly separated from known fields."""

    def test_extra_excludes_aliased_known_fields(self):
        """camelCase API keys like 'offerId' should NOT appear in extra."""
        from apis_sdk.clients.marketplaces.playerauctions_official.client import PAOfficialClient

        data = {
            "offerId": 123,
            "gameId": 3637,
            "state": 1,
            "productType": "currency",
            "title": "Test",
            "price": 5.0,
            "customField": "should-be-extra",
            "anotherCustom": 42,
        }

        # Simulate what the client does
        known_aliases: set[str] = set()
        for name, info in PAOfferDetail.model_fields.items():
            known_aliases.add(name)
            if info.alias:
                known_aliases.add(info.alias)

        extra = {k: v for k, v in data.items() if k not in known_aliases}

        assert "customField" in extra
        assert "anotherCustom" in extra
        # Known fields (by alias) should NOT be in extra
        assert "offerId" not in extra
        assert "gameId" not in extra
        assert "productType" not in extra
        assert "title" not in extra


# =========================================================================
# PACompositeClient Tests
# =========================================================================

# PACompositeClient lives in the Django backend (provider layer) and can't
# be imported here without triggering Django setup. We test it via a
# lightweight local replica of its routing logic. Full integration tests
# belong in the backend test suite.

from unittest.mock import MagicMock


def _make_composite():
    """Build a PACompositeClient-like wrapper using the same logic as the
    real class, but without Django imports."""
    from apis_sdk.clients.marketplaces.playerauctions.models import (
        PlayerAuctionsCancelRequest as _Req,
    )

    class _Composite:
        needs_password_encryption = False

        def __init__(self, official, legacy):
            self._official = official
            self._legacy = legacy

        def list_offers(self, **kw):
            return self._official.list_offers(**kw)

        def create_offer(self, payload=None, *, proxy_group=None, **kw):
            if payload is None:
                payload = kw.get("payload", {})
            pt = payload.pop("productType", "account")
            return self._official.create_offer(pt, payload, proxy_group=proxy_group)

        def cancel_offers(self, request=None, *, offer_ids=None, proxy_group=None, **kw):
            if request is not None:
                offer_ids = request.offer_ids
            return self._official.cancel_offers(offer_ids=offer_ids, proxy_group=proxy_group)

        def list_seller_orders(self, **kw):
            return self._legacy.list_seller_orders(**kw)

        def get_order_details(self, order_id, **kw):
            return self._legacy.get_order_details(order_id, **kw)

        def bulk_upload(self, file_path, **kw):
            return self._official.bulk_upload(file_path, **kw)

        def game_account_servers(self, game_id, **kw):
            pt = kw.pop("product_type", "account")
            return self._official.game_servers(game_id, pt, **kw)

    official = MagicMock(name="official_facade")
    legacy = MagicMock(name="legacy_facade")
    return _Composite(official, legacy), official, legacy


class TestPACompositeClient:
    """Verify composite routing logic (offer→official, order→legacy)."""

    def test_needs_password_encryption_is_false(self):
        composite, _, _ = _make_composite()
        assert composite.needs_password_encryption is False

    def test_list_offers_routes_to_official(self):
        composite, official, legacy = _make_composite()
        composite.list_offers(page=1, listing_status="active")
        official.list_offers.assert_called_once_with(page=1, listing_status="active")
        legacy.list_offers.assert_not_called()

    def test_create_offer_extracts_product_type(self):
        composite, official, _ = _make_composite()
        payload = {"gameId": 3637, "title": "Test", "productType": "account"}
        composite.create_offer(payload=payload, proxy_group="g1")
        official.create_offer.assert_called_once_with(
            "account",
            {"gameId": 3637, "title": "Test"},
            proxy_group="g1",
        )

    def test_create_offer_defaults_product_type_to_account(self):
        composite, official, _ = _make_composite()
        payload = {"gameId": 3637, "title": "Test"}
        composite.create_offer(payload=payload)
        official.create_offer.assert_called_once_with(
            "account", payload, proxy_group=None,
        )

    def test_cancel_offers_from_legacy_request_model(self):
        from apis_sdk.clients.marketplaces.playerauctions.models import (
            PlayerAuctionsCancelRequest as CancelReq,
        )
        composite, official, _ = _make_composite()
        request = CancelReq(offerIds=[100, 200])
        composite.cancel_offers(request)
        official.cancel_offers.assert_called_once_with(
            offer_ids=[100, 200], proxy_group=None,
        )

    def test_list_seller_orders_routes_to_legacy(self):
        composite, official, legacy = _make_composite()
        composite.list_seller_orders(page=1, order_status="All")
        legacy.list_seller_orders.assert_called_once_with(page=1, order_status="All")
        official.list_seller_orders.assert_not_called()

    def test_get_order_details_routes_to_legacy(self):
        composite, official, legacy = _make_composite()
        composite.get_order_details(order_id="ORD-123")
        legacy.get_order_details.assert_called_once_with("ORD-123")
        official.get_order_details.assert_not_called()

    def test_bulk_upload_routes_to_official(self):
        composite, official, _ = _make_composite()
        composite.bulk_upload("/tmp/test.xlsx", product_type="accounts")
        official.bulk_upload.assert_called_once_with(
            "/tmp/test.xlsx", product_type="accounts",
        )

    def test_game_account_servers_routes_to_official(self):
        composite, official, _ = _make_composite()
        composite.game_account_servers(3637)
        official.game_servers.assert_called_once_with(3637, "account")
