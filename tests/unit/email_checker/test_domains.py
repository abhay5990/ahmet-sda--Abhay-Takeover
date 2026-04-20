"""Tests for domain classification helpers."""
from apps.email_checker.services.domains import (
    get_domain,
    get_imap_server,
    is_gmail_domain,
    is_outlook_domain,
    normalize_email,
)


class TestNormalizeEmail:
    def test_lowercases_and_strips(self):
        assert normalize_email("  Foo@Bar.COM ") == "foo@bar.com"

    def test_empty_input(self):
        assert normalize_email("") == ""
        assert normalize_email(None) == ""  # type: ignore[arg-type]


class TestGetDomain:
    def test_simple_domain(self):
        assert get_domain("user@hotmail.com") == "hotmail.com"

    def test_uppercase_and_whitespace_normalized(self):
        assert get_domain("  USER@HOTMAIL.COM  ") == "hotmail.com"

    def test_malformed_returns_empty(self):
        assert get_domain("no-at-sign") == ""
        assert get_domain("") == ""

    def test_multiple_at_picks_last(self):
        assert get_domain("a@b@c.com") == "c.com"


class TestOutlookDomain:
    def test_hotmail_variants(self):
        assert is_outlook_domain("hotmail.com")
        assert is_outlook_domain("hotmail.co.uk")
        assert is_outlook_domain("hotmail.fr")

    def test_outlook_variants(self):
        assert is_outlook_domain("outlook.com")
        assert is_outlook_domain("outlook.com.tr")

    def test_live_and_msn(self):
        assert is_outlook_domain("live.com")
        assert is_outlook_domain("live.it")
        assert is_outlook_domain("msn.com")
        assert is_outlook_domain("msn.co.uk")

    def test_non_outlook(self):
        assert not is_outlook_domain("yahoo.com")
        assert not is_outlook_domain("gmail.com")
        assert not is_outlook_domain("")


class TestGmailDomain:
    def test_gmail_variants(self):
        assert is_gmail_domain("gmail.com")
        assert is_gmail_domain("gmail.co.uk")
        assert is_gmail_domain("googlemail.com")

    def test_non_gmail(self):
        assert not is_gmail_domain("yahoo.com")
        assert not is_gmail_domain("hotmail.com")


class TestImapServer:
    def test_hardcoded_yahoo(self):
        host, port = get_imap_server("yahoo.com")
        assert host == "imap.mail.yahoo.com"
        assert port == 993

    def test_hardcoded_mail_ru(self):
        host, port = get_imap_server("mail.ru")
        assert host == "imap.mail.ru"

    def test_unknown_domain_fallback(self):
        host, port = get_imap_server("randomdomain.xyz")
        assert host == "imap.randomdomain.xyz"
        assert port == 993
