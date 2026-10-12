from django.apps import AppConfig


class IntegrationsConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'apps.integrations'
    verbose_name = 'Integrations'

    def ready(self):
        # Auto-discover and register all providers
        from apps.integrations.providers import (  # noqa: F401
            eldorado,
            g2g,
            gameboost,
            lzt,
            playerauctions,
            u7buy,
        )
