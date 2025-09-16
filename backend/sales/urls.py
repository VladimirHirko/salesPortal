from django.urls import path
from . import views_api
from .views_api import SalesExcursionPickupsView

urlpatterns = [
    path("login/", views_api.login_view),
    path("excursions/", views_api.excursions),      # read-only из старой системы
    path("pickups/", views_api.pickups),            # read-only из старой системы
    path("pricing/quote/", views_api.quote),        # расчёт на нашей стороне
    path("bookings/create/", views_api.create_booking),
    path("hotels/", views_api.hotels),
    path("excursions/", views_api.excursions),
    path("pickups/", views_api.pickups),
    path("pricing/quote/", views_api.quote),
    path("debug/csi-base/", views_api.debug_csi_base),
    path("pickups/", SalesExcursionPickupsView.as_view(), name="sales-pickups"),

]
