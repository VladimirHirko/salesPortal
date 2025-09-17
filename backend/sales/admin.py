# sales/admin.py
from django.contrib import admin
from .models import Company, GuideProfile, BookingSale, FamilyBooking, Traveler

@admin.register(FamilyBooking)
class FamilyBookingAdmin(admin.ModelAdmin):
    list_display = ("ref_code","hotel_name","arrival_date","departure_date","created_at")
    search_fields = ("ref_code","hotel_name","region_name","phone","email")
    list_filter = ("arrival_date","region_name")

@admin.register(Traveler)
class TravelerAdmin(admin.ModelAdmin):
    list_display = ("last_name","first_name","dob","family")
    search_fields = ("last_name","first_name","passport","email","phone")
    list_filter = ("dob",)

admin.site.register(Company)
admin.site.register(GuideProfile)
admin.site.register(BookingSale)
