"""Tests for PA transient-session classification (F2) and outbound web-address
detection (F1)."""
from apps.posting.services.stock.consumer import _is_pa_relay_transient_session_error
from apps.posting.services.stock.pa_relay_poster import _web_address_hits
from django.test import SimpleTestCase


class TransientSessionClassifierTests(SimpleTestCase):
    def test_post_refresh_web_address_message_is_transient(self):
        err = (
            "PA relay upstream error (upstream_status=1): "
            "Please do not use web addresses for your description/title/instruction"
        )
        self.assertTrue(_is_pa_relay_transient_session_error(err))

    def test_401_is_not_transient(self):
        self.assertFalse(
            _is_pa_relay_transient_session_error(
                "PA relay upstream error (upstream_status=401): Unauthorized"
            )
        )

    def test_other_validation_is_not_transient(self):
        self.assertFalse(
            _is_pa_relay_transient_session_error(
                "PA relay upstream error (upstream_status=301): Please select a game."
            )
        )

    def test_none_is_not_transient(self):
        self.assertFalse(_is_pa_relay_transient_session_error(None))


class WebAddressHitsTests(SimpleTestCase):
    def test_detects_full_url_www_and_bare_domain(self):
        self.assertEqual(_web_address_hits("visit https://foo.gg/x"), ["https://foo.gg/x"])
        self.assertIn("www.example.com", _web_address_hits("see www.example.com now"))
        self.assertIn("example.com", _web_address_hits("mail me at a@example.com"))

    def test_clean_text_has_no_hits(self):
        self.assertEqual(_web_address_hits("Level 200, Max stats, 150 cars"), [])

    def test_empty(self):
        self.assertEqual(_web_address_hits(""), [])
