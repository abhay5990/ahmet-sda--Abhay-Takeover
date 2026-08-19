from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import Mock, patch

from django.test import SimpleTestCase
from django.utils import timezone

from apps.listings.enums import ListingStatus
from apps.posting.services import offer_editor
from apps.posting.services.relist import (
    _handoff_active_offer_replacement,
    _playerauctions_expiry_after_relist,
)


class _Saved:
    def __init__(self, **kwargs):
        self.saved_fields = []
        for key, value in kwargs.items():
            setattr(self, key, value)

    def save(self, *, update_fields):
        self.saved_fields.append(tuple(update_fields))


class _EmptyQuery:
    def select_related(self, *args):
        return self

    def first(self):
        return None


class _OfferQuery:
    def __init__(self, offers):
        self.offers = offers

    def select_related(self, *args):
        return self.offers


class PlayerAuctionsReplacementOfferHandoffTests(SimpleTestCase):
    def test_handoff_moves_clone_and_exact_item_to_replacement_offer(self):
        old_listing = object()
        new_listing = object()
        item = _Saved(target_offer_id='294100001')
        active_offer = _Saved(
            listing=old_listing,
            store_listing_id='294100001',
            pool_item=item,
            pool_item_id=21,
        )

        _handoff_active_offer_replacement(
            [active_offer],
            '294100002',
            new_listing=new_listing,
        )

        self.assertIs(active_offer.listing, new_listing)
        self.assertEqual(active_offer.store_listing_id, '294100002')
        self.assertEqual(item.target_offer_id, '294100002')
        self.assertIn('listing', active_offer.saved_fields[0])
        self.assertEqual(item.saved_fields[0], ('target_offer_id', 'updated_at'))

    def test_replacement_expiry_uses_response_or_duration_from_new_listed_time(self):
        renewed_at = timezone.now()
        expiry = _playerauctions_expiry_after_relist(
            {'details': {'offerDuration': 30}},
            {},
            renewed_at,
        )

        self.assertEqual(expiry, renewed_at + timedelta(days=30))

    def test_pa_edit_refreshes_lifecycle_and_handoffs_the_new_offer_id(self):
        item = _Saved(target_offer_id='294100001')
        active_offer = _Saved(
            store_listing_id='294100001',
            pool_item=item,
            pool_item_id=21,
            pool_offer=SimpleNamespace(pool=object()),
            pool_offer_id=1,
            pool=None,
        )
        product = SimpleNamespace()
        listing = _Saved(
            pk=8,
            store_listing_id='294100001',
            integration_account=SimpleNamespace(
                provider='playerauctions',
                credential=object(),
            ),
            raw_data={'payload': {'details': {'offerDuration': 30}}},
            listing_owned_products=SimpleNamespace(
                select_related=lambda *args: SimpleNamespace(first=lambda: SimpleNamespace(owned_product=product)),
            ),
            status=ListingStatus.LISTED,
            removed_at=None,
            listed_at=None,
            marketplace_expires_at=None,
        )
        provider = SimpleNamespace(
            delete_listing=Mock(return_value=SimpleNamespace(ok=True)),
            create_listing=Mock(return_value=SimpleNamespace(
                ok=True,
                data={'offer_id': '294100002'},
            )),
        )
        payload = {
            'title': 'Original title',
            'offerDesc': 'Original description',
            'price': 20,
            'details': {'offerDuration': 30},
            'autoDelivery': {},
        }
        active_offer_manager = SimpleNamespace(filter=lambda **kwargs: _OfferQuery([active_offer]))
        pool_offer_manager = SimpleNamespace(filter=lambda **kwargs: _EmptyQuery())

        with patch(
            'core.marketplace.payload_extractor.extract_create_payload',
            return_value=payload,
        ), patch(
            'apps.posting.services.pool.replenisher._apply_pa_auto_delivery_credentials',
        ), patch(
            'apps.posting.services.offer_editor.build_proxy_pool', return_value=None,
        ), patch(
            'apps.posting.services.offer_editor.get_group_name', return_value='',
        ), patch(
            'apps.posting.services.offer_editor.get_or_build_client', return_value=object(),
        ), patch(
            'apps.posting.services.offer_editor.get_provider', return_value=provider,
        ), patch(
            'apps.posting.services.offer_editor._log',
        ), patch.object(offer_editor.PoolOffer, 'objects', pool_offer_manager), patch.object(
            offer_editor.OfferPoolActiveOffer, 'objects', active_offer_manager,
        ), patch.object(
            offer_editor.OfferPool,
            'objects',
            SimpleNamespace(filter=lambda **kwargs: _EmptyQuery()),
        ):
            result = offer_editor._edit_pa_single(listing, {'title': 'Updated title'}, listing.integration_account)

        self.assertTrue(result.ok, result.error)
        self.assertEqual(result.new_offer_id, '294100002')
        self.assertEqual(provider.delete_listing.call_args.args[1], '294100001')
        self.assertEqual(listing.store_listing_id, '294100002')
        self.assertEqual(listing.status, ListingStatus.LISTED)
        self.assertIsNotNone(listing.listed_at)
        self.assertEqual(
            listing.marketplace_expires_at,
            listing.listed_at + timedelta(days=30),
        )
        self.assertEqual(active_offer.store_listing_id, '294100002')
        self.assertEqual(item.target_offer_id, '294100002')
