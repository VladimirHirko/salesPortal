from django import template

register = template.Library()

@register.simple_tag
def net_saved(saved_map, ex_id, reg, company_id=0):
    """
    Вернёт объект ExcursionNetPrice из словаря saved по ключу
    (excursion_id, region_slug, company_id|0) либо None.
    """
    try:
        ex = int(ex_id)
    except Exception:
        ex = 0
    slug = (reg or "").lower()
    try:
        cid = int(company_id or 0)
    except Exception:
        cid = 0
    return saved_map.get((ex, slug, cid))
