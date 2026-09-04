from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import Mock

from apps.integrations.providers.playerauctions import PlayerAuctionsProvider
from apis_sdk.clients.marketplaces.playerauctions.facade import PlayerAuctionsFacade


class PlayerAuctionsTitleEditTests(TestCase):
    def test_provider_forwards_visible_edit_fields_with_credential_confirmation(self):
        client = Mock()
        client.edit_offer_in_browser.return_value = SimpleNamespace(ok=True)

        result = PlayerAuctionsProvider().update_listing(
            client,
            '294723367',
            {
                'payload': {
                    'title': 'Updated title',
                    'offerDesc': 'Updated description',
                    'price': '249.99',
                    'autoDelivery': {
                        'retypeLoginName': 'account@example.com',
                        'retypePassword': 'account-password',
                    },
                },
            },
        )

        self.assertTrue(result.ok)
        client.edit_offer_in_browser.assert_called_once_with(
            offer_id=294723367,
            login_name='account@example.com',
            account_password='account-password',
            title='Updated title',
            description='Updated description',
            price='249.99',
        )

    def test_facade_accepts_and_forwards_all_visible_edit_fields(self):
        auth = Mock()
        auth.edit_offer_in_browser.return_value = SimpleNamespace(ok=True)
        facade = object.__new__(PlayerAuctionsFacade)
        facade._auth = auth

        result = facade.edit_offer_in_browser(
            offer_id=294723367,
            login_name='account@example.com',
            account_password='account-password',
            title='Updated title',
            description='Updated description',
            price='249.99',
        )

        self.assertTrue(result.ok)
        auth.edit_offer_in_browser.assert_called_once_with(
            offer_id=294723367,
            login_name='account@example.com',
            account_password='account-password',
            title='Updated title',
            description='Updated description',
            price='249.99',
        )
