"""Code-Tracker image bridge client for the SDA posting pipeline.

Replaces the Dropbox + ImageShack + Eldorado CDN upload chain with a single
call to the code-tracker bridge endpoint (POST /api/sda/render-images).

The endpoint returns pre-rendered images for all three platforms:
  - gameboost_image_urls  → used as external_urls (GameBoost)
  - imageshack_album_url  → used as album_url (PlayerAuctions)
  - eldorado.*            → used as Eldorado CDN paths (Eldorado)

Thread-safety
-------------
``_BRIDGE_RESULT_STORE`` is a dict keyed by ``(source_item_id, game)`` that
the ``CtBridgeMediaPublisher`` writes to during ``prepare_once`` and
``_build_eldorado_uploader`` reads from during ``build``.

Each login has a unique ``(source_item_id, game)`` key, so concurrent
producer threads don't interfere.  Results are evicted after the Eldorado
uploader reads them to prevent unbounded growth.
"""
from __future__ import annotations

import logging
import threading
from dataclasses import dataclass, field
from typing import Any

import requests

logger = logging.getLogger(__name__)

_REQUEST_TIMEOUT = 120  # seconds — bridge has its own serial queue, may wait

# ---------------------------------------------------------------------------
# Thread-safe bridge result store
# ---------------------------------------------------------------------------

_BRIDGE_RESULT_STORE: dict[tuple[str, str], "CtBridgeResult"] = {}
_BRIDGE_RESULT_LOCK = threading.Lock()


def _store_bridge_result(source_item_id: str, game: str, result: "CtBridgeResult") -> None:
    key = (str(source_item_id), game)
    with _BRIDGE_RESULT_LOCK:
        _BRIDGE_RESULT_STORE[key] = result


def pop_bridge_result(source_item_id: str, game: str) -> "CtBridgeResult | None":
    """Retrieve and remove the bridge result for (source_item_id, game)."""
    key = (str(source_item_id), game)
    with _BRIDGE_RESULT_LOCK:
        return _BRIDGE_RESULT_STORE.pop(key, None)


def peek_bridge_result(source_item_id: str, game: str) -> "CtBridgeResult | None":
    """Retrieve (without removing) the bridge result for (source_item_id, game)."""
    key = (str(source_item_id), game)
    with _BRIDGE_RESULT_LOCK:
        return _BRIDGE_RESULT_STORE.get(key)


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class CtEldoradoImage:
    """One Eldorado CDN image triple (small / big / original)."""
    small_image: str = ""
    big_image: str = ""
    original_image: str = ""

    @classmethod
    def from_dict(cls, d: dict) -> "CtEldoradoImage":
        return cls(
            small_image=d.get("smallImage", ""),
            big_image=d.get("bigImage", ""),
            original_image=d.get("originalImage", ""),
        )

    def as_formatted_paths(self) -> list[str]:
        """Return [small, big, original] — matches Eldorado upload_images format."""
        return [self.small_image, self.big_image, self.original_image]


@dataclass
class CtBridgeResult:
    """Parsed response from the code-tracker bridge endpoint."""
    ok: bool = False
    cached: bool = False
    source_item_id: str = ""
    game: str = ""
    # ImageShack
    imageshack_album_url: str = ""
    imageshack_direct_urls: list[str] = field(default_factory=list)
    # Eldorado
    eldorado_ok: bool = False
    eldorado_main_image: CtEldoradoImage = field(default_factory=CtEldoradoImage)
    eldorado_offer_images: list[CtEldoradoImage] = field(default_factory=list)
    # GameBoost
    gameboost_image_urls: list[str] = field(default_factory=list)
    # PlayerAuctions
    pa_image_url: str = ""

    @classmethod
    def from_response(cls, data: dict, source_item_id: str = "", game: str = "") -> "CtBridgeResult":
        eldorado = data.get("eldorado") or {}
        gameboost = data.get("gameboost") or {}
        pa = data.get("pa") or {}
        offer_images = [
            CtEldoradoImage.from_dict(img)
            for img in (eldorado.get("offerImages") or [])
        ]
        return cls(
            ok=bool(data.get("ok")),
            cached=bool(data.get("cached")),
            source_item_id=source_item_id,
            game=game,
            imageshack_album_url=data.get("imageshackAlbumUrl") or "",
            imageshack_direct_urls=list(data.get("imageshackDirectUrls") or []),
            eldorado_ok=bool(eldorado.get("ok")),
            eldorado_main_image=CtEldoradoImage.from_dict(
                eldorado.get("mainImage") or {}
            ),
            eldorado_offer_images=offer_images,
            gameboost_image_urls=list(gameboost.get("imageUrls") or []),
            pa_image_url=pa.get("imageUrl") or "",
        )

    def eldorado_formatted_paths(self) -> list[str]:
        """Return all Eldorado paths as a flat list of triples.

        Format: [main_small, main_big, main_orig, offer1_small, offer1_big, offer1_orig, ...]
        This matches what upload_images_to_eldorado() expects.
        """
        paths: list[str] = []
        paths.extend(self.eldorado_main_image.as_formatted_paths())
        for img in self.eldorado_offer_images:
            paths.extend(img.as_formatted_paths())
        return paths


