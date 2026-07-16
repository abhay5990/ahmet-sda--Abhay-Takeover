from unittest.mock import Mock, patch

from django.test import SimpleTestCase

from apps.posting.services.stock.pa_relay_poster import PARelayPoster


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
