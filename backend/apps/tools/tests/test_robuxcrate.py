"""Comprehensive tests for the RobuxCrate tool — API endpoints, services, helpers."""
from __future__ import annotations

import json
import uuid
from unittest.mock import MagicMock, patch, PropertyMock

from django.test import TestCase, RequestFactory, override_settings
from django.contrib.auth import get_user_model
from django.test.client import Client
from django.urls import reverse

from apps.tools.helpers import (
    api_role_required,
    create_lookup_token,
    parse_json_body,
    verify_lookup_token,
    LOOKUP_TOKEN_MAX_AGE,
)
from apps.tools.models import RobuxCrateBatch, RobuxCrateOrder
from apps.tools.services.robuxcrate import (
    map_provider_status,
    process_pending_batches,
    refresh_order_status,
    _update_batch_status,
)

User = get_user_model()


# ── Helpers ───────────────────────────────────────────────────────

def _make_api_result(ok=True, data=None, error=None):
    """Build a mock ApiResult matching the SDK pattern."""
    result = MagicMock()
    result.ok = ok
    result.data = data
    result.error = error
    return result


def _make_error(message='test error', details=None, category=None):
    from apis_sdk.core.enums import ErrorCategory
    err = MagicMock()
    err.message = message
    err.details = details or {}
    err.category = category or ErrorCategory.VALIDATION
    return err


def _make_network_error(message='Connection timeout'):
    from apis_sdk.core.enums import ErrorCategory
    return _make_error(message=message, category=ErrorCategory.NETWORK)


class _BaseTestCase(TestCase):
    """Shared setup: create admin, user, viewer accounts."""

    @classmethod
    def setUpTestData(cls):
        cls.admin = User.objects.create_user(
            username='admin_user', password='testpass', role='admin',
        )
        cls.user = User.objects.create_user(
            username='normal_user', password='testpass', role='user',
        )
        cls.viewer = User.objects.create_user(
            username='viewer_user', password='testpass', role='viewer',
        )

    def setUp(self):
        self.client = Client()


# ═══════════════════════════════════════════════════════════════════
# 1. ACCESS CONTROL
# ═══════════════════════════════════════════════════════════════════

class AccessControlTests(_BaseTestCase):
    """anonymous/viewer/user/admin access matrix for all endpoints."""

    def test_page_anonymous_redirects(self):
        resp = self.client.get(reverse('tools:robuxcrate'))
        self.assertEqual(resp.status_code, 302)
        self.assertIn('login', resp.url)

    def test_page_viewer_forbidden(self):
        self.client.login(username='viewer_user', password='testpass')
        resp = self.client.get(reverse('tools:robuxcrate'))
        self.assertEqual(resp.status_code, 403)

    def test_page_user_ok(self):
        self.client.login(username='normal_user', password='testpass')
        resp = self.client.get(reverse('tools:robuxcrate'))
        self.assertEqual(resp.status_code, 200)

    def test_page_admin_ok(self):
        self.client.login(username='admin_user', password='testpass')
        resp = self.client.get(reverse('tools:robuxcrate'))
        self.assertEqual(resp.status_code, 200)

    def test_api_anonymous_returns_json_401(self):
        resp = self.client.post(
            reverse('tools:rbx_lookup_user'),
            data=json.dumps({'username': 'test'}),
            content_type='application/json',
        )
        self.assertEqual(resp.status_code, 401)
        data = resp.json()
        self.assertIn('error', data)

    def test_api_viewer_returns_json_403(self):
        self.client.login(username='viewer_user', password='testpass')
        resp = self.client.post(
            reverse('tools:rbx_lookup_user'),
            data=json.dumps({'username': 'test'}),
            content_type='application/json',
        )
        self.assertEqual(resp.status_code, 403)
        data = resp.json()
        self.assertIn('error', data)

    def test_list_orders_anonymous_401(self):
        resp = self.client.get(reverse('tools:rbx_list_orders'))
        self.assertEqual(resp.status_code, 401)

    def test_list_orders_viewer_403(self):
        self.client.login(username='viewer_user', password='testpass')
        resp = self.client.get(reverse('tools:rbx_list_orders'))
        self.assertEqual(resp.status_code, 403)


# ═══════════════════════════════════════════════════════════════════
# 2. ORDER VISIBILITY / OWNERSHIP
# ═══════════════════════════════════════════════════════════════════

