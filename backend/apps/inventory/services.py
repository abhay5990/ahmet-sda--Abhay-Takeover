import logging

from .models import Game, GamePlatformMapping, OwnedProduct
from .enums import OwnedProductStatus

logger = logging.getLogger(__name__)

# ── Game resolution cache ─────────────────────────────────────────────
_game_cache: dict[tuple[str, str], Game | None] = {}


def warm_game_cache() -> int:
    """Pre-load all GamePlatformMappings into memory. Returns count."""
    _game_cache.clear()
    qs = GamePlatformMapping.objects.select_related('game', 'game__category')
    count = 0
    for m in qs.iterator():
        _game_cache[(m.platform, str(m.external_id))] = m.game
        count += 1
    return count


def clear_game_cache() -> None:
    _game_cache.clear()


def resolve_game(platform: str, external_id: str) -> Game | None:
    """
    Resolve a Game from a platform-specific external ID.

    Uses in-memory cache if warmed via ``warm_game_cache()``.
    """
    key = (platform, str(external_id))
    if key in _game_cache:
        return _game_cache[key]

    mapping = (
        GamePlatformMapping.objects
        .filter(platform=platform, external_id=str(external_id))
        .select_related('game')
        .first()
    )
    result = mapping.game if mapping else None
    _game_cache[key] = result
    return result


def resolve_owned_product_status(owned: OwnedProduct) -> str:
    """Determine and apply the correct status for an OwnedProduct.

    Single source of truth for OwnedProduct status. Priority:
      1. 2+ sold orders (pending/delivered/completed) -> MULTIPLE_SOLD
      2. 1 sold order  -> SOLD
      3. Active listing exists -> LISTED
      4. Otherwise -> DRAFT

    Returns the resolved status string. Saves to DB only if changed.
    """
    from apps.listings.enums import ListingStatus
    from apps.orders.enums import OrderStatus

    _SOLD = (OrderStatus.PENDING, OrderStatus.DELIVERED, OrderStatus.COMPLETED)
    _ACTIVE_LISTING = (ListingStatus.LISTED, ListingStatus.PAUSED)

    success_count = owned.orders.filter(status__in=_SOLD).count()

    if success_count >= 2:
        new_status = OwnedProductStatus.MULTIPLE_SOLD
    elif success_count == 1:
        new_status = OwnedProductStatus.SOLD
    elif owned.listing_owned_products.filter(
        listing__status__in=_ACTIVE_LISTING,
    ).exists():
        new_status = OwnedProductStatus.LISTED
    else:
        new_status = OwnedProductStatus.DRAFT

    if owned.status != new_status:
        old_status = owned.status
        owned.status = new_status
        owned.save(update_fields=['status', 'updated_at'])
        logger.info(
            "OwnedProduct #%s (%s) %s → %s",
            owned.pk, owned.login, old_status, new_status,
        )

    return new_status


class InventoryService:
    @staticmethod
    def get_draft_products(game=None):
        qs = OwnedProduct.objects.filter(status=OwnedProductStatus.DRAFT)
        if game:
            qs = qs.filter(game=game)
        return qs

    @staticmethod
    def get_listable_products():
        return OwnedProduct.objects.filter(
            status__in=[OwnedProductStatus.DRAFT, OwnedProductStatus.LISTED]
        )
