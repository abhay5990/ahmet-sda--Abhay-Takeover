"""Tests for the credential smart parser and backfill management command."""
import os
import tempfile
from io import StringIO

from apps.inventory.models import Category, Game, OwnedProduct
from apps.posting.services.pool.credential_parser import (
    parse_credential_row,
    parse_credential_text,
)
from django.core.management import call_command
from django.test import TestCase


class CredentialParserTests(TestCase):
    def test_full_seven_field_row(self):
        row = (
            "aa278546609\tehaa452714\thhlw3454@outlook.com\tikdpzu185733\t"
            "HqUOJiwQ@jood886.ltd\tScVdGooCCkhQ\tmx.duolashop.com/outlook.com"
        ).split("\t")
        cred = parse_credential_row(row)
        self.assertEqual(cred["login"], "aa278546609")
        self.assertEqual(cred["password"], "ehaa452714")
        self.assertEqual(cred["email"], "hhlw3454@outlook.com")
        self.assertEqual(cred["email_password"], "ikdpzu185733")
        self.assertEqual(cred["security_email"], "HqUOJiwQ@jood886.ltd")
        self.assertEqual(cred["security_email_password"], "ScVdGooCCkhQ")
        # Email domain kept whole, never split on '/'.
        self.assertEqual(cred["email_login_link"], "mx.duolashop.com/outlook.com")

    def test_short_row_with_domain(self):
        row = "u2\tp2\tu2@outlook.com\tep2\toutlook.com".split("\t")
        cred = parse_credential_row(row)
        self.assertEqual(cred["email_login_link"], "outlook.com")
        self.assertEqual(cred["security_email"], "")

    def test_header_row_skipped(self):
        text = "login\tpassword\temail\nu1\tp1\tu1@x.com"
        rows = parse_credential_text(text)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["login"], "u1")


class BackfillCommandTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.category = Category.objects.create(name="bf", title="BF")
        cls.game = Game.objects.create(name="Fortnite", slug="fortnite", category=cls.category)

    def _make_old_account(self, login="aa278546609"):
        # Simulates an account added before smart parse: no recovery/domain.
        return OwnedProduct.objects.create(
            category=self.category, game=self.game,
            login=login, password="ehaa452714",
            email="hhlw3454@outlook.com",
        )

    def _write(self, text):
        fd, path = tempfile.mkstemp(suffix=".tsv")
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(text)
        self.addCleanup(os.remove, path)
        return path

    def test_backfills_blank_detail_fields(self):
        owned = self._make_old_account()
        path = self._write(
            "aa278546609\tehaa452714\thhlw3454@outlook.com\tikdpzu185733\t"
            "HqUOJiwQ@jood886.ltd\tScVdGooCCkhQ\tmx.duolashop.com/outlook.com"
        )
        out = StringIO()
        call_command("backfill_credential_details", file=path, stdout=out)

        owned.refresh_from_db()
        self.assertEqual(owned.security_email, "HqUOJiwQ@jood886.ltd")
        self.assertEqual(owned.security_email_password, "ScVdGooCCkhQ")
        self.assertEqual(owned.email_login_link, "mx.duolashop.com/outlook.com")
        self.assertIn("updated=1", out.getvalue())

    def test_dry_run_does_not_save(self):
        owned = self._make_old_account()
        path = self._write(
            "aa278546609\tehaa452714\thhlw3454@outlook.com\tikdpzu185733\t"
            "HqUOJiwQ@jood886.ltd\tScVdGooCCkhQ\tmx.duolashop.com/outlook.com"
        )
        call_command("backfill_credential_details", file=path, dry_run=True, stdout=StringIO())
        owned.refresh_from_db()
        self.assertEqual(owned.security_email, "")

    def test_does_not_overwrite_without_flag(self):
        owned = self._make_old_account()
        owned.security_email = "existing@keep.com"
        owned.save(update_fields=["security_email"])
        path = self._write(
            "aa278546609\tehaa452714\thhlw3454@outlook.com\tikdpzu185733\t"
            "HqUOJiwQ@jood886.ltd\tScVdGooCCkhQ\tmx.duolashop.com/outlook.com"
        )
        # Without --overwrite: existing value preserved, but blank domain filled.
        call_command("backfill_credential_details", file=path, stdout=StringIO())
        owned.refresh_from_db()
        self.assertEqual(owned.security_email, "existing@keep.com")
        self.assertEqual(owned.email_login_link, "mx.duolashop.com/outlook.com")

        # With --overwrite: existing value replaced.
        call_command("backfill_credential_details", file=path, overwrite=True, stdout=StringIO())
        owned.refresh_from_db()
        self.assertEqual(owned.security_email, "HqUOJiwQ@jood886.ltd")

    def test_reports_unmatched_logins(self):
        path = self._write("ghost123\tpw\tghost@x.com\tep\tmx.x.com/y.com")
        out = StringIO()
        call_command("backfill_credential_details", file=path, stdout=out)
        self.assertIn("not_found=1", out.getvalue())
        self.assertIn("ghost123", out.getvalue())
