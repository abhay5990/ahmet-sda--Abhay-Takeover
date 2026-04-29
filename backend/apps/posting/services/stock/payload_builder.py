"""Stock payload builder — pure function extracted from StockOrchestrator.

Given a ``PostingJobItem`` and its resolver-prepared data, this module:
- Reads store-scoped pricing from ``job.settings`` (baseline fallback)
- Selects a sub-platform (fixed or auto via capacity)
- Builds the marketplace payload via the payload pipeline (non-PA) or the
  PA Excel row builder (PA)
- Returns a standard pipeline-result dict
"""

from __future__ import annotations

import logging
from decimal import Decimal

from payload_pipeline.pricing.rules import calculate_price

from apps.posting.models import PostingJob, PostingJobItem, SubplatformLimit
from apps.posting.pipeline import adapter
from apps.posting.services.shared.pricing import (
    STOCK_PRICING_BASELINE,
    build_pricing_rule,
)
from apps.posting.services.shared.subplatform import (
    get_active_offer_counts,
    select_best_subplatform,
)
from payload_pipeline.core.contracts import ListingKind

logger = logging.getLogger(__name__)


def build_item_payload(
    item: PostingJobItem,
    prepared_data: dict,
    job: PostingJob,
) -> dict:
    """Select subplatform, compute final_price, then build marketplace payload.

    Returns a standard result dict:
      ok path:  {'ok': True, 'stage': str, 'data': {'payload', 'final_price', 'sub_platform', 'mode'}}
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

        # --- Subplatform selection ---
        fixed_sp = (store_settings.get('sub_platform') or '').strip()
        if fixed_sp and fixed_sp.lower() != 'auto':
            sub_platform = fixed_sp
        else:
            limits = list(SubplatformLimit.objects.filter(
                store=item.store, game=job.game,
            ))
            if not limits:
                sub_platform = ''
            else:
                counts = get_active_offer_counts(item.store, job.game)
                sub_platform = select_best_subplatform(limits, counts, mode='stock')
                if sub_platform is None:
                    return {
                        'ok': False, 'stage': stage,
                        'error': 'No available sub-platform slots',
                        'error_category': 'capacity',
                    }

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
                    sub_platform=sub_platform,
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
                        'sub_platform': sub_platform,
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
                sub_platform=sub_platform,
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
                    'sub_platform': sub_platform,
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
            sub_platform=sub_platform,
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
                'sub_platform': sub_platform,
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
