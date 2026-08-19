from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import Mock, patch

from django.test import SimpleTestCase
from django.utils import timezone

from apps.sync.management.commands.renew_expiring_playerauctions import (
    _has_sale_or_open_order,
    _remote_offer_is_active,
)
from apps.sync.services.playerauctions.offers.service import (
    _expire_to_listed,
    _payload_expiry,
)


class PlayerAuctionsExpiryLifecycleTests(SimpleTestCase):
    def test_remote_expiry_is_preserved_and_derives_the_original_listing_time(self):
        payload = {
            'expiredTimeString': 'Aug-31-2026 10:47:05 AM',
            'details': {'offerDuration': 30},
        }

        expiry = _payload_expiry(payload)

        self.assertIsNotNone(expiry)
        self.assertEqual(
            _expire_to_listed(expiry, payload),
            expiry - timedelta(days=30),
        )

    def test_only_explicitly_active_remote_pa_offer_is_renewable(self):
        self.assertTrue(_remote_offer_is_active(SimpleNamespace(
            ok=True,
            data={'state': 1},
        )))
        self.assertFalse(_remote_offer_is_active(SimpleNamespace(
            ok=True,
            data={'state': 0},
        )))
        self.assertFalse(_remote_offer_is_active(SimpleNamespace(
            ok=True,
            data={},
        )))
        self.assertFalse(_remote_offer_is_active(SimpleNamespace(
            ok=False,
            data={'state': 1},
        )))

    def test_pending_order_blocks_automatic_renewal(self):
        listing = SimpleNamespace(
            integration_account=SimpleNamespace(pk=8),
            store_listing_id='292886322',
        )
        empty_events = Mock()
        empty_events.filter.return_value.exists.return_value = False
        pending_orders = Mock()
        pending_orders.filter.return_value.exists.return_value = True

        with patch(
            'apps.sync.management.commands.renew_expiring_playerauctions.PoolSaleEvent.objects',
            empty_events,
        ), patch(
            'apps.sync.management.commands.renew_expiring_playerauctions.OfferPoolActiveOffer.objects',
            empty_events,
        ), patch(
            'apps.sync.management.commands.renew_expiring_playerauctions.Order.objects',
            pending_orders,
        ):
            self.assertTrue(_has_sale_or_open_order(listing))

    def test_playerauctions_relist_derives_a_new_expiry_when_api_omits_one(self):
        from apps.posting.services.relist import _playerauctions_expiry_after_relist

        renewed_at = timezone.now()
        expiry = _playerauctions_expiry_after_relist(
            {'details': {'offerDuration': 30}},
            {},
            renewed_at,
        )

        self.assertEqual(expiry, renewed_at + timedelta(days=30))
