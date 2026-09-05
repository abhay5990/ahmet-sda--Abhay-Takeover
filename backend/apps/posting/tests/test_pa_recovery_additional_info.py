from django.test import SimpleTestCase

from apps.posting.services.pool.formatter import append_playerauctions_recovery_email


class PlayerAuctionsRecoveryAdditionalInfoTests(SimpleTestCase):
    def test_appends_only_a_labelled_recovery_email(self):
        instruction = append_playerauctions_recovery_email(
            "Email: buyer@example.test\nEmail Password: existing-delivery-password",
            "recovery@example.test",
        )

        self.assertIn("Recovery Email: recovery@example.test", instruction)
        self.assertNotIn("recovery-password", instruction)

    def test_does_not_duplicate_or_emit_an_empty_recovery_email(self):
        existing = "Login: account\nRecovery Email: recovery@example.test"
        self.assertEqual(
            append_playerauctions_recovery_email(existing, "other@example.test"),
            existing,
        )
        self.assertEqual(append_playerauctions_recovery_email("Login: account", ""), "Login: account")
