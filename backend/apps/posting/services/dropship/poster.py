"""Dropship poster — continuous loop driven by the scheduler service.

Public entry point: ``poster_loop(config, stop_event)``
Called by the scheduler's poster thread wrapper.  Raises ``PauseRequired``
when error thresholds are exceeded; the wrapper catches it and sets the
config to PAUSED.
"""

from __future__ import annotations

import logging
from decimal import Decimal
from threading import Event

from django.db import transaction
from django.utils import timezone

from apps.integrations.providers import registry
from apps.integrations.proxy_pool import build_proxy_pool, get_group_name
from apps.inventory.enums import DropshipProductStatus
from apps.inventory.models import DropshipProduct
from apps.listings.enums import ListingStatus
from apps.listings.models import Listing
from apps.posting.models import (
    DropshippingJobConfig,
    DropshipTargetURL,
    PostingLog,
    PostingLogLevel,
)
from apps.posting.pipeline import adapter
from apps.posting.resolvers.dropship import DropshipResolver, DuplicateItem
from apps.posting.services.dropship.backoff import (
    ErrorTracker,
    PauseRequired,
    classify_api_error,
)
from apps.posting.services.dropship.asset_scrubber import scrub_sources
from apps.posting.services.dropship.source_provider import (
    DropshipSourceProvider,
    get_source_provider,
)
from apps.posting.services.shared import (
    PricingDefaults,
    build_pricing_rule,
    extract_currency_from_payload,
    extract_listing_id,
    extract_price_from_response,
    extract_title_from_payload,
    extract_title_from_response,
    serialize_response,
)
from apps.posting.services.shared.subplatform import SubplatformCache, get_allowed_platforms
from apps.posting.services.shared.tracker_fetcher import fetch_tracker_data
from payload_pipeline.core.contracts import ListingKind
from payload_pipeline.pricing.rules import PricingRule as LibPricingRule, calculate_price

# Ensure all source providers are registered
import apps.posting.services.dropship.sources  # noqa: F401

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Internal exceptions (not exported)
# ---------------------------------------------------------------------------

class _RateLimitError(Exception):
    pass


class _ValidationError(Exception):
    pass


class _ServerError(Exception):
    pass


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def poster_loop(config: DropshippingJobConfig, stop_event: Event) -> None:
    """Continuous poster loop — called by the scheduler thread wrapper.

    * Builds facades once (reused across cycles).
    * Each cycle: refresh config from DB, iterate enabled URLs, fetch+post.
    * After each cycle: wait ``poster_cycle_interval`` (interruptible).
    * Raises ``PauseRequired`` when ErrorTracker thresholds are hit.
    * Returns normally when ``stop_event`` is set (user stop / disable).
    """
    tracker = ErrorTracker(stop_event=stop_event)

    # Load proxy pool once — shared by source + target facades for this job
    proxy_pool = build_proxy_pool()

    # Source provider (LZT, etc.) — built once, reused across cycles
    source_type = config.source_account.provider
    source_provider = get_source_provider(
        source_type, config.source_account.credential, proxy_pool=proxy_pool,
    )
    source_proxy_group = get_group_name(config.source_account)

    # LZT image fetcher (needed for media pipeline when source is LZT)
    lzt_image_fetcher = _build_lzt_image_fetcher(config.source_account)

    # Target marketplace facade — built once
    marketplace = config.store.provider
    target_facade = registry.get_or_build_client(
        marketplace, config.store.credential, proxy_pool=proxy_pool,
    )
    target_provider = registry.get_provider(marketplace)
    target_proxy_group = get_group_name(config.store)

    while not stop_event.is_set():

        # Refresh config from DB at cycle start (delays/interval may have changed)
        config.refresh_from_db(fields=[
            'enabled', 'item_delay', 'source_delay', 'poster_cycle_interval',
        ])
        if not config.enabled:
            break

        # Fresh resolver per cycle (clean duplicate cache)
        target_urls = list(config.target_urls.filter(enabled=True))
        resolver = DropshipResolver()

        for target_url in target_urls:
            if stop_event.is_set():
                break

            try:
                _process_target_url(
                    config=config,
                    target_url=target_url,
                    source_provider=source_provider,
                    source_type=source_type,
                    source_proxy_group=source_proxy_group,
                    target_facade=target_facade,
                    target_provider=target_provider,
                    target_proxy_group=target_proxy_group,
                    resolver=resolver,
                    stop_event=stop_event,
                    tracker=tracker,
                    lzt_image_fetcher=lzt_image_fetcher,
                )
            except PauseRequired:
                raise  # propagate to wrapper
            except Exception as e:
                logger.exception("TargetURL #%d failed: %s", target_url.id, e)
                target_url.last_error = str(e)[:500]
                target_url.error_count += 1
                target_url.save(update_fields=['last_error', 'error_count'])

            stop_event.wait(timeout=float(config.source_delay))

        # --- Cycle end ---
        config.poster_last_cycle_at = timezone.now()
        config.save(update_fields=['poster_last_cycle_at'])
        stop_event.wait(timeout=float(config.poster_cycle_interval))


