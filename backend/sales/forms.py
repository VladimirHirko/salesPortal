# sales/forms.py
from django import forms

class TouristsImportForm(forms.Form):
    file = forms.FileField(label="Файл с туристами (Excel/CSV)")
    dry_run = forms.BooleanField(label="Только проверка", required=False)
