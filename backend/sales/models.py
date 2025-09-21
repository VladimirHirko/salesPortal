# backend/sales/models.py
from django.db import models
from django.contrib.auth.models import User
import re


# ↓ ДОБАВИМ справочник языков (используем на уровне брони)
LANG_CHOICES = (
    ("ru", "Русский"),
    ("en", "English"),
    ("es", "Español"),
    ("de", "Deutsch"),
)

PRICE_SOURCE = (
    ("PICKUP", "По данным pickup/v2"),
    ("REGION", "По региональным ценам"),
    ("MANUAL", "Указано вручную"),
)

# ───────────────────────────────────────────────────────────────────────────────
# utils
def _norm_name(s: str) -> str:
    """Убрать лишние пробелы, привести к Title Case. Пустое -> ''."""
    s = (s or "").strip()
    s = re.sub(r"\s+", " ", s)
    return s.title()


# ───────────────────────────────────────────────────────────────────────────────
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


class BookingSale(models.Model):
    STATUS = [
        ("DRAFT","DRAFT"),                # ← новый
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
    region_name = models.CharField(max_length=120, blank=True)

    pickup_point_id = models.IntegerField(null=True, blank=True)
    pickup_point_name = models.CharField(max_length=255, blank=True)
    pickup_time_str = models.CharField(max_length=16, blank=True)

    # NEW: география точки сбора (снапшот)
    pickup_lat = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    pickup_lng = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    pickup_address = models.CharField(max_length=255, blank=True)  # если приходит от источника

    # состав группы (любой простой формат; если SQLite — храним CSV)
    travelers_csv = models.TextField(blank=True)  # "12,15,33"  (упрощение для SQLite)

    status = models.CharField(max_length=10, choices=STATUS, default="DRAFT")  # ← по умолчанию draft

    # для батч-отправки
    batch_code = models.CharField(max_length=20, blank=True)  # сгруппировать несколько строк
    sent_at = models.DateTimeField(null=True, blank=True)     # когда ушло в офис
    sent_to_email = models.EmailField(blank=True)

    # ↓ НОВОЕ: язык экскурсии, выбранный туристом (обязателен для письма)
    excursion_language = models.CharField(
        max_length=5, choices=LANG_CHOICES, blank=True
    )
    # ↓ НОВОЕ: номер комнаты (заполняется вручную на фронте)
    room_number = models.CharField(max_length=20, blank=True)

    # ↓ НОВОЕ: фиксируем источник и «пер-голова» цены на момент брони
    price_source = models.CharField(
        max_length=10, choices=PRICE_SOURCE, default="PICKUP"
    )
    price_per_adult = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    price_per_child = models.DecimalField(max_digits=10, decimal_places=2, default=0)

    date = models.DateField()
    adults = models.PositiveIntegerField(default=1)
    children = models.PositiveIntegerField(default=0)
    infants = models.PositiveIntegerField(default=0)

    gross_total = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    net_total = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    commission = models.DecimalField(max_digits=10, decimal_places=2, default=0)

    status = models.CharField(max_length=10, choices=STATUS, default="PENDING")
    payment_method = models.CharField(max_length=30, blank=True)
    booking_code = models.CharField(max_length=20, unique=True)

    created_at = models.DateTimeField(auto_now_add=True)

    def maps_url(self):
        if self.pickup_lat and self.pickup_lng:
            return f"https://maps.google.com/?q={self.pickup_lat},{self.pickup_lng}"
        if self.pickup_point_name:
            from urllib.parse import quote_plus
            return "https://maps.google.com/?q=" + quote_plus(self.pickup_point_name)
        return ""

    class Meta:
        indexes = [
            models.Index(fields=["company", "date"]),
            models.Index(fields=["excursion_id", "date"]),
            models.Index(fields=["excursion_language"]),
        ]

    def __str__(self): return f"{self.booking_code} / {self.company}"


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