# ---------------------------------------------------------------------------
# HTTP client
# ---------------------------------------------------------------------------

class CtBridgeClient:
    """HTTP client for the code-tracker SDA image bridge endpoint."""

    def __init__(self, url: str, secret: str) -> None:
        self._url = url.rstrip("/")
        self._secret = secret

    def fetch(
        self,
        source_item_id: str,
        game: str,
        eldorado_store: str = "ezsmurfmart",
        force: bool = False,
    ) -> CtBridgeResult | None:
        """Call the bridge endpoint and return a parsed result.

        Returns None on any network/HTTP/parse error (caller should fall back
        to the standard upload pipeline).
        """
        payload: dict[str, Any] = {
            "sourceItemId": str(source_item_id),
            "game": game,
            "eldoradoStore": eldorado_store,
        }
        if force:
            payload["force"] = True

        try:
            resp = requests.post(
                self._url,
                json=payload,
                headers={
                    "X-Bridge-Secret": self._secret,
                    "Content-Type": "application/json",
                },
                timeout=_REQUEST_TIMEOUT,
            )
        except requests.RequestException as exc:
            logger.warning(
                "CT bridge request failed (item=%s game=%s): %s",
                source_item_id, game, exc,
            )
            return None

        if not resp.ok:
            logger.warning(
                "CT bridge returned HTTP %d for item=%s game=%s: %s",
                resp.status_code, source_item_id, game, resp.text[:200],
            )
            return None

        try:
            data = resp.json()
        except Exception as exc:
            logger.warning("CT bridge response parse error: %s", exc)
            return None

        if not data.get("ok"):
            logger.warning(
                "CT bridge returned ok=false for item=%s game=%s: %s",
                source_item_id, game, data.get("error", "unknown"),
            )
            return None

        result = CtBridgeResult.from_response(data, source_item_id=str(source_item_id), game=game)
        logger.info(
            "CT bridge success: item=%s game=%s store=%s cached=%s "
            "imageshack_urls=%d eldorado_ok=%s gameboost_urls=%d",
            source_item_id, game, eldorado_store, result.cached,
            len(result.imageshack_direct_urls), result.eldorado_ok,
            len(result.gameboost_image_urls),
        )
        return result


# ---------------------------------------------------------------------------
# MediaPublisher adapter
# ---------------------------------------------------------------------------

