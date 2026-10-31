# =============================================================================
# === backend/apps/attendance/hr_views.py ===
# =============================================================================
"""
HR's attendance screens (G3, 28 Oct 2026). All under /api/hr/attendance/.

  GET  daily/?date=YYYY-MM-DD        every active employee's status that day + the counters
  GET  review/?days=7                days that need HR (late, no clock-out, outside site, overtime...)
  GET  days/<id>/                    one day: taps with distance / accuracy / flags, the audit log
  POST days/<id>/decide/             {action: approve|reject|reset, note, waive_late, overtime_minutes}
  POST fix/                          {employee, date, clock_in "HH:MM", clock_out "HH:MM", reason}
  GET  events/<id>/selfie/           the selfie image (HR of the same company only)

Every decision and fix writes an audit entry. A locked day (paid in a pay run) can't change.
"""
import re
from collections import Counter
from datetime import date as Date, datetime, timedelta

from django.db import transaction
from django.db.models import Q
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import serializers, status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.audit import audit_payload, record_audit
from apps.core.models import AuditEntry
from apps.employees.models import Employee
from apps.organizations.permissions import IsCompanyHR

from .day_status import STATUS_LABELS
from .geofence import FLAG_LABELS
from .models import AttendanceDay, ClockEvent
from .review import evaluate, evaluate_missing, row
from apps.payroll.services import day_overtime
from apps.leave.services import approved_leave_on

# The counters across the top of the daily page, in order (Talenta-style).
COUNTERS = ["on_time", "late", "early_out", "no_clock_out", "working", "absent", "leave", "not_yet", "day_off",
            "day_off_work", "rejected"]
LOCKED = "Hari ini sudah dikunci karena sudah masuk pay run."


def _parse_date(value, default):
    try:
        return Date.fromisoformat(value) if value else default
    except ValueError:
        return default


def _days_qs(org):
    return (AttendanceDay.objects.filter(organization=org)
            .select_related("employee", "employee__default_shift", "shift")
            .prefetch_related("events__site"))


def _employees_on(org, day):
    return (Employee.objects.filter(organization=org, join_date__lte=day)
            .filter(Q(status=Employee.Status.ACTIVE) | Q(end_date__gte=day))
            .exclude(end_date__lt=day)
            .select_related("default_shift").order_by("full_name"))


def daily_rows(org, day, now):
    """Every active employee's row for one date (shared by the daily page and the dashboard)."""
    days = {d.employee_id: d for d in _days_qs(org).filter(date=day)}
    leaves = approved_leave_on(org, day)          # G7: approved cuti / sakit / izin that day
    rows = []
    for emp in _employees_on(org, day):
        d = days.pop(emp.id, None)
        leave = leaves.get(emp.id, "")
        rows.append(row(emp, day, d, evaluate(d, now, leave=leave) if d else evaluate_missing(emp, day, now, leave=leave)))
    for d in days.values():            # taps from someone no longer listed (resigned since)
        rows.append(row(d.employee, day, d, evaluate(d, now, leave=leaves.get(d.employee_id, ""))))
    return rows


def daily_counters(rows):
    counts = Counter(tag for r in rows for tag in r["tags"])
    counters = [{"key": k, "label": STATUS_LABELS[k], "count": counts.get(k, 0)} for k in COUNTERS]
    counters.append({"key": "needs_review", "label": "Perlu ditinjau", "count": sum(r["needs_review"] for r in rows)})
    return counters


def review_rows(org, n, now):
    """Days in the last n days that need HR, newest first (shared by the queue and the dashboard)."""
    today = timezone.localtime(now).date()
    rows = []
    for d in _days_qs(org).filter(date__gte=today - timedelta(days=n - 1), date__lte=today, decision=""):
        r = evaluate(d, now)
        if r.needs_review:
            rows.append(row(d.employee, d.date, d, r))
    rows.sort(key=lambda r: (r["date"], r["employee"]["full_name"]), reverse=True)
    return rows


def review_summary(rows):
    # "Terlambat 12 menit" and "Terlambat 40 menit" count as one kind: "Terlambat".
    summary = Counter(re.sub(r" \d+ menit.*$", "", reason) for r in rows for reason in r["review_reasons"])
    return [{"label": k, "count": v} for k, v in summary.most_common()]


