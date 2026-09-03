from types import SimpleNamespace
from unittest.mock import patch

from django.test import SimpleTestCase

from apps.posting.services.pool.formatter import format_credential_for_marketplace


class EldoradoCredentialFormatterTests(SimpleTestCase):
    def test_spec_output_always_contains_core_managed_credentials(self):
        product = SimpleNamespace(
            login="game-login",
            password="game-password",
            email="mail@example.com",
            email_password="mail-password",
            email_login_link="",
            security_email="",
            security_email_password="",
            security_email_login_link="",
            raw_data={},
        )
        spec = object()

        with patch(
            "apps.posting.services.pool.formatter._resolve_product_spec",
            return_value=spec,
        ), patch(
            "apps.posting.services.pool.formatter.format_credential_by_spec",
            return_value="PSN ID: game-login\nPSN Pass: game-password",
        ):
            rendered = format_credential_for_marketplace(product, "eldorado")

        self.assertIn("PSN ID: game-login", rendered)
        self.assertIn("Account details\nLogin: game-login\nPassword: game-password", rendered)
        self.assertIn("Email details\nLogin: mail@example.com\nPassword: mail-password", rendered)
        self.assertNotIn("Additional information\nLogin:", rendered)
        self.assertNotIn("Additional information\nPassword:", rendered)


class _Unused:
    pass

