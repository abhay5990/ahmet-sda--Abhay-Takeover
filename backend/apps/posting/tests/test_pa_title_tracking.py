from unittest import TestCase

from apps.posting.services.stock.pa_tracking import (
    append_tracking_code_for_code,
    extract_tracking_code,
)


class PlayerAuctionsTitleTrackingTests(TestCase):
    def test_visible_title_edit_keeps_the_same_pool_clone_code(self):
        code = '#RXV6OV'

        updated_title = append_tracking_code_for_code(
            '[PS4] Updated GTA V account title',
            code,
        )

        self.assertEqual(extract_tracking_code(updated_title), code)
        self.assertEqual(updated_title.count(code), 1)