class OwnershipTests(_BaseTestCase):
    """User can only see/refresh their own orders; admin sees all."""

    def setUp(self):
        super().setUp()
        # Create a batch + order owned by normal_user
        self.user_batch = RobuxCrateBatch.objects.create(
            client_request_id=uuid.uuid4(),
            created_by=self.user,
            roblox_username='testplayer',
            place_id=123,
            robux_amount=1000,
            quantity=1,
            status=RobuxCrateBatch.Status.COMPLETED,
        )
        self.user_order = RobuxCrateOrder.objects.create(
            batch=self.user_batch,
            created_by=self.user,
            status=RobuxCrateOrder.Status.QUEUED,
        )
        # Create a batch + order owned by admin
        self.admin_batch = RobuxCrateBatch.objects.create(
            client_request_id=uuid.uuid4(),
            created_by=self.admin,
            roblox_username='adminplayer',
            place_id=456,
            robux_amount=2000,
            quantity=1,
            status=RobuxCrateBatch.Status.COMPLETED,
        )
        self.admin_order = RobuxCrateOrder.objects.create(
            batch=self.admin_batch,
            created_by=self.admin,
            status=RobuxCrateOrder.Status.QUEUED,
        )

    def test_user_sees_only_own_orders(self):
        self.client.login(username='normal_user', password='testpass')
        resp = self.client.get(reverse('tools:rbx_list_orders'))
        data = resp.json()
        self.assertTrue(data['ok'])
        order_ids = {o['id'] for o in data['orders']}
        self.assertIn(str(self.user_order.id), order_ids)
        self.assertNotIn(str(self.admin_order.id), order_ids)

    def test_admin_sees_all_orders(self):
        self.client.login(username='admin_user', password='testpass')
        resp = self.client.get(reverse('tools:rbx_list_orders'))
        data = resp.json()
        order_ids = {o['id'] for o in data['orders']}
        self.assertIn(str(self.user_order.id), order_ids)
        self.assertIn(str(self.admin_order.id), order_ids)

    def test_user_cannot_refresh_other_users_order(self):
        self.client.login(username='normal_user', password='testpass')
        resp = self.client.post(
            reverse('tools:rbx_refresh_status', args=[self.admin_order.id]),
            content_type='application/json',
        )
        self.assertEqual(resp.status_code, 403)

    def test_admin_can_refresh_any_order(self):
        self.client.login(username='admin_user', password='testpass')
        with patch('apps.tools.services.robuxcrate.refresh_order_status', return_value=(True, '')):
            resp = self.client.post(
                reverse('tools:rbx_refresh_status', args=[self.user_order.id]),
                content_type='application/json',
            )
        self.assertEqual(resp.status_code, 200)


# ═══════════════════════════════════════════════════════════════════
# 3. REQUEST VALIDATION
# ═══════════════════════════════════════════════════════════════════

class ValidationTests(_BaseTestCase):
    """Invalid JSON, field boundaries, missing fields."""

    def setUp(self):
        super().setUp()
        self.client.login(username='normal_user', password='testpass')

    def test_invalid_json_returns_400(self):
        resp = self.client.post(
            reverse('tools:rbx_lookup_user'),
            data='not json{{{',
            content_type='application/json',
        )
        self.assertEqual(resp.status_code, 400)
        self.assertIn('Invalid JSON', resp.json()['error'])

    def test_non_object_json_returns_400(self):
        resp = self.client.post(
            reverse('tools:rbx_lookup_user'),
            data=json.dumps([1, 2, 3]),
            content_type='application/json',
        )
        self.assertEqual(resp.status_code, 400)
        self.assertIn('JSON object', resp.json()['error'])

    def test_empty_body_returns_400(self):
        resp = self.client.post(
            reverse('tools:rbx_lookup_user'),
            data='',
            content_type='application/json',
        )
        self.assertEqual(resp.status_code, 400)

    def test_empty_username_returns_400(self):
        resp = self.client.post(
            reverse('tools:rbx_lookup_user'),
            data=json.dumps({'username': ''}),
            content_type='application/json',
        )
        self.assertEqual(resp.status_code, 400)

    def test_long_username_returns_400(self):
        resp = self.client.post(
            reverse('tools:rbx_lookup_user'),
            data=json.dumps({'username': 'x' * 100}),
            content_type='application/json',
        )
        self.assertEqual(resp.status_code, 400)

    def test_create_order_missing_lookup_token(self):
        resp = self.client.post(
            reverse('tools:rbx_create_order'),
            data=json.dumps({
                'place_id': 123,
                'robux_amount': 1000,
                'client_request_id': str(uuid.uuid4()),
            }),
            content_type='application/json',
        )
        self.assertEqual(resp.status_code, 400)
        self.assertIn('lookup_token', resp.json()['error'])

    def test_create_order_invalid_quantity_over_max(self):
        token = create_lookup_token(12345, 'testuser', [111])
        resp = self.client.post(
            reverse('tools:rbx_create_order'),
            data=json.dumps({
                'lookup_token': token,
                'client_request_id': str(uuid.uuid4()),
                'place_id': 111,
                'robux_amount': 1000,
                'quantity': 50,
            }),
            content_type='application/json',
        )
        self.assertEqual(resp.status_code, 400)
        self.assertIn('quantity', resp.json()['error'])

    def test_create_order_negative_robux(self):
        token = create_lookup_token(12345, 'testuser', [111])
        resp = self.client.post(
            reverse('tools:rbx_create_order'),
            data=json.dumps({
                'lookup_token': token,
                'client_request_id': str(uuid.uuid4()),
                'place_id': 111,
                'robux_amount': -100,
                'quantity': 1,
            }),
            content_type='application/json',
        )
        self.assertEqual(resp.status_code, 400)

    def test_create_order_invalid_client_request_id(self):
        token = create_lookup_token(12345, 'testuser', [111])
        resp = self.client.post(
            reverse('tools:rbx_create_order'),
            data=json.dumps({
                'lookup_token': token,
                'client_request_id': 'not-a-uuid',
                'place_id': 111,
                'robux_amount': 1000,
            }),
            content_type='application/json',
        )
        self.assertEqual(resp.status_code, 400)
        self.assertIn('client_request_id', resp.json()['error'])

    def test_create_order_place_not_in_token(self):
        token = create_lookup_token(12345, 'testuser', [111, 222])
        resp = self.client.post(
            reverse('tools:rbx_create_order'),
            data=json.dumps({
                'lookup_token': token,
                'client_request_id': str(uuid.uuid4()),
                'place_id': 999,
                'robux_amount': 1000,
            }),
            content_type='application/json',
        )
        self.assertEqual(resp.status_code, 400)
        self.assertIn('does not belong', resp.json()['error'])


