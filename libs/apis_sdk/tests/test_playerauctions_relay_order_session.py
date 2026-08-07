from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import Mock

from apis_sdk.clients.marketplaces.playerauctions.auth import PlayerAuctionsAuth
from apis_sdk.clients.services.pa_relay.client import PaRelayTokenResult
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
