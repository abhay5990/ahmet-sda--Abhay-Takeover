from django.db import models


class ProductCategory(models.TextChoices):
    ACCOUNTS = 'accounts', 'Accounts'
    ITEMS = 'items', 'Items'
    CURRENCY = 'currency', 'Currency'
    GIFT_CARD = 'gift_card', 'Gift Card'
    TOP_UP = 'top_up', 'Top Up'