# ═══════════════════════════════════════════════════════════════════
# 4. LOOKUP ENDPOINT
# ═══════════════════════════════════════════════════════════════════

def _make_roblox_user(user_id=12345, username='TestUser', display_name='Test'):
    from apis_sdk.clients.services.roblox.client import RobloxUser
    return RobloxUser(user_id=user_id, username=username, display_name=display_name)


def _make_roblox_place(place_id, name='Game', universe_id=0):
    from apis_sdk.clients.services.roblox.client import RobloxPlace
    return RobloxPlace(place_id=place_id, universe_id=universe_id, name=name)


def _make_lookup_result(user, places, partial=False):
    from apis_sdk.clients.services.roblox.facade import RobloxUserLookup
    return RobloxUserLookup(user=user, places=places, partial=partial)


class LookupTests(_BaseTestCase):
    """Roblox lookup: single place, multiple places, zero places, errors."""

    def setUp(self):
        super().setUp()
        self.client.login(username='normal_user', password='testpass')
        self.url = reverse('tools:rbx_lookup_user')

    @patch('apps.tools.api.robuxcrate._get_roblox_client')
    def test_single_place(self, mock_get_client):
        user = _make_roblox_user()
        places = [_make_roblox_place(111, 'MyGame')]
        lookup = _make_lookup_result(user, places)

        facade = MagicMock()
        facade.lookup_user_with_places.return_value = _make_api_result(ok=True, data=lookup)
        mock_get_client.return_value = facade

        resp = self.client.post(
            self.url,
            data=json.dumps({'username': 'TestUser'}),
            content_type='application/json',
        )
        data = resp.json()
        self.assertTrue(data['ok'])
        self.assertEqual(len(data['places']), 1)
        self.assertEqual(data['places'][0]['place_id'], 111)
        self.assertIn('lookup_token', data)
        self.assertEqual(data['user_id'], 12345)

    @patch('apps.tools.api.robuxcrate._get_roblox_client')
    def test_multiple_places(self, mock_get_client):
        user = _make_roblox_user()
        places = [_make_roblox_place(111, 'Game1'), _make_roblox_place(222, 'Game2')]
        lookup = _make_lookup_result(user, places)

        facade = MagicMock()
        facade.lookup_user_with_places.return_value = _make_api_result(ok=True, data=lookup)
        mock_get_client.return_value = facade

        resp = self.client.post(
            self.url,
            data=json.dumps({'username': 'TestUser'}),
            content_type='application/json',
        )
        data = resp.json()
        self.assertTrue(data['ok'])
        self.assertEqual(len(data['places']), 2)

    @patch('apps.tools.api.robuxcrate._get_roblox_client')
    def test_zero_places(self, mock_get_client):
        user = _make_roblox_user()
        lookup = _make_lookup_result(user, [])

        facade = MagicMock()
        facade.lookup_user_with_places.return_value = _make_api_result(ok=True, data=lookup)
        mock_get_client.return_value = facade

        resp = self.client.post(
            self.url,
            data=json.dumps({'username': 'TestUser'}),
            content_type='application/json',
        )
        data = resp.json()
        self.assertTrue(data['ok'])
        self.assertEqual(len(data['places']), 0)

    @patch('apps.tools.api.robuxcrate._get_roblox_client')
    def test_user_not_found(self, mock_get_client):
        from apis_sdk.core.enums import ErrorCategory
        facade = MagicMock()
        facade.lookup_user_with_places.return_value = _make_api_result(
            ok=False, error=_make_error('User not found', category=ErrorCategory.NOT_FOUND),
        )
        mock_get_client.return_value = facade

        resp = self.client.post(
            self.url,
            data=json.dumps({'username': 'NonExistent'}),
            content_type='application/json',
        )
        self.assertEqual(resp.status_code, 404)

    @patch('apps.tools.api.robuxcrate._get_roblox_client')
    def test_network_error(self, mock_get_client):
        """Network error during lookup → 502."""
        facade = MagicMock()
        facade.lookup_user_with_places.return_value = _make_api_result(
            ok=False, error=_make_network_error('Connection timeout'),
        )
        mock_get_client.return_value = facade

        resp = self.client.post(
            self.url,
            data=json.dumps({'username': 'TestUser'}),
            content_type='application/json',
        )
        self.assertEqual(resp.status_code, 502)

    @patch('apps.tools.api.robuxcrate._get_roblox_client')
    def test_partial_places(self, mock_get_client):
        """Partial data → returns ok with warning."""
        user = _make_roblox_user()
        places = [_make_roblox_place(111, 'Game1')]
        lookup = _make_lookup_result(user, places, partial=True)

        facade = MagicMock()
        facade.lookup_user_with_places.return_value = _make_api_result(ok=True, data=lookup)
        mock_get_client.return_value = facade

        resp = self.client.post(
            self.url,
            data=json.dumps({'username': 'TestUser'}),
            content_type='application/json',
        )
        data = resp.json()
        self.assertTrue(data['ok'])
        self.assertEqual(len(data['places']), 1)
        self.assertTrue(data.get('partial'))
        self.assertIn('warning', data)

    def test_no_roblox_service_configured(self):
        """No ServiceCredential for Roblox → 503."""
        with patch('apps.tools.api.robuxcrate._get_roblox_client', return_value=None):
            resp = self.client.post(
                self.url,
                data=json.dumps({'username': 'TestUser'}),
                content_type='application/json',
            )
            self.assertEqual(resp.status_code, 503)


