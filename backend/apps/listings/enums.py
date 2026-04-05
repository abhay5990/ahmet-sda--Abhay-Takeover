from django.db import models


class ListingStatus(models.TextChoices):
    LISTED = 'listed', 'Listed'
    PAUSED = 'paused', 'Paused'
    CLOSED = 'closed', 'Closed'
    DELETED = 'deleted', 'Deleted'
