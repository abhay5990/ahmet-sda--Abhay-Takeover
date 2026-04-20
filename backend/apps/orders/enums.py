from django.db import models


class OrderStatus(models.TextChoices):
    PENDING = 'pending', 'Pending'
    DELIVERED = 'delivered', 'Delivered'
    COMPLETED = 'completed', 'Completed'
    REFUNDED = 'refunded', 'Refunded'
    DISPUTED = 'disputed', 'Disputed'
    DISPUTE_RESOLVED = 'dispute_resolved', 'Dispute Resolved'
    CANCELLED = 'cancelled', 'Cancelled'


class FeeType(models.TextChoices):
    SALE = 'sale', 'Sale'
    WITHDRAW = 'withdraw', 'Withdraw'
