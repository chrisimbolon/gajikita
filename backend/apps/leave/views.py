# =============================================================================
# === backend/apps/leave/views.py ===
# =============================================================================
"""
The worker's side of leave (G7, 28 Oct 2026). All under /api/worker/leave/.

  GET  /                  my balance, my requests, the choices, and (for a site manager)
                          my crew's requests waiting for me
  POST /                  ask for leave: kind, special_reason, start_date, end_date, reason, attachment
  POST <id>/cancel/       cancel my own request while it is still waiting
  POST <id>/decide/       site manager only: {action: approve|reject, note}
"""
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import serializers, status
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.attendance.views import NOT_AN_EMPLOYEE, _my_employee

from . import rules
from .models import LeaveRequest
from .services import LeaveError, annual_balance, can_approve_on_phone, create_leave, decide_leave


def leave_payload(l):
    mandor = l.employee.mandor
    return {
        "id": str(l.id),
        "employee": {"id": str(l.employee.id), "employee_no": l.employee.employee_no, "full_name": l.employee.full_name},
        "kind": l.kind, "kind_label": l.get_kind_display(), "special_reason": l.special_reason, "label": l.label,
        "paid": l.paid,
        "start_date": l.start_date.isoformat(), "end_date": l.end_date.isoformat(), "days": l.days,
        "reason": l.reason,
        "has_attachment": bool(l.attachment),
        "sick_note_missing": rules.sick_note_missing(l.kind, l.days, bool(l.attachment)),
        "status": l.status, "status_label": l.get_status_display(),
        "source": l.source, "source_label": l.get_source_display(),
        "approver": mandor.full_name if mandor else None,
        "requested_at": l.created_at.isoformat(),
        "decided_by": l.decided_by.full_name if l.decided_by else None,
        "decided_at": l.decided_at.isoformat() if l.decided_at else None,
        "decision_note": l.decision_note,
    }


def choices_payload():
    return {
        "kinds": [{"value": k, "label": v, "paid": rules.PAID[k]} for k, v in rules.KIND_LABELS.items()],
        "special_reasons": [{"value": k, "label": label, "days": days} for k, (label, days) in rules.SPECIAL_REASONS.items()],
    }


def error_response(err):
    return Response({"success": False, "message": err.message, "errors": err.errors}, status=status.HTTP_400_BAD_REQUEST)


def _qs():
    return LeaveRequest.objects.select_related("employee", "employee__mandor", "decided_by")


class LeaveInputSerializer(serializers.Serializer):
    kind = serializers.ChoiceField(choices=list(rules.KIND_LABELS))
    special_reason = serializers.CharField(required=False, allow_blank=True, default="")
    start_date = serializers.DateField()
    end_date = serializers.DateField()
    reason = serializers.CharField(required=False, allow_blank=True, default="", max_length=500)
    attachment = serializers.FileField(required=False, allow_null=True)


class DecisionSerializer(serializers.Serializer):
    action = serializers.ChoiceField(choices=["approve", "reject"])
    note = serializers.CharField(required=False, allow_blank=True, default="", max_length=255)


class MyLeaveView(APIView):
    permission_classes = [IsAuthenticated]
    parser_classes = [MultiPartParser, FormParser, JSONParser]

    def get(self, request):
        me = _my_employee(request.user)
        if me is None:
            return Response({"success": False, "message": NOT_AN_EMPLOYEE}, status=status.HTTP_403_FORBIDDEN)
        mine = _qs().filter(employee=me)[:30]
        crew = _qs().filter(employee__mandor=me, status=LeaveRequest.Status.PENDING).order_by("start_date")
        recent = _qs().filter(employee__mandor=me).exclude(status=LeaveRequest.Status.PENDING)[:10]
        return Response({
            "success": True,
            "employee": {"id": str(me.id), "full_name": me.full_name},
            "approver": me.mandor.full_name if me.mandor_id else None,
            "annual": annual_balance(me, timezone.localdate()),
            **choices_payload(),
            "requests": [leave_payload(l) for l in mine],
            "is_approver": me.crew.exists(),
            "to_approve": [leave_payload(l) for l in crew],
            "crew_recent": [leave_payload(l) for l in recent],
        })

    def post(self, request):
        me = _my_employee(request.user)
        if me is None:
            return Response({"success": False, "message": NOT_AN_EMPLOYEE}, status=status.HTTP_403_FORBIDDEN)
        ser = LeaveInputSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        d = ser.validated_data
        try:
            leave = create_leave(employee=me, kind=d["kind"], special_reason=d["special_reason"], start=d["start_date"],
                                 end=d["end_date"], reason=d["reason"], attachment=d.get("attachment"),
                                 actor=request.user, by_worker=True)
        except LeaveError as err:
            return error_response(err)
        who = me.mandor.full_name if me.mandor_id else "HR"
        return Response({"success": True, "leave": leave_payload(_qs().get(pk=leave.pk)),
                         "message": f"Pengajuan terkirim ({leave.days} hari kerja). Menunggu persetujuan {who}."},
                        status=status.HTTP_201_CREATED)


class MyLeaveCancelView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        me = _my_employee(request.user)
        if me is None:
            return Response({"success": False, "message": NOT_AN_EMPLOYEE}, status=status.HTTP_403_FORBIDDEN)
        leave = get_object_or_404(_qs(), pk=pk, employee=me)
        if leave.status != LeaveRequest.Status.PENDING:
            return Response({"success": False, "message": "Hanya pengajuan yang masih menunggu yang bisa dibatalkan. "
                                                          "Hubungi HR untuk membatalkan cuti yang sudah disetujui."},
                            status=status.HTTP_400_BAD_REQUEST)
        try:
            leave = decide_leave(leave, action="cancel", actor=request.user, note="Dibatalkan oleh karyawan")
        except LeaveError as err:
            return error_response(err)
        return Response({"success": True, "leave": leave_payload(_qs().get(pk=leave.pk))})


class CrewLeaveDecideView(APIView):
    """The site manager approves or rejects a crew member's request from the phone."""
    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        me = _my_employee(request.user)
        if me is None:
            return Response({"success": False, "message": NOT_AN_EMPLOYEE}, status=status.HTTP_403_FORBIDDEN)
        leave = get_object_or_404(_qs(), pk=pk, organization=me.organization)
        if not can_approve_on_phone(me, leave):
            return Response({"success": False, "message": "Anda bukan atasan karyawan ini."}, status=status.HTTP_403_FORBIDDEN)
        ser = DecisionSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        try:
            leave = decide_leave(leave, action=ser.validated_data["action"], actor=request.user,
                                 note=ser.validated_data["note"])
        except LeaveError as err:
            return error_response(err)
        return Response({"success": True, "leave": leave_payload(_qs().get(pk=leave.pk))})
