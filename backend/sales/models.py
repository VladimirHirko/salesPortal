# backend/sales/models.py
from django.db import models
from django.contrib.auth.models import User
from django.conf import settings
import re
import logging
from functools import lru_cache
from decimal import Decimal

log = logging.getLogger(__name__)

# ───── Справочники ────────────────────────────────────────────────────────────
LANG_CHOICES = (
    ("ru", "Русский"),
    ("en", "English"),
    ("es", "Español"),
    ("fr", "Français"),
    ("de", "Deutsch"),
)

PRICE_SOURCE = (
    ("PICKUP", "По данным pickup/v2"),
    ("REGION", "По региональным ценам"),
    ("MANUAL", "Указано вручную"),
)

# ───── Utils ──────────────────────────────────────────────────────────────────
def _norm_name(s: str) -> str:
    s = (s or "").strip()
    s = re.sub(r"\s+", " ", s)
    return s.title()

# ───── Базовые цены НЕТТО ─────-───────────────────────────────────────────────
# кэшируем вызовы к CSI, чтобы в админке не дёргать API по сто раз
@lru_cache(maxsize=512)
def _exc_title_cached(excursion_id: int, lang: str = "ru") -> str:
    try:
        from .services import costasolinfo as csi
        return csi.excursion_title(int(excursion_id), lang=lang) or ""
    except Exception:
        return ""

