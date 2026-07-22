"""Offer Pool (Auto Restock) API endpoints."""
from __future__ import annotations

import hashlib
import json
import logging
import uuid

from django.contrib.auth.decorators import login_required
from django.core.exceptions import ObjectDoesNotExist, ValidationError
from django.db import IntegrityError, transaction
from django.db.models import Count, Exists, OuterRef, Q
from django.http import JsonResponse
from django.views.decorators.http import require_POST, require_GET, require_http_methods

from apps.integrations.models import IntegrationAccount
from apps.inventory.models import Game, OwnedProduct
from apps.listings.models import Listing, ListingOwnedProduct
from apps.listings.utils import parse_price
from apps.orders.enums import OrderStatus
from apps.posting.models import (
    OfferPool,
    OfferPoolActiveOffer,
    OfferPoolActiveOfferStatus,
    OfferPoolItem,
    OfferPoolItemStatus,
    OfferPoolStatus,
    CredentialSpec,
    GameVariant,
    PoolDispatchAttempt,
    PoolDispatchReservation,
    PoolDispatchReservationStatus,
    PoolDispatchStatus,
    PoolOffer,
    PoolOfferStatus,
    PoolOfferStrategy,
    PoolSaleEvent,
    PostingDefault,
)

logger = logging.getLogger(__name__)


# ── Pool CRUD ─────────────────────────────────────────────────────


@login_required
@require_http_methods(['GET', 'POST'])
def list_pools(request):
    """List all offer pools with summary stats."""
    if request.method == 'POST':
        return create_pool(request)
    pools = (
        OfferPool.objects
        .select_related('game', 'variant', 'credential_spec')
        .prefetch_related('pool_offers__listing__integration_account')
        .annotate(
            _items_pending=Count('items', filter=Q(items__status=OfferPoolItemStatus.PENDING)),
            _items_queued=Count('items', filter=Q(items__status=OfferPoolItemStatus.QUEUED)),
            _items_pushed=Count('items', filter=Q(items__status=OfferPoolItemStatus.PUSHED)),
            _items_failed=Count('items', filter=Q(items__status=OfferPoolItemStatus.FAILED)),
            _items_consumed=Count('items', filter=Q(items__status=OfferPoolItemStatus.CONSUMED)),
            _has_blocking_items=Exists(
                OfferPoolItem.objects.filter(
                    pool_id=OuterRef('pk'),
                    status__in=_POOL_DELETE_BLOCKING_ITEM_STATUSES,
                ),
            ),
            _has_blocking_pool_offers=Exists(
                PoolOffer.objects.filter(pool_id=OuterRef('pk')).exclude(
                    status=PoolOfferStatus.DETACHED,
                ),
            ),
            _has_blocking_active_offers=Exists(
                OfferPoolActiveOffer.objects.filter(
                    pool_id=OuterRef('pk'),
                    status=OfferPoolActiveOfferStatus.ACTIVE,
                ),
            ),
            _has_blocking_reservations=Exists(
                PoolDispatchReservation.objects.filter(
                    pool_id=OuterRef('pk'),
                    status=PoolDispatchReservationStatus.ACTIVE,
                ),
            ),
            _has_blocking_attempts=Exists(
                PoolDispatchAttempt.objects.filter(
                    pool_offer__pool_id=OuterRef('pk'),
                    status__in=_POOL_DELETE_BLOCKING_ATTEMPT_STATUSES,
                ),
            ),
        )
        .order_by('-created_at')
    )

    # Optional filters
    game_id = request.GET.get('game')
    if game_id:
        pools = pools.filter(game_id=game_id)

    status = request.GET.get('status')
    if status in OfferPoolStatus.values:
        pools = pools.filter(status=status)

    data = []
    for pool in pools:
        data.append(_pool_to_dict(pool))

    return JsonResponse({'pools': data})


@login_required
@require_POST
def create_pool(request):
    """Create an offer-independent stock pool."""
    try:
        body = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({'error': 'Invalid JSON'}, status=400)

    name = str(body.get('name') or '').strip()
    if not name:
        return JsonResponse({'error': 'name is required', 'error_code': 'name_required'}, status=400)
    game_id = body.get('game_id')
    if not game_id:
        return JsonResponse({'error': 'game_id is required'}, status=400)

    try:
        game = Game.objects.get(id=game_id)
    except Game.DoesNotExist:
        return JsonResponse({'error': 'Game not found'}, status=404)

    variant = None
    variant_id = body.get('variant_id')
    if variant_id:
        try:
            variant = GameVariant.objects.get(pk=variant_id, game=game)
        except GameVariant.DoesNotExist:
            return JsonResponse({'error': 'Variant not found for this game'}, status=400)

    credential_spec = None
    credential_spec_id = body.get('credential_spec_id')
    if credential_spec_id:
        try:
            credential_spec = CredentialSpec.objects.get(pk=credential_spec_id, game=game)
        except CredentialSpec.DoesNotExist:
            return JsonResponse({'error': 'Credential spec not found for this game'}, status=400)

    pool = OfferPool(
        name=name[:255],
        game=game,
        variant=variant,
        credential_spec=credential_spec,
        status=OfferPoolStatus.ACTIVE,
    )
    try:
        pool.full_clean()
        pool.save()
    except ValidationError as exc:
        return JsonResponse({'error': exc.message_dict}, status=400)

    # Add initial credentials if provided
    credentials = body.get('credentials', [])
    create_result = {'added': 0, 'skipped': [], 'warnings': [], 'needs_confirmation': []}
    if credentials:
        _add_credentials_to_pool(
            pool, credentials, game, listing=None,
            force=True, result=create_result,
        )

    pool.refresh_from_db()
    return JsonResponse({
        'pool': _pool_to_dict(pool),
        **create_result,
    }, status=201)


@login_required
@require_http_methods(['GET', 'PATCH', 'DELETE'])
def pool_detail(request, pool_id):
    """Get pool detail with all items."""
    if request.method == 'PATCH':
        return update_pool(request, pool_id)
    if request.method == 'DELETE':
        return delete_pool(request, pool_id)
    try:
        pool = (
            OfferPool.objects
            .select_related('game', 'variant', 'credential_spec')
            .prefetch_related('pool_offers__listing__integration_account')
            .get(id=pool_id)
        )
    except OfferPool.DoesNotExist:
        return JsonResponse({'error': 'Pool not found'}, status=404)

    items = list(
        pool.items
        .select_related('owned_product', 'pool_offer')
        .order_by('order', 'created_at')
    )

    active_offers = list(
        OfferPoolActiveOffer.objects.filter(pool_offer__pool=pool)
        .select_related('listing', 'pool_item', 'pool_offer')
        .order_by('-created_at')
    )

    pool_offers = list(
        pool.pool_offers.select_related('listing', 'listing__integration_account')
        .order_by('created_at')
    )

    return JsonResponse({
        'pool': _pool_to_dict(pool),
        'pool_offers': [_pool_offer_to_dict(po) for po in pool_offers],
        'items': [_item_to_dict(item) for item in items],
        'active_offers': [_active_offer_to_dict(ao) for ao in active_offers],
    })


@login_required
@require_http_methods(['PATCH'])
def update_pool(request, pool_id):
    """Update pool identity and user-controlled intent."""
    try:
        pool = OfferPool.objects.get(id=pool_id)
    except OfferPool.DoesNotExist:
        return JsonResponse({'error': 'Pool not found'}, status=404)

    try:
        body = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({'error': 'Invalid JSON'}, status=400)

    update_fields = ['updated_at']

    if 'name' in body:
        name = str(body['name'] or '').strip()
        if not name:
            return JsonResponse({'error': 'name cannot be empty'}, status=400)
        pool.name = name[:255]
        update_fields.append('name')

    if 'status' in body:
        new_status = body['status']
        if new_status in {
            OfferPoolStatus.ACTIVE,
            OfferPoolStatus.PAUSED,
            OfferPoolStatus.ARCHIVED,
        }:
            pool.status = new_status
            update_fields.append('status')

    if 'variant_id' in body:
        variant_id = body.get('variant_id')
        if variant_id:
            try:
                pool.variant = GameVariant.objects.get(pk=variant_id, game=pool.game)
            except GameVariant.DoesNotExist:
                return JsonResponse({'error': 'Variant not found for this game'}, status=400)
        else:
            pool.variant = None
        update_fields.append('variant')

    if 'credential_spec_id' in body:
        spec_id = body.get('credential_spec_id')
        if spec_id:
            try:
                pool.credential_spec = CredentialSpec.objects.get(pk=spec_id, game=pool.game)
            except CredentialSpec.DoesNotExist:
                return JsonResponse({'error': 'Credential spec not found for this game'}, status=400)
        else:
            pool.credential_spec = None
        update_fields.append('credential_spec')

    try:
        pool.full_clean()
        pool.save(update_fields=update_fields)
    except ValidationError as exc:
        return JsonResponse({'error': exc.message_dict}, status=400)
    return JsonResponse({'pool': _pool_to_dict(pool)})