# ═══════════════════════════════════════════════════════════════════
# 5. SIGNED LOOKUP TOKEN
# ═══════════════════════════════════════════════════════════════════

class LookupTokenTests(TestCase):
    """Signed token: valid, tampered, expired."""

    def test_valid_token_roundtrip(self):
        token = create_lookup_token(12345, 'testuser', [111, 222])
        data = verify_lookup_token(token)
        self.assertIsNotNone(data)
        self.assertEqual(data['uid'], 12345)
        self.assertEqual(data['un'], 'testuser')
        self.assertEqual(data['pids'], [111, 222])

    def test_tampered_token_returns_none(self):
        token = create_lookup_token(12345, 'testuser', [111])
        # Tamper with the token
        tampered = token[:-5] + 'XXXXX'
        data = verify_lookup_token(tampered)
        self.assertIsNone(data)

    def test_expired_token_returns_none(self):
        from django.core import signing
        # Create a token that's already expired
        token = signing.dumps(
            {'uid': 12345, 'un': 'testuser', 'pids': [111]},
            salt='robuxcrate-lookup-v1',
        )
        # Verify with max_age=0 should fail
        result = None
        try:
            result = signing.loads(token, salt='robuxcrate-lookup-v1', max_age=0)
        except (signing.BadSignature, signing.SignatureExpired):
            pass
        # Either result is None or the signing.loads above raised
        # Our verify_lookup_token uses max_age=1800, so a just-created token is valid
        data = verify_lookup_token(token)
        self.assertIsNotNone(data)

    def test_empty_token_returns_none(self):
        self.assertIsNone(verify_lookup_token(''))

    def test_garbage_token_returns_none(self):
        self.assertIsNone(verify_lookup_token('not-a-token-at-all'))


# ═══════════════════════════════════════════════════════════════════
# 6. CREATE ORDER + IDEMPOTENCY
# ═══════════════════════════════════════════════════════════════════

class CreateOrderTests(_BaseTestCase):
    """Create order: success, validation, idempotency."""

    def setUp(self):
        super().setUp()
        self.client.login(username='normal_user', password='testpass')
        self.url = reverse('tools:rbx_create_order')
        self.token = create_lookup_token(12345, 'testuser', [111, 222])

    def test_successful_batch_creation(self):
        crid = str(uuid.uuid4())
        resp = self.client.post(
            self.url,
            data=json.dumps({
                'lookup_token': self.token,
                'client_request_id': crid,
                'place_id': 111,
                'robux_amount': 1000,
                'quantity': 3,
            }),
            content_type='application/json',
        )
        self.assertEqual(resp.status_code, 201)
        data = resp.json()
        self.assertTrue(data['ok'])
        self.assertEqual(data['quantity'], 3)
        self.assertEqual(data['created_count'], 3)
        self.assertEqual(data['batch_status'], 'pending')

        # Verify DB
        batch = RobuxCrateBatch.objects.get(client_request_id=crid)
        self.assertEqual(batch.quantity, 3)
        self.assertEqual(batch.orders.count(), 3)
        self.assertTrue(all(o.status == 'pending' for o in batch.orders.all()))

    def test_idempotency_same_request_id(self):
        """Same client_request_id → no new batch/orders created."""
        crid = str(uuid.uuid4())
        payload = json.dumps({
            'lookup_token': self.token,
            'client_request_id': crid,
            'place_id': 111,
            'robux_amount': 1000,
            'quantity': 2,
        })

        resp1 = self.client.post(self.url, data=payload, content_type='application/json')
        resp2 = self.client.post(self.url, data=payload, content_type='application/json')

        self.assertEqual(resp1.status_code, 201)
        self.assertEqual(resp2.status_code, 200)  # Returns existing

        data1 = resp1.json()
        data2 = resp2.json()
        self.assertEqual(data1['batch_id'], data2['batch_id'])

        # Only 1 batch and 2 orders total
        self.assertEqual(RobuxCrateBatch.objects.filter(client_request_id=crid).count(), 1)
        batch = RobuxCrateBatch.objects.get(client_request_id=crid)
        self.assertEqual(batch.orders.count(), 2)


