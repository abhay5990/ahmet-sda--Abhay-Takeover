"""PA offer description formatting: preserve seller line breaks, drop emoji/URLs."""
from types import SimpleNamespace

from payload_pipeline.marketplaces.playerauctions import (
    _format_offer_description,
    _normalize_blank_lines,
)

# The exact multi-line, emoji-bulleted description a seller pasted.
_SELLER_DESC = (
    "\U0001F4CC Don't change the details without checking the account.\n"
    "\n\n"
    "\U0001F3AE Please be aware that you should be using an ENHANCED version.\n"
    "\n\n"
    "\u2705GTA-V STEAM  ENHANCED Version\n"
    "\u2705 New Mansion :- 3x\n"
    "\u2705 100m Pure Cash\n"
    "\u2705  250 Million in Form of Boxes\n"
    "\u2705 150 modified cars, each with F1/Benny wheels\n"
    "\u2705 20 Modded Outfits\n"
    "\u2705 Max stats\n"
    "\n\n\n"
    "\U0001F6A8 Please do not add funds. See https://example.com/policy for details.\n"
)


def _listing(album_url: str = ""):
    return SimpleNamespace(media=SimpleNamespace(album_url=album_url))


class TestFormatOfferDescription:
    def test_bulk_path_keeps_real_newlines(self):
        out = _format_offer_description(_SELLER_DESC, _listing(), html_breaks=False)
        assert "<br>" not in out
        assert "\n" in out
        # Each bullet ends up on its own line.
        assert "* 100m Pure Cash" in out
        assert "* Max stats" in out

    def test_json_path_uses_html_breaks(self):
        out = _format_offer_description(_SELLER_DESC, _listing(), html_breaks=True)
        assert "<br>" in out
        assert "\n" not in out

    def test_emojis_replaced_and_urls_stripped(self):
        out = _format_offer_description(_SELLER_DESC, _listing(), html_breaks=False)
        assert "\u2705" not in out and "\U0001F4CC" not in out
        assert "https://" not in out
        assert "example.com/policy" in out  # URL kept, scheme removed

    def test_excessive_blank_lines_collapsed(self):
        out = _format_offer_description(_SELLER_DESC, _listing(), html_breaks=False)
        assert "\n\n\n" not in out  # at most one blank line between sections

    def test_album_link_prepended_when_present(self):
        out = _format_offer_description(
            "body text", _listing("https://imageshack.com/a/YfX57"), html_breaks=False,
        )
        assert out.startswith("Images Link:")
        assert "imageshack.com/a/YfX57" in out
        assert "https://" not in out


class TestNormalizeBlankLines:
    def test_collapses_and_trims(self):
        assert _normalize_blank_lines("a\n\n\n\nb") == "a\n\nb"
        assert _normalize_blank_lines("a   \nb") == "a\nb"
        assert _normalize_blank_lines("\n\na\n\n") == "a"
