from django.test import SimpleTestCase

from apps.orders.enums import OrderStatus
from apps.sync.services.base import BaseSyncService


class PoolSaleStatusGuardTests(SimpleTestCase):
    def test_pending_playerauctions_order_cannot_consume_pool_stock(self):
        self.assertFalse(
            BaseSyncService._is_pool_sale_confirmed(OrderStatus.PENDING),
        )

    def test_only_delivery_or_completion_states_can_consume_pool_stock(self):
        self.assertTrue(
            BaseSyncService._is_pool_sale_confirmed(OrderStatus.DELIVERED),
        )
        self.assertTrue(
            BaseSyncService._is_pool_sale_confirmed(OrderStatus.COMPLETED),
        )
        self.assertFalse(
            BaseSyncService._is_pool_sale_confirmed(OrderStatus.CANCELLED),
        )
        self.assertFalse(
            BaseSyncService._is_pool_sale_confirmed(OrderStatus.REFUNDED),
        )
