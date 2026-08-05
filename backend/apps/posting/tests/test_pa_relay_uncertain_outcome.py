"""Tests for classifying PA relay failures whose remote outcome is UNKNOWN.

A gateway/timeout failure may have created the offer on PlayerAuctions before
the relay gave up, so the reserved item must NOT be auto-retried (duplicate
risk). A pre-creation failure (401/content) is safe to return to the pool.
"""
from apps.posting.services.stock.consumer import (
    _is_pa_relay_transient_session_error,
    _is_pa_relay_uncertain_outcome,
)
from django.test import SimpleTestCase


class UncertainOutcomeClassifierTests(SimpleTestCase):
    def test_502_timeout_is_uncertain(self):
        self.assertTrue(_is_pa_relay_uncertain_outcome(
            "PA relay upstream error (upstream_status=502): "
            "relay exception: timeout of 50000ms exceeded"
        ))

    def test_client_timeout_is_uncertain(self):
        self.assertTrue(_is_pa_relay_uncertain_outcome("PA relay timeout"))

    def test_503_504_are_uncertain(self):
        self.assertTrue(_is_pa_relay_uncertain_outcome("upstream_status=503"))
        self.assertTrue(_is_pa_relay_uncertain_outcome("upstream_status=504"))

    def test_401_is_not_uncertain(self):
        # Pre-creation rejection — safe to retry, not a duplicate risk.
        self.assertFalse(_is_pa_relay_uncertain_outcome(
            "PA relay upstream error (upstream_status=401): Unauthorized"
        ))

    def test_content_rejection_is_not_uncertain(self):
        self.assertFalse(_is_pa_relay_uncertain_outcome(
            "PA relay upstream error (upstream_status=1): Please select a game."
        ))

    def test_none_is_not_uncertain(self):
        self.assertFalse(_is_pa_relay_uncertain_outcome(None))

    def test_uncertain_takes_precedence_over_transient(self):
        # A 502/timeout must never be treated as a safe transient session blip.
        err = "PA relay upstream error (upstream_status=502): timeout of 50000ms exceeded"
        self.assertTrue(_is_pa_relay_uncertain_outcome(err))
        # (The web-address transient classifier only matches the '1'/web-address
        # message, so it stays independent.)
        self.assertFalse(_is_pa_relay_transient_session_error(err))
