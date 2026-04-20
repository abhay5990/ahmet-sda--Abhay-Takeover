"""Eldorado marketplace image uploader adapter.

Bridges the ``MarketplaceImageUploader`` protocol to the Eldorado SDK facade's
``upload_image()`` method.  Used by ``EldoradoConfig`` during the build phase.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)


class EldoradoMarketplaceUploader:
    """Uploads a local image file to Eldorado and returns S3 path list.

    Satisfies ``payload_pipeline.core.contracts.MarketplaceImageUploader``.
    """

    def __init__(self, facade, *, proxy_group: str | None = None) -> None:
        self._facade = facade
        self._proxy_group = proxy_group

    def upload_image(self, file_path: str) -> list[str] | None:
        """Upload *file_path* to Eldorado, return paths or None on failure."""
        result = self._facade.upload_image(
            file_path, proxy_group=self._proxy_group,
        )
        if not result.ok or not result.data:
            logger.warning(
                "Eldorado image upload failed for %s: %s",
                file_path,
                result.error.message if result.error else 'no data',
            )
            return None
        return result.data
