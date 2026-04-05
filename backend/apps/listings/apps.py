from django.apps import AppConfig


class ListingsConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'apps.listings'
    verbose_name = 'Listings'

    def ready(self):
        import apps.listings.signals  # noqa: F401