@login_required
@require_http_methods(['POST', 'DELETE'])
def delete_pool(request, pool_id):
    """Archive by default; hard-delete a Pool when no remote work is active."""
    try:
        body = json.loads(request.body or b'{}')
    except json.JSONDecodeError:
        return JsonResponse({'error': 'Invalid JSON'}, status=400)

    if body.get('hard'):
        with transaction.atomic():
            try:
                pool = OfferPool.objects.select_for_update().get(id=pool_id)
            except OfferPool.DoesNotExist:
                return JsonResponse({'error': 'Pool not found'}, status=404)

            blockers = _pool_delete_blockers(pool)
            if blockers:
                return JsonResponse({
                    'error': 'Pool cannot be deleted while marketplace work is active',
                    'error_code': 'pool_delete_blocked',
                    'blockers': blockers,
                }, status=409)

            pool_offer_ids = list(pool.pool_offers.values_list('pk', flat=True))
            item_count = pool.items.count()
            offer_count = len(pool_offer_ids)

            if pool_offer_ids:
                PoolSaleEvent.objects.filter(
                    pool_offer_id__in=pool_offer_ids,
                ).update(pool_offer=None)
                PoolDispatchAttempt.objects.filter(
                    pool_offer_id__in=pool_offer_ids,
                ).delete()

            OfferPoolActiveOffer.objects.filter(pool=pool).delete()
            pool.items.update(reservation=None)
            pool.items.all().delete()
            pool.dispatch_reservations.all().delete()
            pool.pool_offers.all().delete()
            pool.delete()

        return JsonResponse({
            'ok': True,
            'deleted': True,
            'removed_pool_items': item_count,
            'removed_pool_offers': offer_count,
            'listings_preserved': True,
            'inventory_preserved': True,
        })

    try:
        pool = OfferPool.objects.get(id=pool_id)
    except OfferPool.DoesNotExist:
        return JsonResponse({'error': 'Pool not found'}, status=404)
    pool.status = OfferPoolStatus.ARCHIVED
    pool.save(update_fields=['status', 'updated_at'])
    return JsonResponse({'ok': True, 'archived': True})


# ── Linked Offer Management ─────────────────────────────────────


@login_required
@require_POST
def add_pool_offer(request, pool_id):
    """Link one eligible listing to a pool and derive strategy server-side."""
    try:
        pool = OfferPool.objects.select_related('game', 'variant').get(pk=pool_id)
    except OfferPool.DoesNotExist:
        return JsonResponse({'error': 'Pool not found'}, status=404)
    try:
        body = json.loads(request.body)
        listing_id = int(body['listing_id'])
        target_count = int(body.get('target_count', 5))
        threshold = int(body.get('threshold', 2))
    except (json.JSONDecodeError, KeyError, TypeError, ValueError):
        return JsonResponse({'error': 'Invalid listing/config payload'}, status=400)

    try:
        listing = Listing.objects.select_related(
            'integration_account', 'integration_account__credential', 'game',
        ).get(pk=listing_id)
    except Listing.DoesNotExist:
        return JsonResponse({'error': 'Listing not found'}, status=404)

    if listing.status != 'listed' or not listing.is_instant:
        return JsonResponse({'error': 'Listing must be an active instant listing'}, status=400)
    if listing.pool_active_offers.exists():
        return JsonResponse({
            'error': 'Listing is already managed as a PlayerAuctions active offer',
            'error_code': 'listing_already_managed',
        }, status=409)
    if not listing.integration_account_id:
        return JsonResponse({'error': 'Listing has no integration account'}, status=400)
    try:
        credential = listing.integration_account.credential
    except ObjectDoesNotExist:
        credential = None
    if not credential or not credential.is_active:
        return JsonResponse({'error': 'Listing store has no active credential'}, status=400)
    if listing.game_id != pool.game_id:
        return JsonResponse({'error': 'Listing game does not match pool game'}, status=400)
    if pool.variant_id:
        from apps.posting.services.pool.spec_resolver import variant_value_contains_slug
        if not variant_value_contains_slug(listing.variant, pool.variant.slug):
            return JsonResponse({'error': 'Listing variant does not match pool variant'}, status=400)

    try:
        strategy = PoolOffer.strategy_for_provider(listing.integration_account.provider)
    except ValidationError as exc:
        return JsonResponse({'error': str(exc)}, status=400)
    max_concurrent = None
    if strategy == PoolOfferStrategy.CLONE:
        try:
            max_concurrent = int(body.get('max_concurrent', 10))
        except (TypeError, ValueError):
            return JsonResponse({'error': 'max_concurrent must be an integer'}, status=400)

    pool_offer = PoolOffer(
        pool=pool,
        listing=listing,
        strategy=strategy,
        target_count=target_count,
        threshold=threshold,
        max_concurrent=max_concurrent,
    )
    try:
        with transaction.atomic():
            pool_offer.full_clean()
            pool_offer.save()
            if strategy == PoolOfferStrategy.CLONE:
                _adopt_pa_source_listing(pool_offer)
    except ValidationError as exc:
        return JsonResponse({'error': exc.message_dict}, status=400)
    except IntegrityError:
        return JsonResponse({
            'error': 'Listing is already linked to a pool',
            'error_code': 'listing_already_linked',
        }, status=409)

    return JsonResponse({'pool_offer': _pool_offer_to_dict(pool_offer)}, status=201)


def _adopt_pa_source_listing(pool_offer: PoolOffer) -> None:
    """Count an existing credential-bearing PA source listing as offer #1."""
    listing = pool_offer.listing
    links = list(
        listing.listing_owned_products.select_related('owned_product')[:2]
    )
    if not links:
        return  # template-only source
    if len(links) > 1:
        raise ValidationError({'listing': 'PA source listing must contain at most one credential.'})

    owned_product = links[0].owned_product
    item, created = OfferPoolItem.objects.get_or_create(
        owned_product=owned_product,
        defaults={
            'pool': pool_offer.pool,
            'pool_offer': pool_offer,
            'status': OfferPoolItemStatus.PUSHED,
            'target_offer_id': listing.store_listing_id,
            'remote_state': 'present',
            'pushed_at': listing.listed_at or listing.created_at,
            'order': pool_offer.pool.items.count(),
        },
    )
    if not created:
        if item.pool_id != pool_offer.pool_id:
            raise ValidationError({'listing': 'Credential is managed by another pool.'})
        if item.pool_offer_id and item.pool_offer_id != pool_offer.pk:
            raise ValidationError({'listing': 'Credential is assigned to another offer.'})
        item.pool_offer = pool_offer
        item.status = OfferPoolItemStatus.PUSHED
        item.target_offer_id = listing.store_listing_id
        item.remote_state = 'present'
        item.pushed_at = item.pushed_at or listing.listed_at or listing.created_at
        item.save(update_fields=[
            'pool_offer', 'status', 'target_offer_id', 'remote_state',
            'pushed_at', 'updated_at',
        ])

    OfferPoolActiveOffer.objects.create(
        pool=pool_offer.pool,
        pool_offer=pool_offer,
        listing=listing,
        pool_item=item,
        store_listing_id=listing.store_listing_id,
    )
    pool_offer.current_remote_count = 1
    pool_offer.save(update_fields=['current_remote_count', 'updated_at'])


@login_required
@require_http_methods(['PATCH'])
def update_pool_offer(request, pool_id, offer_id):
    try:
        pool_offer = PoolOffer.objects.select_related(
            'pool', 'listing', 'listing__integration_account',
        ).get(pk=offer_id, pool_id=pool_id)
    except PoolOffer.DoesNotExist:
        return JsonResponse({'error': 'Pool offer not found'}, status=404)
    try:
        body = json.loads(request.body)
        if 'target_count' in body:
            pool_offer.target_count = int(body['target_count'])
        if 'threshold' in body:
            pool_offer.threshold = int(body['threshold'])
        if 'max_concurrent' in body:
            value = body['max_concurrent']
            pool_offer.max_concurrent = int(value) if value is not None else None
        if 'status' in body:
            if body['status'] not in PoolOfferStatus.values:
                return JsonResponse({'error': 'Invalid PoolOffer status'}, status=400)
            pool_offer.status = body['status']
        pool_offer.full_clean()
        pool_offer.save()
    except (json.JSONDecodeError, TypeError, ValueError):
        return JsonResponse({'error': 'Invalid config payload'}, status=400)
    except ValidationError as exc:
        return JsonResponse({'error': exc.message_dict}, status=400)
    return JsonResponse({'pool_offer': _pool_offer_to_dict(pool_offer)})


