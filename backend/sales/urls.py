# backend/sales/urls.py
from django.urls import path
from . import views_api
from .views_pages import tourists_import_page  # страница импорта

app_name = "sales"

urlpatterns = [
    # HTML-страница (сейчас будет доступна по /api/sales/import/tourists/)
    path("import/tourists/", tourists_import_page, name="tourists_import_page"),

    # API endpoints
    path("login/", views_api.login_view, name="login"),
    path("hotels/", views_api.hotels, name="hotels"),
    path("excursions/", views_api.excursions, name="excursions"),

    # Легаси/простой вариант пикапов
    path("pickups/", views_api.pickups, name="pickups"),

    # Новый нормализованный вариант пикапов (не конфликтует, другой URL)
    path("sales/pickups/", views_api.SalesExcursionPickupsView.as_view(), name="sales_excursion_pickups"),

    path("pricing/quote/", views_api.quote, name="pricing_quote"),
    path("bookings/create/", views_api.create_booking, name="create_booking"),
    path("debug/csi-base/", views_api.debug_csi_base, name="debug_csi_base"),
]
