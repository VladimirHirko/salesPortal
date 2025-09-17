from __future__ import annotations
import pandas as pd
from datetime import datetime
from dataclasses import dataclass, field
from typing import Dict, List, Any, Optional
from django.db import transaction
from django.utils.timezone import make_naive
from sales.models import FamilyBooking, Traveler
from sales.services import costasolinfo as csi
import re

def _norm(s: str) -> str:
    if s is None:
        return ""
    s = str(s)
    s = s.replace("\xa0", " ")          # NBSP -> обычный пробел
    s = re.sub(r"\s+", " ", s).strip()
    s = s.lower()
    # уберём лишние символы, чтобы "check-out" == "check out"
    s = re.sub(r"[^\w\sа-яё\-]", "", s, flags=re.IGNORECASE)
    s = s.replace("-", " ")
    s = re.sub(r"\s+", " ", s).strip()
    return s

def _find_col(df: pd.DataFrame, aliases: List[str]) -> Optional[str]:
    cols = [str(c).strip() for c in df.columns]
    norm_cols = {c: _norm(c) for c in cols}
    norm_alias = [_norm(a) for a in aliases]

    # сначала — точное совпадение нормализованной строки
    for c, nc in norm_cols.items():
        if nc in norm_alias:
            return c
    # затем — частичное вхождение
    for c, nc in norm_cols.items():
        if any(na in nc for na in norm_alias if na):
            return c
    return None



COLMAP = {
    "ref_code": ["Номер брони","Номер заявки","Reservation","Booking","ref","Заявка"],
    "hotel": ["Отель","Hotel","Гостиница"],
    "arrival": ["Дата заезда","Arrival","Дата прилёта","Check-in","Check in","Заезд"],
    "departure": [
        "Дата выезда","Дата отъезда","Отъезд","Выезд",
        "Дата возвращения","Возврат",
        "Departure","Return date",
        "Check-out","Check out",
        "Дата вылета","Вылет"
    ],
    "last_name": ["Фамилия","Last name","Surname"],
    "first_name": ["Имя","First name","Name"],
    "middle_name": ["Отчество","Middle name","Patronymic"],
    "dob": ["Дата рождения","DOB","Birth date"],
    "nationality": ["Национальность","Nationality"],
    "passport": ["Паспорт","Passport","Doc number"],
    "passport_expiry": ["Срок действия паспорта","Passport expiry","Expiry"],
    "phone": ["Телефон","Phone","Номер телефона","Контактный телефон"],
    "email": ["Email","E-mail","Эл. почта","Почта"],
    "note": ["Примечание","Note","Комментарий"],
}

def _find_col(df: pd.DataFrame, aliases: List[str]) -> Optional[str]:
    cols = [str(c).strip() for c in df.columns]
    for a in aliases:
        for c in cols:
            if c.lower() == a.lower():
                return c
    low_alias = [a.lower() for a in aliases]
    for c in cols:
        lc = c.lower()
        if any(a in lc for a in low_alias):
            return c
    return None

def _parse_date(v):
    if v is None or (isinstance(v, float) and pd.isna(v)) or (isinstance(v, str) and not v.strip()):
        return None
    if isinstance(v, (datetime, pd.Timestamp)):
        try:
            return make_naive(v).date() if isinstance(v, pd.Timestamp) and v.tzinfo else v.date()
        except Exception:
            return v.date() if hasattr(v, "date") else None
    for fmt in ("%d.%m.%Y","%Y-%m-%d","%d/%m/%Y","%m/%d/%Y"):
        try: return datetime.strptime(str(v).strip(), fmt).date()
        except Exception: pass
    d = pd.to_datetime(v, dayfirst=True, errors="coerce")
    return d.date() if not pd.isna(d) else None

def _resolve_hotel(name: str) -> tuple[Optional[int], str, str]:
    try:
        items = csi.search_hotels(name, limit=1) or []
        if isinstance(items, dict):
            items = items.get("items") or []
        if items:
            h = items[0]
            return h.get("id"), h.get("name") or h.get("title") or name, (h.get("region") or h.get("region_name") or "")
    except Exception:
        pass
    return None, name, ""

# ---------- НОВОЕ: авто-детекция строки заголовков ----------
def _auto_header(df0: pd.DataFrame) -> pd.DataFrame:
    """
    Если текущие имена колонок «Unnamed: …» или не совпадают с алиасами,
    пытаемся найти строку, где есть знакомые заголовки (Фамилия, Имя, Отель)
    и назначаем её как header.
    """
    # если колонок с нормальными именами уже хватает — оставляем как есть
    def _score(cols: List[str]) -> int:
        cols_l = [str(c).strip().lower() for c in cols]
        score = 0
        for key, aliases in COLMAP.items():
            for a in aliases:
                a = a.lower()
                if a in cols_l:
                    score += 1
                    break
        return score

    if _score(list(df0.columns)) >= 2:
        return df0  # уже норм

    # перебираем первые 10 строк — ищем лучшую «шапку»
    best = (None, -1)
    for i in range(min(10, len(df0))):
        row = [str(x).strip() for x in df0.iloc[i].tolist()]
        sc = _score(row)
        if sc > best[1]:
            best = (i, sc)
    header_idx, sc = best
    if header_idx is not None and sc >= 2:
        # назначаем найденную строку заголовком
        new_cols = [str(x).strip() or f"col_{j}" for j, x in enumerate(df0.iloc[header_idx].tolist())]
        df = df0.iloc[header_idx + 1 : ].copy()
        df.columns = new_cols
        return df

    # fallback: вернуть как есть
    return df0

