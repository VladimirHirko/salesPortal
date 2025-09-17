# sales/views_pages.py
from django.shortcuts import render
from django.views.decorators.http import require_http_methods
from django.contrib import messages
from .forms import TouristsImportForm
from .importers.tourists_excel import import_tourists_excel

@require_http_methods(["GET", "POST"])
def tourists_import_page(request):
    if request.method == "POST":
        form = TouristsImportForm(request.POST, request.FILES)
        if form.is_valid():
            f = form.cleaned_data["file"]
            dry = form.cleaned_data["dryrun"]
            try:
                report = import_tourists_excel(f, dry_run=dry)
                if report.get("issues"):
                    messages.warning(request, "Импорт завершён с замечаниями.")
                else:
                    messages.success(request, "Импорт завершён успешно.")
                return render(request, "sales/tourists_import.html", {
                    "form": form,
                    "report": report,
                })
            except Exception as e:
                messages.error(request, f"Ошибка импорта: {e}")
    else:
        form = TouristsImportForm()
    return render(request, "sales/tourists_import.html", {"form": form})
