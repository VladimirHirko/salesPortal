from rest_framework import serializers
from sales.models import BookingSale, Company
from django.contrib.auth import get_user_model
from decimal import Decimal, ROUND_HALF_UP
from django.apps import apps
from django.db.models import Q
from django.db import transaction
from rest_framework import serializers
from .models import Company, BookingSale, Traveler, FamilyBooking
from datetime import date
from django.conf import settings
import requests


# Справочник компаний для фронта
class CompanySerializer(serializers.ModelSerializer):
    class Meta:
        model = Company
        fields = ["id", "name", "slug", "email_for_orders", "is_active"]


class TravelerMiniSerializer(serializers.ModelSerializer):
    # чтобы фронт мог прокинуть/редактировать
    gender = serializers.CharField(allow_null=True, allow_blank=True, required=False)
    doc_type = serializers.CharField(allow_null=True, allow_blank=True, required=False)
    doc_expiry = serializers.DateField(allow_null=True, required=False)

    class Meta:
        model = Traveler
        fields = (
            "id","first_name","last_name","dob","nationality","passport",
            "passport_expiry","gender","doc_type","doc_expiry","email","phone",
        )

    def validate_gender(self, v):
        if not v: return v
        s = str(v).strip().upper().rstrip(".")
        if s in ("MR","M"):  return "M"
        if s in ("MRS","MS","MISS","F"): return "F"
        raise serializers.ValidationError("gender must be M/F (or MR./MRS.)")

    def validate_doc_type(self, v):
        if not v: return v
        s = str(v).strip().lower()
        if s in ("passport","dni"): return s
        raise serializers.ValidationError("doc_type must be 'passport' or 'dni'")

# новый/уточнённый сериализатор семьи
FamilyBooking = apps.get_model('sales', 'FamilyBooking')
Traveler = apps.get_model('sales', 'Traveler')

def _is_child(dob):
    if not dob:
        return False
    today = date.today()
    age = today.year - dob.year - ((today.month, today.day) < (dob.month, dob.day))
    return age < 12