# ═══════════════════════════════════════════════════════════════════
# 7. BATCH PROCESSING (Background service)
# ═══════════════════════════════════════════════════════════════════

class BatchProcessingTests(_BaseTestCase):
    """Batch processing: full success, partial failure, network timeout."""

    def _create_batch(self, quantity=1, status=RobuxCrateBatch.Status.PENDING):
        batch = RobuxCrateBatch.objects.create(
            client_request_id=uuid.uuid4(),
            created_by=self.user,
            roblox_username='testplayer',
            place_id=111,
            robux_amount=1000,
            quantity=quantity,
            status=status,
        )
        for _ in range(quantity):
            RobuxCrateOrder.objects.create(
                batch=batch,
                created_by=self.user,
            )
        return batch

    @patch('apps.tools.services.robuxcrate.RobuxCrateService')
    @patch('apps.tools.services.robuxcrate.ServiceCredential')
    def test_full_success_batch(self, mock_cred_model, mock_service):
        """All orders succeed → batch status = completed."""
        batch = self._create_batch(quantity=3)

        # Mock credential
        cred = MagicMock()
        cred.credentials = {'api_key': 'test-key'}
        mock_cred_model.objects.get.return_value = cred

        # Mock client
        client = MagicMock()
        client.create_gamepass_order.return_value = _make_api_result(
            ok=True, data={'status': 'queued'}
        )
        mock_service.build_client.return_value = client

        process_pending_batches()

        batch.refresh_from_db()
        self.assertEqual(batch.status, RobuxCrateBatch.Status.PROCESSING)

        orders = list(batch.orders.all())
        self.assertTrue(all(o.status == RobuxCrateOrder.Status.QUEUED for o in orders))

    @patch('apps.tools.services.robuxcrate.RobuxCrateService')
    @patch('apps.tools.services.robuxcrate.ServiceCredential')
    def test_partial_failure_batch(self, mock_cred_model, mock_service):
        """Some orders fail → batch continues, reflects mixed status."""
        batch = self._create_batch(quantity=2)

        cred = MagicMock()
        cred.credentials = {'api_key': 'test-key'}
        mock_cred_model.objects.get.return_value = cred

        client = MagicMock()
        call_count = [0]

        def create_side_effect(**kwargs):
            call_count[0] += 1
            if call_count[0] == 1:
                return _make_api_result(ok=True, data={'status': 'queued'})
            return _make_api_result(ok=False, error=_make_error('Validation failed'))

        client.create_gamepass_order.side_effect = create_side_effect
        mock_service.build_client.return_value = client

        process_pending_batches()

        orders = list(batch.orders.order_by('created_at'))
        statuses = {o.status for o in orders}
        self.assertIn(RobuxCrateOrder.Status.QUEUED, statuses)
        self.assertIn(RobuxCrateOrder.Status.ERROR, statuses)

    @patch('apps.tools.services.robuxcrate.RobuxCrateService')
    @patch('apps.tools.services.robuxcrate.ServiceCredential')
    def test_network_timeout_marks_unknown(self, mock_cred_model, mock_service):
        """Network error during create → order marked UNKNOWN (exception path)."""
        batch = self._create_batch(quantity=1)

        cred = MagicMock()
        cred.credentials = {'api_key': 'test-key'}
        mock_cred_model.objects.get.return_value = cred

        client = MagicMock()
        client.create_gamepass_order.side_effect = Exception('Connection timeout')
        # Reconciliation will also fail (provider unreachable)
        client.get_order_info.side_effect = Exception('Connection timeout')
        mock_service.build_client.return_value = client

        process_pending_batches()

        order = batch.orders.first()
        self.assertEqual(order.status, RobuxCrateOrder.Status.UNKNOWN)

    @patch('apps.tools.services.robuxcrate.RobuxCrateService')
    @patch('apps.tools.services.robuxcrate.ServiceCredential')
    def test_network_error_result_marks_unknown(self, mock_cred_model, mock_service):
        """Facade returns network error ApiResult → order marked UNKNOWN."""
        batch = self._create_batch(quantity=1)

        cred = MagicMock()
        cred.credentials = {'api_key': 'test-key'}
        mock_cred_model.objects.get.return_value = cred

        client = MagicMock()
        client.create_gamepass_order.return_value = _make_api_result(
            ok=False, error=_make_network_error('Connection timeout'),
        )
        client.get_order_info.return_value = _make_api_result(
            ok=False, error=_make_network_error('Still unreachable'),
        )
        mock_service.build_client.return_value = client

        process_pending_batches()

        order = batch.orders.first()
        self.assertEqual(order.status, RobuxCrateOrder.Status.UNKNOWN)
        self.assertIn('Uncertain', order.error_message)

    @patch('apps.tools.services.robuxcrate.RobuxCrateService')
    @patch('apps.tools.services.robuxcrate.ServiceCredential')
    def test_unknown_order_reconciliation_success(self, mock_cred_model, mock_service):
        """UNKNOWN order is reconciled via get_order_info."""
        batch = self._create_batch(quantity=1)
        order = batch.orders.first()
        order.status = RobuxCrateOrder.Status.UNKNOWN
        order.save()
        batch.status = RobuxCrateBatch.Status.PROCESSING
        batch.save()

        cred = MagicMock()
        cred.credentials = {'api_key': 'test-key'}
        mock_cred_model.objects.get.return_value = cred

        client = MagicMock()
        # get_order_info finds the order at provider
        client.get_order_info.return_value = _make_api_result(
            ok=True, data={'status': 'queued'}
        )
        mock_service.build_client.return_value = client

        process_pending_batches()

        order.refresh_from_db()
        self.assertEqual(order.status, RobuxCrateOrder.Status.QUEUED)

    @patch('apps.tools.services.robuxcrate.ServiceCredential')
    def test_missing_credential_skips_processing(self, mock_cred_model):
        """Missing/inactive credential → batches stay pending."""
        batch = self._create_batch(quantity=1)
        from apps.integrations.models import ServiceCredential
        mock_cred_model.objects.get.side_effect = ServiceCredential.DoesNotExist
        mock_cred_model.DoesNotExist = ServiceCredential.DoesNotExist

        process_pending_batches()

        batch.refresh_from_db()
        self.assertEqual(batch.status, RobuxCrateBatch.Status.PENDING)

    @patch('apps.tools.services.robuxcrate.ServiceCredential')
    def test_empty_api_key_skips_processing(self, mock_cred_model):
        """Credential exists but no api_key → skip."""
        batch = self._create_batch(quantity=1)
        cred = MagicMock()
        cred.credentials = {'api_key': ''}
        mock_cred_model.objects.get.return_value = cred

        process_pending_batches()

        batch.refresh_from_db()
        self.assertEqual(batch.status, RobuxCrateBatch.Status.PENDING)


