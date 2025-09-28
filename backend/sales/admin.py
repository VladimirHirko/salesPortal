# sales/admin.py
from django.contrib import admin, messages
from django.template.response import TemplateResponse
from django.urls import path
from django.shortcuts import redirect
from django.utils.html import format_html
from django.core.management import call_command

from .models import Company, GuideProfile, BookingSale, FamilyBooking, Traveler, InboundEmail
from .forms import TouristsImportForm
from .importers import tourists_excel  # импортёр Excel

import logging
log = logging.getLogger(__name__)

@admin.action(description="Проверить входящие Gmail сейчас")
def fetch_gmail_now(modeladmin, request, queryset):
    call_command("fetch_gmail")
    modeladmin.message_user(request, "Готово: входящие обновлены.")

@admin.register(InboundEmail)
class InboundEmailAdmin(admin.ModelAdmin):
    list_display = ("subject","from_email","date","created_at")
    search_fields = ("subject","from_email","to_email","snippet","body_text")
    readonly_fields = ("uid","message_id","raw_headers","created_at","html_preview")

    actions = [fetch_gmail_now]

    def html_preview(self, obj):
        return format_html('<div style="border:1px solid #eee;padding:8px;">{}</div>', obj.body_html or "—")
    html_preview.short_description = "HTML"

# ── BookingSale ─────────────────────────────────────────────────────────────────
@admin.register(BookingSale)
class BookingSaleAdmin(admin.ModelAdmin):
    list_display = (
        "booking_code", "company", "excursion_title", "date",
        "hotel_name", "pickup_point_name", "pickup_time_str",
        "excursion_language", "room_number",
        "adults", "children", "gross_total", "status",
    )
    list_filter = ("company", "status", "excursion_language", "date")
    search_fields = ("booking_code", "excursion_title", "hotel_name",
                     "pickup_point_name", "room_number")
    readonly_fields = ("created_at",)

    actions = ["export_bookings_xlsx"]

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

        # шапка
        for i,(title,_) in enumerate(cols, start=1):
            ws.cell(row=1, column=i, value=title)

        # строки
        r = 2
        for obj in queryset:
            for c,(title,field) in enumerate(cols, start=1):
                if callable(field):
                    val = field(obj)
                else:
                    val = getattr(obj, field, "")
                ws.cell(row=r, column=c, value=val)
            r += 1

        # автоподбор ширины
        for i in range(1, len(cols)+1):
            ws.column_dimensions[get_column_letter(i)].width = 18

        resp = HttpResponse(
            content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )
        resp['Content-Disposition'] = 'attachment; filename="bookings.xlsx"'
        wb.save(resp)
        return resp

    export_bookings_xlsx.short_description = "Экспортировать выбранные брони в Excel"
    
# ── FamilyBooking ──────────────────────────────────────────────────────────────
@admin.register(FamilyBooking)
class FamilyBookingAdmin(admin.ModelAdmin):
    list_display = ("ref_code", "hotel_name", "arrival_date", "departure_date", "created_at")
    search_fields = ("ref_code", "hotel_name", "region_name", "phone", "email")
    list_filter = ("arrival_date", "region_name")

    change_list_template = "admin/sales/familybooking/change_list.html"

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
                    # логируем полный traceback в консоль/файл
                    log.exception("Ошибка при импорте туристов")
                    # пользователю выводим короткое сообщение
                    messages.error(request, f"Ошибка импорта: {e}")
            else:
                messages.error(request, f"Проверьте форму: {form.errors.as_text()}")
        else:
            form = TouristsImportForm()

        context["form"] = form
        return TemplateResponse(request, "admin/sales/familybooking/import_form.html", context)

# ── Traveler ───────────────────────────────────────────────────────────────────
@admin.register(Traveler)
class TravelerAdmin(admin.ModelAdmin):
    list_display = ("last_name","first_name","dob","nationality","passport","passport_expiry","gender","doc_type","doc_expiry","family")
    list_filter  = ("gender","doc_type","nationality","family")
    search_fields = ("last_name","first_name","passport","email","phone")

# ── Прочие справочники (одиночная регистрация, без дублей) ─────────────────────
@admin.register(Company)
class CompanyAdmin(admin.ModelAdmin):
    list_display = ("name", "slug", "email_for_orders", "is_active")
    search_fields = ("name", "slug", "email_for_orders")
    list_filter = ("is_active",)

@admin.register(GuideProfile)
class GuideProfileAdmin(admin.ModelAdmin):
    list_display = ("user",)
    search_fields = ("user__username", "user__email")
