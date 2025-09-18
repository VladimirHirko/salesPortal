# backend/sales/urls.py
from django.urls import path
from . import views_api as api
from .views_pages import tourists_import_page  # HTML-страница импорта

app_name = "sales"

urlpatterns = [
    # ── Тех/health ──────────────────────────────────────────────────────────────
    # /api/sales/health/
    path("health/", api.health, name="health"),

    # ── HTML-страницы (админские/служебные) ────────────────────────────────────
    # /api/sales/import/tourists/
    path("import/tourists/", tourists_import_page, name="tourists_import_page"),
    path("tourists/", api.tourists, name="tourists"),
    
    # ── Публичные API эндпоинты ────────────────────────────────────────────────
    # /api/sales/login/
    path("login/", api.login_view, name="login"),

    # /api/sales/hotels/?q=...  (также принимает ?search=...)
    path("hotels/", api.hotels, name="hotels"),

    # /api/sales/excursions/?lang=ru&limit=...
    path("excursions/", api.excursions, name="excursions"),

    # Легаси пикапы: /api/sales/pickups/?excursion_id=&hotel_id=
    path("pickups/", api.pickups, name="pickups"),

    # Новый нормализованный вариант пикапов:
    # /api/sales/sales/pickups/?excursion_id=&hotel_id=&date=YYYY-MM-DD
    # (если хочешь избежать "sales/sales" в URL, можешь переименовать путь ниже,
    # например, на "pickups/v2/".)
    path("sales/pickups/", api.SalesExcursionPickupsView.as_view(), name="sales_excursion_pickups"),

    # Калькуляция цены: /api/sales/pricing/quote/?excursion_id=&adults=&children=&infants=
    path("pricing/quote/", api.quote, name="pricing_quote"),

    # Черновик создания брони (эхо-заглушка): /api/sales/bookings/create/
    path("bookings/create/", api.create_booking, name="create_booking"),

    # Отладка базовых настроек источника: /api/sales/debug/csi-base/
    path("debug/csi-base/", api.debug_csi_base, name="debug_csi_base"),
]
