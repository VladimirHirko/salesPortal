# sales/services/costasolinfo.py
from __future__ import annotations

from dataclasses import dataclass
import logging
import requests
from decimal import Decimal, ROUND_HALF_UP
from typing import Any, Dict, Optional, List

import requests
from urllib.parse import urljoin, quote_plus
from django.conf import settings
from django.core.cache import cache

log = logging.getLogger(__name__)


def _money(x) -> float:
    return float(Decimal(str(x or 0)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))

def _normalize_region_obj(raw: dict | None) -> dict | None:
    if not raw:
        return None
    rid = raw.get("id")
    rslug = raw.get("slug") or raw.get("code") or raw.get("name")
    return {"id": rid, "slug": rslug} if (rid or rslug) else None

def _hotel_region(hotel_id: int) -> dict | None:
    data = _get(f"/hotels/{hotel_id}/", allow_404=True)
    if not data:
        return None
    # 1) вложенный объект region
    r = data.get("region")
    norm = _normalize_region_obj(r) if isinstance(r, dict) else None
    if norm:
        return norm
    # 2) плоское поле region_id
    rid = data.get("region_id")
    if rid is not None:
        return {"id": rid, "slug": None}
    # 3) иногда по другому называется
    for key in ("area", "zone", "resort"):
        r2 = data.get(key)
        if isinstance(r2, dict):
            norm = _normalize_region_obj(r2)
            if norm:
                return norm
    return None

def _pick_first(*values):
    for v in values:
        if v is not None:
            return v
    return None

def _extract_price_row(row: dict) -> tuple[float, float, str] | None:
    # поддержим разные имена полей
    a = _pick_first(row.get("adult"), row.get("adult_price"), row.get("price_adult"), row.get("adultGross"))
    c = _pick_first(row.get("child"), row.get("child_price"), row.get("price_child"), row.get("childGross"))
    cur = _pick_first(row.get("currency"), row.get("curr"))
    if a is None and c is None:
        return None
    if c is None:
        c = a
    return _money(a), _money(c), (cur or "EUR")

def _excursion_price_for_region(excursion_id: int, region: dict | None) -> tuple[float, float, str] | None:
    detail = _get(f"/excursions/{excursion_id}/", allow_404=True)
    if not detail:
        return None

    # A) prices_by_region: [ {region:{id/slug}, adult/child/currency} ]
    pbr = detail.get("prices_by_region") or detail.get("pricesByRegion") or detail.get("region_prices")
    if isinstance(pbr, list) and region:
        rid = region.get("id")
        rslug = (region.get("slug") or "").lower() if region.get("slug") else None
        for row in pbr:
            r = row.get("region") or {}
            if (rid and r.get("id") == rid) or (rslug and (str(r.get("slug") or "").lower() == rslug)):
                got = _extract_price_row(row)
                if got:
                    return got

    # B) Табличные структуры: {"prices":[{"region":...,"adult_price":...},...]} или {"tariffs":[...]}
    for key in ("prices", "tariffs", "pricing", "price_table"):
        arr = detail.get(key)
        if isinstance(arr, list) and region:
            rid = region.get("id")
            rslug = (region.get("slug") or "").lower() if region.get("slug") else None
            for row in arr:
                r = row.get("region") or {}
                if (rid and r.get("id") == rid) or (rslug and (str(r.get("slug") or "").lower() == rslug)):
                    got = _extract_price_row(row)
                    if got:
                        return got

    # C) Поля вида adult_price_{slug}/child_price_{slug}
    if region and region.get("slug"):
        slug = str(region["slug"]).lower()
        a = detail.get(f"adult_price_{slug}")
        c = detail.get(f"child_price_{slug}")
        if a is not None or c is not None:
            a2 = _money(a if a is not None else c)
            c2 = _money(c if c is not None else a)
            return a2, c2, detail.get("currency", "EUR")

    # D) Базовые без регионов
    a = _pick_first(detail.get("adult_price"), detail.get("price_adult"))
    c = _pick_first(detail.get("child_price"), detail.get("price_child"))
    if a is not None or c is not None:
        a2 = _money(a if a is not None else c)
        c2 = _money(c if c is not None else a)
        return a2, c2, detail.get("currency", "EUR")

    return None



