"""Stock payload builder — pure function extracted from StockOrchestrator.

Given a ``PostingJobItem`` and its resolver-prepared data, this module:
- Reads store-scoped pricing from ``job.settings`` (baseline fallback)
- Selects a variant via the VariantRouter (capacity-aware)
- Builds the marketplace payload via the payload pipeline (non-PA) or the
  PA Excel row builder (PA)
- Returns a standard pipeline-result dict
"""

from __future__ import annotations

import logging
from decimal import Decimal

from payload_pipeline.pricing.rules import calculate_price

from apps.posting.models import PostingJob, PostingJobItem
from apps.posting.pipeline import adapter
from apps.posting.services.shared.pricing import (
    STOCK_PRICING_BASELINE,
    build_pricing_rule,
)
from apps.posting.services.variant_slug import resolve_listing_variant_slug
from apps.posting.services.variant_routing import VariantRouter, get_eligible_variants
from payload_pipeline.core.contracts import ListingKind

logger = logging.getLogger(__name__)


def build_item_payload(
    item: PostingJobItem,
    prepared_data: dict,
    job: PostingJob,
    *,
    variant_ctx: dict | None = None,
    router: VariantRouter | None = None,
    force_variant: str = '',
) -> dict:
    """Select variant, compute final_price, then build marketplace payload.

    Args:
        item: The posting job item being processed.
        prepared_data: Dict with 'prepared' (PreparedListing) and 'owned_product'.
        job: Parent posting job (provides game + settings).
        variant_ctx: Pre-built variant context dict (from build_variant_context).
        router: Pre-built VariantRouter (created once per consumer thread).

    Returns a standard result dict:
      ok path:  {'ok': True, 'stage': str, 'data': {'payload', 'final_price', 'variant_slug', 'mode'}}
      fail path: {'ok': False, 'stage': str, 'error': str, 'error_category': str}
    """
    stage = f'build_{item.marketplace}'
    try:
        prepared = prepared_data['prepared']

        # Read pricing from job.settings (store-slug-keyed, job-scoped).
        # No DB read here — orchestrator is DB-independent in the build path.
        # Missing/partial settings fall back to STOCK_PRICING_BASELINE.
        store_settings = job.settings.get(item.store.slug, {})
        pricing = STOCK_PRICING_BASELINE.with_overrides(store_settings)

        # --- Pricing (mirrors lib's internal calculation for Listing.price) ---
        raw_price = prepared.subject.price  # float from lib resolver
        if raw_price <= 0:
            return {
                'ok': False, 'stage': stage,
                'error': f'Invalid price: {raw_price}',
                'error_category': 'validation',
            }
        rule = build_pricing_rule(pricing)
        final_price = Decimal(str(calculate_price(raw_price, rule)))
        if pricing.exchange_rate is not None:
            final_price = (final_price * Decimal(str(pricing.exchange_rate))).quantize(Decimal('0.01'))

        # --- Variant selection ---
        manual_variant = (
            force_variant
            or store_settings.get('variant')
            or store_settings.get('sub_platform')
            or ''
        ).strip()

        if router is not None:
            allowed = get_eligible_variants(job.game.slug, prepared.subject)
            variant_slug = router.select(
                'platform',
                allowed=allowed,
                game_slug=job.game.slug,
                manual=manual_variant,
            )
            if variant_slug is None:
                return {
                    'ok': False, 'stage': stage,
                    'error': 'No available variant slots',
                    'error_category': 'capacity',
                }
        else:
            # Fallback for callers that don't provide a router (e.g. relist)
            variant_slug = manual_variant or getattr(prepared.subject, 'main_platform', '') or ''

        # --- PA routing: single (API JSON) or bulk (Excel row) ---
        if item.marketplace == 'playerauctions':
            pa_mode = store_settings.get('pa_mode', 'bulk')

            if pa_mode == 'single':
                # Single post: use pipeline → build_payload() → API JSON
                pipeline_result = adapter.build(
                    prepared=prepared,
                    marketplace=item.marketplace,
                    pricing_defaults=pricing,
                    store=item.store,
                    kind=ListingKind.STOCK,
                    variant_slug=variant_slug,
                    variant_context=variant_ctx,
                )
                if not pipeline_result.success:
                    return {
                        'ok': False,
                        'stage': pipeline_result.error_stage or stage,
                        'error': pipeline_result.error or 'Build failed',
                        'error_category': 'pipeline_error',
                    }
                return {
                    'ok': True, 'stage': stage,
                    'data': {
                        'payload': pipeline_result.payload,
                        'final_price': final_price,
                        'variant_slug': variant_slug,
                        'listing_variant_slug': _listing_variant_slug(
                            prepared.subject, variant_ctx, variant_slug,
                        ),
                        'mode': 'json',
                    },
                }

            # Bulk mode: Excel row via pipeline build_bulk_payload()
            pipeline_result = adapter.build_bulk(
                prepared=prepared,
                marketplace=item.marketplace,
                pricing_defaults=pricing,
                store=item.store,
                kind=ListingKind.STOCK,
                variant_slug=variant_slug,
                variant_context=variant_ctx,
            )
            if not pipeline_result.success:
                return {
                    'ok': False,
                    'stage': pipeline_result.error_stage or stage,
                    'error': pipeline_result.error or 'Bulk build failed',
                    'error_category': 'pipeline_error',
                }
            return {
                'ok': True, 'stage': stage,
                'data': {
                    'payload': pipeline_result.payload,
                    'final_price': final_price,
                    'variant_slug': variant_slug,
                    'listing_variant_slug': _listing_variant_slug(
                        prepared.subject, variant_ctx, variant_slug,
                    ),
                    'mode': 'excel_row',
                },
            }

        # --- Non-PA: adapter.build() → PipelineResult ---
        pipeline_result = adapter.build(
            prepared=prepared,
            marketplace=item.marketplace,
            pricing_defaults=pricing,
            store=item.store,
            kind=ListingKind.STOCK,
            variant_slug=variant_slug,
            variant_context=variant_ctx,
        )
        if not pipeline_result.success:
            return {
                'ok': False,
                'stage': pipeline_result.error_stage or stage,
                'error': pipeline_result.error or 'Build failed',
                'error_category': 'pipeline_error',
            }
        return {
            'ok': True, 'stage': stage,
            'data': {
                'payload': pipeline_result.payload,
                'final_price': final_price,
                'variant_slug': variant_slug,
                'listing_variant_slug': _listing_variant_slug(
                    prepared.subject, variant_ctx, variant_slug,
                ),
                'mode': 'json',
            },
        }

    except Exception as exc:
        logger.exception("build_item_payload failed for item #%d", item.id)
        return {
            'ok': False,
            'stage': stage,
            'error': str(exc),
            'error_category': 'unexpected',
        }


def _listing_variant_slug(subject, variant_ctx: dict | None, platform_slug: str) -> str:
    selected = {'platform': platform_slug} if platform_slug else None
    return resolve_listing_variant_slug(
        subject=subject,
        variant_ctx=variant_ctx,
        selected_variants=selected,
        fallback=platform_slug,
    )