@login_required
@require_http_methods(['DELETE', 'POST'])
def unlink_pool_offer(request, pool_id, offer_id):
    try:
        pool_offer = PoolOffer.objects.get(pk=offer_id, pool_id=pool_id)
    except PoolOffer.DoesNotExist:
        return JsonResponse({'error': 'Pool offer not found'}, status=404)
    try:
        body = json.loads(request.body or b'{}')
    except json.JSONDecodeError:
        return JsonResponse({'error': 'Invalid JSON'}, status=400)
    mode = body.get('mode')
    if mode not in {'leave_remote', 'remove_remote'}:
        return JsonResponse({'error': 'mode must be leave_remote or remove_remote'}, status=400)

    from apps.posting.services.pool.lifecycle import detach_pool_offer
    result = detach_pool_offer(pool_offer, mode)
    return JsonResponse({
        'ok': result.ok,
        'detached': result.detached,
        'released': result.released,
        'errors': result.errors,
    }, status=200 if result.ok else 409)


# ── Pool Item Management ─────────────────────────────────────────


@login_required
@require_POST
def add_pool_items(request, pool_id):
    """Add credentials to a pool with validation.

    POST body (JSON):
        credentials: list[dict]  — [{login, password, email?, ...}]
        owned_product_ids: list[int] — existing OwnedProduct IDs to add
        force: bool              — skip warnings (sold accounts) and add anyway

    Response:
        added: int
        total_pending: int
        skipped: [{login, reason, detail?}]   — blocked, not added
        warnings: [{login, reason, detail?}]  — added despite warning (or needs confirm)
        needs_confirmation: [login, ...]       — re-submit with force=true to add these
    """
    try:
        pool = OfferPool.objects.select_related('game', 'variant').get(id=pool_id)
    except OfferPool.DoesNotExist:
        return JsonResponse({'error': 'Pool not found'}, status=404)

    try:
        body = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({'error': 'Invalid JSON'}, status=400)

    force = bool(body.get('force', False))
    result = {'added': 0, 'skipped': [], 'warnings': [], 'needs_confirmation': []}

    # Mode 1: raw credentials → create OwnedProducts + add to pool
    credentials = body.get('credentials', [])
    if credentials:
        reference_listing = pool.pool_offers.select_related('listing').first()
        _add_credentials_to_pool(
            pool, credentials, pool.game,
            listing=reference_listing.listing if reference_listing else None,
                                 force=force, result=result)

    # Mode 2: existing OwnedProduct IDs
    owned_product_ids = body.get('owned_product_ids', [])
    if owned_product_ids:
        products = OwnedProduct.objects.filter(id__in=owned_product_ids)
        max_order = pool.items.count()
        for i, product in enumerate(products):
            check = _validate_pool_candidate(product, pool)
            if check['block']:
                result['skipped'].append({
                    'login': product.login,
                    'reason': check['block_reason'],
                    'detail': check['block_detail'],
                })
                continue
            if not _process_warnings(check, product.login, force, result):
                continue

            _, created = OfferPoolItem.objects.get_or_create(
                pool=pool,
                owned_product=product,
                defaults={'order': max_order + i},
            )
            if created:
                result['added'] += 1

    pool.refresh_from_db()
    result['total_pending'] = pool.pending_count
    return JsonResponse(result)


@login_required
@require_POST
def remove_pool_item(request, pool_id, item_id):
    """Remove one Pool key locally or from its assigned marketplace offer."""
    try:
        item = (
            OfferPoolItem.objects
            .select_related('pool_offer__listing', 'owned_product')
            .get(id=item_id, pool_id=pool_id)
        )
    except OfferPoolItem.DoesNotExist:
        return JsonResponse({'error': 'Item not found'}, status=404)

    if item.status == OfferPoolItemStatus.RESERVED:
        return JsonResponse({
            'error': 'This key is reserved by an in-progress dispatch. Try again after it finishes.',
        }, status=409)

    if item.status == OfferPoolItemStatus.PENDING and item.pool_offer_id is None:
        item.delete()
        return JsonResponse({
            'ok': True,
            'removed_from_marketplace': False,
            'message': 'Pending key removed from the Pool. The account remains in inventory.',
        })

    if not item.pool_offer_id:
        return JsonResponse({
            'error': f'Cannot safely remove an unassigned key with status {item.status}.',
        }, status=409)

    from apps.posting.services.pool.lifecycle import remove_pool_item as remove_assigned_item

    result = remove_assigned_item(
        item.pool_offer,
        item,
        listing=item.pool_offer.listing,
    )
    if not result.ok:
        return JsonResponse({
            'error': '; '.join(result.errors) or 'Key removal failed',
        }, status=409)

    item.refresh_from_db(fields=['status'])
    return JsonResponse({
        'ok': True,
        'removed_from_marketplace': result.remote_removed,
        'status': item.status,
        'message': (
            'Key removed from the marketplace offer and Pool.'
            if result.remote_removed
            else 'Key removed from the Pool assignment.'
        ),
    })


@login_required
@require_POST
def retry_pool_item(request, pool_id, item_id):
    """Retry only failures whose remote absence is known."""
    try:
        with transaction.atomic():
            item = OfferPoolItem.objects.select_for_update().get(
                pk=item_id,
                pool_id=pool_id,
            )
            if item.status != OfferPoolItemStatus.FAILED:
                return JsonResponse({'error': 'Only FAILED items can be retried'}, status=400)
            if item.remote_state != 'absent':
                return JsonResponse({
                    'error': 'Remote outcome must be reconciled before retry',
                    'error_code': 'reconcile_required',
                }, status=409)
            item.status = OfferPoolItemStatus.PENDING
            item.pool_offer = None
            item.failure_stage = ''
            item.error_message = ''
            item.remote_credential_id = ''
            item.target_offer_id = ''
            item.save(update_fields=[
                'status', 'pool_offer', 'failure_stage', 'error_message',
                'remote_credential_id', 'target_offer_id', 'updated_at',
            ])
    except OfferPoolItem.DoesNotExist:
        return JsonResponse({'error': 'Item not found'}, status=404)
    return JsonResponse({'ok': True, 'item': _item_to_dict(item)})


# ── Pool Actions ─────────────────────────────────────────────────


@login_required
@require_POST
def trigger_replenish(request, pool_id):
    """Manually trigger a replenish check for a pool."""
    from apps.posting.services.pool.checker import _check_and_replenish

    try:
        pool = (
            OfferPool.objects
            .select_related('game')
            .prefetch_related('pool_offers')
            .get(id=pool_id)
        )
    except OfferPool.DoesNotExist:
        return JsonResponse({'error': 'Pool not found'}, status=404)

    if pool.status != OfferPoolStatus.ACTIVE:
        return JsonResponse({'error': f'Pool is {pool.status}, not active'}, status=400)

    results = []
    pool_offers = list(
        pool.pool_offers.exclude(status=PoolOfferStatus.DETACHED)
    )
    pool_offers.sort(key=lambda offer: (
        -1 if offer.current_remote_count is None else (
            offer.current_remote_count / max(offer.target_count, 1)
        ),
        offer.pk,
    ))
    for pool_offer in pool_offers:
        try:
            pushed = _check_and_replenish(pool_offer, force=True)
            results.append({
                'pool_offer_id': pool_offer.pk,
                'pushed': pushed,
                'status': 'succeeded',
            })
        except Exception as exc:
            logger.exception(
                'pool API: manual replenish failed for pool_offer %d',
                pool_offer.pk,
            )
            results.append({
                'pool_offer_id': pool_offer.pk,
                'pushed': 0,
                'status': 'failed',
                'error': str(exc)[:500],
            })

    pool.refresh_from_db()
    return JsonResponse({
        'pushed': sum(item['pushed'] for item in results),
        'results': results,
        'pool': _pool_to_dict(pool),
    })


# ── Pool Offer Edit ──────────────────────────────────────────────


@login_required
@require_POST
def edit_pool_offers(request, pool_id):
    """Edit title/description/price of all offers in a pool."""
    try:
        body = json.loads(request.body)
    except (json.JSONDecodeError, ValueError):
        return JsonResponse({'error': 'Invalid JSON'}, status=400)

    try:
        pool = (
            OfferPool.objects
            .select_related('game')
            .prefetch_related(
                'pool_offers__listing__integration_account__credential',
            )
            .get(id=pool_id)
        )
    except OfferPool.DoesNotExist:
        return JsonResponse({'error': 'Pool not found'}, status=404)

    changes = {}
    if 'title' in body:
        title = str(body['title']).strip() if body['title'] else ''
        if not title:
            return JsonResponse({'error': 'title cannot be empty'}, status=400)
        changes['title'] = title
    if 'description' in body:
        description = str(body['description']).strip() if body['description'] else ''
        if not description:
            return JsonResponse({'error': 'description cannot be empty'}, status=400)
        changes['description'] = description
    if 'price' in body and body['price'] is not None:
        try:
            changes['price'] = parse_price(body['price'])
        except ValueError as exc:
            return JsonResponse({'error': str(exc)}, status=400)

    if not changes:
        return JsonResponse({'error': 'No changes provided'}, status=400)

    from apps.posting.services.offer_editor import edit_pool_offers as _edit_pool_offers

    try:
        result = _edit_pool_offers(pool, changes)
    except Exception as exc:
        logger.exception('pool API: edit_pool_offers failed for pool %d', pool_id)
        return JsonResponse({'error': str(exc)[:500]}, status=500)

    status_code = 200 if result.failed == 0 else 207
    return JsonResponse({
        'ok': result.failed == 0,
        'total': result.total,
        'succeeded': result.succeeded,
        'failed': result.failed,
        'errors': result.errors,
    }, status=status_code)