class DailyView(APIView):
    permission_classes = [IsCompanyHR]

    def get(self, request):
        day = _parse_date(request.query_params.get("date"), timezone.localdate())
        rows = daily_rows(request.hr_org, day, timezone.now())
        return Response({"success": True, "date": day.isoformat(), "counters": daily_counters(rows), "rows": rows})


class ReviewQueueView(APIView):
    permission_classes = [IsCompanyHR]

    def get(self, request):
        try:
            n = max(1, min(31, int(request.query_params.get("days", 7))))
        except ValueError:
            n = 7
        rows = review_rows(request.hr_org, n, timezone.now())
        return Response({"success": True, "days": n, "count": len(rows), "summary": review_summary(rows), "rows": rows})


def _day_detail(request, day):
    events = []
    for e in day.events.all():
        events.append({
            "id": str(e.id), "kind": e.kind, "kind_label": e.get_kind_display(), "source": e.get_source_display(),
            "occurred_at": e.occurred_at.isoformat(), "time": timezone.localtime(e.occurred_at).strftime("%H:%M"),
            "received_at": e.received_at.isoformat(),
            "site": e.site.name if e.site else None,
            "latitude": float(e.latitude) if e.latitude is not None else None,
            "longitude": float(e.longitude) if e.longitude is not None else None,
            "accuracy_m": float(e.accuracy_m) if e.accuracy_m is not None else None,
            "distance_m": e.distance_m,
            "flags": e.flags, "flag_labels": [FLAG_LABELS.get(f, f) for f in e.flags],
            "has_selfie": bool(e.selfie),
        })
    audit = AuditEntry.objects.filter(organization=day.organization, target_type="attendance.attendanceday",
                                      target_id=str(day.id)).select_related("actor")
    result = evaluate(day)
    data = row(day.employee, day.date, day, result)
    data.update({
        "shift": ({"name": (day.shift or day.employee.default_shift).name,
                   "start": (day.shift or day.employee.default_shift).start_time.strftime("%H:%M"),
                   "end": (day.shift or day.employee.default_shift).end_time.strftime("%H:%M")}
                  if (day.shift or day.employee.default_shift) else None),
        "events": events,
        "decision_note": day.decision_note,
        "waive_late": day.waive_late,
        "decided_by": day.decided_by.full_name if day.decided_by else None,
        "decided_at": day.decided_at.isoformat() if day.decided_at else None,
        "audit": [audit_payload(a) for a in audit],
        "overtime_pay": day_overtime(day, result.overtime_proposed_minutes),
    })
    return data


class DayDetailView(APIView):
    permission_classes = [IsCompanyHR]

    def get(self, request, pk):
        day = get_object_or_404(_days_qs(request.hr_org), pk=pk)
        return Response({"success": True, "day": _day_detail(request, day)})


def _snapshot(day):
    return {
        "decision": day.decision, "note": day.decision_note, "waive_late": day.waive_late,
        "overtime_approved_minutes": day.overtime_approved_minutes,
        "hr_in": timezone.localtime(day.hr_in).strftime("%Y-%m-%d %H:%M") if day.hr_in else None,
        "hr_out": timezone.localtime(day.hr_out).strftime("%Y-%m-%d %H:%M") if day.hr_out else None,
    }


class DecideSerializer(serializers.Serializer):
    action = serializers.ChoiceField(choices=["approve", "reject", "reset"])
    note = serializers.CharField(required=False, allow_blank=True, default="")
    waive_late = serializers.BooleanField(required=False, default=False)
    overtime_minutes = serializers.IntegerField(required=False, allow_null=True, min_value=0, max_value=24 * 60)

    def validate(self, attrs):
        if attrs["action"] == "reject" and not attrs["note"].strip():
            raise serializers.ValidationError({"note": "Tulis alasan penolakan."})
        return attrs


