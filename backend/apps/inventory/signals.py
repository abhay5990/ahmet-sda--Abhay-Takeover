"""Signals that keep OwnedProduct.status in sync automatically.

Listens to Order and ListingOwnedProduct changes and recalculates
the OwnedProduct status via resolve_owned_product_status.

This replaces manual _sync_owned_product_status calls throughout
the codebase — status is always correct as a side-effect of save/delete.
"""

import logging

from django.db.models.signals import post_save, post_delete
from django.dispatch import receiver

logger = logging.getLogger(__name__)


@receiver(post_save, sender='orders.Order')
def order_saved(sender, instance, **kwargs):
    """Recalculate OwnedProduct status when an Order is created/updated."""
    if instance.owned_product_id:
        _resolve_status(instance.owned_product)


@receiver(post_delete, sender='orders.Order')
def order_deleted(sender, instance, **kwargs):
    """Recalculate OwnedProduct status when an Order is deleted."""
    if instance.owned_product_id:
        try:
            from apps.inventory.models import OwnedProduct
            owned = OwnedProduct.objects.get(pk=instance.owned_product_id)
            _resolve_status(owned)
        except Exception:
            pass


@receiver(post_save, sender='listings.ListingOwnedProduct')
def listing_owned_product_saved(sender, instance, **kwargs):
    """Recalculate OwnedProduct status when a ListingOwnedProduct is created."""
    if instance.owned_product_id:
        try:
            from apps.inventory.models import OwnedProduct
            owned = OwnedProduct.objects.get(pk=instance.owned_product_id)
            _resolve_status(owned)
        except Exception:
            pass


@receiver(post_delete, sender='listings.ListingOwnedProduct')
def listing_owned_product_deleted(sender, instance, **kwargs):
    """Recalculate OwnedProduct status when a ListingOwnedProduct is deleted."""
    if instance.owned_product_id:
        try:
            from apps.inventory.models import OwnedProduct
            owned = OwnedProduct.objects.get(pk=instance.owned_product_id)
            _resolve_status(owned)
        except Exception:
            pass


def _resolve_status(owned):
    from apps.inventory.services import resolve_owned_product_status
    resolve_owned_product_status(owned)
