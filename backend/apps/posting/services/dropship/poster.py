"""Dropship poster — continuous loop driven by the scheduler service.

Public entry point: ``poster_loop(config, stop_event)``
Called by the scheduler's poster thread wrapper.  Raises ``PauseRequired``
when error thresholds are exceeded; the wrapper catches it and sets the
config to PAUSED.
"""

from __future__ import annotations

import logging
import threading
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
from apps.posting.services.shared.max_offer_error import is_max_offer_error
from apps.posting.services.variant_context import build_variant_context
from apps.posting.services.variant_routing import PLATFORM_PRIORITY, VariantRouter, get_eligible_variants
from apps.posting.services.variant_slug import resolve_listing_variant_slug
from apps.posting.services.shared.tracker_fetcher import fetch_tracker_data
from core.marketplace.normalizers import normalize_offer_response
from payload_pipeline.core.contracts import ListingCategory, ListingKind
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


class _MaxOfferError(Exception):
    """Raised when Eldorado returns 'Maximum of N active offers is allowed'."""

    def __init__(self, msg: str, variant_slug: str = ''):
        super().__init__(msg)
        self.variant_slug = variant_slug


class _StoreFullError(Exception):
    """Marketplace store hit its active-offer cap (e.g. PA 200). Capacity
    condition, NOT a payload problem — pause this cycle, do not disable."""


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
    marketplace = config.store.provider

    # === Capacity pre-check (before fetch) ===
    # Build variant context once here; reused in Phase 2 so no duplicate DB queries.
    variant_ctx = build_variant_context(
        store=config.store, game=config.game, marketplace=marketplace,
    )
    variant_router = VariantRouter(variant_ctx, mode='dropship')

    if variant_router.select('platform', game_slug=config.game.slug) is None:
        logger.info(
            "All slots full for %s/%s — skipping fetch this cycle",
            config.game.slug, config.store.name,
        )
        PostingLog.objects.create(
            task_name='dropship_poster',
            level=PostingLogLevel.INFO,
            message=f"Cycle skipped: all slots full ({config.store.name})",
            detail={'config_id': config.id, 'game': config.game.slug},
            integration_account=config.store,
        )
        return

    try:
        # === Phase 1: Fetch + filter ===
        target_url.processing_state = DropshipTargetURL.PROC_FETCHING
        try:
            target_url.save(update_fields=['processing_state'])
        except Exception:
            pass  # Row may have been deleted; continue anyway

        new_items: list[dict] = []
        cycle_found = 0

        seller_username = getattr(target_url, 'seller_username', '') or ''
        # Pre-seed the UUID cache from DB if available — avoids expensive scan
        seller_uuid_db = getattr(target_url, 'seller_uuid', None) or ''
        if seller_username and seller_uuid_db:
            from apps.posting.services.dropship.sources.eldorado import _SELLER_UUID_CACHE
            _SELLER_UUID_CACHE[seller_username.lower()] = seller_uuid_db
        for page_items in source_provider.fetch_items(target_url.url, seller_username=seller_username, proxy_group=source_proxy_group):
            if stop_event.is_set():
                break
            _min_price = float(target_url.min_price or 0)
            for item in page_items:
                cycle_found += 1
                # Pre-filter by min_price before attempting to post
                if _min_price > 0:
                    item_price = float(item.get('price') or 0)
                    if item_price < _min_price:
                        continue
                try:
                    resolver.resolve(item, source_provider)
                    new_items.append(item)
                except DuplicateItem:
                    continue
            stop_event.wait(timeout=float(config.source_delay))

        cycle_new = len(new_items)

        # === Phase 2: Post new items (with stop checks + backoff) ===
        target_url.processing_state = DropshipTargetURL.PROC_POSTING
        try:
            target_url.save(update_fields=['processing_state'])
        except Exception:
            pass  # Row may have been deleted; continue anyway

        pricing = build_pricing_rule(PricingDefaults.from_model(target_url))
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
                    variant_router=variant_router,
                    variant_ctx=variant_ctx,
                    target_facade=target_facade,
                    target_provider=target_provider,
                    target_proxy_group=target_proxy_group,
                    lzt_image_fetcher=lzt_image_fetcher,
                    stop_event=stop_event,
                )
                if posted:
                    tracker.on_success()
                    posted_count += 1

            except _MaxOfferError as e:
                # Variant fallback: try remaining variants
                _item_id = source_provider.extract_item_id(item)
                excluded = [e.variant_slug] if e.variant_slug else []
                tiers = PLATFORM_PRIORITY.get(config.game.slug, [])
                all_variants = [slug for tier in tiers for slug in tier]
                available = [v for v in all_variants if v not in excluded]

                # Build context once — it's variant-independent (DB counts + limits)
                fresh_ctx = build_variant_context(
                    store=config.store, game=config.game, marketplace=marketplace,
                )

                fallback_posted = False
                for candidate in available:
                    fresh_router = VariantRouter(fresh_ctx, mode='dropship')
                    # Force variant by setting manual override on the router
                    try:
                        posted = _attempt_post(
                            item=item,
                            config=config,
                            target_url=target_url,
                            source_provider=source_provider,
                            source_type=source_type,
                            pricing=pricing,
                            variant_router=fresh_router,
                            variant_ctx=fresh_ctx,
                            target_facade=target_facade,
                            target_provider=target_provider,
                            target_proxy_group=target_proxy_group,
                            lzt_image_fetcher=lzt_image_fetcher,
                            stop_event=stop_event,
                        )
                        if posted:
                            tracker.on_success()
                            posted_count += 1
                            fallback_posted = True
                            break
                    except _MaxOfferError as inner:
                        excluded.append(inner.variant_slug)
                        continue
                    except (_ValidationError, _RateLimitError, _ServerError):
                        break
                    except Exception as exc:
                        logger.warning(
                            "Unexpected error during variant fallback for %s/%s: %s",
                            config.game.slug, config.store.name, exc,
                        )
                        break

                if not fallback_posted:
                    logger.warning(
                        "All variants exhausted for item %s (%s/%s) — stopping posts this cycle",
                        _item_id, config.game.slug, config.store.name,
                    )
                    break  # API confirmed all slots full; no point trying remaining items

            except _StoreFullError as e:
                _item_id = source_provider.extract_item_id(item)
                logger.info(
                    "Store full for %s/%s (%s) — stopping posts this cycle",
                    config.game.slug, config.store.name, e,
                )
                PostingLog.objects.create(
                    task_name='dropship_poster',
                    level=PostingLogLevel.WARNING,
                    message=f"Store full — posting paused this cycle: {config.store.name}",
                    detail={'config_id': config.id, 'item_id': _item_id, 'error': str(e)},
                    integration_account=config.store,
                )
                break  # exit items loop; cycle retries next interval

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
        target_url.cycle_found = cycle_found
        target_url.cycle_new = cycle_new
        target_url.cycle_posted = posted_count
        target_url.last_error = ''
        target_url.error_count = 0
        try:
            target_url.save(update_fields=[
                'last_fetched_at', 'cycle_found', 'cycle_new', 'cycle_posted',
                'last_error', 'error_count',
            ])
        except Exception:
            pass  # Row may have been deleted; stats update skipped

        if posted_count:
            PostingLog.objects.create(
                task_name='dropship_poster',
                level=PostingLogLevel.SUCCESS,
                message=f"Posted {posted_count}/{cycle_found} items from {target_url.url[:60]}",
                detail={
                    'config_id': config.id,
                    'target_url_id': target_url.id,
                    'cycle_found': cycle_found,
                    'cycle_new': cycle_new,
                    'cycle_posted': posted_count,
                },
                integration_account=config.store,
            )
    finally:
        # Reset processing state regardless of exit path (exception, early return, etc.)
        DropshipTargetURL.objects.filter(pk=target_url.pk).update(
            processing_state=DropshipTargetURL.PROC_IDLE,
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
    variant_router: VariantRouter,
    variant_ctx: dict | None,
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

    # SAB item dropship must never post non-SAB Eldorado offers. Seller-UUID
    # fetches omit gameId server-side; source filter is primary, this is a
    # last-line guard in case a wrong-game item still reaches the poster.
    if game.slug == 'steal-a-brainrot' and source_type == 'eldorado':
        from apps.posting.services.dropship.sources.eldorado import (
            SAB_GAME_ID,
            _coerce_game_id,
        )
        item_game_id = _coerce_game_id(item.get('gameId') or item.get('game_id'))
        if item_game_id is not None and item_game_id != SAB_GAME_ID:
            logger.warning(
                "Skipping non-SAB Eldorado item %s (gameId=%s, expected=%s)",
                item_id, item_game_id, SAB_GAME_ID,
            )
            return False

    # Pricing
    raw_price_float = float(str(item.get('price', 0)))
    if raw_price_float <= 0:
        logger.warning("Item %s has no price, skipping", item_id)
        return False

    final_price = Decimal(str(calculate_price(raw_price_float, pricing)))
    if target_url.exchange_rate is not None:
        final_price = (final_price * Decimal(str(target_url.exchange_rate))).quantize(Decimal('0.01'))
    raw_price = Decimal(str(raw_price_float))

    # Early slot check — all platform slots full → stop the items loop
    if variant_router.select('platform', game_slug=game.slug) is None:
        raise _StoreFullError(
            f"All platform slots full for {game.slug}/{config.store.name}"
        )

    # Prepare + build via pipeline
    sources: dict = {source_type: item}
    if game.slug != "rainbow-six-siege":
        tracker_data = fetch_tracker_data(game.slug, item)
        if tracker_data is not None:
            sources['tracker'] = tracker_data

    sources = scrub_sources(sources, game_slug=game.slug)

    _ITEM_GAMES = frozenset({"steal-a-brainrot", "new-world"})
    _listing_category = (
        ListingCategory.ITEM
        if game.slug in _ITEM_GAMES
        else ListingCategory.ACCOUNT
    )
    prepare_result = adapter.prepare(
        game_slug=game.slug,
        sources=sources,
        kind=ListingKind.DROPSHIPPING,
        category=_listing_category,
        disable_media=False,
        lzt_image_fetcher=lzt_image_fetcher,
    )
    if not prepare_result.success:
        raise RuntimeError(
            f"Pipeline prepare failed [{prepare_result.error_stage}]: {prepare_result.error}"
        )

    # Final variant selection — filter by account compatibility
    allowed = get_eligible_variants(game.slug, prepare_result.prepared.subject)
    variant_slug = variant_router.select(
        'platform', allowed=allowed, game_slug=game.slug,
    )
    if variant_slug is None:
        logger.info(
            "No compatible variant slot for %s/%s, skipping item %s",
            config.store.name, game.name, item.get('item_id'),
        )
        return False

    # Region capacity check — for games with region variants (e.g. LoL) where the
    # account's region is fixed. Verifies the account's region has remaining dropship
    # capacity before posting.
    region_slug = ''
    if variant_ctx and 'region' in variant_ctx:
        region_phrase = getattr(prepare_result.prepared.subject, 'region_phrase', '')
        if region_phrase:
            region_slug = variant_router.select_fixed('region', region_phrase)
            if region_slug and variant_router.select('region', allowed={region_slug}) is None:
                logger.info(
                    "Region '%s' capacity exhausted for %s/%s, skipping item %s",
                    region_slug, config.store.name, game.name, item.get('item_id'),
                )
                return False

    pipeline_result = adapter.build(
        prepared=prepare_result.prepared,
        marketplace=marketplace,
        pricing_defaults=target_url,
        store=config.store,
        kind=ListingKind.DROPSHIPPING,
        variant_slug=variant_slug or '',
        variant_context=variant_ctx,
    )
    if not pipeline_result.success:
        raise RuntimeError(
            f"Pipeline build failed [{pipeline_result.error_stage}]: {pipeline_result.error}"
        )

    payload = pipeline_result.payload
    listing_variant_slug = resolve_listing_variant_slug(
        subject=prepare_result.prepared.subject,
        variant_ctx=variant_ctx,
        selected_variants={'platform': variant_slug} if variant_slug else None,
        fallback=variant_slug or '',
    )

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
        # Check max offer error before generic classification
        if is_max_offer_error(api_result):
            err = api_result.error
            msg = f"Max offer limit: {err.message}" if err else "Max offer limit reached"
            if game.slug in PLATFORM_PRIORITY:
                # Variant platform (Eldorado): try the next variant slot
                raise _MaxOfferError(msg, variant_slug=variant_slug or '')
            # Non-variant platform (e.g. PlayerAuctions): whole store is full
            raise _StoreFullError(msg)

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
    # GameBoost: publish the newly created offer (draft → listed)
    if marketplace == 'gameboost':
        _ITEM_GAMES_PUB = frozenset({"steal-a-brainrot", "new-world"})
        _publish_fn = (
            target_facade.list_item_offer
            if game.slug in _ITEM_GAMES_PUB
            else target_facade.list_account_offer
        )
        pub_result = _publish_fn(
            str(store_listing_id),
            proxy_group=target_proxy_group,
        )
        if not pub_result.ok:
            err = pub_result.error
            logger.warning(
                "GameBoost publish failed for offer %s (store=%s): %s",
                store_listing_id, config.store.name,
                getattr(err, 'message', err),
            )
        else:
            logger.info(
                "GameBoost offer %s published (listed) for store=%s",
                store_listing_id, config.store.name,
            )

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

    if marketplace in {'eldorado', 'gameboost', 'playerauctions'}:
        listing_raw_data = normalize_offer_response(
            marketplace,
            api_result.data,
            payload=payload,
            client=target_facade,
            proxy_group=target_proxy_group,
        )
    else:
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
            variant=listing_variant_slug,
            status=ListingStatus.LISTED,
            title=posted_title,
            price=listing_price,
            currency=posted_currency,
            listed_at=timezone.now(),
            raw_data=listing_raw_data,
        )

    variant_router.record_post('platform', variant_slug)
    if region_slug:
        variant_router.record_post('region', region_slug)
    # SAB lifecycle: notify MCT immediately so sheet + U7Buy listing are created without 5-min delay
    if game.slug == 'steal-a-brainrot' and marketplace == 'gameboost':
        _sab_code = item.get('code') or item.get('item_code') or str(item_id)
        _sab_offer_id = str(store_listing_id)
        _sab_store = config.store.name
        _sab_title = posted_title or ''
        _sab_price = str(listing_price) if listing_price is not None else ''
        def _notify_mct_sab():
            try:
                import requests as _req
                from django.conf import settings as _dj_settings
                _bridge_url = getattr(_dj_settings, 'CT_BRIDGE_URL', '')
                _bridge_secret = getattr(_dj_settings, 'CT_BRIDGE_SECRET', 'bridge-ce1b9d8001c8fc76ccbfd28c44832eec299ccc89ea537e9d')
                import re as _re
                _base = _re.sub(r'/api/.*', '', _bridge_url) if _bridge_url else 'http://35.196.132.30:3456'
                _url = f'{_base}/api/bridge/sab-gb-listed'
                _resp = _req.post(
                    _url,
                    json={'code': _sab_code, 'gbOfferId': _sab_offer_id, 'gbStore': _sab_store, 'title': _sab_title, 'price': _sab_price, 'gbListingUrl': None, 'eldoradoGameId': item.get('gameId')},
                    headers={'x-bridge-secret': _bridge_secret},
                    timeout=10,
                )
                import logging as _log
                _log.getLogger(__name__).info('[SABWebhook] MCT notified code=%s offerId=%s status=%s', _sab_code, _sab_offer_id, _resp.status_code)
            except Exception as _e:
                import logging as _log
                _log.getLogger(__name__).warning('[SABWebhook] MCT notify failed: %s', _e)
        threading.Thread(target=_notify_mct_sab, daemon=True).start()
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
