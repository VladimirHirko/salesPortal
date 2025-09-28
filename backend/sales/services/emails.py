# sales/services/emails.py
from django.apps import apps
from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string
from django.utils.html import strip_tags
from functools import lru_cache
import re, json

from sales.services import costasolinfo as csi

Traveler = apps.get_model("sales", "Traveler")

# ---------------- helpers: загрузка локального словаря ----------------
@lru_cache(maxsize=1)
def _load_local_es_dict() -> dict:
    """
    Пытаемся прочитать backend/sales/data/excursion_es.json.
    Возвращаем {"by_id":{}, "by_name":{}}.
    """
    try:
        import importlib.resources as res
        with res.files("sales.data").joinpath("excursion_es.json").open("rb") as f:
            raw = json.load(f)
            return {
                "by_id": {str(k): str(v) for k, v in (raw.get("by_id") or {}).items()},
                "by_name": {str(k).strip().lower(): str(v) for k, v in (raw.get("by_name") or {}).items()},
            }
    except Exception:
        return {"by_id": {}, "by_name": {}}

# ---------------- API: заголовок с источника (кеш) -------------------
@lru_cache(maxsize=512)
def _title_in_lang(excursion_id: int, lang: str) -> str:
    try:
        # Некоторые API ожидают "es-ES". Попробуем оба.
        t = csi.excursion_title(excursion_id, lang=lang) or ""
        if not t and lang == "es":
            t = csi.excursion_title(excursion_id, lang="es-ES") or ""
        return t
    except Exception:
        return ""

_EMOJI_OR_MISC = re.compile(r"[\u2600-\u27BF\U0001F300-\U0001FAFF]")

def _strip_to_toponym(ru_title: str) -> str:
    s = (ru_title or "").strip()
    s = _EMOJI_OR_MISC.sub("", s)
    s = re.split(r"[—\-:]", s, maxsplit=1)[0].strip()
    s = re.sub(r"[\(\)\[\]«»\"']", "", s).strip()
    return s

@lru_cache(maxsize=1024)
def spanish_excursion_name(excursion_id: int, ru_title: str) -> str:
    """
    Надёжный конвейер:
    1) по id из локального словаря
    2) из API (es / es-ES) -> укоротить по «—»/«:»
    3) по корневому названию (локальный словарь by_name)
    4) хардкод-топонимы (legacy)
    5) fallback: корневое русское слово (хотя бы без приписок)
    """
    dct = _load_local_es_dict()

    # 1) локально по id
    if excursion_id and str(excursion_id) in dct["by_id"]:
        return dct["by_id"][str(excursion_id)]

    # 2) API испанский
    if excursion_id:
        es = _title_in_lang(excursion_id, "es")
        if es:
            short = re.split(r"[—:]", es, maxsplit=1)[0].strip()
            return short or es

    base_ru = _strip_to_toponym(ru_title or "")
    lower = base_ru.lower()

    # 3) локально по имени
    if lower in dct["by_name"]:
        return dct["by_name"][lower]

    # 4) минимальный хардкод (оставим как сетку безопасности)
    TOPONYM_RU_ES = {
        "севилья": "Sevilla", "гибралтар": "Gibraltar", "кордоба": "Córdoba",
        "ронда": "Ronda", "танжер": "Tánger", "каминито дель рей": "Caminito del Rey",
        "нерха": "Nerja", "нерха и фрихилиана": "Nerja y Frigiliana",
        "королевская тропа": "Caminito del Rey",
    }
    for key in sorted(TOPONYM_RU_ES.keys(), key=len, reverse=True):
        if key in lower:
            return TOPONYM_RU_ES[key]

    # 5) fallback
    return base_ru or (ru_title or "")

# ---------------- остальной код (урезано до части email) --------------
def _special_key(title: str | None) -> str | None:
    s = (title or "").lower()
    if "tang" in s or "танж" in s: return "tangier"
    if "granad" in s or "грана" in s: return "granada"
    if "gibr" in s or "гибр" in s: return "gibraltar"
    if "sevil" in s or "севил" in s: return "seville"
    return None

def _parse_travelers_csv(csv: str) -> list[int]:
    return [int(p) for p in str(csv or "").split(",") if p.strip().isdigit()]

