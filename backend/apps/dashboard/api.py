"""
Financial dashboard JSON API.

Single endpoint: /dashboard/finance/api/overview/
Filter params: start_date, end_date, marketplace, currency, game, granularity
  granularity: auto (default) | day | week | month
Returns: all widget data (summary, timeseries, marketplace, games, status)
"""
from datetime import datetime, timedelta
from decimal import Decimal

from django.db.models import Sum, Count, Avg, F, Q, DecimalField
from django.db.models.functions import TruncDate, TruncWeek, TruncMonth, Coalesce
from django.http import JsonResponse
from django.utils import timezone

from apps.accounts.decorators import role_required
from apps.orders.models import Order
from apps.orders.enums import OrderStatus
from apps.integrations.models import Provider
from apps.inventory.models import Game
from core.enums import ProductCategory


# Statuses counted as revenue (excludes cancelled/refunded/disputed).
# Note: pending/delivered are not finalized but included for pipeline visibility.
# For strict accounting, use COMPLETED only.
REVENUE_STATUSES = [
    OrderStatus.PENDING,
    OrderStatus.DELIVERED,
    OrderStatus.COMPLETED,
]


def _parse_date(value, default):
    if not value:
        return default
    try:
        return datetime.strptime(value, '%Y-%m-%d').date()
    except (ValueError, TypeError):
        return default


def _parse_int(value):
    """Return valid positive integer or None."""
    if not value:
        return None
    try:
        n = int(value)
        return n if n > 0 else None
    except (ValueError, TypeError):
        return None


# Granularity -> TruncFunc mapping
_TRUNC_FUNCS = {
    'day': TruncDate,
    'week': TruncWeek,
    'month': TruncMonth,
}


def _resolve_granularity(requested, start_date, end_date):
    """Resolve user granularity preference.

    For `auto` or invalid values, auto-selects based on date range:
      - <= 31 days  -> day
      - 32-180 days -> week
      - > 180 days  -> month

    Returns: (granularity_str, is_auto) — so the UI can show the resolved value.
    """
    if requested in _TRUNC_FUNCS:
        return requested, False

    span_days = (end_date - start_date).days
    if span_days <= 31:
        return 'day', True
    if span_days <= 180:
        return 'week', True
    return 'month', True


def _build_queryset(request):
    """Build Order queryset from filter parameters.

    Note (TZ): sold_at is stored in UTC, `__date` lookup uses UTC dates.
    Frontend sends UTC dates via `new Date().toISOString()` — minor midnight
    drift possible for single-user/TR usage. For multi-user or tz-sensitive
    use, activate user-TZ and switch to local date inputs.
    """
    today = timezone.now().date()
    start_date = _parse_date(request.GET.get('start_date'), today - timedelta(days=30))
    end_date = _parse_date(request.GET.get('end_date'), today)
    marketplace = request.GET.get('marketplace') or None
    currency = request.GET.get('currency') or 'USD'
    game_id = _parse_int(request.GET.get('game'))

    granularity_req = (request.GET.get('granularity') or 'auto').lower()
    granularity, granularity_auto = _resolve_granularity(
        granularity_req, start_date, end_date,
    )

    product_category = request.GET.get('product_category') or None

    qs = Order.objects.filter(
        sold_at__date__gte=start_date,
        sold_at__date__lte=end_date,
        currency=currency,
    )

    if marketplace:
        qs = qs.filter(integration_account__provider=marketplace)

    if game_id:
        qs = qs.filter(game_id=game_id)

    if product_category:
        qs = qs.filter(product_category=product_category)

    return qs, {
        'start_date': start_date.isoformat(),
        'end_date': end_date.isoformat(),
        'marketplace': marketplace,
        'currency': currency,
        'game': game_id,
        'product_category': product_category,
        'granularity': granularity,
        'granularity_auto': granularity_auto,
    }


