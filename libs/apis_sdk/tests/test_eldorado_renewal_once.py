"""Synthetic renewal PUT boundary tests; transport never opens a socket."""
from concurrent.futures import ThreadPoolExecutor
import os
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import Mock, patch

from apis_sdk.clients.marketplaces.eldorado.client import EldoradoClient
from apis_sdk.clients.marketplaces.eldorado.config import EldoradoConfig
from apis_sdk.clients.marketplaces.eldorado.facade import EldoradoFacade
from apis_sdk.clients.marketplaces.eldorado.governor import (
    OFFER_MUTATION_METHODS,
    WRITE_METHODS,
    EldoradoGovernor,
    GovernedEldoradoFacade,
    is_governor_refusal,
)
from apis_sdk.core.enums import ErrorCategory, HttpMethod
from apis_sdk.core.exceptions import TransportError
from apis_sdk.core.result import ApiResult


class RenewalOnceTests(TestCase):
    def setUp(self):
        # Only fake clients and a temporary governor directory are used.
        env = patch.dict(os.environ, {'ELDORADO_WRITES_HELD': 'false'})
        env.start()
        self.addCleanup(env.stop)
        directory = TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.state_dir = Path(directory.name)
        self.auth = Mock()
        self.auth.get_auth_headers.return_value = {'Authorization': 'synthetic-token'}
        self.transport = Mock()
        self.retry = Mock()
        self.retry.execute.side_effect = AssertionError('general retry must not run')
        self.proxy = SimpleNamespace(host='synthetic-proxy', port=1234,
                                     to_url=lambda: 'http://synthetic-proxy:1234')
        self.pool = Mock()
        self.pool.acquire.return_value = self.proxy
        self.pool.is_healthy.return_value = True
        self.low = EldoradoClient(EldoradoConfig(base_url='https://example.invalid'), self.transport)
        self.logger = Mock()
        self.facade = EldoradoFacade(self.low, self.auth, transport=self.transport,
                                      proxy_pool=self.pool, retry_policy=self.retry,
                                      max_retry_attempts=7, logger=self.logger)
        self.governor = EldoradoGovernor(self.state_dir, write_min_interval=120,
                                         clock=lambda: 1_800_000_000.0)
        self.client = GovernedEldoradoFacade(self.facade, 'synthetic-store',
                                           governor=self.governor, max_write_wait=0)

    def test_sent_transport_error_is_never_replayed_inside_outer_lease(self):
        self.transport.request.side_effect = TransportError('sent-response-unknown-sentinel',
                                                            provider='eldorado')
        payload = {'details': {'pricing': {'volumeDiscounts': []}},
                   'accountDeliveryDetails': [], 'accountSecretDetails': []}
        with self.client.offer_mutation('fixture-offer') as admitted:
            self.assertTrue(admitted)
            result = self.client.update_offer_once('fixture-offer', payload, proxy_group='fixture-group')
        self.assertFalse(result.ok)
        self.assertEqual(result.error.category, ErrorCategory.NETWORK)
        self.transport.request.assert_called_once()
        self.retry.execute.assert_not_called()
        self.auth.refresh.assert_not_called()
        self.pool.acquire.assert_called_once_with(group='fixture-group', exclude=None)
        args, kwargs = self.transport.request.call_args
        self.assertEqual(args[0], HttpMethod.PUT)
        self.assertEqual(args[1], 'https://example.invalid/api/flexibleOffers/account/fixture-offer/details')
        self.assertEqual(kwargs['headers'], {'Authorization': 'synthetic-token'})
        self.assertEqual(kwargs['proxy_url'], 'http://synthetic-proxy:1234')
        self.assertNotIn('accountSecretDetails', kwargs['json_body'])
        self.assertIsNone(kwargs['json_body']['details']['pricing']['volumeDiscounts'])
        self.assertEqual(self._counts()['write'], 1)

    def test_server_error_and_unexpected_exception_each_send_at_most_once(self):
        for failure in ('server', 'unexpected'):
            with self.subTest(failure=failure):
                self.transport.reset_mock(side_effect=True)
                if failure == 'server':
                    self.transport.request.return_value = SimpleNamespace(
                        is_success=False, status_code=503, headers={},
                        json=lambda: {'message': 'synthetic-server-sentinel'},
                    )
                else:
                    self.transport.request.side_effect = RuntimeError('synthetic-response-loss')
                # A fresh store budget isolates the two synthetic outcomes.
                client = GovernedEldoradoFacade(self.facade, failure,
                                               governor=self.governor, max_write_wait=0)
                result = client.update_offer_once('fixture-offer', {})
                self.assertFalse(result.ok)
                self.transport.request.assert_called_once()
                self.retry.execute.assert_not_called()
                self.auth.refresh.assert_not_called()

    def test_explicit_auth_rejection_is_not_replayed_for_renewal(self):
        self.transport.request.return_value = SimpleNamespace(
            is_success=False, status_code=401, headers={},
            json=lambda: {'message': 'synthetic-auth-rejection'},
        )
        result = self.client.update_offer_once('fixture-offer', {})
        self.assertFalse(result.ok)
        self.assertEqual(result.error.category, ErrorCategory.AUTHENTICATION)
        self.transport.request.assert_called_once()
        self.auth.refresh.assert_not_called()
        self.retry.execute.assert_not_called()

    def test_other_execute_once_callers_keep_default_auth_refresh_behavior(self):
        operation = Mock(side_effect=[
            ApiResult.from_error(ErrorCategory.AUTHENTICATION, 'synthetic-auth-rejection',
                                 provider='eldorado', status_code=401),
            ApiResult.success({}),
        ])
        result = self.facade._exec.execute_once(operation, proxy_group='fixture-group')
        self.assertTrue(result.ok)
        self.assertEqual(operation.call_count, 2)
        self.auth.refresh.assert_called_once()

    def test_renewal_private_and_delivery_read_errors_never_log_raw_provider_message(self):
        sentinel = 'SYNTHETIC_PRIVATE_READ_ERROR_SENTINEL'
        for method in ('get_private_offer', 'get_offer_account_details'):
            with self.subTest(method=method):
                self.transport.reset_mock()
                self.logger.reset_mock()
                self.transport.request.return_value = SimpleNamespace(
                    is_success=False, status_code=400, headers={},
                    json=lambda: {'message': sentinel},
                )
                result = getattr(self.client, method)('fixture-offer', renewal_safe=True)
                self.assertFalse(result.ok)
                self.transport.request.assert_called_once()
                self.assertNotIn(sentinel, str(self.logger.mock_calls))
                self.retry.execute.assert_not_called()
                self.auth.refresh.assert_not_called()

    def test_uppercase_and_lowercase_uuid_contend_on_the_same_offer_lease(self):
        oid = '3d952183-48cb-476e-ab3f-08df24631e7b'
        calls = []
        inner = SimpleNamespace(update_offer_once=lambda *a, **k: calls.append('write') or ApiResult.success({}))
        peer = GovernedEldoradoFacade(inner, 'synthetic-store',
                                     governor=EldoradoGovernor(self.state_dir, write_min_interval=0), max_write_wait=0)
        with ThreadPoolExecutor(max_workers=1) as executor:
            with self.client.offer_mutation(' ' + oid.upper() + ' ') as admitted:
                self.assertTrue(admitted)
                with peer.offer_mutation(oid) as nested:
                    self.assertTrue(nested)
                refused = executor.submit(peer.update_offer_once, oid, {}).result(timeout=5)
                self.assertEqual(refused.error.details['governor'], 'offer_mutation_busy')
                self.assertEqual(calls, [])
            self.assertTrue(executor.submit(peer.update_offer_once, oid, {}).result(timeout=5).ok)
        self.assertEqual(calls, ['write'])

    def test_write_hold_refuses_without_auth_proxy_transport_or_budget(self):
        cached = self.client.update_offer_once
        with patch.dict(os.environ, {'ELDORADO_WRITES_HELD': 'true'}):
            result = cached('fixture-offer', {})
            with self.client.offer_mutation('fixture-offer') as admitted:
                self.assertFalse(admitted)
        self.assertTrue(is_governor_refusal(result))
        self.assertEqual(result.error.details['governor'], 'writes_held')
        self.transport.request.assert_not_called()
        self.auth.get_auth_headers.assert_not_called()
        self.pool.acquire.assert_not_called()
        self.assertEqual(self.governor.snapshot(), {})

    def test_budget_refusal_inside_outer_lease_has_zero_sends(self):
        self.assertTrue(self.governor.acquire_write('synthetic-store', max_wait=0)[0])
        with self.client.offer_mutation('fixture-offer') as admitted:
            self.assertTrue(admitted)
            result = self.client.update_offer_once('fixture-offer', {})
        self.assertEqual(result.error.details['governor'], 'write_budget')
        self.transport.request.assert_not_called()
        self.assertEqual(self._counts()['write'], 1)

    def test_nested_once_reuses_lease_but_another_thread_is_refused(self):
        calls = []
        inner = SimpleNamespace(update_offer_once=lambda *a, **k: calls.append('write') or ApiResult.success({}))
        peer = GovernedEldoradoFacade(inner, 'eldorado-synthetic-store',
                                     governor=EldoradoGovernor(self.state_dir, write_min_interval=0),
                                     max_write_wait=0)
        with ThreadPoolExecutor(max_workers=1) as executor:
            with self.client.offer_mutation('fixture-offer') as admitted:
                self.assertTrue(admitted)
                with peer.offer_mutation('fixture-offer') as nested:
                    self.assertTrue(nested)
                    self.assertTrue(peer.update_offer_once(offer_id='fixture-offer', payload={}).ok)
                refused = executor.submit(peer.update_offer_once, 'fixture-offer', {}).result(timeout=5)
                self.assertEqual(refused.error.details['governor'], 'offer_mutation_busy')
                self.assertEqual(calls, ['write'])
            self.assertTrue(executor.submit(peer.update_offer_once, 'fixture-offer', {}).result(timeout=5).ok)
        self.assertEqual(calls, ['write', 'write'])

    def test_existing_update_offer_still_uses_the_general_retry_executor(self):
        self.retry.execute.side_effect = None
        self.retry.execute.return_value = ApiResult.success({})
        self.assertTrue(self.facade.update_offer('fixture-offer', {}).ok)
        self.retry.execute.assert_called_once()
        self.assertIn('update_offer_once', WRITE_METHODS)
        self.assertIn('update_offer_once', OFFER_MUTATION_METHODS)

    def _counts(self):
        return next(iter(self.governor.snapshot()['synthetic-store']['hours'].values()))