def _collect_travelers(booking) -> list[dict]:
    ids = _parse_travelers_csv(getattr(booking, "travelers_csv", ""))
    if not ids: return []
    rows = (Traveler.objects
            .filter(id__in=ids)
            .values("id","first_name","last_name","passport","nationality",
                    "dob","gender","doc_type","doc_expiry","passport_expiry"))
    by_id = {r["id"]: r for r in rows}
    out = []
    for i in ids:
        r = by_id.get(i)
        if not r: continue
        out.append({
            "id": i,
            "first_name": r.get("first_name") or "",
            "last_name":  r.get("last_name")  or "",
            "passport":   r.get("passport")   or "",
            "nationality":r.get("nationality")or "",
            "dob":             (r["dob"].isoformat() if r.get("dob") else ""),
            "gender":          r.get("gender") or "",
            "doc_type":        r.get("doc_type") or "",
            "doc_expiry":      (r["doc_expiry"].isoformat() if r.get("doc_expiry") else ""),
            "passport_expiry": (r["passport_expiry"].isoformat() if r.get("passport_expiry") else ""),
        })
    return out

def send_booking_email(booking, *, subject_prefix: str = "[SalesPortal]") -> bool:
    # адресаты
    to = []
    company = getattr(booking, "company", None)
    comp_email = getattr(company, "email_for_orders", None)
    if comp_email: to.append(comp_email)
    fallback_to = getattr(settings, "BOOKINGS_FALLBACK_EMAIL", None)
    if not to and fallback_to: to.append(fallback_to)
    if not to: return True  # нет адресата — не падаем

    # название ES
    title_es = spanish_excursion_name(
        int(getattr(booking, "excursion_id", 0) or 0),
        getattr(booking, "excursion_title", "") or ""
    )

    # карта
    maps_url = None
    if getattr(booking, "pickup_lat", None) is not None and getattr(booking, "pickup_lng", None) is not None:
        maps_url = f"https://maps.google.com/?q={booking.pickup_lat},{booking.pickup_lng}"
    elif booking.pickup_point_name or booking.hotel_name:
        from urllib.parse import quote
        maps_url = f"https://maps.google.com/?q={quote(booking.pickup_point_name or booking.hotel_name)}"

    # контекст
    ctx = {
        "booking": {
            "title_es":          title_es,  # <— ЭТО читает шаблон!
            "excursion_title":   getattr(booking, "excursion_title", ""),
            "excursion_language":getattr(booking, "excursion_language", ""),
            "date":              booking.date.isoformat() if booking.date else "",
            "company":           company,
            "booking_code":      booking.booking_code,
            "hotel_name":        booking.hotel_name,
            "room_number":       getattr(booking, "room_number", ""),
            "adults":            booking.adults,
            "children":          booking.children,
            "infants":           booking.infants,
            "pickup_point_name": booking.pickup_point_name,
            "pickup_time_str":   booking.pickup_time_str,
            "pickup_address":    getattr(booking, "pickup_address", ""),
            "pickup_lat":        getattr(booking, "pickup_lat", None),
            "pickup_lng":        getattr(booking, "pickup_lng", None),
            "maps_url":          maps_url,
        },
        "special_key": _special_key(getattr(booking, "excursion_title", "")),
        "travelers":   _collect_travelers(booking),
    }

    html = render_to_string("sales/email_reservation.html", ctx)
    text = strip_tags(html)

    # тема: "Reserva de <Компания/Гид> · <ES-название> · <дата> · <код>"
    comp_name = (getattr(company, "name", "") or "").strip()
    who = comp_name or (getattr(getattr(booking, "guide", None), "get_full_name", lambda: "")() or "—")
    subject = f"{subject_prefix} Reserva de {who} · {title_es} · {booking.date or ''} · {booking.booking_code}"

    msg = EmailMultiAlternatives(subject=subject, body=text,
                                 from_email=getattr(settings, "DEFAULT_FROM_EMAIL", "no-reply@example.com"),
                                 to=to)
    msg.attach_alternative(html, "text/html")
    try:
        return bool(msg.send(fail_silently=False))
    except Exception:
        return False
