"""Tests for Token Broker API — auth, IP, service, endpoint."""

from __future__ import annotations

import hashlib
import json
from datetime import timedelta
from unittest.mock import patch, MagicMock

from django.test import TestCase, RequestFactory, override_settings
from django.utils import timezone

from apps.integrations.models import (
    IntegrationAccount, IntegrationCredential, TokenApiClient,
)
from apps.integrations.api.token_broker import (
    get_client_ip, check_ip_allowed, token_api_auth_required, token_view,
)
from apps.integrations.services.token_broker import (
    TokenBrokerService, StoreNotFound, UnsupportedMarketplace,
)


def _make_api_client(
    name='test-client',
    plain_key='test-key-abc123',
    allowed_ips=None,
    allow_any_ip=False,
    is_active=True,
):
    """Helper: create a TokenApiClient with known key."""
    return TokenApiClient.objects.create(
        name=name,
        api_key_hash=hashlib.sha256(plain_key.encode()).hexdigest(),
        api_key_prefix=plain_key[:8],
        allowed_ips=allowed_ips or [],
        allow_any_ip=allow_any_ip,
        is_active=is_active,
    )


def _make_credential(
    provider='eldorado',
    slug='eldorado-test',
    id_token='eyJ-valid-token',
    token_expires_at=None,
    is_active=True,
    account_active=True,
):
    """Helper: create IntegrationAccount + IntegrationCredential pair."""
    account = IntegrationAccount.objects.create(
        name='Test Store',
        provider=provider,
        slug=slug,
        is_active=account_active,
    )
    creds = {'email': 'test@example.com', 'password': 'secret'}
    if id_token:
        creds['id_token'] = id_token
    credential = IntegrationCredential.objects.create(
        account=account,
        credentials=creds,
        token_expires_at=token_expires_at,
        is_active=is_active,
    )
    return account, credential


# ---------------------------------------------------------------------------
# IP helper tests
# ---------------------------------------------------------------------------


class TestGetClientIp(TestCase):

    def _request(self, remote_addr='1.2.3.4', xff=None):
        factory = RequestFactory()
        request = factory.get('/')
        request.META['REMOTE_ADDR'] = remote_addr
        if xff:
            request.META['HTTP_X_FORWARDED_FOR'] = xff
        return request

    @override_settings(TRUSTED_PROXY_IPS=[])
    def test_returns_remote_addr_when_no_trusted_proxies(self):
        # Reset cached proxies
        from apps.integrations.api import token_broker
        token_broker._TRUSTED_PROXIES = None

        request = self._request(remote_addr='5.6.7.8', xff='10.0.0.1')
        self.assertEqual(get_client_ip(request), '5.6.7.8')

    @override_settings(TRUSTED_PROXY_IPS=['127.0.0.1'])
    def test_reads_xff_when_remote_is_trusted(self):
        from apps.integrations.api import token_broker
        token_broker._TRUSTED_PROXIES = None

        request = self._request(remote_addr='127.0.0.1', xff='85.1.2.3, 127.0.0.1')
        self.assertEqual(get_client_ip(request), '85.1.2.3')

    @override_settings(TRUSTED_PROXY_IPS=['10.0.0.0/8'])
    def test_cidr_trusted_proxy(self):
        from apps.integrations.api import token_broker
        token_broker._TRUSTED_PROXIES = None

        request = self._request(remote_addr='10.0.1.5', xff='203.0.113.1')
        self.assertEqual(get_client_ip(request), '203.0.113.1')


class TestCheckIpAllowed(TestCase):

    def test_allow_any_ip_true(self):
        client = _make_api_client(allow_any_ip=True)
        self.assertTrue(check_ip_allowed('99.99.99.99', client))

    def test_empty_list_denies_all(self):
        client = _make_api_client(allowed_ips=[], allow_any_ip=False)
        self.assertFalse(check_ip_allowed('1.2.3.4', client))

    def test_exact_ip_match(self):
        client = _make_api_client(allowed_ips=['1.2.3.4'])
        self.assertTrue(check_ip_allowed('1.2.3.4', client))
        self.assertFalse(check_ip_allowed('1.2.3.5', client))

    def test_cidr_match(self):
        client = _make_api_client(allowed_ips=['10.0.0.0/24'])
        self.assertTrue(check_ip_allowed('10.0.0.55', client))
        self.assertFalse(check_ip_allowed('10.0.1.1', client))


# ---------------------------------------------------------------------------
# Auth decorator tests
# ---------------------------------------------------------------------------


class TestTokenApiAuth(TestCase):

    def setUp(self):
        self.factory = RequestFactory()
        self.plain_key = 'my-secret-api-key-12345'
        self.client_obj = _make_api_client(
            plain_key=self.plain_key,
            allow_any_ip=True,
        )

    def _get(self, auth_header=None):
        request = self.factory.get('/integrations/api/token/')
        request.META['REMOTE_ADDR'] = '127.0.0.1'
        if auth_header:
            request.META['HTTP_AUTHORIZATION'] = auth_header
        return request

    def test_missing_auth_header_returns_401(self):
        response = token_view(self._get())
        self.assertEqual(response.status_code, 401)

    def test_wrong_api_key_returns_401(self):
        response = token_view(self._get(auth_header='Bearer wrong-key'))
        self.assertEqual(response.status_code, 401)

    def test_inactive_client_returns_401(self):
        self.client_obj.is_active = False
        self.client_obj.save()
        response = token_view(self._get(auth_header=f'Bearer {self.plain_key}'))
        self.assertEqual(response.status_code, 401)

    @override_settings(TRUSTED_PROXY_IPS=[])
    def test_ip_mismatch_returns_403(self):
        from apps.integrations.api import token_broker
        token_broker._TRUSTED_PROXIES = None

        self.client_obj.allow_any_ip = False
        self.client_obj.allowed_ips = ['10.10.10.10']
        self.client_obj.save()

        request = self._get(auth_header=f'Bearer {self.plain_key}')
        request.META['REMOTE_ADDR'] = '99.99.99.99'
        response = token_view(request)
        self.assertEqual(response.status_code, 403)


