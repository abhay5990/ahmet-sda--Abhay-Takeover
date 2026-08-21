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

    def test_unauthorized_relay_post_retries_once_with_forced_fresh_session(self):
        calls = []

        class _Poster:
            def __init__(self, **kwargs):
                pass

            def post_batch(self, token, store_slug, payloads, *, cookie):
                calls.append((token, store_slug, payloads, cookie))
                if token == 'stale-token':
                    return SimpleNamespace(successful={}, failed={0: 'Unauthorized'})
                return SimpleNamespace(successful={0: '294600002'}, failed={})

        store = SimpleNamespace(
            credential=SimpleNamespace(credentials={
                'access_token': 'stale-token',
                'cookie': 'stale-cookie',
                'username': 'user',
                'password': 'pass',
                'store_slug': 'ezsmurfmart',
                'relay_url': 'http://relay',
                'relay_secret': 'secret',
            }),
        )
        payload = {'gameId': 5917, 'serverId': 5921, 'title': 'GTA #ABC123'}

        with patch.object(offer_editor, 'PARelayPoster', _Poster), patch.object(
            offer_editor,
            'fetch_relay_token',
            return_value=('fresh-token', 'fresh-cookie'),
        ) as fetch_token:
            result = offer_editor._post_pa_relay_payloads(
                store,
                [payload],
                session=('stale-token', 'stale-cookie', 'ezsmurfmart', 'http://relay', 'secret'),
            )

        self.assertEqual(result.successful, {0: '294600002'})
        self.assertEqual(result.failed, {})
        self.assertEqual([call[0] for call in calls], ['stale-token', 'fresh-token'])
        self.assertTrue(fetch_token.call_args.kwargs['force_refresh'])

    def test_pa_edit_lock_uses_only_the_marketplace_lane(self):
        lane = SimpleNamespace(
            status='active',
            last_error='',
            save=lambda **kwargs: None,
        )
        context = SimpleNamespace(pool_offer=lane)

        previous = offer_editor._begin_pa_pool_edit_lock(context)

        self.assertEqual(previous, ('active', ''))
        self.assertEqual(lane.status, 'error')
        self.assertIn('Automatic replenishment', lane.last_error)

        offer_editor._finish_pa_pool_edit_lock(context, previous)

        self.assertEqual(lane.status, 'active')
        self.assertEqual(lane.last_error, '')

    def test_selective_relist_rejects_non_pushed_pool_items_before_marketplace_call(self):
        item = SimpleNamespace(
            status='pending',
            pool_offer_id=193,
            pool_offer=SimpleNamespace(marketplace='playerauctions'),
        )

        result = offer_editor.relist_pa_pool_item(item)

        self.assertFalse(result.ok)
        self.assertIn('Only a pushed PlayerAuctions account', result.error)

    def test_bump_reuses_the_existing_unique_code_without_a_price_change(self):
        listing = SimpleNamespace(title='GTA V full access #XCZY3P')
        item = SimpleNamespace(owned_product=SimpleNamespace(ref_key=''))

        code, title = offer_editor._bump_title_with_existing_tracking_code(listing, item)

        self.assertEqual(code, '#XCZY3P')
        self.assertEqual(title, 'GTA V full access #XCZY3P')
