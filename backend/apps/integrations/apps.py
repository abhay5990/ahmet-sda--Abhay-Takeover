from django.apps import AppConfig


class IntegrationsConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'apps.integrations'
    verbose_name = 'Integrations'

    def ready(self):
        # Auto-discover and register all providers
        from apps.integrations.providers import lzt, eldorado, g2g, gameboost, playerauctions  # noqa: F401
