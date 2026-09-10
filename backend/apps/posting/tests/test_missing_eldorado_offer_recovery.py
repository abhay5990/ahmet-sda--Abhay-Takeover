from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase

from apps.posting.services.pool.checker import _recover_missing_offer


class MissingEldoradoOfferRecoveryTests(SimpleTestCase):
    def _pool(self):
        store = SimpleNamespace(credential=object())
        listing = SimpleNamespace(
            store_listing_id="old-offer",
            raw_data={"legacy": "payload"},
        )
        pool_offer = object()
        pool = MagicMock(
            pk=77,
            store=store,
            listing=listing,
            pool_offer=pool_offer,
            target_count=2,
        )
        return pool

    @patch("apps.posting.services.pool.checker.PostingLog.objects.create")
    @patch("apps.posting.services.pool.checker.claim_pending_items", return_value=[])
    @patch(
        "apps.posting.services.pool.checker.extract_create_payload",
        return_value={"accountSecretDetails": ["legacy-sold-credential"]},
    )
    def test_missing_offer_with_no_pending_stock_never_uses_legacy_credentials(
        self,
        extract_payload,
        claim_pending,
        _log,
    ):
        pool = self._pool()

        with patch(
            "apps.posting.services.pool.checker._create_eldorado_offer"
        ) as create_offer:
            result = _recover_missing_offer(pool, "eldorado")

        self.assertEqual(result, 0)
        claim_pending.assert_called_once_with(pool.pool_offer, pool.target_count)
        create_offer.assert_not_called()

    @patch("apps.posting.services.pool.checker.PostingLog.objects.create")
    @patch("apps.posting.services.pool.checker.replenish_pool_offer")
    @patch("apps.posting.services.pool.checker._create_eldorado_offer", return_value=1)
    @patch("apps.posting.services.pool.checker.get_or_build_client")
    @patch("apps.posting.services.pool.checker.get_group_name", return_value=None)
    @patch("apps.posting.services.pool.checker.build_proxy_pool")
    @patch(
        "apps.posting.services.pool.formatter.format_credential_for_marketplace",
        return_value="fresh-pending-credential",
    )
    @patch("apps.posting.services.pool.checker.claim_pending_items")
    @patch(
        "apps.posting.services.pool.checker.extract_create_payload",
        return_value={"accountSecretDetails": ["legacy-sold-credential"]},
    )
    def test_missing_offer_uses_only_newly_claimed_pending_stock(
        self,
        extract_payload,
        claim_pending,
        format_credential,
        build_proxy_pool,
        get_group_name,
        get_client,
        create_offer,
        replenish,
        _log,
    ):
        pool = self._pool()
        pending_item = SimpleNamespace(owned_product=object())
        claim_pending.return_value = [pending_item]

        result = _recover_missing_offer(pool, "eldorado")

        self.assertEqual(result, 1)
        create_offer.assert_called_once()
        args = create_offer.call_args.args
        self.assertEqual(args[3], ["fresh-pending-credential"])
        self.assertEqual(args[4], [pending_item])
        self.assertNotIn("legacy-sold-credential", args[3])
        pool.save.assert_called_once()
        replenish.assert_called_once_with(pool.pool_offer)
