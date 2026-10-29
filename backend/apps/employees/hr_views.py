# =============================================================================
# === backend/apps/employees/hr_views.py ===
# =============================================================================
"""
HR's Employees screen (G2b, 27 Oct 2026).

  GET/POST   /api/hr/employees/             list (?q= name or no., ?status=) / add
  GET/PATCH  /api/hr/employees/<id>/        one employee / edit
  POST       /api/hr/employees/<id>/login/  turn on phone + PIN login, or reset the PIN.
                                            Returns the PIN once, for HR to hand over.

Sites, shift and mandor can only point at things in HR's own company.
"""
from django.db.models import Q
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import serializers, status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.organizations.permissions import IsCompanyHR
from apps.sites.models import Shift, Site

from .models import Employee
from .worker_login import enable_login


class EmployeeSerializer(serializers.ModelSerializer):
    sites = serializers.PrimaryKeyRelatedField(many=True, queryset=Site.objects.none(), required=False)
    default_site = serializers.PrimaryKeyRelatedField(queryset=Site.objects.none(), allow_null=True, required=False)
    default_shift = serializers.PrimaryKeyRelatedField(queryset=Shift.objects.none(), allow_null=True, required=False)
    mandor = serializers.PrimaryKeyRelatedField(queryset=Employee.objects.none(), allow_null=True, required=False)
    has_login = serializers.SerializerMethodField()
    login_locked = serializers.SerializerMethodField()

    class Meta:
        model = Employee
        fields = [
            "id", "employee_no", "full_name", "nik", "npwp", "ptkp_status", "join_date", "end_date",
            "employment_type", "pay_type", "base_rate", "fixed_allowance", "overtime_eligible", "bank_name", "bank_account_no", "bank_account_name",
            "bpjs_kesehatan_no", "bpjs_tk_no", "phone", "sites", "default_site", "default_shift", "mandor",
            "status", "login_phone", "must_change_pin", "has_login", "login_locked", "created_at",
        ]
        read_only_fields = ["id", "login_phone", "must_change_pin", "created_at"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        org = self.context["org"]
        self.fields["sites"].child_relation.queryset = Site.objects.filter(organization=org)
        self.fields["default_site"].queryset = Site.objects.filter(organization=org)
        self.fields["default_shift"].queryset = Shift.objects.filter(organization=org)
        self.fields["mandor"].queryset = Employee.objects.filter(organization=org)

    def get_has_login(self, obj):
        return bool(obj.user_id and obj.login_phone)

    def get_login_locked(self, obj):
        return bool(obj.pin_locked_until and obj.pin_locked_until > timezone.now())

    def validate_employee_no(self, value):
        value = value.strip()
        qs = Employee.objects.filter(organization=self.context["org"], employee_no__iexact=value)
        if self.instance:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise serializers.ValidationError("No. karyawan sudah dipakai.")
        return value

    def validate(self, attrs):
        mandor = attrs.get("mandor")
        if mandor is not None and self.instance is not None and mandor.pk == self.instance.pk:
            raise serializers.ValidationError({"mandor": "Karyawan tidak bisa menjadi mandor untuk dirinya sendiri."})
        end, start = attrs.get("end_date"), attrs.get("join_date", getattr(self.instance, "join_date", None))
        if end and start and end < start:
            raise serializers.ValidationError({"end_date": "Tanggal keluar tidak boleh sebelum tanggal masuk."})
        return attrs


def _employees(org):
    return (Employee.objects.filter(organization=org)
            .select_related("default_site", "default_shift").prefetch_related("sites"))


class EmployeeListView(APIView):
    permission_classes = [IsCompanyHR]

    def get(self, request):
        qs = _employees(request.hr_org)
        q = (request.query_params.get("q") or "").strip()
        if q:
            qs = qs.filter(Q(full_name__icontains=q) | Q(employee_no__icontains=q) | Q(phone__icontains=q))
        if request.query_params.get("status") in (Employee.Status.ACTIVE, Employee.Status.RESIGNED):
            qs = qs.filter(status=request.query_params["status"])
        data = EmployeeSerializer(qs.order_by("full_name"), many=True, context={"org": request.hr_org}).data
        return Response({"success": True, "employees": data})

    def post(self, request):
        ser = EmployeeSerializer(data=request.data, context={"org": request.hr_org})
        ser.is_valid(raise_exception=True)
        emp = ser.save(organization=request.hr_org)
        return Response({"success": True, "employee": EmployeeSerializer(emp, context={"org": request.hr_org}).data},
                        status=status.HTTP_201_CREATED)


class EmployeeDetailView(APIView):
    permission_classes = [IsCompanyHR]

    def get(self, request, pk):
        emp = get_object_or_404(_employees(request.hr_org), pk=pk)
        return Response({"success": True, "employee": EmployeeSerializer(emp, context={"org": request.hr_org}).data})

    def patch(self, request, pk):
        emp = get_object_or_404(_employees(request.hr_org), pk=pk)
        ser = EmployeeSerializer(emp, data=request.data, partial=True, context={"org": request.hr_org})
        ser.is_valid(raise_exception=True)
        ser.save()
        emp.refresh_from_db()
        return Response({"success": True, "employee": EmployeeSerializer(emp, context={"org": request.hr_org}).data})


class EmployeeLoginView(APIView):
    permission_classes = [IsCompanyHR]

    def post(self, request, pk):
        emp = get_object_or_404(Employee, pk=pk, organization=request.hr_org)
        if not emp.is_active:
            return Response({"success": False, "message": "Karyawan sudah keluar; login tidak bisa diaktifkan."},
                            status=status.HTTP_400_BAD_REQUEST)
        try:
            pin = enable_login(emp, request.data.get("phone") or emp.login_phone or emp.phone,
                               request.data.get("pin") or None)
        except ValueError as err:
            return Response({"success": False, "message": str(err)}, status=status.HTTP_400_BAD_REQUEST)
        emp.refresh_from_db()
        return Response({"success": True, "pin": pin, "login_phone": emp.login_phone,
                         "employee": EmployeeSerializer(emp, context={"org": request.hr_org}).data})
