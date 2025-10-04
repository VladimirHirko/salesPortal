# sales/views_api.py
from collections import defaultdict
from datetime import date
import datetime as dt
from django.utils import timezone
from django.db import transaction
from rest_framework.parsers import JSONParser
from sales.services.emails import send_booking_email
from sales.services.titles import excursion_title_es
from sales.services.emails import send_cancellation_email

from django.db.models import Q
from django.core.exceptions import FieldError   # ← ДОБАВИТЬ
from django.conf import settings
from django.contrib.auth import get_user_model
from django.shortcuts import render, get_object_or_404
from django.http import JsonResponse
from django.views.decorators.http import require_GET
from django.views.decorators.csrf import csrf_exempt
from django.utils.dateparse import parse_date
from django.utils.decorators import method_decorator
from django.views.decorators.cache import never_cache
from sales.services.costasolinfo import NotFoundError
from .services import costasolinfo as csi
from .services.costasolinfo import get_client, pricing_quote
from rest_framework.response import Response
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.decorators import api_view, permission_classes, authentication_classes
from rest_framework.generics import RetrieveAPIView
from rest_framework.views import APIView
from rest_framework import status, viewsets
from .models import FamilyBooking, Traveler, Company, BookingSale
from django.apps import apps
from .serializers import (
    CompanySerializer,
    BookingSaleCreateSerializer,
    BookingSaleListSerializer,
    TravelerMiniSerializer,      # понадобится, если решишь оставить FBV
    FamilyDetailSerializer,
    BookingSaleDetailSerializer,      # для CBV
)

import re, html
import requests
import logging
import inspect

WEEKDAYS = ["mon","tue","wed","thu","fri","sat","sun"]

FamilyBooking = apps.get_model('sales', 'FamilyBooking')

class BookingSaleViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = BookingSale.objects.all()

    def get_serializer_class(self):
        # список -> краткий; деталка -> детальный
        if self.action == "retrieve":
            return BookingSaleDetailSerializer
        return BookingSaleListSerializer

class FamilyDetailView(RetrieveAPIView):
    queryset = FamilyBooking.objects.all()   # без prefetch_related('party')
    serializer_class = FamilyDetailSerializer
    permission_classes = [AllowAny]


def _booking_to_json(b: BookingSale) -> dict:
    return {
        "id": b.id,
        "booking_code": b.booking_code,
        "status": b.status,
        "family_id": getattr(b, "family_id", None),   # ← ДОБАВИЛИ
        "date": b.date.isoformat() if b.date else None,
        "excursion_id": b.excursion_id,
        "excursion_title": b.excursion_title,
        "hotel_id": b.hotel_id,
        "hotel_name": b.hotel_name,
        "region_name": getattr(b, "region_name", "") or "",
        "pickup_point_id": b.pickup_point_id,
        "pickup_point_name": b.pickup_point_name,
        "pickup_time_str": b.pickup_time_str,
        "pickup_lat": getattr(b, "pickup_lat", None),
        "pickup_lng": getattr(b, "pickup_lng", None),
        "pickup_address": getattr(b, "pickup_address", ""),
        "excursion_language": getattr(b, "excursion_language", None),
        "room_number": getattr(b, "room_number", ""),
        "adults": b.adults,
        "children": b.children,
        "infants": b.infants,
        "price_source": getattr(b, "price_source", "PICKUP"),
        "price_per_adult": str(getattr(b, "price_per_adult", 0) or 0),
        "price_per_child": str(getattr(b, "price_per_child", 0) or 0),
        "gross_total": str(b.gross_total or 0),
        "net_total": str(getattr(b, "net_total", 0) or 0),
        "commission": str(getattr(b, "commission", 0) or 0),
        "created_at": b.created_at.isoformat() if b.created_at else None,
        "is_sendable": b.status in ("DRAFT",),
        "is_sent": b.status in ("PENDING", "HOLD", "PAID", "CANCELLED", "EXPIRED"),
    }


def _resolve_user(request):
    """ Dev-fallback: если нет аутентификации — берём первого активного. """
    u = getattr(request, "user", None)
    if u and getattr(u, "is_authenticated", False):
        return u
    User = get_user_model()
    return (
        User.objects.filter(is_active=True)
        .order_by("-is_superuser", "-is_staff", "id")
        .first()
    )

def _normalize_name(s: str) -> str:
    """Убираем лишнее и приводим к нижнему регистру для сравнения."""
    s = (s or "").strip().lower()
    s = re.sub(r"\s+", " ", s)
    return s

def _resolve_hotel_id_by_name(hotel_name: str) -> int | None:
    """
    Ищет hotel_id в CSI по названию отеля.
    Приоритет: точное совпадение → начинается с → первый результат.
    """
    if not hotel_name:
        return None

    try:
        res = csi.search_hotels(hotel_name, limit=10)
        items = res if isinstance(res, list) else (res.get("items") or [])
        if not items:
            return None

        target = _normalize_name(hotel_name)
        # 1) точное совпадение
        for it in items:
            name = _normalize_name(it.get("name") or it.get("title") or "")
            if name == target:
                return int(it.get("id"))

        # 2) начинается с
        for it in items:
            name = _normalize_name(it.get("name") or it.get("title") or "")
            if name.startswith(target) or target.startswith(name):
                return int(it.get("id"))

        # 3) первый адекватный
        for it in items:
            if it.get("id"):
                return int(it["id"])
    except Exception:
        pass
    return None

def _weekday_slug(date_str: str) -> str | None:
    # Делает парсер терпимым: обрезаем мусор, берём только YYYY-MM-DD
    try:
        s = (date_str or "").strip()[:10]
        d = dt.date.fromisoformat(s)
        return WEEKDAYS[d.weekday()]  # 0=mon ... 6=sun
    except Exception:
        return None


@api_view(["GET"])
@permission_classes([AllowAny])
def debug_hotel_region(request):
    """Показывает, какой регион видит CSI для данного hotel_id."""
    hotel_id_raw = request.GET.get("hotel_id")
    try:
        hotel_id = int(hotel_id_raw) if hotel_id_raw else None
    except ValueError:
        return JsonResponse({"detail": "hotel_id must be int"}, status=400)
    if not hotel_id:
        return JsonResponse({"detail": "hotel_id required"}, status=400)

    # импортируем только внутри функции, чтобы не ломать загрузку модуля
    try:
        from .services.costasolinfo import _hotel_region as svc_hotel_region
    except ImportError:
        return JsonResponse({"detail": "helper _hotel_region is not defined in costasolinfo.py"}, status=500)

    region = svc_hotel_region(hotel_id)
    return JsonResponse({"hotel_id": hotel_id, "region": region}, json_dumps_params={"ensure_ascii": False})


