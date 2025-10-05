# sales/services/emails.py
from __future__ import annotations

import logging
import re
from functools import lru_cache
from typing import Any, Dict, List, Optional

from django.apps import apps
from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string
from django.utils.html import strip_tags

from sales.services.titles import compose_bilingual_title, spanish_excursion_name

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Модели по ленивому доступу (чтобы не ломать импорт, если порядок app'ов меняется)
Traveler = apps.get_model("sales", "Traveler")

# ---------------------------------------------------------------------------
# Попытка использовать единый сервис испанских названий.
# Если файла sales/services/titles.py пока нет — используем встроенный fallback.
try:
    from sales.services.titles import spanish_excursion_name as _spanish_excursion_name  # type: ignore
    _HAS_TITLES_SERVICE = True
except Exception:
    _HAS_TITLES_SERVICE = False

    # --- Fallback: извлекаем ES-имя (core -> CSI -> эвристика) ----------------
    from sales.services import costasolinfo as csi  # локальный импорт, чтобы не тянуть при старте

    _EMOJI_OR_MISC = re.compile(r"[\u2600-\u27BF\U0001F300-\U0001FAFF]")
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

    def _strip_to_toponym(ru_title: str) -> str:
        s = (ru_title or "").strip()
        s = _EMOJI_OR_MISC.sub("", s)
        s = re.split(r"[—\-:]", s, maxsplit=1)[0].strip()
        s = re.sub(r"[\(\)\[\]«»\"']", "", s).strip()
        return s

    @lru_cache(maxsize=512)
    def _title_in_lang(excursion_id: int, lang: str) -> str:
        try:
            return csi.excursion_title(excursion_id, lang=lang) or ""
        except Exception:
            return ""

    @lru_cache(maxsize=512)
    def _title_es_from_core_any(excursion_id: int, ru_title: str) -> str:
        """
        Достаём испанское имя из core.Excursion.name (колонка «Экскурсия»).
        Стратегии:
          1) core.Excursion(csi_id=excursion_id).name
          2) core.Excursion(id=excursion_id).name
          3) core.ExcursionContentBlock(excursion__csi_id=excursion_id).excursion.name
          4) по топониму: ищем core.Excursion.name ~ 'Sevilla', 'Ronda', ...
        """
        try:
            CoreExcursion = apps.get_model("core", "Excursion")
        except Exception:
            CoreExcursion = None
            log.warning("emails: core.Excursion model not found")

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

        # 2) safety-net: по внутреннему id
        if CoreExcursion and excursion_id:
            name = (CoreExcursion.objects
                    .filter(id=excursion_id)
                    .values_list("name", flat=True)
                    .first())
            if name:
                return name

        # 3) через контент-блок
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
            # точное совпадение
            name = (CoreExcursion.objects
                    .filter(name__iexact=guess_es)
                    .values_list("name", flat=True)
                    .first())
            if name:
                return name
            # contains
            name = (CoreExcursion.objects
                    .filter(name__icontains=guess_es)
                    .values_list("name", flat=True)
                    .first())
            if name:
                return name

        log.info("emails: ES title not found in core (exc_id=%s, ru='%s')", excursion_id, ru_title)
        return ""

    @lru_cache(maxsize=1024)
    def _spanish_excursion_name(excursion_id: int, ru_title: str) -> str:
        """
        Fallback-реализация spanish_excursion_name:
          1) core.Excursion.name
          2) CSI API (lang='es'), укорачиваем по разделителю
          3) эвристика: топоним из RU и словарь
        """
        es_core = _title_es_from_core_any(excursion_id, ru_title)
        if es_core:
            return es_core

        es_api = _title_in_lang(excursion_id, "es") if excursion_id else ""
        if es_api:
            short = re.split(r"[—:]", es_api, maxsplit=1)[0].strip()
            return short or es_api

        base_ru = _strip_to_toponym(ru_title)
        lower = base_ru.lower()
        for key in sorted(TOPONYM_RU_ES.keys(), key=len, reverse=True):
            if key in lower:
                return TOPONYM_RU_ES[key]
        return base_ru

# Публичная обёртка: не привязываемся к наличию внешнего сервиса
def spanish_excursion_name(excursion_id: int, ru_title: str) -> str:
    try:
        return _spanish_excursion_name(int(excursion_id or 0), ru_title or "")
    except Exception:
        # если вообще всё пошло не так — вернём хотя бы RU
        return (ru_title or "").strip()


# ---------------------------------------------------------------------------
# Прочие утилиты

def _fmt_date(d) -> str:
    """Человекочитаемая дата для темы письма. Без локали — безопасно."""
    try:
        return d.strftime("%d.%m.%Y") if d else ""
    except Exception:
        return str(d or "")

def _maps_url_for(booking) -> Optional[str]:
    """Формируем стабильный Google Maps URL из координат или названия точки/отеля."""
    from urllib.parse import quote
    lat = getattr(booking, "pickup_lat", None)
    lng = getattr(booking, "pickup_lng", None)
    if lat is not None and lng is not None:
        return f"https://maps.google.com/?q={str(lat).strip()},{str(lng).strip()}"
    q = (getattr(booking, "pickup_point_name", None) or getattr(booking, "hotel_name", None) or "").strip()
    return f"https://maps.google.com/?q={quote(q)}" if q else None

def _special_key(title: Optional[str]) -> Optional[str]:
    s = (title or "").lower()
    if "tang" in s or "танж" in s:
        return "tangier"
    if "granad" in s or "грана" in s:
        return "granada"
    if "gibr" in s or "гибр" in s:
        return "gibraltar"
    if "sevil" in s or "севил" in s:
        return "seville"
    return None

def _parse_travelers_csv(csv: str) -> List[int]:
    return [int(p) for p in str(csv or "").split(",") if p.strip().isdigit()]

def _collect_travelers(booking) -> List[Dict[str, Any]]:
    """Вытягиваем пассажиров из CSV id → список словарей, сохраняя исходный порядок."""
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
    out: List[Dict[str, Any]] = []
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

def _build_common_ctx(booking) -> Dict[str, Any]:
    """Единая сборка контекста для шаблонов брони/аннуляции."""
    title_es = spanish_excursion_name(
        int(getattr(booking, "excursion_id", 0) or 0),
        getattr(booking, "excursion_title", "") or ""
    )

    title_bi_html  = compose_bilingual_title(getattr(booking, "excursion_title", ""), title_es, html=True)
    title_bi_plain = compose_bilingual_title(getattr(booking, "excursion_title", ""), title_es, html=False)

    return {
        "booking": {
            "title_es":           title_es,
            "excursion_title":    getattr(booking, "excursion_title", ""),  # fallback
            "title_bi_html":  title_bi_html,
            "title_bi_plain": title_bi_plain,
            "excursion_language": getattr(booking, "excursion_language", ""),
            "date":               (getattr(booking, "date", None).isoformat() if getattr(booking, "date", None) else ""),
            "company":            getattr(booking, "company", None),
            "booking_code":       getattr(booking, "booking_code", ""),
            "hotel_name":         getattr(booking, "hotel_name", ""),
            "room_number":        getattr(booking, "room_number", ""),
            "adults":             getattr(booking, "adults", 0),
            "children":           getattr(booking, "children", 0),
            "infants":            getattr(booking, "infants", 0),
            "pickup_point_name":  getattr(booking, "pickup_point_name", ""),
            "pickup_time_str":    getattr(booking, "pickup_time_str", ""),
            "pickup_address":     getattr(booking, "pickup_address", ""),
            "pickup_lat":         getattr(booking, "pickup_lat", None),
            "pickup_lng":         getattr(booking, "pickup_lng", None),
            "maps_url":           _maps_url_for(booking),
        },
        "travelers":  _collect_travelers(booking),
        "special_key":_special_key(getattr(booking, "excursion_title", "")),
    }

# ---------------------------------------------------------------------------
# Отправка писем

def send_booking_email(booking, *, subject_prefix: str = "[SalesPortal]") -> bool:
    """
    Письмо-заявка/бронирование в офис партнёра.
    Возвращает True, если письмо успешно передано SMTP-бэкенду.
    """
    # Кому шлём
    to: List[str] = []
    company = getattr(booking, "company", None)
    comp_email = getattr(company, "email_for_orders", None)
    if comp_email:
        to.append(comp_email)

    fallback_to = getattr(settings, "BOOKINGS_FALLBACK_EMAIL", None)
    if not to and fallback_to:
        to.append(fallback_to)
    if not to:
        log.warning("send_booking_email: no recipients for booking_code=%s", getattr(booking, "booking_code", ""))
        return True  # не считаем ошибкой: просто некуда отправлять

    ctx = _build_common_ctx(booking)
    html = render_to_string("sales/email_reservation.html", ctx)
    text = strip_tags(html)

    title_es = ctx["booking"].get("title_es") or ctx["booking"].get("excursion_title") or ""
    when = _fmt_date(getattr(booking, "date", None))
    who = (getattr(getattr(booking, "company", None), "name", "")
           or getattr(getattr(booking, "guide", None), "get_full_name", lambda: "")()
           or "").strip() or "—"

    subject = f"{subject_prefix} Reserva de {who} — {title_es} — {when} — {getattr(booking, 'booking_code', '')}"
    subject = re.sub(r"\s+", " ", subject).strip()

    from_email = getattr(settings, "DEFAULT_FROM_EMAIL", "no-reply@example.com")
    msg = EmailMultiAlternatives(subject=subject, body=text, from_email=from_email, to=to)
    msg.attach_alternative(html, "text/html")

    try:
        sent = msg.send(fail_silently=False)
        return bool(sent)
    except Exception:
        log.exception("send_booking_email failed for booking_code=%s", getattr(booking, "booking_code", ""))
        return False


def send_cancellation_email(booking, reason: str = "", *, subject_prefix: str = "[SalesPortal]") -> bool:
    """
    Письмо-Аннуляция в офис партнёра.
    """
    to: List[str] = []
    company = getattr(booking, "company", None)
    comp_email = getattr(company, "email_for_orders", None)
    if comp_email:
        to.append(comp_email)

    fallback_to = getattr(settings, "BOOKINGS_FALLBACK_EMAIL", None)
    if not to and fallback_to:
        to.append(fallback_to)
    if not to:
        log.warning("send_cancellation_email: no recipients for booking_code=%s", getattr(booking, "booking_code", ""))
        return True

    ctx = _build_common_ctx(booking)
    ctx["reason"] = reason or ""

    title_es = ctx["booking"].get("title_es") or ctx["booking"].get("excursion_title") or ""
    when = _fmt_date(getattr(booking, "date", None))
    comp_or_guide = (getattr(getattr(booking, "company", None), "name", None)
                     or getattr(getattr(booking, "guide", None), "get_full_name", lambda: "")()
                     or "—")

    subject = f"{subject_prefix} Cancelación — Reserva de {comp_or_guide}: {title_es} · {when} · {getattr(booking, 'booking_code', '')}"
    subject = re.sub(r"\s+", " ", subject).strip()

    html = render_to_string("sales/email_cancellation.html", ctx)
    text = strip_tags(html)
    from_email = getattr(settings, "DEFAULT_FROM_EMAIL", "no-reply@example.com")

    msg = EmailMultiAlternatives(subject=subject, body=text, from_email=from_email, to=to)
    msg.attach_alternative(html, "text/html")
    try:
        return bool(msg.send(fail_silently=False))
    except Exception:
        log.exception("send_cancellation_email failed for booking_code=%s", getattr(booking, "booking_code", ""))
        return False
