# sales/services/titles.py
from __future__ import annotations
import re
from functools import lru_cache
from django.apps import apps
from sales.services import costasolinfo as csi

# мини-словарь на всякий случай
TOPONYM_RU_ES = {
    "севилья": "Sevilla",
    "гибралтар": "Gibraltar",
    "кордоба": "Córdoba",
    "ронда": "Ronda",
    "танжер": "Tánger",
    "каминито дель рей": "Caminito del Rey",
    "нерха и фрихилиана": "Nerja y Frigiliana",
    "королевская тропа": "Caminito del Rey",
}
_EMOJI = re.compile(r"[\u2600-\u27BF\U0001F300-\U0001FAFF]")

def _strip_to_toponym(ru_title: str) -> str:
    s = (ru_title or "").strip()
    s = _EMOJI.sub("", s)
    s = re.split(r"[—\-:]", s, maxsplit=1)[0].strip()   # до первого «—», «-» или «:»
    s = re.sub(r"[\(\)\[\]«»\"']", "", s).strip()
    return s

def _short(s: str) -> str:
    """Обрезаем длинные варианты до первого разделителя."""
    if not s:
        return ""
    return re.split(r"[—:]", s, maxsplit=1)[0].strip()

@lru_cache(maxsize=512)
def excursion_title_es(excursion_id: int | None, fallback_ru: str = "") -> str:
    """
    Возвращает испанское «краткое» название экскурсии.
    Приоритет:
      1) Core.Excursion (title_es/name/title)
      2) CSI: csi.excursion_title(lang='es')
      3) Эвристика: словарик по русскому заголовку
      4) Фолбэк: очищенный русский топоним
    """
    if not excursion_id:
        excursion_id = 0

    # 1) Core
    try:
        Exc = apps.get_model("core", "Excursion")
        # Под разные схемы: пробуем найти поле title_es / name / title
        ex = Exc.objects.only("id").get(pk=excursion_id)
        for attr in ("title_es", "name", "title"):
            if hasattr(ex, attr):
                val = getattr(ex, attr) or ""
                if val:
                    return _short(val)
    except Exception:
        pass

    # 2) Источник (CSI)
    try:
        es = csi.excursion_title(excursion_id, lang="es") or ""
        if es:
            return _short(es)
    except Exception:
        pass

    # 3) Словарик по русскому
    base_ru = _strip_to_toponym(fallback_ru)
    low = base_ru.lower()
    for key in sorted(TOPONYM_RU_ES.keys(), key=len, reverse=True):
        if key in low:
            return TOPONYM_RU_ES[key]

    # 4) Последний фолбэк
    return base_ru or "Excursión"
