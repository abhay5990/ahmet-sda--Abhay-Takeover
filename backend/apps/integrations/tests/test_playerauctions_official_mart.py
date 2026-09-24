from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import Mock

from django.test import SimpleTestCase

from apps.integrations.providers.playerauctions import (
    PACompositeClient,
    PlayerAuctionsProvider,
    _normalize_official_account_payload,
)


class PlayerAuctionsOfficialMartTests(SimpleTestCase):
    def _payload(self) -> dict:
        return {
            'gameId': 9078,
            'serverId': 9309,
            'categoryId': 9309,
            'price': 20,
            'freeInsurance': 7,
            'offerDuration': 30,
            'title': 'Safe account offer',
            'offerDesc': 'Safe description',
            'screenShot': '',
            'isAuto': True,
            'autoDelivery': {
                'loginName': 'safe-login',
                'password': 'safe-password',
                'isInfoSame': True,
                'choose5': True,
                'original': {
                    'firstName': 'Jane', 'lastName': 'Doe', 'phone': '5555555555',
                    'email': 'owner@example.com', 'city': 'Austin', 'country': 'United States',
                },
                'current': {
                    'phone': '5555555555', 'email': 'owner@example.com',
                    'city': 'Austin', 'country': 'United States',
                },
            },
        }

    def test_normalizer_creates_documented_official_account_shape(self):
        normalized = _normalize_official_account_payload(self._payload(), None)

        self.assertIsNotNone(normalized)
        assert normalized is not None
        self.assertNotIn('offerId', normalized)
        self.assertEqual(normalized['selleraftersaleprotection'], 7)
        self.assertTrue(normalized['agreeCheck'])
        self.assertEqual(normalized['autoDelivery']['retypeLoginName'], 'safe-login')
        self.assertEqual(normalized['autoDelivery']['retypePassword'], 'safe-password')
        self.assertNotIn('freeInsurance', normalized)

    def test_normalizer_adds_offer_id_only_for_edit(self):
        normalized = _normalize_official_account_payload(self._payload(), '123456')

        self.assertIsNotNone(normalized)
        assert normalized is not None
        self.assertEqual(normalized['offerId'], 123456)

    def test_official_only_client_never_has_legacy_order_or_browser_route(self):
        official = Mock()
        client = PACompositeClient(official_facade=official)

        self.assertTrue(client.uses_official_offer_api_only())
        self.assertFalse(client.uses_relay_browser_order_reads())
        self.assertFalse(client.list_seller_orders().ok)
        with self.assertRaisesRegex(RuntimeError, 'browser-session edits are disabled'):
            client.edit_offer_in_browser()

    def test_provider_creates_and_edits_mart_with_official_facade(self):
        official_client = Mock()
        official_client.uses_official_offer_api_only.return_value = True
        official_client.create_offer.return_value = SimpleNamespace(ok=True)
        official_client.edit_offer.return_value = SimpleNamespace(ok=True)
        provider = PlayerAuctionsProvider()

        created = provider.create_listing(
            official_client,
            {'payload': self._payload(), 'proxy_group': 'mart'},
        )
        updated = provider.update_listing(
            official_client,
            '123456',
            {'payload': self._payload(), 'proxy_group': 'mart'},
        )

        self.assertTrue(created.ok)
        self.assertTrue(updated.ok)
        create_args = official_client.create_offer.call_args
        self.assertEqual(create_args.args[0], 'account')
        self.assertNotIn('offerId', create_args.args[1])
        edit_args = official_client.edit_offer.call_args
        self.assertEqual(edit_args.args[0], 'account')
        self.assertEqual(edit_args.args[1]['offerId'], 123456)
        self.assertEqual(edit_args.kwargs['proxy_group'], 'mart')
