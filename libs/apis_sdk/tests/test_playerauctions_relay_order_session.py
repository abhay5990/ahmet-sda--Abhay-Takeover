from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import Mock

from apis_sdk.clients.marketplaces.playerauctions.auth import PlayerAuctionsAuth
from apis_sdk.clients.services.pa_relay.client import PaRelayClient, PaRelayTokenResult
from apis_sdk.clients.services.pa_relay.config import PaRelayConfig
from apis_sdk.core.enums import ErrorCategory
from apis_sdk.core.result import ApiResult


class PlayerAuctionsRelayOrderSessionTests(TestCase):
    def test_order_preflight_uses_cache_first_shared_relay_session(self):
        auth = PlayerAuctionsAuth(
            transport=Mock(),
            username='seller@example.test',
            password='secret',
            store_slug='ezsmurfmart',
        )
        auth._relay_client = Mock()
        auth._relay_client.get_token.return_value = ApiResult.success(
            PaRelayTokenResult(
                access_token='relay-jwt',
                cached=True,
                cookie='browser-cookie',
                user_agent='relay-agent',
            )
        )

        self.assertTrue(auth.refresh_relay_session())
        auth._relay_client.get_token.assert_called_once_with(
            username='seller@example.test',
            password='secret',
            store='ezsmurfmart',
            force_refresh=False,
        )
        self.assertEqual(auth.access_token, 'relay-jwt')
        self.assertEqual(auth.cookie, 'browser-cookie')
        self.assertEqual(auth.user_agent, 'relay-agent')

    def test_browser_edit_forwards_title_description_and_price_to_relay(self):
        auth = PlayerAuctionsAuth(
            transport=Mock(),
            username='seller@example.test',
            password='secret',
            store_slug='ezsmurfmart',
        )
        auth._relay_client = Mock()
        auth._relay_client.edit_offer_in_browser.return_value = ApiResult.success({})

        auth.edit_offer_in_browser(
            offer_id=295390832,
            login_name='account-login',
            account_password='account-password',
            title='Updated title',
            description='Updated description',
            price='248.50',
        )

        auth._relay_client.edit_offer_in_browser.assert_called_once_with(
            username='seller@example.test',
            password='secret',
            store='ezsmurfmart',
            offer_id=295390832,
            login_name='account-login',
            account_password='account-password',
            title='Updated title',
            description='Updated description',
            price='248.50',
        )

    def test_mart_order_read_uses_no_sda_credential_or_token_handoff(self):
        transport = Mock()
        transport.request.return_value = SimpleNamespace(
            is_success=True,
            status_code=200,
            json=lambda: {
                'ok': True,
                'data': {'items': [{'orderId': 12345, 'status': 'Delivery Fully Completed'}], 'count': 1},
            },
        )
        relay = PaRelayClient(PaRelayConfig(base_url='http://relay.test:3001'), transport)

        result = relay.list_seller_orders_in_existing_browser(
            store='ezsmurfmart',
            page=2,
            page_size=50,
        )

        self.assertTrue(result.ok)
        _, kwargs = transport.request.call_args
        self.assertEqual(kwargs['json_body'], {
            'store': 'ezsmurfmart',
            'existingBrowserOnly': True,
            'pageIndex': 2,
            'pageSize': 50,
        })
        self.assertNotIn('username', kwargs['json_body'])
        self.assertNotIn('password', kwargs['json_body'])
        self.assertNotIn('accessToken', kwargs['json_body'])

    def test_held_mart_order_read_returns_safe_unavailable_state(self):
        transport = Mock()
        transport.request.return_value = SimpleNamespace(
            is_success=False,
            status_code=423,
            json=lambda: {'ok': False, 'errorCode': 'relay_store_hold'},
        )
        relay = PaRelayClient(PaRelayConfig(base_url='http://relay.test:3001'), transport)

        result = relay.list_seller_orders_in_existing_browser(store='ezsmurfmart')

        self.assertFalse(result.ok)
        self.assertEqual(result.error.category, ErrorCategory.AUTHENTICATION)
        self.assertEqual(
            result.error.message,
            'Mart unavailable: relay authentication hold is active; order fetch was not attempted.',
        )

    def test_mart_auth_reads_orders_without_token_refresh(self):
        auth = PlayerAuctionsAuth(
            transport=Mock(),
            username='seller@example.test',
            password='secret',
            store_slug='ezsmurfmart',
        )
        auth._relay_client = Mock()
        auth._relay_client.list_seller_orders_in_existing_browser.return_value = ApiResult.success({
            'items': [{'orderId': 12345, 'status': 'Delivery Fully Completed'}],
            'count': 1,
        })

        result = auth.list_seller_orders_in_existing_browser()

        self.assertTrue(result.ok)
        self.assertEqual(result.data[0].order_id, 12345)
        self.assertEqual(result.meta['total_count'], 1)
        auth._relay_client.get_token.assert_not_called()
