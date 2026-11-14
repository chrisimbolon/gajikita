# =============================================================================
# === backend/apps/attendance/note_decision_views.py ===
# =============================================================================
"""
HR's notes -> decisions (G17-4, 14 Nov 2026). The groups and words are in note_decisions.py.

GET  /api/hr/attendance/note-decisions/?month=YYYY-MM
     the period's HR notes (DayNotes), grouped: UL, ½ day, Cuti, Cuti ½, machine / power, handled, other.
     Every row has a state: todo | done | locked | no_taps (forgive needs taps), and for Cuti the SeeGaji balance.
POST /api/hr/attendance/note-decisions/apply/
     {"month", "group", "items": [{"employee", "date", "choice"}]}   choice only for cuti / half_cuti
       ul         -> unpaid leave that day (Cuti & Izin, "Formulir kertas", approved)
       cuti       -> annual | unpaid leave that day (HR chooses every row)
       half       -> the day: ½ day unpaid, no late / early minutes, approved
       half_cuti  -> paid (½ day, no cut) | unpaid (½ day unpaid)
       forgive    -> the day approved, late and single tap forgiven
     Locked days and rows already done are skipped; every failure comes back by name and date. Audited.
"""
from datetime import date as Date

from django.db import transaction
from django.utils import timezone
from rest_framework import serializers, status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.audit import record_audit
from apps.employees.models import Employee
from apps.leave import rules as leave_rules
from apps.leave.models import LeaveRequest
from apps.leave.services import LeaveError, annual_balance, create_leave
from apps.organizations.permissions import IsCompanyHR

from .models import AttendanceDay, DayNote
from .note_decisions import (ACTIONABLE, CHOICES, CUTI, FORGIVE, GROUPS, HALF, HALF_CUTI, UL, classify)
from .review import evaluate, evaluate_missing, leaves_between, night_context
from .review_bulk import _period

ACTIVE = (LeaveRequest.Status.PENDING, LeaveRequest.Status.APPROVED)


def _t(dt):
    return timezone.localtime(dt).strftime("%H:%M") if dt else None


def _state(group, day, r, on_leave):
    if day is not None and day.is_locked:
        return "locked"
    if group in (UL, CUTI):
        return "done" if on_leave else "todo"
    if group in (HALF, HALF_CUTI):
        if day is not None and (day.half_day_leave or (group == HALF_CUTI and day.decision == "approved"
                                                       and day.waive_late)):
            return "done"
        return "done" if on_leave else "todo"
    if group == FORGIVE:
        # G17-4.1: covered by a Kejadian, leave, "tidak wajib absen" or a day off = done. A day with NO taps and
        # none of those is "absent", and absent days never wait in Perlu Tinjau, so "nothing to review" there
        # must not read as done (Vinsen 8 Okt "Mati lampu", no taps, no event: still loses a day's pay).
        if r is not None and (r.disrupted or r.status in ("leave", "exempt", "day_off")):
            return "done"
        if day is None:
            return "no_taps"
        if (day.decision == "approved" and day.waive_late) or (r is not None and not r.needs_review):
            return "done"
        return "todo"
    return "info"


def build(org, month):
    info, start, end = _period(org, month)
    notes = list(DayNote.objects.filter(organization=org, date__gte=start, date__lte=end)
                 .select_related("employee", "employee__default_shift").order_by("date", "employee__full_name"))
    emp_ids = {n.employee_id for n in notes}
    days = {(d.employee_id, d.date): d for d in AttendanceDay.objects.filter(
        organization=org, employee_id__in=emp_ids, date__gte=start, date__lte=end).select_related(
        "employee", "employee__default_shift", "shift").prefetch_related("events__site")}
    leaves = leaves_between(org.id, start, end)
    covered = set()
    for lv in LeaveRequest.objects.filter(organization=org, employee_id__in=emp_ids, status__in=ACTIVE,
                                          start_date__lte=end, end_date__gte=start):
        d = max(lv.start_date, start)
        while d <= min(lv.end_date, end):
            covered.add((lv.employee_id, d))
            d = Date.fromordinal(d.toordinal() + 1)
    ctx = night_context(org.id, None, start, end)
    now = timezone.now()
    groups = {k: [] for k, _, _ in GROUPS}
    for n in notes:
        g = classify(n.code, n.text)
        key = (n.employee_id, n.date)
        day = days.get(key)
        r = None
        if g == FORGIVE or day is not None:
            if day is not None:
                r = evaluate(day, now, leave=leaves.get(key, ""), ctx=ctx)
            else:
                r = evaluate_missing(n.employee, n.date, now, leave=leaves.get(key, ""), ctx=ctx)
        row = {
            "employee": {"id": str(n.employee_id), "employee_no": n.employee.employee_no,
                         "full_name": n.employee.full_name},
            "date": n.date.isoformat(), "code": n.code, "text": n.text,
            "taps": (f"{_t(r.first_in) or '–'} – {_t(r.last_out) or '–'}"
                     if r is not None and (r.first_in or r.last_out) else None),
            "state": _state(g, day, r, key in covered),
        }
        if g == CUTI:
            row["balance_left"] = annual_balance(n.employee, n.date)["left"]
        groups[g].append(row)
    out = []
    for k, label, explain in GROUPS:
        rows = groups[k]
        out.append({"key": k, "label": label, "explain": explain, "actionable": k in ACTIONABLE,
                    "choices": [{"key": c, "label": l} for c, l in CHOICES.get(k, [])],
                    "todo": sum(1 for x in rows if x["state"] == "todo"), "rows": rows})
    return {"success": True, **info, "total": len(notes), "groups": out}


