from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import patch

from django.test import TestCase

from apps.integrations.models import IntegrationAccount, IntegrationCredential
from apps.inventory.models import Category, Game
from apps.listings.models import Listing
from apps.posting.services import offer_editor


class EldoradoEditPayloadTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.category = Category.objects.create(name="acc", title="Account")
        cls.game = Game.objects.create(name="Fortnite", slug="fortnite", category=cls.category)

    def _listing(self):
        store = IntegrationAccount.objects.create(
            name="Eldorado edit store",
            slug="eldorado-edit-store",
            provider="eldorado",
            role="sell",
        )
        IntegrationCredential.objects.create(account=store, credentials={"test": "x"})
        return Listing.objects.create(
            is_instant=True,
            integration_account=store,
            game=self.game,
            store_listing_id="eldorado-offer-1",
            status="listed",
            title="Old title",
            price=Decimal("20.00"),
            currency="USD",
            raw_data={
                "offerTitle": "Old title",
                "description": "Old description",
                "pricePerUnit": {"amount": 20.0, "currency": "USD"},
                "quantity": 1,
                "gameId": "70",
                "tradeEnvironmentValues": [],
                "attributes": [],
                "_credential_entries": [
                    {"id": "credential-1", "secretDetails": "login\npassword"},
                ],
            },
        )

    def test_eldorado_edit_uses_canonical_update_payload(self):
        listing = self._listing()
        captured = {}

        class Provider:
            def update_listing(self, client, external_id, payload):
                captured["external_id"] = external_id
                captured["payload"] = payload
                return SimpleNamespace(ok=True, error=None)

        client = SimpleNamespace(
            get_offer_account_details=lambda offer_id, proxy_group=None: SimpleNamespace(
                ok=False, data=None,
            ),
        )
        with patch("apps.posting.services.offer_editor.build_proxy_pool", return_value=None), \
                patch("apps.posting.services.offer_editor.get_group_name", return_value=""), \
                patch("apps.posting.services.offer_editor.get_or_build_client", return_value=client), \
                patch("apps.posting.services.offer_editor.get_provider", return_value=Provider()):
            result = offer_editor.edit_offer(
                listing,
                {
                    "title": "New title",
                    "description": "New description",
                    "price": Decimal("31.50"),
                },
            )

        self.assertTrue(result.ok, result.error)
        self.assertEqual(captured["external_id"], "eldorado-offer-1")
        payload = captured["payload"]
        self.assertIn("accountSecretDetails", payload)
        self.assertNotIn("accountDetails", payload)
        self.assertEqual(payload["accountSecretDetails"][0]["id"], "credential-1")
        self.assertEqual(payload["details"]["offerTitle"], "New title")
        self.assertEqual(payload["details"]["description"], "New description")
        self.assertEqual(payload["details"]["pricing"]["pricePerUnit"]["amount"], 31.5)
        self.assertEqual(payload["details"]["pricing"]["minQuantity"], 1)
        self.assertEqual(payload["details"]["pricing"]["volumeDiscounts"], [])
        self.assertEqual(payload["augmentedGame"]["gameId"], "70")
        self.assertIsNone(payload["augmentedGame"]["tradeEnvironmentId"])
