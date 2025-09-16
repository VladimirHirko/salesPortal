# sales/services/costasolinfo.py
from __future__ import annotations
from dataclasses import dataclass
import logging
import requests
from urllib.parse import urljoin
from django.conf import settings
from django.core.cache import cache
from typing import Any, Dict, List, Optional

log = logging.getLogger(__name__)

def _base():
    base = getattr(settings, "CSI_API_BASE", None)
    if not base:
        raise RuntimeError("CSI_API_BASE is not configured. Check .env and settings.py")
    return base.rstrip("/") + "/"

def _get(path: str, params: dict | None = None, cache_key: str | None = None):
    """
    Универсальный GET с таймаутом, простым кэшированием и безопасными ошибками.
    """
    url = urljoin(_base(), path.lstrip("/"))
    key = cache_key or f"csi::{path}::{sorted(params.items()) if params else ''}"
    cached = cache.get(key)
    if cached is not None:
        return cached

    try:
        resp = requests.get(url, params=params, timeout=settings.CSI_HTTP_TIMEOUT)
        resp.raise_for_status()
        data = resp.json()
        cache.set(key, data, timeout=settings.CSI_CACHE_SECONDS)
        return data
    except requests.RequestException as e:
        log.exception("CSI GET failed: %s %s", url, e)
        # Возвращаем предыдущее кэш-значение, если есть
        if cached:
            return cached
        # Фоллбек, чтобы UI не падал
        return {"error": "unavailable", "items": []}

# ==== Конкретные «обёртки» под текущие эндпоинты CostaSolinfo ====

def search_hotels(query: str, limit: int = 10):
    # Пример из твоих тестов: /api/hotels/?search=mar
    params = {"search": query, "limit": limit}
    return _get("hotels/", params, cache_key=f"hotels::{query}::{limit}")

def transfer_schedule(hotel_id: int, date: str, type_: str = "group"):
    # Из твоих проверок: /api/transfer-schedule/?hotel_id=1&date=YYYY-MM-DD&type=group
    params = {"hotel_id": hotel_id, "date": date, "type": type_}
    return _get("transfer-schedule/", params)

def transfer_content(slug: str, lang: str = "ru"):
    # Примеры: transfer-content/transfer_home/?lang=ru
    params = {"lang": lang}
    return _get(f"transfer-content/{slug}/", params)

# Заглушки под экскурсии/прайсинг — подстроим под существующие эндпоинты,
# если у тебя уже есть /api/excursions/ и т.д.
def list_excursions(lang: str = "ru", date: str | None = None, region: str | None = None):
    params = {"lang": lang}
    if date: params["date"] = date
    if region: params["region"] = region
    return _get("excursions/", params)

def excursion_detail(excursion_id: int, lang: str = "ru"):
    """
    Вернёт объект экскурсии (минимум: title / localized_title),
    чтобы можно было отдать excursion_title в Sales-API.
    """
    params = {"lang": lang}
    return _get(f"excursions/{excursion_id}/", params)

def excursion_title(excursion_id: int, lang: str = "ru") -> str:
    data = excursion_detail(excursion_id, lang) or {}
    return (data.get("localized_title")
            or data.get("title")
            or "")

@dataclass
class PickupItem:
    id: int
    point: str
    time: Optional[str]  # "HH:MM" or None
    lat: Optional[float] = None
    lng: Optional[float] = None
    direction: Optional[str] = None  # e.g. "to_gibraltar" / "to_malaga"


