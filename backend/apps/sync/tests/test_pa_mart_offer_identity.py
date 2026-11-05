from datetime import timedelta
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import patch

from django.test import SimpleTestCase, TestCase
from django.utils import timezone

from apps.integrations.models import IntegrationAccount
from apps.listings.enums import ListingStatus
from apps.listings.models import Listing
from apps.orders.enums import OrderStatus
from apps.orders.models import Order
from apps.sync.models import PaMartRenewalAttempt
from apps.sync.services.base import BaseSyncService
from apps.sync.services.pa_mart_offer_identity import (
    is_pa_mart_identity_account,
    resolve_pa_mart_listing,
)
from apps.sync.services.playerauctions.orders.service import PlayerAuctionsOrderSyncService


class PaMartOfferIdentityTests(TestCase):
    def setUp(self):
        self.account = IntegrationAccount.objects.create(
            name='Synthetic Mart', provider='playerauctions',
            slug='playerauctions-csgosmurfkings',
        )
        self.shop = IntegrationAccount.objects.create(
            name='Synthetic Shop', provider='playerauctions',
            slug='playerauctions-shop',
        )
        self.listing = self._listing(self.account, '300')
        self.previous_expiry = timezone.now() + timedelta(days=3)
        self.sequence = 0

    def _listing(self, account, offer_id):
        return Listing.objects.create(
            integration_account=account, store_listing_id=offer_id,
            title='Synthetic listing', price=Decimal('10.00'),
        )

    def _attempt(self, listing, old_id, new_id, status='succeeded', **kwargs):
        self.sequence += 1
        values = {
            'listing': listing,
            'integration_account': listing.integration_account,
            'request_id': f'synthetic-renewal-{self.sequence:04d}',
            'old_offer_id': old_id,
            'new_offer_id': new_id,
            'status': status,
            'previous_expires_at': self.previous_expiry,
            'verified_expires_at': self.previous_expiry + timedelta(days=30),
        }
        values.update(kwargs)
        return PaMartRenewalAttempt.objects.create(**values)

    def _history(self):
        self._attempt(self.listing, '100', '200')
        self._attempt(self.listing, '200', '300')

    def test_current_id_resolves_without_a_ledger_row(self):
        self.assertEqual(resolve_pa_mart_listing(self.account, '300'), self.listing)

    def test_multiple_renewal_cycles_preserve_every_old_and_new_id(self):
        self._history()
        for offer_id in ('100', '200', '300'):
            with self.subTest(offer_id=offer_id):
                self.assertEqual(resolve_pa_mart_listing(self.account, offer_id), self.listing)
        self.assertEqual(PaMartRenewalAttempt.objects.count(), 2)
        self.listing.refresh_from_db()
        self.assertEqual(self.listing.store_listing_id, '300')

    def test_succeeded_new_id_resolves_without_being_the_current_id(self):
        self._attempt(self.listing, '100', '200')
        self.assertEqual(resolve_pa_mart_listing(self.account, '200'), self.listing)

    def test_current_and_history_for_same_listing_are_not_ambiguous(self):
        self._history()
        self._attempt(self.listing, '300', '300')
        self.assertEqual(resolve_pa_mart_listing(self.account, '300'), self.listing)

    def test_duplicate_alias_rows_for_same_listing_are_not_ambiguous(self):
        self._attempt(self.listing, '100', '200')
        self._attempt(
            self.listing, '100', '300',
            previous_expires_at=self.previous_expiry + timedelta(days=30),
        )
        self.assertEqual(resolve_pa_mart_listing(self.account, '100'), self.listing)

    def test_current_id_collision_with_another_listings_alias_fails_closed(self):
        self._history()
        self._listing(self.account, '100')
        self.assertIsNone(resolve_pa_mart_listing(self.account, '100'))

    def test_two_historical_listing_identities_fail_closed(self):
        self._history()
        other = self._listing(self.account, '400')
        self._attempt(other, '100', '400')
        self.assertIsNone(resolve_pa_mart_listing(self.account, '100'))

    def test_collision_across_old_and_new_ledger_columns_fails_closed(self):
        self._attempt(self.listing, '100', '200')
        other = self._listing(self.account, '400')
        self._attempt(other, '150', '100')
        self.assertIsNone(resolve_pa_mart_listing(self.account, '100'))

    def test_other_accounts_current_id_does_not_match(self):
        self._listing(self.shop, '100')
        self.assertIsNone(resolve_pa_mart_listing(self.account, '100'))

    def test_other_accounts_alias_is_not_matched(self):
        other = self._listing(self.shop, '400')
        self._attempt(other, '100', '400')
        self.assertIsNone(resolve_pa_mart_listing(self.account, '100'))
        self.assertIsNone(resolve_pa_mart_listing(self.shop, '100'))

    def test_ledger_account_cannot_point_to_another_stores_listing(self):
        other = self._listing(self.shop, '400')
        self._attempt(other, '100', '400', integration_account=self.account)
        self.assertIsNone(resolve_pa_mart_listing(self.account, '100'))

    def test_foreign_ledger_account_cannot_alias_a_mart_listing(self):
        self._attempt(self.listing, '100', '300', integration_account=self.shop)
        self.assertIsNone(resolve_pa_mart_listing(self.account, '100'))

    def test_other_accounts_collision_does_not_shadow_the_mart_alias(self):
        self._history()
        other = self._listing(self.shop, '100')
        self._attempt(other, '100', '400')
        self.assertEqual(resolve_pa_mart_listing(self.account, '100'), self.listing)

    def test_pending_rejected_and_unverified_unknown_are_not_aliases(self):
        for status, old_id in (
            ('pending', '101'), ('rejected', '102'), ('unknown', '103'),
        ):
            self._attempt(
                self.listing, old_id, '201', status,
                verified_expires_at=None,
            )
            with self.subTest(status=status):
                self.assertIsNone(resolve_pa_mart_listing(self.account, old_id))
        self.assertIsNone(resolve_pa_mart_listing(self.account, '201'))

    def test_unknown_partial_verification_is_not_promoted_without_policy_approval(self):
        self._attempt(self.listing, '100', '200', 'unknown')
        self.assertIsNone(resolve_pa_mart_listing(self.account, '100'))
        self.assertIsNone(resolve_pa_mart_listing(self.account, '200'))

    def test_unknown_attempt_does_not_invalidate_an_independent_current_id(self):
        self._attempt(self.listing, '100', '300', 'unknown', verified_expires_at=None)
        self.assertEqual(resolve_pa_mart_listing(self.account, '300'), self.listing)

    def test_closed_listings_remain_resolvable_for_late_native_orders(self):
        self._history()
        Listing.objects.filter(pk=self.listing.pk).update(status=ListingStatus.CLOSED)
        self.assertEqual(resolve_pa_mart_listing(self.account, '100'), self.listing)

    def test_base_exact_lookup_uses_history_but_keeps_original_order_id(self):
        self._history()
        defaults = {'store_listing_id': '100', 'status': OrderStatus.DELIVERED}
        raw = SimpleNamespace(integration_account=self.account)
        BaseSyncService._link_listing(raw, defaults)
        self.assertEqual(defaults['listing'], self.listing)
        self.assertEqual(defaults['store_listing_id'], '100')

    def test_base_non_mart_lookup_remains_current_id_only(self):
        other = self._listing(self.shop, '400')
        self._attempt(other, '100', '400')
        raw = SimpleNamespace(integration_account=self.shop)
        defaults = {'store_listing_id': '100', 'status': OrderStatus.DELIVERED}
        BaseSyncService._link_listing(raw, defaults)
        self.assertNotIn('listing', defaults)
        defaults['store_listing_id'] = '400'
        BaseSyncService._link_listing(raw, defaults)
        self.assertEqual(defaults['listing'], other)

    def test_base_pending_mart_lookup_does_not_attach_stock(self):
        self._history()
        for offer_id in ('100', '300'):
            defaults = {'store_listing_id': offer_id, 'status': OrderStatus.PENDING}
            BaseSyncService._link_listing(SimpleNamespace(integration_account=self.account), defaults)
            self.assertNotIn('listing', defaults)
            self.assertNotIn('dropship_product', defaults)

    def _raw_order(self, status='Pending Buyer Inspection', offer_id='100'):
        return SimpleNamespace(
            integration_account=self.account,
            integration_account_id=self.account.pk,
            remote_id='900',
            payload={
                'order_id': '900', 'offer_id': offer_id,
                'status': status, 'price': '$10.00', 'product_type': 'Accounts',
            },
        )

    @patch('apps.posting.services.pool.checker.notify_sale')
    def test_late_native_order_links_same_listing_and_notifies_resolved_pk(self, notify):
        self._history()
        service = PlayerAuctionsOrderSyncService()
        with patch.object(service, '_match_or_create_owned_product', return_value=None):
            self.assertEqual(service.parse_and_apply(self._raw_order()), 'created')
            self.assertEqual(service.parse_and_apply(self._raw_order()), 'updated')
        order = Order.objects.get(store_order_id='900', integration_account=self.account)
        self.assertEqual(order.listing_id, self.listing.pk)
        self.assertEqual(order.store_listing_id, '100')
        self.assertEqual(order.raw_data['offer_id'], '100')
        self.assertEqual(Order.objects.count(), 1)
        self.assertEqual(notify.call_count, 2)
        for call in notify.call_args_list:
            self.assertEqual(call.args, (self.listing.pk,))
            self.assertEqual(call.kwargs['event_key'], f'playerauctions:{self.account.pk}:900')
            self.assertEqual(call.kwargs['order_id'], order.pk)

    @patch('apps.posting.services.pool.checker.notify_sale')
    def test_pending_payment_does_not_link_stock_close_listing_or_notify(self, notify):
        self._history()
        service = PlayerAuctionsOrderSyncService()
        with patch.object(service, '_match_or_create_owned_product') as owned_match:
            service.parse_and_apply(self._raw_order('Pending Payment'))
        owned_match.assert_not_called()
        notify.assert_not_called()
        order = Order.objects.get(store_order_id='900')
        self.assertEqual(order.status, OrderStatus.PENDING)
        self.assertIsNone(order.listing_id)
        self.assertIsNone(order.owned_product_id)
        self.assertIsNone(order.dropship_product_id)
        self.listing.refresh_from_db()
        self.assertEqual(self.listing.status, ListingStatus.LISTED)

    @patch('apps.posting.services.pool.checker.notify_sale')
    def test_later_confirmed_update_links_previously_pending_native_order(self, notify):
        self._history()
        service = PlayerAuctionsOrderSyncService()
        with patch.object(service, '_match_or_create_owned_product', return_value=None):
            service.parse_and_apply(self._raw_order('Pending Payment'))
            self.assertFalse(notify.called)
            service.parse_and_apply(self._raw_order())
        order = Order.objects.get(store_order_id='900')
        self.assertEqual(order.listing_id, self.listing.pk)
        self.assertEqual(order.store_listing_id, '100')
        self.assertEqual(order.status, OrderStatus.DELIVERED)
        notify.assert_called_once_with(
            self.listing.pk, event_key=f'playerauctions:{self.account.pk}:900', order_id=order.pk,
        )

    @patch('apps.posting.services.pool.checker.notify_sale')
    def test_native_collision_cannot_fall_back_to_title_or_notify(self, notify):
        self._history()
        self._listing(self.account, '100')
        service = PlayerAuctionsOrderSyncService()
        with patch.object(service, '_match_or_create_owned_product', return_value=None) as owned_match, \
                patch('apps.sync.services.playerauctions.orders.service.extract_tracking_code') as tracking:
            service.parse_and_apply(self._raw_order())
        owned_match.assert_not_called()
        tracking.assert_not_called()
        notify.assert_not_called()
        self.assertIsNone(Order.objects.get(store_order_id='900').listing_id)

    @patch('apps.posting.services.pool.checker.notify_sale')
    def test_collision_replay_clears_an_old_fk_and_does_not_notify(self, notify):
        self._history()
        Order.objects.create(
            integration_account=self.account, store_order_id='900',
            store_listing_id='100', listing=self.listing,
            status=OrderStatus.DISPUTED, price=Decimal('10.00'),
        )
        self._listing(self.account, '100')
        service = PlayerAuctionsOrderSyncService()
        with patch.object(service, '_match_or_create_owned_product', return_value=None):
            service.parse_and_apply(self._raw_order())
        self.assertIsNone(Order.objects.get(store_order_id='900').listing_id)
        notify.assert_not_called()

    @patch('apps.posting.services.pool.checker.notify_sale')
    def test_pending_replay_clears_preexisting_fk_before_order_signal(self, notify):
        self._history()
        Order.objects.create(
            integration_account=self.account, store_order_id='900',
            store_listing_id='100', listing=self.listing,
            status=OrderStatus.DISPUTED, price=Decimal('10.00'),
        )
        service = PlayerAuctionsOrderSyncService()
        with patch.object(service, '_match_or_create_owned_product') as owned_match:
            service.parse_and_apply(self._raw_order('Pending Payment'))
        self.assertIsNone(Order.objects.get(store_order_id='900').listing_id)
        self.listing.refresh_from_db()
        self.assertEqual(self.listing.status, ListingStatus.LISTED)
        owned_match.assert_not_called()
        notify.assert_not_called()

    @patch('apps.posting.services.pool.checker.notify_sale')
    def test_final_notification_rechecks_identity_instead_of_trusting_stale_fk(self, notify):
        self._history()
        self._listing(self.account, '100')
        order = SimpleNamespace(
            integration_account=self.account, integration_account_id=self.account.pk,
            store_listing_id='100', store_order_id='900', listing_id=self.listing.pk,
            status=OrderStatus.DELIVERED, pk=901,
        )
        BaseSyncService._notify_pool_on_sale(order)
        notify.assert_not_called()

    @patch('apps.posting.services.pool.checker.notify_sale')
    def test_non_mart_final_notification_remains_current_id_only(self, notify):
        other = self._listing(self.shop, '400')
        self._attempt(other, '100', '400')
        order = SimpleNamespace(
            integration_account=self.shop, integration_account_id=self.shop.pk,
            store_listing_id='100', store_order_id='900', status=OrderStatus.DELIVERED, pk=901,
        )
        BaseSyncService._notify_pool_on_sale(order)
        notify.assert_not_called()
        order.store_listing_id = '400'
        BaseSyncService._notify_pool_on_sale(order)
        notify.assert_called_once_with(
            other.pk, event_key=f'playerauctions:{self.shop.pk}:900', order_id=901,
        )


