"""Stock posting API endpoints — job CRUD, polling status, defaults management."""

from __future__ import annotations

import hashlib
import json
import logging
import threading
import uuid
from decimal import Decimal

from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.views.decorators.http import require_POST, require_GET

from apps.integrations.models import IntegrationAccount
from apps.inventory.models import Game, OwnedProduct
from apps.posting.models import (
    ContentTemplate,
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
        source_type: 'account' | 'manual'  (default: 'account')
        game_id: int
        stores: list[int]  — IntegrationAccount IDs
        defaults: dict     — {store_slug: {multiplier_low, ..., sub_platform, account_type}}

    Account mode (source_type='account'):
        logins: list[str]  — one login per line
        source_account_id: int|null — fallback account for resolving missing products

    Manual mode (source_type='manual'):
        platform: str            — e.g. 'PlayStation 5'
        credentials: list[dict]  — [{login, password, email, ..., cash_amount, level, cars_count, cost}]
        distribution_mode: 'cross_platform' | 'shared'
        distribution: dict       — {store_slug: int} (only for shared mode)
    """
    try:
        body = json.loads(request.body)
    except (json.JSONDecodeError, ValueError):
        return JsonResponse({'error': 'Invalid JSON'}, status=400)

    source_type = body.get('source_type', 'account')
    game_id = body.get('game_id')
    store_ids = body.get('stores', [])
    defaults_data = body.get('defaults', {})

    if not game_id or not store_ids:
        return JsonResponse({'error': 'game_id and stores are required'}, status=400)
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

    # Build store-slug-keyed settings for this job.
    job_settings = {}
    for store in stores:
        store_defaults = defaults_data.get(store.slug, defaults_data.get(store.provider, {}))
        job_settings[store.slug] = dict(store_defaults) if store_defaults else {}

    # Upsert PostingDefaults (UI pre-fill only)
    for store in stores:
        mp = store.provider
        store_defaults = defaults_data.get(store.slug, defaults_data.get(mp, {}))
        if store_defaults:
            update_fields = {
                k: v for k, v in {
                    'multiplier_low': store_defaults.get('multiplier_low'),
                    'multiplier_mid': store_defaults.get('multiplier_mid'),
                    'multiplier_high': store_defaults.get('multiplier_high'),
                    'min_price': store_defaults.get('min_price'),
                    'forced_ending': store_defaults.get('forced_ending'),
                    'exchange_rate': store_defaults.get('exchange_rate'),
                    'sub_platform': store_defaults.get('sub_platform'),
                    'account_type': store_defaults.get('account_type'),
                }.items() if v is not None
            }
            # Template selections — explicit null clears the FK; validate match before writing
            for fk_field, expected_type in (
                ('title_template_id', 'title'),
                ('description_template_id', 'description'),
            ):
                if fk_field not in store_defaults:
                    continue
                val = store_defaults[fk_field]
                if val:
                    template_id = int(val)
                    if not ContentTemplate.objects.filter(
                        id=template_id,
                        game=game,
                        marketplace=mp,
                        template_type=expected_type,
                    ).exists():
                        return JsonResponse(
                            {
                                'error': (
                                    f'Template {template_id} is not a valid {expected_type} '
                                    f'template for {game.slug}/{mp}.'
                                )
                            },
                            status=400,
                        )
                    update_fields[fk_field] = template_id
                else:
                    update_fields[fk_field] = None
            PostingDefault.objects.update_or_create(
                game=game,
                marketplace=mp,
                defaults=update_fields,
            )

    if source_type == 'manual':
        return _create_manual_job(body, game, stores, job_settings)

    if source_type == 'sheet':
        from apps.posting.api.manual import _create_sheet_job
        return _create_sheet_job(body, game, stores, job_settings)

    return _create_account_job(body, game, stores, job_settings)


def _create_account_job(body: dict, game: Game, stores: list, job_settings: dict) -> JsonResponse:
    """Create job from source account mode (existing flow)."""
    logins = body.get('logins', [])
    source_account_id = body.get('source_account_id')

    if not logins:
        return JsonResponse({'error': 'logins are required'}, status=400)
    if not isinstance(logins, list):
        return JsonResponse({'error': 'logins must be a list'}, status=400)

    # Resolve source account for fallback
    source_account = None
    if source_account_id:
        source_account = IntegrationAccount.objects.filter(
            id=source_account_id, is_active=True,
        ).first()
        if not source_account:
            return JsonResponse({'error': 'Source account not found or inactive'}, status=404)

    # Clean login list
    clean_logins = [login.strip() for login in logins if login.strip()]
    if not clean_logins:
        return JsonResponse({'error': 'No valid logins provided'}, status=400)

    # Pre-resolve OwnedProducts
    owned_map: dict[str, OwnedProduct | None] = {}
    if game.category_id:
        existing = OwnedProduct.objects.filter(
            category=game.category,
            login__in=[l.lower() for l in clean_logins],
        ).select_related('source_account')
        owned_map = {op.login: op for op in existing}

    # Create PostingJob + items
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

    return _launch_job(job, total)


def _create_manual_job(body: dict, game: Game, stores: list, job_settings: dict) -> JsonResponse:
    """Create job from manual credentials.

    Creates OwnedProducts first, then builds PostingJobItems with distribution logic.
    """
    platform = body.get('platform', '')
    credentials = body.get('credentials', [])
    distribution_mode = body.get('distribution_mode', 'cross_platform')
    distribution = body.get('distribution', {})
    purchased_price = body.get('purchased_price', 0)

    if not platform:
        return JsonResponse({'error': 'platform is required for manual mode'}, status=400)
    if not credentials or not isinstance(credentials, list):
        return JsonResponse({'error': 'credentials list is required'}, status=400)

    if not game.category_id:
        return JsonResponse({'error': 'Game has no category assigned'}, status=400)

    try:
        purchased_price = float(purchased_price or 0)
    except (ValueError, TypeError):
        return JsonResponse({'error': 'purchased_price must be a number'}, status=400)

    if purchased_price <= 0:
        return JsonResponse({'error': 'purchased_price is required'}, status=400)

    # Validate credentials (platform-specific primary keys)
    mapping = _PLATFORM_CREDENTIAL_MAP.get(platform)
    login_key = mapping[0] if mapping else 'login'
    pass_key = mapping[1] if mapping else 'password'
    for i, cred in enumerate(credentials):
        if not cred.get(login_key) or not cred.get(pass_key):
            return JsonResponse(
                {'error': f'Credential #{i+1}: {login_key} and {pass_key} are required'},
                status=400,
            )

    # Validate shared distribution
    if distribution_mode == 'shared':
        total_distributed = sum(int(v) for v in distribution.values())
        if total_distributed > len(credentials):
            return JsonResponse(
                {'error': f'Total distributed ({total_distributed}) exceeds credential count ({len(credentials)})'},
                status=400,
            )

    # Batch-level fields from UI
    is_gta = game.slug.startswith('grand-theft-auto')

    # GTA-specific fields only accepted for GTA games
    if is_gta:
        batch_data = {
            'platform': platform,
            'purchased_price': purchased_price,
            'level': _to_int(body.get('level'), 0),
            'cash_amount': _to_int(body.get('cash_amount'), 0),
            'cash_unit': body.get('cash_unit', 'Million'),
            'cars_count': _to_int(body.get('cars_count'), 0),
            'account_tags': body.get('account_tags') or [],
            'has_dual_characters': bool(body.get('has_dual_characters', False)),
            'title': body.get('title') or '',
            'description': body.get('description') or '',
        }
    else:
        batch_data = {
            'platform': platform,
            'purchased_price': purchased_price,
            'title': body.get('title') or '',
            'description': body.get('description') or '',
        }

    # Create OwnedProducts with LZT-compatible raw_data
    owned_products = _create_manual_owned_products(credentials, batch_data, game)

    # Build job items based on distribution mode
    if distribution_mode == 'shared':
        items_data = _build_shared_items(owned_products, stores, distribution)
    else:
        items_data = _build_cross_platform_items(owned_products, stores)

    if not items_data:
        return JsonResponse({'error': 'No items to post (check distribution)'}, status=400)

    # Mark manual source in job settings
    job_settings['_manual'] = {
        'source_type': 'manual',
        'platform': platform,
        'distribution_mode': distribution_mode,
        'purchased_price': purchased_price,
        'batch_data': batch_data,
    }

    job = PostingJob.objects.create(
        game=game,
        source_account=None,
        settings=job_settings,
        total_count=len(items_data),
    )

    items = []
    for login, owned, store in items_data:
        items.append(PostingJobItem(
            job=job,
            login=login,
            owned_product=owned,
            store=store,
            marketplace=store.provider,
        ))
    PostingJobItem.objects.bulk_create(items)

    return _launch_job(job, len(items_data))


# Platform-specific credential key mappings:
# (primary_login_key, primary_password_key, extra_keys_to_store_in_raw_data)
_PLATFORM_CREDENTIAL_MAP: dict[str, tuple[str, str, tuple[str, ...]]] = {
    'PlayStation 4':   ('psn_id',   'psn_pass',   ('psn_id', 'psn_pass', 'dob')),
    'PlayStation 5':   ('psn_id',   'psn_pass',   ('psn_id', 'psn_pass', 'dob')),
    'Xbox One':        ('xbox_id',  'xbox_pass',  ('xbox_id', 'xbox_pass')),
    'Xbox Series X/S': ('xbox_id',  'xbox_pass',  ('xbox_id', 'xbox_pass')),
    'PC - Legacy':     ('steam_id', 'steam_pass', ('steam_id', 'steam_pass', 'rock_id', 'rock_pass')),
    'PC - Enhanced':   ('steam_id', 'steam_pass', ('steam_id', 'steam_pass', 'rock_id', 'rock_pass')),
}


def _extract_platform_credentials(cred: dict, platform: str) -> tuple[str, str, dict]:
    """Extract login, password, and credential_extras from a credential dict.

    For platform-specific GTA credentials, the primary login/password are mapped
    from platform keys (e.g. psn_id → login). All platform keys are also stored
    as extras in raw_data for the credential formatting pipeline.

    Returns (login, password, extras_dict).
    """
    mapping = _PLATFORM_CREDENTIAL_MAP.get(platform)
    if mapping:
        login_key, pass_key, extra_keys = mapping
        login = cred.get(login_key, '').strip().lower()
        password = cred.get(pass_key, '').strip()
        extras = {}
        for k in extra_keys:
            val = cred.get(k, '').strip()
            if val:
                extras[k] = val
        return login, password, extras

    # Default: generic login/password
    return cred.get('login', '').strip().lower(), cred.get('password', '').strip(), {}


def _create_manual_owned_products(
    credentials: list[dict],
    batch_data: dict,
    game: Game,
) -> list[OwnedProduct]:
    """Create or update OwnedProducts for manual credentials.

    Raw data is stored in LZT-compatible format so the existing pipeline
    can process it without changes.  Batch-level fields (price, level, cash,
    platform, title, description) come from ``batch_data``.
    """
    products = []
    platform = batch_data['platform']
    cost = batch_data['purchased_price']

    for cred in credentials:
        login, password, credential_extras = _extract_platform_credentials(cred, platform)

        # Build pipeline-compatible raw_data
        raw_data = {
            'source': 'manual',
            'main_platform': platform,
            'price': cost,
            'loginData': {
                'login': login,
                'password': password,
            },
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
            'title': batch_data.get('title', ''),
            'description': batch_data.get('description', ''),
        }

        # Store platform-specific extras in raw_data
        if credential_extras:
            raw_data.update(credential_extras)

        # GTA-specific fields
        if 'cash_amount' in batch_data:
            raw_data.update({
                'cash_amount': batch_data['cash_amount'],
                'cash_unit': batch_data['cash_unit'],
                'level': batch_data['level'],
                'cars_count': batch_data['cars_count'],
                'tags': batch_data.get('account_tags') or ['modded'],
                'has_dual_characters': batch_data.get('has_dual_characters', False),
            })

        # Upsert OwnedProduct (canonical key: category + login)
        owned, created = OwnedProduct.objects.update_or_create(
            category=game.category,
            login=login,
            defaults={
                'password': password,
                'password_hash': hashlib.sha256(password.encode()).hexdigest(),
                'email': cred.get('email', '').strip(),
                'email_password': cred.get('email_password', '').strip(),
                'email_login_link': cred.get('email_login_link', '').strip(),
                'security_email': cred.get('security_email', '').strip(),
                'security_email_password': cred.get('security_email_password', '').strip(),
                'game': game,
                'status': 'draft',
                'price': Decimal(str(cost)),
                'currency': 'USD',
                'source_account': None,
                'raw_data': raw_data,
            },
        )
        products.append(owned)

    return products


def _build_cross_platform_items(
    owned_products: list[OwnedProduct],
    stores: list,
) -> list[tuple[str, OwnedProduct, IntegrationAccount]]:
    """Cross-platform: same credentials go to ALL stores."""
    items = []
    for owned in owned_products:
        for store in stores:
            items.append((owned.login, owned, store))
    return items


def _build_shared_items(
    owned_products: list[OwnedProduct],
    stores: list,
    distribution: dict,
) -> list[tuple[str, OwnedProduct, IntegrationAccount]]:
    """Shared: different credentials go to different stores based on distribution counts."""
    items = []
    store_map = {s.slug: s for s in stores}
    idx = 0  # credential cursor

    for store_slug, count in distribution.items():
        store = store_map.get(store_slug)
        if not store or not count:
            continue
        count = int(count)
        for _ in range(count):
            if idx >= len(owned_products):
                break
            owned = owned_products[idx]
            items.append((owned.login, owned, store))
            idx += 1

    return items


def _to_int(value, default: int) -> int:
    try:
        if value in (None, ''):
            return default
        return int(value)
    except (TypeError, ValueError):
        return default


def _launch_job(job: PostingJob, total: int) -> JsonResponse:
    """Start orchestrator in background thread (with duplicate guard)."""
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
                'exchange_rate': str(d.exchange_rate) if d.exchange_rate is not None else None,
                'sub_platform': d.sub_platform,
                'account_type': d.account_type,
                'title_template_id': d.title_template_id,
                'description_template_id': d.description_template_id,
            })
        except PostingDefault.DoesNotExist:
            return JsonResponse({
                'multiplier_low': '2.00',
                'multiplier_mid': '1.80',
                'multiplier_high': '1.50',
                'min_price': '0.00',
                'forced_ending': '0.99',
                'exchange_rate': '0.87' if marketplace == 'gameboost' else None,
                'sub_platform': '',
                'account_type': '',
                'title_template_id': None,
                'description_template_id': None,
            })

    elif request.method == 'POST':
        try:
            body = json.loads(request.body)
        except (json.JSONDecodeError, ValueError):
            return JsonResponse({'error': 'Invalid JSON'}, status=400)

        update_fields = {}
        for field in ('multiplier_low', 'multiplier_mid', 'multiplier_high',
                      'min_price', 'forced_ending', 'exchange_rate',
                      'sub_platform', 'account_type'):
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