class CSIClient:
    def __init__(self,
                 base: Optional[str] = None,
                 timeout: Optional[float] = None,
                 cache_seconds: Optional[int] = None):
        self.base = (base or getattr(settings, "CSI_API_BASE", "")).rstrip("/")
        self.timeout = timeout or getattr(settings, "CSI_HTTP_TIMEOUT", 8.0)
        self.cache_seconds = cache_seconds if cache_seconds is not None else getattr(settings, "CSI_CACHE_SECONDS", 60)

    # --- internal helpers -------------------------------------------------
    def _get_json(self, url: str, params: Dict[str, Any] | None = None) -> Any:
        resp = requests.get(url, params=params or {}, timeout=self.timeout)
        resp.raise_for_status()
        return resp.json()

    def excursion_title(self, excursion_id: int, lang: str = "ru") -> str | None:
        """
        Берём название экскурсии c CostaSolinfo.
        Пробуем детальный эндпоинт: /api/excursions/{id}/
        """
        if not self.base:
            return None
        try:
            url = f"{self.base}/excursions/{excursion_id}/"
            data = self._get_json(url, params={"lang": lang})
            # разные сериализаторы могут отдавать разные ключи — подстрахуемся
            return (data.get("title")
                    or data.get("localized_title")
                    or data.get("name"))
        except Exception:
            return None

    def _normalize_time(self, value: Any) -> Optional[str]:
        """Return HH:MM if possible; otherwise None."""
        if not value:
            return None
        s = str(value).strip()
        # Accept formats like HH:MM, HH:MM:SS, or "07.30"
        s = s.replace(".", ":")
        parts = s.split(":")
        if len(parts) >= 2 and parts[0].isdigit() and parts[1].isdigit():
            hh = int(parts[0])
            mm = int(parts[1])
            if 0 <= hh <= 23 and 0 <= mm <= 59:
                return f"{hh:02d}:{mm:02d}"
        return None

    def _normalize_pickup(self, raw: Dict[str, Any]) -> PickupItem:
        # Try common keys from CostaSolinfo
        pid = raw.get("id") or raw.get("pk") or raw.get("pickup_id")
        point = raw.get("point") or raw.get("name") or raw.get("pickup_point") or "Pickup"
        time_val = raw.get("time") or raw.get("pickup_time") or raw.get("departure")
        lat = raw.get("lat") or raw.get("latitude")
        lng = raw.get("lng") or raw.get("longitude")
        direction = raw.get("direction")
        try:
            pid = int(pid) if pid is not None else 0
        except Exception:
            pid = 0
        return PickupItem(
            id=pid,
            point=str(point).strip(),
            time=self._normalize_time(time_val),
            lat=float(lat) if lat is not None else None,
            lng=float(lng) if lng is not None else None,
            direction=str(direction) if direction else None,
        )

    # --- public API -------------------------------------------------------
    def excursion_pickup(self, excursion_id: int, hotel_id: int) -> dict | None:
        """
        Берём точку сбора для конкретной экскурсии и отеля
        с CostaSolinfo: /api/excursions/{id}/pickup/?hotel_id=...
        И дополняем полем excursion_title.
        """
        if not self.base:
            raise RuntimeError("CSI_API_BASE is not configured")

        # основной эндпоинт (соответствует твоему core.urls в CostaSolinfo)
        pickup_url = f"{self.base}/excursions/{excursion_id}/pickup/"
        try:
            raw = self._get_json(pickup_url, params={"hotel_id": hotel_id})
            # ожидаемый формат см. твой excursion_pickup_view в core: { id, name, lat, lng, time, price_* }
            if not isinstance(raw, dict) or ("id" not in raw and "name" not in raw):
                return None

            # нормализуем типы
            item = {
                "id": raw.get("id"),
                "name": raw.get("name"),
                "lat": float(raw["lat"]) if raw.get("lat") is not None else None,
                "lng": float(raw["lng"]) if raw.get("lng") is not None else None,
                "time": raw.get("time"),  # "HH:MM" or None
                "price_adult": raw.get("price_adult"),
                "price_child": raw.get("price_child"),
            }

            # подтянем название экскурсии (без panics, если не вышло)
            title = self.excursion_title(excursion_id, lang=getattr(settings, "LANGUAGE_CODE", "ru"))
            if title:
                item["excursion_title"] = title

            return item
        except requests.HTTPError as e:
            # 404 — точки нет
            if e.response is not None and e.response.status_code == 404:
                return None
            raise


# Factory (single place to construct client)
_client: Optional[CSIClient] = None

def get_client() -> CSIClient:
    global _client
    if _client is None:
        _client = CSIClient()
    return _client

def excursion_pickups(excursion_id: int, hotel_id: Optional[int], date: str):
    return get_client().excursion_pickups(
        excursion_id=excursion_id,
        hotel_id=hotel_id,
        date=date,
    )

def excursion_pickup(excursion_id: int, hotel_id: int):
    return get_client().excursion_pickup(excursion_id, hotel_id)


def excursion_pickup_once(excursion_id: int, hotel_id: int) -> dict | None:
    """
    Возвращает одну точку сбора для пары (excursion, hotel) или None.
    """
    url = urljoin(_base(), f"excursions/{excursion_id}/pickup/")
    try:
        data = requests.get(
            url,
            params={"hotel_id": hotel_id},
            timeout=settings.CSI_HTTP_TIMEOUT
        )
        if data.status_code == 404:
            return None
        data.raise_for_status()
        return data.json()
    except requests.RequestException:
        log.exception("CSI excursion_pickup_once failed: %s", url)
        return None

def pricing_quote(excursion_id: int, adults: int, children: int, infants: int,
                  region: str | None = None, company_id: int | None = None, lang: str = "ru"):
    """
    Черновой расчёт на нашей стороне.
    Если в старом API есть котировки — можно делать HTTP-запрос туда,
    а пока считаем локально по данным экскурсии (когда подключим).
    """
    # Мини-заглушка: всё нули, чтобы фронт не падал (реальную формулу подключим позже).
    return {
        "gross": 0.0,
        "net": 0.0,
        "commission": 0.0,
        "currency": "EUR",
        "details": {"excursion_id": excursion_id, "adults": adults, "children": children, "infants": infants, "region": region, "company_id": company_id, "lang": lang},
    }
