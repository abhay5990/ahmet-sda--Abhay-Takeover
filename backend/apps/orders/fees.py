"""Fee calculation utility.

Entry point: calculate_fee()
Used during order sync and bulk fee backfill.
"""
from datetime import date
from decimal import Decimal
from typing import Optional

from django.db.models import Q

from .enums import FeeType
from .models import FeeRule


def calculate_fee(
    marketplace: str,
    fee_type: str = FeeType.SALE,
    product_category: str = '',
    game_id: Optional[int] = None,
    ref_date: Optional[date] = None,
) -> Optional[FeeRule]:
    """Return the most specific matching FeeRule.

    Lookup priority (most specific wins):
      1. marketplace + game + product_category + fee_type
      2. marketplace + game + fee_type
      3. marketplace + product_category + fee_type
      4. marketplace + fee_type  (default)

    Args:
        marketplace: Provider value (e.g. 'eldorado', 'gameboost')
        fee_type: 'sale' or 'withdraw'
        product_category: ProductCategory value (e.g. 'accounts', 'items') or ''
        game_id: Game PK (nullable)
        ref_date: Date to match rules against (default: today)

    Returns:
        Matching FeeRule or None (if no rule found)
    """
    if ref_date is None:
        from django.utils import timezone
        ref_date = timezone.now().date()

    # Date filter: effective_from <= ref_date AND (effective_until >= ref_date OR NULL)
    base_qs = FeeRule.objects.filter(
        marketplace=marketplace,
        fee_type=fee_type,
        effective_from__lte=ref_date,
    ).filter(
        Q(effective_until__gte=ref_date) | Q(effective_until__isnull=True),
    )

    # 1. marketplace + game + category (most specific)
    if game_id and product_category:
        rule = base_qs.filter(
            game_id=game_id,
            product_category=product_category,
        ).order_by('-effective_from').first()
        if rule:
            return rule

    # 2. marketplace + game
    if game_id:
        rule = base_qs.filter(
            game_id=game_id,
            product_category='',
        ).order_by('-effective_from').first()
        if rule:
            return rule

    # 3. marketplace + category
    if product_category:
        rule = base_qs.filter(
            game__isnull=True,
            product_category=product_category,
        ).order_by('-effective_from').first()
        if rule:
            return rule

    # 4. marketplace default
    rule = base_qs.filter(
        game__isnull=True,
        product_category='',
    ).order_by('-effective_from').first()
    return rule


def compute_fee_amount(
    price: Decimal,
    rule: FeeRule,
    include_flat: bool = True,
) -> Decimal:
    """Calculate fee amount from a FeeRule.

    Args:
        include_flat: True  -> includes flat_fee (full calculation).
                      False -> percent only (for sync/backfill).

    Formula: (price * fee_percent / 100) [+ flat_fee]
    """
    percent_fee = price * rule.fee_percent / Decimal('100')
    total = percent_fee + rule.flat_fee if include_flat else percent_fee
    return total.quantize(Decimal('0.01'))


def apply_fee_to_order(order) -> bool:
    """Auto-apply fee to an order.

    Skips if our_fee is already set.
    Skips if no matching FeeRule is found.

    Returns:
        True if fee was applied, False if skipped.
    """
    if order.our_fee is not None:
        return False

    provider = ''
    if order.integration_account:
        provider = order.integration_account.provider

    if not provider:
        return False

    ref_date = order.sold_at.date() if order.sold_at else None

    rule = calculate_fee(
        marketplace=provider,
        fee_type=FeeType.SALE,
        product_category=order.product_category or '',
        game_id=order.game_id,
        ref_date=ref_date,
    )
    if not rule:
        return False

    order.our_fee = compute_fee_amount(order.price, rule, include_flat=False)
    return True
