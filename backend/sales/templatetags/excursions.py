# sales/templatetags/excursions.py
from django import template

# берём уже готовую логику перевода из твоего сервиса
from sales.services.emails import spanish_excursion_name

register = template.Library()

@register.filter(name="es_excursion")
def es_excursion(ru_title, excursion_id=0):
    """
    Вернёт испанское краткое имя экскурсии.
    Работает и без id (по словарю/эвристике), но с id ещё надёжнее.
    """
    try:
        exid = int(excursion_id or 0)
    except Exception:
        exid = 0
    ru = (ru_title or "").strip()
    return spanish_excursion_name(exid, ru)