class FamilyDetailSerializer(serializers.ModelSerializer):
    checkin  = serializers.SerializerMethodField()
    checkout = serializers.SerializerMethodField()
    room     = serializers.SerializerMethodField()
    party    = serializers.SerializerMethodField()

    class Meta:
        model = FamilyBooking
        # только реально существующие поля модели + вычисляемые
        fields = ["id", "hotel_id", "hotel_name", "checkin", "checkout", "room", "party"]

    def get_checkin(self, obj):
        d = getattr(obj, "arrival_date", None)
        return d.isoformat() if d else None

    def get_checkout(self, obj):
        d = getattr(obj, "departure_date", None)
        return d.isoformat() if d else None

    def get_room(self, obj):
        # в модели комнаты пока нет — оставляем пусто (совместимо с фронтом)
        return ""

    def get_party(self, obj):
        # без предположений про related_name — явный запрос
        rows = (
            Traveler.objects
            .filter(family_id=obj.id)
            .only("id", "first_name", "last_name", "dob")
            .order_by("last_name", "first_name", "id")
        )
        out = []
        for t in rows:
            full = f"{(t.last_name or '').strip()} {(t.first_name or '').strip()}".strip()
            out.append({
                "id": t.id,
                "first_name": t.first_name,
                "last_name": t.last_name,
                "full_name": full or f"Traveler #{t.id}",
                "is_child": _is_child(getattr(t, "dob", None)),
            })
        return out

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
        if not attrs.get("date"):
            raise serializers.ValidationError("Не указана дата экскурсии.")
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

    def _resolve_region_by_hotel(self, hotel_id: int) -> str | None:
        """
        Запрашивает CostaSolinfo по hotel_id и возвращает region/region_slug.
        Возвращает None при любой ошибке или отсутствии данных.
        """
        if not hotel_id:
            return None
        # ленивые импорты, чтобы не ломать окружение при тестах
        from django.conf import settings
        import requests

        base = getattr(settings, "CSI_API_BASE", None) or getattr(settings, "CSI", {}).get("BASE")
        timeout = getattr(settings, "CSI_HTTP_TIMEOUT", 6.0)
        token = getattr(settings, "CSI", {}).get("TOKEN", "") if hasattr(settings, "CSI") else ""
        if not base:
            return None
        try:
            r = requests.get(
                f"{str(base).rstrip('/')}/api/hotels/{int(hotel_id)}/",
                headers={"Authorization": f"Bearer {token}"} if token else {},
                timeout=timeout,
            )
            if r.status_code != 200:
                return None
            data = r.json() or {}
            region = (data.get("region") or data.get("region_slug") or "").strip()
            return region or None
        except Exception:
            return None

    @transaction.atomic  # важно, чтобы всё создавалось/падало единым блоком
    def create(self, validated_data):
        from decimal import Decimal, ROUND_HALF_UP
        from django.contrib.auth import get_user_model
        from django.db.models import Q
        from django.apps import apps

        # 0) служебные поля из validated_data
        company_id = validated_data.pop("company_id")
        fam_id     = validated_data.pop("family_id", None)
        travelers  = validated_data.pop("travelers", [])  # список id (может быть пустым)

        # 0.1) сохранить CSV состава в сам объект брони
        validated_data["travelers_csv"] = ",".join(str(i) for i in travelers) if travelers else ""

        # 0.2) статус по умолчанию
        validated_data.setdefault("status", "DRAFT")

        # 1) company
        try:
            company = Company.objects.get(pk=company_id)
        except Company.DoesNotExist:
            raise serializers.ValidationError({"company_id": "Компания не найдена."})

        # 2) family (необязательная)
        family = None
        if fam_id:
            FB = apps.get_model('sales', 'FamilyBooking')
            family = FB.objects.filter(pk=fam_id).only("id", "region_name").first()
            if not family:
                raise serializers.ValidationError({"family_id": "Семья не найдена."})

        # 3) guide (фолбэк, если запрос без аутентификации)
        guide_user = self._resolve_guide()
        if not guide_user:
            raise serializers.ValidationError("Нет доступного пользователя (guide) для привязки брони.")

        # 4) per-head цены по умолчанию, если не прислали
        gross = validated_data.get("gross_total")
        try:
            gross = Decimal(gross or "0")
        except Exception:
            gross = Decimal("0")
        adults_count = max(int(validated_data.get("adults", 0)), 1)
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

        def _norm_lang(v: str) -> str:
            return (v or "").strip().lower()

        # ---- АНТИ-ДУБЛИ/КОНФЛИКТЫ -----------------------------------------------
        new_date = validated_data.get("date")
        try:
            new_excursion_id = int(validated_data.get("excursion_id") or 0)
        except Exception:
            new_excursion_id = 0
        new_lang = _norm_lang(validated_data.get("excursion_language"))
        new_travelers = set(int(x) for x in travelers) if travelers else set()
        new_pickup_id = None
        if "pickup_point_id" in validated_data:
            try:
                new_pickup_id = int(validated_data.get("pickup_point_id") or 0)
            except Exception:
                new_pickup_id = 0

        if fam_id and new_date:
            busy_statuses = ("DRAFT", "PENDING")  # при желании добавьте 'CONFIRMED'

            existing_qs = BookingSale.objects.filter(
                family_id=fam_id,
                date=new_date,
                status__in=busy_statuses,
            )

            # 1) точный дубль
            exact_qs = existing_qs.filter(excursion_id=new_excursion_id)
            if hasattr(BookingSale, "pickup_point_id") and new_pickup_id is not None:
                exact_qs = exact_qs.filter(
                    Q(pickup_point_id__isnull=True) | Q(pickup_point_id=new_pickup_id)
                )

            for b in exact_qs:
                b_ids = _to_idset(getattr(b, "travelers_csv", ""))  # пусто => set()
                if new_travelers and b_ids and new_travelers == b_ids:
                    raise serializers.ValidationError(
                        "Такая бронь уже есть на эту экскурсию/дату/пикап для этого состава (язык не влияет)."
                    )
                if not new_travelers and not b_ids:
                    if (int(validated_data.get("adults", 0)) == int(b.adults) and
                        int(validated_data.get("children", 0)) == int(b.children) and
                        int(validated_data.get("infants", 0)) == int(b.infants)):
                        raise serializers.ValidationError(
                            "Похоже на дубль: та же экскурсия/дата/пикап и одинаковые количества участников (язык не влияет)."
                        )

            # 2) конфликт по участникам в ту же дату
            if new_travelers:
                conflict_qs = existing_qs.exclude(excursion_id=new_excursion_id)
                for b in conflict_qs:
                    b_ids = _to_idset(getattr(b, "travelers_csv", ""))
                    if not b_ids:
                        continue
                    overlap = new_travelers & b_ids
                    if overlap:
                        ids_list = ", ".join(str(i) for i in sorted(overlap))
                        raise serializers.ValidationError(
                            {"travelers": [f"Конфликт: участники с ID {ids_list} уже записаны на другую экскурсию в эту дату. "
                                           f"Удалите конфликтующий черновик или измените дату."]}
                        )
        # -------------------------------------------------------------------------

        # ---- ВЫЧИСЛЯЕМ И ФИКСИРУЕМ region_name ---------------------------------
        region = (validated_data.get("region_name") or "").strip()

        # 1) если есть family.region_name — он приоритетен
        if (not region) and family and getattr(family, "region_name", None):
            reg = str(family.region_name).strip()
            if reg:
                region = reg

        # 2) иначе пробуем получить по hotel_id из CostaSolinfo
        if not region:
            hotel_id = validated_data.get("hotel_id")
            region = self._resolve_region_by_hotel(hotel_id) or ""

        # гарантированно проставим в запись (пусть даже пустую строку)
        validated_data["region_name"] = region
        # -------------------------------------------------------------------------

        # 6) создать запись
        kwargs = {
            "company": company,
            "guide": guide_user,
            "booking_code": self._make_code(),
            **validated_data,  # уже содержит status, travelers_csv и region_name
        }
        if hasattr(BookingSale, "family"):
            kwargs["family"] = family

        booking = BookingSale.objects.create(**kwargs)

        # 7) дублировать CSV (если поле есть) — по сути, уже установлено выше
        if travelers and hasattr(booking, "travelers_csv"):
            booking.travelers_csv = ",".join(str(t) for t in travelers)
            booking.save(update_fields=["travelers_csv"])

        return booking




