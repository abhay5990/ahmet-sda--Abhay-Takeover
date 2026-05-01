"""Stock posting API endpoints — job CRUD, SSE stream, defaults management."""

from __future__ import annotations

import json
import logging
import threading
import time
from datetime import datetime

from django.contrib.auth.decorators import login_required
from django.http import HttpRequest, JsonResponse, StreamingHttpResponse
from django.views.decorators.http import require_POST, require_GET

from apps.integrations.models import IntegrationAccount
from apps.inventory.models import Game
from apps.posting.models import (
    PostingDefault,
    PostingJob,
    PostingJobItem,
    PostingJobItemStatus,
    PostingJobStatus,
    PostingLog,
    PostingLogLevel,
)
from apps.posting.services.stock import StockOrchestrator

logger = logging.getLogger(__name__)

# Thread tracking — prevents duplicate launches, enables status queries.
_active_jobs: dict[int, threading.Thread] = {}
_jobs_lock = threading.Lock()


def _run_job(job_id: int) -> None:
    """Wrapper that runs orchestrator and cleans up thread tracking on exit."""
    try:
        StockOrchestrator().execute(job_id)
    finally:
        with _jobs_lock:
            _active_jobs.pop(job_id, None)


@login_required
@require_POST
def create_job(request):
    """Create a stock posting job.

    POST body (JSON):
        game_id: int
        logins: list[str]  — one login per line
        stores: list[int]  — IntegrationAccount IDs
        defaults: dict     — {store_slug: {multiplier_low, ..., sub_platform, account_type}}
        source_account_id: int|null — fallback account for resolving missing products
    """
    try:
        body = json.loads(request.body)
    except (json.JSONDecodeError, ValueError):
        return JsonResponse({'error': 'Invalid JSON'}, status=400)

    game_id = body.get('game_id')
    logins = body.get('logins', [])
    store_ids = body.get('stores', [])
    defaults_data = body.get('defaults', {})
    source_account_id = body.get('source_account_id')

    if not game_id or not logins or not store_ids:
        return JsonResponse({'error': 'game_id, logins, and stores are required'}, status=400)

    if not isinstance(logins, list):
        return JsonResponse({'error': 'logins must be a list'}, status=400)
    if not isinstance(store_ids, list):
        return JsonResponse({'error': 'stores must be a list'}, status=400)
    if not isinstance(defaults_data, dict):
        return JsonResponse({'error': 'defaults must be an object'}, status=400)

    try:
        game = Game.objects.get(id=game_id, is_active=True)
    except Game.DoesNotExist:
        return JsonResponse({'error': 'Game not found'}, status=404)

    stores = list(
        IntegrationAccount.objects.filter(
            id__in=store_ids, is_active=True, role__in=['sell', 'both'],
        )
    )
    if not stores:
        return JsonResponse({'error': 'No valid stores found'}, status=400)

    # Resolve source account for fallback (None = no fallback, user chose explicitly)
    source_account = None
    if source_account_id:
        source_account = IntegrationAccount.objects.filter(
            id=source_account_id, is_active=True,
        ).first()
        if not source_account:
            return JsonResponse({'error': 'Source account not found or inactive'}, status=404)

    # Clean login list
    clean_logins = []
    for login in logins:
        login = login.strip()
        if login:
            clean_logins.append(login)

    if not clean_logins:
        return JsonResponse({'error': 'No valid logins provided'}, status=400)

    # Quick DB lookup — pre-resolve OwnedProducts where possible
    from apps.inventory.models import OwnedProduct

    owned_map: dict[str, OwnedProduct | None] = {}
    if game.category_id:
        existing = OwnedProduct.objects.filter(
            category=game.category,
            login__in=[l.lower() for l in clean_logins],
        ).select_related('source_account')
        owned_map = {op.login: op for op in existing}

    # Build store-slug-keyed settings for this job.
    # Always write an entry per store (may be empty). Orchestrator falls back
    # to STOCK_PRICING_BASELINE for missing pricing fields; non-pricing fields
    # (sub_platform, account_type) are simply absent.
    job_settings = {}
    for store in stores:
        store_defaults = defaults_data.get(store.slug, defaults_data.get(store.provider, {}))
        job_settings[store.slug] = dict(store_defaults) if store_defaults else {}

    # Upsert PostingDefaults (UI pre-fill only — orchestrator won't read these)
    for store in stores:
        mp = store.provider
        store_defaults = defaults_data.get(store.slug, defaults_data.get(mp, {}))
        if store_defaults:
            PostingDefault.objects.update_or_create(
                game=game,
                marketplace=mp,
                defaults={
                    k: v for k, v in {
                        'multiplier_low': store_defaults.get('multiplier_low'),
                        'multiplier_mid': store_defaults.get('multiplier_mid'),
                        'multiplier_high': store_defaults.get('multiplier_high'),
                        'min_price': store_defaults.get('min_price'),
                        'forced_ending': store_defaults.get('forced_ending'),
                        'sub_platform': store_defaults.get('sub_platform'),
                        'account_type': store_defaults.get('account_type'),
                    }.items() if v is not None
                },
            )

    # Create PostingJob + items — ALL logins enter the job, no skipping
    total = len(clean_logins) * len(stores)
    job = PostingJob.objects.create(
        game=game,
        source_account=source_account,
        settings=job_settings,
        total_count=total,
    )

    items = []
    for login in clean_logins:
        normalized = login.lower().strip()
        owned = owned_map.get(normalized)
        for store in stores:
            items.append(PostingJobItem(
                job=job,
                login=normalized,
                owned_product=owned,
                store=store,
                marketplace=store.provider,
            ))
    PostingJobItem.objects.bulk_create(items)

    # Start orchestrator in background thread (with duplicate guard)
    with _jobs_lock:
        if job.id in _active_jobs:
            return JsonResponse({'error': 'Job already running'}, status=409)
        thread = threading.Thread(
            target=_run_job,
            args=(job.id,),
            daemon=True,
            name=f"posting-job-{job.id}",
        )
        _active_jobs[job.id] = thread
        thread.start()

    return JsonResponse({
        'job_id': job.id,
        'total_count': total,
    }, status=201)


