"""ImageShack adapter — implements AlbumUploader protocol.

Includes a circuit breaker: after ``MAX_CONSECUTIVE_FAILURES`` consecutive
failures the adapter stops attempting uploads for the remainder of the
process lifetime and returns empty results immediately.  This prevents
wasting time on DNS / connectivity errors that won't resolve mid-session.
"""

from __future__ import annotations

import logging
import mimetypes
import os
import secrets
import string
import threading

logger = logging.getLogger(__name__)

_ALBUM_CHARS = string.ascii_uppercase + string.digits

# Circuit breaker: stop trying after this many consecutive failures
MAX_CONSECUTIVE_FAILURES = 2


class ImageShackAlbumUploader:
    """Implements AlbumUploader protocol using ImageShackFacade.

    Uploads images to a single auto-generated album.
    Returns the album page URL.

    Circuit breaker: after ``MAX_CONSECUTIVE_FAILURES`` consecutive failures
    (e.g. DNS resolution errors), all subsequent calls return ``""``
    immediately without attempting network calls.
    """

    def __init__(self, facade, album_prefix: str = "AC") -> None:
        self._facade = facade
        self._album_prefix = album_prefix.strip().upper() or "AC"
        self._consecutive_failures = 0
        self._circuit_open = False
        self._lock = threading.Lock()

    def upload_album_from_paths(self, image_paths: list[str]) -> str:
        """Upload all images into an album and return album URL."""
        if self._circuit_open:
            return ""

        suffix = ''.join(secrets.choice(_ALBUM_CHARS) for _ in range(6))
        album_title = f"{self._album_prefix}-{suffix}"

        album_id: str = ""
        had_failure = False

        for path in image_paths:
            if not os.path.isfile(path):
                logger.warning("File not found, skipping: %s", path)
                continue
            try:
                file_name = os.path.basename(path)
                content_type = mimetypes.guess_type(path)[0] or 'image/png'

                with open(path, 'rb') as f:
                    image_data = f.read()

                result = self._facade.upload_image(
                    image_data, file_name, content_type, album=album_title,
                )

                if result.ok and result.data and not album_id:
                    images = result.data.get('images', [])
                    if images:
                        album_info = images[0].get('album', {})
                        if isinstance(album_info, dict):
                            album_id = str(album_info.get('id', ''))
                        elif album_info:
                            album_id = str(album_info)

                if not result.ok:
                    error_msg = result.error.message if result.error else 'unknown'
                    logger.warning("ImageShack upload failed for %s: %s", path, error_msg)
                    had_failure = True
                    # First image failed — skip remaining (likely same error)
                    if not album_id:
                        break

            except Exception as exc:
                logger.warning("ImageShack upload failed for %s: %s", path, exc)
                had_failure = True
                # Connection/DNS error on first image — skip remaining
                if not album_id:
                    break

        # Update circuit breaker state
        with self._lock:
            if had_failure and not album_id:
                self._consecutive_failures += 1
                if self._consecutive_failures >= MAX_CONSECUTIVE_FAILURES:
                    self._circuit_open = True
                    logger.warning(
                        "ImageShack circuit breaker OPEN after %d consecutive failures "
                        "— skipping all future uploads this session",
                        self._consecutive_failures,
                    )
            else:
                self._consecutive_failures = 0

        if album_id:
            return f"https://imageshack.com/a/{album_id}"
        return ""
