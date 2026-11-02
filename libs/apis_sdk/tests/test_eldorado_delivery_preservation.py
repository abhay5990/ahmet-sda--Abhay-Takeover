"""Synthetic lossless inventory-write tests; no marketplace or real secrets."""
from copy import deepcopy

import pytest

from apis_sdk.clients.marketplaces.eldorado.delivery_details import (
    EldoradoDeliveryDetailsError,
    preserved_delivery_details,
    to_wire_payload,
)
from apis_sdk.clients.marketplaces.eldorado.models import EldoradoOfferCredentialsResponse


def structured_entry():
    return {
        'accountDetails': {'accountLogin': 'synthetic-account', 'accountPassword': 'fixture-password'},
        'emailDetails': {'emailLogin': 'fixture@example.com', 'emailPassword': 'fixture-email-password', 'emailProviderUrl': 'https://example.com'},
        'mfaDetails': {'method': 'synthetic', 'fixtureCodes': ['fixture-only']},
        'additionalInfo': '  Preserve original spacing\nSecond line  ',
        'futureProviderField': {'nested': ['keep-me']},
    }


def test_append_preserves_mfa_and_unknown_fields_exactly():
    detail = structured_entry()
    response = EldoradoOfferCredentialsResponse.model_validate({
        'accountDeliveryDetails': [{'id': 'fixture-id', 'legacySecretDetails': None, 'structuredDetails': detail}]
    })
    preserved = preserved_delivery_details(response)
    wire = to_wire_payload({'accountSecretDetails': ['Login: new\nPassword: fixture-new'],
                            'accountDeliveryDetails': preserved})
    assert wire['accountDeliveryDetails'] == [detail]
    assert 'accountSecretDetails' not in wire
    assert 'structuredDetails=' not in repr(response.accountsDetails[0])


def test_structured_original_wins_over_lossy_legacy_rendering():
    detail = structured_entry()
    response = EldoradoOfferCredentialsResponse.model_validate({
        'accountDeliveryDetails': [{'id': 'fixture-id', 'legacySecretDetails': 'Login: synthetic-account\nPassword: fixture-password', 'structuredDetails': detail}]
    })
    assert preserved_delivery_details(response) == [detail]


def test_preserved_output_has_no_nested_alias_to_response():
    response = EldoradoOfferCredentialsResponse.model_validate({
        'accountDeliveryDetails': [{'id': 'fixture-id', 'structuredDetails': structured_entry()}]
    })
    before = deepcopy(response.accountsDetails[0].structuredDetails)
    preserved_delivery_details(response)[0]['mfaDetails']['fixtureCodes'].append('different')
    assert response.accountsDetails[0].structuredDetails == before


@pytest.mark.parametrize('entry', [
    {'id': 'unreadable'},
    {'id': 'partial', 'structuredDetails': {'accountDetails': {'accountLogin': 'fixture'}}},
    'invalid-provider-entry',
])
def test_unreadable_existing_entry_refuses_inventory_replacement(entry):
    response = EldoradoOfferCredentialsResponse.model_validate({'accountDeliveryDetails': [entry]})
    assert len(response.accountsDetails) == 1
    with pytest.raises(EldoradoDeliveryDetailsError):
        preserved_delivery_details(response)


def test_missing_list_shape_refused_but_authoritative_empty_list_allowed():
    with pytest.raises(EldoradoDeliveryDetailsError):
        preserved_delivery_details(EldoradoOfferCredentialsResponse.model_validate({}))
    assert preserved_delivery_details(EldoradoOfferCredentialsResponse.model_validate({'accountDeliveryDetails': []})) == []


def test_legacy_entry_still_converts_without_dropping_units():
    response = EldoradoOfferCredentialsResponse.model_validate({
        'accountsDetails': [{'id': 'legacy', 'secretDetails': 'Login: fixture\nPassword: fixture-password'}]
    })
    details = preserved_delivery_details(response)
    assert len(details) == 1
    assert details[0]['accountDetails']['accountLogin'] == 'fixture'
