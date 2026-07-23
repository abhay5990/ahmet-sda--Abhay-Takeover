from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import Mock

from apis_sdk.clients.marketplaces.playerauctions.auth import PlayerAuctionsAuth


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
            data=SimpleNamespace(
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

    def test_initial_session_refresh_keeps_cache_first_behavior(self):
        auth = self.make_auth()
        auth._relay_client = Mock()
        auth._relay_client.get_token.return_value = SimpleNamespace(
            ok=True,
            data=SimpleNamespace(
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