# Для списков/деталей брони
class BookingSaleListSerializer(serializers.ModelSerializer):
    company = CompanySerializer(read_only=True)
    maps_url = serializers.SerializerMethodField()
    travelers_names = serializers.SerializerMethodField()

    class Meta:
        model = BookingSale
        fields = [
            "id", "booking_code", "status", "date",
            "excursion_id", "excursion_title",
            "hotel_id", "hotel_name", "region_name",
            "pickup_point_id", "pickup_point_name", "pickup_time_str",
            "pickup_lat", "pickup_lng", "pickup_address",
            "excursion_language", "room_number",
            "adults", "children", "infants",
            "price_source", "price_per_adult", "price_per_child",
            "gross_total", "net_total", "commission",
            "company", "created_at",
            "maps_url",
            "travelers_names",
        ]

    def get_maps_url(self, obj):
        lat = getattr(obj, "pickup_lat", None)
        lng = getattr(obj, "pickup_lng", None)
        if lat is not None and lng is not None:
            return f"https://maps.google.com/?q={lat},{lng}"
        name = getattr(obj, "pickup_point_name", None) or getattr(obj, "hotel_name", None)
        if not name:
            return None
        # аккуратный энкод (без импортов можно простым replace; полноценно — через urllib.parse.quote)
        try:
            from urllib.parse import quote
            return f"https://maps.google.com/?q={quote(str(name))}"
        except Exception:
            return f"https://maps.google.com/?q={name}"

    def get_travelers_names(self, obj):
        """
        Возвращаем список имён участников.
        1) Если есть M2M booking.travelers — берём оттуда (full_name -> first+last).
        2) Иначе читаем travelers_csv (id через запятую) и подтягиваем из Traveler,
           сохраняя порядок id. Пустые имена заменяем на 'Traveler #<id>'.
        """
        # 1) M2M, если есть
        if hasattr(obj, "travelers"):
            try:
                people = list(obj.travelers.all())
                if people:
                    out = []
                    for t in people:
                        full = getattr(t, "full_name", None)
                        if not full:
                            fn = (getattr(t, "first_name", "") or "").strip()
                            ln = (getattr(t, "last_name", "") or "").strip()
                            full = (f"{fn} {ln}").strip()
                        if not full:
                            full = f"Traveler #{getattr(t, 'id', '')}".strip()
                        out.append(full)
                    if out:
                        return out
            except Exception:
                # упадём на CSV-флоу ниже
                pass

        # 2) CSV fallback
        csv_raw = (getattr(obj, "travelers_csv", "") or "").strip()
        if not csv_raw:
            return []

        try:
            ids = [int(p.strip()) for p in csv_raw.split(",") if p.strip().isdigit()]
        except Exception:
            ids = []
        if not ids:
            return []

        Traveler = apps.get_model("sales", "Traveler")
        rows = Traveler.objects.filter(id__in=ids).values("id", "full_name", "first_name", "last_name")
        by_id = {}
        for r in rows:
            name = (r.get("full_name") or "").strip()
            if not name:
                fn = (r.get("first_name") or "").strip()
                ln = (r.get("last_name") or "").strip()
                name = (f"{fn} {ln}").strip()
            if not name:
                name = f"Traveler #{r['id']}"
            by_id[r["id"]] = name

        # сохранить порядок CSV и выкинуть пустые/отсутствующие
        return [by_id[i] for i in ids if by_id.get(i)]



class BookingSaleDetailSerializer(BookingSaleListSerializer):
    """
    Детальная версия брони: всё то же, что в списке, + полный набор полей каждого туриста.
    Поддерживает оба варианта хранения участников: M2M booking.travelers или CSV id в travelers_csv.
    """
    travelers_full = serializers.SerializerMethodField()

    class Meta(BookingSaleListSerializer.Meta):
        fields = BookingSaleListSerializer.Meta.fields + ["travelers_full"]

    def get_travelers_full(self, obj):
        # 1) Если есть M2M — берём оттуда и сортируем по id
        if hasattr(obj, "travelers"):
            try:
                qs = list(obj.travelers.all().order_by("id"))
                if qs:
                    return [
                        TravelerMiniSerializer(t).data
                        for t in qs
                    ]
            except Exception:
                pass

        # 2) Фолбэк по CSV (сохраняем порядок из CSV)
        csv_raw = (getattr(obj, "travelers_csv", "") or "").strip()
        if not csv_raw:
            return []

        try:
            ids = [int(p.strip()) for p in csv_raw.split(",") if p.strip().isdigit()]
        except Exception:
            ids = []
        if not ids:
            return []

        Traveler = apps.get_model("sales", "Traveler")
        rows = Traveler.objects.filter(id__in=ids)
        by_id = {t.id: t for t in rows}
        out = []
        for tid in ids:
            t = by_id.get(tid)
            if t:
                out.append(TravelerMiniSerializer(t).data)
        return out
