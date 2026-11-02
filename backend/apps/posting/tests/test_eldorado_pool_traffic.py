"""Pool restock must stay inside Eldorado's per-store quota (2 Nov 2026)."""

from types import SimpleNamespace

from django.test import SimpleTestCase

from apis_sdk.core.enums import ErrorCategory
from apis_sdk.core.result import ApiResult

from apps.posting.services.offer_editor import build_eldorado_full_update_payload
from apps.posting.services.pool.checker import _eldorado_offer_unchanged
from apps.posting.services.pool.replenisher import _eldorado_failure_kind


def _err(category, status=None, details=None, message='x'):
    return ApiResult.from_error(category, message, status_code=status, provider='eldorado', details=details)


class FailureKindTests(SimpleTestCase):
    def test_cowboy_and_governor_refusal_mean_wait(self):
        self.assertEqual(_eldorado_failure_kind(_err(ErrorCategory.RATE_LIMIT, 429)), 'paused')
        self.assertEqual(
            _eldorado_failure_kind(_err(ErrorCategory.RATE_LIMIT, details={'governor': 'write_budget'})),
            'paused',
        )

    def test_content_rejections_stop_retrying(self):
        self.assertEqual(_eldorado_failure_kind(_err(ErrorCategory.VALIDATION, 400)), 'rejected')
        self.assertEqual(
            _eldorado_failure_kind(_err(ErrorCategory.UNKNOWN, message='credential entry has no recognisable account login and password')),
            'rejected',
        )

    def test_network_and_server_errors_are_other(self):
        self.assertEqual(_eldorado_failure_kind(_err(ErrorCategory.NETWORK)), 'other')
        self.assertEqual(_eldorado_failure_kind(_err(ErrorCategory.SERVER_ERROR, 502)), 'other')


class FullUpdatePayloadTests(SimpleTestCase):
    def test_pool_update_sends_complete_offer_not_partial(self):
        listing = SimpleNamespace(raw_data={
            'gameId': '106', 'category': 'Account', 'offerTitle': 'GTA', 'description': 'd',
            'pricePerUnit': {'amount': 9.5, 'currency': 'USD'}, 'quantity': 1,
            'tradeEnvironmentValues': [{'id': 2}],
            'attributes': [{'id': 'gta-platform', 'type': 'Select', 'value': 'pc'}],
        })
        payload = build_eldorado_full_update_payload(listing, ['Login: a\nPassword: b', 'Login: c\nPassword: d'])
        self.assertEqual(payload['details']['pricing']['quantity'], 2)
        self.assertEqual(payload['details']['offerTitle'], 'GTA')
        self.assertEqual(payload['augmentedGame']['gameId'], '106')
        self.assertEqual(payload['augmentedGame']['tradeEnvironmentId'], '2')
        self.assertEqual(len(payload['accountSecretDetails']), 2)


class BulkCheckTests(SimpleTestCase):
    def _offer(self, count, threshold=10):
        return SimpleNamespace(
            listing=SimpleNamespace(store_listing_id='o1'),
            current_remote_count=count, threshold=threshold,
        )

    def test_unchanged_full_offer_skips_the_per_offer_read(self):
        self.assertTrue(_eldorado_offer_unchanged(self._offer(40), {'o1': 40}))

    def test_changed_low_or_missing_offers_get_the_full_check(self):
        self.assertFalse(_eldorado_offer_unchanged(self._offer(40), {'o1': 39}))
        self.assertFalse(_eldorado_offer_unchanged(self._offer(8), {'o1': 8}))
        self.assertFalse(_eldorado_offer_unchanged(self._offer(40), {}))
        self.assertFalse(_eldorado_offer_unchanged(self._offer(None), {'o1': 40}))
