"""Export parsed credentials from instant account order RawPayloads to a JSON file.

Filters:
  - category = accounts (instant delivery only)
  - status = pending / delivered / completed / disputed
  - is_instant = True

Usage:
    python manage.py export_order_credentials
    python manage.py export_order_credentials --provider gameboost
    python manage.py export_order_credentials --output /tmp/creds.json
"""

import json
from pathlib import Path

from django.core.management.base import BaseCommand
from django.utils import timezone

from apps.sync.enums import ResourceType
from apps.sync.models import RawPayload


# Statuses we care about (successful or active orders)
_ACCEPTED_STATUSES = {
    # Gameboost
    'new', 'in_delivery', 'delivered', 'completed', 'disputed',
    # Eldorado (state.state)
    'initialized', 'pendingreview', 'paid', 'delivered', 'received',
    'completed', 'disputed', 'delivereddisputed',
    # PlayerAuctions
    'pending payment', 'payment received', 'order processing',
    'delivery in progress', 'verifying payment',
    'delivery fully completed',
    'disputed', 'disputed delivery not completed',
    'disputed delivery completed', 'disputed delivery partially completed',
    'disputed delivery fully completed',
}


class Command(BaseCommand):
    help = 'Re-parse instant account order RawPayloads and export credentials to a JSON file'

    def add_arguments(self, parser):
        parser.add_argument(
            '--provider',
            choices=['gameboost', 'eldorado', 'playerauctions'],
            help='Filter by provider (default: all)',
        )
        parser.add_argument(
            '--output', '-o',
            default='',
            help='Output file path (default: tmp/order_credentials_<date>.json)',
        )

    def handle(self, *args, **options):
        provider_filter = options['provider']
        output_path = options['output']

        if not output_path:
            from django.conf import settings
            date_str = timezone.now().strftime('%Y-%m-%d_%H%M')
            output_path = str(
                settings.ROOT_DIR / 'tmp' / f'order_credentials_{date_str}.json'
            )

        Path(output_path).parent.mkdir(parents=True, exist_ok=True)

        qs = RawPayload.objects.filter(
            resource_type=ResourceType.ORDERS,
        ).select_related('integration_account')

        if provider_filter:
            qs = qs.filter(integration_account__provider=provider_filter)

        total = qs.count()
        self.stdout.write(f'Scanning {total} order RawPayloads...')

        results = []
        stats = {
            'total': total,
            'skipped_not_account': 0,
            'skipped_status': 0,
            'skipped_not_instant': 0,
            'parsed': 0,
            'no_creds': 0,
            'error': 0,
        }

        for raw in qs.iterator():
            provider = raw.integration_account.provider
            account_slug = raw.integration_account.slug
            payload = raw.payload

            # --- Filter: category must be accounts ---
            if not _is_account_category(provider, payload):
                stats['skipped_not_account'] += 1
                continue

            # --- Filter: status must be accepted ---
            if not _is_accepted_status(provider, payload):
                stats['skipped_status'] += 1
                continue

            # --- Filter: must be instant delivery ---
            if not _is_instant(provider, payload):
                stats['skipped_not_instant'] += 1
                continue

            try:
                creds = _extract_credentials(provider, payload)
            except Exception as exc:
                stats['error'] += 1
                results.append({
                    'remote_id': raw.remote_id,
                    'provider': provider,
                    'account': account_slug,
                    'error': str(exc),
                })
                continue

            if not creds:
                stats['no_creds'] += 1
                results.append({
                    'remote_id': raw.remote_id,
                    'provider': provider,
                    'account': account_slug,
                    'credentials': None,
                })
                continue

            stats['parsed'] += 1
            entry = {
                'remote_id': raw.remote_id,
                'provider': provider,
                'account': account_slug,
                'status': _get_raw_status(provider, payload),
                'game': _extract_game_info(provider, payload),
                'raw_credentials': _extract_raw_credentials_text(provider, payload),
                'credentials': creds,
            }
            results.append(entry)

        output = {
            'exported_at': timezone.now().isoformat(),
            'stats': stats,
            'orders': results,
        }

        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(output, f, indent=2, ensure_ascii=False, default=str)

        self.stdout.write(self.style.SUCCESS(
            f'Done. parsed={stats["parsed"]}, no_creds={stats["no_creds"]}, '
            f'errors={stats["error"]}\n'
            f'  Skipped: not_account={stats["skipped_not_account"]}, '
            f'status={stats["skipped_status"]}, '
            f'not_instant={stats["skipped_not_instant"]}\n'
            f'  Output: {output_path}'
        ))


# ── Filter helpers ─────────────────────────────────────────────────


def _is_account_category(provider: str, payload: dict) -> bool:
    """Check if order is for an account product (not currency/items)."""
    if provider == 'gameboost':
        return bool(payload.get('account_offer_id'))
    elif provider == 'eldorado':
        offer = payload.get('orderOfferDetails') or {}
        return offer.get('category') == 'Account'
    elif provider == 'playerauctions':
        product_type = (
            payload.get('product_type') or payload.get('productType') or ''
        ).strip().lower()
        return product_type in ('', 'game accounts', 'accounts')
    return False


