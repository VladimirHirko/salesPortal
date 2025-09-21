from rest_framework import serializers
from sales.models import BookingSale, Company
from django.contrib.auth import get_user_model
from decimal import Decimal, ROUND_HALF_UP
from django.apps import apps
from django.db.models import Q


# Справочник компаний для фронта
class CompanySerializer(serializers.ModelSerializer):
    class Meta:
        model = Company
        fields = ["id", "name", "slug", "email_for_orders", "is_active"]


# Создание/подтверждение брони
class BookingSaleCreateSerializer(serializers.ModelSerializer):
    # входные «служебные» поля (не из модели)
    company_id = serializers.IntegerField(required=True, write_only=True)
    family_id = serializers.IntegerField(required=False, allow_null=True, write_only=True)
    travelers = serializers.ListField(
        child=serializers.IntegerField(),
        required=False, write_only=True
    )

    # бизнес-параметры
    excursion_language = serializers.ChoiceField(
        choices=BookingSale._meta.get_field("excursion_language").choices,
        required=True
    )
    room_number = serializers.CharField(required=False, allow_blank=True)

    price_source = serializers.ChoiceField(
        choices=BookingSale._meta.get_field("price_source").choices,
        required=False, default="PICKUP"
    )
    price_per_adult = serializers.DecimalField(max_digits=10, decimal_places=2, required=False)
    price_per_child = serializers.DecimalField(max_digits=10, decimal_places=2, required=False)

    # принимаем координаты/адрес точки сбора с фронта
    pickup_lat = serializers.DecimalField(max_digits=9, decimal_places=6, required=False, allow_null=True)
    pickup_lng = serializers.DecimalField(max_digits=9, decimal_places=6, required=False, allow_null=True)
    pickup_address = serializers.CharField(required=False, allow_blank=True)

    class Meta:
        model = BookingSale
        fields = [
            # основные
            "date", "adults", "children", "infants",
            "excursion_id", "excursion_title",
            "hotel_id", "hotel_name", "region_name",
            "pickup_point_id", "pickup_point_name", "pickup_time_str",
            # новые для точки сбора
            "pickup_lat", "pickup_lng", "pickup_address",
            # новые для компании/языка/комнаты
            "company_id", "family_id", "excursion_language", "room_number",
            # цены
            "price_source", "price_per_adult", "price_per_child",
            "gross_total", "net_total", "commission",
            # список туристов (входной)
            "travelers",
        ]

    def validate(self, attrs):
        if attrs.get("adults", 0) <= 0 and attrs.get("children", 0) <= 0:
            raise serializers.ValidationError("Нужно хотя бы 1 участник.")
        if not attrs.get("excursion_id"):
            raise serializers.ValidationError("Не указана экскурсия.")
        return attrs

    def _resolve_user(self):
        """Возвращаем авторизованного пользователя или dev-фолбэк."""
        req = self.context.get("request")
        user = getattr(req, "user", None)
        if getattr(user, "is_authenticated", False):
            return user
        User = get_user_model()
        return (
            User.objects.filter(is_active=True)
            .order_by("-is_superuser", "-is_staff", "id")
            .first()
        )

    def _resolve_guide(self):
        req = self.context.get("request")
        if req and getattr(req.user, "is_authenticated", False):
            return req.user
        User = get_user_model()
        return (
            User.objects.filter(is_active=True)
            .order_by("-is_superuser", "-is_staff", "id")
            .first()
        )

    def _make_code(self) -> str:
        from django.utils.crypto import get_random_string
        return get_random_string(10).upper()

    def create(self, validated_data):
        # 1) company
        company_id = validated_data.pop("company_id")
        try:
            company = Company.objects.get(pk=company_id)
        except Company.DoesNotExist:
            raise serializers.ValidationError({"company_id": "Компания не найдена."})

        # 2) family (необязательная)
        fam_id = validated_data.pop("family_id", None)
        family = None
        if fam_id:
            FB = apps.get_model('sales', 'FamilyBooking')  # безопасно, без прямого импорта
            if FB:
                family = FB.objects.filter(pk=fam_id).first()

        # 3) travelers (если шлёте массив id — можно сохранить в CSV, если поле есть)
        travelers = validated_data.pop("travelers", [])  # не упадём, если не прислали

        # 4) guide (фолбэк, если запрос без аутентификации)
        User = get_user_model()
        guide_user = self.context.get("request").user if self.context.get("request") else None
        if not getattr(guide_user, "is_authenticated", False):
            guide_user = (
                User.objects.filter(is_active=True)
                .order_by("-is_superuser", "-is_staff", "id")
                .first()
            )
        if not guide_user:
            raise serializers.ValidationError("Нет доступного пользователя (guide) для привязки брони.")

        # 5) пер-голова цены по умолчанию, если не прислали
        gross = validated_data.get("gross_total") or Decimal("0")
        adults_count = max(int(validated_data.get("adults", 1)), 1)
        validated_data.setdefault(
            "price_per_adult",
            (gross / Decimal(adults_count)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        )
        validated_data.setdefault("price_per_child", Decimal("0.00"))

        def _to_idset(csv_str):
            if not csv_str:
                return set()
            out = set()
            for p in str(csv_str).split(","):
                p = p.strip()
                if p.isdigit():
                    out.add(int(p))
            return out

        # ---- АНТИ-ДУБЛИ/КОНФЛИКТЫ -----------------------------------------------
        new_date = validated_data.get("date")
        new_excursion_id = int(validated_data.get("excursion_id") or 0)
        new_lang = (validated_data.get("excursion_language") or "").strip().lower()
        new_travelers = set(int(x) for x in travelers) if travelers else set()

        if fam_id and new_date:
            # какие статусы учитываем как «занято»
            busy_statuses = ("DRAFT", "PENDING")  # при желании добавь CONFIRMED

            existing_qs = BookingSale.objects.filter(
                family_id=fam_id,
                date=new_date,
                status__in=busy_statuses,
            )

            # 1) точный дубль: та же экскурсия, тот же язык и тот же состав
            exact_qs = existing_qs.filter(excursion_id=new_excursion_id)
            if hasattr(BookingSale, "excursion_language"):
                exact_qs = exact_qs.filter(
                    Q(excursion_language__isnull=True, ) | Q(excursion_language__iexact=new_lang)
                )

            for b in exact_qs:
                b_ids = _to_idset(getattr(b, "travelers_csv", ""))  # пусто => set()
                if new_travelers and b_ids and new_travelers == b_ids:
                    raise serializers.ValidationError(
                        "Такая бронь уже есть: та же экскурсия, та же дата и тот же состав участников."
                    )
                # если фронт вдруг не прислал состав — подстрахуемся по числам
                if not new_travelers and not b_ids:
                    # одна и та же экскурсия + одинаковые counts — тоже считаем дублем
                    if (int(validated_data.get("adults", 0)) == int(b.adults) and
                        int(validated_data.get("children", 0)) == int(b.children) and
                        int(validated_data.get("infants", 0)) == int(b.infants)):
                        raise serializers.ValidationError(
                            "Выглядит как дублирующая бронь на ту же экскурсию и дату."
                        )

            # 2) конфликт: в ТУ ЖЕ дату участник уже едет на ДРУГУЮ экскурсию
            for b in existing_qs.exclude(excursion_id=new_excursion_id):
                b_ids = _to_idset(getattr(b, "travelers_csv", ""))
                if not new_travelers or not b_ids:
                    continue
                overlap = new_travelers & b_ids
                if overlap:
                    # можно красиво вывести id, при желании подтянуть имена
                    raise serializers.ValidationError(
                        f"Конфликт: часть участников уже записана на другую экскурсию в этот день (ID: {sorted(overlap)})."
                    )
        # -------------------------------------------------------------------------

        # 6) собираем kwargs (вот тут и используется ваш блок)
        kwargs = {
            "company": company,
            "guide": guide_user,
            "booking_code": self._make_code(),
            "status": "DRAFT",
            **validated_data,
        }
        if hasattr(BookingSale, "family"):
            kwargs["family"] = family

        booking = BookingSale.objects.create(**kwargs)

        # 7) сохраним состав (если есть соответствующее поле)
        if travelers and hasattr(booking, "travelers_csv"):
            booking.travelers_csv = ",".join(str(t) for t in travelers)
            booking.save(update_fields=["travelers_csv"])

        return booking

# Для списков/деталей брони
class BookingSaleListSerializer(serializers.ModelSerializer):
    company = CompanySerializer(read_only=True)
    # ссылка на карту строится на лету
    maps_url = serializers.SerializerMethodField()

    class Meta:
        model = BookingSale
        fields = [
            "id", "booking_code", "status", "date",
            "excursion_id", "excursion_title",
            "hotel_id", "hotel_name", "region_name",
            "pickup_point_id", "pickup_point_name", "pickup_time_str",
            # если есть в модели — будут отданы; если нет, просто игнорируй
            "pickup_lat", "pickup_lng", "pickup_address",
            "excursion_language", "room_number",
            "adults", "children", "infants",
            "price_source", "price_per_adult", "price_per_child",
            "gross_total", "net_total", "commission",
            "company", "created_at",
            "maps_url",            # ← ДОБАВЛЕНО! (это и требовал DRF)
        ]

    def get_maps_url(self, obj):
        lat = getattr(obj, "pickup_lat", None)
        lng = getattr(obj, "pickup_lng", None)
        if lat is not None and lng is not None:
            return f"https://maps.google.com/?q={lat},{lng}"
        name = getattr(obj, "pickup_point_name", None) or getattr(obj, "hotel_name", None)
        return f"https://maps.google.com/?q={name}" if name else None
