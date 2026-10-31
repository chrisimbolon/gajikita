# =============================================================================
# === backend/apps/sites/hr_views.py ===
# =============================================================================
"""
HR's Sites and Shifts screens (G2b, 27 Oct 2026).

  GET/POST   /api/hr/sites/              list / add (optionally with a first pin)
  GET/PATCH  /api/hr/sites/<id>/         one site with its pin history / edit name, kind, code, active
  POST       /api/hr/sites/<id>/pin/     move the pin (adds a row; old pins stay for history)
  GET/POST   /api/hr/shifts/             list / add
  PATCH      /api/hr/shifts/<id>/        edit

Everything is filtered by request.hr_org (see apps/organizations/permissions.py).
"""
from decimal import Decimal

from django.core.exceptions import ValidationError as DjangoValidationError
from django.db.models import Count
from django.shortcuts import get_object_or_404
from rest_framework import serializers, status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.organizations.permissions import IsCompanyHR

from .models import Shift, Site, SiteLocation


def _loc(loc):
    if loc is None:
        return None
    return {"id": str(loc.id), "latitude": float(loc.latitude), "longitude": float(loc.longitude),
            "radius_m": loc.radius_m, "valid_from": loc.valid_from.isoformat()}


def _six(value):
    return Decimal(str(round(float(value), 6)))


# ── sites ──
class SiteSerializer(serializers.ModelSerializer):
    location = serializers.SerializerMethodField()
    employee_count = serializers.SerializerMethodField()

    class Meta:
        model = Site
        fields = ["id", "name", "kind", "project_code", "is_active", "location", "employee_count", "created_at"]
        read_only_fields = ["id", "created_at"]

    def get_location(self, obj):
        return _loc(obj.location_at())

    def get_employee_count(self, obj):
        return getattr(obj, "n_employees", None)

    def validate_name(self, value):
        value = value.strip()
        qs = Site.objects.filter(organization=self.context["org"], name__iexact=value)
        if self.instance:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise serializers.ValidationError("Nama lokasi sudah dipakai.")
        return value


class PinSerializer(serializers.Serializer):
    latitude = serializers.FloatField(min_value=-90, max_value=90)
    longitude = serializers.FloatField(min_value=-180, max_value=180)
    radius_m = serializers.IntegerField(min_value=20, max_value=5000, required=False)


class SiteListView(APIView):
    permission_classes = [IsCompanyHR]

    def get(self, request):
        sites = (Site.objects.filter(organization=request.hr_org)
                 .annotate(n_employees=Count("employees", distinct=True)).order_by("-is_active", "name"))
        return Response({"success": True, "sites": SiteSerializer(sites, many=True, context={"org": request.hr_org}).data})

    def post(self, request):
        ser = SiteSerializer(data=request.data, context={"org": request.hr_org})
        ser.is_valid(raise_exception=True)
        pin = None
        if request.data.get("latitude") not in (None, "") and request.data.get("longitude") not in (None, ""):
            pin = PinSerializer(data=request.data)
            pin.is_valid(raise_exception=True)
        site = ser.save(organization=request.hr_org)
        if pin is not None:
            d = pin.validated_data
            site.move_pin(_six(d["latitude"]), _six(d["longitude"]), radius_m=d.get("radius_m"))
        return Response({"success": True, "site": SiteSerializer(site, context={"org": request.hr_org}).data},
                        status=status.HTTP_201_CREATED)


class SiteDetailView(APIView):
    permission_classes = [IsCompanyHR]

    def _site(self, request, pk):
        return get_object_or_404(Site, pk=pk, organization=request.hr_org)

    def _payload(self, request, site):
        data = SiteSerializer(site, context={"org": request.hr_org}).data
        data["history"] = [_loc(l) for l in site.locations.order_by("-valid_from")]
        return data

    def get(self, request, pk):
        return Response({"success": True, "site": self._payload(request, self._site(request, pk))})

    def patch(self, request, pk):
        site = self._site(request, pk)
        ser = SiteSerializer(site, data=request.data, partial=True, context={"org": request.hr_org})
        ser.is_valid(raise_exception=True)
        ser.save()
        return Response({"success": True, "site": self._payload(request, site)})


class SitePinView(APIView):
    permission_classes = [IsCompanyHR]

    def post(self, request, pk):
        site = get_object_or_404(Site, pk=pk, organization=request.hr_org)
        ser = PinSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        d = ser.validated_data
        try:
            site.move_pin(_six(d["latitude"]), _six(d["longitude"]), radius_m=d.get("radius_m"))
        except DjangoValidationError as err:
            return Response({"success": False, "errors": err.message_dict}, status=status.HTTP_400_BAD_REQUEST)
        data = SiteSerializer(site, context={"org": request.hr_org}).data
        data["history"] = [_loc(l) for l in site.locations.order_by("-valid_from")]
        return Response({"success": True, "site": data}, status=status.HTTP_201_CREATED)


# ── shifts ──
class ShiftSerializer(serializers.ModelSerializer):
    crosses_midnight = serializers.BooleanField(read_only=True)

    class Meta:
        model = Shift
        fields = ["id", "name", "start_time", "end_time", "grace_minutes", "working_days", "is_active",
                  "crosses_midnight"]
        read_only_fields = ["id"]

    def validate_name(self, value):
        value = value.strip()
        qs = Shift.objects.filter(organization=self.context["org"], name__iexact=value)
        if self.instance:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise serializers.ValidationError("Nama shift sudah dipakai.")
        return value

    def validate(self, attrs):
        probe = Shift(organization=self.context["org"])
        for field in ("name", "start_time", "end_time", "grace_minutes", "working_days", "is_active"):
            value = attrs.get(field, getattr(self.instance, field, None) if self.instance else None)
            if value is not None:
                setattr(probe, field, value)
        try:
            probe.clean()
        except DjangoValidationError as err:
            raise serializers.ValidationError(err.message_dict)
        return attrs


class ShiftListView(APIView):
    permission_classes = [IsCompanyHR]

    def get(self, request):
        shifts = Shift.objects.filter(organization=request.hr_org).order_by("-is_active", "start_time", "name")
        return Response({"success": True, "shifts": ShiftSerializer(shifts, many=True, context={"org": request.hr_org}).data})

    def post(self, request):
        ser = ShiftSerializer(data=request.data, context={"org": request.hr_org})
        ser.is_valid(raise_exception=True)
        shift = ser.save(organization=request.hr_org)
        return Response({"success": True, "shift": ShiftSerializer(shift, context={"org": request.hr_org}).data},
                        status=status.HTTP_201_CREATED)


class ShiftDetailView(APIView):
    permission_classes = [IsCompanyHR]

    def patch(self, request, pk):
        shift = get_object_or_404(Shift, pk=pk, organization=request.hr_org)
        ser = ShiftSerializer(shift, data=request.data, partial=True, context={"org": request.hr_org})
        ser.is_valid(raise_exception=True)
        ser.save()
        return Response({"success": True, "shift": ShiftSerializer(shift, context={"org": request.hr_org}).data})
