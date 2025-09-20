# backend/sales/urls.py
from django.urls import path
from . import views_api as v
from .views_pages import tourists_import_page  # HTML-страница импорта

app_name = "sales"

urlpatterns = [
    # Health
    path("health/", v.health, name="health"),

    # HTML-страницы (служебные)
    path("import/tourists/", tourists_import_page, name="tourists_import_page"),

    # Публичные API
    path("login/", v.login_view, name="login"),
    path("hotels/", v.hotels, name="hotels"),                      # ?q= / ?search=
    path("tourists/", v.tourists, name="tourists"),                # ?hotel_name=&search=
    path("families/<int:fam_id>/", v.family_detail, name="family_detail"),
    path("excursions/", v.excursions, name="excursions"),

    # Пикапы (нормализованный вариант)
    path("pickups/v2/", v.SalesExcursionPickupsView.as_view(), name="pickups_v2"),

    # (Опционально) Легаси — можно удалить, если не используется
    path("pickups/", v.pickups, name="pickups"),

    # Калькуляция цены — ВАЖНО: новая вью
    path("pricing/quote/", v.pricing_quote_view, name="pricing_quote"),

    # Черновик создания брони
    path("bookings/create/", v.create_booking, name="create_booking"),

    # Отладка
    path("debug/csi-base/", v.debug_csi_base, name="debug_csi_base"),
    path("debug/pricing-sig/", v.pricing_debug_signature, name="debug_pricing_sig"),
    path("debug/hotel-region/", v.debug_hotel_region, name="debug_hotel_region"),
    path("debug/excursion-prices/", v.debug_excursion_prices, name="debug_excursion_prices"),
    path("debug/raw/hotel/", v.debug_raw_hotel, name="debug_raw_hotel"),
    path("debug/raw/excursion/", v.debug_raw_excursion, name="debug_raw_excursion"),

]