@api_view(["GET"])
@permission_classes([AllowAny])
def debug_excursion_prices(request):
    """Возвращает цены экскурсии по региону (adult/child/currency) для пары (excursion_id, region)."""
    try:
        excursion_id = int(request.GET.get("excursion_id"))
    except (TypeError, ValueError):
        return JsonResponse({"detail": "excursion_id required (int)"}, status=400)

    region_id = request.GET.get("region_id")
    region_slug = request.GET.get("region_slug")
    region = None
    if region_id or region_slug:
        try:
            region = {"id": int(region_id)} if region_id else {"id": None}
        except ValueError:
            return JsonResponse({"detail": "region_id must be int"}, status=400)
        if region_slug:
            region["slug"] = region_slug

    try:
        from .services.costasolinfo import _excursion_price_for_region as svc_ex_price_region
    except ImportError:
        return JsonResponse({"detail": "helper _excursion_price_for_region is not defined in costasolinfo.py"}, status=500)

    prices = svc_ex_price_region(excursion_id, region)
    return JsonResponse(
        {"excursion_id": excursion_id, "region": region, "prices": prices},
        json_dumps_params={"ensure_ascii": False},
    )

log = logging.getLogger(__name__)

_TAG_RE = re.compile(r"<[^>]+>")

def login_view(request): return JsonResponse({"ok": True})

def _csi_url(path: str) -> str:
    """Надёжно склеивает CSI_API_BASE и относительный путь."""
    base = getattr(settings, "CSI_API_BASE", "http://127.0.0.1:8000").rstrip("/")
    if base.endswith("/api"):
        return f"{base}/{path.lstrip('/')}"           # base уже с /api
    return f"{base}/api/{path.lstrip('/')}"           # добавим /api

@csrf_exempt
@api_view(["POST"])
@authentication_classes([])          # отключаем SessionAuthentication => не требует CSRF
@permission_classes([AllowAny])      # в деве позволим всем
def create_booking(request):
    # На этом шаге просто эхо-заглушка, чтобы проверить POST
    data = request.data or {}
    return Response({
        "status": "PENDING",
        "booking_code": "S-000001",
        "echo": data,                # вернём то, что прислали, для наглядности
    })

@api_view(["GET"])
def debug_csi_base(request):
    from django.conf import settings
    return Response({
        "CSI_API_MODE": settings.CSI_API_MODE,
        "CSI_API_BASE": settings.CSI_API_BASE,
        "timeout": settings.CSI_HTTP_TIMEOUT,
        "cache_sec": settings.CSI_CACHE_SECONDS,
    })

@api_view(["GET"])
@permission_classes([AllowAny])
def health(request):
    return Response({"status": "ok"})

def _via_client(query: str, limit: int) -> list:
    from .services import costasolinfo as csi
    data = csi.search_hotels(query, limit=limit)
    return data if isinstance(data, list) else (data.get("items") if isinstance(data, dict) else [])

def _via_proxy(query: str, limit: int) -> list:
    """
    Пробуем REST-эндпоинты источника:
    1) /api/hotels/?search=
    2) /api/available-hotels/?search=
    Возвращаем первый непустой результат.
    """
    for path in ("hotels/", "available-hotels/"):
        r = requests.get(_csi_url(path), params={"search": query, "limit": limit}, timeout=6)
        if r.ok:
            data = r.json()
            items = data if isinstance(data, list) else (data.get("items") if isinstance(data, dict) else [])
            if items:
                return items
    return []

@api_view(["GET"])
@permission_classes([AllowAny])
def hotels(request):
    """
    /api/sales/hotels/?q=best benalmadena   или   ?search=best benalmadena
    Возвращает {items:[...]}.
    Алгоритм: полная строка → последнее слово → первое слово;
    для каждой попытки: сначала через csi-клиент, затем прямой прокси.
    """
    q = (request.query_params.get("q") or request.query_params.get("search") or "").strip()
    if not q:
        return Response({"items": []})

    try:
        limit = int(request.query_params.get("limit", "10"))
    except ValueError:
        limit = 10

    attempts = [q]
    parts = [p for p in re.split(r"[\s,.;-]+", q) if p]
    if len(parts) > 1:
        attempts += [parts[-1], parts[0]]  # сначала «benalmadena», затем «best»

    for query in attempts:
        items = []
        # 1) через клиент
        try:
            items = _via_client(query, limit)
        except Exception:
            items = []
        # 2) фолбэк — прямые REST эндпоинты источника
        if not items:
            try:
                items = _via_proxy(query, limit)
            except Exception:
                items = []

        if items:
            _enrich_hotels(items)       # ← ДОБАВЛЕНО: подмешиваем счётчик
            return Response({"items": items})

    return Response({"items": []})