def _base() -> str:
    base = getattr(settings, "CSI_API_BASE", None)
    if not base:
        raise RuntimeError("CSI_API_BASE is not configured. Check .env and settings.py")
    return base.rstrip("/") + "/"


def _get(
    path: str,
    params: Optional[Dict[str, Any]] = None,
    cache_key: Optional[str] = None,
    *,
    cache_seconds: Optional[int] = None,
    allow_404: bool = False,
    timeout: Optional[float] = None,
) -> Any:
    """
    Универсальный GET с таймаутом, кэшированием и аккуратной обработкой ошибок.

    - allow_404=True → 404 не считается ошибкой, возвращаем None
    - cache_seconds: если не задан, используем settings.CSI_CACHE_SECONDS
    - timeout: если не задан, используем settings.CSI_HTTP_TIMEOUT
    """
    url = urljoin(_base(), path.lstrip("/"))

    # аккуратно собираем ключ кэша
    if cache_key:
        key = cache_key
    else:
        params_tuple = tuple(sorted((params or {}).items()))
        key = f"csi::{path}::{params_tuple}"

    cached = cache.get(key)
    if cached is not None:
        return cached

    try:
        resp = requests.get(url, params=params, timeout=timeout or settings.CSI_HTTP_TIMEOUT)

        # мягкая обработка 404 по флагу
        if resp.status_code == 404 and allow_404:
            return None

        resp.raise_for_status()

        try:
            data = resp.json()
        except ValueError:
            # неожиданно не-JSON ответ
            log.exception("CSI GET non-JSON response: %s", url)
            data = {"error": "bad_json"}

        cache.set(key, data, timeout=cache_seconds if cache_seconds is not None else settings.CSI_CACHE_SECONDS)
        return data

    except requests.RequestException as e:
        log.exception("CSI GET failed: %s %s", url, e)
        # если был кэш — его уже вернули выше; здесь возвращаем «мягкую» заглушку
        return {"error": "unavailable", "items": []}


# ==== Конкретные «обёртки» под текущие эндпоинты CostaSolinfo ====

def search_hotels(q: str, limit: int = 10):
    safe_q = quote_plus(q or "")
    cache_key = f"hotels:{safe_q}:{limit}"
    cached = cache.get(cache_key)
    if cached is not None:
        return cached

    try:
        url = urljoin(_base(), "hotels/")
        resp = requests.get(url, params={"search": q, "limit": limit}, timeout=settings.CSI_HTTP_TIMEOUT)
        resp.raise_for_status()
        data = resp.json()
    except requests.RequestException:
        log.exception("CSI search_hotels failed")
        data = {"items": []}

    cache.set(cache_key, data, timeout=60)
    return data


def transfer_schedule(hotel_id: int, date: str, type_: str = "group"):
    params = {"hotel_id": hotel_id, "date": date, "type": type_}
    return _get("transfer-schedule/", params)


def transfer_content(slug: str, lang: str = "ru"):
    params = {"lang": lang}
    return _get(f"transfer-content/{slug}/", params)


def list_excursions(lang: str = "ru", date: str | None = None, region: str | None = None):
    params = {"lang": lang}
    if date:
        params["date"] = date
    if region:
        params["region"] = region
    return _get("excursions/", params)


def excursion_detail(excursion_id: int, lang: str = "ru"):
    params = {"lang": lang}
    return _get(f"excursions/{excursion_id}/", params)


def excursion_title(excursion_id: int, lang: str = "ru") -> str:
    data = excursion_detail(excursion_id, lang) or {}
    return data.get("localized_title") or data.get("title") or ""


@dataclass
class PickupItem:
    id: int
    point: str
    time: Optional[str]  # "HH:MM" or None
    lat: Optional[float] = None
    lng: Optional[float] = None
    direction: Optional[str] = None  # e.g. "to_gibraltar" / "to_malaga"


def _num(x, default=None):
    try:
        if x is None:
            return default
        return float(x)
    except Exception:
        return default

