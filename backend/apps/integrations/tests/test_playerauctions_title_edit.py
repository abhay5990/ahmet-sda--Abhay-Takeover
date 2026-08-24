from types import SimpleNamespace
from unittest.mock import Mock

from django.test import SimpleTestCase

from apps.integrations.providers.playerauctions import PlayerAuctionsProvider


class PlayerAuctionsTitleEditTests(SimpleTestCase):
    def test_provider_forwards_visible_title_with_credential_confirmation(self):
        client = Mock()
        client.edit_offer_in_browser.return_value = SimpleNamespace(ok=True)

        result = PlayerAuctionsProvider().update_listing(
            client,
            '294723367',
            {
                'payload': {
                    'title': 'Updated title',
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
        )