@api_view(["GET"])
@permission_classes([AllowAny])
def tourists(request):
    """
    /api/sales/tourists/?hotel_name=RIU%20COSTA%20DEL%20SOL&search=ivan
    Также понимает: ?hotel_id=... (зарезервировано), ?q=...
    Возвращает {items:[{ id, last_name, first_name, checkin, checkout, room, party:[...] }]}
    где party — все путешественники (Traveler) в рамках одной FamilyBooking.
    """
    # 1) входные параметры
    hotel_name = (request.query_params.get("hotel_name")
                  or request.query_params.get("hotel")
                  or "").strip()
    _ = request.query_params.get("hotel_id")  # пока не используем
    q = (request.query_params.get("search")
         or request.query_params.get("q")
         or "").strip()

    if not hotel_name:
        return Response({"items": []})

    # 2) модели
    from .models import FamilyBooking, Traveler

    # 3) все семейные брони по отелю (icontains — нечувствительно к регистру)
    fam_ids = list(
        FamilyBooking.objects
        .filter(hotel_name__icontains=hotel_name)
        .values_list("id", flat=True)
    )
    if not fam_ids:
        return Response({"items": []})

    # 4) выбираем путешественников этих семей
    trav_qs = Traveler.objects.filter(family_id__in=fam_ids)
    if q:
        trav_qs = trav_qs.filter(Q(last_name__icontains=q) | Q(first_name__icontains=q))

    # Берём только нужные поля и убираем дубликаты на уровне БД
    trav_rows = (
        trav_qs
        .values("id", "last_name", "first_name", "dob", "family_id")
        .order_by("family_id", "last_name", "first_name", "id")
        .distinct()
    )

    if not trav_rows:
        return Response({"items": []})

    # 5) группируем по family_id
    groups = defaultdict(list)
    for r in trav_rows:
        groups[r["family_id"]].append(r)

    fam_map = {
        f.id: f for f in FamilyBooking.objects.filter(id__in=groups.keys())
    }

    def is_child(dob):
        if not dob:
            return False
        try:
            today = date.today()
            age = today.year - dob.year - ((today.month, today.day) < (dob.month, dob.day))
            return age < 12
        except Exception:
            return False

    items = []
    for fam_id, members in groups.items():
        fam = fam_map.get(fam_id)
        head = members[0]  # первый по алфавиту
        party = [{
            "id": m["id"],
            "full_name": f'{m["last_name"]} {m["first_name"]}'.strip(),
            "is_child": is_child(m.get("dob")),
        } for m in members]

        items.append({
            "id": fam_id,  # id семейной брони — ключ карточки
            "last_name": head["last_name"],
            "first_name": head["first_name"],
            "checkin": (fam.arrival_date.isoformat() if getattr(fam, "arrival_date", None) else None),
            "checkout": (fam.departure_date.isoformat() if getattr(fam, "departure_date", None) else None),
            "room": "",  # комнат в модели нет — оставляем пусто
            "party": party,
        })

    # свежие заезды выше
    items.sort(key=lambda x: (x["checkin"] or ""), reverse=True)
    return Response({"items": items})

def _tourists_count_by_hotel_name(name: str) -> int:
    # считаем именно путешественников (distinct на случай задвоений)
    fam_ids = list(
        FamilyBooking.objects.filter(hotel_name__icontains=name)
        .values_list("id", flat=True)
    )
    if not fam_ids:
        return 0
    return (
        Traveler.objects.filter(family_id__in=fam_ids)
        .distinct()
        .count()
    )

def _enrich_hotels(items: list[dict]) -> list[dict]:
    # безопасно добавляем поле tourists_count к каждому отелю
    for it in items:
        name = (it.get("name") or it.get("title") or "").strip()
        it["tourists_count"] = _tourists_count_by_hotel_name(name) if name else 0
    return items


def _strip_html(s: str) -> str:
    if not s:
        return ""
    # 1) раскодировать HTML сущности (&mdash; и т.д.)
    s = html.unescape(s)
    # 2) убрать теги
    s = _TAG_RE.sub("", s)
    # 3) нормализовать пробелы
    return re.sub(r"\s+", " ", s).strip()

WEEKDAY_NUM_TO_CODE = {0:"mon",1:"tue",2:"wed",3:"thu",4:"fri",5:"sat",6:"sun"}
WEEKDAY_CODE_TO_NUM = {v:k for k,v in WEEKDAY_NUM_TO_CODE.items()}

def _is_child(birth_date):
    if not birth_date:
        return False
    today = date.today()
    age = today.year - birth_date.year - ((today.month, today.day) < (birth_date.month, birth_date.day))
    return age < 12

@api_view(["GET"])
@permission_classes([AllowAny])
def family_detail(request, fam_id: int):
    from .models import FamilyBooking, Traveler
    fam = get_object_or_404(FamilyBooking, pk=fam_id)

    def _iso(d):
        try:
            return d.isoformat() if d else None
        except Exception:
            return None

    party = []
    for t in Traveler.objects.filter(family=fam).order_by("last_name", "first_name"):
        party.append({
            "id": t.id,
            "first_name": t.first_name or "",
            "last_name":  t.last_name or "",
            "full_name":  f"{t.last_name or ''} {t.first_name or ''}".strip(),
            "is_child":   _is_child(t.dob),

            # ↓↓↓ ЭТИ ПОЛЯ НУЖНЫ ФРОНТУ ДЛЯ АВТО-ЗАПОЛНЕНИЯ ↓↓↓
            "dob":              _iso(getattr(t, "dob", None)),
            "nationality":      getattr(t, "nationality", "") or "",
            "passport":         getattr(t, "passport", "") or "",
            "passport_expiry":  _iso(getattr(t, "passport_expiry", None)),
            "gender":           getattr(t, "gender", "") or "",      # "M" / "F" / ""
            "doc_type":         getattr(t, "doc_type", "") or "",     # "passport" / "dni" / ""
            "doc_expiry":       _iso(getattr(t, "doc_expiry", None)),
            "email":            getattr(t, "email", "") or "",
            "phone":            getattr(t, "phone", "") or "",
        })

    return Response({
        "id": fam.id,
        "hotel_id": fam.hotel_id,
        "hotel_name": fam.hotel_name,
        "checkin": fam.arrival_date.isoformat() if fam.arrival_date else None,
        "checkout": fam.departure_date.isoformat() if fam.departure_date else None,
        "room": "",
        "party": party,
    })

class TravelerPartialUpdateView(APIView):
    permission_classes = [AllowAny]  # можно ужесточить позже

    @transaction.atomic
    def patch(self, request, pk: int):
        t = get_object_or_404(Traveler, pk=pk)
        data = request.data or {}

        allowed = {"gender","doc_type","doc_expiry","passport","nationality","dob","passport_expiry"}
        payload = {k: v for k, v in data.items() if k in allowed and v is not None}

        # аккуратно парсим даты
        for k in ("dob","doc_expiry","passport_expiry"):
            if k in payload and payload[k]:
                try:
                    payload[k] = dt.date.fromisoformat(str(payload[k])[:10])
                except Exception:
                    return Response({"detail": f"Bad date for {k}, use YYYY-MM-DD"}, status=400)

        for k, v in payload.items():
            setattr(t, k, v)
        t.save(update_fields=list(payload.keys()))

        # вернём актуальный срез для фронта
        return Response({
            "id": t.id,
            "gender": t.gender or "",
            "doc_type": t.doc_type or "",
            "doc_expiry": t.doc_expiry.isoformat() if t.doc_expiry else None,
            "passport": t.passport or "",
            "nationality": t.nationality or "",
            "dob": t.dob.isoformat() if t.dob else None,
            "passport_expiry": t.passport_expiry.isoformat() if t.passport_expiry else None,
        })

