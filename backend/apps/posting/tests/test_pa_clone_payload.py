"""PA clone/replacement must send a pre-built JSON payload (numeric gameId /
serverId), not an Excel row whose Game column holds the numeric id.

Regression: converting the JSON payload to an Excel row put the numeric gameId
into the ``Game`` column, which PARelayPoster._build_json_payload treats as a
game *name* — PlayerAuctions then rejected it with "Please select a game".
"""
from unittest.mock import patch

from apps.posting.services.stock.pa_relay_poster import PARelayPoster
from django.test import SimpleTestCase

_MOD = "apps.posting.services.stock.pa_relay_poster"


class PostBatchJsonPayloadTests(SimpleTestCase):
    def _payload(self):
        return {
            "gameId": 5917,
            "serverId": 5921,
            "categoryId": 5921,
            "title": "GTA V account",
            "offerDesc": "desc",
            "isAuto": True,
            "autoDelivery": {"loginName": "u", "password": "plainpw", "retypePassword": "plainpw"},
        }

    def test_json_payload_is_sent_as_is(self):
        captured = {}

        def _fake_post_one(self, token, store_slug, payload, *, cookie=None):
            captured["payload"] = payload
            return "offer-123", None

        poster = PARelayPoster(relay_url="http://relay", relay_secret="s")
        with patch.object(PARelayPoster, "_post_one", _fake_post_one), \
                patch(f"{_MOD}.pa_encrypt", return_value="ENC"):
            result = poster.post_batch("tok", "store", [self._payload()])

        self.assertEqual(result.successful.get(0), "offer-123")
        sent = captured["payload"]
        # The numeric identifiers are preserved (JSON branch), so PA gets a valid
        # game instead of the numeric id landing in a "Game name" field.
        self.assertEqual(sent["gameId"], 5917)
        self.assertEqual(sent["serverId"], 5921)
        # Plain password was encrypted before sending.
        self.assertEqual(sent["autoDelivery"]["password"], "ENC")

    def test_excel_row_would_reshape_game(self):
        """An Excel-style row (no serverId key) is reshaped by _build_json_payload —
        which is exactly why the clone path must NOT convert to an Excel row."""
        poster = PARelayPoster(relay_url="http://relay", relay_secret="s")
        built = poster._build_json_payload({"Game": "5917", "Server": "5921", "Title": "t"})
        # The numeric '5917' is treated as a game *name* and does not resolve to
        # the real GTA V game id — proving the old conversion was broken.
        self.assertNotEqual(built.get("gameId"), 5917)
