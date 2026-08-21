from types import SimpleNamespace
from unittest.mock import patch

from django.test import SimpleTestCase

from apps.posting.services import offer_editor


class PlayerAuctionsPoolEditRelayPayloadTests(SimpleTestCase):
    def test_relay_edit_payload_preserves_numeric_game_and_server_metadata(self):
        captured = {}

        class _Poster:
            def __init__(self, **kwargs):
                captured['poster_kwargs'] = kwargs

            def post_batch(self, token, store_slug, payloads, *, cookie):
                captured.update({
                    'token': token,
                    'store_slug': store_slug,
                    'payloads': payloads,
                    'cookie': cookie,
                })
                return SimpleNamespace(successful={0: '294600001'}, failed={})

        store = SimpleNamespace(
            credential=SimpleNamespace(credentials={
                'access_token': 'token',
                'cookie': 'cookie',
                'store_slug': 'csgosmurfkings',
                'relay_url': 'http://relay',
                'relay_secret': 'secret',
            }),
        )
        payload = {
            'gameId': 5917,
            'serverId': 5921,
            'categoryId': 5921,
            'title': 'GTA V account #ABC123',
            'price': 32.89,
        }

        with patch.object(offer_editor, 'PARelayPoster', _Poster):
            result = offer_editor._post_pa_relay_payloads(store, [payload])

        self.assertEqual(result.successful, {0: '294600001'})
        self.assertEqual(captured['payloads'][0]['gameId'], 5917)
        self.assertEqual(captured['payloads'][0]['serverId'], 5921)
        self.assertNotIn('Game', captured['payloads'][0])

    def test_bulk_edit_session_preflight_prevents_cancel_when_token_is_unavailable(self):
        store = SimpleNamespace(
            credential=SimpleNamespace(credentials={
                'store_slug': 'csgosmurfkings',
            }),
        )

        self.assertIsNone(offer_editor._resolve_pa_relay_session(store))

    def test_selective_relist_rejects_non_pushed_pool_items_before_marketplace_call(self):
        item = SimpleNamespace(
            status='pending',
            pool_offer_id=193,
            pool_offer=SimpleNamespace(marketplace='playerauctions'),
        )

        result = offer_editor.relist_pa_pool_item(item)

        self.assertFalse(result.ok)
        self.assertIn('Only a pushed PlayerAuctions account', result.error)
