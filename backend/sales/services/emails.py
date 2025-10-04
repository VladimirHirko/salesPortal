from django.apps import apps
from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string
from django.utils.html import strip_tags
import re
from functools import lru_cache
from sales.services import costasolinfo as csi
import logging
log = logging.getLogger(__name__)

Traveler = apps.get_model("sales", "Traveler")

# --- helpers ---------------------------------------------------------------

@lru_cache(maxsize=512)
def _title_in_lang(excursion_id: int, lang: str) -> str:
    try:
        return csi.excursion_title(excursion_id, lang=lang) or ""
    except Exception:
        return ""

# Берём ES-название из core.Excursion по csi_id
@lru_cache(maxsize=512)
def _title_es_from_core_any(excursion_id: int, ru_title: str) -> str:
    """
    Достаём испанское имя из core.Excursion.name (колонка «Экскурсия»).
    Стратегии:
      1) core.Excursion(csi_id=excursion_id).name
      2) core.Excursion(id=excursion_id).name   (если вдруг брони хранят внутренний id)
      3) core.ExcursionContentBlock(excursion__csi_id=excursion_id).excursion.name
      4) по топониму: ищем core.Excursion.name ~ «Sevilla», «Ronda», ...
    """
    try:
        CoreExcursion = apps.get_model("core", "Excursion")
    except Exception:
        log.warning("emails: core.Excursion model not found")
        CoreExcursion = None

    try:
        CoreBlock = apps.get_model("core", "ExcursionContentBlock")
    except Exception:
        CoreBlock = None

    # 1) по csi_id
    if CoreExcursion and excursion_id:
        name = (CoreExcursion.objects
                .filter(csi_id=excursion_id)
                .values_list("name", flat=True)
                .first())
        if name:
            return name

    # 2) по внутреннему id
    if CoreExcursion and excursion_id:
        name = (CoreExcursion.objects
                .filter(id=excursion_id)
                .values_list("name", flat=True)
                .first())
        if name:
            return name

    # 3) через блок -> excursion.name
    if CoreBlock and excursion_id:
        name = (CoreBlock.objects
                .filter(excursion__csi_id=excursion_id)
                .values_list("excursion__name", flat=True)
                .first())
        if name:
            return name

    # 4) по топониму из русского
    base_ru = _strip_to_toponym(ru_title)
    guess_es = TOPONYM_RU_ES.get((base_ru or "").lower())
    if CoreExcursion and guess_es:
        # сначала точное совпадение
        name = (CoreExcursion.objects
                .filter(name__iexact=guess_es)
                .values_list("name", flat=True)
                .first())
        if name:
            return name
        # потом contains
        name = (CoreExcursion.objects
                .filter(name__icontains=guess_es)
                .values_list("name", flat=True)
                .first())
        if name:
            return name

    log.info("emails: ES title not found in core (exc_id=%s, ru='%s')", excursion_id, ru_title)
    return ""