class NoteDecisionsView(APIView):
    permission_classes = [IsCompanyHR]

    def get(self, request):
        return Response(build(request.hr_org, request.query_params.get("month")))


class ItemSerializer(serializers.Serializer):
    employee = serializers.UUIDField()
    date = serializers.DateField()
    choice = serializers.CharField(required=False, allow_blank=True, default="")


class ApplySerializer(serializers.Serializer):
    month = serializers.CharField(required=False, allow_blank=True, default="")
    group = serializers.ChoiceField(choices=list(ACTIONABLE))
    items = ItemSerializer(many=True, allow_empty=False)


def _day(org, emp, d):
    day, _ = AttendanceDay.objects.get_or_create(employee=emp, date=d,
                                                 defaults={"organization": org, "shift": emp.default_shift})
    return day


def _decide_day(org, actor, emp, d, text, half, summary):
    """Approve the day (late forgiven); half = "" | "paid" | "unpaid". -> error text or None."""
    if half:
        day = _day(org, emp, d)
    else:
        day = AttendanceDay.objects.filter(employee=emp, date=d).first()
        if day is None:
            return "Tidak ada tap di hari itu: pakai Kejadian atau Ubah jam."
    if day.is_locked:
        return "Hari ini sudah masuk payroll yang dikunci."
    before = {"decision": day.decision, "waive_late": day.waive_late, "half_day_leave": day.half_day_leave}
    day.decision, day.waive_late, day.half_day_leave = "approved", True, half
    day.decision_note = f"Catatan HR: {text}"[:1000]
    day.decided_by, day.decided_at = actor, timezone.now()
    day.save(update_fields=["decision", "waive_late", "half_day_leave", "decision_note", "decided_by", "decided_at",
                            "updated_at"])
    record_audit(organization=org, actor=actor, action="attendance.note_decision", target=day,
                 summary=f"{emp.full_name} {d:%d-%m-%Y}: {summary} (catatan HR: {text})"[:255],
                 before=before, after={"decision": "approved", "waive_late": True, "half_day_leave": half})
    return None


def _leave(emp, d, kind, text, actor):
    try:
        create_leave(employee=emp, kind=kind, start=d, end=d, actor=actor, by_worker=False, approve=True,
                     reason=f"Catatan HR: {text}", note="Dari catatan HR")
    except LeaveError as err:
        return err.message
    # G17-4.2: the note says UL / cuti but the person tapped that day (DKCB: Eko 2 and 5 Okt, Junaidi 6 Okt).
    # Anthony counts the leave, so the taps are set aside ("Tolak" on a leave day = back to the leave, G9b).
    day = AttendanceDay.objects.filter(employee=emp, date=d, is_locked=False).first()
    if day is not None and day.events.exists() and day.decision != "rejected":
        before = {"decision": day.decision}
        day.decision, day.waive_late, day.overtime_approved_minutes, day.half_day_leave = "rejected", False, None, ""
        day.decision_note = f"Catatan HR: {text} (tap diabaikan, dihitung cuti / izin)"[:1000]
        day.decided_by, day.decided_at = actor, timezone.now()
        day.save(update_fields=["decision", "waive_late", "overtime_approved_minutes", "half_day_leave",
                                "decision_note", "decided_by", "decided_at", "updated_at"])
        record_audit(organization=emp.organization, actor=actor, action="attendance.note_decision", target=day,
                     summary=f"{emp.full_name} {d:%d-%m-%Y}: tap diabaikan, dihitung cuti / izin (catatan HR: {text})"[:255],
                     before=before, after={"decision": "rejected"})
    return None


class NoteDecisionApplyView(APIView):
    permission_classes = [IsCompanyHR]

    def post(self, request):
        ser = ApplySerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        d = ser.validated_data
        org, group = request.hr_org, d["group"]
        valid = {c for c, _ in CHOICES.get(group, [])}
        applied, errors = 0, []
        for item in d["items"]:
            emp = Employee.objects.select_related("default_shift").filter(pk=item["employee"], organization=org).first()
            note = (DayNote.objects.filter(organization=org, employee=emp, date=item["date"]).first()
                    if emp is not None else None)
            name = emp.full_name if emp is not None else "?"
            when = item["date"]
            if note is None or classify(note.code, note.text) != group:
                errors.append({"name": name, "date": when.isoformat(), "message": "Catatan tidak ditemukan di kelompok ini."})
                continue
            choice = item["choice"]
            if valid and choice not in valid:
                errors.append({"name": name, "date": when.isoformat(), "message": "Pilih dulu untuk baris ini."})
                continue
            with transaction.atomic():
                if group == UL:
                    problem = _leave(emp, when, leave_rules.UNPAID, note.text, request.user)
                elif group == CUTI:
                    kind = leave_rules.ANNUAL if choice == "annual" else leave_rules.UNPAID
                    problem = _leave(emp, when, kind, note.text, request.user)
                elif group == HALF or (group == HALF_CUTI and choice == "unpaid"):
                    problem = _decide_day(org, request.user, emp, when, note.text, "unpaid", "izin ½ hari tanpa upah")
                elif group == HALF_CUTI:
                    problem = _decide_day(org, request.user, emp, when, note.text, "paid", "cuti ½ hari dibayar")
                else:
                    problem = _decide_day(org, request.user, emp, when, note.text, "", "disetujui, dimaafkan")
            if problem:
                errors.append({"name": name, "date": when.isoformat(), "message": problem})
            else:
                applied += 1
        body = build(org, d["month"])
        body.update({"applied": applied, "errors": errors})
        return Response(body, status=status.HTTP_200_OK)