# --- Черновики броней по семье (лента на странице семьи) ---------------------
class FamilyBookingDraftsView(APIView):
    permission_classes = [AllowAny]

    def get(self, request, fam_id: int):
        qs = (BookingSale.objects
              .filter(family_id=fam_id)
              .select_related("company")
              .order_by("-created_at"))

        rows = []
        for b in qs:
            rows.append({
                "id": b.id,
                "booking_code": b.booking_code,
                "status": b.status,
                "date": b.date.isoformat() if b.date else None,
                "excursion_id": b.excursion_id,
                "excursion_title": b.excursion_title,
                "hotel_id": b.hotel_id,
                "hotel_name": b.hotel_name,
                "region_name": getattr(b, "region_name", "") or "",
                "pickup_point_id": b.pickup_point_id,
                "pickup_point_name": b.pickup_point_name,
                "pickup_time_str": b.pickup_time_str,
                "pickup_lat": getattr(b, "pickup_lat", None),
                "pickup_lng": getattr(b, "pickup_lng", None),
                "pickup_address": getattr(b, "pickup_address", ""),
                "excursion_language": getattr(b, "excursion_language", None),
                "room_number": getattr(b, "room_number", ""),
                "adults": b.adults, "children": b.children, "infants": b.infants,
                "price_source": getattr(b, "price_source", "PICKUP"),
                "price_per_adult": str(getattr(b, "price_per_adult", 0) or 0),
                "price_per_child": str(getattr(b, "price_per_child", 0) or 0),
                "gross_total": str(b.gross_total or 0),
                "net_total": str(getattr(b, "net_total", 0) or 0),
                "commission": str(getattr(b, "commission", 0) or 0),
                "company": CompanySerializer(getattr(b, "company", None)).data if getattr(b, "company_id", None) else None,
                "created_at": b.created_at.isoformat() if b.created_at else None,
                # удобные поля для фронта:
                "maps_url": (
                    f"https://maps.google.com/?q={b.pickup_lat},{b.pickup_lng}"
                    if getattr(b, "pickup_lat", None) is not None and getattr(b, "pickup_lng", None) is not None
                    else (f"https://maps.google.com/?q={b.pickup_point_name or b.hotel_name}"
                          if (b.pickup_point_name or b.hotel_name) else None)
                ),
                "travelers_csv": getattr(b, "travelers_csv", "") or "",
                "is_sendable": b.status in ("DRAFT",),      # кнопка «Отправить» только для черновиков
                "is_sent": b.status in ("PENDING", "HOLD", "PAID", "CANCELLED", "EXPIRED"),
            })
        return Response(rows)


SPECIAL_MAP = {
    # требования «на каждого участника»
    "granada":   {"all": ["first_name", "last_name", "passport", "nationality"]},
    "gibraltar": {"all": ["nationality"]},
    "tangier":   {"all": ["first_name", "last_name", "passport", "nationality", "gender", "dob", "doc_type", "doc_expiry"]},
    "seville":   {"all": ["first_name", "last_name", "passport", "nationality", "dob"]},  # возраст считаем из dob
}

SPECIAL_TITLES = {
    "granada":  ("granada", "гранада"),
    "gibraltar":("gibraltar", "гибралтар"),
    "tangier":  ("tanger", "tangier", "танжер"),
    "seville":  ("seville", "севилья"),
}

def _guess_special_key(title: str | None) -> str | None:
    s = (title or "").lower()
    for key, needles in SPECIAL_TITLES.items():
        if any(n in s for n in needles):
            return key
    return None

def _parse_travelers_csv(csv: str) -> list[int]:
    return [int(x) for x in str(csv or "").split(",") if x.strip().isdigit()]

def _validate_booking_requirements(b) -> list[dict]:
    """
    Проверяет бронь b на спец-требования.
    Возвращает список проблем:
      {"booking_id": int, "traveler_id": int|None, "missing": [field,...]}
    Пустой список = всё ок.
    """
    key = _guess_special_key(getattr(b, "excursion_title", ""))
    if not key:
        return []  # не спецэкскурсия

    need = SPECIAL_MAP.get(key, {}).get("all", [])
    trav_ids = _parse_travelers_csv(getattr(b, "travelers_csv", ""))

    problems = []
    if not trav_ids:
        problems.append({"booking_id": b.id, "traveler_id": None, "missing": ["participants"]})
        return problems

    # Разом тянем нужные поля
    fields = ["id", "first_name", "last_name", "passport", "nationality", "dob", "gender", "doc_type", "doc_expiry", "passport_expiry"]
    travelers = {t.id: t for t in Traveler.objects.filter(id__in=trav_ids).only(*fields)}

    for tid in trav_ids:
        t = travelers.get(tid)
        if not t:
            problems.append({"booking_id": b.id, "traveler_id": tid, "missing": ["not_found"]})
            continue
        miss = []
        for f in need:
            val = getattr(t, f, None)
            if not val:
                # допускаем подмену doc_expiry на паспортный срок, если он есть
                if f == "doc_expiry" and getattr(t, "passport_expiry", None):
                    continue
                miss.append(f)
        if miss:
            problems.append({"booking_id": b.id, "traveler_id": tid, "missing": miss})

    return problems