# ── Single Offer Edit ────────────────────────────────────────────


@login_required
@require_POST
def edit_single_pool_offer(request, pool_id, offer_id):
    """Edit title/description/price of one linked offer on the marketplace."""
    try:
        body = json.loads(request.body)
    except (json.JSONDecodeError, ValueError):
        return JsonResponse({'error': 'Invalid JSON'}, status=400)

    try:
        pool_offer = PoolOffer.objects.select_related(
            'pool', 'listing', 'listing__integration_account',
            'listing__integration_account__credential',
        ).get(pk=offer_id, pool_id=pool_id)
    except PoolOffer.DoesNotExist:
        return JsonResponse({'error': 'Pool offer not found'}, status=404)

    changes = {}
    if 'title' in body:
        title = str(body['title']).strip() if body['title'] else ''
        if not title:
            return JsonResponse({'error': 'title cannot be empty'}, status=400)
        changes['title'] = title
    if 'description' in body:
        description = str(body['description']).strip() if body['description'] else ''
        if not description:
            return JsonResponse({'error': 'description cannot be empty'}, status=400)
        changes['description'] = description
    if 'price' in body and body['price'] is not None:
        try:
            changes['price'] = parse_price(body['price'])
        except ValueError as exc:
            return JsonResponse({'error': str(exc)}, status=400)

    if not changes:
        return JsonResponse({'error': 'No changes provided'}, status=400)

    from apps.posting.services.offer_editor import edit_offer
    result = edit_offer(pool_offer.listing, changes)

    return JsonResponse({
        'ok': result.ok,
        'error': result.error,
        'pool_offer': _pool_offer_to_dict(pool_offer),
    }, status=200 if result.ok else 502)


# ── Activity Log ─────────────────────────────────────────────────


@login_required
@require_GET
def pool_activity(request, pool_id):
    """Return activity log for a pool: dispatch attempts + sale events."""
    try:
        pool = OfferPool.objects.get(pk=pool_id)
    except OfferPool.DoesNotExist:
        return JsonResponse({'error': 'Pool not found'}, status=404)

    limit = min(int(request.GET.get('limit', 50)), 200)

    attempts = list(
        PoolDispatchAttempt.objects
        .filter(pool_offer__pool=pool)
        .select_related('pool_offer__listing', 'item__owned_product')
        .order_by('-created_at')[:limit]
    )

    sale_events = list(
        PoolSaleEvent.objects
        .filter(pool_offer__pool=pool)
        .select_related('pool_offer__listing')
        .order_by('-created_at')[:20]
    )

    def _fmt_attempt(a):
        return {
            'type': 'dispatch',
            'id': a.pk,
            'operation': a.operation,
            'status': a.status,
            'pool_offer_id': a.pool_offer_id,
            'listing_id': a.pool_offer.listing_id if a.pool_offer_id else None,
            'item_login': (
                a.item.owned_product.login
                if a.item_id and a.item.owned_product_id
                else None
            ),
            'error_code': a.error_code,
            'error_message': a.error_message,
            'started_at': a.started_at.isoformat() if a.started_at else None,
            'finished_at': a.finished_at.isoformat() if a.finished_at else None,
            'created_at': a.created_at.isoformat(),
        }

    def _fmt_sale(s):
        return {
            'type': 'sale',
            'id': s.pk,
            'event_key': s.event_key,
            'pool_offer_id': s.pool_offer_id,
            'listing_id': s.listing_id,
            'order_id': s.order_id,
            'outcome': s.outcome,
            'processed_at': s.processed_at.isoformat() if s.processed_at else None,
            'created_at': s.created_at.isoformat(),
        }

    events = sorted(
        [_fmt_attempt(a) for a in attempts] + [_fmt_sale(s) for s in sale_events],
        key=lambda e: e['created_at'],
        reverse=True,
    )[:limit]

    return JsonResponse({'events': events, 'pool_id': pool_id})


# ── Sweep Settings ───────────────────────────────────────────────


@login_required
@require_GET
def sweep_settings(request):
    """Get current pool sweep settings."""
    from apps.sync.services.shared.feature_flags import SyncFlag, get_sync_setting, is_sync_feature_enabled

    return JsonResponse({
        'enabled': is_sync_feature_enabled(SyncFlag.POOL_SWEEP),
        'interval_minutes': get_sync_setting(SyncFlag.POOL_SWEEP, 'interval_minutes', default=30),
    })


@login_required
@require_POST
def update_sweep_settings(request):
    """Update pool sweep interval and enabled state."""
    from apps.sync.models import SyncFeatureFlag
    from apps.sync.services.shared.feature_flags import SyncFlag

    try:
        body = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({'error': 'Invalid JSON'}, status=400)

    flag, _ = SyncFeatureFlag.objects.get_or_create(
        key=SyncFlag.POOL_SWEEP,
        defaults={'description': 'Offer pool auto-restock sweep'},
    )

    if 'enabled' in body:
        flag.is_enabled = bool(body['enabled'])

    if 'interval_minutes' in body:
        interval = int(body['interval_minutes'])
        if interval < 1:
            return JsonResponse({'error': 'interval_minutes must be >= 1'}, status=400)
        value = flag.value or {}
        value['interval_minutes'] = interval
        flag.value = value

    flag.save()

    return JsonResponse({
        'enabled': flag.is_enabled,
        'interval_minutes': (flag.value or {}).get('interval_minutes', 30),
    })


# ── Available Accounts for Pool ──────────────────────────────────


@login_required
@require_GET
def available_accounts(request):
    """List OwnedProducts available for pool assignment.

    Filters: game_id (required), q (search login), exclude_pool_id.
    """
    game_id = request.GET.get('game_id')
    if not game_id:
        return JsonResponse({'error': 'game_id is required'}, status=400)

    qs = OwnedProduct.objects.filter(
        game_id=game_id,
    ).order_by('-created_at')

    # Exclude items already in a specific pool
    exclude_pool = request.GET.get('exclude_pool_id')
    if exclude_pool:
        existing_ids = OfferPoolItem.objects.filter(
            pool_id=exclude_pool,
        ).values_list('owned_product_id', flat=True)
        qs = qs.exclude(id__in=existing_ids)

    # Search
    q = request.GET.get('q', '').strip()
    if q:
        qs = qs.filter(login__icontains=q)

    # Pagination (simple offset/limit)
    limit = min(int(request.GET.get('limit', 50)), 200)
    offset = int(request.GET.get('offset', 0))
    total = qs.count()
    products = qs[offset:offset + limit]

    data = []
    for p in products:
        data.append({
            'id': p.id,
            'login': p.login,
            'email': p.email or '',
            'status': p.status,
            'price': str(p.price) if p.price else None,
            'created_at': p.created_at.isoformat(),
        })

    return JsonResponse({'accounts': data, 'total': total})


# ── Available Listings for Pool ──────────────────────────────────


@login_required
@require_GET
def available_listings(request):
    """List active listings that can have a pool created.

    Filters: game_id, store_id, q (search title/offer_id).
    Returns only listings without an existing pool.
    """
    qs = (
        Listing.objects
        .filter(
            status='listed',
            is_instant=True,
            integration_account__provider__in=['eldorado', 'gameboost', 'playerauctions'],
            integration_account__is_active=True,
            integration_account__credential__is_active=True,
        )
        .select_related('integration_account', 'game')
        .filter(pool_offer__isnull=True, pool_active_offers__isnull=True)
        .distinct()
        .order_by('-created_at')
    )

    game_id = request.GET.get('game_id')
    if game_id:
        qs = qs.filter(game_id=game_id)

    pool_id = request.GET.get('pool_id')
    if pool_id:
        try:
            target_pool = OfferPool.objects.select_related('variant').get(pk=pool_id)
        except OfferPool.DoesNotExist:
            return JsonResponse({'error': 'Pool not found'}, status=404)
        qs = qs.filter(game_id=target_pool.game_id)
        if target_pool.variant_id:
            qs = qs.filter(variant__icontains=target_pool.variant.slug)

    store_id = request.GET.get('store_id')
    if store_id:
        qs = qs.filter(integration_account_id=store_id)

    q = request.GET.get('q', '').strip()
    if q:
        from django.db.models import Q
        qs = qs.filter(Q(title__icontains=q) | Q(store_listing_id__icontains=q))

    limit = min(int(request.GET.get('limit', 50)), 200)
    offset = int(request.GET.get('offset', 0))
    total = qs.count()
    listings = qs[offset:offset + limit]

    data = []
    from apps.posting.services.pool.spec_resolver import resolve_game_variant
    for lst in listings:
        resolved_variant = (
            resolve_game_variant(lst.game, lst.variant)
            if lst.game_id and lst.variant
            else None
        )
        data.append({
            'id': lst.id,
            'title': lst.title or lst.store_listing_id,
            'store_listing_id': lst.store_listing_id,
            'store': lst.integration_account.name if lst.integration_account else '',
            'marketplace': lst.integration_account.provider if lst.integration_account else '',
            'game': lst.game.name if lst.game else '',
            'game_id': lst.game_id,
            'price': str(lst.price),
            'variant': lst.variant,
            'variant_id': resolved_variant.pk if resolved_variant else None,
            'created_at': lst.created_at.isoformat(),
        })

    return JsonResponse({'listings': data, 'total': total})