def _is_accepted_status(provider: str, payload: dict) -> bool:
    """Check if order status is one we care about."""
    status = _get_raw_status(provider, payload)
    return status.lower() in _ACCEPTED_STATUSES


def _get_raw_status(provider: str, payload: dict) -> str:
    """Extract raw status string from payload."""
    if provider == 'gameboost':
        return payload.get('status', '')
    elif provider == 'eldorado':
        return (payload.get('state') or {}).get('state', '')
    elif provider == 'playerauctions':
        status_obj = payload.get('status')
        if isinstance(status_obj, dict):
            return status_obj.get('current') or status_obj.get('orderStatus') or ''
        return status_obj or ''
    return ''


def _is_instant(provider: str, payload: dict) -> bool:
    """Check if order is instant delivery."""
    if provider == 'gameboost':
        return not payload.get('is_manual_delivery', False)
    elif provider == 'eldorado':
        offer = payload.get('orderOfferDetails') or {}
        return offer.get('guaranteedDeliveryTime') == 'Instant'
    elif provider == 'playerauctions':
        from apps.sync.services.playerauctions.orders import mapper
        return mapper.extract_is_instant(payload)
    return False


# ── Game & raw text helpers ────────────────────────────────────────


def _extract_game_info(provider: str, payload: dict) -> dict | None:
    """Extract game external ID and resolve to Game name if possible."""
    from apps.inventory.services import resolve_game

    if provider == 'gameboost':
        from apps.sync.services.gameboost.orders import mapper
        ext_id = mapper.extract_game_external_id(payload)
        platform = 'gameboost'
    elif provider == 'eldorado':
        from apps.sync.services.eldorado.orders import mapper
        ext_id = mapper.extract_game_external_id(payload)
        platform = 'eldorado'
    elif provider == 'playerauctions':
        from apps.sync.services.playerauctions.orders import mapper
        ext_id = mapper.extract_game_external_id(payload)
        platform = 'playerauctions'
    else:
        return None

    if not ext_id:
        return None

    game = resolve_game(platform, ext_id)
    return {
        'external_id': ext_id,
        'name': game.name if game else None,
        'category': game.category.name if game and game.category else None,
    }


def _extract_raw_credentials_text(provider: str, payload: dict) -> str | None:
    """Extract the raw credentials text before parsing."""
    if provider == 'gameboost':
        # 1. credential entries
        entries = payload.get('_credential_entries') or []
        if entries:
            texts = [e.get('credentials', '') for e in entries if e.get('credentials')]
            if texts:
                return '\n---\n'.join(texts)
        # 2. inline credentials
        inline = payload.get('credentials', '')
        if inline:
            return inline
        # 3. delivery_instructions
        return payload.get('delivery_instructions') or None

    elif provider == 'eldorado':
        ad = payload.get('accountDetails') or {}
        return ad.get('secretDetails') or None

    elif provider == 'playerauctions':
        order_info = payload.get('order_info') or payload.get('orderInfo') or {}
        return order_info.get('loginName') or order_info.get('login_name') or None

    return None


# ── Credential extraction ──────────────────────────────────────────


def _extract_credentials(provider: str, payload: dict) -> dict | None:
    """Extract credentials from an order payload using provider-specific logic."""
    if provider == 'gameboost':
        return _extract_gameboost(payload)
    elif provider == 'eldorado':
        return _extract_eldorado(payload)
    elif provider == 'playerauctions':
        return _extract_playerauctions(payload)
    return None


def _extract_gameboost(payload: dict) -> dict | None:
    from apps.sync.services.gameboost.orders import mapper

    # 3-step fallback (same as service)
    parsed = None
    entries = payload.get('_credential_entries') or []
    if entries:
        parsed_list = mapper.parse_credentials_from_entries(entries)
        if parsed_list:
            parsed = parsed_list[0]

    if not parsed or not parsed.login:
        parsed = mapper.parse_credentials_from_inline(payload)

    if not parsed or not parsed.login:
        parsed = mapper.parse_credentials_from_delivery_instructions(payload)

    if not parsed or not parsed.login:
        return None

    return _creds_to_dict(parsed)


def _extract_eldorado(payload: dict) -> dict | None:
    from apps.sync.services.eldorado.orders import mapper

    parsed = mapper.parse_credentials_from_account_details(payload)
    if not parsed.login:
        return None

    return _creds_to_dict(parsed)


def _extract_playerauctions(payload: dict) -> dict | None:
    from apps.sync.services.playerauctions.orders import mapper

    login = mapper.extract_login(payload)
    if not login:
        return None

    return {'login': login}


def _creds_to_dict(parsed) -> dict:
    """Convert ParsedCredentials to a plain dict, omitting empty fields."""
    fields = [
        'login', 'password', 'email', 'email_password',
        'email_login_link', 'security_email', 'security_email_password',
    ]
    return {k: getattr(parsed, k) for k in fields if getattr(parsed, k)}