class CtBridgeMediaPublisher:
    """MediaPublisher that uses the CT bridge instead of Dropbox + ImageShack.

    Satisfies the ``MediaPublisher`` protocol:
        publish(local_paths, request=None) -> MediaBundle

    Reads ``ct_bridge_source_id``, ``ct_bridge_game``, and
    ``ct_bridge_eldorado_store`` from ``request.context``.

    On success:
      - Stores the full CtBridgeResult in the module-level store keyed by
        (source_item_id, game) so _build_eldorado_uploader() can retrieve it.
      - Returns a MediaBundle with external_urls (GameBoost) and album_url (PA).

    On failure: falls back to NullMediaPublisher behaviour (local_paths only).
    """

    def __init__(self, client: CtBridgeClient) -> None:
        self._client = client

    def publish(self, local_paths, request=None):
        from pathlib import Path
        from payload_pipeline.core.contracts import MediaBundle

        normalized = [str(Path(p)) for p in local_paths if p]

        if request is None:
            logger.debug("CT bridge publisher: no request context, skipping bridge call")
            return MediaBundle(local_paths=normalized)

        source_item_id = request.context.get("ct_bridge_source_id", "")
        game = request.context.get("ct_bridge_game", "")
        eldorado_store = request.context.get("ct_bridge_eldorado_store", "") or "ezsmurfmart"

        if not source_item_id or not game:
            logger.debug(
                "CT bridge publisher: missing source_item_id or game in context, skipping"
            )
            return MediaBundle(local_paths=normalized)

        result = self._client.fetch(
            source_item_id=source_item_id,
            game=game,
            eldorado_store=eldorado_store,
        )
        if result is None:
            logger.warning(
                "CT bridge call failed for item=%s game=%s — falling back to local paths",
                source_item_id, game,
            )
            return MediaBundle(local_paths=normalized)

        # Store the full bridge result so _build_eldorado_uploader() can use it
        _store_bridge_result(source_item_id, game, result)

        return MediaBundle(
            local_paths=normalized,
            external_urls=result.gameboost_image_urls,
            album_url=result.imageshack_album_url or None,
        )


# ---------------------------------------------------------------------------
# Eldorado uploader adapter
# ---------------------------------------------------------------------------

class CtBridgeEldoradoUploader:
    """MarketplaceImageUploader that returns pre-fetched Eldorado CDN paths.

    The bridge result is retrieved from the module-level store using
    (source_item_id, game) as the key.  The result is popped (removed) on
    first use to prevent memory leaks.

    upload_images_to_eldorado() calls upload_image() once per image file.
    We return [small, big, original] for each call in order, ignoring the
    actual file_path (which is a local collagedfile we don't need to upload).

    If no bridge result is available (bridge failed), falls back to the
    real EldoradoMarketplaceUploader.
    """

    def __init__(
        self,
        source_item_id: str,
        game: str,
        fallback_uploader=None,
    ) -> None:
        self._source_item_id = source_item_id
        self._game = game
        self._fallback = fallback_uploader
        self._result: CtBridgeResult | None = None
        self._paths: list[str] = []
        self._call_count = 0
        self._loaded = False

    def _load_result(self) -> None:
        if self._loaded:
            return
        self._loaded = True
        result = pop_bridge_result(self._source_item_id, self._game)
        if result and result.eldorado_ok:
            self._result = result
            self._paths = result.eldorado_formatted_paths()
            logger.debug(
                "CT bridge Eldorado uploader: loaded %d pre-fetched paths for item=%s game=%s",
                len(self._paths), self._source_item_id, self._game,
            )
        else:
            logger.debug(
                "CT bridge Eldorado uploader: no bridge result for item=%s game=%s, will use fallback",
                self._source_item_id, self._game,
            )

    def upload_image(self, file_path: str) -> list[str]:
        """Return the next 3-path triple from the pre-fetched bridge result."""
        self._load_result()

        if self._result is None:
            if self._fallback is not None:
                logger.debug(
                    "CT bridge Eldorado uploader: no bridge result, falling back to real uploader"
                )
                return self._fallback.upload_image(file_path)
            raise RuntimeError(
                "CT bridge Eldorado uploader: no bridge result and no fallback configured"
            )

        start = self._call_count * 3
        triple = self._paths[start : start + 3]
        self._call_count += 1

        if len(triple) < 3:
            logger.warning(
                "CT bridge Eldorado uploader: not enough paths for call #%d "
                "(have %d total paths, need index %d+3)",
                self._call_count, len(self._paths), start,
            )
            triple = (triple + ["", "", ""])[:3]

        logger.debug(
            "CT bridge Eldorado uploader: returning pre-fetched paths for call #%d: %s",
            self._call_count, triple,
        )
        return triple