# ── Dispatch endpoints ────────────────────────────────────────────


@login_required
@require_GET
def dispatch_prefill(request, pool_id):
    """Return pre-fill data for the Create Offer drawer.

    GET /api/pools/{id}/dispatch-prefill/
    GET /api/pools/{id}/dispatch-prefill/?store_id=123
    """
    try:
        pool = OfferPool.objects.select_related('game').get(pk=pool_id)
    except OfferPool.DoesNotExist:
        return JsonResponse({'error': 'Pool not found'}, status=404)

    store_id = request.GET.get('store_id')
    store = None
    if store_id:
        try:
            store = IntegrationAccount.objects.get(
                pk=store_id,
                is_active=True,
                provider__in=['eldorado', 'gameboost', 'playerauctions'],
            )
        except IntegrationAccount.DoesNotExist:
            return JsonResponse({'error': 'Store not found'}, status=404)

    # --- Pending count (unreserved) ---
    from apps.posting.models import PoolDispatchReservation
    pending_count = pool.items.filter(
        status=OfferPoolItemStatus.PENDING,
        pool_offer__isnull=True,
        reservation__isnull=True,
    ).count()

    # --- Game info ---
    game = pool.game
    game_slug = game.slug or ''
    is_gta = game_slug.lower().startswith('gta') or game_slug.lower().startswith('grand-theft-auto')

    # --- Listing prefill from most recent active PoolOffer ---
    title = ''
    description = ''
    listing_price = None

    active_offer = (
        pool.pool_offers
        .filter(status=PoolOfferStatus.ACTIVE)
        .select_related('listing')
        .order_by('-created_at')
        .first()
    )
    if active_offer and active_offer.listing:
        from apps.posting.services.shared.utils import (
            extract_title_from_payload,
            extract_title_from_response,
            extract_price_from_response,
        )
        lst = active_offer.listing
        title = lst.title or ''
        listing_price = str(lst.price) if lst.price is not None else None
        # Try to get description from raw_data
        raw = lst.raw_data or {}
        description = (
            raw.get('description')
            or (raw.get('payload') or {}).get('description')
            or (raw.get('payload') or {}).get('offer_description')
            or ''
        )

    # --- Item prefill from first unreserved PENDING item ---
    purchased_price = None
    batch_data: dict = {}
    platform = ''

    first_item = (
        pool.items.filter(
            status=OfferPoolItemStatus.PENDING,
            pool_offer__isnull=True,
            reservation__isnull=True,
        )
        .select_related('owned_product')
        .order_by('order', 'created_at')
        .first()
    )
    if first_item and first_item.owned_product:
        op = first_item.owned_product
        raw = op.raw_data or {}
        purchased_price = (
            str(op.price)
            if op.price is not None
            else str(raw.get('price') or raw.get('purchased_price') or '')
        ) or None
        platform = raw.get('main_platform') or raw.get('platform') or ''

        # Extract manual_fields / offer_details / batch_data from raw
        manual_fields = raw.get('manual_fields') or {}
        offer_details = raw.get('offer_details') or {}
        batch_data_raw = raw.get('batch_data') or {}
        batch_data = {
            'manual_fields': manual_fields,
            'offer_details': offer_details,
            **{k: v for k, v in batch_data_raw.items() if k != 'manual_fields'},
        }
        # GTA-style top-level fields
        for gta_field in ('cash_amount', 'cash_unit', 'level', 'cars_count', 'tags'):
            if gta_field in raw:
                batch_data[gta_field] = raw[gta_field]

    # --- Pool config from most recent active PoolOffer ---
    target_count = 5
    threshold = 2
    max_concurrent = None
    if active_offer:
        target_count = active_offer.target_count
        threshold = active_offer.threshold
        max_concurrent = active_offer.max_concurrent

    # --- Store settings from PostingDefault ---
    # Create Offer uses a direct final sale price. Multipliers are intentionally
    # hidden and neutralized server-side; only provider-specific settings remain.
    store_settings: dict = {}
    if store and store.provider == 'playerauctions':
        try:
            default = PostingDefault.objects.get(game=game, marketplace=store.provider)
            store_settings['pa_mode'] = getattr(default, 'pa_mode', 'bulk') or 'bulk'
        except PostingDefault.DoesNotExist:
            store_settings['pa_mode'] = 'bulk'

    # --- Supported stores ---
    supported_providers = ['eldorado', 'gameboost', 'playerauctions']
    supported_stores_qs = IntegrationAccount.objects.filter(
        is_active=True,
        provider__in=supported_providers,
        role__in=['sell', 'both'],
    ).select_related('credential').filter(credential__is_active=True)

    supported_stores = [
        {
            'id': s.id,
            'name': s.name,
            'provider': s.provider,
            'slug': s.slug,
        }
        for s in supported_stores_qs
    ]

    return JsonResponse({
        'pending_count': pending_count,
        'game_id': game.id,
        'game_slug': game_slug,
        'is_gta': is_gta,
        'platform': platform,
        'title': title,
        'description': description,
        'listing_price': listing_price,
        'purchased_price': purchased_price,
        'batch_data': batch_data,
        'store_settings': store_settings,
        'pool_config': {
            'target_count': target_count,
            'threshold': threshold,
            'max_concurrent': max_concurrent,
        },
        'supported_stores': supported_stores,
    })


