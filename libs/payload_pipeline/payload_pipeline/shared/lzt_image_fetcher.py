"""Protocol-based image fetcher that delegates to an ``ImageFetcher`` adapter.

The fetcher no longer knows *how* to talk to the LZT API — it only knows
how to call ``fetcher.fetch_image(category, item_id) -> bytes | None`` and
persist the result to disk.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..core.contracts import ImageFetcher

logger = logging.getLogger(__name__)


class LztImageFetcher:
    """Thin file-persistence wrapper around an ``ImageFetcher`` protocol.

    The class accepts any object that satisfies ``ImageFetcher`` (i.e. has a
    ``fetch_image(category, item_id) -> bytes | None`` method).
    """

    def __init__(self, fetcher: ImageFetcher | None = None) -> None:
        self.fetcher = fetcher

    def fetch_to_file(
        self,
        *,
        category: str,
        item_id: str,
        output_path: Path,
    ) -> bool:
        """Download an image via the injected fetcher and save it to *output_path*.

        Returns ``True`` on success, ``False`` on failure.
        """
        if self.fetcher is None:
            logger.warning("No image fetcher configured — skipping %s/%s", category, item_id)
            return False

        try:
            data = self.fetcher.fetch_image(category, item_id)
        except Exception as exc:
            logger.warning("Image fetcher error for %s/%s: %s", category, item_id, exc)
            return False

        if data is None:
            return False

        try:
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_bytes(data)
            return True
        except Exception as exc:
            logger.warning("Failed to write image to %s: %s", output_path, exc)
            return False