# ---------- Отчет ----------
@dataclass
class RowIssue:
    rownum: int
    message: str
    payload: Dict[str, Any] = field(default_factory=dict)

@dataclass
class ImportReport:
    sheet: str
    total_rows: int = 0
    created_families: int = 0
    updated_families: int = 0
    created_travelers: int = 0
    issues: List[RowIssue] = field(default_factory=list)

def import_tourists_excel(file, dry_run: bool = True) -> Dict[str, Any]:
    # читаем .xlsx или .csv
    if hasattr(file, "name") and str(file.name).lower().endswith(".csv"):
        df0 = pd.read_csv(file, header=None)  # без заголовка — определим сами
        sheet_name = "CSV"
    else:
        xls = pd.ExcelFile(file)
        sheet_name = xls.sheet_names[0]
        # читаем БЕЗ заголовков, потом определим
        df0 = xls.parse(sheet_name, header=None)

    # авто-детекция header
    df = _auto_header(df0)
    report = ImportReport(sheet=sheet_name, total_rows=len(df))

    # сопоставление колонок
    cols = {key: _find_col(df, aliases) for key, aliases in COLMAP.items()}
    required = ["hotel","last_name","first_name"]
    missing = [k for k in required if not cols.get(k)]
    if missing:
        report.issues.append(RowIssue(0, f"Нет обязательных колонок: {missing}"))
        return {
            **report.__dict__,
            "column_mapping": {k: cols[k] for k in cols if cols[k]},
            "issues": [i.__dict__ for i in report.issues],
            "dry_run": dry_run,
        }

    @transaction.atomic
    def _do():
        for idx, row in df.iterrows():
            hotel_raw = str(row.get(cols["hotel"], "")).strip()
            if not hotel_raw:
                report.issues.append(RowIssue(idx+2, "Пустой отель")); continue
            hotel_id, hotel_name, region_name = _resolve_hotel(hotel_raw)

            ref_code = str(row.get(cols.get("ref_code"), "")).strip() if cols.get("ref_code") else ""
            arrival = _parse_date(row.get(cols.get("arrival"))) if cols.get("arrival") else None
            departure = _parse_date(row.get(cols.get("departure"))) if cols.get("departure") else None

            fam = (FamilyBooking.objects
                   .filter(ref_code=ref_code or "", hotel_id=hotel_id or 0)
                   .first())
            if not fam:
                fam = FamilyBooking.objects.create(
                    ref_code=ref_code or "",
                    hotel_id=hotel_id or 0,
                    hotel_name=hotel_name,
                    region_name=region_name,
                    arrival_date=arrival,
                    departure_date=departure,
                )
                report.created_families += 1
            else:
                changed = False
                if arrival and fam.arrival_date != arrival: fam.arrival_date = arrival; changed = True
                if departure and fam.departure_date != departure: fam.departure_date = departure; changed = True
                if hotel_name and fam.hotel_name != hotel_name: fam.hotel_name = hotel_name; changed = True
                if region_name and fam.region_name != region_name: fam.region_name = region_name; changed = True
                if changed:
                    fam.save(update_fields=["arrival_date","departure_date","hotel_name","region_name"])
                    report.updated_families += 1

            traveler = Traveler(
                family=fam,
                last_name=str(row.get(cols["last_name"], "")).strip(),
                first_name=str(row.get(cols["first_name"], "")).strip(),
                middle_name=str(row.get(cols.get("middle_name"), "")).strip() if cols.get("middle_name") else "",
                dob=_parse_date(row.get(cols.get("dob"))) if cols.get("dob") else None,
                nationality=str(row.get(cols.get("nationality"), "")).strip() if cols.get("nationality") else "",
                passport=str(row.get(cols.get("passport"), "")).strip() if cols.get("passport") else "",
                passport_expiry=_parse_date(row.get(cols.get("passport_expiry"))) if cols.get("passport_expiry") else None,
                phone=str(row.get(cols.get("phone"), "")).strip() if cols.get("phone") else "",
                email=str(row.get(cols.get("email"), "")).strip() if cols.get("email") else "",
                note=str(row.get(cols.get("note"), "")).strip() if cols.get("note") else "",
            )
            traveler.save()
            report.created_travelers += 1

    if dry_run:
        with transaction.atomic():
            _do()
            transaction.set_rollback(True)
    else:
        _do()

    colmap_human = {k: cols[k] for k in cols if cols[k]}
    return {**report.__dict__, "column_mapping": colmap_human, "issues": [i.__dict__ for i in report.issues], "dry_run": dry_run}