@login_required
@require_POST
def dispatch_offer(request, pool_id):
    """Create a new offer from pool items.

    POST /api/pools/{id}/dispatch-offer/
    """
    try:
        pool = OfferPool.objects.select_related('game').get(
            pk=pool_id,
            status=OfferPoolStatus.ACTIVE,
        )
    except OfferPool.DoesNotExist:
        return JsonResponse({'error': 'Pool not found or not active'}, status=404)

    try:
        body = json.loads(request.body)
    except (ValueError, TypeError):
        return JsonResponse({'error': 'Invalid JSON'}, status=400)

    # --- Validate store ---
    store_id = body.get('store_id')
    if not store_id:
        return JsonResponse({'error': 'store_id is required'}, status=400)
    try:
        store = IntegrationAccount.objects.select_related('credential').get(
            pk=store_id,
            is_active=True,
            role__in=['sell', 'both'],
        )
    except IntegrationAccount.DoesNotExist:
        return JsonResponse({'error': 'Store not found or not eligible'}, status=400)

    # Validate provider supported
    try:
        PoolOffer.strategy_for_provider(store.provider)
    except ValidationError as e:
        return JsonResponse({'error': str(e)}, status=400)

    # --- Validate counts ---
    try:
        count = int(body.get('count', 0))
        target_count = int(body.get('target_count', 5))
        threshold = int(body.get('threshold', 2))
    except (TypeError, ValueError):
        return JsonResponse({'error': 'count, target_count, threshold must be integers'}, status=400)

    if count < 1:
        return JsonResponse({'error': 'count must be at least 1'}, status=400)

    unreserved_pending = pool.items.filter(
        status=OfferPoolItemStatus.PENDING,
        pool_offer__isnull=True,
        reservation__isnull=True,
    ).count()
    if count > unreserved_pending:
        return JsonResponse({
            'error': f'Not enough pending items: requested {count}, available {unreserved_pending}',
        }, status=400)

    if target_count < 1:
        return JsonResponse({'error': 'target_count must be at least 1'}, status=400)
    if threshold < 1 or threshold > target_count:
        return JsonResponse({'error': 'threshold must be between 1 and target_count'}, status=400)

    # --- Validate max_concurrent (PA/clone only) ---
    strategy = PoolOffer.strategy_for_provider(store.provider)
    max_concurrent = body.get('max_concurrent')
    if strategy == PoolOfferStrategy.CLONE:
        try:
            max_concurrent = int(max_concurrent)
        except (TypeError, ValueError):
            return JsonResponse({'error': 'max_concurrent is required for PA/clone'}, status=400)
        if not (target_count <= max_concurrent <= 10):
            return JsonResponse({
                'error': f'max_concurrent must satisfy target_count ({target_count}) <= max_concurrent <= 10',
            }, status=400)
    else:
        if max_concurrent is not None:
            return JsonResponse({'error': 'max_concurrent must not be set for append providers'}, status=400)

    # --- Validate direct sale price ---
    try:
        sale_price = float(body.get('sale_price') or 0)
    except (TypeError, ValueError):
        sale_price = 0.0
    if sale_price <= 0:
        return JsonResponse({'error': 'sale_price must be greater than 0'}, status=400)

    # Keep the established posting pipeline shape while making the final price
    # explicit: base price equals sale price and all multipliers are neutral.
    batch_data = dict(body.get('batch_data') or {})
    batch_data['price'] = sale_price
    batch_data['sales_price'] = sale_price
    batch_data['purchased_price'] = sale_price

    store_settings = dict(body.get('store_settings') or {})
    store_settings.update({
        'multiplier_low': '1.00',
        'multiplier_mid': '1.00',
        'multiplier_high': '1.00',
    })

    # Pool-created offers must use a pre-fed image; automatic media generation
    # is deliberately not available in this workflow.
    if body.get('selected_image_preset_id') in (None, '', 'auto'):
        return JsonResponse({'error': 'Please select or upload a listing image'}, status=400)
    from apps.posting.api.media_override import (
        mark_image_override_used,
        resolve_image_override_settings,
    )
    media_settings, media_error = resolve_image_override_settings(body, pool.game)
    if media_error:
        return media_error

    # --- Dispatch ---
    from apps.posting.services.pool.dispatcher import dispatch_offer_from_pool

    try:
        job = dispatch_offer_from_pool(
            pool=pool,
            store=store,
            count=count,
            target_count=target_count,
            threshold=threshold,
            max_concurrent=max_concurrent,
            batch_data=batch_data,
            store_settings=store_settings,
            media_settings=media_settings,
        )
        mark_image_override_used(job.settings)
    except ValueError as e:
        return JsonResponse({'error': str(e)}, status=400)
    except Exception as e:
        logger.exception('dispatch_offer_from_pool failed (pool=%d): %s', pool_id, e)
        return JsonResponse({'error': 'Dispatch failed unexpectedly'}, status=500)

    reservation = getattr(job, 'pool_dispatch_reservation', None)
    return JsonResponse({
        'job_id': job.pk,
        'reservation_id': reservation.pk if reservation else None,
        'reservation_token': str(reservation.token) if reservation else None,
        'total_count': job.total_count,
    }, status=201)


# ── Serializers ──────────────────────────────────────────────────


_POOL_DELETE_BLOCKING_ITEM_STATUSES = (
    OfferPoolItemStatus.RESERVED,
    OfferPoolItemStatus.QUEUED,
    OfferPoolItemStatus.PUSHED,
    OfferPoolItemStatus.FAILED,
)
_POOL_DELETE_BLOCKING_ATTEMPT_STATUSES = (
    PoolDispatchStatus.PENDING,
    PoolDispatchStatus.IN_PROGRESS,
    PoolDispatchStatus.UNKNOWN,
)


def _pool_delete_blockers(pool: OfferPool) -> list[str]:
    """Return active remote/in-progress conditions that make deletion unsafe."""
    checks = (
        (
            'active_pool_items',
            '_has_blocking_items',
            lambda: pool.items.filter(
                status__in=_POOL_DELETE_BLOCKING_ITEM_STATUSES,
            ).exists(),
        ),
        (
            'active_linked_offers',
            '_has_blocking_pool_offers',
            lambda: pool.pool_offers.exclude(
                status=PoolOfferStatus.DETACHED,
            ).exists(),
        ),
        (
            'active_remote_offers',
            '_has_blocking_active_offers',
            lambda: pool.active_offers.filter(
                status=OfferPoolActiveOfferStatus.ACTIVE,
            ).exists(),
        ),
        (
            'active_dispatch_reservations',
            '_has_blocking_reservations',
            lambda: pool.dispatch_reservations.filter(
                status=PoolDispatchReservationStatus.ACTIVE,
            ).exists(),
        ),
        (
            'in_progress_dispatch_attempts',
            '_has_blocking_attempts',
            lambda: PoolDispatchAttempt.objects.filter(
                pool_offer__pool=pool,
                status__in=_POOL_DELETE_BLOCKING_ATTEMPT_STATUSES,
            ).exists(),
        ),
    )
    blockers = []
    for label, annotation, query in checks:
        blocked = getattr(pool, annotation, None)
        if blocked is None:
            blocked = query()
        if blocked:
            blockers.append(label)
    return blockers


def _pool_to_dict(pool: OfferPool) -> dict:
    pending = getattr(pool, '_items_pending', None)
    queued = getattr(pool, '_items_queued', None)
    pushed = getattr(pool, '_items_pushed', None)
    failed = getattr(pool, '_items_failed', None)
    consumed = getattr(pool, '_items_consumed', None)
    if pending is None:
        counts = dict(
            pool.items.values_list('status').annotate(total=Count('id'))
        )
        pending = counts.get(OfferPoolItemStatus.PENDING, 0)
        queued = counts.get(OfferPoolItemStatus.QUEUED, 0)
        pushed = counts.get(OfferPoolItemStatus.PUSHED, 0)
        failed = counts.get(OfferPoolItemStatus.FAILED, 0)
        consumed = counts.get(OfferPoolItemStatus.CONSUMED, 0)

    delete_blockers = _pool_delete_blockers(pool)

    linked_offers = [
        offer for offer in pool.pool_offers.all()
        if offer.status != PoolOfferStatus.DETACHED
    ]
    linked_offers.sort(key=lambda offer: (offer.created_at, offer.pk))
    first_offer = linked_offers[0] if linked_offers else None
    listing = first_offer.listing if first_offer else None
    store = first_offer.store if first_offer else None

    # All stores/marketplaces this common pool serves (one PoolOffer per store).
    # The single-value ``store``/``marketplace`` fields below are kept for
    # backward compatibility, but a pool can span multiple stores so the UI
    # should render this list instead of just the first offer.
    stores = []
    _seen_store_ids: set[int] = set()
    for offer in linked_offers:
        offer_store = offer.store
        if not offer_store or offer_store.pk in _seen_store_ids:
            continue
        _seen_store_ids.add(offer_store.pk)
        stores.append({
            'id': offer_store.pk,
            'name': offer_store.name,
            'marketplace': offer_store.provider,
            'strategy': offer.strategy,
            'threshold': offer.threshold,
            'target_count': offer.target_count,
            'current_remote_count': offer.current_remote_count,
            'listing_id': offer.listing.pk if offer.listing else None,
            'offer_id': offer.listing.store_listing_id if offer.listing else '',
        })
    marketplaces = sorted({s['marketplace'] for s in stores if s['marketplace']})
    if pool.status == OfferPoolStatus.ARCHIVED:
        health = 'archived'
    elif pool.status == OfferPoolStatus.PAUSED:
        health = 'paused'
    elif not linked_offers:
        health = 'no_offers'
    elif any(offer.status == PoolOfferStatus.ERROR for offer in linked_offers):
        health = 'attention_required'
    else:
        health = 'depleted' if pending == 0 else 'healthy'

    return {
        'id': pool.id,
        'name': pool.name or f'Pool #{pool.pk}',
        'health': health,
        'variant_id': pool.variant_id,
        'variant': pool.variant.slug if pool.variant_id else '',
        'credential_spec_id': pool.credential_spec_id,
        'linked_offer_count': len(linked_offers),
        'can_hard_delete': not delete_blockers,
        'delete_blockers': delete_blockers,
        # Compatibility fields for the existing UI during cutover.
        'listing_id': listing.pk if listing else None,
        'listing_title': (listing.title or listing.store_listing_id) if listing else '',
        'offer_id': listing.store_listing_id if listing else '',
        'game': pool.game.name if pool.game else '',
        'game_id': pool.game_id,
        'store': store.name if store else '',
        'store_id': store.pk if store else None,
        'marketplace': store.provider if store else '',
        # Full set of stores/marketplaces served by this common pool.
        'stores': stores,
        'marketplaces': marketplaces,
        'strategy': first_offer.strategy if first_offer else '',
        'status': pool.status,
        'threshold': first_offer.threshold if first_offer else None,
        'target_count': first_offer.target_count if first_offer else None,
        'max_concurrent': first_offer.max_concurrent if first_offer else None,
        'current_remote_count': first_offer.current_remote_count if first_offer else None,
        'last_checked_at': first_offer.last_checked_at.isoformat() if first_offer and first_offer.last_checked_at else None,
        'last_replenished_at': first_offer.last_replenished_at.isoformat() if first_offer and first_offer.last_replenished_at else None,
        'items_pending': pending,
        'items_queued': queued,
        'items_pushed': pushed,
        'items_failed': failed,
        'items_consumed': consumed,
        'items_total': pending + queued + pushed + failed + consumed,
        'created_at': pool.created_at.isoformat(),
    }