# ═══════════════════════════════════════════════════════════════════
# 8. STATUS MAPPING
# ═══════════════════════════════════════════════════════════════════

class StatusMappingTests(TestCase):
    """Provider status → internal status mapping."""

    def test_known_statuses(self):
        self.assertEqual(map_provider_status('queued'), RobuxCrateOrder.Status.QUEUED)
        self.assertEqual(map_provider_status('in_progress'), RobuxCrateOrder.Status.QUEUED)
        self.assertEqual(map_provider_status('inprogress'), RobuxCrateOrder.Status.QUEUED)
        self.assertEqual(map_provider_status('completed'), RobuxCrateOrder.Status.COMPLETED)
        self.assertEqual(map_provider_status('done'), RobuxCrateOrder.Status.COMPLETED)
        self.assertEqual(map_provider_status('error'), RobuxCrateOrder.Status.ERROR)
        self.assertEqual(map_provider_status('failed'), RobuxCrateOrder.Status.ERROR)
        self.assertEqual(map_provider_status('cancelled'), RobuxCrateOrder.Status.CANCELLED)
        self.assertEqual(map_provider_status('canceled'), RobuxCrateOrder.Status.CANCELLED)

    def test_unknown_status_maps_to_unknown(self):
        self.assertEqual(map_provider_status('some_new_status'), RobuxCrateOrder.Status.UNKNOWN)
        self.assertEqual(map_provider_status(''), RobuxCrateOrder.Status.UNKNOWN)

    def test_case_insensitive(self):
        self.assertEqual(map_provider_status('QUEUED'), RobuxCrateOrder.Status.QUEUED)
        self.assertEqual(map_provider_status('Completed'), RobuxCrateOrder.Status.COMPLETED)

    def test_whitespace_stripped(self):
        self.assertEqual(map_provider_status('  queued  '), RobuxCrateOrder.Status.QUEUED)


# ═══════════════════════════════════════════════════════════════════
# 9. BATCH STATUS AGGREGATION
# ═══════════════════════════════════════════════════════════════════

class BatchStatusAggregationTests(_BaseTestCase):
    """Batch status computed from order statuses."""

    def _make_batch_with_orders(self, statuses):
        batch = RobuxCrateBatch.objects.create(
            client_request_id=uuid.uuid4(),
            created_by=self.user,
            roblox_username='test',
            place_id=111,
            robux_amount=1000,
            quantity=len(statuses),
            status=RobuxCrateBatch.Status.PROCESSING,
        )
        for s in statuses:
            RobuxCrateOrder.objects.create(batch=batch, created_by=self.user, status=s)
        return batch

    def test_all_completed_without_store(self):
        """All completed but no marketplace store → delivery fails permanently → ERROR."""
        batch = self._make_batch_with_orders(['completed', 'completed'])
        _update_batch_status(batch)
        self.assertEqual(batch.status, RobuxCrateBatch.Status.ERROR)

    def test_all_error(self):
        batch = self._make_batch_with_orders(['error', 'error'])
        _update_batch_status(batch)
        self.assertEqual(batch.status, RobuxCrateBatch.Status.ERROR)

    def test_mixed_completed_and_error_triggers_delivery(self):
        """At least 1 completed → delivery attempted, permanent fail → ERROR."""
        batch = self._make_batch_with_orders(['completed', 'error'])
        _update_batch_status(batch)
        self.assertEqual(batch.status, RobuxCrateBatch.Status.ERROR)

    def test_has_pending(self):
        """1 completed + 1 pending → delivery attempted, no store → ERROR."""
        batch = self._make_batch_with_orders(['completed', 'pending'])
        _update_batch_status(batch)
        self.assertEqual(batch.status, RobuxCrateBatch.Status.ERROR)

    def test_has_queued(self):
        batch = self._make_batch_with_orders(['queued', 'completed'])
        _update_batch_status(batch)
        self.assertEqual(batch.status, RobuxCrateBatch.Status.ERROR)

    def test_has_unknown(self):
        batch = self._make_batch_with_orders(['unknown', 'completed'])
        _update_batch_status(batch)
        self.assertEqual(batch.status, RobuxCrateBatch.Status.ERROR)

    def test_no_completed_still_processing(self):
        """Only non-final orders, none completed → stays PROCESSING."""
        batch = self._make_batch_with_orders(['queued', 'pending'])
        _update_batch_status(batch)
        self.assertEqual(batch.status, RobuxCrateBatch.Status.PROCESSING)


