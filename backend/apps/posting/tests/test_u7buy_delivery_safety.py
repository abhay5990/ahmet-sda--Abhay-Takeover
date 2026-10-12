from types import SimpleNamespace
from unittest.mock import Mock, patch

from django.test import SimpleTestCase

from apps.posting.services.shared.listing_writer import persist_success


class U7BuyDeliveryAuditTests(SimpleTestCase):
    def test_automatic_delivery_keys_are_not_persisted_in_listing_audit_data(self):
        store = SimpleNamespace()
        item = SimpleNamespace(
            marketplace="u7buy",
            store=store,
            listing=None,
            status=None,
        )
        job = SimpleNamespace(settings={}, game=SimpleNamespace(name="GTA 5"))
        owned_product = SimpleNamespace(login="owned-login")
        payload = {
            "offerName": "GTA account",
            "priceUsd": "10.00",
            "deliveryType": "automatic-type",
            "keys": [{"encrypted": "private-account-credential-bundle"}],
        }
        created_listing = Mock()

        with patch(
            "apps.posting.services.shared.listing_writer.Listing.objects.create",
            return_value=created_listing,
        ) as create_listing, patch(
            "apps.posting.services.shared.listing_writer.ListingOwnedProduct.objects.create",
        ):
            persist_success(
                item=item,
                job=job,
                owned_product=owned_product,
                store_listing_id="offer-1",
                variant_slug="pc",
                final_price=10,
                payload=payload,
                response_data={"offerId": "offer-1"},
            )

        raw_data = create_listing.call_args.kwargs["raw_data"]
        persisted_payload = raw_data["payload"]
        self.assertNotIn("keys", persisted_payload)
        self.assertNotIn("private-account-credential-bundle", str(raw_data))
        self.assertEqual(persisted_payload["_u7buy_delivery_mode"], "automatic")
        self.assertEqual(persisted_payload["_u7buy_delivery_key_count"], 1)
