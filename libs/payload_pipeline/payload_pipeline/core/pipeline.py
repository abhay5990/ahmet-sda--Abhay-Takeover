"""Top-level orchestration for payload_pipeline."""

from __future__ import annotations

import logging

from .contracts import (
    BuildContext,
    MediaBundle,
    PipelineRequest,
    PipelineResult,
    PrepareResult,
    PreparedListing,
)
from .registry import PipelineRegistry
from .validation import validate_resolved
from ..shared.media import NullMediaPublisher

logger = logging.getLogger(__name__)


class PayloadPipeline:
    """Resolve sources, compose a listing, and build marketplace payloads.

    Both phases return a result envelope and never raise.  Always check
    ``result.success`` before consuming the result data.

    Usage::

        pipeline = PayloadPipeline(registry, media_publisher=publisher)

        # Phase 1 — resolve, media, compose (marketplace-independent)
        prepare_result = pipeline.prepare_once(request)
        if not prepare_result.success:
            handle_error(prepare_result.error_stage, prepare_result.error)
            return

        # Phase 2 — build a marketplace payload (repeat per store)
        result = pipeline.build(prepare_result.prepared, build_ctx)
        if result.success:
            post_payload(result.payload)
    """

    def __init__(
        self,
        registry: PipelineRegistry,
        media_publisher=None,
    ) -> None:
        self.registry = registry
        self.media_publisher = media_publisher or NullMediaPublisher()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def prepare_once(self, request: PipelineRequest) -> PrepareResult[object]:
        """Run the shared preparation phase exactly once.

        Steps: resolve → validate → media prepare → hosted upload → compose.

        Always returns a :class:`PrepareResult` — never raises.
        On failure ``result.success`` is ``False`` and ``result.error_stage``
        is one of ``"registry"``, ``"resolve"``, ``"validate"``, or
        ``"compose"``.  Media failures are non-fatal and collected in
        ``result.warnings`` even on an otherwise successful result.

        The returned ``PrepareResult.prepared`` can be reused across
        multiple :meth:`build` calls with different :class:`BuildContext`\\s.
        """
        warnings: list[str] = []

        # --- registry ---------------------------------------------------
        try:
            definition = self.registry.get_game(request.game, request.category)
        except Exception as exc:
            logger.error("Registry lookup failed for %s/%s: %s", request.game, request.category, exc)
            return PrepareResult(success=False, error=str(exc), error_stage="registry")

        # --- resolve ----------------------------------------------------
        try:
            subject = definition.resolver.resolve(request)
        except Exception as exc:
            logger.error("Resolver failed for %s: %s", request.game, exc)
            return PrepareResult(success=False, error=str(exc), error_stage="resolve")

        # --- inject ref_key from context into resolved account -----------
        from . import context_keys as ctx_keys
        ref_key = ctx_keys.REF_KEY.get(request, "")
        if ref_key and hasattr(subject, "ref_key"):
            subject.ref_key = ref_key

        # --- fake password override ---------------------------------------
        from .config import is_fake_password_enabled
        if is_fake_password_enabled(request.game) and hasattr(subject, "credentials"):
            subject.credentials.password = "akdapwno1"

        # --- validate ---------------------------------------------------
        try:
            validate_resolved(subject, game=request.game, kind=request.kind)
        except Exception as exc:
            logger.error("Validation failed for %s: %s", request.game, exc)
            return PrepareResult(success=False, error=str(exc), error_stage="validate")

        # --- media (non-fatal) ------------------------------------------
        media = MediaBundle()
        if definition.media_strategy is not None:
            try:
                local_paths = list(definition.media_strategy.prepare(subject, request))
            except Exception as exc:
                msg = f"Media preparation failed: {exc}"
                logger.warning(msg)
                warnings.append(msg)
                local_paths = []

            if local_paths:
                try:
                    media = self.media_publisher.publish(local_paths, request=request)
                except Exception as exc:
                    msg = f"Media publication failed: {exc}"
                    logger.warning(msg)
                    warnings.append(msg)
                    media = MediaBundle(local_paths=local_paths)

        # --- compose ----------------------------------------------------
        try:
            listing = definition.composer.compose(subject, request, media)
        except Exception as exc:
            logger.error("Composer failed for %s: %s", request.game, exc)
            return PrepareResult(success=False, error=str(exc), error_stage="compose", warnings=warnings)

        return PrepareResult(
            success=True,
            prepared=PreparedListing(
                subject=subject,
                listing=listing,
                media=media,
                game=request.game,
                category=request.category,
                warnings=warnings,
            ),
            warnings=warnings,
        )

    def build(
        self,
        prepared: PreparedListing[object],
        build_ctx: BuildContext,
    ) -> PipelineResult[object]:
        """Build a marketplace payload from a prepared listing.

        Always returns a :class:`PipelineResult` — never raises.
        On success ``result.success`` is ``True`` and ``result.payload``
        contains the marketplace dict.  On failure ``result.error`` and
        ``result.error_stage`` describe what went wrong.

        Warnings accumulated during preparation are always forwarded.
        """
        warnings = list(prepared.warnings)

        try:
            definition = self.registry.get_game(prepared.game, prepared.category)
            builder = definition.get_builder(build_ctx.marketplace)
        except Exception as exc:
            logger.error("Registry lookup failed for %s/%s: %s", prepared.game, build_ctx.marketplace, exc)
            return PipelineResult(
                success=False,
                subject=prepared.subject,
                listing=prepared.listing,
                marketplace=build_ctx.marketplace,
                error=str(exc),
                error_stage="registry",
                warnings=warnings,
            )

        try:
            payload = builder.build_payload(prepared.subject, prepared.listing, build_ctx)
        except Exception as exc:
            logger.error("Payload build failed for %s/%s: %s", prepared.game, build_ctx.marketplace, exc)
            return PipelineResult(
                success=False,
                subject=prepared.subject,
                listing=prepared.listing,
                marketplace=build_ctx.marketplace,
                error=str(exc),
                error_stage="build",
                warnings=warnings,
            )

        return PipelineResult(
            success=True,
            subject=prepared.subject,
            listing=prepared.listing,
            payload=payload,
            marketplace=build_ctx.marketplace,
            warnings=warnings,
        )

    def build_bulk(
        self,
        prepared: PreparedListing[object],
        build_ctx: BuildContext,
    ) -> PipelineResult[object]:
        """Build a bulk/Excel payload from a prepared listing.

        Same as :meth:`build` but calls ``build_bulk_payload`` on the builder
        instead of ``build_payload``.  Used for PA Excel bulk uploads.
        """
        warnings = list(prepared.warnings)

        try:
            definition = self.registry.get_game(prepared.game, prepared.category)
            builder = definition.get_builder(build_ctx.marketplace)
        except Exception as exc:
            logger.error("Registry lookup failed for %s/%s: %s", prepared.game, build_ctx.marketplace, exc)
            return PipelineResult(
                success=False,
                subject=prepared.subject,
                listing=prepared.listing,
                marketplace=build_ctx.marketplace,
                error=str(exc),
                error_stage="registry",
                warnings=warnings,
            )

        try:
            payload = builder.build_bulk_payload(prepared.subject, prepared.listing, build_ctx)
        except Exception as exc:
            logger.error("Bulk payload build failed for %s/%s: %s", prepared.game, build_ctx.marketplace, exc)
            return PipelineResult(
                success=False,
                subject=prepared.subject,
                listing=prepared.listing,
                marketplace=build_ctx.marketplace,
                error=str(exc),
                error_stage="build_bulk",
                warnings=warnings,
            )

        return PipelineResult(
            success=True,
            subject=prepared.subject,
            listing=prepared.listing,
            payload=payload,
            marketplace=build_ctx.marketplace,
            warnings=warnings,
        )
