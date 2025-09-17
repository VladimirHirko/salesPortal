# sales/forms.py
from django import forms

class TouristsImportForm(forms.Form):
    file = forms.FileField(
        label="Файл Excel/CSV",
        help_text="Поддерживается .xlsx (рекомендовано) и .csv"
    )
    dryrun = forms.BooleanField(
        label="Dry-run (проверка без сохранения)",
        initial=True,
        required=False
    )
