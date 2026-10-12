import hashlib
import hmac
from types import SimpleNamespace
from unittest.mock import Mock, patch

from django.test import RequestFactory, SimpleTestCase

from apps.integrations.api.u7buy_webhook import u7buy_webhook
from apps.integrations.providers.u7buy import U7BuyClient, webhook_signature_is_valid


class U7BuySignatureTests(SimpleTestCase):
    def test_accepts_documented_app_id_comma_raw_body_hmac(self):
        body = b'{"event":"new_order_received","data":{"orderId":"123"}}'
        expected = hmac.new(b"secret", b"app-1," + body, hashlib.sha256).hexdigest()
        self.assertTrue(
            webhook_signature_is_valid(
                raw_body=body,
                supplied_signature=expected,
                app_id="app-1",
                app_secret="secret",
            )
        )

    def test_rejects_signature_for_modified_body(self):
        signature = hmac.new(b"secret", b"app-1,{}", hashlib.sha256).hexdigest()
        self.assertFalse(
            webhook_signature_is_valid(
                raw_body=b'{"event":"new_order_received"}',
                supplied_signature=signature,
                app_id="app-1",
                app_secret="secret",
            )
        )


class U7BuyCreateRecoveryTests(SimpleTestCase):
    def test_recovers_unique_offer_id_when_create_returns_boolean(self):
        client = U7BuyClient("id", "secret")
        with patch.object(U7BuyClient, "_request", return_value={"items": [True]}), patch.object(
            U7BuyClient,
            "_recover_exact_offer_id",
            return_value="offer-123",
        ) as recover:
            result = client.create_offer({"offerName": "unique offer"})
        self.assertEqual(result, {"offerId": "offer-123"})
        recover.assert_called_once_with("unique offer")

    def test_refuses_unresolved_create_outcome(self):
        client = U7BuyClient("id", "secret")
        with patch.object(U7BuyClient, "_request", return_value={"items": [True]}), patch.object(
            U7BuyClient,
            "_recover_exact_offer_id",
            return_value="",
        ):
            with self.assertRaisesRegex(RuntimeError, "could not be verified"):
                client.create_offer({"offerName": "unique offer"})

    def test_delist_off_sales_before_deleting(self):
        client = U7BuyClient("id", "secret")
        with patch.object(U7BuyClient, "_request", return_value={}) as request:
            client.delete_offer("offer-123")
        self.assertEqual(request.call_args_list[0].args[:2], ("PUT", "/open-api/offer_common/status"))
        self.assertEqual(request.call_args_list[1].args[:2], ("DELETE", "/open-api/offer_common"))

    def test_updates_through_documented_game_service_endpoint(self):
        client = U7BuyClient("id", "secret")
        with patch.object(U7BuyClient, "_request", return_value={}) as request:
            client.update_offer("offer-123", {"offerName": "new title"})
        self.assertEqual(request.call_args.args[:2], ("PUT", "/open-api/game_service_offer/v2"))
        self.assertEqual(request.call_args.kwargs["payload"]["offerId"], "offer-123")


class U7BuyWebhookEndpointTests(SimpleTestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.account = SimpleNamespace(
            id=7,
            pk=7,
            slug="u7buy-main",
            credential=SimpleNamespace(credentials={"app_id": "app-1", "app_secret": "secret"}),
        )

    def _headers(self, body: bytes) -> dict:
        return {
            "HTTP_X_U7BUY_SIGNATURE": hmac.new(b"secret", b"app-1," + body, hashlib.sha256).hexdigest(),
        }

    def test_queues_signed_order_without_trusting_it_as_delivery_data(self):
        body = b'{"event":"new_order_received","data":{"orderId":"u7-order-1"}}'
        request = self.factory.post("/integrations/webhooks/u7buy/u7buy-main/", data=body, content_type="application/json", **self._headers(body))
        with patch("apps.integrations.api.u7buy_webhook.get_object_or_404", return_value=self.account), patch(
            "apps.integrations.api.u7buy_webhook.U7BuyWebhookEvent.objects.get_or_create",
            return_value=(Mock(integration_account_id=7), True),
        ) as create:
            response = u7buy_webhook(request, self.account.slug)
        self.assertEqual(response.status_code, 200)
        self.assertJSONEqual(response.content, {"status": "OK"})
        self.assertEqual(create.call_args.kwargs["defaults"]["external_order_id"], "u7-order-1")

    def test_rejects_invalid_signature_before_creating_event(self):
        request = self.factory.post(
            "/integrations/webhooks/u7buy/u7buy-main/",
            data=b'{"event":"new_order_received","data":{"orderId":"u7-order-1"}}',
            content_type="application/json",
            HTTP_X_U7BUY_SIGNATURE="wrong",
        )
        with patch("apps.integrations.api.u7buy_webhook.get_object_or_404", return_value=self.account), patch(
            "apps.integrations.api.u7buy_webhook.U7BuyWebhookEvent.objects.get_or_create"
        ) as create:
            response = u7buy_webhook(request, self.account.slug)
        self.assertEqual(response.status_code, 401)
        create.assert_not_called()
