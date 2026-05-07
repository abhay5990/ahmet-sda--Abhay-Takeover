"""Typed constants for PipelineRequest.context keys.

Centralizes all known context keys to avoid scattered string literals
and make usage discoverable via IDE autocomplete.

Each key is a ``ContextKey[T]`` that subclasses ``str``, so it works
everywhere a plain string key would (dict literals, ``**`` unpacking,
``request.context.get(ctx.KEY)``).  The generic parameter ``T`` carries
the expected value type for static analysis.
"""

from __future__ import annotations

from typing import Any, Generic, TypeVar, overload

T = TypeVar("T")


class ContextKey(str, Generic[T]):
    """A str-subclass that also carries the expected value type as ``T``.

    Since it *is* a ``str``, it works in all existing code paths::

        # As a dict key (no change needed)
        context={ctx.DISABLE_MEDIA: True}

        # With dict.get
        request.context.get(ctx.DISABLE_MEDIA)

    Additionally it provides typed ``get`` / ``set`` helpers::

        enabled = ctx.DISABLE_MEDIA.get(request)       # -> bool | None
        ctx.DISABLE_MEDIA.set(request, True)
    """

    def __new__(cls, key: str) -> ContextKey[T]:
        return str.__new__(cls, key)

    # -- typed accessors ------------------------------------------------

    @overload
    def get(self, request: Any) -> T | None: ...

    @overload
    def get(self, request: Any, default: T) -> T: ...

    def get(self, request: Any, default: T | None = None) -> T | None:
        """Retrieve the value from ``request.context``, or *default*."""
        return request.context.get(self, default)

    def set(self, request: Any, value: T) -> None:
        """Store *value* into ``request.context``."""
        request.context[self] = value


# ── Source clients (shared, used during prepare phase) ───────────────

LZT_CLIENT: ContextKey[Any] = ContextKey("lzt_client")

# ── Image fetchers (protocol-based, used during media phase) ────────

LZT_IMAGE_FETCHER: ContextKey[Any] = ContextKey("lzt_image_fetcher")

# ── Marketplace clients (per-store, used during build phase) ─────────

ELDORADO_CLIENT: ContextKey[Any] = ContextKey("eldorado_client")
ELDORADO_IMAGE_RETRIES: ContextKey[int] = ContextKey("eldorado_image_retries")

# ── Media control ────────────────────────────────────────────────────

DISABLE_MEDIA: ContextKey[bool] = ContextKey("disable_media")
MEDIA_SOURCE_POLICY: ContextKey[str] = ContextKey("media_source_policy")
MEDIA_OUTPUT_DIR: ContextKey[str] = ContextKey("media_output_dir")
FILE_OUTPUT_DIR: ContextKey[str] = ContextKey("file_output_dir")
CACHE_BASE_DIR: ContextKey[str] = ContextKey("cache_base_dir")

# ── Subplatform / slot management ────────────────────────────────────

SUBPLATFORM_STATUS: ContextKey[dict[str, dict[str, Any]]] = ContextKey("subplatform_status")
CURRENT_SUBPLATFORM: ContextKey[str] = ContextKey("current_subplatform")

# ── G2G seller config ────────────────────────────────────────────────

G2G_SELLER_ID: ContextKey[str] = ContextKey("g2g_seller_id")
G2G_SERVICE_ID: ContextKey[str] = ContextKey("g2g_service_id")

# ── Source-level overrides ───────────────────────────────────────────

TRACKER_URL: ContextKey[str] = ContextKey("tracker_url")

# -- Template-backed content rendering ---------------------------------------

USE_TEMPLATE_CONTENT: ContextKey[bool] = ContextKey("use_template_content")
CONTENT_TEMPLATE_MANAGER: ContextKey[Any] = ContextKey("content_template_manager")
CONTENT_TEMPLATE_OVERRIDES: ContextKey[dict[str, Any]] = ContextKey(
    "content_template_overrides"
)