# ---------------------------------------------------------------------------
# TokenBrokerService tests
# ---------------------------------------------------------------------------


class TestTokenBrokerService(TestCase):

    def setUp(self):
        self.service = TokenBrokerService()

    def test_unsupported_marketplace_raises(self):
        with self.assertRaises(UnsupportedMarketplace):
            self.service.get_token('gameboost', 'any-store')

    def test_nonexistent_store_raises(self):
        with self.assertRaises(StoreNotFound):
            self.service.get_token('eldorado', 'nonexistent-store')

    def test_inactive_account_raises(self):
        _make_credential(slug='inactive-acct', account_active=False)
        with self.assertRaises(StoreNotFound):
            self.service.get_token('eldorado', 'inactive-acct')

    def test_inactive_credential_raises(self):
        _make_credential(slug='inactive-cred', is_active=False)
        with self.assertRaises(StoreNotFound):
            self.service.get_token('eldorado', 'inactive-cred')

    def test_valid_token_returns_from_db_no_refresh(self):
        """Valid token in DB → return directly, no Cognito call."""
        expires = timezone.now() + timedelta(hours=1)
        _make_credential(
            slug='valid-store',
            id_token='eyJ-cached-token',
            token_expires_at=expires,
        )

        with patch(
            'apps.integrations.services.token_broker.TokenBrokerService._refresh_token'
        ) as mock_refresh:
            result = self.service.get_token('eldorado', 'valid-store')

        mock_refresh.assert_not_called()
        self.assertEqual(result['token'], 'eyJ-cached-token')
        self.assertEqual(result['marketplace'], 'eldorado')
        self.assertEqual(result['store'], 'valid-store')
        self.assertGreater(result['expires_in'], 0)

    def test_empty_token_triggers_refresh(self):
        """No id_token in DB → must refresh."""
        _make_credential(slug='empty-store', id_token=None, token_expires_at=None)

        mock_refresh = MagicMock(return_value={
            'id_token': 'eyJ-new-token',
            'expires_in': 3600,
        })

        with patch.object(
            TokenBrokerService, '_refresh_eldorado', mock_refresh,
        ):
            result = self.service.get_token('eldorado', 'empty-store')

        self.assertEqual(result['token'], 'eyJ-new-token')
        mock_refresh.assert_called_once()

    def test_expired_token_triggers_refresh(self):
        """Expired token → must refresh."""
        expired = timezone.now() - timedelta(minutes=5)
        _make_credential(slug='expired-store', id_token='eyJ-old', token_expires_at=expired)

        mock_refresh = MagicMock(return_value={
            'id_token': 'eyJ-refreshed',
            'expires_in': 3600,
        })

        with patch.object(
            TokenBrokerService, '_refresh_eldorado', mock_refresh,
        ):
            result = self.service.get_token('eldorado', 'expired-store')

        self.assertEqual(result['token'], 'eyJ-refreshed')
        mock_refresh.assert_called_once()

        # Verify DB was updated
        cred = IntegrationCredential.objects.get(account__slug='expired-store')
        self.assertEqual(cred.credentials['id_token'], 'eyJ-refreshed')
        self.assertIsNotNone(cred.token_expires_at)


# ---------------------------------------------------------------------------
# Endpoint integration tests
# ---------------------------------------------------------------------------


class TestTokenEndpoint(TestCase):

    def setUp(self):
        self.factory = RequestFactory()
        self.plain_key = 'endpoint-test-key-xyz'
        _make_api_client(plain_key=self.plain_key, allow_any_ip=True)

    def _get(self, params='', auth=True):
        request = self.factory.get(f'/integrations/api/token/?{params}')
        request.META['REMOTE_ADDR'] = '127.0.0.1'
        if auth:
            request.META['HTTP_AUTHORIZATION'] = f'Bearer {self.plain_key}'
        return request

    def test_missing_params_returns_400(self):
        response = token_view(self._get('marketplace=eldorado'))
        self.assertEqual(response.status_code, 400)

    def test_unsupported_marketplace_returns_400(self):
        response = token_view(self._get('marketplace=gameboost&store=any'))
        self.assertEqual(response.status_code, 400)

    def test_nonexistent_store_returns_404(self):
        response = token_view(self._get('marketplace=eldorado&store=no-such-store'))
        self.assertEqual(response.status_code, 404)

    def test_success_returns_token_with_cache_control(self):
        expires = timezone.now() + timedelta(hours=1)
        _make_credential(slug='my-store', id_token='eyJ-ok', token_expires_at=expires)

        response = token_view(self._get('marketplace=eldorado&store=my-store'))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Cache-Control'], 'no-store')

        data = json.loads(response.content)
        self.assertEqual(data['token'], 'eyJ-ok')
        self.assertEqual(data['marketplace'], 'eldorado')
        self.assertEqual(data['store'], 'my-store')
        self.assertGreater(data['expires_in'], 0)