@method_decorator(csrf_exempt, name="dispatch")
class BookingBatchPreviewView(APIView):
    """
    POST /api/sales/bookings/batch/preview/
    Body JSON: { "family_id": 123 } ИЛИ { "booking_ids": [1,2,3] }
    Возвращает сводку черновиков текущего "гида" (status='DRAFT').
    """
    authentication_classes = []
    permission_classes = [AllowAny]

    def post(self, request):
        booking_ids = request.data.get("booking_ids") or []
        family_id = request.data.get("family_id")

        user = _resolve_user(request)

        qs = BookingSale.objects.filter(status="DRAFT").select_related("company")
        if user:
            qs = qs.filter(guide=user)

        try:
            if family_id:
                qs = qs.filter(family_id=family_id)
            elif booking_ids:
                qs = qs.filter(id__in=booking_ids)
        except FieldError:
            return Response({"detail": "В модели BookingSale нет поля family."}, status=400)

        items = []
        total = 0.0
        blocked = 0

        # Валидация спец-экскурсий на лету
        problems_all = {}  # booking_id -> [problem,...]

        for b in qs.order_by("-created_at"):
            gross = float(b.gross_total or 0)
            total += gross

            probs = _validate_booking_requirements(b)
            if probs:
                blocked += 1
                problems_all[b.id] = probs

            items.append({
                "id": b.id,
                "booking_code": b.booking_code,
                "company": getattr(b.company, "name", None),
                "date": b.date.isoformat() if b.date else None,
                "excursion_id": b.excursion_id,
                "excursion_title": b.excursion_title,
                "hotel_name": b.hotel_name,
                "pickup_point_name": b.pickup_point_name,
                "pickup_time_str": b.pickup_time_str,
                "excursion_language": getattr(b, "excursion_language", None),
                "room_number": getattr(b, "room_number", ""),
                "adults": b.adults, "children": b.children, "infants": b.infants,
                "gross_total": f"{gross:.2f}",
                "price_per_adult": str(getattr(b, "price_per_adult", 0) or 0),
                "price_per_child": str(getattr(b, "price_per_child", 0) or 0),
                "pickup_lat": getattr(b, "pickup_lat", None),
                "pickup_lng": getattr(b, "pickup_lng", None),
                "pickup_address": getattr(b, "pickup_address", ""),
                "status": b.status,
                # можно отправить, только если DRAFT и нет проблем по требованиям
                "is_sendable": (b.status == "DRAFT" and not probs),
                # чтобы фронт красиво подсветил недостающие поля рядом с участниками
                "problems": problems_all.get(b.id, []),
            })

        return Response({
            "count": len(items),
            "total": f"{total:.2f}",
            "blocked": blocked,             # сколько броней нельзя отправить
            "items": items,
        }, status=200)




@method_decorator(csrf_exempt, name="dispatch")
class BookingBatchSendView(APIView):
    """
    POST /api/sales/bookings/batch/send/
    Body JSON: { "family_id": 123 } ИЛИ { "booking_ids": [1,2,3] }
    Переводит выбранные черновики из DRAFT -> PENDING и (опционально) запускает отправку.
    """
    authentication_classes = []
    permission_classes = [AllowAny]

    def post(self, request):
        booking_ids = request.data.get("booking_ids") or []
        family_id = request.data.get("family_id")

        user = _resolve_user(request)

        qs = BookingSale.objects.filter(status="DRAFT").select_related("company")
        if user:
            qs = qs.filter(guide=user)

        try:
            if family_id:
                qs = qs.filter(family_id=family_id)
            elif booking_ids:
                qs = qs.filter(id__in=booking_ids)
        except FieldError:
            return Response({"detail": "В модели BookingSale нет поля family."}, status=400)

        # Валидация перед отправкой: если есть «дыры» — 422 и список проблем
        problems = []
        for b in qs:
            problems += _validate_booking_requirements(b)

        if problems:
            return Response(
                {"detail": "Requirements missing", "problems": problems},
                status=422  # Unprocessable Entity
            )

        # --- отправка писем + перевод статусов ---------------------------------------
        bookings = list(qs)           # материализуем queryset, чтобы переиспользовать
        sent_ids = []
        failed_ids = []

        for b in bookings:
            try:
                ok = send_booking_email(b, subject_prefix="[SalesPortal]")
            except Exception:
                ok = False
            if ok:
                sent_ids.append(b.id)
            else:
                failed_ids.append(b.id)

        # Переводим в PENDING только те, что реально ушли
        if sent_ids:
            upd = {"status": "PENDING"}
            if hasattr(BookingSale, "sent_at"):
                upd["sent_at"] = timezone.now()
            BookingSale.objects.filter(id__in=sent_ids).update(**upd)

        return Response(
            {
                "sent": len(sent_ids),
                "failed_ids": failed_ids,
                "updated_to_pending": len(sent_ids),
            },
            status=200 if sent_ids and not failed_ids else 207  # 207 = частичный успех
        )



@method_decorator(csrf_exempt, name="dispatch")
class BookingBatchCancelView(APIView):
    """
    POST /api/sales/bookings/batch/cancel/
    Body JSON: { "booking_ids": [1,2,3] } ИЛИ { "family_id": 123, "reason": "..." }
    Правила:
      - DRAFT удалять/не трогать (не аннулируем)
      - CANCELLED — идемпотентно (пропускаем)
      - Остальные (PENDING/HOLD/PAID/CONFIRMED/EXPIRED) → CANCELLED
    """
    authentication_classes = []
    permission_classes = [AllowAny]

    @transaction.atomic
    def post(self, request):
        booking_ids = request.data.get("booking_ids") or []
        family_id = request.data.get("family_id")
        reason = (request.data.get("reason") or "").strip()

        user = _resolve_user(request)

        # Базовый queryset: все НЕ DRAFT (DRAFT не аннулируем)
        qs = BookingSale.objects.exclude(status="DRAFT")
        if user:
            qs = qs.filter(guide=user)

        try:
            if family_id:
                qs = qs.filter(family_id=family_id)
            elif booking_ids:
                qs = qs.filter(id__in=booking_ids)
        except FieldError:
            return Response({"detail": "В модели BookingSale нет поля family."}, status=400)

        # Разделим на уже отменённые и подлежащие отмене
        to_cancel = list(qs.exclude(status="CANCELLED").values_list("id", flat=True))
        already = list(qs.filter(status="CANCELLED").values_list("id", flat=True))

        if not to_cancel and not already:
            return Response({"updated": 0, "cancelled_ids": [], "already_cancelled": []}, status=200)

        # 1) Письма об аннуляции (не прерывают процесс, просто считаем успех/ошибки)
        emailed_ok, emailed_fail = [], []
        for b in BookingSale.objects.filter(id__in=to_cancel):
            try:
                ok = send_cancellation_email(b, reason)
            except Exception:
                ok = False
            (emailed_ok if ok else emailed_fail).append(b.id)

        # 2) Обновляем статус/время/причину для всех к аннуляции
        now = timezone.now()
        upd = {"status": "CANCELLED"}
        if hasattr(BookingSale, "cancelled_at"):
            upd["cancelled_at"] = now
        BookingSale.objects.filter(id__in=to_cancel).update(**upd)

        # причину пишем отдельным апдейтом, только если она передана и поле есть
        if reason and hasattr(BookingSale, "cancel_reason"):
            BookingSale.objects.filter(id__in=to_cancel).update(cancel_reason=reason)

        return Response({
            "updated": len(to_cancel),
            "cancelled_ids": to_cancel,      # все, кому сменили статус
            "already_cancelled": already,    # были отменены раньше
            "email_sent_ok": emailed_ok,     # для логов/индикаторов на фронте
            "email_failed_ids": emailed_fail
        }, status=200)



