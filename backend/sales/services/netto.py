# sales/services/netto.py
from decimal import Decimal, ROUND_HALF_UP
from django.utils import timezone
from sales.models import ExcursionNetPrice

def _in_range(rec, d):
    if not d: return True
    if rec.valid_from and d < rec.valid_from: return False
    if rec.valid_to   and d > rec.valid_to:   return False
    return True

def resolve_net_prices(*, company_id: int|None, excursion_id: int, region_slug: str|None, date=None):
    """
    Возвращает словарь:
      {'currency':'EUR','net_adult':Decimal,'net_child':Decimal}
    Ищет в порядке приоритета: company+region → company → any+region → any.
    Берёт актуальную запись по дате.
    """
    qs = ExcursionNetPrice.objects.filter(is_active=True, excursion_id=excursion_id)
    region_slug = (region_slug or '').strip().lower()
    today = date or timezone.now().date()

    # кандидаты по убыванию специфичности
    candidates = list(qs.filter(company_id=company_id, region_slug=region_slug)) + \
                 list(qs.filter(company_id=company_id, region_slug='')) + \
                 list(qs.filter(company_id__isnull=True, region_slug=region_slug)) + \
                 list(qs.filter(company_id__isnull=True, region_slug=''))

    # сначала по дате, затем «самая свежая» valid_from
    best = None
    for rec in candidates:
        if not _in_range(rec, today): 
            continue
        if best is None or (rec.valid_from or today) > (best.valid_from or today):
            best = rec

    if not best:
        return None

    cur = best.currency or 'EUR'
    net_adult = Decimal(best.net_per_adult)
    if best.net_per_child is not None:
        net_child = Decimal(best.net_per_child)
    else:
        disc = Decimal(best.child_discount_pct or 0) / Decimal(100)
        net_child = (net_adult * (Decimal(1) - disc)).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)

    return {"currency": cur, "net_adult": net_adult, "net_child": net_child}