def _item_to_dict(item: OfferPoolItem) -> dict:
    return {
        'id': item.id,
        'owned_product_id': item.owned_product_id,
        'login': item.owned_product.login if item.owned_product else '',
        'email': item.owned_product.email if item.owned_product else '',
        'status': item.status,
        'pool_offer_id': item.pool_offer_id,
        'order': item.order,
        'pushed_at': item.pushed_at.isoformat() if item.pushed_at else None,
        'target_offer_id': item.target_offer_id,
        'remote_credential_id': item.remote_credential_id,
        'remote_state': item.remote_state,
        'failure_stage': item.failure_stage,
        'error_message': item.error_message,
    }


def _active_offer_to_dict(ao: OfferPoolActiveOffer) -> dict:
    return {
        'id': ao.id,
        'store_listing_id': ao.store_listing_id,
        'status': ao.status,
        'pool_offer_id': ao.pool_offer_id,
        'pool_item_login': ao.pool_item.owned_product.login if ao.pool_item and ao.pool_item.owned_product else '',
        'created_at': ao.created_at.isoformat(),
    }


def _pool_offer_to_dict(pool_offer: PoolOffer) -> dict:
    listing = pool_offer.listing
    store = pool_offer.store
    return {
        'id': pool_offer.pk,
        'pool_id': pool_offer.pool_id,
        'listing_id': listing.pk,
        'listing_title': listing.title or listing.store_listing_id,
        'offer_id': listing.store_listing_id,
        'store_id': store.pk if store else None,
        'store': store.name if store else '',
        'marketplace': store.provider if store else '',
        'strategy': pool_offer.strategy,
        'status': pool_offer.status,
        'target_count': pool_offer.target_count,
        'threshold': pool_offer.threshold,
        'max_concurrent': pool_offer.max_concurrent,
        'current_remote_count': pool_offer.current_remote_count,
        'last_checked_at': pool_offer.last_checked_at.isoformat() if pool_offer.last_checked_at else None,
        'last_replenished_at': pool_offer.last_replenished_at.isoformat() if pool_offer.last_replenished_at else None,
        'last_error': pool_offer.last_error,
    }


# ── Internal helpers ─────────────────────────────────────────────


# Legacy platform-specific credential key mappings (GTA fallback)
_PLATFORM_CREDENTIAL_MAP: dict[str, tuple[str, str, tuple[str, ...]]] = {
    'PlayStation 4':   ('psn_id',   'psn_pass',   ('psn_id', 'psn_pass', 'dob')),
    'PlayStation 5':   ('psn_id',   'psn_pass',   ('psn_id', 'psn_pass', 'dob')),
    'Xbox One':        ('xbox_id',  'xbox_pass',  ('xbox_id', 'xbox_pass')),
    'Xbox Series X/S': ('xbox_id',  'xbox_pass',  ('xbox_id', 'xbox_pass')),
    'PC - Legacy':     ('steam_id', 'steam_pass', ('steam_id', 'steam_pass', 'rock_id', 'rock_pass')),
    'PC - Enhanced':   ('steam_id', 'steam_pass', ('steam_id', 'steam_pass', 'rock_id', 'rock_pass')),
}


def _validate_pool_candidate(
    owned: OwnedProduct,
    pool: OfferPool,
) -> dict:
    """Check if an OwnedProduct can be added to a pool.

    Returns:
        {block: bool, block_reason, block_detail,
         warnings: [{reason, detail, needs_confirm}]}
    """
    result: dict = {
        'block': False, 'block_reason': '', 'block_detail': '',
        'warnings': [],
    }

    # Global exclusivity: one credential has one durable pool item for life.
    existing_item = (
        OfferPoolItem.objects.filter(owned_product=owned)
        .select_related('pool')
        .first()
    )
    if existing_item:
        result['block'] = True
        result['block_reason'] = (
            'already_in_pool'
            if existing_item.pool_id == pool.pk
            else 'in_another_pool'
        )
        result['block_detail'] = (
            f'Already managed by {existing_item.pool.name or f"Pool #{existing_item.pool_id}"}'
        )
        return result

    if owned.game_id and owned.game_id != pool.game_id:
        result['block'] = True
        result['block_reason'] = 'game_mismatch'
        result['block_detail'] = 'Credential game does not match pool game'
        return result

    # Sold (has active sold order, not cancelled/refunded) → needs confirmation
    _SOLD_STATUSES = (OrderStatus.PENDING, OrderStatus.DELIVERED, OrderStatus.COMPLETED)
    sold_order = owned.orders.filter(status__in=_SOLD_STATUSES).first()
    if sold_order:
        sold_date = sold_order.created_at.strftime('%Y-%m-%d') if sold_order.created_at else '?'
        result['warnings'].append({
            'reason': 'sold',
            'detail': f'Sold on {sold_date}, not refunded/cancelled',
            'needs_confirm': True,
        })

    return result


def _process_warnings(
    check: dict,
    login: str,
    force: bool,
    result: dict,
) -> bool:
    """Process validation warnings. Returns True if item should be added, False to skip.

    Adds entries to result['warnings'] and result['needs_confirmation'] as needed.
    """
    warnings = check.get('warnings', [])
    if not warnings:
        return True

    needs_confirm = any(w['needs_confirm'] for w in warnings)

    for w in warnings:
        result['warnings'].append({
            'login': login,
            'reason': w['reason'],
            'detail': w['detail'],
        })

    if needs_confirm and not force:
        result['needs_confirmation'].append(login)
        return False

    return True


def _get_or_create_owned_product(
    game: Game,
    login: str,
    password: str,
    *,
    ref_price=None,
    extra_fields: dict | None = None,
    raw_data: dict | None = None,
) -> tuple[OwnedProduct, bool]:
    """Get or create an OwnedProduct. On update, only touch credential fields — never status.

    Returns (owned_product, created).
    """
    try:
        owned = OwnedProduct.objects.get(category=game.category, login=login)
        # Existing product: update only credential fields, PRESERVE status/price
        owned.password = password
        owned.password_hash = hashlib.sha256(password.encode()).hexdigest()
        owned.game = game
        update_fields = ['password', 'password_hash', 'game', 'updated_at']

        if extra_fields:
            for field, value in extra_fields.items():
                setattr(owned, field, value)
                update_fields.append(field)

        if raw_data is not None:
            owned.raw_data = raw_data
            update_fields.append('raw_data')

        owned.save(update_fields=update_fields)
        return owned, False

    except OwnedProduct.DoesNotExist:
        create_kwargs = {
            'category': game.category,
            'login': login,
            'password': password,
            'password_hash': hashlib.sha256(password.encode()).hexdigest(),
            'game': game,
            'status': 'draft',
            'price': ref_price,
            'raw_data': raw_data or {},
        }
        if extra_fields:
            create_kwargs.update(extra_fields)
        owned = OwnedProduct.objects.create(**create_kwargs)
        return owned, True


def _skip_missing_login_password(cred: dict, login: str, result: dict) -> None:
    """Record a credential row that has no usable login/password.

    Prevents silent drops: previously such rows were skipped without any
    feedback, so the UI reported nothing was added and gave no reason.
    """
    shown_login = login or str(
        cred.get('login')
        or cred.get('psn_id')
        or cred.get('xbox_id')
        or cred.get('steam_id')
        or ''
    ).strip()
    result['skipped'].append({
        'login': shown_login or '(unknown)',
        'reason': 'missing_login_password',
        'detail': 'Row has no login/password value the pool credential format recognizes',
    })


