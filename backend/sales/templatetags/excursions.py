# sales/templatetags/excursions.py
from __future__ import annotations
from django import template
from sales.services.titles import excursion_title_es

register = template.Library()

@register.simple_tag
def title_es(excursion_id, fallback_ru_title=""):
    """
    Тег: {% title_es excursion_id booking.excursion_title as es %}
    Вернёт короткое испанское название.
    """
    try:
        exid = int(excursion_id or 0)
    except Exception:
        exid = 0
    return excursion_title_es(exid, fallback_ru_title or "")

# Совместимость со старым названием фильтра/тега
@register.filter(name="spanish_excursion_name")
def spanish_excursion_name_filter(ru_title, excursion_id=0):
    """
    Использование: {{ booking.excursion_title|spanish_excursion_name:booking.excursion_id }}
    """
    try:
        exid = int(excursion_id or 0)
    except Exception:
        exid = 0
    return excursion_title_es(exid, ru_title or "")
