# backend/sales/cache.py
from urllib.parse import quote_plus

def make_key(key: str, key_prefix: str, version: int) -> str:
    """
    Делает безопасный для Memcached ключ:
    - экранирует пробелы/спецсимволы
    - добавляет префикс и версию
    - не превышает лимит 250 символов
    """
    safe = quote_plus(key or "")
    composed = f"{key_prefix}:{version}:{safe}"
    return composed[:240]  # небольшой запас под внутренние добавки бекенда
