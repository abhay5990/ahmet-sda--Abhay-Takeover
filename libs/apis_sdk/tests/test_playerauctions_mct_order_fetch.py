from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import Mock

from apis_sdk.clients.marketplaces.playerauctions.client import PlayerAuctionsClient
from apis_sdk.clients.marketplaces.playerauctions.config import PlayerAuctionsConfig
from apis_sdk.clients.marketplaces.playerauctions.facade import PlayerAuctionsFacade
from apis_sdk.core.result import ApiResult


class PlayerAuctionsMctOrderFetchTests(TestCase):
    def test_order_client_uses_mct_minimal_headers_without_cookie(self):
        transport = Mock()
        transport.request.return_value = SimpleNamespace(
            is_success=True,
            status_code=200,
            headers={},
            json=lambda: {"data": {"items": [], "count": 0}},
        )
        client = PlayerAuctionsClient(PlayerAuctionsConfig(), transport)

        result = client.list_seller_orders(
            auth_headers={
                "Authorization": "Bearer relay-jwt",
                "Cookie": "stale-browser-cookie",
                "User-Agent": "relay-browser-agent",
                "origin": "https://member.playerauctions.com",
            },
            proxy_url=None,
        )

        self.assertTrue(result.ok)
        _, kwargs = transport.request.call_args
        self.assertEqual(
            kwargs["headers"],
            {
                "Accept": "application/json",
                "Authorization": "Bearer relay-jwt",
                "User-Agent": "relay-browser-agent",
            },
        )
        self.assertIsNone(kwargs["proxy_url"])

    def test_order_facade_bypasses_proxy_for_mct_compatible_reads(self):
        low_level_client = Mock()
        low_level_client.list_seller_orders.return_value = ApiResult.success([])
        facade = PlayerAuctionsFacade(low_level_client, Mock(), rate_limit_delay=0)

        calls = []

        def execute_with_retry(operation, *, proxy_group=None):
            calls.append(proxy_group)
            return operation("http://proxy-that-must-not-be-used")

        facade._exec = SimpleNamespace(
            get_auth_headers=lambda: {"Authorization": "Bearer relay-jwt"},
            execute_with_retry=execute_with_retry,
        )

        result = facade.list_seller_orders(proxy_group="playerauctions")

        self.assertTrue(result.ok)
        self.assertEqual(calls, [None])
        self.assertIsNone(low_level_client.list_seller_orders.call_args.kwargs["proxy_url"])

    def test_order_detail_facade_bypasses_proxy_for_mct_compatible_reads(self):
        low_level_client = Mock()
        low_level_client.get_order_details.return_value = ApiResult.success(Mock())
        facade = PlayerAuctionsFacade(low_level_client, Mock(), rate_limit_delay=0)

        def execute_with_retry(operation, *, proxy_group=None):
            self.assertIsNone(proxy_group)
            return operation("http://proxy-that-must-not-be-used")

        facade._exec = SimpleNamespace(
            get_auth_headers=lambda: {"Authorization": "Bearer relay-jwt"},
            execute_with_retry=execute_with_retry,
        )

        result = facade.get_order_details("123456", proxy_group="playerauctions")

        self.assertTrue(result.ok)
        self.assertIsNone(low_level_client.get_order_details.call_args.kwargs["proxy_url"])
