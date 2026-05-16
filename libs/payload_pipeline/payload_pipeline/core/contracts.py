"""Shared contracts for the payload pipeline."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, ClassVar, Generic, Literal, Protocol, TypeVar, overload

TConfig = TypeVar("TConfig")

from .enums import ListingCategory, ListingKind, Marketplace  # noqa: F401

TSubject = TypeVar("TSubject")


@dataclass(frozen=True, slots=True)
class FieldMeta:
    """Metadata for a single template-visible field.

    Attributes:
        description: Human-readable explanation shown in the template editor.
        sample: Representative value used for template preview rendering.
        source: Origin of the field — ``resolved`` (from model), ``computed``
            (derived at render time), or ``runtime`` (injected by the pipeline).
    """

    description: str
    sample: Any
    source: str = "resolved"


@dataclass(slots=True)
class BuildContext:
    """Runtime configuration passed to payload builders.

    Separates builder concerns (pricing, mode, marketplace services) from
    resolver concerns (raw sources).  Builders receive this instead of the
    full ``PipelineRequest``.

    Marketplace-specific configuration is passed via ``marketplace_config``.
    Each marketplace module defines its own config dataclass
    (e.g. ``EldoradoConfig``, ``G2GConfig``) so the core layer stays
    decoupled from marketplace details.
    """

    kind: ListingKind = ListingKind.STOCK
    marketplace: str = ""
    pricing_rules: dict[str, Any] | None = None
    marketplace_config: Any = None
    exchange_rate: float | None = None

    def get_config(self, config_type: type[TConfig], default: TConfig | None = None) -> TConfig:
        """Return ``marketplace_config`` if it matches *config_type*, else *default*.

        If no default is supplied, constructs one via ``config_type()``.
        """
        if isinstance(self.marketplace_config, config_type):
            return self.marketplace_config
        return default if default is not None else config_type()


@dataclass(slots=True)
class CredentialBundle:
    """Normalized credential fields used across games."""

    login: str = ""
    password: str = ""
    email_login: str = ""
    email_password: str = ""
    email_login_link: str = ""
    security_email: str = ""
    security_email_password: str = ""

    def __post_init__(self) -> None:
        # Outlook format: very long password with colons — keep only before first ':'
        if self.password and len(self.password) >= 200 and ":" in self.password:
            self.password = self.password.split(":", 1)[0]

        if self.email_password:
            if len(self.email_password) >= 200 and ":" in self.email_password:
                # Outlook format: keep only before first ':'
                self.email_password = self.email_password.split(":", 1)[0]
            elif self.email_password.count(":") == 2 and len(self.email_password) < 200:
                # Security email format: email_password:security_email:security_email_password
                parts = self.email_password.split(":", 2)
                self.email_password = parts[0]
                self.security_email = parts[1] if len(parts) > 1 else ""
                self.security_email_password = parts[2] if len(parts) > 2 else ""

    @property
    def is_empty(self) -> bool:
        return not any(
            [
                self.login,
                self.password,
                self.email_login,
                self.email_password,
                self.email_login_link,
            ]
        )

    def to_multiline(self) -> str:
        lines: list[str] = []
        if self.login:
            lines.append(f"Login: {self.login}")
        if self.password:
            lines.append(f"Password: {self.password}")
        if self.email_login:
            lines.append(f"Email: {self.email_login}")
        if self.email_password:
            lines.append(f"Email Password: {self.email_password}")
        if self.security_email:
            lines.append(f"Security Email: {self.security_email}")
        if self.security_email_password:
            lines.append(f"Security Email Password: {self.security_email_password}")
        if self.email_login_link:
            lines.append(f"Email Login Link: {self.email_login_link}")
        return "\n".join(lines)


@dataclass(slots=True)
class ResolvedAccountBase:
    """Common fields shared by all resolved game account models.

    Every game-specific resolved model inherits from this base to
    guarantee a consistent contract for validation, pricing, and
    credential handling.

    Subclasses should extend ``FIELD_META`` and ``COMPUTED_FIELDS`` to
    provide template editor metadata (descriptions + sample values).
    """

    item_id: str = ""
    category_id: int = 0
    price: float = 0.0
    kind: Literal["stock", "dropshipping"] = "stock"
    ref_key: str = ""
    credentials: CredentialBundle = field(default_factory=CredentialBundle)

    FIELD_META: ClassVar[dict[str, FieldMeta]] = {
        "item_id": FieldMeta("Source item ID.", "sample-item-123"),
        "category_id": FieldMeta("Listing category ID.", 1),
        "price": FieldMeta("Listing price.", 10.0),
        "kind": FieldMeta("Listing kind: stock or dropshipping.", "stock"),
        "ref_key": FieldMeta("Traceability reference key.", "#ABC1234"),
    }

    COMPUTED_FIELDS: ClassVar[dict[str, FieldMeta]] = {
        "album_url": FieldMeta(
            "Hosted media album URL when available.",
            "https://imgur.com/a/sample",
            "runtime",
        ),
        "is_stock": FieldMeta("True for stock listings.", True, "runtime"),
    }


@dataclass(slots=True)
class MediaBundle:
    """Shared media state before and after publishing."""

    local_paths: list[str] = field(default_factory=list)
    external_urls: list[str] = field(default_factory=list)
    album_url: str | None = None

    @property
    def is_published(self) -> bool:
        return bool(self.external_urls or self.album_url)


@dataclass(slots=True)
class ListingContent:
    """Default marketplace-facing content for a resolved subject."""

    title: str = ""
    description: str = ""
    tags: list[str] = field(default_factory=list)


@dataclass(slots=True)
class MarketplaceListingOverride:
    """Optional marketplace-specific content adjustments."""

    title: str | None = None
    description: str | None = None
    tags: list[str] | None = None


@dataclass(slots=True)
class ListingDraft:
    """Platform-independent listing draft with optional marketplace overrides."""

    default: ListingContent = field(default_factory=ListingContent)
    media: MediaBundle = field(default_factory=MediaBundle)
    marketplace_overrides: dict[str, MarketplaceListingOverride] = field(default_factory=dict)

    def content_for(self, marketplace: str, ref_key: str = "") -> ListingContent:
        """Return the effective listing content for the requested marketplace.

        When unique_key is enabled for the marketplace:
        - PA/Gameboost: appends ref_key to title (e.g. ``#ABC1234``)
        - Eldorado: appends ``#`` to title, prepends ref_key to description
        """
        from .config import get_unique_key_config

        override = self.marketplace_overrides.get(marketplace.lower())
        if override is None:
            title = self.default.title
            description = self.default.description
            tags = list(self.default.tags)
        else:
            title = override.title if override.title is not None else self.default.title
            description = (
                override.description
                if override.description is not None
                else self.default.description
            )
            tags = list(override.tags) if override.tags is not None else list(self.default.tags)

        uk = get_unique_key_config(marketplace)

        if title and uk.get("title"):
            if ref_key and marketplace.lower() in ("playerauctions", "gameboost"):
                if not title.rstrip().endswith(ref_key):
                    title = title.rstrip() + ' ' + ref_key
            else:
                if not title.endswith('#'):
                    title = title.rstrip() + ' #'

        if description is not None and uk.get("description") and ref_key:
            if not description.startswith(ref_key):
                description = f"{ref_key}\n{description}"

        return ListingContent(
            title=title,
            description=description,
            tags=tags,
        )


@dataclass(slots=True)
class PipelineRequest:
    """Structured input for the shared preparation phase.

    Marketplace-specific configuration is passed separately via
    ``BuildContext`` when calling ``pipeline.build()``.
    """

    game: str
    category: ListingCategory = ListingCategory.ACCOUNT
    kind: ListingKind = ListingKind.STOCK
    sources: dict[str, Mapping[str, Any]] = field(default_factory=dict)
    context: dict[str, Any] = field(default_factory=dict)

    def source(self, name: str) -> Mapping[str, Any]:
        raw = self.sources.get(name)
        return raw if isinstance(raw, Mapping) else {}

    @property
    def registry_key(self) -> str:
        return f"{self.game.lower()}:{self.category.lower()}"


@dataclass(slots=True)
class PreparedListing(Generic[TSubject]):
    """Output of the shared preparation phase — marketplace-independent."""

    subject: TSubject
    listing: ListingDraft
    media: MediaBundle
    game: str = ""
    category: ListingCategory = ListingCategory.ACCOUNT
    warnings: list[str] = field(default_factory=list)


@dataclass(slots=True)
class PrepareResult(Generic[TSubject]):
    """Consistent result envelope returned by ``prepare_once``.

    Always check ``success`` before using ``prepared``.  When ``success``
    is ``False``, ``error`` and ``error_stage`` describe the failure.

    ``error_stage`` is one of:
      - ``"registry"``  — game/category not found in registry
      - ``"resolve"``   — resolver raised an exception
      - ``"validate"``  — resolved subject failed validation
      - ``"compose"``   — composer raised an exception

    Non-fatal issues (e.g. media preparation/publication failures) are
    collected in ``warnings`` regardless of ``success``.  A successful
    result may still carry warnings.
    """

    success: bool
    prepared: PreparedListing[TSubject] | None = None
    error: str | None = None
    error_stage: str | None = None
    warnings: list[str] = field(default_factory=list)


@dataclass(slots=True)
class PipelineResult(Generic[TSubject]):
    """Consistent result envelope returned by the pipeline for every build.

    Always check ``success`` before using ``payload``.  When ``success``
    is ``False``, ``error`` and ``error_stage`` describe the failure.
    Non-fatal issues (e.g. media generation failures) are collected in
    ``warnings`` regardless of ``success``.
    """

    success: bool
    subject: TSubject
    listing: ListingDraft
    payload: dict[str, Any] | None = None
    marketplace: str = ""
    error: str | None = None
    error_stage: str | None = None
    warnings: list[str] = field(default_factory=list)


class SubjectResolver(Protocol[TSubject]):
    """Create a resolved subject model from raw prepared sources."""

    def resolve(self, request: PipelineRequest) -> TSubject:
        ...


class MediaStrategy(Protocol[TSubject]):
    """Prepare local media paths for a resolved subject."""

    def prepare(self, subject: TSubject, request: PipelineRequest) -> Sequence[str]:
        ...


class ListingComposer(Protocol[TSubject]):
    """Build listing content from a resolved subject.

    All marketplace variants should be expressed via
    ``ListingDraft.marketplace_overrides``.
    """

    def compose(
        self,
        subject: TSubject,
        request: PipelineRequest,
        media: MediaBundle,
    ) -> ListingDraft:
        ...


class PayloadBuilder(Protocol[TSubject]):
    """Build a marketplace payload from a resolved subject and listing."""

    marketplace: str

    def build_payload(
        self,
        subject: TSubject,
        listing: ListingDraft,
        ctx: BuildContext,
    ) -> dict[str, Any]:
        ...


class ImageFetcher(Protocol):
    """Fetch a single preview image by category and item ID.

    Pipeline never calls vendor-specific methods directly.  Instead,
    the consuming project provides an adapter that satisfies this
    protocol — or uses the built-in ``LztDefaultImageFetcher``.
    """

    def fetch_image(self, category: str, item_id: str) -> bytes | None:
        """Return raw image bytes on success, or ``None`` on failure."""
        ...


class MarketplaceImageUploader(Protocol):
    """Upload a single image file to a marketplace and return formatted URLs.

    The pipeline calls this during the build phase for marketplaces that
    host their own images (e.g. Eldorado).  The consuming project wraps
    its vendor-specific client in an adapter that satisfies this protocol.
    """

    def upload_image(self, file_path: str) -> list[str] | None:
        """Upload *file_path* and return a list of formatted image URLs.

        Typically returns 3 URLs per image (small, large, original).
        Returns ``None`` on failure.
        """
        ...


class ImageUploader(Protocol):
    """Upload images to a hosting service and return per-image public URLs."""

    def upload_images(self, image_paths: list[str]) -> list[str]:
        """Upload each image and return a list of direct-download URLs."""
        ...


class AlbumUploader(Protocol):
    """Upload images into an album and return the album URL."""

    def upload_album_from_paths(self, image_paths: list[str]) -> str:
        """Upload all images into an album and return the album page URL."""
        ...


class AlbumDownloader(Protocol):
    """Download all images from a remote album URL to a local directory.

    The consuming project provides a concrete implementation (e.g.
    ``ImgurAlbumDownloader``) that wraps the SDK facade.
    ``payload_pipeline`` only sees this protocol.
    """

    def download_album(self, album_url: str, output_dir: str) -> list[str]:
        """Download all images from *album_url* into *output_dir*.

        Returns a list of absolute paths to the saved files.
        Returns an empty list on failure — never raises.
        """
        ...


class MediaPublisher(Protocol):
    """Publish prepared local media paths to shared hosts."""

    def publish(
        self,
        local_paths: Sequence[str],
        request: PipelineRequest | None = None,
    ) -> MediaBundle:
        ...
