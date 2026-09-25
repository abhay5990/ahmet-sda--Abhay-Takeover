from __future__ import annotations

import base64
import json
from types import SimpleNamespace
from unittest.mock import Mock, patch

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from django.test import SimpleTestCase

from apps.integrations.providers.playerauctions import (
    MctMartDelegationClient,
    PACompositeClient,
    PlayerAuctionsProvider,
    _get_mct_mart_delegation_config,
    _mart_mct_delegation_enabled,
    _normalize_official_account_payload,
)
from apps.sync.services.playerauctions.offers.service import (
    PlayerAuctionsOfferSyncService,
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

    def test_mart_delegation_requires_protected_endpoint_and_aes_key(self):
        key = base64.b64encode(b'x' * 32).decode('ascii')
        url, token, decoded = _get_mct_mart_delegation_config({
            'PA_MART_MCT_DELEGATION_URL': 'https://mct.example/api/sda/pa-mart/delegate',
            'PA_MART_MCT_DELEGATION_TOKEN': 'bridge-token',
            'PA_MART_MCT_DELEGATION_KEY': key,
        })

        self.assertEqual(url, 'https://mct.example/api/sda/pa-mart/delegate')
        self.assertEqual(token, 'bridge-token')
        self.assertEqual(decoded, b'x' * 32)
        self.assertTrue(_mart_mct_delegation_enabled({'PA_MART_MCT_DELEGATION_ENABLED': 'true'}))
        self.assertFalse(_mart_mct_delegation_enabled({}))
        with self.assertRaisesRegex(RuntimeError, 'configuration is incomplete'):
            _get_mct_mart_delegation_config({'PA_MART_MCT_DELEGATION_URL': 'http://mct.example/api/sda/pa-mart/delegate'})

    def test_mart_delegation_encrypts_delivery_payload_before_transport(self):
        key = b'y' * 32
        client = MctMartDelegationClient(
            url='https://mct.example/api/sda/pa-mart/delegate',
            token='bridge-token',
            key=key,
        )
        payload = {'autoDelivery': {'loginName': 'user', 'password': 'secret-password'}}
        envelope = client._encrypted_envelope(payload)

        self.assertNotIn('secret-password', json.dumps(envelope))
        nonce = base64.b64decode(envelope['iv'])
        ciphertext = base64.b64decode(envelope['data']) + base64.b64decode(envelope['tag'])
        self.assertEqual(json.loads(AESGCM(key).decrypt(nonce, ciphertext, None)), payload)
        self.assertTrue(client.uses_official_offer_api_only())
        self.assertFalse(client.uses_relay_browser_order_reads())

    @patch('apps.integrations.providers.playerauctions.requests.post')
    def test_mart_active_offer_snapshot_sends_only_sda_known_offer_ids(self, post):
        client = MctMartDelegationClient(
            url='https://mct.example/api/sda/pa-mart/delegate',
            token='bridge-token',
            key=b's' * 32,
        )
        post.return_value = SimpleNamespace(
            ok=True,
            status_code=200,
            content=b'{}',
            json=lambda: {
                'ok': True,
                'offers': [{'offerId': 294100001, 'title': 'Safe summary'}],
                'pagination': {'currentPage': 1, 'totalPages': 1},
                'snapshotRefreshedAt': '2026-09-25T10:00:00Z',
                'snapshotAgeSeconds': 60,
            },
        )

        result = client.list_offers(
            offer_ids=[294100001, 294100001], page=1, page_size=50,
            listing_status='Active',
        )

        self.assertTrue(result.ok)
        self.assertTrue(client.uses_mct_official_offer_snapshot())
        self.assertEqual(result.data, [{'offerId': 294100001, 'title': 'Safe summary'}])
        post.assert_called_once_with(
            'https://mct.example/api/sda/pa-mart/official-active-offers',
            json={'offerIds': [294100001], 'pageIndex': 1, 'pageSize': 50},
            headers={'X-Bridge-Secret': 'bridge-token', 'Content-Type': 'application/json'},
            timeout=45,
        )

    def test_mart_active_offer_snapshot_refuses_unbounded_discovery(self):
        client = MctMartDelegationClient(
            url='https://mct.example/api/sda/pa-mart/delegate',
            token='bridge-token',
            key=b't' * 32,
        )

        result = client.list_offers(offer_ids=[], listing_status='Active')

        self.assertFalse(result.ok)
        self.assertIn('requires SDA-known offer IDs', result.error.message)

    def test_mart_snapshot_sync_does_not_request_offer_details(self):
        client = Mock()
        client.uses_mct_official_offer_snapshot.return_value = True
        service = PlayerAuctionsOfferSyncService(client=client)
        item = {'offerId': 294100001, 'title': 'Safe summary'}

        prepared, meta = service.prepare_item(item, SimpleNamespace())

        self.assertEqual(prepared, item)
        self.assertEqual(meta, {'detail_source': 'mct_official_active_snapshot'})
        client.get_offer_details.assert_not_called()

    @patch('apps.integrations.providers.playerauctions.requests.post')
    def test_mart_delegated_edit_returns_the_provider_confirmed_offer_id(self, post):
        client = MctMartDelegationClient(
            url='https://mct.example/api/sda/pa-mart/delegate',
            token='bridge-token',
            key=b'z' * 32,
        )
        post.return_value = SimpleNamespace(
            ok=True,
            status_code=200,
            content=b'{}',
            json=lambda: {
                'ok': True,
                'status': 'succeeded',
                'offerId': '294100002',
            },
        )

        result = client.edit_offer('account', {'offerId': 294100001})

        self.assertTrue(result.ok)
        self.assertEqual(result.data['offer_id'], '294100002')