def _normalize_excursions(raw, compact: bool = True, limit: int | None = None, offset: int = 0):
    items = raw.get("items") if isinstance(raw, dict) else raw
    if not isinstance(items, list):
        items = []

    total = len(items)
    if limit is not None:
        items = items[offset: offset + limit]

    norm = []
    for it in items:
        _id = it.get("id")
        title = it.get("localized_title") or it.get("title") or ""
        description_html = it.get("localized_description") or it.get("description") or ""
        image = it.get("image")
        duration = it.get("duration")
        direction = it.get("direction")

        days_code = it.get("days") or []
        days_num = it.get("available_days") or []
        if not days_code and days_num:
            days_code = [WEEKDAY_NUM_TO_CODE.get(n) for n in days_num if n in WEEKDAY_NUM_TO_CODE]
        if not days_num and days_code:
            days_num = [WEEKDAY_CODE_TO_NUM.get(c) for c in days_code if c in WEEKDAY_CODE_TO_NUM]

        languages = it.get("tour_languages") or it.get("languages") or []

        if compact:
            short = _strip_html(description_html)[:220].rstrip()
            norm.append({
                "id": _id,
                "title": title,
                "short_description": short,
                "duration": duration,
                "direction": direction,
                "days": days_code,          # ["thu", ...]
                "available_days": days_num, # [3, ...]
                "languages": languages,     # <= ВАЖНО для выпадающего списка языков
                "image": image,
            })
        else:
            norm.append({
                "id": _id,
                "title": title,
                "description_html": description_html,
                "duration": duration,
                "direction": direction,
                "days": days_code,
                "available_days": days_num,
                "languages": languages,
                "image": image,
            })
    return {"items": norm, "total": total}

def _es_title_overrides() -> dict[int, str]:
    """
    Необязательная мапа {excursion_id: 'Sevilla', ...} из вашей админки core,
    чтобы (если нужно) добавить поле title_es к ответу — не затрагивая title.
    """
    try:
        CoreExcursion = apps.get_model('core', 'Excursion')
    except Exception:
        return {}
    rows = (
        CoreExcursion.objects
        .filter(is_active=True)
        .exclude(csi_id__isnull=True)
        .values("csi_id", "name")
    )
    out = {}
    for r in rows:
        try:
            out[int(r["csi_id"])] = r["name"] or ""
        except Exception:
            pass
    return out

@api_view(["GET"])
def excursions(request):
    lang = request.query_params.get("lang", "ru")
    date = request.query_params.get("date")
    region = request.query_params.get("region")
    compact = request.query_params.get("compact", "1") not in ("0", "false", "False")
    try:
        limit = int(request.query_params.get("limit", "20"))
    except ValueError:
        limit = 20
    try:
        offset = int(request.query_params.get("offset", "0"))
    except ValueError:
        offset = 0

    # <-- ВАЖНО: всегда используем CSI как источник, чтобы не потерять languages
    raw = csi.list_excursions(lang=lang, date=date, region=region)
    data = _normalize_excursions(raw, compact=compact, limit=limit, offset=offset)

    # Необязательное: добавим title_es, если есть в админке core (не ломает фронт)
    es_map = _es_title_overrides()
    if es_map:
        for it in data["items"]:
            es = es_map.get(int(it["id"] or 0))
            if es:
                it["title_es"] = es

    return Response(data)


class SalesExcursionPickupsView(APIView):
    """GET /api/sales/pickups/v2/?excursion_id=&hotel_id=&hotel_name=&date=YYYY-MM-DD
    Returns: {excursion_id, excursion_title, hotel_id, date, count, results:[{...}]}
    """

    permission_classes = [AllowAny]

    def get(self, request, *args, **kwargs):
        # 1) excursion_id обязателен и целый
        try:
            excursion_id = int(request.GET.get("excursion_id", ""))
        except (TypeError, ValueError):
            return Response({"detail": "excursion_id must be integer"}, status=status.HTTP_400_BAD_REQUEST)

        # 2) date обязателен и в формате YYYY-MM-DD
        date_str = request.GET.get("date")
        if not date_str or not parse_date(date_str):
            return Response({"detail": "Invalid or missing 'date' (YYYY-MM-DD)"}, status=status.HTTP_400_BAD_REQUEST)

        # 3) hotel_id ИЛИ hotel_name (fallback)
        hotel_name = (request.GET.get("hotel_name") or request.GET.get("hotel") or "").strip()
        hotel_id = None
        hotel_id_raw = request.GET.get("hotel_id")
        try:
            hotel_id = int(hotel_id_raw) if hotel_id_raw not in (None, "",) else None
        except ValueError:
            hotel_id = None

        if not hotel_id and hotel_name:
            hid = _resolve_hotel_id_by_name(hotel_name)
            if hid:
                hotel_id = hid

        if not hotel_id:
            # мягкий ответ, как и раньше: просто пустой список без ошибки
            title = csi.excursion_title(excursion_id, lang=(request.GET.get("lang") or "ru")[:5])
            return Response({
                "excursion_id": excursion_id,
                "excursion_title": title,
                "hotel_id": None,
                "date": date_str,
                "count": 0,
                "results": [],
            })

        # 4) тянем пикапы у клиента
        client = get_client()
        pickups = client.excursion_pickups(excursion_id=excursion_id, hotel_id=hotel_id, date=date_str)

        # 5) добавим заголовок экскурсии
        lang = (request.GET.get("lang") or request.headers.get("Accept-Language") or "ru")[:5]
        title = csi.excursion_title(excursion_id, lang=lang)

        results = []
        for it in pickups:
            results.append({
                "id": it.get("id"),
                "point": it.get("name") or it.get("point"),
                "time": it.get("time"),
                "lat": it.get("lat"),
                "lng": it.get("lng"),
                "address": it.get("address") or "",
            })

        return Response({
            "excursion_id": excursion_id,
            "excursion_title": title,
            "hotel_id": hotel_id,
            "date": date_str,
            "count": len(results),
            "results": results,     # ← ТАК, а не pickups
        })



