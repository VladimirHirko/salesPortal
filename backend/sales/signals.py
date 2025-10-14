# sales/signals.py
from django.db.models.signals import pre_save
from django.dispatch import receiver
from .models import BookingSale

@receiver(pre_save, sender=BookingSale)
def fill_travelers_names(sender, instance: BookingSale, **kwargs):
    """
    Перед сохранением брони обновляем поле-снапшот travelers_names
    из travelers_csv (списка ID гостей). Так билет не зависит от связей.
    """
    try:
        instance.set_travelers_names_from_ids()
    except Exception:
        # не рушим сохранение из-за побочного снапшота
        pass
