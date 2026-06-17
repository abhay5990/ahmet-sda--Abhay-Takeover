from decimal import Decimal, InvalidOperation, ROUND_HALF_UP


def parse_price(value: object) -> Decimal:
    """Parse and validate a price value from API input."""
    try:
        price = Decimal(str(value)).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
    except (InvalidOperation, TypeError, ValueError):
        raise ValueError('Invalid price format')
    if price <= 0:
        raise ValueError('Price must be greater than zero')
    return price