# ---------------------------------------------------------------------------
# URL processing (Phase 1: fetch, Phase 2: post)
# ---------------------------------------------------------------------------

def _process_target_url(
    *,
    config: DropshippingJobConfig,
    target_url: DropshipTargetURL,
    source_provider: DropshipSourceProvider,
    source_type: str,
    source_proxy_group: str | None,
    target_facade,
    target_provider,
    target_proxy_group: str | None,
    resolver: DropshipResolver,
    stop_event: Event,
    tracker: ErrorTracker,
    lzt_image_fetcher=None,
) -> None:
    """Fetch items from a source filter URL and post new ones."""

    # === Phase 1: Fetch + filter ===
    new_items: list[dict] = []
    total_found = 0

    for page_items in source_provider.fetch_items(target_url.url, proxy_group=source_proxy_group):
        if stop_event.is_set():
            break
        for item in page_items:
            total_found += 1
            try:
                resolver.resolve(item, source_provider)
                new_items.append(item)
            except DuplicateItem:
                continue
        stop_event.wait(timeout=float(config.source_delay))

    # === Phase 2: Post new items (with stop checks + backoff) ===
    pricing = build_pricing_rule(PricingDefaults.from_model(target_url))
    subplatform_cache = SubplatformCache(config.store, config.game, mode='dropship')
    posted_count = 0

    for item in new_items:
        if stop_event.is_set():
            break

        # DB stop check before each item
        config.refresh_from_db(fields=['enabled'])
        if not config.enabled:
            stop_event.set()
            break

        try:
            posted = _attempt_post(
                item=item,
                config=config,
                target_url=target_url,
                source_provider=source_provider,
                source_type=source_type,
                pricing=pricing,
                subplatform_cache=subplatform_cache,
                target_facade=target_facade,
                target_provider=target_provider,
                target_proxy_group=target_proxy_group,
                lzt_image_fetcher=lzt_image_fetcher,
                stop_event=stop_event,
            )
            if posted:
                tracker.on_success()
                posted_count += 1

        except _RateLimitError:
            tracker.on_rate_limit()  # backoff or PauseRequired

        except _ValidationError as e:
            _item_id = source_provider.extract_item_id(item)
            logger.warning(
                "Validation error for item %s (config #%d): %s",
                _item_id, config.id, e,
            )
            PostingLog.objects.create(
                task_name='dropship_poster',
                level=PostingLogLevel.WARNING,
                message=f"Validation error, item skipped: {_item_id}",
                detail={
                    'item_id': _item_id,
                    'config_id': config.id,
                    'error': str(e),
                },
                integration_account=config.store,
            )
            tracker.on_validation_error(_item_id, last_error=str(e))  # may raise PauseRequired

        except _ServerError:
            tracker.on_server_error()  # backoff or PauseRequired

        except Exception as e:
            _item_id = source_provider.extract_item_id(item)
            logger.warning("Post failed for item %s: %s", _item_id, e)
            PostingLog.objects.create(
                task_name='dropship_poster',
                level=PostingLogLevel.ERROR,
                message=f"Post failed: item {_item_id}",
                detail={
                    'item_id': _item_id,
                    'config_id': config.id,
                    'error': str(e),
                },
                integration_account=config.store,
            )

        stop_event.wait(timeout=float(config.item_delay))

    # Update URL stats
    target_url.last_fetched_at = timezone.now()
    target_url.items_found = total_found
    target_url.items_posted = posted_count
    target_url.last_error = ''
    target_url.error_count = 0
    target_url.save(update_fields=[
        'last_fetched_at', 'items_found', 'items_posted',
        'last_error', 'error_count',
    ])

    if posted_count:
        PostingLog.objects.create(
            task_name='dropship_poster',
            level=PostingLogLevel.SUCCESS,
            message=f"Posted {posted_count}/{total_found} items from {target_url.url[:60]}",
            detail={
                'config_id': config.id,
                'target_url_id': target_url.id,
                'total_found': total_found,
                'posted': posted_count,
            },
            integration_account=config.store,
        )