@login_required
@require_GET
def job_status(request, job_id):
    """Get current job status with all items."""
    try:
        job = PostingJob.objects.select_related('game').get(id=job_id)
    except PostingJob.DoesNotExist:
        return JsonResponse({'error': 'Job not found'}, status=404)

    items = job.items.select_related('owned_product', 'store', 'listing').all()

    return JsonResponse({
        'id': job.id,
        'game': job.game.name,
        'status': job.status,
        'total_count': job.total_count,
        'success_count': job.success_count,
        'fail_count': job.fail_count,
        'created_at': job.created_at.isoformat(),
        'completed_at': job.completed_at.isoformat() if job.completed_at else None,
        'items': [
            {
                'id': item.id,
                'login': item.login,
                'store': f"{item.marketplace} — {item.store.name}",
                'status': item.status,
                'offer_id': item.listing.store_listing_id if item.listing else None,
                'offer_title': item.listing.title if item.listing else None,
                'error': item.error_message,
                'resolved': item.owned_product_id is not None,
            }
            for item in items
        ],
    })


@login_required
@require_GET
def job_stream(request: HttpRequest, job_id: int) -> StreamingHttpResponse:
    """SSE endpoint — streams PostingJob progress in realtime."""
    try:
        PostingJob.objects.get(id=job_id)
    except PostingJob.DoesNotExist:
        return JsonResponse({'error': 'Job not found'}, status=404)

    MAX_DURATION = 600          # 10 minute hard limit
    HEARTBEAT_INTERVAL = 20     # prevent proxy timeout on idle connection
    POLL_INTERVAL = 2           # reduce DB load (1→2s)

    def event_generator():
        last_updated: dict[int, datetime] = {}
        start_time = time.monotonic()
        last_heartbeat = start_time

        while True:
            now = time.monotonic()

            # Hard timeout — prevent infinite loop
            if now - start_time > MAX_DURATION:
                yield f"data: {json.dumps({'type': 'timeout'})}\n\n"
                return

            # Heartbeat — prevent proxy from dropping idle connection
            if now - last_heartbeat >= HEARTBEAT_INTERVAL:
                yield ": heartbeat\n\n"
                last_heartbeat = now

            job = PostingJob.objects.get(id=job_id)

            # Only fetch changed items (skip on first poll)
            if last_updated:
                min_ts = min(last_updated.values())
                items = job.items.select_related(
                    'owned_product', 'store', 'listing',
                ).filter(updated_at__gte=min_ts)
            else:
                items = job.items.select_related(
                    'owned_product', 'store', 'listing',
                ).all()

            for item in items:
                if item.updated_at != last_updated.get(item.id):
                    last_updated[item.id] = item.updated_at
                    yield f"data: {json.dumps({'type': 'item_update', 'item_id': item.id, 'login': item.login, 'store': f'{item.marketplace} — {item.store.name}', 'status': item.status, 'offer_id': item.listing.store_listing_id if item.listing else None, 'offer_title': item.listing.title if item.listing else None, 'error': item.error_message, 'resolved': item.owned_product_id is not None})}\n\n"

            if job.status in (
                PostingJobStatus.COMPLETED,
                PostingJobStatus.FAILED,
                PostingJobStatus.CANCELLED,
            ):
                yield f"data: {json.dumps({'type': 'job_complete', 'status': job.status, 'success_count': job.success_count, 'fail_count': job.fail_count})}\n\n"
                return

            time.sleep(POLL_INTERVAL)

    response = StreamingHttpResponse(
        event_generator(),
        content_type='text/event-stream',
    )
    response['Cache-Control'] = 'no-cache'
    response['X-Accel-Buffering'] = 'no'
    return response


