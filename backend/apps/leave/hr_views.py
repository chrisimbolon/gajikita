# =============================================================================
# === backend/apps/leave/hr_views.py ===
# =============================================================================
"""
HR's leave screen (G7, 28 Oct 2026). All under /api/hr/leave/.

  GET  ?status=pending|approved|rejected|cancelled|all&q=   the list + a count per status
  POST /                    record a paper form: {employee, kind, special_reason, start_date, end_date,
                            reason, attachment}; approved straight away
  POST <id>/decide/         {action: approve|reject|cancel, note}; HR can decide any request,
                            also ones waiting for a site manager
  GET  <id>/attachment/     the doctor's letter photo / PDF
  GET  balance/<employee>/  that employee's annual leave balance (for the paper-form dialog)
  GET/PATCH settings/       G14-1: the company's leave rules (Pengaturan cuti)
"""
import mimetypes
import os

from django.db import transaction
from django.db.models import Count, Q
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import serializers, status
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.audit import record_audit
from apps.employees.models import Employee
from apps.organizations.permissions import IsCompanyHR

from . import rules
from .models import LeaveRequest, LeaveSettings
from .services import LeaveError, annual_balance, create_leave, decide_leave
from .views import LeaveInputSerializer, _qs, choices_payload, error_response, leave_payload

LIST_LIMIT = 300


class HrLeaveInputSerializer(LeaveInputSerializer):
    employee = serializers.UUIDField()


class HrDecisionSerializer(serializers.Serializer):
    action = serializers.ChoiceField(choices=["approve", "reject", "cancel"])
    note = serializers.CharField(required=False, allow_blank=True, default="", max_length=255)


class HrLeaveListView(APIView):
    permission_classes = [IsCompanyHR]
    parser_classes = [MultiPartParser, FormParser, JSONParser]

    def get(self, request):
        org = request.hr_org
        base = _qs().filter(organization=org)
        wanted = request.query_params.get("status", "pending")
        q = (request.query_params.get("q") or "").strip()
        qs = base if wanted == "all" else base.filter(status=wanted)
        if q:
            qs = qs.filter(Q(employee__full_name__icontains=q) | Q(employee__employee_no__icontains=q))
        if wanted == "pending":
            qs = qs.order_by("start_date", "created_at")       # the oldest waiting first
        counts = {r["status"]: r["n"] for r in LeaveRequest.objects.filter(organization=org).order_by()
                  .values("status").annotate(n=Count("id"))}
        return Response({
            "success": True,
            "status": wanted,
            "counts": {s: counts.get(s, 0) for s in LeaveRequest.Status.values},
            **choices_payload(org),
            "requests": [leave_payload(l) for l in qs[:LIST_LIMIT]],
        })

    def post(self, request):
        ser = HrLeaveInputSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        d = ser.validated_data
        emp = get_object_or_404(Employee.objects.select_related("default_shift", "organization"),
                                pk=d["employee"], organization=request.hr_org)
        try:
            leave = create_leave(employee=emp, kind=d["kind"], special_reason=d["special_reason"], start=d["start_date"],
                                 end=d["end_date"], reason=d["reason"], attachment=d.get("attachment"),
                                 actor=request.user, by_worker=False, approve=True, note="Formulir kertas")
        except LeaveError as err:
            return error_response(err)
        return Response({"success": True, "leave": leave_payload(_qs().get(pk=leave.pk))}, status=status.HTTP_201_CREATED)


class HrLeaveDecideView(APIView):
    permission_classes = [IsCompanyHR]

    def post(self, request, pk):
        leave = get_object_or_404(_qs(), pk=pk, organization=request.hr_org)
        ser = HrDecisionSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        try:
            leave = decide_leave(leave, action=ser.validated_data["action"], actor=request.user,
                                 note=ser.validated_data["note"])
        except LeaveError as err:
            return error_response(err)
        return Response({"success": True, "leave": leave_payload(_qs().get(pk=leave.pk))})


class HrLeaveAttachmentView(APIView):
    permission_classes = [IsCompanyHR]

    def get(self, request, pk):
        leave = get_object_or_404(LeaveRequest, pk=pk, organization=request.hr_org)
        if not leave.attachment:
            raise Http404("Tidak ada lampiran.")
        name = os.path.basename(leave.attachment.name)
        resp = FileResponse(leave.attachment.open("rb"),
                            content_type=mimetypes.guess_type(name)[0] or "application/octet-stream")
        resp["Cache-Control"] = "private, max-age=3600"
        return resp


SETTING_FIELDS = ("collective_leave_reduces_annual", "paternity_extra_days", "menstrual_leave",
                  "maternity_extension_pay", "long_rest", "long_leave_keeps_attendance_bonus")          # G14-2
SETTING_WORDS = {"collective_leave_reduces_annual": "cuti bersama mengurangi cuti tahunan",
                 "paternity_extra_days": "tambahan cuti istri melahirkan", "menstrual_leave": "cuti haid",
                 "maternity_extension_pay": "upah perpanjangan cuti melahirkan", "long_rest": "istirahat panjang",
                 "long_leave_keeps_attendance_bonus": "tunjangan kehadiran saat cuti panjang"}


def settings_json(cfg):
    return {f: getattr(cfg, f) for f in SETTING_FIELDS}


class LeaveSettingsInput(serializers.Serializer):
    collective_leave_reduces_annual = serializers.BooleanField(required=False)
    paternity_extra_days = serializers.IntegerField(required=False, min_value=0, max_value=rules.PATERNITY_EXTRA_MAX)
    menstrual_leave = serializers.BooleanField(required=False)
    maternity_extension_pay = serializers.IntegerField(required=False, min_value=0, max_value=100)      # G14-2
    long_rest = serializers.BooleanField(required=False)
    long_leave_keeps_attendance_bonus = serializers.BooleanField(required=False)


class HrLeaveSettingsView(APIView):
    """G14-1: GET/PATCH /api/hr/leave/settings/. Every change goes to the audit log (shown on Aturan perusahaan vs UU)."""
    permission_classes = [IsCompanyHR]

    def get(self, request):
        return Response({"success": True, "settings": settings_json(LeaveSettings.for_org(request.hr_org))})

    def patch(self, request):
        org = request.hr_org
        ser = LeaveSettingsInput(data=request.data)
        ser.is_valid(raise_exception=True)
        cfg = LeaveSettings.for_org(org)
        changed = {k: v for k, v in ser.validated_data.items() if getattr(cfg, k) != v}
        if changed:
            before = {k: getattr(cfg, k) for k in changed}
            with transaction.atomic():
                for k, v in changed.items():
                    setattr(cfg, k, v)
                cfg.save()
                record_audit(organization=org, actor=request.user, action="leave.settings", target=org,
                             summary="Pengaturan cuti diubah: " + ", ".join(SETTING_WORDS[k] for k in changed),
                             before=before, after=changed)
        return Response({"success": True, "settings": settings_json(cfg)})


class HrLeaveBalanceView(APIView):
    permission_classes = [IsCompanyHR]

    def get(self, request, employee_id):
        emp = get_object_or_404(Employee, pk=employee_id, organization=request.hr_org)
        return Response({"success": True, "annual": annual_balance(emp, timezone.localdate())})