# ---------------------------------------------------------------------------
# Single item post
# ---------------------------------------------------------------------------

def _attempt_post(
    *,
    item: dict,
    config: DropshippingJobConfig,
    target_url: DropshipTargetURL,
    source_provider: DropshipSourceProvider,
    source_type: str,
    pricing: LibPricingRule,
    subplatform_cache: SubplatformCache,
    target_facade,
    target_provider,
    target_proxy_group: str | None,
    lzt_image_fetcher=None,
    stop_event: Event | None = None,
) -> bool:
    """Post a single item to the target marketplace.

    Returns True if posted successfully, False if skipped (no slot / no price / stopped).
    Raises _RateLimitError, _ValidationError, _ServerError for API failures.
    Raises RuntimeError for pipeline / unknown errors.
    """
    game = config.game
    marketplace = config.store.provider

    # Extract item ID via source provider
    item_id = source_provider.extract_item_id(item)

    # Pricing
    raw_price_float = float(str(item.get('price', 0)))
    if raw_price_float <= 0:
        logger.warning("Item %s has no price, skipping", item_id)
        return False

    final_price = Decimal(str(calculate_price(raw_price_float, pricing)))
    raw_price = Decimal(str(raw_price_float))

    # Early slot check — skip before expensive prepare() if all slots are full
    if subplatform_cache.resolve(fallback='') is None:
        logger.info(
            "No available sub-platform slots for %s/%s, skipping item %s",
            config.store.name, game.name, item.get('item_id'),
        )
        return False

    # Prepare + build via pipeline
    sources: dict = {source_type: item}
    tracker_data = fetch_tracker_data(game.slug, item)
    if tracker_data is not None:
        sources['tracker'] = tracker_data

    sources = scrub_sources(sources, game_slug=game.slug)

    prepare_result = adapter.prepare(
        game_slug=game.slug,
        sources=sources,
        kind=ListingKind.DROPSHIPPING,
        disable_media=False,
        lzt_image_fetcher=lzt_image_fetcher,
    )
    if not prepare_result.success:
        raise RuntimeError(
            f"Pipeline prepare failed [{prepare_result.error_stage}]: {prepare_result.error}"
        )

    # Final sub-platform selection — filter by account compatibility
    allowed = get_allowed_platforms(game.slug, prepare_result.prepared.subject)
    account_platform = getattr(prepare_result.prepared.subject, 'main_platform', '') or ''
    sub_platform = subplatform_cache.resolve(fallback=account_platform, allowed_platforms=allowed)
    if sub_platform is None:
        logger.info(
            "No compatible sub-platform slot for %s/%s, skipping item %s",
            config.store.name, game.name, item.get('item_id'),
        )
        return False

    pipeline_result = adapter.build(
        prepared=prepare_result.prepared,
        marketplace=marketplace,
        pricing_defaults=target_url,
        store=config.store,
        kind=ListingKind.DROPSHIPPING,
        sub_platform=sub_platform or '',
    )
    if not pipeline_result.success:
        raise RuntimeError(
            f"Pipeline build failed [{pipeline_result.error_stage}]: {pipeline_result.error}"
        )

    payload = pipeline_result.payload

    # Stop check after pipeline (which can take 30s+ with image uploads)
    # — avoids sending to marketplace when user already requested stop
    if stop_event is not None and stop_event.is_set():
        logger.info("Stop requested after pipeline build, skipping API call for item %s", item_id)
        return False

    # Marketplace POST
    product_data = {'payload': payload}
    if target_proxy_group:
        product_data['proxy_group'] = target_proxy_group

    api_result = target_provider.create_listing(target_facade, product_data)

    if not api_result.ok:
        error_type = classify_api_error(api_result)
        err = api_result.error
        parts = [f"API error: {err.message} (category={err.category})"]
        if err.status_code:
            parts.append(f"status={err.status_code}")
        if err.details:
            parts.append(f"response_body={err.details}")
        logger.debug("Rejected payload for item %s: %s", item_id, payload)
        msg = ' | '.join(parts)
        if error_type == 'rate_limit':
            raise _RateLimitError(msg)
        if error_type == 'validation':
            raise _ValidationError(msg)
        if error_type == 'server':
            raise _ServerError(msg)
        raise RuntimeError(msg)

    # Success — create DropshipProduct + Listing atomically
    store_listing_id = extract_listing_id(api_result.data)

    if not game.category_id:
        raise RuntimeError(f"Game '{game.name}' has no category assigned")

    # Title: response > payload > source item fallback
    posted_title = extract_title_from_response(api_result.data, marketplace)
    if not posted_title:
        posted_title = extract_title_from_payload(payload, marketplace)
    if not posted_title:
        posted_title = item.get('title', item.get('title_en', ''))

    # Price: prefer confirmed USD price from response
    confirmed_price = extract_price_from_response(api_result.data, marketplace)
    listing_price = confirmed_price if confirmed_price is not None else final_price

    posted_currency = extract_currency_from_payload(payload, marketplace)

    # raw_data: store both sent payload and API response for audit
    listing_raw_data: dict = {'payload': payload}
    if api_result.data is not None:
        listing_raw_data['response'] = serialize_response(api_result.data)

    with transaction.atomic():
        dp, created = DropshipProduct.objects.get_or_create(
            source_account=config.source_account,
            source_product_id=item_id,
            defaults={
                'category': game.category,
                'game': game,
                'price': raw_price,
                'currency': item.get('price_currency', 'USD'),
                'product_title': item.get('title', item.get('title_en', '')),
                'source_url': source_provider.build_source_url(item_id),
                'raw_data': item,
                'status': DropshipProductStatus.LISTED,
            },
        )
        if not created:
            # DELETED item re-posted (re-post after price change)
            # LISTED/SOLD are blocked by resolver — should not reach here
            logger.info(
                "Re-posting DELETED item %s for config #%d", item_id, config.id,
            )
            dp.status = DropshipProductStatus.LISTED
            dp.price = raw_price
            dp.currency = item.get('price_currency', 'USD')
            dp.product_title = item.get('title', item.get('title_en', ''))
            dp.source_url = source_provider.build_source_url(item_id)
            dp.raw_data = item
            dp.deleted_at = None
            dp.save(update_fields=[
                'status', 'price', 'currency', 'product_title',
                'source_url', 'raw_data', 'deleted_at',
            ])

        Listing.objects.create(
            is_instant=False,
            dropship_product=dp,
            integration_account=config.store,
            game=game,
            store_listing_id=store_listing_id,
            sub_platform=sub_platform,
            status=ListingStatus.LISTED,
            title=posted_title,
            price=listing_price,
            currency=posted_currency,
            listed_at=timezone.now(),
            raw_data=listing_raw_data,
        )

    subplatform_cache.record_post(sub_platform)
    return True


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _build_lzt_image_fetcher(source_account):
    """Build LztDefaultImageFetcher if source is LZT, else return None."""
    if source_account.provider != 'lzt':
        return None
    try:
        from payload_pipeline.shared.lzt_default_fetcher import LztDefaultImageFetcher

        creds = source_account.credential.credentials or {}
        token = creds.get('api_key', '')
        if not token:
            logger.info("No LZT token — image fetcher disabled for dropship")
            return None

        fetcher = LztDefaultImageFetcher(token=token)
        logger.debug("LZT image fetcher initialised for dropship")
        return fetcher
    except (ImportError, AttributeError, KeyError) as exc:
        logger.warning("Could not build LZT image fetcher: %s", exc)
        return None
