# backend/sales/services/titles.py
from __future__ import annotations

import logging
import re
from functools import lru_cache

from django.apps import apps

log = logging.getLogger(__name__)

# -----------------------------------------------------------------------------
# CSI (API) title helper

@lru_cache(maxsize=512)
def csi_title_in_lang(excursion_id: int, lang: str) -> str:
    """Пробуем получить название экскурсии из внешнего CSI в нужной локали."""
    if not excursion_id:
        return ""
    try:
        # Локальный импорт, чтобы модуль не ронялся при старте проекта без CSI.
        from sales.services import costasolinfo as csi  # type: ignore
        return (csi.excursion_title(excursion_id, lang=lang) or "").strip()
    except Exception:
        return ""

# -----------------------------------------------------------------------------
# CORE -> ES lookup (через наши модели контента)

@lru_cache(maxsize=512)
def core_es_title_by_ids(excursion_id: int) -> str:
    """
    Пытаемся достать испанское имя из core разными путями:
      1) core.Excursion(csi_id=excursion_id).name
      2) core.Excursion(id=excursion_id).name           (safety-net)
      3) core.ExcursionContentBlock(excursion__csi_id=excursion_id).excursion.name
    """
    if not excursion_id:
        return ""

    try:
        CoreExcursion = apps.get_model("core", "Excursion")
    except Exception:
        CoreExcursion = None

    try:
        CoreBlock = apps.get_model("core", "ExcursionContentBlock")
    except Exception:
        CoreBlock = None

    # 1) по csi_id
    if CoreExcursion:
        name = (
            CoreExcursion.objects
            .filter(csi_id=excursion_id)
            .values_list("name", flat=True)
            .first()
        )
        if name:
            return str(name).strip()

        # 2) safety-net: по внутреннему id
        name = (
            CoreExcursion.objects
            .filter(id=excursion_id)
            .values_list("name", flat=True)
            .first()
        )
        if name:
            return str(name).strip()

    # 3) через контентный блок
    if CoreBlock:
        name = (
            CoreBlock.objects
            .filter(excursion__csi_id=excursion_id)
            .values_list("excursion__name", flat=True)
            .first()
        )
        if name:
            return str(name).strip()

    return ""

# -----------------------------------------------------------------------------
# Эвристика: RU -> ES по топонимам

_EMOJI_OR_MISC = re.compile(r"[\u2600-\u27BF\U0001F300-\U0001FAFF]")

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

def _strip_to_toponym(ru_title: str) -> str:
    s = (ru_title or "").strip()
    s = _EMOJI_OR_MISC.sub("", s)
    # Берём основу до первого длинного тире/дефиса/двоеточия
    s = re.split(r"[—\-:]", s, maxsplit=1)[0].strip()
    # Убираем кавычки/скобки
    s = re.sub(r"[\(\)\[\]«»\"']", "", s).strip()
    return s

# -----------------------------------------------------------------------------
# Публичные функции

@lru_cache(maxsize=1024)
def spanish_excursion_name(excursion_id: int, ru_title: str) -> str:
    """
    Единая точка получения «испанского» названия:
      1) core.Excursion.name
      2) CSI API (lang='es'), укоротим по разделителю
      3) эвристика: выжать топоним из RU и замапить словарём
    """
    # 1) CORE
    es = core_es_title_by_ids(int(excursion_id or 0))
    if es:
        return es

    # 2) CSI (es)
    es_api = csi_title_in_lang(int(excursion_id or 0), "es")
    if es_api:
        short = re.split(r"[—:]", es_api, maxsplit=1)[0].strip()
        return short or es_api

    # 3) Эвристика RU -> ES
    base_ru = _strip_to_toponym(ru_title or "")
    low = base_ru.lower()
    for k in sorted(TOPONYM_RU_ES.keys(), key=len, reverse=True):
        if k in low:
            return TOPONYM_RU_ES[k]
    # Если ничего не нашли — возвращаем очищенную RU-основу или исходное RU
    return base_ru or (ru_title or "")

# --- Backward compatibility -------------------------------------------------
def excursion_title_es(excursion_id: int, ru_title: str) -> str:
    """
    Старое имя функции, которое используется в templatetags и шаблонах.
    Делегирует в spanish_excursion_name.
    """
    return spanish_excursion_name(excursion_id, ru_title)

__all__ = ["spanish_excursion_name", "excursion_title_es"]


def compose_bilingual_title(ru_title: str | None, es_title: str | None, *, html: bool = True) -> str:
    ru = (ru_title or "").strip()
    es = (es_title or "").strip()
    if not es or es.lower() == ru.lower():
        return ru
    if html:
        return f'{ru} <span class="es-title">({es})</span>'
    return f"{ru} ({es})"

