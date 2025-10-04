# backend/sales/admin.py
from django.contrib import admin, messages
from django.template.response import TemplateResponse
from django.urls import path
from django.shortcuts import redirect
from django.utils.html import format_html
from django.utils.text import Truncator
from django.core.management import call_command
from django.http import HttpResponse

import logging
import openpyxl
from openpyxl.utils import get_column_letter

from .models import (
    Company, GuideProfile, BookingSale, FamilyBooking, Traveler,
    InboundEmail, CancelledBookingSale,   # proxy-модель
)
from .forms import TouristsImportForm
from .importers import tourists_excel

log = logging.getLogger(__name__)

# ── общий рендер бейджа статуса ───────────────────────────────────────────────
def render_status_badge(status: str):
    s = (status or "").lower()
    label = {
        "draft": "DRAFT",
        "pending": "Отправлено",
        "hold": "HOLD",
        "paid": "PAID",
        "cancelled": "Отменено",
        "expired": "EXPIRED",
    }.get(s, status)
    return format_html('<span class="sp-badge sp-{}">{}</span>', s, label)

# ───────────────────────────────────────────────────────────────────────────────
# Общий список: фильтр «Аннулированные»
class HideCancelledFilter(admin.SimpleListFilter):
    title = "Аннулированные"
    parameter_name = "cancelled"

    def lookups(self, request, model_admin):
        return [("show", "Показывать")]

    def queryset(self, request, queryset):
        # если пользователь не включил фильтр — скрываем CANCELLED
        if self.value() != "show":
            return queryset.exclude(status="CANCELLED")
        return queryset


# ───────────────────────────────────────────────────────────────────────────────
# InboundEmail
@admin.action(description="Проверить входящие Gmail сейчас")
def fetch_gmail_now(modeladmin, request, queryset):
    call_command("fetch_gmail")
    modeladmin.message_user(request, "Готово: входящие обновлены.")

@admin.register(InboundEmail)
class InboundEmailAdmin(admin.ModelAdmin):
    list_display = ("subject", "from_email", "date", "created_at")
    search_fields = ("subject", "from_email", "to_email", "snippet", "body_text")
    readonly_fields = ("uid", "message_id", "raw_headers", "created_at", "html_preview")
    actions = [fetch_gmail_now]

    def html_preview(self, obj):
        return format_html('<div style="border:1px solid #eee;padding:8px;">{}</div>', obj.body_html or "—")
    html_preview.short_description = "HTML"


# ───────────────────────────────────────────────────────────────────────────────
# BookingSale (основной список продаж)
@admin.register(BookingSale)
class BookingSaleAdmin(admin.ModelAdmin):
    list_display = (
        "booking_code", "company", "excursion_title", "date",
        "hotel_name", "pickup_point_name", "pickup_time_str",
        "excursion_language", "room_number",
        "adults", "children", "gross_total", "status_badge",
    )
    # ВКЛЮЧАЕМ наш фильтр HideCancelledFilter
    list_filter = (HideCancelledFilter, "company", "status", "excursion_language", "date")
    search_fields = (
        "booking_code", "excursion_title", "hotel_name",
        "pickup_point_name", "room_number"
    )
    readonly_fields = ("created_at",)
    actions = ["export_bookings_xlsx"]

    # цветной статус вместо plain-строки
    def status_badge(self, obj):
        return render_status_badge(getattr(obj, "status", ""))
    status_badge.short_description = "Status"
    status_badge.allow_tags = True

    # подключаем стили бейджей
    class Media:
        css = {"all": ("sales/admin-status-badges.css",)}

    # Дополнительно страхуемся параметром в URL (?cancelled=show)
    def get_queryset(self, request):
        qs = super().get_queryset(request)
        if request.GET.get("cancelled") != "show":
            qs = qs.exclude(status="CANCELLED")
        return qs

    def export_bookings_xlsx(self, request, queryset):
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = "Bookings"

        cols = [
            ("Booking code", "booking_code"),
            ("Company", lambda o: o.company.name if o.company_id else ""),
            ("Date", "date"),
            ("Excursion", "excursion_title"),
            ("Hotel", "hotel_name"),
            ("Pickup name", "pickup_point_name"),
            ("Pickup time", "pickup_time_str"),
            ("Pickup lat", "pickup_lat"),
            ("Pickup lng", "pickup_lng"),
            ("Pickup address", "pickup_address"),
            ("Maps URL", lambda o: o.maps_url()),
            ("Adults", "adults"),
            ("Children", "children"),
            ("Gross", "gross_total"),
            ("Language", "excursion_language"),
            ("Room", "room_number"),
            ("Created at", "created_at"),
        ]

        # заголовок
        for i, (title, _) in enumerate(cols, start=1):
            ws.cell(row=1, column=i, value=title)

        # данные
        r = 2
        for obj in queryset:
            for c, (_, field) in enumerate(cols, start=1):
                val = field(obj) if callable(field) else getattr(obj, field, "")
                ws.cell(row=r, column=c, value=val)
            r += 1

        # ширина колонок
        for i in range(1, len(cols) + 1):
            ws.column_dimensions[get_column_letter(i)].width = 18

        resp = HttpResponse(
            content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )
        resp["Content-Disposition"] = 'attachment; filename="bookings.xlsx"'
        wb.save(resp)
        return resp

    export_bookings_xlsx.short_description = "Экспортировать выбранные брони в Excel"


