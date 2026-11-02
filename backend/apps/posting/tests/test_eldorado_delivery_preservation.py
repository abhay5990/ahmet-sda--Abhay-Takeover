"""Synthetic caller-level tests for lease, lossless append, and fail-closed edits."""
from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import patch

from django.test import SimpleTestCase

from apis_sdk.core.result import ApiResult
from apis_sdk.core.enums import ErrorCategory
from apis_sdk.clients.marketplaces.eldorado.models import EldoradoOfferCredentialsResponse
from apps.posting.services import offer_editor
from apps.posting.services.pool import replenisher


DETAIL = {
    'accountDetails': {'accountLogin': 'existing-fixture', 'accountPassword': 'fixture-only'},
    'emailDetails': None,
    'mfaDetails': {'fixtureRecovery': ['synthetic-only']},
    'additionalInfo': '  keep spacing  ',
    'unknownProviderField': {'keep': True},
}


class LeaseClient:
    def __init__(self, response, admitted=True, result=None):
        self.response = response
        self.admitted = admitted
        self.depth = 0
        self.calls = []
        self.result = result if result is not None else ApiResult.success({})
        self.payload = None

    @contextmanager
    def offer_mutation(self, offer_id):
        self.calls.append('lease')
        self.depth += 1
        try:
            yield self.admitted
        finally:
            self.depth -= 1
            self.calls.append('release')

    def get_offer_account_details(self, *args, **kwargs):
        assert self.depth > 0, 'Authoritative read must occur inside the lease'
        self.calls.append('read')
        return ApiResult.success(self.response)

    def update_offer(self, offer_id, payload, **kwargs):
        assert self.depth > 0, 'PUT must use the same lease as the read'
        self.calls.append('update')
        self.payload = payload
        return self.result

    def create_offer(self, *args, **kwargs):
        raise AssertionError('No automatic recreate after failed PUT')

    def delete_offer(self, *args, **kwargs):
        raise AssertionError('No automatic delete after failed PUT')


def listing():
    return SimpleNamespace(pk=1, store_listing_id='fixture-offer', raw_data={
        'gameId': '106', 'category': 'Account', 'offerTitle': 'Fixture title',
        'description': 'Fixture description', 'pricePerUnit': {'amount': 10, 'currency': 'USD'},
        'quantity': 1, 'attributes': [], 'tradeEnvironmentValues': [],
    })


def response(entry=None):
    return EldoradoOfferCredentialsResponse.model_validate({'accountDeliveryDetails': [
        {'id': 'existing', 'legacySecretDetails': 'Login: existing-fixture\nPassword: fixture-only',
         'structuredDetails': DETAIL} if entry is None else entry
    ]})


class EldoradoDeliveryPreservationTests(SimpleTestCase):
    def _push(self, client):
        pool = SimpleNamespace(pk=1, listing=listing(), store=SimpleNamespace(pk=1), pool_offer=SimpleNamespace(pk=1))
        item = SimpleNamespace(pk=2, owned_product=object())
        with patch.object(replenisher, 'format_credential_for_marketplace', return_value='Login: new-fixture\nPassword: fixture-new'), \
             patch.object(replenisher, '_mark_items_pushed', return_value=1), \
             patch.object(replenisher, '_eldorado_remote_ids_for_credentials', return_value={}), \
             patch.object(replenisher, 'release_claims_as_pending') as released, \
             patch.object(replenisher, '_park_pool_offer_for_attention') as parked, \
             patch.object(replenisher, '_log'):
            value = replenisher._push_eldorado(pool, client, 'fixture-offer', [item], None)
        return value, released, parked

    def test_append_retains_original_mfa_and_holds_one_lease(self):
        client = LeaseClient(response())
        value, released, parked = self._push(client)
        self.assertEqual(value, 1)
        self.assertEqual(client.calls, ['lease', 'read', 'update', 'release'])
        self.assertEqual(client.payload['accountDeliveryDetails'][0], DETAIL)
        self.assertEqual(client.payload['accountDeliveryDetails'][1]['accountDetails']['accountLogin'], 'new-fixture')
        self.assertEqual(client.payload['details']['pricing']['quantity'], 2)
        released.assert_not_called()
        parked.assert_not_called()

    def test_busy_or_held_offer_never_reads_or_writes_and_releases_claim(self):
        client = LeaseClient(response(), admitted=False)
        value, released, _ = self._push(client)
        self.assertEqual(value, 0)
        self.assertEqual(client.calls, ['lease', 'release'])
        released.assert_called_once()

    def test_unreadable_existing_account_never_sends_put(self):
        client = LeaseClient(response({'id': 'unreadable'}))
        value, released, parked = self._push(client)
        self.assertEqual(value, 0)
        self.assertNotIn('update', client.calls)
        released.assert_called_once()
        parked.assert_called_once()

    def test_content_rejection_preserves_original_without_recreate(self):
        client = LeaseClient(response(), result=ApiResult.from_error(ErrorCategory.VALIDATION, 'fixture rejection', status_code=400))
        value, released, parked = self._push(client)
        self.assertEqual(value, 0)
        self.assertEqual(client.calls, ['lease', 'read', 'update', 'release'])
        released.assert_called_once()
        parked.assert_called_once()

    def test_rate_limit_never_recreates_or_deletes(self):
        client = LeaseClient(response(), result=ApiResult.from_error(ErrorCategory.RATE_LIMIT, 'fixture 429', status_code=429))
        value, released, parked = self._push(client)
        self.assertEqual(value, 0)
        released.assert_called_once()
        parked.assert_not_called()

    def test_edit_uses_same_lease_and_preserves_original_mfa(self):
        client = LeaseClient(response())
        class Provider:
            def update_listing(self, facade, offer_id, payload):
                return facade.update_offer(offer_id, payload)
        with patch.object(offer_editor, 'build_proxy_pool', return_value=None), \
             patch.object(offer_editor, 'get_group_name', return_value=None), \
             patch.object(offer_editor, 'get_or_build_client', return_value=client), \
             patch.object(offer_editor, 'get_provider', return_value=Provider()), \
             patch.object(offer_editor, '_update_listing_db'), \
             patch.object(offer_editor, '_log'):
            value = offer_editor._edit_eldorado(listing(), {'title': 'New fixture title'}, SimpleNamespace(pk=1, credential=object()))
        self.assertTrue(value.ok)
        self.assertEqual(client.calls, ['lease', 'read', 'update', 'release'])
        self.assertEqual(client.payload['accountDeliveryDetails'], [DETAIL])
        self.assertEqual(client.payload['details']['offerTitle'], 'New fixture title')

    def test_edit_fails_closed_without_serialization(self):
        with patch.object(offer_editor, 'build_proxy_pool', return_value=None), \
             patch.object(offer_editor, 'get_group_name', return_value=None), \
             patch.object(offer_editor, 'get_or_build_client', return_value=SimpleNamespace()):
            value = offer_editor._edit_eldorado(listing(), {'title': 'x'}, SimpleNamespace(pk=1, credential=object()))
        self.assertFalse(value.ok)