@login_required
def posting_defaults(request, game_id, marketplace):
    """GET: read defaults. POST: upsert defaults."""
    try:
        game = Game.objects.get(id=game_id)
    except Game.DoesNotExist:
        return JsonResponse({'error': 'Game not found'}, status=404)

    if request.method == 'GET':
        try:
            d = PostingDefault.objects.get(game=game, marketplace=marketplace)
            return JsonResponse({
                'multiplier_low': str(d.multiplier_low),
                'multiplier_mid': str(d.multiplier_mid),
                'multiplier_high': str(d.multiplier_high),
                'min_price': str(d.min_price),
                'forced_ending': str(d.forced_ending) if d.forced_ending is not None else None,
                'sub_platform': d.sub_platform,
                'account_type': d.account_type,
            })
        except PostingDefault.DoesNotExist:
            return JsonResponse({
                'multiplier_low': '2.00',
                'multiplier_mid': '1.80',
                'multiplier_high': '1.50',
                'min_price': '0.00',
                'forced_ending': '0.99',
                'sub_platform': '',
                'account_type': '',
            })

    elif request.method == 'POST':
        try:
            body = json.loads(request.body)
        except (json.JSONDecodeError, ValueError):
            return JsonResponse({'error': 'Invalid JSON'}, status=400)

        update_fields = {}
        for field in ('multiplier_low', 'multiplier_mid', 'multiplier_high',
                      'min_price', 'forced_ending', 'sub_platform', 'account_type'):
            if field in body:
                update_fields[field] = body[field]

        PostingDefault.objects.update_or_create(
            game=game, marketplace=marketplace,
            defaults=update_fields,
        )
        return JsonResponse({'ok': True})

    return JsonResponse({'error': 'Method not allowed'}, status=405)


@login_required
@require_GET
def available_stores(request):
    """List active sell/both stores for the posting UI."""
    stores = IntegrationAccount.objects.filter(
        is_active=True, role__in=['sell', 'both'],
    ).values('id', 'name', 'provider', 'slug')

    return JsonResponse({'stores': list(stores)})


@login_required
@require_POST
def cancel_job(request, job_id):
    """Cancel a running job. Remaining items will be marked SKIPPED."""
    try:
        job = PostingJob.objects.get(id=job_id)
    except PostingJob.DoesNotExist:
        return JsonResponse({'error': 'Job not found'}, status=404)

    if job.status not in (PostingJobStatus.PENDING, PostingJobStatus.RUNNING):
        return JsonResponse(
            {'error': f'Cannot cancel job with status "{job.status}"'},
            status=400,
        )

    job.status = PostingJobStatus.CANCELLED
    job.save(update_fields=['status'])

    logger.info("Job #%d cancelled by user", job_id)
    return JsonResponse({'ok': True, 'status': 'cancelled'})


@login_required
@require_GET
def repost_data(request):
    """Extract logins from selected job items for the repost flow.

    Query params:
        job_id: int — source job
        item_ids: str — comma-separated item IDs (e.g. "5,12,45")

    Returns game info + unique login list for pre-filling the create job form.
    """
    job_id = request.GET.get('job_id')
    item_ids_raw = request.GET.get('item_ids', '')

    if not job_id:
        return JsonResponse({'error': 'job_id is required'}, status=400)

    try:
        job = PostingJob.objects.select_related('game').get(id=int(job_id))
    except (PostingJob.DoesNotExist, ValueError):
        return JsonResponse({'error': 'Job not found'}, status=404)

    # Parse item IDs
    try:
        item_ids = [int(x.strip()) for x in item_ids_raw.split(',') if x.strip()]
    except ValueError:
        return JsonResponse({'error': 'Invalid item_ids format'}, status=400)

    if not item_ids:
        return JsonResponse({'error': 'item_ids is required'}, status=400)

    # Get unique logins from selected items
    items = PostingJobItem.objects.filter(
        job=job,
        id__in=item_ids,
    )

    logins = list(dict.fromkeys(
        item.login for item in items
    ))

    if not logins:
        return JsonResponse({'error': 'No valid items found'}, status=400)

    return JsonResponse({
        'game_id': job.game_id,
        'game_name': job.game.name,
        'logins': logins,
        'source_account_id': job.source_account_id,
    })
