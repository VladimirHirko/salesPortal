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
    # ссылки на объекты старой системы будем хранить как ID (не FK)
    excursion_id = models.IntegerField()
    hotel_id = models.IntegerField(null=True, blank=True)
    pickup_point_id = models.IntegerField(null=True, blank=True)
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
