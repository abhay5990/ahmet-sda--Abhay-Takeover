"""Tests for the domain -> check method router."""
from apps.email_checker.services.dispatcher import classify
from apps.email_checker.services.types import CheckMethod


class TestClassify:
    def test_hotmail_is_lzt(self):
        assert classify("user@hotmail.com") == CheckMethod.LZT

    def test_outlook_tld_variant_is_lzt(self):
        assert classify("user@outlook.com.tr") == CheckMethod.LZT

    def test_live_is_lzt(self):
        assert classify("user@live.it") == CheckMethod.LZT

    def test_msn_is_lzt(self):
        assert classify("user@msn.co.uk") == CheckMethod.LZT

    def test_gmail_is_skipped(self):
        assert classify("user@gmail.com") == CheckMethod.SKIP

    def test_googlemail_is_skipped(self):
        assert classify("user@googlemail.com") == CheckMethod.SKIP

    def test_yahoo_is_imap(self):
        assert classify("user@yahoo.com") == CheckMethod.IMAP

    def test_mail_ru_is_imap(self):
        assert classify("user@mail.ru") == CheckMethod.IMAP

    def test_unknown_domain_falls_back_to_imap(self):
        assert classify("user@bilinmeyen.xyz") == CheckMethod.IMAP

    def test_caps_and_whitespace_normalized(self):
        assert classify(" User@HOTMAIL.COM ") == CheckMethod.LZT

    def test_malformed_is_skipped(self):
        assert classify("no-at-sign") == CheckMethod.SKIP
        assert classify("") == CheckMethod.SKIP
