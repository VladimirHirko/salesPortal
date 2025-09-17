from django.db import models
from django.contrib.auth.models import User

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
    STATUS = [("PENDING","PENDING"),("HOLD","HOLD"),("PAID","PAID"),("CANCELLED","CANCELLED"),("EXPIRED","EXPIRED")]
    company = models.ForeignKey(Company, on_delete=models.PROTECT)
    guide = models.ForeignKey(User, on_delete=models.PROTECT)

    # Внешние справочники (из старой системы) — только ID + snapshot имени
    excursion_id = models.IntegerField()
    excursion_title = models.CharField(max_length=255, blank=True)

    hotel_id = models.IntegerField(null=True, blank=True)
    hotel_name = models.CharField(max_length=255, blank=True)
    region_name = models.CharField(max_length=120, blank=True)

    pickup_point_id = models.IntegerField(null=True, blank=True)
    pickup_point_name = models.CharField(max_length=255, blank=True)
    pickup_time_str = models.CharField(max_length=16, blank=True)

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
    def __str__(self): return f"{self.booking_code} / {self.company}"

class FamilyBooking(models.Model):
    # Привязка к внешнему отелю через ID + снэпшот названия
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
        indexes = [models.Index(fields=["last_name", "first_name", "dob"])]
    def __str__(self): return f"{self.last_name} {self.first_name}"
