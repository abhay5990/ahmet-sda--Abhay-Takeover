"""Pure renewal payload tests; no database, HTTP, or credential generation."""
from copy import deepcopy
from unittest.mock import patch

from django.test import SimpleTestCase

from apis_sdk.clients.marketplaces.eldorado.delivery_details import to_wire_payload
from apis_sdk.clients.marketplaces.eldorado.models import (
    EldoradoOfferCredentialsResponse,
    EldoradoPrivateOffer,
)
from apps.posting.services import offer_editor
from apps.sync.services.eldorado.renewal_payload import build_renewal_payload


DETAIL = {
    'accountDetails': {'accountLogin': 'synthetic-account', 'accountPassword': 'fixture-only'},
    'emailDetails': None,
    'mfaDetails': {'method': 'synthetic', 'codes': ['fixture-only']},
    'additionalInfo': '  retain original spacing\nSecond line  ',
    'unknownCredentialField': {'nested': ['keep-exactly'], 'nullable': None},
}
IMAGE = {'smallImage': 'small-fixture', 'largeImage': 'large-fixture',
         'originalSizeImage': 'original-fixture'}


def live(**changes):
    return {
        'id': 'fixture-offer', 'offerState': 'Active', 'expireDate': '2026-11-08T18:00:00Z',
        'gameId': '106', 'category': 'Account', 'offerTitle': 'Live fixture title',
        'description': 'Live fixture description', 'guaranteedDeliveryTime': 'Instant',
        'quantity': 1, 'minQuantity': 1, 'pricePerUnit': {'amount': 12.5, 'currency': 'USD'},
        'volumeDiscounts': [], 'hasOriginalEmail': False,
        'mainOfferImage': deepcopy(IMAGE), 'offerImages': [deepcopy(IMAGE)],
        'tradeEnvironmentValues': [{'id': 2, 'name': 'Device', 'value': 'PC'}],
        'attributes': [{'id': 'platform', 'type': 'Select', 'value': {'id': 'pc', 'name': 'PC'}},
                       {'id': 'level', 'type': 'Numeric', 'value': 25}],
        **changes,
    }


def credentials(entries=None):
    return EldoradoOfferCredentialsResponse.model_validate({'accountDeliveryDetails': (
        [{'id': 'entry-fixture', 'legacySecretDetails': 'Login: lossy\nPassword: fixture',
          'structuredDetails': deepcopy(DETAIL)}] if entries is None else entries
    )})


