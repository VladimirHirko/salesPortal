# sales/views_api.py

from django.shortcuts import render
from django.http import JsonResponse
from django.views.decorators.http import require_GET
from django.views.decorators.csrf import csrf_exempt
from django.utils.dateparse import parse_date
from .services import costasolinfo as csi
from .services.costasolinfo import get_client
from rest_framework.response import Response
from rest_framework.permissions import AllowAny
from rest_framework.decorators import api_view, permission_classes, authentication_classes
from rest_framework.views import APIView
from rest_framework import status
import re, html


def login_view(request): return JsonResponse({"ok": True})

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
def hotels(request):
    q = request.query_params.get("q", "").strip()
    if not q:
        return Response({"items": []})
    data = csi.search_hotels(q, limit=int(request.query_params.get("limit", "10")))
    return Response({"items": data} if isinstance(data, list) else (data or {"items": []}))

_TAG_RE = re.compile(r"<[^>]+>")

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

def _normalize_excursions(raw, compact: bool = True, limit: int | None = None, offset: int = 0):
    """
    Приводим ответ к единому формату { items: [ ... ], total: N }.
    Поддерживаем как массив, так и {items: [...]} из старого API.
    """
    items = raw.get("items") if isinstance(raw, dict) else raw
    if not isinstance(items, list):
        items = []

    total = len(items)
    # пагинация на нашей стороне (простая)
    if limit is not None:
        items = items[offset: offset + limit]

    norm = []
    for it in items:
        # исходные поля
        _id = it.get("id")
        title = it.get("localized_title") or it.get("title") or ""
        description_html = it.get("localized_description") or it.get("description") or ""
        image = it.get("image")
        duration = it.get("duration")
        direction = it.get("direction")
        # дни – могут прийти и кодами, и цифрами; соберём оба и унифицируем
        days_code = it.get("days") or []
        days_num = it.get("available_days") or []
        # добьём отсутствующие представления
        if not days_code and days_num:
            days_code = [WEEKDAY_NUM_TO_CODE.get(n) for n in days_num if n in WEEKDAY_NUM_TO_CODE]
        if not days_num and days_code:
            days_num = [WEEKDAY_CODE_TO_NUM.get(c) for c in days_code if c in WEEKDAY_CODE_TO_NUM]

        languages = it.get("tour_languages") or it.get("languages") or []

        if compact:
            short = _strip_html(description_html)[:220].rstrip()  # короткое описание ~ 220 симв.
            norm.append({
                "id": _id,
                "title": title,
                "short_description": short,
                "duration": duration,
                "direction": direction,
                "days": days_code,              # ["thu", ...]
                "available_days": days_num,     # [3, ...]
                "languages": languages,
                "image": image,
            })
        else:
            # полный вариант, оставляем HTML
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

@api_view(["GET"])
def excursions(request):
    lang = request.query_params.get("lang", "ru")
    date = request.query_params.get("date")
    region = request.query_params.get("region")
    compact = request.query_params.get("compact", "1") not in ("0", "false", "False")
    # простая пагинация
    try:
        limit = int(request.query_params.get("limit", "20"))
    except ValueError:
        limit = 20
    try:
        offset = int(request.query_params.get("offset", "0"))
    except ValueError:
        offset = 0

    raw = csi.list_excursions(lang=lang, date=date, region=region)
    data = _normalize_excursions(raw, compact=compact, limit=limit, offset=offset)
    return Response(data)


class SalesExcursionPickupsView(APIView):
    """GET /api/sales/pickups/?excursion_id=&hotel_id=&date=YYYY-MM-DD
    Returns: [{id, point, time, lat?, lng?, direction?}]"""

    def get(self, request, *args, **kwargs):
        try:
            excursion_id = int(request.GET.get("excursion_id", ""))
            hotel_id = int(request.GET.get("hotel_id", ""))
        except ValueError:
            return Response({
                "detail": "excursion_id and hotel_id must be integers"
            }, status=status.HTTP_400_BAD_REQUEST)

        date_str = request.GET.get("date")
        if not date_str or not parse_date(date_str):
            return Response({"detail": "Invalid or missing 'date' (YYYY-MM-DD)"}, status=status.HTTP_400_BAD_REQUEST)

        client = get_client()
        pickups = client.excursion_pickups(excursion_id=excursion_id, hotel_id=hotel_id, date=date_str)

        # добавим название экскурсии (язык можно брать из заголовка/квери, по умолчанию ru)
        lang = (request.GET.get("lang") or request.headers.get("Accept-Language") or "ru")[:5]
        title = csi.excursion_title(excursion_id, lang=lang)

        return Response({
            "excursion_id": excursion_id,
            "excursion_title": title,
            "hotel_id": hotel_id,
            "date": date_str,
            "count": len(pickups),
            "results": pickups,
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
        return Response({"error": "invalid params"}, status=400)
    region = request.query_params.get("region")
    company_id = request.query_params.get("company_id")
    lang = request.query_params.get("lang", "ru")
    data = csi.pricing_quote(ex_id, adults, children, infants, region,
                             int(company_id) if company_id else None, lang)
    return Response(data)