# sales/admin.py
from django.contrib import admin, messages
from django.template.response import TemplateResponse
from django.urls import path
from django.shortcuts import redirect
from .models import Company, GuideProfile, BookingSale, FamilyBooking, Traveler
from .forms import TouristsImportForm

# предположим, что у тебя есть импортёр:
# sales/importers/tourists_excel.py c функцией import_file(file, dry_run=False) -> dict
# Если имя другое — поправь импорт/вызов ниже.
from .importers import tourists_excel


@admin.register(FamilyBooking)
class FamilyBookingAdmin(admin.ModelAdmin):
    list_display = ("ref_code","hotel_name","arrival_date","departure_date","created_at")
    search_fields = ("ref_code","hotel_name","region_name","phone","email")
    list_filter = ("arrival_date","region_name")

    # добавляем кнопку «Импорт туристов» в списке
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
                dry = bool(form.cleaned_data.get("dry_run", False))   # ← безопасно берём чекбокс
                try:
                    result = tourists_excel.import_file(up_file, dry_run=dry)
                    families = result.get("families_created", 0)
                    travelers = result.get("travelers_created", 0)
                    skipped = result.get("skipped", 0)
                    msg = f"Семей: {families}, туристов: {travelers}, пропущено: {skipped}."
                    messages.success(request, ("Проверка прошла успешно. " if dry else "Импорт завершён. ") + msg)
                    return redirect("admin:sales_familybooking_changelist")
                except Exception as e:
                    messages.error(request, f"Ошибка импорта: {e}")
            else:
                # покажем причину, если форма не валидна
                messages.error(request, f"Проверьте форму: {form.errors.as_text()}")
        else:
            form = TouristsImportForm()

        context["form"] = form
        return TemplateResponse(request, "admin/sales/familybooking/import_form.html", context)



@admin.register(Traveler)
class TravelerAdmin(admin.ModelAdmin):
    list_display = ("last_name","first_name","dob","family")
    search_fields = ("last_name","first_name","passport","email","phone")
    list_filter = ("dob",)


admin.site.register(Company)
admin.site.register(GuideProfile)
admin.site.register(BookingSale)