TOPONYM_RU_ES = {
    "севилья": "Sevilla",
    "гибралтар": "Gibraltar",
    "кордоба": "Córdoba",
    "ронда": "Ronda",
    "танжер": "Tánger",
    "каминито дель рей": "Caminito del Rey",
    "нерха и фрихилиана": "Nerja y Frigiliana",
    "королевская тропа": "Caminito del Rey",
}

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
    Единая точка получения испанского названия:
    core.Excursion.name -> (если нет) API ES -> (если нет) эвристика из RU.
    """
    # A) core.Excursion.name (как вы и хотите)
    es_core = _title_es_from_core_any(excursion_id, ru_title)
    if es_core:
        return es_core

    # B) вдруг источник отдаёт ES
    es_api = _title_in_lang(excursion_id, "es") if excursion_id else ""
    if es_api:
        short = re.split(r"[—:]", es_api, maxsplit=1)[0].strip()
        return short or es_api

    # C) fallback: выжимаем топоним и маппим словарём
    base_ru = _strip_to_toponym(ru_title)
    lower = base_ru.lower()
    for key in sorted(TOPONYM_RU_ES.keys(), key=len, reverse=True):
        if key in lower:
            return TOPONYM_RU_ES[key]
    return base_ru

def _special_key(title: str | None) -> str | None:
    s = (title or "").lower()
    if "tang" in s or "танж" in s:      return "tangier"
    if "granad" in s or "грана" in s:    return "granada"
    if "gibr" in s or "гибр" in s:       return "gibraltar"
    if "sevil" in s or "севил" in s:     return "seville"
    return None

def _parse_travelers_csv(csv: str) -> list[int]:
    return [int(p) for p in str(csv or "").split(",") if p.strip().isdigit()]

def _collect_travelers(booking) -> list[dict]:
    ids = _parse_travelers_csv(getattr(booking, "travelers_csv", ""))
    if not ids:
        return []
    rows = (
        Traveler.objects
        .filter(id__in=ids)
        .values(
            "id", "first_name", "last_name",
            "passport", "nationality",
            "dob", "gender", "doc_type", "doc_expiry", "passport_expiry",
        )
    )
    by_id = {r["id"]: r for r in rows}
    out = []
    for i in ids:
        r = by_id.get(i)
        if not r:
            continue
        out.append({
            "id": i,
            "first_name": r.get("first_name") or "",
            "last_name":  r.get("last_name")  or "",
            "passport":   r.get("passport")   or "",
            "nationality":r.get("nationality")or "",
            "dob":            (r["dob"].isoformat() if r.get("dob") else ""),
            "gender":         r.get("gender") or "",
            "doc_type":       r.get("doc_type") or "",
            "doc_expiry":     (r["doc_expiry"].isoformat() if r.get("doc_expiry") else ""),
            "passport_expiry":(r["passport_expiry"].isoformat() if r.get("passport_expiry") else ""),
        })
    return out

# --- отправка ---------------------------------------------------------------

def send_booking_email(booking, *, subject_prefix: str = "[SalesPortal]") -> bool:
    # Куда отправляем
    to = []
    company = getattr(booking, "company", None)
    comp_email = getattr(company, "email_for_orders", None)
    if comp_email:
        to.append(comp_email)
    fallback_to = getattr(settings, "BOOKINGS_FALLBACK_EMAIL", None)
    if not to and fallback_to:
        to.append(fallback_to)
    if not to:
        return True

    # Испанское название — ЖЁСТКО из core, с падением на другие варианты
    title_es = spanish_excursion_name(
        int(getattr(booking, "excursion_id", 0) or 0),
        getattr(booking, "excursion_title", "") or "",
    )

    # Карта
    maps_url = None
    if getattr(booking, "pickup_lat", None) is not None and getattr(booking, "pickup_lng", None) is not None:
        maps_url = f"https://maps.google.com/?q={booking.pickup_lat},{booking.pickup_lng}"
    elif booking.pickup_point_name or booking.hotel_name:
        from urllib.parse import quote
        maps_url = f"https://maps.google.com/?q={quote(booking.pickup_point_name or booking.hotel_name)}"

    # Контекст
    ctx = {
        "booking": {
            "title_es":          title_es,  # ← используем в шаблоне
            "excursion_title":   booking.excursion_title,  # на всякий случай оставим и RU
            "excursion_language":getattr(booking, "excursion_language", ""),
            "date":              booking.date.isoformat() if booking.date else "",
            "company":           company,
            "booking_code":      booking.booking_code,
            "hotel_name":        booking.hotel_name,
            "room_number":       getattr(booking, "room_number", ""),
            "adults":            booking.adults, "children": booking.children, "infants": booking.infants,
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

    # Тема: «Reserva de <Компания или гид> - <ES-название> - <дата> - <код>»
    who = (getattr(company, "name", "") or getattr(getattr(booking, "guide", None), "get_full_name", lambda: "")() or "").strip()
    who = who or "—"
    subject = f"{subject_prefix} Reserva de {who} - {title_es} - {booking.date or ''} - {booking.booking_code}"

    from_email = getattr(settings, "DEFAULT_FROM_EMAIL", "no-reply@example.com")
    msg = EmailMultiAlternatives(subject=subject, body=text, from_email=from_email, to=to)
    msg.attach_alternative(html, "text/html")

    try:
        sent = msg.send(fail_silently=False)
        return bool(sent)
    except Exception:
        return False


# sales/services/emails.py

def _build_common_ctx(booking) -> dict:
    maps_url = None
    if getattr(booking, "pickup_lat", None) is not None and getattr(booking, "pickup_lng", None) is not None:
        maps_url = f"https://maps.google.com/?q={booking.pickup_lat},{booking.pickup_lng}"
    elif booking.pickup_point_name or booking.hotel_name:
        from urllib.parse import quote
        maps_url = f"https://maps.google.com/?q={quote(booking.pickup_point_name or booking.hotel_name)}"

    title_es = spanish_excursion_name(
        int(getattr(booking, "excursion_id", 0) or 0),
        getattr(booking, "excursion_title", "") or ""
    )

    return {
        "booking": {
            "title_es":          title_es,
            "excursion_title":   booking.excursion_title,   # fallback
            "excursion_language":getattr(booking, "excursion_language", ""),
            "date":              booking.date.isoformat() if booking.date else "",
            "company":           getattr(booking, "company", None),
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
        "travelers": _collect_travelers(booking),
        "special_key": _special_key(getattr(booking, "excursion_title", "")),
    }

def send_cancellation_email(booking, reason: str = "", *, subject_prefix: str = "[SalesPortal]") -> bool:
    # получатели
    to = []
    company = getattr(booking, "company", None)
    comp_email = getattr(company, "email_for_orders", None)
    if comp_email:
        to.append(comp_email)
    fallback_to = getattr(settings, "BOOKINGS_FALLBACK_EMAIL", None)
    if not to and fallback_to:
        to.append(fallback_to)
    if not to:
        return True

    ctx = _build_common_ctx(booking)
    ctx["reason"] = reason or ""

    # тема в формате "Cancelación — Reserva de <Company/Guide>: <ES title> · <date> · <code>"
    comp_or_guide = (getattr(getattr(booking, "company", None), "name", None)
                     or getattr(getattr(booking, "guide", None), "get_full_name", lambda: "")()
                     or "—")
    title_es = ctx["booking"].get("title_es") or ctx["booking"].get("excursion_title") or ""
    subject = f"{subject_prefix} Cancelación — Reserva de {comp_or_guide}: {title_es} · {booking.date or ''} · {booking.booking_code}"

    html = render_to_string("sales/email_cancellation.html", ctx)
    text = strip_tags(html)
    from_email = getattr(settings, "DEFAULT_FROM_EMAIL", "no-reply@example.com")

    msg = EmailMultiAlternatives(subject=subject, body=text, from_email=from_email, to=to)
    msg.attach_alternative(html, "text/html")
    try:
        return bool(msg.send(fail_silently=False))
    except Exception:
        return False
