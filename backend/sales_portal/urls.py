# backend/sales_portal/urls.py
from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static

# используем health из sales.views_api
from sales import views_api as api

urlpatterns = [
    path('admin/', admin.site.urls),
    path("api/health/", api.health),        # /api/health/ → один источник
    path("api/sales/", include("sales.urls")),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
