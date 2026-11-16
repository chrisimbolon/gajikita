# =============================================================================
# === backend/apps/attendance/checklist.py ===
# =============================================================================
"""
G17-7 (16 Nov 2026) — "Siap gajian?": Perlu Tinjau as a guided checklist per pay period.

Why (Chris, 16 Nov, on seegaji.com): 260 rows "Belum diputuskan", 112 of them "Terlambat". A late arrival is a FACT
with a company rule (5 minutes grace, Rp 500/minute), not a question; a new HR user freezes in front of 260 rows.
Only overtime (money out, needs an SPL) and patterns (a power cut) really need HR. Everything else is shown as a
summary per person, with "what happens if you do nothing" and a button for the exceptions.

GET  /api/hr/attendance/checklist/?month=YYYY-MM
     steps: import (days with taps), events (existing Kejadian + dates where many people miss taps = suggestion),
     notes (HR notes still to apply), overtime (open days per person, with the proposal), missing taps (½ day by
     the rule unless forgiven), late & early (minutes and rupiah by the rule unless forgiven). Each person's days
     carry day_id, so the screen acts with the existing bulk actions (pay_overtime, no_overtime, forgive, away)
     and their Urungkan.
POST /api/hr/attendance/checklist/dismiss/  {start, end}   "Bukan kejadian": the suggestion stops showing (audited)

Only days up to today are counted; locked days are left out of the lists (they can't change).
"""
from collections import defaultdict
from datetime import date as Date, timedelta
from decimal import Decimal

from django.utils import timezone
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.audit import record_audit
from apps.core.models import AuditEntry
from apps.organizations.permissions import IsCompanyHR
from apps.payroll.models import PayrollSettings, PayRun

from . import checklist_rules as R
from .day_status import Status
from .models import ClockEvent, CompanyEvent, DayNote
from .review import evaluate, evaluate_missing, night_context
from .review_bulk import _period
from .review_kinds import capped_overtime

DISMISS = "attendance.event_dismiss"


def _t(dt):
    return timezone.localtime(dt).strftime("%H:%M") if dt else None


def _emp(e):
    return {"id": str(e.id), "employee_no": e.employee_no, "full_name": e.full_name}


def _daily_rate(emp, cfg):
    if emp.pay_type == emp.PayType.DAILY:
        return Decimal(emp.base_rate)
    return Decimal(emp.base_rate) / Decimal(cfg.daily_divisor or 30)


def _dismissed(org, start, end):
    out = set()
    for a in AuditEntry.objects.filter(organization=org, action=DISMISS):
        d = (a.data or {}).get("after") or {}
        try:
            s, e = Date.fromisoformat(d.get("start", "")), Date.fromisoformat(d.get("end", ""))
        except ValueError:
            continue
        if e >= start and s <= end:
            out.add((s, e))
    return out