class PaMartIdentityBoundaryTests(SimpleTestCase):
    def setUp(self):
        self.account = SimpleNamespace(
            pk=1, slug='playerauctions-csgosmurfkings', provider='playerauctions',
        )

    def test_non_mart_account_gates_fail_without_database_access(self):
        for account in (
            None,
            SimpleNamespace(pk=1, slug='playerauctions-csgosmurfkings', provider='eldorado'),
            SimpleNamespace(pk=1, slug='playerauctions-shop', provider='playerauctions'),
            SimpleNamespace(pk=1, slug='csgosmurfkings', provider='playerauctions'),
            SimpleNamespace(pk=1, slug='ezsmurfmart', provider='playerauctions'),
            SimpleNamespace(pk=None, slug='playerauctions-csgosmurfkings', provider='playerauctions'),
        ):
            with self.subTest(account=account):
                self.assertFalse(is_pa_mart_identity_account(account))
                self.assertIsNone(resolve_pa_mart_listing(account, '100'))

    def test_invalid_numeric_ids_fail_without_database_access(self):
        for offer_id in (
            None, '', '0', 0, -1, True, False, '0100', ' 100', '100 ', '+100',
            '100\n', '１00', '١٠٠', '100.0', 100.0, [], {},
            '9' * 17, 10 ** 16, 10 ** 5000,
        ):
            self.assertIsNone(resolve_pa_mart_listing(self.account, offer_id))

    def test_bounded_integer_id_is_looked_up_as_exact_ascii_text(self):
        listing = SimpleNamespace(pk=9, id=9, dropship_product_id=None)
        with patch('apps.listings.models.Listing.objects') as listings, \
                patch('apps.sync.models.PaMartRenewalAttempt.objects') as attempts:
            listings.filter.return_value.filter.return_value.select_related.return_value.order_by.return_value.__getitem__.return_value = [listing]
            self.assertIs(resolve_pa_mart_listing(self.account, 100), listing)
        attempts.filter.assert_called_once_with(
            integration_account=self.account,
            listing__integration_account=self.account,
            status='succeeded',
        )
        self.assertEqual(attempts.filter.return_value.filter.call_args.args[0].children,
                         [('old_offer_id', '100'), ('new_offer_id', '100')])

    def test_base_dropship_link_uses_the_resolved_listing(self):
        dropship = object()
        listing = SimpleNamespace(id=9, dropship_product_id=10, dropship_product=dropship)
        defaults = {'store_listing_id': '100', 'status': OrderStatus.DELIVERED}
        with patch('apps.sync.services.pa_mart_offer_identity.resolve_pa_mart_listing', return_value=listing):
            BaseSyncService._link_listing(SimpleNamespace(integration_account=self.account), defaults)
        self.assertIs(defaults['listing'], listing)
        self.assertIs(defaults['dropship_product'], dropship)
        self.assertEqual(defaults['store_listing_id'], '100')

    @patch('apps.posting.services.pool.checker.notify_sale')
    def test_final_mart_notification_rejects_all_nonconfirmed_statuses(self, notify):
        order = SimpleNamespace(
            integration_account=self.account, store_listing_id='100',
        )
        with patch('apps.sync.services.pa_mart_offer_identity.resolve_pa_mart_listing') as resolver:
            for status in (OrderStatus.PENDING, OrderStatus.CANCELLED,
                           OrderStatus.REFUNDED, OrderStatus.DISPUTED):
                order.status = status
                BaseSyncService._notify_pool_on_sale(order)
        resolver.assert_not_called()
        notify.assert_not_called()

    def test_non_mart_parser_preserves_existing_owned_product_matching(self):
        service = PlayerAuctionsOrderSyncService()
        raw = SimpleNamespace(
            integration_account=SimpleNamespace(pk=2, provider='playerauctions', slug='playerauctions-shop'),
            integration_account_id=2, remote_id='900',
            payload={'offer_id': '100', 'status': 'Pending Payment', 'price': '$10.00'},
        )
        with patch.object(service, '_match_or_create_owned_product', return_value=None) as owned, \
                patch.object(service, '_upsert_order', return_value='created') as upsert:
            self.assertEqual(service.parse_and_apply(raw), 'created')
        owned.assert_called_once()
        self.assertNotIn('listing', upsert.call_args.args[1])
        self.assertEqual(upsert.call_args.args[1]['status'], OrderStatus.PENDING)
