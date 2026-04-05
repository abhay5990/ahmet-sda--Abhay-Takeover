from django.db import models


class OwnedProductStatus(models.TextChoices):
    DRAFT = 'draft', 'Draft'
    LISTED = 'listed', 'Listed'
    SOLD = 'sold', 'Sold'
    MULTIPLE_SOLD = 'multiple_sold', 'Multiple Sold'
    REPLACED = 'replaced', 'Replaced'
    RECOVERED = 'recovered', 'Recovered'
    LOST = 'lost', 'Lost'
    BANNED = 'banned', 'Banned'


class DropshipProductStatus(models.TextChoices):
    LISTED = 'listed', 'Listed'
    SOLD = 'sold', 'Sold'
    DELETED = 'deleted', 'Deleted'