def _summary(qs):
    """Aggregate summary card data.

    Cost: OwnedProduct.price linked to the Order (purchase cost).
    Only computed for orders with an owned_product FK.
    """
    revenue_qs = qs.filter(status__in=REVENUE_STATUSES)
    agg = revenue_qs.aggregate(
        total_revenue=Coalesce(Sum('price'), Decimal('0'), output_field=DecimalField()),
        total_fees=Coalesce(Sum('our_fee'), Decimal('0'), output_field=DecimalField()),
        total_cost=Coalesce(
            Sum('owned_product__price'),
            Decimal('0'),
            output_field=DecimalField(),
        ),
        total_orders=Count('id'),
        orders_with_cost=Count('id', filter=Q(owned_product__price__isnull=False)),
        avg_order_value=Coalesce(Avg('price'), Decimal('0'), output_field=DecimalField()),
    )
    total_revenue = agg['total_revenue']
    total_fees = agg['total_fees']
    total_cost = agg['total_cost']
    profit = total_revenue - total_fees - total_cost
    return {
        'total_revenue': float(total_revenue),
        'total_fees': float(total_fees),
        'total_cost': float(total_cost),
        'net_revenue': float(total_revenue - total_fees),
        'profit': float(profit),
        'total_orders': agg['total_orders'],
        'orders_with_cost': agg['orders_with_cost'],
        'avg_order_value': float(agg['avg_order_value']),
    }


def _revenue_timeseries(qs, granularity='day'):
    """Revenue + order count time series (day/week/month granularity)."""
    trunc_func = _TRUNC_FUNCS.get(granularity, TruncDate)
    rows = (
        qs.filter(status__in=REVENUE_STATUSES)
        .annotate(bucket=trunc_func('sold_at'))
        .values('bucket')
        .annotate(
            revenue=Coalesce(Sum('price'), Decimal('0'), output_field=DecimalField()),
            orders=Count('id'),
        )
        .order_by('bucket')
    )
    result = []
    for row in rows:
        bucket = row['bucket']
        if bucket is None:
            continue
        # TruncDate -> date, TruncWeek/Month -> datetime. ISO date works for both.
        bucket_date = bucket.date() if hasattr(bucket, 'date') else bucket
        result.append({
            'date': bucket_date.isoformat(),
            'revenue': float(row['revenue']),
            'orders': row['orders'],
        })
    return result


def _marketplace_breakdown(qs):
    """Revenue breakdown by marketplace."""
    rows = (
        qs.filter(status__in=REVENUE_STATUSES)
        .values('integration_account__provider')
        .annotate(
            revenue=Coalesce(Sum('price'), Decimal('0'), output_field=DecimalField()),
            orders=Count('id'),
        )
        .order_by('-revenue')
    )
    provider_labels = dict(Provider.choices)
    return [
        {
            'provider': row['integration_account__provider'] or 'unknown',
            'label': provider_labels.get(row['integration_account__provider'], 'Unknown'),
            'revenue': float(row['revenue']),
            'orders': row['orders'],
        }
        for row in rows
    ]


def _top_games(qs, limit=10):
    """Top revenue-generating games."""
    rows = (
        qs.filter(status__in=REVENUE_STATUSES, game__isnull=False)
        .values('game__name')
        .annotate(
            revenue=Coalesce(Sum('price'), Decimal('0'), output_field=DecimalField()),
            orders=Count('id'),
        )
        .order_by('-revenue')[:limit]
    )
    return [
        {
            'game': row['game__name'],
            'revenue': float(row['revenue']),
            'orders': row['orders'],
        }
        for row in rows
    ]


def _status_breakdown(qs):
    """Order status distribution (all statuses, no revenue filter)."""
    rows = qs.values('status').annotate(count=Count('id')).order_by('status')
    status_labels = dict(OrderStatus.choices)
    return [
        {
            'status': row['status'],
            'label': status_labels.get(row['status'], row['status']),
            'count': row['count'],
        }
        for row in rows
    ]


@role_required('admin')
def finance_overview(request):
    """Return all financial dashboard data in a single endpoint.

    Access: admin role only (user/viewer restricted).
    """
    qs, filters = _build_queryset(request)

    return JsonResponse({
        'filters': filters,
        'summary': _summary(qs),
        'revenue_timeseries': _revenue_timeseries(qs, granularity=filters['granularity']),
        'marketplace_breakdown': _marketplace_breakdown(qs),
        'top_games': _top_games(qs),
        'status_breakdown': _status_breakdown(qs),
        'available_marketplaces': [
            {'value': p.value, 'label': p.label}
            for p in Provider
        ],
        'available_categories': [
            {'value': c.value, 'label': c.label}
            for c in ProductCategory
        ],
        'available_games': list(
            Game.objects.filter(is_active=True)
            .order_by('name')
            .values('id', 'name')
        ),
    })
