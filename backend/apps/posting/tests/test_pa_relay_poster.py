from unittest.mock import Mock, patch

from django.test import SimpleTestCase, override_settings

from apps.posting.services.stock.consumer import _pa_legacy_relay_disabled
from apps.posting.services.stock.pa_relay_poster import (
    PARelayPoster,
    _format_relay_error,
)


class PARelayPosterConfigurationTests(SimpleTestCase):
    @patch("apps.posting.services.stock.pa_relay_poster.requests.post")
    def test_post_batch_uses_configured_relay_url_secret_and_timeout(self, post):
        response = Mock()
        response.json.return_value = {"ok": True, "offerId": "12345678"}
        post.return_value = response
        poster = PARelayPoster(
            relay_url="http://relay.example.test:3001/",
            relay_secret="store-specific-secret",
            timeout=17,
        )

        result = poster.post_batch(
            "access-token",
            "csgosmurfkings",
            [{"serverId": 5205, "title": "Configured relay test"}],
        )

        self.assertEqual(result.successful, {0: "12345678"})
        self.assertEqual(result.failed, {})
        post.assert_called_once_with(
            "http://relay.example.test:3001/pa-post-offer",
            json={
                "token": "access-token",
                "cookie": "access-token",
                "store": "csgosmurfkings",
                "payload": {"serverId": 5205, "title": "Configured relay test"},
            },
            headers={
                "Content-Type": "application/json",
                "X-Relay-Secret": "store-specific-secret",
            },
            timeout=17,
        )


class FormatRelayErrorTests(SimpleTestCase):
    def test_empty_405_preserves_status_not_flattened(self):
        # The obsolete legacy endpoint returns an empty 405 body.
        msg = _format_relay_error({}, 405)
        self.assertIn("upstream_status=405", msg)
        self.assertIn("empty upstream response body", msg)

    def test_preserves_upstream_status_request_id_and_detail(self):
        msg = _format_relay_error(
            {"status": 405, "requestId": "req-abc", "error": "Method Not Allowed"},
            200,
        )
        self.assertIn("upstream_status=405", msg)
        self.assertIn("request_id=req-abc", msg)
        self.assertIn("Method Not Allowed", msg)


class PostOneErrorCaptureTests(SimpleTestCase):
    @patch("apps.posting.services.stock.pa_relay_poster.requests.post")
    def test_failed_post_returns_structured_error(self, post):
        response = Mock()
        response.status_code = 405
        response.json.return_value = {"ok": False, "status": 405, "error": ""}
        post.return_value = response

        poster = PARelayPoster(relay_url="http://relay.test", relay_secret="s")
        result = poster.post_batch("t", "store", [{"serverId": 1, "title": "x"}])

        self.assertEqual(result.successful, {})
        self.assertIn("upstream_status=405", result.failed[0])

    @patch("apps.posting.services.stock.pa_relay_poster.requests.post")
    def test_non_json_body_is_handled(self, post):
        response = Mock()
        response.status_code = 405
        response.json.side_effect = ValueError("no json")
        post.return_value = response

        poster = PARelayPoster(relay_url="http://relay.test", relay_secret="s")
        result = poster.post_batch("t", "store", [{"serverId": 1, "title": "x"}])

        self.assertEqual(result.successful, {})
        self.assertIn("upstream_status=405", result.failed[0])


class LegacyRelayGuardFlagTests(SimpleTestCase):
    @override_settings(PA_LEGACY_RELAY_ENABLED=False)
    def test_disabled_by_default(self):
        self.assertTrue(_pa_legacy_relay_disabled())

    @override_settings(PA_LEGACY_RELAY_ENABLED=True)
    def test_can_be_force_enabled(self):
        self.assertFalse(_pa_legacy_relay_disabled())
