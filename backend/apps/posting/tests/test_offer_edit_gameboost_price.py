"""GameBoost 'Update on Marketplace' price edits must convert USD->EUR
(the edit path previously sent raw USD)."""
from decimal import Decimal
from unittest.mock import patch

from apps.integrations.models import IntegrationAccount, IntegrationCredential
from apps.inventory.models import Category, Game
from apps.listings.models import Listing
from apps.posting.services import offer_editor
from apps.posting.services.shared.pricing import DEFAULT_GAMEBOOST_USD_TO_EUR
from django.test import TestCase

_MOD = "apps.posting.services.offer_editor"


class _OkResult:
    ok = True
    error = None


class GameBoostEditPriceConversionTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.category = Category.objects.create(name="acc", title="Acc")
        cls.game = Game.objects.create(name="Fortnite", slug="fortnite", category=cls.category)

    def _listing(self, provider="gameboost"):
        store = IntegrationAccount.objects.create(
            name=f"{provider} store", slug=f"{provider}-store", provider=provider, role="sell",
        )
        IntegrationCredential.objects.create(account=store, credentials={"test": "x"})
        return Listing.objects.create(
            is_instant=True, integration_account=store, game=self.game,
            store_listing_id="gb-offer-1", status="listed", title="t",
            price=Decimal("20.00"), currency="USD",
        )

    def _run_edit(self, listing, changes):
        captured = {}

        class _Provider:
            def update_listing(self, client, external_id, payload):
                captured["payload"] = payload
                return _OkResult()

        with patch(f"{_MOD}.build_proxy_pool", return_value=None), \
                patch(f"{_MOD}.get_group_name", return_value=""), \
                patch(f"{_MOD}.get_or_build_client", return_value=object()), \
                patch(f"{_MOD}.get_provider", return_value=_Provider()):
            result = offer_editor.edit_offer(listing, changes)
        return result, captured.get("payload")

    def test_gameboost_edit_converts_usd_to_eur(self):
        listing = self._listing("gameboost")
        result, payload = self._run_edit(listing, {"price": Decimal("26.99")})

        self.assertTrue(result.ok, result.error)
        expected = round(26.99 * DEFAULT_GAMEBOOST_USD_TO_EUR, 2)  # 23.48
        self.assertEqual(payload["price"], expected)
        # Stored price matches what was posted (EUR), not the raw USD.
        listing.refresh_from_db()
        self.assertEqual(float(listing.price), expected)

    def test_gameboost_edit_respects_configured_posting_default_rate(self):
        from apps.posting.models import PostingDefault
        PostingDefault.objects.create(
            game=self.game, marketplace="gameboost",
            multiplier_low=Decimal("2"), multiplier_mid=Decimal("1.8"),
            multiplier_high=Decimal("1.5"), min_price=Decimal("0"),
            exchange_rate=Decimal("0.90"),
        )
        listing = self._listing("gameboost")
        _, payload = self._run_edit(listing, {"price": Decimal("10.00")})
        self.assertEqual(payload["price"], round(10.0 * 0.90, 2))  # 9.0