# ───────────────────────────────────────────────────────────────────────────────
# Прокси-админ: только отменённые
@admin.register(CancelledBookingSale)
class CancelledBookingSaleAdmin(BookingSaleAdmin):
    # свой набор фильтров — БЕЗ HideCancelledFilter и, по желанию, без status
    list_filter = ("company", "excursion_language", "date")

    def get_queryset(self, request):
        # НЕ зовём super(), чтобы не сработала логика «скрывать CANCELLED»
        return self.model.objects.filter(status="CANCELLED")

    def changelist_view(self, request, extra_context=None):
        extra_context = (extra_context or {}) | {"title": "Cancelled bookings"}
        return super().changelist_view(request, extra_context=extra_context)


# ── Inlines для семьи ─────────────────────────────────────────────────────────
class TravelerInline(admin.TabularInline):
    model = Traveler
    extra = 0
    fields = ("last_name", "first_name", "dob", "nationality", "passport", "passport_expiry")
    show_change_link = True

class BookingSaleInline(admin.TabularInline):
    model = BookingSale
    extra = 0
    can_delete = False
    show_change_link = True

    fields = (
    "booking_code", "date",
    "excursion_title", "excursion_language",
    "adults", "children", "infants",
    "pickup_point_name", "pickup_time_str",
    "gross_total", "status_badge",
    )
    readonly_fields = fields  # показываем как read-only, редактирование в самой брони

    def status_badge(self, obj):
        return render_status_badge(getattr(obj, "status", ""))
    status_badge.short_description = "Status"

    class Media:
        css = {"all": ("sales/admin-status-badges.css",)}

# ── FamilyBooking ──────────────────────────────────────────────────────────────
@admin.register(FamilyBooking)
class FamilyBookingAdmin(admin.ModelAdmin):
    list_display = ("ref_code", "hotel_name", "arrival_date", "departure_date", "people", "created_at")
    search_fields = ("ref_code", "hotel_name", "region_name", "phone", "email",
                     "travelers__last_name", "travelers__first_name")
    list_filter = ("arrival_date", "region_name")
    inlines = [TravelerInline, BookingSaleInline]

    change_list_template = "admin/sales/familybooking/change_list.html"

    # чтобы список работал без N+1
    def get_queryset(self, request):
        qs = super().get_queryset(request)
        return qs.prefetch_related("travelers", "bookings")

    def people(self, obj):
        # короткий список имён для списка семей
        names = ["{} {}".format(t.last_name or "", t.first_name or "").strip()
                 for t in obj.travelers.all()]
        text = ", ".join(filter(None, names)) or "—"
        return Truncator(text).chars(60)
    people.short_description = "Состав семьи"

    # импорт как у вас было
    def get_urls(self):
        urls = super().get_urls()
        custom = [
            path(
                "import/",
                self.admin_site.admin_view(self.import_view),
                name="sales_familybooking_import",
            ),
        ]
        return custom + urls

    def import_view(self, request):
        if not self.has_add_permission(request):
            messages.error(request, "Недостаточно прав для импорта.")
            return redirect("admin:sales_familybooking_changelist")

        context = dict(self.admin_site.each_context(request), title="Импорт туристов")

        if request.method == "POST":
            form = TouristsImportForm(request.POST, request.FILES)
            if form.is_valid():
                up_file = form.cleaned_data.get("file")
                dry = bool(form.cleaned_data.get("dry_run", False))
                try:
                    result = tourists_excel.import_file(up_file, dry_run=dry)
                    families = result.get("families_created", 0)
                    travelers = result.get("travelers_created", 0)
                    skipped = result.get("skipped", 0)
                    msg = f"Семей: {families}, туристов: {travelers}, пропущено: {skipped}."
                    messages.success(
                        request,
                        ("Проверка прошла успешно. " if dry else "Импорт завершён. ") + msg
                    )
                    return redirect("admin:sales_familybooking_changelist")
                except Exception as e:
                    log.exception("Ошибка при импорте туристов")
                    messages.error(request, f"Ошибка импорта: {e}")
            else:
                messages.error(request, f"Проверьте форму: {form.errors.as_text()}")
        else:
            form = TouristsImportForm()

        context["form"] = form
        return TemplateResponse(request, "admin/sales/familybooking/import_form.html", context)


# ───────────────────────────────────────────────────────────────────────────────
# Traveler
@admin.register(Traveler)
class TravelerAdmin(admin.ModelAdmin):
    list_display = (
        "last_name", "first_name", "dob", "nationality", "passport",
        "passport_expiry", "gender", "doc_type", "doc_expiry", "family"
    )
    list_filter = ("gender", "doc_type", "nationality", "family")
    search_fields = ("last_name", "first_name", "passport", "email", "phone")


# ───────────────────────────────────────────────────────────────────────────────
# Прочие справочники
@admin.register(Company)
class CompanyAdmin(admin.ModelAdmin):
    list_display = ("name", "slug", "email_for_orders", "is_active")
    search_fields = ("name", "slug", "email_for_orders")
    list_filter = ("is_active",)

@admin.register(GuideProfile)
class GuideProfileAdmin(admin.ModelAdmin):
    list_display = ("user",)
    search_fields = ("user__username", "user__email")