def build(org, month=None, now=None):
    from apps.payroll.payrun import _dates, _days_by_employee, _leaves_by_employee, employees_in_period
    info, start, end = _period(org, month)
    now = now or timezone.now()
    today = timezone.localdate(now)
    cfg = PayrollSettings.for_org(org)
    emps = list(employees_in_period(org, start, end))
    ids = [e.id for e in emps]
    days = _days_by_employee(org, start, end, ids)
    leaves = _leaves_by_employee(org, start, end, ids)
    ctx = night_context(org.id, ids, start, end)
    notes = {(n.employee_id, n.date): n for n in DayNote.objects.filter(organization=org, employee_id__in=ids,
                                                                        date__gte=start, date__lte=end)}
    tol, fine = cfg.late_tolerance_minutes, Decimal(cfg.late_fine_per_minute or 0)
    cap = cfg.overtime_daily_cap_minutes

    tapped_days, tapped_people = 0, set()
    per_date = defaultdict(lambda: [0, 0, []])            # date -> [tracked, problems, names]
    covered_dates, off_for_all = set(), defaultdict(lambda: [0, 0])
    ot, miss, late = {}, {}, {}
    ot_decided = 0

    def note_of(emp_id, d):
        n = notes.get((emp_id, d))
        return {"code": n.code, "text": n.text} if n else None

    for emp in emps:
        rate = _daily_rate(emp, cfg)
        for d in _dates(start, min(end, today)):
            if d < emp.join_date or (emp.end_date and d > emp.end_date):
                continue
            day = days.get(emp.id, {}).get(d)
            lv = leaves.get(emp.id, {}).get(d)
            r = (evaluate(day, now, leave=lv[1] if lv else "", ctx=ctx) if day
                 else evaluate_missing(emp, d, now, leave=lv[1] if lv else "", ctx=ctx))
            if r.disrupted or r.holiday:
                covered_dates.add(d)
            off_for_all[d][0] += 1
            if r.status == Status.DAY_OFF:
                off_for_all[d][1] += 1
            if r.first_in or r.last_out:
                tapped_days += 1
                tapped_people.add(emp.id)
            # expected to tap that day (for the power-cut pattern)
            expected = r.status not in (Status.DAY_OFF, Status.LEAVE, Status.EXEMPT, Status.NOT_YET) \
                and not r.disrupted and not r.holiday
            if expected:
                per_date[d][0] += 1
                forgiven_day = day is not None and day.waive_late
                if r.status == Status.ABSENT or (r.half_day and not forgiven_day):
                    per_date[d][1] += 1
                    per_date[d][2].append(emp.full_name)
            if day is None or day.is_locked:
                continue
            base = {"day_id": str(day.id), "date": d.isoformat(), "in": _t(r.first_in), "out": _t(r.last_out),
                    "note": note_of(emp.id, d)}
            # overtime still open
            proposed = r.overtime_proposed_minutes or 0
            if proposed and not day.decision and day.overtime_approved_minutes is None:
                rest = Status.DAY_OFF_WORK in r.tags
                p = ot.setdefault(emp.id, {"employee": _emp(emp), "days": [], "proposed": 0})
                p["days"].append({**base, "proposed": proposed,
                                  "suggested": capped_overtime(proposed, None if rest else cap) or 0, "rest_day": rest})
                p["proposed"] += proposed
            elif day.decision == "approved" and day.overtime_approved_minutes:
                ot_decided += 1
            # one tap
            if r.half_day:
                forgiven = day.waive_late and day.decision != "rejected"
                cut = cfg.single_tap_half_day and not forgiven
                p = miss.setdefault(emp.id, {"employee": _emp(emp), "days": [], "cut_days": 0, "rupiah": 0})
                kind = "Tidak absen masuk" if Status.NO_CLOCK_IN in r.tags else "Tidak absen pulang"
                p["days"].append({**base, "kind": kind, "forgiven": forgiven, "cut": cut})
                if cut:
                    p["cut_days"] += 1
                    p["rupiah"] += R.rupiah_int(rate / 2)
            # late / early: facts, fined by the rule
            charged = R.late_charge(r.late_minutes if Status.LATE in r.tags else 0,
                                    r.early_minutes if Status.EARLY_OUT in r.tags else 0, tol)
            was_late = (r.late_minutes or 0) > tol or (r.early_minutes or 0) > 0
            if charged or (day.waive_late and was_late):
                p = late.setdefault(emp.id, {"employee": _emp(emp), "days": [], "minutes": 0, "rupiah": 0, "count": 0})
                p["days"].append({**base, "late": r.late_minutes or 0, "early": r.early_minutes or 0,
                                  "charged": charged, "rupiah": R.rupiah_int(charged * fine),
                                  "forgiven": bool(day.waive_late and not charged)})
                if charged:
                    p["count"] += 1
                    p["minutes"] += charged
                    p["rupiah"] += R.rupiah_int(charged * fine)

    # the power-cut pattern
    dismissed = _dismissed(org, start, end)
    flagged = [d for d, (tracked, probs, _) in per_date.items() if d not in covered_dates and R.is_cluster(probs, tracked)]
    everyone_off = lambda d: off_for_all[d][0] > 0 and off_for_all[d][1] == off_for_all[d][0]
    suggestions = []
    for s, e in R.group_dates(flagged, gap_ok=everyone_off):
        if any(ds <= s and e <= de for ds, de in dismissed):
            continue
        names, peak = set(), 0
        d = s
        while d <= e:
            if d in per_date:
                names.update(per_date[d][2])
                peak = max(peak, per_date[d][1])
            d += timedelta(days=1)
        suggestions.append({"start": s.isoformat(), "end": e.isoformat(), "people": len(names), "peak": peak,
                            "names": sorted(names)[:8]})
    events = [{"id": str(x.id), "start": x.start.isoformat(), "end": x.end.isoformat(), "kind": x.kind,
               "kind_label": x.get_kind_display(), "reason": x.reason}
              for x in CompanyEvent.objects.filter(organization=org, start__lte=end, end__gte=start).order_by("start")]

    # HR notes still to apply (only when the company imported notes)
    note_step = None
    if notes:
        from .note_decision_views import build as notes_build
        nb = notes_build(org, info["month"])
        todo = sum(g["todo"] for g in nb["groups"] if g["actionable"])
        note_step = {"total": nb["total"], "todo": todo}

    by_money = lambda rows, key: sorted(rows, key=lambda x: (-x[key], x["employee"]["full_name"]))
    ot_rows = by_money(list(ot.values()), "proposed")
    miss_rows = by_money(list(miss.values()), "rupiah")
    late_rows = by_money(list(late.values()), "rupiah")
    last_import = (ClockEvent.objects.filter(organization=org, source="fingerprint", day__date__gte=start,
                                             day__date__lte=end).order_by("-received_at").values_list("received_at", flat=True).first())
    run = PayRun.objects.filter(organization=org, period_end__year=end.year, period_end__month=end.month).first()
    return {
        "success": True, **info,
        "rules": {"late_fine_per_minute": str(fine), "late_tolerance_minutes": tol,
                  "single_tap_half_day": cfg.single_tap_half_day, "overtime_cap_minutes": cap},
        "import": {"days": tapped_days, "people": len(tapped_people), "employees": len(emps),
                   "last_import": timezone.localtime(last_import).isoformat() if last_import else None},
        "events": {"existing": events, "suggestions": suggestions},
        "notes": note_step,
        "overtime": {"open_days": sum(len(p["days"]) for p in ot_rows), "people": ot_rows,
                     "proposed": sum(p["proposed"] for p in ot_rows), "decided_days": ot_decided},
        "missing": {"days": sum(len(p["days"]) for p in miss_rows), "cut_days": sum(p["cut_days"] for p in miss_rows),
                    "rupiah": sum(p["rupiah"] for p in miss_rows), "people": miss_rows},
        "late": {"count": sum(p["count"] for p in late_rows), "minutes": sum(p["minutes"] for p in late_rows),
                 "rupiah": sum(p["rupiah"] for p in late_rows), "people": late_rows},
        "run": ({"id": str(run.id), "name": run.name, "locked": run.is_locked} if run else None),
    }


class ChecklistView(APIView):
    permission_classes = [IsCompanyHR]

    def get(self, request):
        return Response(build(request.hr_org, request.query_params.get("month")))


class ChecklistDismissView(APIView):
    permission_classes = [IsCompanyHR]

    def post(self, request):
        try:
            s, e = Date.fromisoformat(str(request.data.get("start"))), Date.fromisoformat(str(request.data.get("end")))
        except ValueError:
            return Response({"success": False, "message": "Tanggal tidak valid."}, status=status.HTTP_400_BAD_REQUEST)
        if e < s or (e - s).days > 62:
            return Response({"success": False, "message": "Tanggal tidak valid."}, status=status.HTTP_400_BAD_REQUEST)
        record_audit(organization=request.hr_org, actor=request.user, action=DISMISS, target=request.hr_org,
                     summary=f"Bukan kejadian: {s:%d-%m-%Y} s/d {e:%d-%m-%Y}", after={"start": s.isoformat(), "end": e.isoformat()})
        return Response({"success": True})