class ExcursionNetPrice(models.Model):
    # строковая ссылка, чтобы избежать NameError
    company = models.ForeignKey(
        'sales.Company',  # или просто 'Company', если модель в этом же app
        null=True, blank=True,
        on_delete=models.SET_NULL,
        related_name='net_prices',
        help_text="Если пусто — цена действует для всех компаний",
    )

    excursion_id = models.IntegerField(db_index=True)
    region_slug   = models.SlugField(max_length=32, blank=True, db_index=True,
                                     help_text="Например: malaga, cds, marbella, estepona")
    currency      = models.CharField(max_length=3, default="EUR")

    net_per_adult = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    net_per_child = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    child_discount_pct = models.DecimalField(max_digits=5, decimal_places=2, default=Decimal('25'))

    valid_from = models.DateField(null=True, blank=True)
    valid_to   = models.DateField(null=True, blank=True)
    is_active  = models.BooleanField(default=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = (('company', 'excursion_id', 'region_slug'),)
        ordering = ['excursion_id', 'region_slug']

    def __str__(self):
        return f"net ex#{self.excursion_id} [{self.region_slug or 'all'}]"

    def effective_child_net(self):
        """Если нет явной детской цены — применяем скидку от взрослой."""
        if self.net_per_child is not None:
            return self.net_per_child
        if self.net_per_adult is None:
            return None
        pct = self.child_discount_pct or Decimal('25')
        return (self.net_per_adult * (Decimal('100') - pct) / Decimal('100')).quantize(Decimal('0.01'))


# ───── Базовые справочники ────────────────────────────────────────────────────
class Company(models.Model):
    name = models.CharField(max_length=120)
    slug = models.SlugField(unique=True)
    email_for_orders = models.EmailField(blank=True, null=True)
    is_active = models.BooleanField(default=True)
    def __str__(self): return self.name

class GuideProfile(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE)
    companies = models.ManyToManyField(Company, blank=True)
    def __str__(self): return self.user.get_username()

# ───── Семейные брони / туристы ───────────────────────────────────────────────
class FamilyBooking(models.Model):
    ref_code = models.CharField("Номер брони/заявки", max_length=64, db_index=True, blank=True)
    hotel_id = models.IntegerField()
    hotel_name = models.CharField(max_length=255, blank=True)
    region_name = models.CharField(max_length=120, blank=True)

    arrival_date = models.DateField(null=True, blank=True)
    departure_date = models.DateField(null=True, blank=True)
    phone = models.CharField(max_length=64, blank=True)
    email = models.EmailField(blank=True)
    comment = models.TextField(blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            models.Index(fields=["hotel_id", "arrival_date"]),
            models.Index(fields=["ref_code"]),
        ]
        ordering = ["-arrival_date", "hotel_name"]

    def __str__(self):
        return f"{self.ref_code or '—'} @ {self.hotel_name}"

class Traveler(models.Model):
    family = models.ForeignKey(FamilyBooking, on_delete=models.CASCADE, related_name="travelers")
    first_name = models.CharField(max_length=64)
    last_name  = models.CharField(max_length=64)
    middle_name = models.CharField(max_length=64, blank=True)
    dob = models.DateField("Дата рождения", null=True, blank=True)
    nationality = models.CharField(max_length=64, blank=True)
    passport = models.CharField(max_length=64, blank=True)
    passport_expiry = models.DateField(null=True, blank=True)
    phone = models.CharField(max_length=64, blank=True)
    email = models.EmailField(blank=True)
    note = models.CharField(max_length=255, blank=True)
    gender = models.CharField(max_length=1, choices=[('M','Male'),('F','Female')], null=True, blank=True)
    doc_type = models.CharField(max_length=16, choices=[('passport','Passport'),('dni','DNI')], null=True, blank=True)
    doc_expiry = models.DateField(null=True, blank=True)

    class Meta:
        unique_together = [("family", "last_name", "first_name", "dob")]
        indexes = [
            models.Index(fields=["family", "last_name", "first_name", "dob"]),
            models.Index(fields=["last_name", "first_name", "dob"]),
        ]

    def save(self, *args, **kwargs):
        self.last_name = _norm_name(self.last_name)
        self.first_name = _norm_name(self.first_name)
        self.middle_name = _norm_name(self.middle_name)
        super().save(*args, **kwargs)

    def __str__(self): return f"{self.last_name} {self.first_name}"

# ───── Проданные экскурсии ────────────────────────────────────────────────────
class BookingSale(models.Model):
    STATUS = [
        ("DRAFT","DRAFT"),
        ("PENDING","PENDING"),
        ("HOLD","HOLD"),
        ("PAID","PAID"),
        ("CANCELLED","CANCELLED"),
        ("EXPIRED","EXPIRED"),
    ]

    company = models.ForeignKey(Company, on_delete=models.PROTECT)
    guide = models.ForeignKey(User, on_delete=models.PROTECT)

    family = models.ForeignKey(
        'FamilyBooking', on_delete=models.SET_NULL,
        null=True, blank=True, related_name="bookings"
    )

    # внешние справочники (снэпшоты)
    excursion_id = models.IntegerField()
    excursion_title = models.CharField(max_length=255, blank=True)

    hotel_id = models.IntegerField(null=True, blank=True)
    hotel_name = models.CharField(max_length=255, blank=True)
    region_name = models.CharField(max_length=120, blank=True)  # заполним автоматически в save()

    pickup_point_id = models.IntegerField(null=True, blank=True)
    pickup_point_name = models.CharField(max_length=255, blank=True)
    pickup_time_str = models.CharField(max_length=16, blank=True)

    # география точки сбора (снапшот)
    pickup_lat = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    pickup_lng = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    pickup_address = models.CharField(max_length=255, blank=True)

    # состав группы (CSV-idшники под SQLite)
    travelers_csv = models.TextField(blank=True)  # "12,15,33"

    # статус
    status = models.CharField(max_length=10, choices=STATUS, default="DRAFT", db_index=True)

    # батч-отправка
    batch_code = models.CharField(max_length=20, blank=True)
    sent_at = models.DateTimeField(null=True, blank=True)
    sent_to_email = models.EmailField(blank=True)

    # язык экскурсии, выбранный туристом
    excursion_language = models.CharField(max_length=5, choices=LANG_CHOICES, blank=True)

    # номер комнаты
    room_number = models.CharField(max_length=20, blank=True)

    # источник цены + пер-голова
    price_source = models.CharField(max_length=10, choices=PRICE_SOURCE, default="PICKUP")
    price_per_adult = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    price_per_child = models.DecimalField(max_digits=10, decimal_places=2, default=0)

    # состав и суммы
    date = models.DateField()
    adults = models.PositiveIntegerField(default=1)
    children = models.PositiveIntegerField(default=0)
    infants = models.PositiveIntegerField(default=0)

    gross_total = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    net_total = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    commission = models.DecimalField(max_digits=10, decimal_places=2, default=0)

    # аннуляции
    cancelled_at = models.DateTimeField(null=True, blank=True)
    cancel_reason = models.TextField(null=True, blank=True, default='')

    # прочее
    payment_method = models.CharField(max_length=30, blank=True)
    booking_code = models.CharField(max_length=20, unique=True)

    created_at = models.DateTimeField(auto_now_add=True)

    # ---------- УТИЛИТЫ -------------------------------------------------------
    def maps_url(self):
        if self.pickup_lat and self.pickup_lng:
            return f"https://maps.google.com/?q={self.pickup_lat},{self.pickup_lng}"
        if self.pickup_point_name:
            from urllib.parse import quote_plus
            return "https://maps.google.com/?q=" + quote_plus(self.pickup_point_name)
        return ""

    # ---------- ИСТОЧНИКИ РЕГИОНА ---------------------------------------------
    def _resolve_region_from_family(self):
        fam = getattr(self, "family", None)
        reg = (getattr(fam, "region_name", "") or "").strip() if fam else ""
        return reg or None

    def _resolve_region_from_service(self):
        """Пробуем локальную обёртку sales.services.costasolinfo (без прямого HTTP)."""
        try:
            from sales.services import costasolinfo as csi
        except Exception:
            return None

        hotel_id = getattr(self, "hotel_id", None)
        hotel_name = (getattr(self, "hotel_name", "") or "").strip()

        # по id
        if hotel_id:
            try:
                if hasattr(csi, "hotel_by_id"):
                    data = csi.hotel_by_id(int(hotel_id)) or {}
                    reg = (data.get("region") or data.get("region_slug") or "").strip()
                    if reg:
                        return reg
                if hasattr(csi, "region_for_hotel_id"):
                    reg = (csi.region_for_hotel_id(int(hotel_id)) or "").strip()
                    if reg:
                        return reg
            except Exception as e:
                log.debug("CSI service by id failed: %s", e)

        # по имени
        if hotel_name and hasattr(csi, "region_for_hotel"):
            try:
                reg = (csi.region_for_hotel(hotel_name) or "").strip()
                if reg:
                    return reg
            except Exception as e:
                log.debug("CSI service by name failed: %s", e)

        return None

    def _resolve_region_from_api(self):
        """Прямой HTTP к CostaSolinfo по hotel_id (если CSI_API_BASE задан)."""
        hotel_id = getattr(self, "hotel_id", None)
        if not hotel_id:
            return None
        try:
            from django.conf import settings
            import requests
        except Exception:
            return None

        base = getattr(settings, "CSI_API_BASE", None) or getattr(settings, "CSI", {}).get("BASE")
        if not base:
            return None

        timeout = getattr(settings, "CSI_HTTP_TIMEOUT", 6.0)
        token = getattr(settings, "CSI", {}).get("TOKEN", "") if hasattr(settings, "CSI") else ""
        try:
            r = requests.get(
                f"{str(base).rstrip('/')}/api/hotels/{int(hotel_id)}/",
                headers={"Authorization": f"Bearer {token}"} if token else {},
                timeout=timeout,
            )
            if r.status_code != 200:
                return None
            data = r.json() or {}
            reg = (data.get("region") or data.get("region_slug") or "").strip()
            return reg or None
        except Exception:
            return None

    def _resolve_region_from_text(self):
        """
        Безвебовый фолбэк: пробуем распознать регион по тексту
        pickup_point_name/hotel_name. Работает офлайн.
        """
        raw = " ".join([
            (self.pickup_point_name or ""),
            (self.hotel_name or "")
        ]).lower()

        # быстрые метки
        if " cds" in " " + raw or raw.startswith("cds") or "costa del sol" in raw:
            return "CDS"
        if "marbella" in raw:
            return "Marbella"
        if "estepona" in raw:
            return "Estepona"
        if "malaga" in raw or "málaga" in raw:
            return "Malaga"

        # часто в названии pickup-а уже есть суффикс типа "Riu CDS"
        if " cds" in raw or "cds " in raw:
            return "CDS"

        return None

    def ensure_region_name(self):
        """
        Цепочка: Family → локальный сервис → прямой API → текстовый фолбэк.
        """
        current = (self.region_name or "").strip()
        if current:
            return current

        reg = (
            self._resolve_region_from_family()
            or self._resolve_region_from_service()
            or self._resolve_region_from_api()
            or self._resolve_region_from_text()
        )
        if reg:
            self.region_name = reg
            return reg

        log.warning(
            "Region unresolved for booking %s (family_id=%s, hotel_id=%s, hotel_name=%r, pickup=%r)",
            getattr(self, "booking_code", "?"),
            getattr(self, "family_id", None),
            getattr(self, "hotel_id", None),
            self.hotel_name, self.pickup_point_name
        )
        return None

    # ---------- СИСТЕМНАЯ ЛОГИКА ---------------------------------------------
    def save(self, *args, **kwargs):
        self.ensure_region_name()  # гарантируем автозаполнение
        super().save(*args, **kwargs)

    class Meta:
        indexes = [
            models.Index(fields=["company", "date"]),
            models.Index(fields=["excursion_id", "date"]),
            models.Index(fields=["excursion_language"]),
            models.Index(fields=["status"]),
        ]

    def __str__(self): 
        return f"{self.booking_code} / {self.company}"


# ───── Входящие письма (опционально, остаётся) ───────────────────────────────
class InboundEmail(models.Model):
    uid = models.CharField(max_length=64, unique=True)  # IMAP UID сообщения
    message_id = models.CharField(max_length=255, blank=True, null=True)
    subject = models.CharField(max_length=512, blank=True, null=True)
    from_email = models.CharField(max_length=255, blank=True, null=True)
    to_email = models.CharField(max_length=255, blank=True, null=True)
    date = models.DateTimeField(blank=True, null=True)

    snippet = models.TextField(blank=True, null=True)
    body_text = models.TextField(blank=True, null=True)
    body_html = models.TextField(blank=True, null=True)

    raw_headers = models.TextField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    booking = models.ForeignKey("BookingSale", null=True, blank=True, on_delete=models.SET_NULL)

    class Meta:
        ordering = ["-date", "-id"]

    def __str__(self):
        return f"{self.subject or '(без темы)'} — {self.from_email}"

# ───── ПРОКСИ-модель для админки «Аннулированные брони» ──────────────────────
class CancelledBookingSale(BookingSale):
    class Meta:
        proxy = True
        verbose_name = "Cancelled booking"
        verbose_name_plural = "Cancelled bookings"