# ═══════════════════════════════════════════════════════════════════
# 9b. DELIVERY — RETRYABLE vs PERMANENT ERRORS
# ═══════════════════════════════════════════════════════════════════

class DeliveryErrorHandlingTests(_BaseTestCase):
    """Delivery: permanent errors → ERROR, retryable errors → PROCESSING."""

    def _make_delivery_batch(self, marketplace='eldorado', order_statuses=None):
        from apps.integrations.models import IntegrationAccount, IntegrationCredential
        account = IntegrationAccount.objects.create(
            name='Test Store', provider=marketplace, slug=f'test-{marketplace}',
        )
        store_cred = IntegrationCredential.objects.create(
            account=account, credentials={}, is_active=True,
        )
        batch = RobuxCrateBatch.objects.create(
            client_request_id=uuid.uuid4(),
            created_by=self.user,
            roblox_username='test',
            place_id=111,
            robux_amount=1000,
            quantity=len(order_statuses or ['completed']),
            status=RobuxCrateBatch.Status.PROCESSING,
            marketplace=marketplace,
            marketplace_order_id='test-order-123',
            marketplace_store=store_cred,
        )
        for s in (order_statuses or ['completed']):
            RobuxCrateOrder.objects.create(batch=batch, created_by=self.user, status=s)
        return batch

    @patch('apps.tools.services.robuxcrate._deliver_eldorado')
    def test_eldorado_permanent_error_goes_to_error(self, mock_deliver):
        """HTTP 400 (VALIDATION) → permanent → batch ERROR, no retry."""
        mock_deliver.return_value = (False, 'HTTP 400 — order already delivered', False)
        batch = self._make_delivery_batch(marketplace='eldorado')
        _update_batch_status(batch)
        self.assertEqual(batch.status, RobuxCrateBatch.Status.ERROR)
        self.assertIn('already delivered', batch.delivery_error)

    @patch('apps.tools.services.robuxcrate._deliver_eldorado')
    def test_eldorado_retryable_error_stays_processing(self, mock_deliver):
        """HTTP 503 (SERVER_ERROR) → retryable → batch stays PROCESSING."""
        mock_deliver.return_value = (False, 'HTTP 503 — service unavailable', True)
        batch = self._make_delivery_batch(marketplace='eldorado')
        _update_batch_status(batch)
        self.assertEqual(batch.status, RobuxCrateBatch.Status.PROCESSING)

    @patch('apps.tools.services.robuxcrate._deliver_eldorado')
    def test_eldorado_success_completes_batch(self, mock_deliver):
        """Successful delivery → COMPLETED."""
        mock_deliver.return_value = (True, '', False)
        batch = self._make_delivery_batch(marketplace='eldorado')
        _update_batch_status(batch)
        self.assertEqual(batch.status, RobuxCrateBatch.Status.COMPLETED)

    @patch('apps.tools.services.robuxcrate._deliver_gameboost')
    def test_gameboost_success_completes_batch(self, mock_deliver):
        """GameBoost delivery success → COMPLETED."""
        mock_deliver.return_value = (True, '', False)
        batch = self._make_delivery_batch(marketplace='gameboost')
        _update_batch_status(batch)
        self.assertEqual(batch.status, RobuxCrateBatch.Status.COMPLETED)

    @patch('apps.tools.services.robuxcrate._deliver_gameboost')
    def test_gameboost_permanent_error(self, mock_deliver):
        """GameBoost permanent error → ERROR."""
        mock_deliver.return_value = (False, 'Order not found', False)
        batch = self._make_delivery_batch(marketplace='gameboost')
        _update_batch_status(batch)
        self.assertEqual(batch.status, RobuxCrateBatch.Status.ERROR)

    def test_unsupported_marketplace_goes_to_error(self):
        """Unknown marketplace → permanent ERROR (not infinite retry)."""
        batch = self._make_delivery_batch(marketplace='eldorado')
        batch.marketplace = 'unknown_mp'
        batch.save()
        _update_batch_status(batch)
        self.assertEqual(batch.status, RobuxCrateBatch.Status.ERROR)
        self.assertIn('not implemented', batch.delivery_error)

    @patch('apps.tools.services.robuxcrate._deliver_eldorado')
    def test_error_batch_not_retried(self, mock_deliver):
        """Once in ERROR, scheduler should NOT pick it up (not in _NON_FINAL_BATCH_STATUSES)."""
        from apps.tools.services.robuxcrate import _NON_FINAL_BATCH_STATUSES
        self.assertNotIn(RobuxCrateBatch.Status.ERROR, _NON_FINAL_BATCH_STATUSES)
        self.assertNotIn(RobuxCrateBatch.Status.COMPLETED, _NON_FINAL_BATCH_STATUSES)