def _pick(raw, *names, cast=float):
    """Достаёт первое непустое поле из списка имён и приводит тип."""
    for n in names:
        if n in raw and raw[n] is not None:
            try:
                return cast(raw[n])
            except Exception:
                try:
                    return cast(str(raw[n]).replace(',', '.'))
                except Exception:
                    return None
    return None

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
        if not self.base:
            return None
        try:
            url = f"{self.base}/excursions/{excursion_id}/"
            data = self._get_json(url, params={"lang": lang})
            return data.get("title") or data.get("localized_title") or data.get("name")
        except Exception:
            return None

    def _normalize_time(self, value: Any) -> Optional[str]:
        """Return HH:MM if possible; otherwise None."""
        if not value:
            return None
        s = str(value).strip().replace(".", ":")
        parts = s.split(":")
        if len(parts) >= 2 and parts[0].isdigit() and parts[1].isdigit():
            hh = int(parts[0])
            mm = int(parts[1])
            if 0 <= hh <= 23 and 0 <= mm <= 59:
                return f"{hh:02d}:{mm:02d}"
        return None

    def _normalize_pickup(self, raw: Dict[str, Any]) -> PickupItem:
        pid = raw.get("id") or raw.get("pk") or raw.get("pickup_id")
        point = raw.get("point") or raw.get("name") or raw.get("pickup_point") or "Pickup"

        time_val = raw.get("time") or raw.get("pickup_time") or raw.get("departure")
        lat = raw.get("lat") or raw.get("latitude")
        lng = raw.get("lng") or raw.get("longitude")
        direction = raw.get("direction")

        # ← новые варианты названий полей с ценами
        price_adult = _pick(
            raw,
            "price_adult", "adult_price", "price_adult_eur", "priceA", "price", "adult",
            cast=float
        )
        price_child = _pick(
            raw,
            "price_child", "child_price", "price_child_eur", "priceC", "child",
            cast=float
        )

        try:
            pid = int(pid) if pid is not None else 0
        except Exception:
            pid = 0

        item = PickupItem(
            id=pid,
            point=str(point).strip(),
            time=self._normalize_time(time_val),
            lat=float(lat) if lat is not None else None,
            lng=float(lng) if lng is not None else None,
            direction=str(direction) if direction else None,
        )
        # положим как атрибуты, чтобы их увидел pricing_quote
        item.price_adult = price_adult
        item.price_child = price_child
        return item

    # --- public API -------------------------------------------------------
    def excursion_pickup(self, excursion_id: int, hotel_id: int) -> dict | None:
        if not self.base:
            raise RuntimeError("CSI_API_BASE is not configured")

        pickup_url = f"{self.base}/excursions/{excursion_id}/pickup/"
        try:
            raw = self._get_json(pickup_url, params={"hotel_id": hotel_id})
            if not isinstance(raw, dict) or ("id" not in raw and "name" not in raw):
                return None

            item = {
                "id": raw.get("id"),
                "name": raw.get("name"),
                "lat": float(raw["lat"]) if raw.get("lat") is not None else None,
                "lng": float(raw["lng"]) if raw.get("lng") is not None else None,
                "time": raw.get("time"),
                "price_adult": _pick(raw, "price_adult", "adult_price", "price_adult_eur", "priceA", "price", "adult"),
                "price_child": _pick(raw, "price_child", "child_price", "price_child_eur", "priceC", "child"),
            }

            title = self.excursion_title(excursion_id, lang=getattr(settings, "LANGUAGE_CODE", "ru"))
            if title:
                item["excursion_title"] = title

            return item
        except requests.HTTPError as e:
            if e.response is not None and e.response.status_code == 404:
                return None
            raise

    def excursion_pickups(self, excursion_id: int, hotel_id: Optional[int], date: str) -> List[Dict[str, Any]]:
        """
        Эмулируем список пикапов на дату. Сейчас источник отдаёт одну точку для (excursion, hotel).
        """
        if not hotel_id:
            return []
        one = self.excursion_pickup(excursion_id, hotel_id)
        if not one:
            return []
        return [{
            "id": one.get("id"),
            "point": one.get("name") or one.get("point") or "Pickup",
            "time": one.get("time"),
            "lat": one.get("lat"),
            "lng": one.get("lng"),
            "direction": one.get("direction"),
            "price_adult": one.get("price_adult"),
            "price_child": one.get("price_child"),
        }]

    # --- pricing -----------------------------------------------------------
    def excursion_pricing(self,
                          excursion_id: int,
                          adults: int,
                          children: int,
                          infants: int,
                          region: str | None = None,
                          company_id: int | None = None,
                          lang: str = "ru") -> dict:
        """
        Тянем котировку из основной базы.
        Пробуем основной эндпоинт /api/excursions/{id}/pricing/,
        а затем несколько запасных вариантов. Возвращаем нормализованный dict.
        """
        if not self.base:
            raise RuntimeError("CSI_API_BASE is not configured")

        params = {
            "adults": adults,
            "children": children,
            "infants": infants,
            "lang": lang
        }
        if region:
            params["region"] = region
        if company_id is not None:
            params["company_id"] = company_id

        # список возможных url (на случай, если в старой админке другой роут)
        candidates = [
            f"{self.base}/excursions/{excursion_id}/pricing/",
            f"{self.base}/excursions/{excursion_id}/quote/",
            f"{self.base}/excursions/{excursion_id}/price/",
        ]

        data = None
        last_exc = None
        for url in candidates:
            try:
                data = self._get_json(url, params=params)
                break
            except requests.HTTPError as e:
                last_exc = e
                # если 404 — пробуем следующий кандидат
                if e.response is not None and e.response.status_code == 404:
                    continue
                else:
                    raise
            except Exception as e:
                last_exc = e
                continue

        if data is None:
            # ничего не нашли — мягкий фолбэк
            return {
                "ok": False,
                "gross": 0.0,
                "currency": "EUR",
                "net": None,
                "commission": None,
                "per_adult": None,
                "per_child": None,
                "raw": {"error": str(last_exc) if last_exc else "no-data"}
            }

        # разные сериализаторы отдают разные ключи — аккуратно вытащим общие поля
        currency = (data.get("currency")
                    or data.get("curr")
                    or data.get("code")
                    or "EUR")

        gross = (_num(data.get("gross"))
                 or _num(data.get("total"))
                 or _num(data.get("price_total"))
                 or 0.0)

        net = (_num(data.get("net"))
               or _num(data.get("netto"))
               or None)

        commission = (_num(data.get("commission"))
                      or _num(data.get("comm"))
                      or (gross - net if (gross is not None and net is not None) else None))

        per_adult = (_num(data.get("price_adult"))
                     or _num(data.get("adult_price"))
                     or None)

        per_child = (_num(data.get("price_child"))
                     or _num(data.get("child_price"))
                     or None)

        return {
            "ok": True if gross else False,
            "gross": float(gross or 0.0),
            "currency": str(currency),
            "net": net,
            "commission": commission,
            "per_adult": per_adult,
            "per_child": per_child,
            "raw": data,  # полезно для отладки в DEV
        }


