from django.db import models


class OrderStatus(models.TextChoices):
    PENDING = 'pending', 'Pending'
    DELIVERED = 'delivered', 'Delivered'
    COMPLETED = 'completed', 'Completed'
    REFUNDED = 'refunded', 'Refunded'
    DISPUTED = 'disputed', 'Disputed'
    CANCELLED = 'cancelled', 'Cancelled'
