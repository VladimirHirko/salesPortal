# backend/sales/urls.py
from django.urls import path, include
from rest_framework.routers import DefaultRouter

from . import views_api as v
from .views_pages import tourists_import_page   # ← добавили
from .views_api import (
    CompanyViewSet,
    FamilyBookingDraftsView,
    BookingBatchPreviewView,
    BookingBatchSendView,
    BookingCreateView,
    # … остальные вьюхи, которые уже были подключены
)

router = DefaultRouter()
router.register(r"companies", v.CompanyViewSet, basename="company")

app_name = "sales"

urlpatterns = [
    # Health
    path("health/", v.health, name="health"),

    # HTML-страницы
    path("import/tourists/", tourists_import_page, name="tourists_import_page"),  # ← используем прямую функцию

    # Публичные API
    path("login/", v.login_view, name="login"),
    path("hotels/", v.hotels, name="hotels"),
    path("tourists/", v.tourists, name="tourists"),
    path("families/<int:fam_id>/", v.family_detail, name="family_detail"),
    path("excursions/", v.excursions, name="excursions"),

    # Пикапы
    path("pickups/v2/", v.SalesExcursionPickupsView.as_view(), name="pickups_v2"),
    path("pickups/", v.pickups, name="pickups"),

    # Калькуляция цены
    path("pricing/quote/", v.pricing_quote_view, name="pricing_quote"),

    # Отладка
    path("debug/csi-base/", v.debug_csi_base, name="debug_csi_base"),
    path("debug/pricing-sig/", v.pricing_debug_signature, name="debug_pricing_sig"),
    path("debug/hotel-region/", v.debug_hotel_region, name="debug_hotel_region"),
    path("debug/excursion-prices/", v.debug_excursion_prices, name="debug_excursion_prices"),
    path("debug/raw/hotel/", v.debug_raw_hotel, name="debug_raw_hotel"),
    path("debug/raw/excursion/", v.debug_raw_excursion, name="debug_raw_excursion"),

    # DRF router (companies)
    path("", include(router.urls)),

    # Бронирования (боевые)
    path("bookings/create/", v.BookingCreateView.as_view(), name="booking-create"),
    path("bookings/", v.BookingListView.as_view(), name="booking-list"),
    path("bookings/family/<int:fam_id>/drafts/", v.FamilyBookingDraftsView.as_view(), name="family-drafts"),
    path("bookings/batch/preview/", v.BookingBatchPreviewView.as_view(), name="bookings-batch-preview"),
    path("bookings/batch/send/", v.BookingBatchSendView.as_view(), name="bookings-batch-send"),

]
