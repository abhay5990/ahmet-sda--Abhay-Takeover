from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import patch

import requests
from django.test import SimpleTestCase

from apis_sdk.core.enums import ErrorCategory
from apis_sdk.clients.marketplaces.playerauctions.models import PlayerAuctionsCancelRequest

from apps.integrations.providers.playerauctions import MctMartDelegationClient


class PaMartDelegationOutcomeTests(SimpleTestCase):
    """Synthetic bridge contracts only; no credentials, HTTP, or database access."""

    def setUp(self):
        super().setUp()
        self.client = MctMartDelegationClient(
            url='https://mct.example.invalid/api/sda/pa-mart/delegate',
            token='synthetic-bridge-token',
            key=b't' * 32,
        )
        self.post = self.enterContext(patch(
            'apps.integrations.providers.playerauctions.requests.post',
        ))
        self.enterContext(patch.dict(
            'apps.integrations.providers.playerauctions.os.environ',
            {'PA_MART_CREATE_HOLD': 'false'},
        ))

    def _response(self, body, status_code=200):
        self.post.return_value = SimpleNamespace(
            ok=200 <= status_code < 400,
            status_code=status_code,
            content=b'synthetic-json',
            json=lambda: body,
        )

    def _write(self, action):
        if action == 'create':
            return self.client.create_offer('account', {})
        return self.client.edit_offer('account', {'offerId': 123456})

    def _assert_unknown(self, result):
        self.assertFalse(result.ok)
        self.assertIsNone(result.data)
        self.assertIsNotNone(result.error)
        self.assertEqual(result.error.category, ErrorCategory.SERVER_ERROR)
        self.assertFalse(result.error.is_retryable)
        self.assertEqual(result.error.details['delegation_outcome'], 'unknown')
        self.assertNotIn('no_write_proof', result.error.details)
        self.assertNotIn('provider_message', result.error.details)
        self.assertRegex(result.error.details['request_id'], r'\A[0-9a-f]{40}\Z')
        self.assertEqual(
            result.error.details['request_id'],
            self.post.call_args.kwargs['json']['requestId'],
        )

    def _assert_local_refusal(self, result, error_code):
        self.assertFalse(result.ok)
        self.assertEqual(result.error.category, ErrorCategory.VALIDATION)
        self.assertFalse(result.error.is_retryable)
        self.assertEqual(result.error.details, {
            'delegation_outcome': 'rejected',
            'no_write_proof': 'sda_local_pretransport',
            'error_code': error_code,
        })
        self.post.assert_not_called()

    def test_success_requires_positive_integer_offer_identity_for_create_and_update(self):
        for action in ('create', 'update'):
            for offer_id, expected in ((123456, '123456'), ('123456', '123456'), ('000123456', '123456')):
                with self.subTest(action=action, offer_id=offer_id):
                    self._response({'ok': True, 'status': 'succeeded', 'offerId': offer_id})
                    result = self._write(action)
                    self.assertTrue(result.ok)
                    self.assertEqual(result.data['offer_id'], expected)
                    self.assertEqual(result.status_code, 200)
                    self.assertRegex(result.data['request_id'], r'\A[0-9a-f]{40}\Z')
                    self.assertEqual(self.post.call_args.kwargs['json']['action'], action)

    def test_success_without_offer_identity_is_unknown(self):
        for action in ('create', 'update'):
            with self.subTest(action=action):
                self._response({'ok': True, 'status': 'succeeded'})
                self._assert_unknown(self._write(action))

    def test_success_with_invalid_offer_identity_is_unknown(self):
        invalid_ids = (None, '', 0, -1, True, False, 1.0, 1.5, '0', '000', '-1', '+1',
                       '1.0', '1e3', ' 123 ', 'not-an-id', '\u0661\u0662\u0663', [], {})
        for action in ('create', 'update'):
            for offer_id in invalid_ids:
                with self.subTest(action=action, offer_id=offer_id):
                    self._response({'ok': True, 'status': 'succeeded', 'offerId': offer_id})
                    self._assert_unknown(self._write(action))

    def test_error_with_offer_identity_never_proves_no_write(self):
        bodies = (
            {'ok': False, 'status': 'rejected', 'errorCode': 'create_failed_http_200', 'offerId': 123456},
            {'ok': True, 'status': 'succeeded', 'errorCode': 'create_failed_http_200', 'offerId': 123456},
            {'ok': True, 'status': 'succeeded', 'error': 'rejected', 'offerId': 123456},
        )
        for action in ('create', 'update'):
            for body_index, body in enumerate(bodies):
                with self.subTest(action=action, body_index=body_index):
                    self._response(body)
                    self._assert_unknown(self._write(action))

    def test_missing_or_unrecognized_status_with_offer_identity_is_unknown(self):
        for status in (None, '', 'pending', 'unknown', 'rejected', 'future_status', 'success', 'SUCCEEDED', [], {}):
            for action in ('create', 'update'):
                with self.subTest(action=action, status=status):
                    body = {'ok': True, 'offerId': 123456}
                    if status is not None:
                        body['status'] = status
                    self._response(body)
                    self._assert_unknown(self._write(action))

    def test_generic_rejected_http_200_and_4xx_are_unknown(self):
        for status_code in (200, 400, 401, 403, 404, 409, 422, 429):
            with self.subTest(status_code=status_code):
                self._response({
                    'ok': False,
                    'status': 'rejected',
                    'errorCode': f'create_failed_http_{status_code}',
                }, status_code)
                result = self.client.create_offer('account', {})
                self._assert_unknown(result)
                self.assertEqual(result.status_code, status_code)
                self.assertEqual(result.error.status_code, status_code)

    def test_external_claim_of_local_no_write_proof_is_not_trusted(self):
        self._response({
            'ok': False,
            'status': 'rejected',
            'delegation_outcome': 'rejected',
            'no_write_proof': 'sda_local_pretransport',
            'errorCode': 'mart_create_held',
        })
        self._assert_unknown(self.client.create_offer('account', {}))

    def test_server_failure_is_unknown_even_with_success_and_offer_identity(self):
        for body in ({'ok': False, 'status': 'rejected'},
                     {'ok': True, 'status': 'succeeded', 'offerId': 123456}):
            self._response(body, 500)
            result = self.client.create_offer('account', {})
            self._assert_unknown(result)
            self.assertEqual(result.status_code, 500)

    def test_redirect_is_not_confirmed_success(self):
        self._response({'ok': True, 'status': 'succeeded', 'offerId': 123456}, 302)
        self._assert_unknown(self.client.create_offer('account', {}))

    def test_transport_failure_is_unknown_and_not_auto_retryable(self):
        for exception_type in (requests.Timeout, requests.ConnectionError):
            with self.subTest(exception_type=exception_type.__name__):
                self.post.side_effect = exception_type('synthetic transport failure')
                self._assert_unknown(self.client.create_offer('account', {}))

    def test_invalid_or_empty_json_response_is_unknown(self):
        self._response({})
        self.post.return_value.json = lambda: (_ for _ in ()).throw(ValueError('synthetic invalid JSON'))
        self._assert_unknown(self.client.create_offer('account', {}))
        for body in (None, [], 'unexpected', 42):
            with self.subTest(body=body):
                self._response(body)
                self._assert_unknown(self.client.create_offer('account', {}))
        self._response({'ok': True, 'status': 'succeeded', 'offerId': 123456})
        self.post.return_value.content = b''
        self._assert_unknown(self.client.create_offer('account', {}))

    def test_truthy_ok_is_not_confirmed_success(self):
        for ok in ('false', 'true', 1, [], {}):
            with self.subTest(ok=ok):
                self._response({'ok': ok, 'status': 'succeeded', 'offerId': 123456})
                self._assert_unknown(self.client.create_offer('account', {}))

    def test_local_create_hold_proves_no_write_without_transport_or_encryption(self):
        with patch.dict('apps.integrations.providers.playerauctions.os.environ', {'PA_MART_CREATE_HOLD': 'true'}), \
                patch.object(self.client, '_encrypted_envelope') as encrypt:
            result = self.client.create_offer('account', {})
        self._assert_local_refusal(result, 'mart_create_held')
        encrypt.assert_not_called()

    def test_local_invalid_create_product_type_proves_no_write(self):
        with patch.object(self.client, '_encrypted_envelope') as encrypt:
            result = self.client.create_offer('currency', {})
        self._assert_local_refusal(result, 'mct_invalid_product_type')
        encrypt.assert_not_called()

    def test_create_hold_does_not_block_update_or_exact_id_cancellation(self):
        with patch.dict('apps.integrations.providers.playerauctions.os.environ', {'PA_MART_CREATE_HOLD': 'true'}):
            self._response({'ok': True, 'status': 'succeeded', 'offerId': 123456})
            self.assertTrue(self.client.edit_offer('account', {'offerId': 123456}).ok)
            self.assertEqual(self.post.call_args.kwargs['json']['action'], 'update')
            self._response({'ok': True, 'status': 'succeeded'})
            result = self.client.cancel_offers(offer_ids=[123456])
            self.assertTrue(result.ok)
            self.assertEqual(result.data['offer_id'], '')
            self.assertEqual(self.post.call_args.kwargs['json']['action'], 'cancel')

    def test_request_model_cancellation_succeeds_without_offer_identity(self):
        self._response({'ok': True, 'status': 'succeeded'})
        result = self.client.cancel_offers(PlayerAuctionsCancelRequest(offerIds=[123456]))
        self.assertTrue(result.ok)
        self.assertEqual(result.data['offer_id'], '')
        self.assertEqual(self.post.call_args.kwargs['json']['action'], 'cancel')

    def test_cancel_with_missing_status_is_unknown(self):
        self._response({'ok': True})
        self._assert_unknown(self.client.cancel_offers(offer_ids=[123456]))

    def test_password_bearing_provider_message_codes_and_request_id_are_not_persisted(self):
        # Deliberately synthetic markers, never actual fixture/production secrets.
        marker = 'SYNTHETIC_PASSWORD_MARKER'
        malicious = f'password={marker}; bridge-token={marker}'
        self._response({
            'ok': False,
            'status': 'rejected',
            'message': malicious,
            'errorCode': malicious,
            'error': malicious,
            'requestId': malicious,
            'offerId': malicious,
        })
        result = self.client.create_offer('account', {})
        self._assert_unknown(result)
        self.assertEqual(result.error.details['error_code'], 'mct_delegation_outcome_unknown')
        persisted = json.dumps(result.error.details) + result.error.message
        self.assertNotIn(marker, persisted)
        self.assertNotIn('synthetic-bridge-token', persisted)
        self.assertNotIn('password=', persisted)
