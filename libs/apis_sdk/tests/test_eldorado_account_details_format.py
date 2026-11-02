"""Eldorado Oct-2026 accountDeliveryDetails read format (pool counts read 0 before)."""

from __future__ import annotations

from apis_sdk.clients.marketplaces.eldorado.delivery_details import (
    credential_fingerprint,
    delivery_detail_to_secret_text,
    secret_text_to_delivery_detail,
)
from apis_sdk.clients.marketplaces.eldorado.models import (
    EldoradoOfferCredentialsResponse,
    EldoradoOfferSearchItem,
)

LIVE_SHAPE = {
    "accountDeliveryDetails": [
        {"id": "a1", "legacySecretDetails": "Login: user1\nPassword: pw1", "structuredDetails": None},
        {"id": "a2", "legacySecretDetails": None, "structuredDetails": {
            "accountDetails": {"accountLogin": "user2", "accountPassword": "pw2"},
            "emailDetails": {"emailLogin": "m@gmail.com", "emailPassword": "mp", "emailProviderUrl": "https://mail.google.com"},
            "mfaDetails": None, "additionalInfo": "DOB 1990",
        }},
    ]
}


def test_new_read_format_is_counted():
    resp = EldoradoOfferCredentialsResponse.model_validate(LIVE_SHAPE)
    assert [e.id for e in resp.accountsDetails] == ["a1", "a2"]
    assert [e.id for e in resp.secretDetails] == ["a1", "a2"]
    assert resp.secretDetails[0].secretDetails == "Login: user1\nPassword: pw1"
    assert "Login: user2" in resp.secretDetails[1].secretDetails


def test_legacy_read_format_still_works():
    resp = EldoradoOfferCredentialsResponse.model_validate(
        {"accountsDetails": [{"id": "x", "secretDetails": "Login: a\nPassword: b"}], "secretDetails": []}
    )
    assert len(resp.accountsDetails) == 1


def test_search_item_accepts_new_format():
    item = EldoradoOfferSearchItem.model_validate({"id": "o1", "quantity": 2, **LIVE_SHAPE})
    assert item.quantity == 2 and len(item.accountsDetails) == 2


def test_structured_detail_round_trips_and_fingerprints_match():
    structured = LIVE_SHAPE["accountDeliveryDetails"][1]["structuredDetails"]
    text = delivery_detail_to_secret_text(structured)
    back = secret_text_to_delivery_detail(text)
    assert back["accountDetails"] == structured["accountDetails"]
    assert back["emailDetails"] == structured["emailDetails"]
    assert credential_fingerprint(text) == credential_fingerprint(
        "Email: m@gmail.com\nLogin: USER2\nPassword: pw2"
    )
    assert credential_fingerprint("no creds here") is None
