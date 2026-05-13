"""Download images from an Imgur album URL to a local directory."""

from __future__ import annotations

import logging
import re
import time
from pathlib import Path
from typing import Any, Protocol

logger = logging.getLogger(__name__)

_ALBUM_HASH_RE = re.compile(r"imgur\.com/(?:a|gallery)/([a-zA-Z0-9]+)")

# Browser-like headers to avoid rate limiting on Imgur's public API
_BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/143.0.0.0 Safari/537.36"
    ),
    "Accept": "*/*",
    "Accept-Language": "en,tr-TR;q=0.9,tr;q=0.8,en-US;q=0.7",
    "Origin": "https://imgur.com",
    "Referer": "https://imgur.com/",
    "sec-ch-ua": '"Google Chrome";v="143", "Chromium";v="143", "Not A(Brand";v="24"',
    "sec-ch-ua-mobile": "?0",
    "sec-ch-ua-platform": '"Windows"',
    "sec-fetch-dest": "empty",
    "sec-fetch-mode": "cors",
    "sec-fetch-site": "same-site",
}


class HttpGet(Protocol):
    """Minimal HTTP GET protocol — caller injects the implementation."""

    def get(self, url: str, *, headers: dict[str, str] | None = None,
            params: dict[str, str] | None = None, timeout: float = 30.0) -> Any:
        """Return a response-like object with .status_code, .json(), .content."""
        ...


def extract_album_hash(url: str) -> str | None:
    """Extract the album hash from an Imgur album/gallery URL."""
    match = _ALBUM_HASH_RE.search(url)
    return match.group(1) if match else None


def download_album(
    album_url: str,
    output_dir: str,
    *,
    client_id: str,
    http: HttpGet | None = None,
) -> list[str]:
    """Download all images from an Imgur album to output_dir.

    Args:
        album_url: Full Imgur album URL (e.g. https://imgur.com/a/abc123).
        output_dir: Local directory to save images.
        client_id: Imgur API Client-ID for authentication.
        http: Optional HTTP client (defaults to requests).

    Returns:
        List of saved file paths.
    """
    album_hash = extract_album_hash(album_url)
    if not album_hash:
        logger.warning("Could not extract album hash from URL: %s", album_url)
        return []

    if http is None:
        import requests as _requests
        http = _requests  # type: ignore[assignment]

    # Use Imgur's public post/v1 endpoint (same as their web frontend).
    # The v3 API aggressively rate-limits with 429 errors.
    api_url = f"https://api.imgur.com/post/v1/albums/{album_hash}"
    params = {"client_id": client_id, "include": "media,adconfig,account,tags"}

    try:
        resp = http.get(api_url, headers=_BROWSER_HEADERS, params=params, timeout=30.0)
        if resp.status_code != 200:
            logger.warning("Imgur API returned %d for album %s", resp.status_code, album_hash)
            return []
        data = resp.json()
    except Exception as exc:
        logger.warning("Failed to fetch Imgur album %s: %s", album_hash, exc)
        return []

    media = data.get("media", [])
    if not media:
        return []

    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    saved: list[str] = []
    for i, item in enumerate(media):
        if item.get("type") != "image":
            continue

        link = item.get("url")
        if not link:
            continue

        ext = item.get("ext", "png")
        filename = f"imgur_{i:02d}.{ext}"
        file_path = output_path / filename

        try:
            img_resp = http.get(link, headers=_BROWSER_HEADERS, timeout=30.0)
            if img_resp.status_code == 200:
                file_path.write_bytes(img_resp.content)
                saved.append(str(file_path))
            elif img_resp.status_code == 429:
                logger.warning("Rate limited downloading image %d, retrying after 2s...", i)
                time.sleep(2)
                img_resp = http.get(link, headers=_BROWSER_HEADERS, timeout=30.0)
                if img_resp.status_code == 200:
                    file_path.write_bytes(img_resp.content)
                    saved.append(str(file_path))
            else:
                logger.warning("Failed to download image %s (status %d)", link, img_resp.status_code)
        except Exception as exc:
            logger.warning("Error downloading %s: %s", link, exc)

        # Small delay between downloads to avoid rate limiting
        if i < len(media) - 1:
            time.sleep(0.1)

    return saved
