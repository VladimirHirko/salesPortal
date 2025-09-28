# sales/views_pages.py
from django.shortcuts import render
from django.views.decorators.http import require_http_methods
from django.contrib import messages

from .forms import TouristsImportForm
from .importers.tourists_excel import import_file  # ← используем адаптер

@require_http_methods(["GET", "POST"])
def tourists_import_page(request):
    """
    Страница импорта туристов из Excel/CSV.
    Форма должна быть с enctype="multipart/form-data".
    В форме есть поля:
      - file  : загружаемый файл
      - dryrun: чекбокс «Пробный запуск (без сохранения)»
    """
    if request.method == "POST":
        form = TouristsImportForm(request.POST, request.FILES)
        if not form.is_valid():
            messages.error(request, "Проверьте форму — есть ошибки.")
            return render(request, "sales/tourists_import.html", {"form": form})

        up_file = form.cleaned_data["file"]
        dry_run = form.cleaned_data.get("dryrun", True)

        try:
            # import_file сам прочитает и запустит импортёр
            report = import_file(up_file, dry_run=dry_run)

            # Сообщение пользователю
            if dry_run:
                messages.info(
                    request,
                    f"Пробный запуск: будет создано семей: {report.get('families_created', 0)}, "
                    f"туристов: {report.get('travelers_created', 0)}. "
                    f"Пропущено строк: {report.get('skipped', 0)}."
                )
            else:
                messages.success(
                    request,
                    f"Импорт выполнен: создано семей: {report.get('families_created', 0)}, "
                    f"туристов: {report.get('travelers_created', 0)}. "
                    f"Пропущено строк: {report.get('skipped', 0)}."
                )

            # Показать отчёт (если шаблон это поддерживает)
            return render(request, "sales/tourists_import.html", {
                "form": form,
                "report": report,   # можно вывести цифры и замечания
            })

        except Exception as e:
            messages.error(request, f"Ошибка импорта: {e}")
            # падаем обратно на форму
            return render(request, "sales/tourists_import.html", {"form": form})

    # GET
    form = TouristsImportForm(initial={"dryrun": True})
    return render(request, "sales/tourists_import.html", {"form": form})