@api_view(["GET"])
def pickups(request):
    ex_id = request.GET.get("excursion_id")
    hotel_id = request.GET.get("hotel_id")
    date = request.GET.get("date")  # пока не используем

    if not ex_id or not hotel_id:
        return Response({"error": "excursion_id and hotel_id are required", "items": []}, status=400)

    try:
        ex_id = int(ex_id)
        hotel_id = int(hotel_id)
    except ValueError:
        return Response({"error": "excursion_id and hotel_id must be integers", "items": []}, status=400)

    item = csi.get_client().excursion_pickup(ex_id, hotel_id)
    if not item:
        # совместимо с фронтом: пустой список — просто нет точки
        return Response({"items": []}, status=200)

    # язык для заголовка экскурсии
    lang = (request.GET.get("lang") or request.headers.get("Accept-Language") or "ru")[:5]
    title = csi.excursion_title(ex_id, lang=lang)

    # Нормализуем к единому виду
    norm = {
        "id": item.get("id"),
        "point": item.get("name"),
        "time": item.get("time"),       # "HH:MM" или None
        "lat": item.get("lat"),
        "lng": item.get("lng"),
        "price_adult": item.get("price_adult"),
        "price_child": item.get("price_child"),
    }
    return Response({
        "excursion_id": ex_id,
        "excursion_title": title,
        "hotel_id": hotel_id,
        "items": [norm]
    }, status=200)


@api_view(["GET"])
def quote(request):
    try:
        ex_id = int(request.query_params["excursion_id"])
        adults = int(request.query_params.get("adults", "1"))
        children = int(request.query_params.get("children", "0"))
        infants = int(request.query_params.get("infants", "0"))
    except (KeyError, ValueError):
        return Response({"detail": "invalid params"}, status=400)

    lang = request.query_params.get("lang", "ru")
    hotel_id_raw = request.query_params.get("hotel_id")
    hotel_id = int(hotel_id_raw) if (hotel_id_raw and hotel_id_raw.isdigit()) else None
    date = request.query_params.get("date")
    hotel_name = request.query_params.get("hotel_name") or request.query_params.get("hotel")

    if not hotel_id and hotel_name:
        hid = _resolve_hotel_id_by_name(hotel_name)
        if hid:
            hotel_id = hid

    if not hotel_id:
        return Response({"detail": "hotel_id is required (could not resolve by hotel_name)"}, status=400)

    try:
        data = pricing_quote(
            excursion_id=ex_id,
            adults=adults,
            children=children,
            infants=infants,
            lang=lang,
            hotel_id=hotel_id,
            date=date,
        )
        return Response(data)
    except Exception as e:
        logging.getLogger(__name__).exception("quote() failed")
        return Response({"detail": str(e)}, status=500)



@api_view(["GET"])
@permission_classes([AllowAny])
def pricing_debug_signature(request):
    try:
        import sales.services.costasolinfo as mod
        sig = str(inspect.signature(mod.pricing_quote))
        path = getattr(mod, "__file__", "<unknown>")
        return Response({"module_file": path, "signature": sig})
    except Exception as e:
        return Response({"detail": str(e)}, status=500)

# def _weekday_slug(date_str: str) -> str | None:
#     try:
#         d = dt.date.fromisoformat(date_str)
#         return WEEKDAYS[d.weekday()]
#     except Exception:
#         return None

@api_view(["GET"])
@permission_classes([AllowAny])
def pricing_quote_view(request):
    try:
        excursion_id = int(request.GET.get("excursion_id"))
        adults = int(request.GET.get("adults", 0))
        children = int(request.GET.get("children", 0))
        infants = int(request.GET.get("infants", 0))
        lang = request.GET.get("lang") or "ru"

        hotel_id_raw = request.GET.get("hotel_id")
        hotel_id = int(hotel_id_raw) if (hotel_id_raw and hotel_id_raw.isdigit()) else None
        hotel_name = request.GET.get("hotel_name") or request.GET.get("hotel")  # ← НОВОЕ
        date = request.GET.get("date")

        if adults < 0 or children < 0 or infants < 0:
            return Response({"detail": "Negative quantities not allowed"}, status=400)

        # Если hotel_id отсутствует — пробуем найти его по названию
        if not hotel_id and hotel_name:
            hid = _resolve_hotel_id_by_name(hotel_name)
            if hid:
                hotel_id = hid

        # Если до сих пор нет hotel_id — честно скажем об этом
        if not hotel_id:
            return Response({"detail": "hotel_id is required (could not resolve by hotel_name)"}, status=400)

        # Проверка доступности даты по экскурсии (если дата передана)
        if date:
            wd = _weekday_slug(date)
            if not wd:
                return Response({"detail": "Bad date format, use YYYY-MM-DD"}, status=400)
            try:
                ex = csi.excursion_detail(excursion_id)
            except Exception:
                ex = {}
            avail_raw = (ex.get("available_days") or ex.get("days") or [])
            avail_norm = []
            for x in avail_raw:
                if isinstance(x, int):
                    avail_norm.append(WEEKDAYS[x % 7])     # 0=mon..6=sun
                else:
                    avail_norm.append(str(x).strip().lower()[:3])
            if avail_norm and wd not in avail_norm:
                return Response({
                    "detail": f"Date {date} is not available for this excursion",
                    "available_days": avail_norm
                }, status=400)

        # ВАЖНО: передаём date/ hotel_id дальше
        quote = pricing_quote(
            excursion_id=excursion_id,
            adults=adults,
            children=children,
            infants=infants,
            lang=lang,
            hotel_id=hotel_id,
            date=date,
        )
        return Response(quote)

    except NotFoundError as e:
        # аккуратно: это нормальная «нет цены»
        return Response({"detail": str(e)}, status=404)
    except (TypeError, ValueError) as e:
        return Response({"detail": str(e), "type": e.__class__.__name__}, status=400)
    except Exception as e:
        logging.getLogger(__name__).exception("pricing_quote_view failed")
        return Response({"detail": str(e), "type": e.__class__.__name__}, status=500)


