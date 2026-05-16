"""Imgur album downloader adapter.

Bridges the ``AlbumDownloader`` pipeline protocol to the Imgur SDK facade,
downloading album images to a local directory for further processing.
"""

from __future__ import annotations

import logging
import re
import time
from pathlib import Path

import requests

logger = logging.getLogger(__name__)

# Regex for imgur.com/a/<hash> or imgur.com/gallery/<hash>
_ALBUM_RE = re.compile(r"imgur\.com/(?:a|gallery)/([A-Za-z0-9]+)")

_MAX_RETRIES = 3
_RETRY_BACKOFF = 2.0  # seconds between 429 retries
_DOWNLOAD_TIMEOUT = 30


def _extract_hash(url: str) -> str | None:
    """Extract the album/gallery hash from an Imgur URL."""
    if not url:
        return None
    m = _ALBUM_RE.search(url)
    return m.group(1) if m else None


class ImgurAlbumDownloader:
    """Download all images from an Imgur album to a local directory.

    Implements the ``AlbumDownloader`` protocol expected by payload_pipeline.
    """

    def __init__(self, facade, cdn_proxy_url: str | None = None) -> None:
        self._facade = facade
        self._proxies = {"https": cdn_proxy_url, "http": cdn_proxy_url} if cdn_proxy_url else None

    def download_album(self, album_url: str, output_dir: str) -> list[str]:
        """Download all images from *album_url* into *output_dir*.

        Returns a list of absolute paths to saved files.
        Returns an empty list on failure — never raises.
        """
        album_hash = _extract_hash(album_url)
        if not album_hash:
            logger.warning("Could not extract album hash from URL: %s", album_url)
            return []

        result = self._facade.fetch_album_media(album_hash)
        if not result.ok:
            logger.warning("Imgur API error for %s: %s", album_hash, result.error.message)
            return []

        media_items = result.data or []
        if not media_items:
            logger.info("Album %s contains no media items", album_hash)
            return []

        out = Path(output_dir)
        out.mkdir(parents=True, exist_ok=True)

        saved: list[str] = []
        for idx, item in enumerate(media_items):
            if item.get("type") != "image":
                continue
            url = item.get("url")
            if not url:
                continue
            ext = item.get("ext", "png")
            dest = out / f"imgur_{idx:02d}.{ext}"

            data = self._download_with_retry(url)
            if data is None:
                continue

            dest.write_bytes(data)
            saved.append(str(dest))

        logger.info("Downloaded %d/%d images from album %s", len(saved), len(media_items), album_hash)
        return saved

    def _download_with_retry(self, url: str) -> bytes | None:
        """Download a single image URL with retry on 429."""
        for attempt in range(_MAX_RETRIES):
            try:
                resp = requests.get(url, timeout=_DOWNLOAD_TIMEOUT, proxies=self._proxies)
                if resp.status_code == 429:
                    time.sleep(_RETRY_BACKOFF * (attempt + 1))
                    continue
                if resp.status_code != 200:
                    logger.warning("HTTP %d for %s", resp.status_code, url)
                    return None
                return resp.content
            except Exception as exc:
                logger.warning("Download error for %s: %s", url, exc)
                return None
        logger.warning("All retries exhausted for %s", url)
        return None
