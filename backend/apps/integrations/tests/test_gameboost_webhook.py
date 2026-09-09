import hashlib
import hmac
from types import SimpleNamespace
from unittest.mock import Mock, patch

from django.test import RequestFactory, SimpleTestCase

from apps.integrations.api.gameboost_webhook import (
    gameboost_purchase_webhook,
    signature_is_valid,
)


class GameBoostWebhookSignatureTests(SimpleTestCase):
    def test_accepts_exact_raw_body_hmac(self):
        body = b'{"event":"account.order.purchased"}'
        secret = 'test-signing-secret'
        signature = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()

        self.assertTrue(
            signature_is_valid(
                raw_body=body,
                supplied_signature=signature,
                secret=secret,
            )
        )

    def test_rejects_signature_for_modified_raw_body(self):
        secret = 'test-signing-secret'
        signature = hmac.new(secret.encode(), b'{"event":"a"}', hashlib.sha256).hexdigest()

        self.assertFalse(
            signature_is_valid(
                raw_body=b'{"event":"b"}',
                supplied_signature=signature,
                secret=secret,
            )
        )


class GameBoostWebhookEndpointTests(SimpleTestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.account = SimpleNamespace(
            id=42,
            slug='gameboost-test-store',
            credential=SimpleNamespace(
                credentials={
                    'api_key': 'test-api-key',
                    'webhook_secret': 'test-signing-secret',
                },
            ),
        )
        self.secret = 'test-signing-secret'

    def _signature(self, body: bytes) -> str:
        return hmac.new(self.secret.encode(), body, hashlib.sha256).hexdigest()

    def test_rejects_an_invalid_signature_without_storing_an_event(self):
        request = self.factory.post(
            '/integrations/webhooks/gameboost/gameboost-test-store/',
            data=b'{"event":"account.order.purchased"}',
            content_type='application/json',
            HTTP_X_GAMEBOOST_SIGNATURE='bad-signature',
            HTTP_X_GAMEBOOST_EVENT_ID='test-event-invalid',
            HTTP_X_GAMEBOOST_TOPIC='account.order.purchased',
        )
        with patch(
            'apps.integrations.api.gameboost_webhook.get_object_or_404',
            return_value=self.account,
        ), patch(
            'apps.integrations.api.gameboost_webhook.GameBoostWebhookEvent.objects.get_or_create',
        ) as create:
            response = gameboost_purchase_webhook(request, self.account.slug)

        self.assertEqual(response.status_code, 401)
        create.assert_not_called()

    def test_stores_one_signed_purchase_event_and_acknowledges_redelivery(self):
        body = b'{"event":"account.order.purchased"}'
        headers = {
            'HTTP_X_GAMEBOOST_SIGNATURE': self._signature(body),
            'HTTP_X_GAMEBOOST_EVENT_ID': 'test-event-duplicate',
            'HTTP_X_GAMEBOOST_TOPIC': 'account.order.purchased',
        }

        first_request = self.factory.post('/integrations/webhooks/gameboost/gameboost-test-store/', data=body, content_type='application/json', **headers)
        second_request = self.factory.post('/integrations/webhooks/gameboost/gameboost-test-store/', data=body, content_type='application/json', **headers)
        duplicate_event = Mock(integration_account_id=self.account.id)
        with patch(
            'apps.integrations.api.gameboost_webhook.get_object_or_404',
            return_value=self.account,
        ), patch(
            'apps.integrations.api.gameboost_webhook.GameBoostWebhookEvent.objects.get_or_create',
            side_effect=[(Mock(), True), (duplicate_event, False)],
        ) as create:
            first = gameboost_purchase_webhook(first_request, self.account.slug)
            second = gameboost_purchase_webhook(second_request, self.account.slug)

        self.assertEqual(first.status_code, 202)
        self.assertEqual(second.status_code, 202)
        self.assertJSONEqual(first.content, {'accepted': True, 'duplicate': False})
        self.assertJSONEqual(second.content, {'accepted': True, 'duplicate': True})
        self.assertEqual(create.call_count, 2)