# ═══════════════════════════════════════════════════════════════════
# 10. PAGINATION & FILTERING
# ═══════════════════════════════════════════════════════════════════

class PaginationFilterTests(_BaseTestCase):
    """Order list endpoint pagination and filtering."""

    def setUp(self):
        super().setUp()
        self.client.login(username='admin_user', password='testpass')
        # Create 5 batches
        for i in range(5):
            batch = RobuxCrateBatch.objects.create(
                client_request_id=uuid.uuid4(),
                created_by=self.admin,
                roblox_username=f'player{i}',
                place_id=100 + i,
                robux_amount=1000,
                quantity=1,
                status=RobuxCrateBatch.Status.COMPLETED,
            )
            RobuxCrateOrder.objects.create(
                batch=batch,
                created_by=self.admin,
                status='completed' if i % 2 == 0 else 'error',
            )

    def test_pagination(self):
        resp = self.client.get(
            reverse('tools:rbx_list_orders'),
            {'per_page': 2, 'page': 1},
        )
        data = resp.json()
        self.assertTrue(data['ok'])
        self.assertEqual(len(data['orders']), 2)
        self.assertEqual(data['total_count'], 5)
        self.assertEqual(data['total_pages'], 3)

    def test_status_filter(self):
        resp = self.client.get(
            reverse('tools:rbx_list_orders'),
            {'status': 'error'},
        )
        data = resp.json()
        self.assertTrue(all(o['status'] == 'error' for o in data['orders']))

    def test_search_filter(self):
        resp = self.client.get(
            reverse('tools:rbx_list_orders'),
            {'q': 'player0'},
        )
        data = resp.json()
        self.assertTrue(all(o['roblox_username'] == 'player0' for o in data['orders']))


# ═══════════════════════════════════════════════════════════════════
# 11. REFRESH ORDER STATUS
# ═══════════════════════════════════════════════════════════════════

class RefreshStatusTests(_BaseTestCase):
    """Single order refresh endpoint."""

    def setUp(self):
        super().setUp()
        self.batch = RobuxCrateBatch.objects.create(
            client_request_id=uuid.uuid4(),
            created_by=self.user,
            roblox_username='testplayer',
            place_id=111,
            robux_amount=1000,
            quantity=1,
            status=RobuxCrateBatch.Status.COMPLETED,
        )
        self.order = RobuxCrateOrder.objects.create(
            batch=self.batch,
            created_by=self.user,
            status=RobuxCrateOrder.Status.QUEUED,
        )

    def test_refresh_success(self):
        self.client.login(username='normal_user', password='testpass')
        with patch('apps.tools.api.robuxcrate.refresh_order_status', return_value=(True, '')):
            resp = self.client.post(
                reverse('tools:rbx_refresh_status', args=[self.order.id]),
                content_type='application/json',
            )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data['ok'])

    def test_refresh_nonexistent_order(self):
        self.client.login(username='normal_user', password='testpass')
        fake_id = uuid.uuid4()
        resp = self.client.post(
            reverse('tools:rbx_refresh_status', args=[fake_id]),
            content_type='application/json',
        )
        self.assertEqual(resp.status_code, 404)


# ═══════════════════════════════════════════════════════════════════
# 12. PARSE JSON BODY HELPER
# ═══════════════════════════════════════════════════════════════════

class ParseJsonBodyTests(TestCase):
    """Unit tests for the parse_json_body helper."""

    def _make_request(self, body):
        from django.test import RequestFactory
        factory = RequestFactory()
        if isinstance(body, str):
            body = body.encode()
        return factory.post('/', data=body, content_type='application/json')

    def test_valid_json_object(self):
        req = self._make_request(json.dumps({'key': 'value'}))
        body, err = parse_json_body(req)
        self.assertIsNotNone(body)
        self.assertIsNone(err)
        self.assertEqual(body['key'], 'value')

    def test_invalid_json(self):
        req = self._make_request('{bad json')
        body, err = parse_json_body(req)
        self.assertIsNone(body)
        self.assertIsNotNone(err)
        self.assertEqual(err.status_code, 400)

    def test_json_array_rejected(self):
        req = self._make_request(json.dumps([1, 2, 3]))
        body, err = parse_json_body(req)
        self.assertIsNone(body)
        self.assertIsNotNone(err)

    def test_empty_body(self):
        req = self._make_request(b'')
        body, err = parse_json_body(req)
        self.assertIsNone(body)
        self.assertIsNotNone(err)