def _add_credentials_to_pool(
    pool: OfferPool,
    credentials: list[dict],
    game: Game,
    listing: Listing | None = None,
    *,
    force: bool = False,
    result: dict | None = None,
) -> int:
    """Create OwnedProducts from raw credentials and add as OfferPoolItems.

    Spec-driven: uses CredentialSpec field roles to map incoming keys to
    OwnedProduct fixed columns. Falls back to legacy _PLATFORM_CREDENTIAL_MAP
    if no spec is resolved.

    Args:
        force: If True, skip warnings (sold accounts) and add anyway.
        result: Mutable dict to collect skipped/warnings/needs_confirmation.
    """
    from apps.posting.services.pool.spec_resolver import (
        build_field_role_map,
        build_reverse_role_map,
        resolve_spec,
    )
    from apps.posting.services.pool.presets import ROLE_TO_OWNED_PRODUCT_FIELD

    if result is None:
        result = {'added': 0, 'skipped': [], 'warnings': [], 'needs_confirmation': []}

    max_order = pool.items.count()
    platform = (
        (pool.variant.label or pool.variant.slug)
        if pool.variant_id
        else ((listing.variant or '') if listing else '')
    )

    # Get reference price from listing's existing owned products
    ref_price = None
    if listing:
        ref_lop = (
            ListingOwnedProduct.objects
            .filter(listing=listing, owned_product__price__isnull=False)
            .select_related('owned_product')
            .first()
        )
        if ref_lop:
            ref_price = ref_lop.owned_product.price

    # Try spec-driven ingestion (DB spec or code-level preset)
    spec = resolve_spec(pool)

    # If no DB spec, try code-level preset as structured fallback
    spec_fields = None
    spec_id = None
    if spec:
        spec_fields = spec.fields
        spec_id = spec.id
    else:
        from apps.posting.services.pool.spec_resolver import resolve_game_variant
        from apps.posting.services.pool.presets import get_preset
        game_slug = game.slug if game else ''
        variant_obj = resolve_game_variant(game, platform) if platform and game else None
        variant_slug = variant_obj.slug if variant_obj else None
        preset = get_preset(game_slug, variant_slug)
        if preset:
            spec_fields = preset[1]  # fields list

    if spec_fields:
        role_map = build_field_role_map(spec_fields)
        reverse_map = build_reverse_role_map(spec_fields)
        login_key = role_map.get('login', 'login')
        password_key = role_map.get('password', 'password')

        for i, cred in enumerate(credentials):
            # Accept the spec/preset key, but fall back to the generic
            # 'login'/'password' keys the paste UI sends when its resolved
            # spec differs from the pool's (otherwise rows are silently lost).
            login = str(cred.get(login_key) or cred.get('login') or '').strip().lower()
            password = str(cred.get(password_key) or cred.get('password') or '').strip()

            if not login or not password:
                _skip_missing_login_password(cred, login, result)
                continue

            raw_data = {
                'source': 'manual',
                'main_platform': platform,
                'credential_spec_id': spec_id,
                'credential_values': cred,
                'loginData': {'login': login, 'password': password},
                'item_id': f'manual-{uuid.uuid4().hex[:12]}',
            }

            extra_fields: dict = {}
            for field_key, role in reverse_map.items():
                # login/password are resolved above (with generic fallback) and
                # passed directly; don't let an empty spec-key value blank them.
                if role in ('login', 'password'):
                    continue
                value = str(cred.get(field_key, '')).strip()
                owned_field = ROLE_TO_OWNED_PRODUCT_FIELD.get(role)
                if owned_field:
                    extra_fields[owned_field] = value
                elif role == 'extra' and value:
                    raw_data[field_key] = value

            owned, _ = _get_or_create_owned_product(
                game, login, password,
                ref_price=ref_price,
                extra_fields=extra_fields,
                raw_data=raw_data,
            )

            # Validate before adding to pool
            check = _validate_pool_candidate(owned, pool)
            if check['block']:
                result['skipped'].append({
                    'login': login,
                    'reason': check['block_reason'],
                    'detail': check['block_detail'],
                })
                continue
            if not _process_warnings(check, login, force, result):
                continue

            _, created = OfferPoolItem.objects.get_or_create(
                pool=pool,
                owned_product=owned,
                defaults={'order': max_order + i},
            )
            if created:
                result['added'] += 1

        return result['added']

    # Legacy fallback: no spec and no preset found, use platform credential map
    mapping = _PLATFORM_CREDENTIAL_MAP.get(platform)

    for i, cred in enumerate(credentials):
        if mapping:
            login_key, pass_key, extra_keys = mapping
            login = (cred.get(login_key) or cred.get('login') or '').strip().lower()
            password = (cred.get(pass_key) or cred.get('password') or '').strip()
            credential_extras = {}
            for k in extra_keys:
                val = cred.get(k, '').strip()
                if val:
                    credential_extras[k] = val
        else:
            login = cred.get('login', '').strip().lower()
            password = cred.get('password', '').strip()
            credential_extras = {}

        if not login or not password:
            _skip_missing_login_password(cred, login, result)
            continue

        raw_data = {
            'source': 'manual',
            'main_platform': platform,
            'loginData': {'login': login, 'password': password},
            'emailLoginData': {
                'login': cred.get('email', '').strip(),
                'password': cred.get('email_password', '').strip(),
            },
            'security_email': cred.get('security_email', '').strip(),
            'security_email_password': cred.get('security_email_password', '').strip(),
            'security_email_login_link': cred.get('security_email_login_link', '').strip(),
            'birthday': cred.get('birthday', cred.get('dob', '')).strip(),
            'emailLoginUrl': cred.get('email_login_link', '').strip(),
            'item_id': f'manual-{uuid.uuid4().hex[:12]}',
        }

        if credential_extras:
            raw_data.update(credential_extras)

        extra_fields = {
            'email': cred.get('email', '').strip(),
            'email_password': cred.get('email_password', '').strip(),
            'email_login_link': cred.get('email_login_link', '').strip(),
            'security_email': cred.get('security_email', '').strip(),
            'security_email_password': cred.get('security_email_password', '').strip(),
        }

        owned, _ = _get_or_create_owned_product(
            game, login, password,
            ref_price=ref_price,
            extra_fields=extra_fields,
            raw_data=raw_data,
        )

        # Validate before adding to pool
        check = _validate_pool_candidate(owned, pool)
        if check['block']:
            result['skipped'].append({
                'login': login,
                'reason': check['block_reason'],
                'detail': check['block_detail'],
            })
            continue
        if not _process_warnings(check, login, force, result):
            continue

        _, created = OfferPoolItem.objects.get_or_create(
            pool=pool,
            owned_product=owned,
            defaults={'order': max_order + i},
        )
        if created:
            result['added'] += 1

    return result['added']

# ── Edit pool item credentials ─────────────────────────────────────────────────
@login_required
@require_POST
def edit_pool_item(request, pool_id, item_id):
    """Edit credentials of a pool item (safety-gated to PENDING unless force=true)."""
    try:
        body = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({'error': 'Invalid JSON'}, status=400)
    try:
        item = OfferPoolItem.objects.select_related('owned_product').get(
            id=item_id, pool_id=pool_id
        )
    except OfferPoolItem.DoesNotExist:
        return JsonResponse({'error': 'Item not found'}, status=404)
    force = bool(body.get('force'))
    if item.status != OfferPoolItemStatus.PENDING and not force:
        return JsonResponse(
            {'error': f'item_{item.status}_use_force', 'status': item.status},
            status=409,
        )
    op = item.owned_product
    changed = False
    for field in ('login', 'password', 'email', 'email_password'):
        if field in body and body[field] is not None:
            setattr(op, field, str(body[field]).strip())
            changed = True
    if not changed:
        return JsonResponse({'error': 'No fields to update'}, status=400)
    try:
        op.full_clean()
        op.save()
    except ValidationError as exc:
        return JsonResponse({'error': str(exc)}, status=400)
    return JsonResponse({'ok': True})


# ── Set per-store allocation (target_count + threshold) ────────────────────────
@login_required
@require_POST
def set_store_allocation(request, pool_id):
    """Bulk-update target_count and threshold for each PoolOffer linked to a pool."""
    try:
        body = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({'error': 'Invalid JSON'}, status=400)
    allocations = body.get('allocations')
    if not isinstance(allocations, list) or not allocations:
        return JsonResponse({'error': 'allocations must be a non-empty list'}, status=400)
    try:
        with transaction.atomic():
            for a in allocations:
                listing_id = a.get('listing_id')
                target_count = a.get('target_count')
                threshold = a.get('threshold')
                if listing_id is None:
                    return JsonResponse({'error': 'listing_id required in each allocation'}, status=400)
                try:
                    po = PoolOffer.objects.select_for_update().get(
                        pool_id=pool_id, listing_id=listing_id
                    )
                except PoolOffer.DoesNotExist:
                    return JsonResponse(
                        {'error': f'PoolOffer for listing {listing_id} not found in pool {pool_id}'},
                        status=404,
                    )
                if target_count is not None:
                    po.target_count = int(target_count)
                if threshold is not None:
                    po.threshold = int(threshold)
                # Validate only the fields we are changing (not full model state)
                alloc_errors = {}
                if po.target_count < 1:
                    alloc_errors["target_count"] = "Target count must be >= 1."
                if po.threshold < 1:
                    alloc_errors["threshold"] = "Threshold must be >= 1."
                if po.threshold > po.target_count:
                    alloc_errors["threshold"] = (
                        f"Threshold ({po.threshold}) must be <= target_count ({po.target_count})."
                    )
                if alloc_errors:
                    raise ValidationError(alloc_errors)
                po.save(update_fields=["target_count", "threshold", "updated_at"])
    except ValidationError as exc:
        return JsonResponse({'error': str(exc)}, status=400)
    return JsonResponse({'ok': True})
