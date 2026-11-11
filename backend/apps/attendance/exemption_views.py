# =============================================================================
# === backend/apps/attendance/exemption_views.py ===
# =============================================================================
"""
"Tidak wajib absen" periods per employee (G12i, 11 Nov 2026)

GET    /api/hr/employees/<id>/attendance-exemptions/   the employee's periods, newest first
POST   /api/hr/employees/<id>/attendance-exemptions/   {"start", "end" (optional), "reason"}
PATCH  /api/hr/attendance-exemptions/<id>/             {"end" (null = until further notice), "reason"}
DELETE /api/hr/attendance-exemptions/<id>/

Rules: end on or after start; a reason of 3+ letters; no two periods of one person share a day; no change may
touch the dates of a LOCKED payroll (they were paid that way). Every change is audited.
"""
from django.db import transaction
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import serializers, status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.audit import record_audit
from apps.employees.models import Employee
from apps.organizations.permissions import IsCompanyHR

from .exemptions import changed_ranges, locked_hit, overlapping
from .models import AttendanceExemption


def _d(d):
    return d.strftime("%d-%m-%Y") if d else "seterusnya"


def exemption_json(x):
    return {"id": str(x.pk), "start": x.start.isoformat(), "end": x.end.isoformat() if x.end else None,
            "reason": x.reason}


def current_exemption(emp, today=None):
    """The period covering today (WIB), or None. Uses the prefetched attendance_exemptions when present."""
    today = today or timezone.localdate()
    for x in emp.attendance_exemptions.all():
        if x.start <= today and (x.end is None or today <= x.end):
            return exemption_json(x)
    return None


def _locked(org):
    from apps.payroll.models import PayRun
    return [(r.period_start, r.period_end, r.name)
            for r in PayRun.objects.filter(organization=org, status=PayRun.Status.LOCKED)]


def _bad(message):
    return Response({"success": False, "message": message}, status=status.HTTP_400_BAD_REQUEST)


def _check(org, emp, old, new, skip=None):
    """A plain message when the change is not allowed, else None."""
    if new is not None:
        start, end = new
        if end is not None and end < start:
            return "Tanggal selesai tidak boleh sebelum tanggal mulai."
        periods = [(x.start, x.end, x.reason, x.pk) for x in emp.attendance_exemptions.all()]
        clash = overlapping(periods, start, end, skip=skip)
        if clash is not None:
            return (f"Bertabrakan dengan periode tidak wajib absen yang sudah ada ({_d(clash[0])} s/d {_d(clash[1])}). "
                    f"Ubah atau akhiri periode itu dulu.")
    hit = locked_hit(changed_ranges(old, new), _locked(org))
    if hit is not None:
        return (f"{hit[2]} ({_d(hit[0])} s/d {_d(hit[1])}) sudah dikunci dan dibayar seperti ini. Tanggal di periode "
                f"itu tidak bisa diubah; buka kunci payroll dulu, atau mulai/akhiri sesudah {_d(hit[1])}.")
    return None


class ExemptionInput(serializers.Serializer):
    start = serializers.DateField()
    end = serializers.DateField(required=False, allow_null=True)
    reason = serializers.CharField(max_length=200)

    def validate_reason(self, value):
        value = " ".join(value.split())
        if len(value) < 3:
            raise serializers.ValidationError("Tulis alasannya, mis. \"Kerja di Lobam\" atau \"Sales lapangan\".")
        return value


class ExemptionEdit(serializers.Serializer):
    end = serializers.DateField(required=False, allow_null=True)
    reason = serializers.CharField(max_length=200, required=False)

    def validate_reason(self, value):
        value = " ".join(value.split())
        if len(value) < 3:
            raise serializers.ValidationError("Tulis alasannya.")
        return value


def _body(emp):
    emp = Employee.objects.prefetch_related("attendance_exemptions").get(pk=emp.pk)
    periods = sorted(emp.attendance_exemptions.all(), key=lambda x: x.start, reverse=True)
    return {"success": True, "employee": {"id": str(emp.pk), "employee_no": emp.employee_no, "full_name": emp.full_name},
            "exemptions": [exemption_json(x) for x in periods], "current": current_exemption(emp)}


class EmployeeExemptionsView(APIView):
    permission_classes = [IsCompanyHR]

    def get(self, request, pk):
        emp = get_object_or_404(Employee, pk=pk, organization=request.hr_org)
        return Response(_body(emp))

    def post(self, request, pk):
        org = request.hr_org
        emp = get_object_or_404(Employee, pk=pk, organization=org)
        ser = ExemptionInput(data=request.data)
        ser.is_valid(raise_exception=True)
        d = ser.validated_data
        with transaction.atomic():
            Employee.objects.select_for_update().filter(pk=emp.pk).first()        # one change per person at a time
            problem = _check(org, emp, None, (d["start"], d.get("end")))
            if problem:
                return _bad(problem)
            x = AttendanceExemption.objects.create(organization=org, employee=emp, start=d["start"], end=d.get("end"),
                                                   reason=d["reason"], created_by=request.user)
            record_audit(organization=org, actor=request.user, action="attendance.exemption_create", target=emp,
                         summary=f"{emp.full_name}: tidak wajib absen {_d(x.start)} s/d {_d(x.end)} ({x.reason})",
                         after=exemption_json(x))
        return Response(_body(emp), status=status.HTTP_201_CREATED)


class ExemptionDetailView(APIView):
    permission_classes = [IsCompanyHR]

    def patch(self, request, pk):
        org = request.hr_org
        x = get_object_or_404(AttendanceExemption.objects.select_related("employee"), pk=pk, organization=org)
        ser = ExemptionEdit(data=request.data)
        ser.is_valid(raise_exception=True)
        d = ser.validated_data
        before = exemption_json(x)
        end = d["end"] if "end" in d else x.end
        with transaction.atomic():
            Employee.objects.select_for_update().filter(pk=x.employee_id).first()
            problem = _check(org, x.employee, (x.start, x.end), (x.start, end), skip=x.pk)
            if problem:
                return _bad(problem)
            x.end = end
            x.reason = d.get("reason", x.reason)
            x.save(update_fields=["end", "reason", "updated_at"])
            record_audit(organization=org, actor=request.user, action="attendance.exemption_update", target=x.employee,
                         summary=f"{x.employee.full_name}: tidak wajib absen sekarang {_d(x.start)} s/d {_d(x.end)} "
                                 f"({x.reason})",
                         before=before, after=exemption_json(x))
        return Response(_body(x.employee))

    def delete(self, request, pk):
        org = request.hr_org
        x = get_object_or_404(AttendanceExemption.objects.select_related("employee"), pk=pk, organization=org)
        with transaction.atomic():
            problem = _check(org, x.employee, (x.start, x.end), None)
            if problem:
                return _bad(problem)
            before, emp = exemption_json(x), x.employee
            x.delete()
            record_audit(organization=org, actor=request.user, action="attendance.exemption_delete", target=emp,
                         summary=f"{emp.full_name}: periode tidak wajib absen {_d(x.start)} s/d {_d(x.end)} dihapus",
                         before=before)
        return Response(_body(emp))
