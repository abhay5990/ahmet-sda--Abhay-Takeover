"""Core contracts and orchestration for payload_pipeline."""

from .contracts import (
    BuildContext,
    CredentialBundle,
    FieldMeta,
    ImageFetcher,
    ListingContent,
    ListingDraft,
    MarketplaceImageUploader,
    MarketplaceListingOverride,
    MediaBundle,
    PipelineRequest,
    PipelineResult,
    PrepareResult,
    PreparedListing,
    ResolvedAccountBase,
)
from .capabilities import MediaCapabilities, AUTO_GEN_AND_OVERRIDE, OVERRIDE_ONLY, NO_MEDIA
from .enums import GameSlug, ListingCategory, ListingKind, Marketplace
from .pipeline import PayloadPipeline
from .exceptions import PayloadPipelineError, RegistryConflictError, RegistryLookupError, SourceValidationError
from .registry import GameDefinition, PipelineRegistry
from .manual_fields import ManualFieldSpec, FieldOption, ManualFieldRegistry, manual_field_registry
from .validation import validate_resolved

__all__ = [
    "AUTO_GEN_AND_OVERRIDE",
    "BuildContext",
    "CredentialBundle",
    "FieldMeta",
    "FieldOption",
    "GameDefinition",
    "GameSlug",
    "ManualFieldRegistry",
    "ManualFieldSpec",
    "manual_field_registry",
    "MediaCapabilities",
    "PayloadPipelineError",
    "RegistryConflictError",
    "RegistryLookupError",
    "SourceValidationError",
    "ImageFetcher",
    "ListingCategory",
    "ListingContent",
    "ListingDraft",
    "ListingKind",
    "Marketplace",
    "MarketplaceImageUploader",
    "MarketplaceListingOverride",
    "MediaBundle",
    "NO_MEDIA",
    "OVERRIDE_ONLY",
    "PayloadPipeline",
    "PipelineRegistry",
    "PipelineRequest",
    "PipelineResult",
    "PrepareResult",
    "PreparedListing",
    "ResolvedAccountBase",
    "validate_resolved",
]
