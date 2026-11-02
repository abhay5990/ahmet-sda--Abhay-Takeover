"""Eldorado accountDeliveryDetails wire conversion (Oct 2026 contract)."""

from __future__ import annotations

import pytest

from apis_sdk.clients.marketplaces.eldorado.delivery_details import (
    EldoradoDeliveryDetailsError,
    secret_text_to_delivery_detail,
    to_wire_payload,
)

SECTIONED = (
    "Account details\nLogin: acc_login\nPassword: acc_pass\n\n"
    "Email details\nProvider URL: https://outlook.live.com\nLogin: buyer@hotmail.com\nPassword: mail_pass\n\n"
    "2FA details\nLogin: sec@mail.com\nPassword: sec_pass"
)


def test_sectioned_entry_from_credential_bundle():
    d = secret_text_to_delivery_detail(SECTIONED)
    assert d["accountDetails"] == {"accountLogin": "acc_login", "accountPassword": "acc_pass"}
    assert d["emailDetails"] == {
        "emailLogin": "buyer@hotmail.com", "emailPassword": "mail_pass", "emailProviderUrl": "https://outlook.live.com",
    }
    assert d["mfaDetails"] is None
    assert "sec@mail.com" in d["additionalInfo"]  # security email kept for the buyer


def test_gta_platform_lines_with_unknown_email_domain_keep_email_as_text():
    text = "PSN ID: psn_user\nPSN Password: psn_pw\nDate of Birth: 01/01/1990\nEmail: x@unknownmail.xyz\nEmail Password: e_pw\nBackup Codes:\n1111 2222"
    d = secret_text_to_delivery_detail(text)
    assert d["accountDetails"] == {"accountLogin": "psn_user", "accountPassword": "psn_pw"}
    assert d["emailDetails"] is None
    assert "Email: x@unknownmail.xyz" in d["additionalInfo"]
    assert "Email Password: e_pw" in d["additionalInfo"]
    assert "Date of Birth: 01/01/1990" in d["additionalInfo"]
    assert "1111 2222" in d["additionalInfo"]


def test_known_domain_gets_provider_url_and_absent_parts_are_null():
    d = secret_text_to_delivery_detail("Login: a\nPassword: b\nEmail: c@gmail.com\nEmail Password: d")
    assert d["emailDetails"]["emailProviderUrl"] == "https://mail.google.com"
    assert d["additionalInfo"] is None
    d2 = secret_text_to_delivery_detail("Login: a\nPassword: b")
    assert d2["emailDetails"] is None and d2["mfaDetails"] is None and d2["additionalInfo"] is None


def test_fail_closed_without_login_and_password():
    with pytest.raises(EldoradoDeliveryDetailsError):
        secret_text_to_delivery_detail("just some notes")
    with pytest.raises(EldoradoDeliveryDetailsError):
        secret_text_to_delivery_detail("")


def test_wire_payload_converts_each_unit_and_drops_legacy_field():
    payload = {
        "details": {"pricing": {"quantity": 2, "volumeDiscounts": []}},
        "augmentedGame": {"gameId": "25"},
        "accountSecretDetails": ["Login: a1\nPassword: p1", "Login: a2\nPassword: p2"],
    }
    wire = to_wire_payload(payload)
    assert "accountSecretDetails" not in wire
    assert [e["accountDetails"]["accountLogin"] for e in wire["accountDeliveryDetails"]] == ["a1", "a2"]
    assert wire["details"]["pricing"]["volumeDiscounts"] is None
    assert payload["accountSecretDetails"]  # caller's dict is not mutated


def test_dropship_without_secrets_and_already_converted_payloads():
    assert "accountDeliveryDetails" not in to_wire_payload({"details": {}, "accountSecretDetails": []})
    pre = {"details": {}, "accountDeliveryDetails": [{"x": 1}], "accountSecretDetails": ["Login: a\nPassword: b"]}
    assert to_wire_payload(pre)["accountDeliveryDetails"] == [{"x": 1}]
