# sales/apps.py
from django.apps import AppConfig

class SalesConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'sales'

    def ready(self):
        # подключаем сигналы при старте Django
        from . import signals  # noqa
