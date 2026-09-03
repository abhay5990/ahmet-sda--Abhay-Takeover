from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import patch

from django.test import TestCase

from apps.integrations.models import IntegrationAccount, IntegrationCredential
from apps.inventory.models import Category, Game, OwnedProduct
from apps.listings.models import Listing, ListingOwnedProduct
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
        self.assertEqual(payload["accountSecretDetails"][0], "login\npassword")
        self.assertEqual(payload["details"]["offerTitle"], "New title")
        self.assertEqual(payload["details"]["description"], "New description")
        self.assertEqual(payload["details"]["pricing"]["pricePerUnit"]["amount"], 31.5)
        self.assertEqual(payload["details"]["pricing"]["minQuantity"], 1)
        self.assertEqual(payload["details"]["pricing"]["volumeDiscounts"], [])
        self.assertEqual(payload["augmentedGame"]["gameId"], "70")
        self.assertIsNone(payload["augmentedGame"]["tradeEnvironmentId"])

    def test_edit_prefers_managed_stock_and_includes_full_credentials(self):
        listing = self._listing()
        product = OwnedProduct.objects.create(
            login="managed-login",
            password="managed-pass",
            password_hash="managed-hash",
            email="managed@example.com",
            email_password="managed-email-pass",
            category=self.category,
            game=self.game,
        )
        ListingOwnedProduct.objects.create(listing=listing, owned_product=product)
        captured = {}

        class Provider:
            def update_listing(self, client, external_id, payload):
                captured["payload"] = payload
                return SimpleNamespace(ok=True, error=None)

        class Client:
            def get_offer_account_details(self, *args, **kwargs):
                raise AssertionError("managed credentials should avoid remote credential lookup")

        with patch("apps.posting.services.offer_editor.build_proxy_pool", return_value=None), \
                patch("apps.posting.services.offer_editor.get_group_name", return_value=""), \
                patch("apps.posting.services.offer_editor.get_or_build_client", return_value=Client()), \
                patch("apps.posting.services.offer_editor.get_provider", return_value=Provider()):
            result = offer_editor.edit_offer(listing, {"title": "Managed credentials title"})

        self.assertTrue(result.ok, result.error)
        secret = captured["payload"]["accountSecretDetails"][0]
        self.assertIn("Login: managed-login", secret)
        self.assertIn("Password: managed-pass", secret)
        self.assertIn("Login: managed@example.com", secret)
        self.assertIn("Password: managed-email-pass", secret)

    def test_legacy_edit_recreates_offer_and_hands_off_listing(self):
        listing = self._listing()
        calls = []

        class Provider:
            def update_listing(self, client, external_id, payload):
                calls.append(("update", external_id))
                return SimpleNamespace(
                    ok=False,
                    error=(
                        "ErrorDetail(message='Cannot update structured details on "
                        "a legacy account entry. Use the structured creation flow instead.')"
                    ),
                )

            def create_listing(self, client, product_data):
                calls.append(("create", product_data["payload"]))
                return SimpleNamespace(ok=True, data={"id": "eldorado-offer-2"})

            def delete_listing(self, client, external_id):
                calls.append(("delete", external_id))
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
                {"title": "Recreated title", "price": Decimal("22.25")},
            )

        self.assertTrue(result.ok, result.error)
        self.assertEqual(result.new_offer_id, "eldorado-offer-2")
        self.assertEqual([item[0] for item in calls], ["update", "create", "delete"])
        self.assertEqual(calls[1][1]["details"]["offerTitle"], "Recreated title")
        self.assertEqual(
            calls[1][1]["details"]["pricing"]["pricePerUnit"]["amount"],
            22.25,
        )
        self.assertFalse(Listing.objects.filter(pk=listing.pk, status="listed").exists())
        replacement = Listing.objects.get(store_listing_id="eldorado-offer-2")
        self.assertEqual(replacement.title, "Recreated title")
        self.assertEqual(replacement.price, Decimal("22.25"))
