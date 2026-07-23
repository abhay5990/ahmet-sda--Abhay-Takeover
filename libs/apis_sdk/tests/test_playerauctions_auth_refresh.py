from types import SimpleNamespace
import time
from unittest import TestCase
from unittest.mock import Mock

from apis_sdk.clients.marketplaces.playerauctions.auth import PlayerAuctionsAuth
from apis_sdk.clients.marketplaces.playerauctions.facade import PlayerAuctionsFacade
from apis_sdk.clients.marketplaces.playerauctions.models import PlayerAuctionsCancelRequest
from apis_sdk.core.result import ApiResult
from apis_sdk.infrastructure.logging.logger import StdlibLogger
from apis_sdk.clients.services.pa_relay.client import PaRelayTokenResult


class PlayerAuctionsAuthRefreshTests(TestCase):
    def make_auth(self):
        return PlayerAuctionsAuth(
            transport=Mock(),
            username='seller@example.com',
            password='secret',
            access_token='old-token',
            cookie='old-cookie',
            store_slug='vapenation',
        )

    def test_retry_refresh_forces_a_fresh_relay_session(self):
        auth = self.make_auth()
        auth._relay_client = Mock()
        auth._relay_client.get_token.return_value = SimpleNamespace(
            ok=True,
            data=PaRelayTokenResult(
                access_token='fresh-token',
                cookie='fresh-cookie',
                user_agent='fresh-agent',
                cached=False,
            ),
        )

        self.assertTrue(auth.refresh())

        auth._relay_client.get_token.assert_called_once_with(
            username='seller@example.com',
            password='secret',
            store='vapenation',
            force_refresh=True,
        )
        self.assertEqual(auth.access_token, 'fresh-token')
        self.assertEqual(auth.cookie, 'fresh-cookie')
        self.assertEqual(auth.user_agent, 'fresh-agent')

    def test_cooldown_log_uses_the_sdk_logger_interface(self):
        auth = PlayerAuctionsAuth(
            transport=Mock(),
            username='seller@example.com',
            password='secret',
            access_token='old-token',
            cookie='old-cookie',
            store_slug='vapenation',
            logger=StdlibLogger('test.playerauctions.cooldown'),
        )
        auth._relay_client = Mock()
        auth._transient_backoff_until = time.monotonic() + 60

        self.assertFalse(auth._do_refresh())
        auth._relay_client.get_token.assert_not_called()

    def test_browser_cancellation_uses_store_scoped_relay_session(self):
        auth = self.make_auth()
        auth._relay_client = Mock()
        expected = ApiResult.success({'ok': True, 'offerIds': [12345]})
        auth._relay_client.cancel_offers_in_browser.return_value = expected

        result = auth.cancel_offers_in_browser([12345])

        self.assertIs(result, expected)
        auth._relay_client.cancel_offers_in_browser.assert_called_once_with(
            username='seller@example.com',
            password='secret',
            store='vapenation',
            offer_ids=[12345],
        )

    def test_legacy_facade_cancellation_prefers_browser_relay(self):
        auth = Mock()
        expected = ApiResult.success({'ok': True, 'offerIds': [12345]})
        auth.cancel_offers_in_browser.return_value = expected
        client = Mock()
        facade = PlayerAuctionsFacade(client=client, auth=auth)

        result = facade.cancel_offers(PlayerAuctionsCancelRequest(offerIds=[12345]))

        self.assertIs(result, expected)
        auth.cancel_offers_in_browser.assert_called_once_with([12345])
        client.cancel_offers.assert_not_called()

    def test_initial_session_refresh_keeps_cache_first_behavior(self):
        auth = self.make_auth()
        auth._relay_client = Mock()
        auth._relay_client.get_token.return_value = SimpleNamespace(
            ok=True,
            data=PaRelayTokenResult(
                access_token='cached-token',
                cookie='cached-cookie',
                user_agent='cached-agent',
                cached=True,
            ),
        )

        self.assertTrue(auth._do_refresh())

        auth._relay_client.get_token.assert_called_once_with(
            username='seller@example.com',
            password='secret',
            store='vapenation',
            force_refresh=False,
        )
