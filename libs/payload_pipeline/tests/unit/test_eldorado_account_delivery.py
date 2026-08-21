from __future__ import annotations

import pytest

from payload_pipeline.core.contracts import CredentialBundle


def test_eldorado_secret_sections_keep_credentials_out_of_additional_info():
    credentials = CredentialBundle(
        login="game-login",
        password="game-password",
        email_login="mail@example.com",
        email_password="mail-password",
        email_login_link="https://mail.example.com",
        security_email="2fa@example.com",
        security_email_password="2fa-password",
        additional_info="Account has no penalties.",
    )

    rendered = credentials.to_eldorado_account_secret()

    assert "Account details\nLogin: game-login\nPassword: game-password" in rendered
    assert "Email details\nProvider URL: https://mail.example.com" in rendered
    assert "2FA details\nLogin: 2fa@example.com\nPassword: 2fa-password" in rendered
    assert "Additional information\nAccount has no penalties." in rendered


@pytest.mark.parametrize(
    "unsafe_note",
    ["Password: should-not-go-here", "support@example.com", "token abc"],
)
def test_eldorado_additional_info_rejects_sensitive_content(unsafe_note: str):
    credentials = CredentialBundle(login="game-login", password="game-password")
    credentials.additional_info = unsafe_note

    with pytest.raises(ValueError, match="must not contain credentials"):
        credentials.to_eldorado_account_secret()
