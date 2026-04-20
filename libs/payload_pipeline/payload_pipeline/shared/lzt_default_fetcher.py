"""Built-in standalone LZT image fetcher.

Requires only a *base_url* and *token* — no external client dependency.
Satisfies the ``ImageFetcher`` protocol defined in ``core.contracts``.
"""

from __future__ import annotations

import base64
import logging
from typing import Any

import requests
from requests.adapters import HTTPAdapter

logger = logging.getLogger(__name__)

# Pipeline category → LZT API query param (the slug sent as ?type=...)
_CATEGORY_TO_API_SLUG: dict[str, str] = {
    # Valorant
    "weapons": "weapons",
    "agents": "agents",
    "buddies": "buddies",
    # Fortnite
    "skins": "skins",
    "pickaxes": "pickaxes",
    "dances": "dances",
    "gliders": "gliders",
}


class LztDefaultImageFetcher:
    """Standalone LZT image fetcher that talks directly to the LZT Market API.

    Usage::

        fetcher = LztDefaultImageFetcher(
            base_url="https://prod-api.lzt.market",
            token="your_bearer_token",
        )
        raw_bytes = fetcher.fetch_image("weapons", "185237859")
    """

    def __init__(
        self,
        base_url: str = "https://prod-api.lzt.market",
        token: str = "",
        timeout: int = 30,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.token = token
        self.timeout = timeout
        self._session = requests.Session()
        self._session.mount("https://", HTTPAdapter(pool_connections=5, pool_maxsize=5))
        self._session.headers.update({
            "accept": "application/json",
            "authorization": f"Bearer {token}",
        })

    def fetch_image(self, category: str, item_id: str) -> bytes | None:
        """Fetch an image from the LZT API and return raw bytes.

        *category* is a pipeline-level name (``"weapons"``, ``"skins"``, …).
        It is mapped to the LZT API type automatically.
        """
        api_slug = _CATEGORY_TO_API_SLUG.get(category)
        if not api_slug:
            logger.warning("Unknown image category: %s", category)
            return None

        url = f"{self.base_url}/{item_id}/image"

        try:
            resp = self._session.get(
                url,
                params={"type": api_slug},
                timeout=self.timeout,
            )
            resp.raise_for_status()

            data: dict[str, Any] = resp.json()
            b64 = data.get("base64")
            if not b64:
                logger.warning(
                    "LZT API returned no base64 data for %s/%s", category, item_id,
                )
                return None

            return base64.b64decode(b64)

        except Exception as exc:
            logger.warning("LZT default image fetch failed for %s/%s: %s", category, item_id, exc)
            return None
