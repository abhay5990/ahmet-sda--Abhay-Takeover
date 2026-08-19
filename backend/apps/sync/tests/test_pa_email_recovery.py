from email.message import EmailMessage
from unittest import TestCase

from apps.sync.services.playerauctions.email_recovery import (
    parse_playerauctions_email,
    select_recovery_uids,
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

    def test_select_recovery_uids_keeps_recent_window_and_advances_old_backlog(self):
        uids = [str(value).encode() for value in range(1, 594)]

        recent, backlog = select_recovery_uids(
            uids,
            limit=100,
            backfill_cursor=0,
        )

        self.assertEqual(recent[0], b'494')
        self.assertEqual(recent[-1], b'593')
        self.assertEqual(backlog[0], b'1')
        self.assertEqual(backlog[-1], b'100')

        _, next_backlog = select_recovery_uids(
            uids,
            limit=100,
            backfill_cursor=100,
        )

        self.assertEqual(next_backlog[0], b'101')
        self.assertEqual(next_backlog[-1], b'200')

    def test_select_recovery_uids_does_not_repeat_old_messages_after_cursor(self):
        uids = [str(value).encode() for value in range(1, 151)]

        recent, backlog = select_recovery_uids(
            uids,
            limit=100,
            backfill_cursor=50,
        )

        self.assertEqual(recent[0], b'51')
        self.assertEqual(backlog, [])
