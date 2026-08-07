from email.message import EmailMessage
from unittest import TestCase

from apps.sync.services.playerauctions.email_recovery import (
    parse_playerauctions_email,
)


RECIPIENT_MAP = {
    'csgosmurfkings@gmail.com': 'playerauctions-csgosmurfkings',
    'abhishekdilipjain@gmail.com': 'playerauctions-vapenation234',
}


class PlayerAuctionsEmailRecoveryTests(TestCase):
    def test_maps_auto_delivery_email_to_mart_and_extracts_order_id(self):
        message = EmailMessage()
        message['From'] = 'No Reply [Playerauctions] <noreply@playerauctions.com>'
        message['To'] = 'Csgosmurfkings <csgosmurfkings@gmail.com>'
        message['Subject'] = 'You Have a New Automatic Delivery Account Order'
        message.set_content('Order ID: 16364033')

        candidate = parse_playerauctions_email(message, RECIPIENT_MAP)

        self.assertIsNotNone(candidate)
        self.assertEqual(candidate.order_id, '16364033')
        self.assertEqual(candidate.account_slug, 'playerauctions-csgosmurfkings')

    def test_maps_forwarded_shop_email_from_original_recipient_header(self):
        message = EmailMessage()
        message['From'] = 'No Reply [Playerauctions] <noreply@playerauctions.com>'
        message['To'] = 'ezsmurfmartdisputes@gmail.com'
        message['X-Original-To'] = 'abhishekdilipjain@gmail.com'
        message['Subject'] = 'You Have a New Order'
        message.set_content('Open your order: https://example.test/?orderId=16363599')

        candidate = parse_playerauctions_email(message, RECIPIENT_MAP)

        self.assertIsNotNone(candidate)
        self.assertEqual(candidate.order_id, '16363599')
        self.assertEqual(candidate.account_slug, 'playerauctions-vapenation234')

    def test_rejects_unrelated_or_unmapped_email(self):
        message = EmailMessage()
        message['From'] = 'No Reply [Playerauctions] <noreply@playerauctions.com>'
        message['To'] = 'other@example.com'
        message['Subject'] = 'You Have a New Order'
        message.set_content('Order ID: 16363599')

        self.assertIsNone(parse_playerauctions_email(message, RECIPIENT_MAP))