class DecideView(APIView):
    permission_classes = [IsCompanyHR]

    def post(self, request, pk):
        day = get_object_or_404(_days_qs(request.hr_org), pk=pk)
        if day.is_locked:
            return Response({"success": False, "message": LOCKED}, status=status.HTTP_400_BAD_REQUEST)
        ser = DecideSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        d = ser.validated_data
        before = _snapshot(day)
        result = evaluate(day)
        with transaction.atomic():
            if d["action"] == "reset":
                day.decision, day.decision_note, day.waive_late = "", "", False
                day.overtime_approved_minutes = None
                day.decided_by = day.decided_at = None
                summary = "Keputusan dibatalkan"
            else:
                day.decision = "approved" if d["action"] == "approve" else "rejected"
                day.decision_note = d["note"].strip()
                day.decided_by, day.decided_at = request.user, timezone.now()
                if d["action"] == "approve":
                    day.waive_late = d["waive_late"]
                    proposed = result.overtime_proposed_minutes
                    ot = d.get("overtime_minutes")
                    day.overtime_approved_minutes = (proposed if ot is None else ot) if proposed or ot else None
                    summary = "Disetujui" + (" (terlambat dimaafkan)" if day.waive_late else "") + (
                        f", lembur {day.overtime_approved_minutes} menit" if day.overtime_approved_minutes else "")
                else:
                    day.waive_late, day.overtime_approved_minutes = False, None
                    summary = "Ditolak: dihitung tidak hadir"
            day.save()
            record_audit(organization=day.organization, actor=request.user, action=f"attendance.{d['action']}",
                         target=day, summary=f"{day.employee.full_name} {day.date:%d-%m-%Y}: {summary}",
                         before=before, after=_snapshot(day), note=d["note"])
        day = get_object_or_404(_days_qs(request.hr_org), pk=pk)
        return Response({"success": True, "day": _day_detail(request, day)})


class FixSerializer(serializers.Serializer):
    employee = serializers.UUIDField()
    date = serializers.DateField()
    clock_in = serializers.TimeField(required=False, allow_null=True)
    clock_out = serializers.TimeField(required=False, allow_null=True)
    reason = serializers.CharField()

    def validate(self, attrs):
        if not attrs.get("clock_in") and not attrs.get("clock_out"):
            raise serializers.ValidationError("Isi jam masuk, jam pulang, atau keduanya.")
        if not attrs["reason"].strip():
            raise serializers.ValidationError({"reason": "Tulis alasan perubahan jam."})
        return attrs


class FixTimesView(APIView):
    """HR sets the real clock-in / clock-out (forgot to tap, wrong phone clock...). Approves the day too."""
    permission_classes = [IsCompanyHR]

    def post(self, request):
        ser = FixSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        d = ser.validated_data
        emp = get_object_or_404(Employee.objects.select_related("default_shift"), pk=d["employee"],
                                organization=request.hr_org)
        tz = timezone.get_current_timezone()
        with transaction.atomic():
            day, _ = AttendanceDay.objects.select_for_update().get_or_create(
                employee=emp, date=d["date"], defaults={"organization": emp.organization, "shift": emp.default_shift})
            if day.is_locked:
                return Response({"success": False, "message": LOCKED}, status=status.HTTP_400_BAD_REQUEST)
            before = _snapshot(day)
            if d.get("clock_in"):
                day.hr_in = datetime.combine(day.date, d["clock_in"], tzinfo=tz)
            if d.get("clock_out"):
                out = datetime.combine(day.date, d["clock_out"], tzinfo=tz)
                start = day.hr_in or (min((e.occurred_at for e in day.events.all()), default=None))
                if start is not None and out <= start:
                    out += timedelta(days=1)          # night shift: clock-out is the next morning
                day.hr_out = out
            day.decision, day.decision_note = "approved", d["reason"].strip()
            day.decided_by, day.decided_at = request.user, timezone.now()
            day.save()
            parts = [f"masuk {d['clock_in']:%H:%M}" if d.get("clock_in") else "",
                     f"pulang {d['clock_out']:%H:%M}" if d.get("clock_out") else ""]
            record_audit(organization=day.organization, actor=request.user, action="attendance.fix", target=day,
                         summary=f"{emp.full_name} {day.date:%d-%m-%Y}: jam diubah ({', '.join(p for p in parts if p)})",
                         before=before, after=_snapshot(day), note=d["reason"])
        day = get_object_or_404(_days_qs(request.hr_org), pk=day.pk)
        return Response({"success": True, "day": _day_detail(request, day)})


class SelfieView(APIView):
    permission_classes = [IsCompanyHR]

    def get(self, request, pk):
        event = get_object_or_404(ClockEvent, pk=pk, organization=request.hr_org)
        if not event.selfie:
            raise Http404("Tidak ada selfie.")
        resp = FileResponse(event.selfie.open("rb"), content_type="image/jpeg")
        resp["Cache-Control"] = "private, max-age=3600"
        return resp
