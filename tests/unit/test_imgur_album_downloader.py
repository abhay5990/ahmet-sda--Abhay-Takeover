"""Unit tests for ImgurAlbumDownloader adapter.

Usage:
    cd <project-root>
    venv/bin/python -m pytest tests/unit/test_imgur_album_downloader.py -v
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# ── path setup ────────────────────────────────────────────────────────────────
_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_ROOT / "libs" / "apis_sdk"))
sys.path.insert(0, str(_ROOT / "backend"))
# ─────────────────────────────────────────────────────────────────────────────

from apps.posting.pipeline.media.imgur_downloader_adapter import (  # noqa: E402
    ImgurAlbumDownloader,
    _extract_hash,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_facade(ok: bool, media: list[dict] | None = None, error_msg: str = "err"):
    facade = MagicMock()
    result = MagicMock()
    result.ok = ok
    result.data = media or []
    result.error = MagicMock()
    result.error.message = error_msg
    facade.fetch_album_media.return_value = result
    return facade


def _make_http_response(status: int, content: bytes = b""):
    resp = MagicMock()
    resp.status_code = status
    resp.content = content
    return resp


_PATCH = "apps.posting.pipeline.media.imgur_downloader_adapter"


# ---------------------------------------------------------------------------
# _extract_hash
# ---------------------------------------------------------------------------

class TestExtractHash:
    def test_standard_album_url(self):
        assert _extract_hash("https://imgur.com/a/abc123") == "abc123"

    def test_gallery_url(self):
        assert _extract_hash("https://imgur.com/gallery/XyZ789") == "XyZ789"

    def test_invalid_url_returns_none(self):
        assert _extract_hash("https://example.com/photos/abc") is None

    def test_empty_string_returns_none(self):
        assert _extract_hash("") is None


# ---------------------------------------------------------------------------
# download_album — URL / facade failures
# ---------------------------------------------------------------------------

class TestDownloadAlbumFailures:
    def test_invalid_url_returns_empty(self, tmp_path):
        facade = _make_facade(ok=True, media=[])
        downloader = ImgurAlbumDownloader(facade)
        result = downloader.download_album("https://example.com/photos/abc", str(tmp_path))
        assert result == []
        facade.fetch_album_media.assert_not_called()

    def test_facade_error_returns_empty(self, tmp_path):
        facade = _make_facade(ok=False, error_msg="API error")
        downloader = ImgurAlbumDownloader(facade)
        result = downloader.download_album("https://imgur.com/a/abc123", str(tmp_path))
        assert result == []

    def test_empty_media_returns_empty(self, tmp_path):
        facade = _make_facade(ok=True, media=[])
        downloader = ImgurAlbumDownloader(facade)
        result = downloader.download_album("https://imgur.com/a/abc123", str(tmp_path))
        assert result == []

    def test_correct_hash_passed_to_facade(self, tmp_path):
        facade = _make_facade(ok=True, media=[])
        downloader = ImgurAlbumDownloader(facade)
        downloader.download_album("https://imgur.com/a/myHash42", str(tmp_path))
        facade.fetch_album_media.assert_called_once_with("myHash42")


# ---------------------------------------------------------------------------
# download_album — happy path
# ---------------------------------------------------------------------------

class TestDownloadAlbumSuccess:
    def test_single_image_saved(self, tmp_path):
        media = [{"type": "image", "url": "https://i.imgur.com/img.png", "ext": "png"}]
        facade = _make_facade(ok=True, media=media)
        downloader = ImgurAlbumDownloader(facade)

        with patch(f"{_PATCH}.requests.get", return_value=_make_http_response(200, b"PNG")), \
             patch(f"{_PATCH}.time.sleep"):
            result = downloader.download_album("https://imgur.com/a/abc123", str(tmp_path))

        assert len(result) == 1
        assert (tmp_path / "imgur_00.png").read_bytes() == b"PNG"

    def test_multiple_images_saved(self, tmp_path):
        media = [
            {"type": "image", "url": "https://i.imgur.com/a.jpg", "ext": "jpg"},
            {"type": "image", "url": "https://i.imgur.com/b.png", "ext": "png"},
        ]
        facade = _make_facade(ok=True, media=media)
        downloader = ImgurAlbumDownloader(facade)

        responses = [_make_http_response(200, b"A"), _make_http_response(200, b"B")]
        with patch(f"{_PATCH}.requests.get", side_effect=responses), \
             patch(f"{_PATCH}.time.sleep"):
            result = downloader.download_album("https://imgur.com/a/abc123", str(tmp_path))

        assert len(result) == 2
        assert (tmp_path / "imgur_00.jpg").read_bytes() == b"A"
        assert (tmp_path / "imgur_01.png").read_bytes() == b"B"

    def test_output_dir_created(self, tmp_path):
        nested = tmp_path / "x" / "y"
        media = [{"type": "image", "url": "https://i.imgur.com/img.png", "ext": "png"}]
        facade = _make_facade(ok=True, media=media)
        downloader = ImgurAlbumDownloader(facade)

        with patch(f"{_PATCH}.requests.get", return_value=_make_http_response(200, b"DATA")), \
             patch(f"{_PATCH}.time.sleep"):
            downloader.download_album("https://imgur.com/a/abc123", str(nested))

        assert nested.exists()

    def test_non_image_type_skipped(self, tmp_path):
        media = [
            {"type": "video", "url": "https://i.imgur.com/vid.mp4", "ext": "mp4"},
            {"type": "image", "url": "https://i.imgur.com/img.png", "ext": "png"},
        ]
        facade = _make_facade(ok=True, media=media)
        downloader = ImgurAlbumDownloader(facade)

        with patch(f"{_PATCH}.requests.get", return_value=_make_http_response(200, b"IMG")), \
             patch(f"{_PATCH}.time.sleep"):
            result = downloader.download_album("https://imgur.com/a/abc123", str(tmp_path))

        assert len(result) == 1
        assert result[0].endswith("imgur_01.png")

    def test_item_without_url_skipped(self, tmp_path):
        media = [
            {"type": "image", "ext": "png"},
            {"type": "image", "url": "https://i.imgur.com/img.png", "ext": "png"},
        ]
        facade = _make_facade(ok=True, media=media)
        downloader = ImgurAlbumDownloader(facade)

        with patch(f"{_PATCH}.requests.get", return_value=_make_http_response(200, b"DATA")), \
             patch(f"{_PATCH}.time.sleep"):
            result = downloader.download_album("https://imgur.com/a/abc123", str(tmp_path))

        assert len(result) == 1


# ---------------------------------------------------------------------------
# download_album — retry on 429
# ---------------------------------------------------------------------------

class TestRateLimitRetry:
    def test_429_then_200_saves_image(self, tmp_path):
        media = [{"type": "image", "url": "https://i.imgur.com/img.png", "ext": "png"}]
        facade = _make_facade(ok=True, media=media)
        downloader = ImgurAlbumDownloader(facade)

        responses = [_make_http_response(429), _make_http_response(200, b"OK")]
        with patch(f"{_PATCH}.requests.get", side_effect=responses), \
             patch(f"{_PATCH}.time.sleep"):
            result = downloader.download_album("https://imgur.com/a/abc123", str(tmp_path))

        assert len(result) == 1
        assert (tmp_path / "imgur_00.png").read_bytes() == b"OK"

    def test_all_retries_exhausted_skips_image(self, tmp_path):
        media = [{"type": "image", "url": "https://i.imgur.com/img.png", "ext": "png"}]
        facade = _make_facade(ok=True, media=media)
        downloader = ImgurAlbumDownloader(facade)

        with patch(f"{_PATCH}.requests.get", return_value=_make_http_response(429)), \
             patch(f"{_PATCH}.time.sleep"):
            result = downloader.download_album("https://imgur.com/a/abc123", str(tmp_path))

        assert result == []

    def test_network_exception_skips_image(self, tmp_path):
        media = [{"type": "image", "url": "https://i.imgur.com/img.png", "ext": "png"}]
        facade = _make_facade(ok=True, media=media)
        downloader = ImgurAlbumDownloader(facade)

        with patch(f"{_PATCH}.requests.get", side_effect=ConnectionError("timeout")), \
             patch(f"{_PATCH}.time.sleep"):
            result = downloader.download_album("https://imgur.com/a/abc123", str(tmp_path))

        assert result == []