class RenewalPayloadTests(SimpleTestCase):
    def test_complete_live_content_and_structured_delivery_survive_exactly(self):
        snapshot = live(tags=['keep-public-tag'])
        response = credentials()
        before = deepcopy(snapshot)
        response_before = response.model_dump()
        payload = build_renewal_payload(snapshot, response)
        self.assertEqual(payload['details']['offerTitle'], snapshot['offerTitle'])
        self.assertEqual(payload['details']['description'], snapshot['description'])
        self.assertEqual(payload['details']['pricing']['pricePerUnit'], snapshot['pricePerUnit'])
        self.assertEqual(payload['details']['mainOfferImage'], snapshot['mainOfferImage'])
        self.assertEqual(payload['details']['offerImages'], snapshot['offerImages'])
        self.assertEqual(payload['details']['tags'], ['keep-public-tag'])
        self.assertEqual(payload['augmentedGame'], {
            'gameId': '106', 'category': 'Account', 'tradeEnvironmentId': '2',
            'offerAttributes': [{'id': 'platform', 'type': 'Select', 'value': 'pc'},
                                {'id': 'level', 'type': 'Numeric', 'value': 25}],
            'attributeIdsCsv': None,
        })
        self.assertEqual(payload['accountDeliveryDetails'], [DETAIL])
        self.assertNotIn('accountSecretDetails', payload)
        self.assertEqual(to_wire_payload(payload), payload)
        self.assertEqual(snapshot, before)
        self.assertEqual(response.model_dump(), response_before)
        payload['accountDeliveryDetails'][0]['mfaDetails']['codes'].append('different')
        payload['details']['offerImages'][0]['smallImage'] = 'different'
        self.assertEqual(response.model_dump(), response_before)
        self.assertEqual(snapshot, before)

    def test_explicit_nulls_are_canonical_empty_never_stale_defaults(self):
        snapshot = live(description=None, mainOfferImage=None, offerImages=None,
                        hasOriginalEmail=None, volumeDiscounts=None,
                        tradeEnvironmentValues=None, attributes=None)
        payload = build_renewal_payload(snapshot, credentials())
        details = payload['details']
        self.assertEqual(details['description'], '')
        self.assertEqual(details['mainOfferImage'], {})
        self.assertEqual(details['offerImages'], [])
        self.assertIs(details['hasOriginalEmail'], False)
        self.assertIsNone(details['pricing']['volumeDiscounts'])
        self.assertIsNone(payload['augmentedGame']['tradeEnvironmentId'])
        self.assertEqual(payload['augmentedGame']['offerAttributes'], [])
        self.assertIsNone(snapshot['description'])

    def test_actual_private_model_explicit_nulls_survive_exclude_unset(self):
        model = EldoradoPrivateOffer.model_validate({'offer': live(description=None, mainOfferImage=None)})
        snapshot = model.offer.model_dump(by_alias=True, exclude_unset=True)
        payload = build_renewal_payload(snapshot, credentials())
        self.assertEqual(payload['details']['description'], '')
        self.assertEqual(payload['details']['mainOfferImage'], {})
        self.assertEqual(payload['details']['offerTitle'], 'Live fixture title')

    def test_each_missing_required_public_field_refuses_before_builder(self):
        required = (
            'gameId', 'category', 'offerTitle', 'description', 'guaranteedDeliveryTime',
            'quantity', 'minQuantity', 'pricePerUnit', 'volumeDiscounts', 'hasOriginalEmail',
            'mainOfferImage', 'offerImages', 'tradeEnvironmentValues', 'attributes',
        )
        for key in required:
            with self.subTest(key=key), patch.object(offer_editor, 'build_eldorado_full_update_payload') as builder:
                snapshot = live()
                snapshot.pop(key)
                model = EldoradoPrivateOffer.model_validate({'offer': snapshot})
                # Defaults exist on the model, but are not in the authoritative dump.
                with self.assertRaisesRegex(ValueError, '^renewal_public_fields_missing$'):
                    build_renewal_payload(model.offer.model_dump(exclude_unset=True), credentials())
                builder.assert_not_called()

    def test_nested_missing_price_and_images_do_not_acquire_model_defaults(self):
        for change in (
            {'pricePerUnit': {'currency': 'USD'}}, {'pricePerUnit': {'amount': 12}},
            {'mainOfferImage': {'originalSizeImage': 'only-original'}},
            {'offerImages': [{'smallImage': 'only-small'}]},
        ):
            with self.subTest(change=change):
                model = EldoradoPrivateOffer.model_validate({'offer': live(**change)})
                with self.assertRaises(ValueError):
                    build_renewal_payload(model.offer.model_dump(exclude_unset=True), credentials())

    def test_zero_blank_invalid_types_and_lossy_price_refuse(self):
        for change in (
            {'offerTitle': ''}, {'offerTitle': None}, {'description': {}},
            {'gameId': ''}, {'category': {'id': 'Account'}}, {'category': ''},
            {'guaranteedDeliveryTime': None}, {'quantity': True}, {'quantity': 0},
            {'minQuantity': None}, {'hasOriginalEmail': 'false'},
            {'pricePerUnit': {'amount': 0, 'currency': 'USD'}},
            {'pricePerUnit': {'amount': float('nan'), 'currency': 'USD'}},
            {'pricePerUnit': {'amount': float('inf'), 'currency': 'USD'}},
            {'pricePerUnit': {'amount': 9007199254740993, 'currency': 'USD'}},
            {'pricePerUnit': {'amount': 12, 'currency': ''}},
        ):
            with self.subTest(change=change), self.assertRaisesRegex(ValueError, '^renewal_public_fields_invalid$'):
                build_renewal_payload(live(**change), credentials())

    def test_unknown_public_content_and_multiple_environments_fail_closed(self):
        for change in (
            {'futurePublicContent': {'keep': 'cannot-map-safely'}},
            {'tradeEnvironmentValues': [{'id': 'region'}, {'id': 'device'}]},
            {'tradeEnvironmentValues': [{'id': 2, 'futureEditable': 'unknown'}]},
            {'attributes': [{'id': 'fixture', 'type': 'Text', 'value': 'keep'}]},
            {'attributes': [{'id': 'fixture', 'type': {'unknown': 'keep'}, 'value': 'keep'}]},
            {'attributes': [{'id': 'fixture', 'type': 'Select', 'value': 4}]},
            {'attributes': [{'id': 'fixture', 'type': 'Select', 'value': {'id': 'x', 'unknown': 'keep'}}]},
            {'pricePerUnit': {'amount': 12, 'currency': 'USD', 'unknown': 'keep'}},
        ):
            with self.subTest(change=change), self.assertRaisesRegex(ValueError, '^renewal_public_fields_unrepresentable$'):
                build_renewal_payload(live(**change), credentials())

    def test_quantity_mismatch_never_rewrites_live_inventory_count(self):
        for count, entries in ((2, None), (1, [])):
            with self.subTest(count=count):
                with self.assertRaisesRegex(ValueError, '^renewal_delivery_quantity_mismatch$'):
                    build_renewal_payload(live(quantity=count), credentials(entries))

    def test_missing_or_unreadable_delivery_has_fixed_local_reason(self):
        for response in (
            None, EldoradoOfferCredentialsResponse.model_validate({}),
            credentials([{'id': 'unreadable'}]),
            credentials([{'id': 'partial', 'structuredDetails': {
                'accountDetails': {'accountLogin': 'secret-sentinel-unusable'},
            }}]),
        ):
            with self.subTest(response_type=type(response).__name__):
                with self.assertRaisesRegex(ValueError, '^renewal_delivery_details_unreadable$') as caught:
                    build_renewal_payload(live(), response)
                self.assertIsNone(caught.exception.__cause__)
                self.assertNotIn('secret-sentinel', str(caught.exception))

    def test_assertion_refuses_builder_drift_instead_of_sending_changed_fields(self):
        original = offer_editor.build_eldorado_full_update_payload
        def drifting(row, secrets):
            result = original(row, secrets)
            result['details']['offerTitle'] = 'accidental-replacement'
            return result
        with patch.object(offer_editor, 'build_eldorado_full_update_payload', side_effect=drifting):
            with self.assertRaisesRegex(ValueError, '^renewal_payload_not_faithful$'):
                build_renewal_payload(live(), credentials())

    def test_builder_exception_has_only_a_fixed_local_reason(self):
        with patch.object(offer_editor, 'build_eldorado_full_update_payload',
                          side_effect=RuntimeError('private-payload-sentinel')):
            with self.assertRaisesRegex(ValueError, '^renewal_payload_not_faithful$') as caught:
                build_renewal_payload(live(), credentials())
            self.assertNotIn('private-payload-sentinel', str(caught.exception))
            self.assertIsNone(caught.exception.__cause__)

    def test_actual_modeled_category_and_read_only_metadata_are_not_overblocked(self):
        snapshot = live(userId='fixture-user', gameCategoryTitle='Fixture game', offerVersion=3,
                        pricePerUnitWithDiscount={'amount': 10, 'currency': 'USD'},
                        pricePerUnitInUSD={'amount': 12.5, 'currency': 'USD'}, discountPercentage=None,
                        accountsDetails=[])
        model = EldoradoPrivateOffer.model_validate({'offer': snapshot})
        payload = build_renewal_payload(model.offer.model_dump(exclude_unset=True), credentials())
        self.assertEqual(payload['augmentedGame']['category'], 'Account')
        self.assertEqual(payload['details']['pricing']['quantity'], 1)