@api_view(["GET"])
@permission_classes([AllowAny])
def debug_raw_hotel(request):
    from .services.costasolinfo import _get
    hotel_id = request.GET.get("hotel_id")
    if not hotel_id:
        return JsonResponse({"detail": "hotel_id required"}, status=400)
    try:
        hid = int(hotel_id)
    except ValueError:
        return JsonResponse({"detail": "hotel_id must be int"}, status=400)
    data = _get(f"/hotels/{hid}/", allow_404=True)
    return JsonResponse({"hotel_id": hid, "raw": data}, json_dumps_params={"ensure_ascii": False, "default": str})

@api_view(["GET"])
@permission_classes([AllowAny])
def debug_raw_excursion(request):
    from .services.costasolinfo import _get
    excursion_id = request.GET.get("excursion_id")
    if not excursion_id:
        return JsonResponse({"detail": "excursion_id required"}, status=400)
    try:
        exid = int(excursion_id)
    except ValueError:
        return JsonResponse({"detail": "excursion_id must be int"}, status=400)
    data = _get(f"/excursions/{exid}/", allow_404=True)
    return JsonResponse({"excursion_id": exid, "raw": data}, json_dumps_params={"ensure_ascii": False, "default": str})


class CompanyViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = Company.objects.filter(is_active=True).order_by("name")
    serializer_class = CompanySerializer
    permission_classes = [AllowAny]  # <-- было IsAuthenticated


class BookingCreateView(APIView):
    permission_classes = [AllowAny]  # ← временно для теста

    def post(self, request):
        ser = BookingSaleCreateSerializer(data=request.data, context={"request": request})
        ser.is_valid(raise_exception=True)
        booking = ser.save()
        return Response({"id": booking.id, "booking_code": booking.booking_code}, status=status.HTTP_200_OK)


class BookingListView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        qs = BookingSale.objects.filter(guide=request.user).order_by("-created_at")[:200]
        return Response(BookingSaleListSerializer(qs, many=True).data)


class BookingDetailView(APIView):
    """
    GET    /api/sales/bookings/<pk>/       → данные одной брони
    PUT    /api/sales/bookings/<pk>/       → обновление (только если DRAFT)
    PATCH  /api/sales/bookings/<pk>/       → частичное обновление (только если DRAFT)
    DELETE /api/sales/bookings/<pk>/       → удаление (только если DRAFT)
    """
    permission_classes = [AllowAny]   # пока как и остальные тестовые эндпоинты

    def get_object(self, pk: int) -> BookingSale:
        return get_object_or_404(BookingSale, pk=pk)

    def get(self, request, pk: int):
        b = self.get_object(pk)
        return Response(_booking_to_json(b), status=200)

    @transaction.atomic
    def delete(self, request, pk: int):
        b = self.get_object(pk)
        if b.status != "DRAFT":
            return Response({"detail": "Only DRAFT bookings can be deleted"}, status=409)
        b.delete()
        return Response({"deleted": 1, "id": pk}, status=200)

    @transaction.atomic
    def put(self, request, pk: int):
        return self._update(request, pk, partial=False)

    @transaction.atomic
    def patch(self, request, pk: int):
        return self._update(request, pk, partial=True)

    def _update(self, request, pk: int, partial: bool):
        b = self.get_object(pk)
        if b.status != "DRAFT":
            return Response({"detail": "Only DRAFT bookings can be edited"}, status=409)

        data = request.data or {}
        # список разрешённых к правке полей
        editable = {
            "date", "room_number", "excursion_language",
            "pickup_point_id", "pickup_point_name", "pickup_time_str",
            "pickup_lat", "pickup_lng", "pickup_address",
            "adults", "children", "infants",
            "gross_total", "price_per_adult", "price_per_child",
        }

        # аккуратно приводим типы там, где нужно
        for key, val in list(data.items()):
            if key not in editable:
                data.pop(key, None)

        # date
        if "date" in data and data["date"]:
            try:
                data["date"] = dt.date.fromisoformat(str(data["date"])[:10])
            except Exception:
                return Response({"detail": "Bad date format, use YYYY-MM-DD"}, status=400)

        # числовые
        for k in ("adults", "children", "infants"):
            if k in data and data[k] is not None:
                try: data[k] = int(data[k])
                except Exception: return Response({"detail": f"{k} must be int"}, status=400)

        for k in ("price_per_adult", "price_per_child", "gross_total"):
            if k in data and data[k] is not None:
                try: data[k] = float(data[k])
                except Exception: return Response({"detail": f"{k} must be number"}, status=400)

        # обновляем
        for k, v in data.items():
            setattr(b, k, v)
        b.save(update_fields=[*data.keys()] or None)

        return Response(_booking_to_json(b), status=200)


class BookingCancelView(APIView):
    permission_classes = [AllowAny]

    @transaction.atomic
    def post(self, request, pk: int):
        b = get_object_or_404(BookingSale, pk=pk)

        if b.status == "DRAFT":
            return Response({"detail": "Draft cannot be cancelled, delete it instead"}, status=409)

        if b.status == "CANCELLED":
            return Response(_booking_to_json(b), status=200)

        reason = (request.data or {}).get("reason") or ""

        # отправляем письмо (до изменения статуса; если письмо не ушло — всё равно продолжаем)
        try:
            send_cancellation_email(b, reason)
        except Exception:
            pass

        b.status = "CANCELLED"
        if hasattr(b, "cancelled_at"):
            b.cancelled_at = timezone.now()
        if hasattr(b, "cancel_reason"):
            b.cancel_reason = reason or b.cancel_reason
        b.save(update_fields=["status", *([ "cancelled_at" ] if hasattr(b, "cancelled_at") else []),
                              *([ "cancel_reason" ] if hasattr(b, "cancel_reason") else [])])

        return Response(_booking_to_json(b), status=200)