# --- модульные врапперы -----------------------------------------------------

class NotFoundError(Exception):
    pass

def _to_money(x) -> float:
    if x is None:
        return 0.0
    d = Decimal(str(x)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return float(d)

def pricing_quote(
    excursion_id: int,
    adults: int,
    children: int,
    infants: int,
    lang: str | None = None,
    hotel_id: int | None = None,
    hotel_name: str | None = None,
    date: str | None = None,
    region_override: dict | None = None,
    **_
) -> dict:
    """
    Возвращает {"gross": float, "currency": "EUR", "meta": {...}}.
    Порядок: (1) CSI-котировщик → (2) PICKUP v2 → (3) REGION.
    """

    # 1) Попытка через CSI (если когда-нибудь появится рабочая ручка)
    try:
        data = _get(
            f"/excursions/{excursion_id}/pricing/",
            params={
                "adults": adults,
                "children": children,
                "infants": infants,
                "lang": lang or "ru",
                "hotel_id": hotel_id,
                "date": date,
            },
            allow_404=True,
        )
        if isinstance(data, dict) and "gross" in data:
            return {
                "gross": _money(data.get("gross")),
                "currency": data.get("currency", "EUR"),
                "meta": {
                    "adult_price": _money((data.get("breakdown") or {}).get("adult_price")),
                    "child_price": _money((data.get("breakdown") or {}).get("child_price")),
                    "source": "CSI",
                    "excursion_id": excursion_id,
                    "hotel_id": hotel_id,
                    "date": date,
                },
            }
    except Exception:
        pass

    # 2) PICKUP v2: считаем из цены точки сбора на конкретную дату
    try:
        pickups = get_client().excursion_pickups(
            excursion_id=excursion_id,
            hotel_id=hotel_id,
            date=date or "",
        )
    except Exception:
        pickups = []

    if pickups:
        p = pickups[0]
        adult_price = _money(p.get("price_adult"))
        child_price = _money(p.get("price_child") if p.get("price_child") is not None else adult_price)
        gross = _money(adult_price * adults + child_price * children)
        return {
            "gross": gross,
            "currency": p.get("currency") or "EUR",
            "meta": {
                "adult_price": adult_price,
                "child_price": child_price,
                "source": "PICKUP",
                "excursion_id": excursion_id,
                "hotel_id": hotel_id,
                "date": date,
            },
        }

    # 3) REGION-фолбэк: берём цены экскурсии для региона отеля (или оверрайд)
    if region_override and (region_override.get("id") or region_override.get("slug")):
        region = {"id": region_override.get("id"), "slug": region_override.get("slug")}
    elif hotel_id:
        region = _hotel_region(hotel_id)
    else:
        region = None

    prices = _excursion_price_for_region(excursion_id, region)
    if prices:
        a, c, cur = prices
        gross = _money(a * adults + c * children)
        return {
            "gross": gross,
            "currency": cur or "EUR",
            "meta": {
                "adult_price": _money(a),
                "child_price": _money(c),
                "source": "REGION",
                "region": region,
                "excursion_id": excursion_id,
                "hotel_id": hotel_id,
                "date": date,
            },
        }

    raise NotFoundError("Pricing not available (no pickup and no CSI quote).")


# Factory (single place to construct client)
_client: Optional[CSIClient] = None


def get_client() -> CSIClient:
    global _client
    if _client is None:
        _client = CSIClient()
    return _client


def excursion_pickups(excursion_id: int, hotel_id: Optional[int], date: str):
    return get_client().excursion_pickups(excursion_id=excursion_id, hotel_id=hotel_id, date=date)


def excursion_pickup(excursion_id: int, hotel_id: int):
    return get_client().excursion_pickup(excursion_id, hotel_id)


def excursion_pickup_once(excursion_id: int, hotel_id: int) -> dict | None:
    """Возвращает одну точку сбора для пары (excursion, hotel) или None.
    Нормализует поля цен в ключи price_adult / price_child (float)."""
    url = urljoin(_base(), f"excursions/{excursion_id}/pickup/")
    try:
        resp = requests.get(
            url,
            params={"hotel_id": hotel_id},
            timeout=settings.CSI_HTTP_TIMEOUT,
        )
        if resp.status_code == 404:
            return None
        resp.raise_for_status()
        data = resp.json()
        if not isinstance(data, dict):
            return None

        def _num(v):
            if v is None or v == "":
                return None
            try:
                return float(v)
            except Exception:
                try:
                    return float(str(v).replace(",", "."))
                except Exception:
                    return None

        def _pick(raw, *names):
            for n in names:
                if n in raw and raw[n] not in (None, ""):
                    val = _num(raw[n])
                    if val is not None:
                        return val
            return None

        # Нормализуем цены к единому виду
        pa = _pick(data, "price_adult", "adult_price", "price_adult_eur", "priceA", "price", "adult")
        pc = _pick(data, "price_child", "child_price", "price_child_eur", "priceC", "child")

        data["price_adult"] = pa
        data["price_child"] = pc

        return data

    except requests.RequestException:
        log.exception("CSI excursion_pickup_once failed: %s", url)
        return None



def _safe_float(x, default=None):
    try:
        if x is None: return default
        return float(x)
    except Exception:
        return default

