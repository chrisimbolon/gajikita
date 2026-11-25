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
POST /api/hr/attendance/checklist/dismiss/  {start, end} | {employee}   "Bukan kejadian" / "Bukan, dia wajib absen":
     the suggestion stops showing (audited)

G17-7.1 (16 Nov 2026, first look on seegaji.com): people who (almost) never tap completely, such as a manager, sales,
someone at another site or security on night shifts, made every date look like a power cut (26 Sep: 12 people).
Now a person whose days are mostly missing taps ("chronic", 50%+ of their working days) is left out of the
power-cut pattern and suggested once as "Tidak wajib absen?" instead (step "Siapa yang tidak perlu absen?").

G17-7.2 (16 Nov 2026): (1) someone who tapped, then has 5+ working days in a row with no tap up to the end of the
data ("left", Nur Aji: last tap 1 Okt) is asked "Sudah keluar?" (fills Tanggal keluar) instead of "Tidak wajib
absen?"; (2) days after the last tap in the company's data are "not imported yet", never "absent": a mid-month
import can't make everyone look gone or suggest a power cut for the days not imported.

Only days up to today are counted; locked days are left out of the lists (they can't change).

G20-2 (24 Nov 2026): step "Tidak cocok": days where two things can't both be true (a tap or uang makan on a leave
day, overtime paid on a leave / absent day, ½ day cut but overtime paid), from the payroll's own day-by-day decisions
(attendance_log.day_conflicts). Soft: HR fixes the data, or marks one "Sudah benar" (audited, it stops showing):
POST /api/hr/attendance/checklist/dismiss/  {"conflict": {"employee", "date", "kind"}}
"""
from collections import defaultdict
from datetime import date as Date, timedelta
from decimal import Decimal

from django.db.models import Max
from django.utils import timezone
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.audit import record_audit
from apps.core.models import AuditEntry
from apps.organizations.permissions import IsCompanyHR
from apps.payroll import engine as pay_engine                                          # G13-4: one rule
from apps.payroll.models import PayrollSettings, PayRun

from . import checklist_rules as R
from .day_status import Status
from .models import ClockEvent, CompanyEvent, DayNote
from .review import evaluate, evaluate_missing, night_context
from .review_bulk import _period
from .review_kinds import capped_overtime

DISMISS = "attendance.event_dismiss"
NOTRACK_DISMISS = "attendance.notrack_dismiss"                                              # G17-7.1
CONFLICT_DISMISS = "attendance.conflict_dismiss"                                            # G20-2
CHRONIC_SHARE = Decimal("0.5")


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


def _notrack_dismissed(org):
    return {str(((a.data or {}).get("after") or {}).get("employee")) for a in AuditEntry.objects.filter(organization=org, action=NOTRACK_DISMISS)}


def _conflict_dismissed(org):                                                               # G20-2
    out = set()
    for a in AuditEntry.objects.filter(organization=org, action=CONFLICT_DISMISS):
        d = (a.data or {}).get("after") or {}
        out.add((str(d.get("employee")), str(d.get("date")), str(d.get("kind"))))
    return out


def conflicts_for(org, start, end, now, long_limit, traced=None):                           # G20-2
    from .attendance_log import period_traces, person_conflicts
    if traced is None:
        _, traced = period_traces(org, start, end, now)
    gone = _conflict_dismissed(org)
    rows = [c for c in (person_conflicts(emp, trace, long_limit, gone) for emp, _, trace in traced) if c]
    rows.sort(key=lambda c: (-len(c["items"]), c["employee"]["full_name"]))
    return {"days": sum(len(c["items"]) for c in rows), "people": rows}


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
    long_limit = cfg.long_late_half_day_minutes                                       # G13-4
    cap = cfg.overtime_daily_cap_minutes

    last_data = (ClockEvent.objects.filter(organization=org, day__date__gte=start, day__date__lte=end)
                 .aggregate(m=Max("day__date"))["m"])                               # G17-7.2
    until = min(end, today, last_data) if last_data else min(end, today)
    tapped_days, tapped_people, not_imported = 0, set(), set()
    per_date = defaultdict(list)                          # date -> [(employee, "ok" | "absent" | "one")]
    person = defaultdict(lambda: {"expected": 0, "problems": 0, "tapped": 0, "complete": 0, "seq": []})
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
            if expected and d > until:                     # G17-7.2: not imported yet != absent
                not_imported.add(d)                        # (G17-7.2.1: only working days count, not a last Sunday)
                expected = False
            if expected:
                forgiven_day = day is not None and day.waive_late
                what = "absent" if r.status == Status.ABSENT else "one" if (r.half_day and not forgiven_day) else "ok"
                per_date[d].append((emp, what))
                pp = person[emp.id]
                pp["expected"] += 1
                pp["problems"] += what != "ok"
                pp["tapped"] += bool(r.first_in or r.last_out)
                pp["complete"] += bool(r.first_in and r.last_out)
                pp["seq"].append((d, what, bool(r.first_in or r.last_out)))
            if day is None or day.is_locked:
                continue
            base = {"day_id": str(day.id), "date": d.isoformat(), "in": _t(r.first_in), "out": _t(r.last_out),
                    "note": note_of(emp.id, d)}
            # overtime still open
            proposed = r.overtime_proposed_minutes or 0
            if proposed and not day.decision and day.overtime_approved_minutes is None and not r.overtime_spl_minutes:
                rest = Status.DAY_OFF_WORK in r.tags                    # G17-E1: a day paid by an SPL is not open
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
            # late / early: facts, fined by the rule (G13-4: a long one = ½ day, the same rule as the payroll)
            one_cut = bool(r.half_day and cfg.single_tap_half_day and not (day.waive_late and day.decision != "rejected"))
            l_min, e_min, halves = pay_engine.long_late_split(
                r.late_minutes if Status.LATE in r.tags else 0, r.early_minutes if Status.EARLY_OUT in r.tags else 0,
                long_limit, room=2 - int(one_cut) - int(r.half_leave == "unpaid"))
            charged = R.late_charge(l_min, e_min, tol)
            money = R.rupiah_int(charged * fine + halves * rate / 2)
            was_late = (r.late_minutes or 0) > tol or (r.early_minutes or 0) > 0
            if charged or halves or (day.waive_late and was_late):
                p = late.setdefault(emp.id, {"employee": _emp(emp), "days": [], "minutes": 0, "rupiah": 0, "count": 0,
                                             "half_days": 0})
                p["days"].append({**base, "late": r.late_minutes or 0, "early": r.early_minutes or 0,
                                  "charged": charged, "half": halves, "rupiah": money,
                                  "forgiven": bool(day.waive_late and not charged and not halves)})
                if charged or halves:
                    p["count"] += 1
                    p["minutes"] += charged
                    p["half_days"] += halves
                    p["rupiah"] += money

    # people who (almost) never tap completely: not part of the pattern; suggested as "Tidak wajib absen?"
    left = {}                                                                         # G17-7.2: stopped tapping
    for eid, pp in person.items():
        last_tap = max((d for d, _, t in pp["seq"] if t), default=None)
        after = [w for d, w, _ in pp["seq"] if last_tap and d > last_tap]
        if last_tap and len(after) >= R.LEFT_AFTER_DAYS and all(w == "absent" for w in after):
            left[eid] = (last_tap, len(after))
    chronic = {eid for eid, pp in person.items()
               if eid not in left and pp["expected"] >= 3 and Decimal(pp["problems"]) / Decimal(pp["expected"]) >= CHRONIC_SHARE}
    by_id = {e.id: e for e in emps}
    skip_people = _notrack_dismissed(org)
    no_track = [{"employee": _emp(by_id[eid]), "kind": "notrack", "expected": person[eid]["expected"],
                 "tapped": person[eid]["tapped"], "complete": person[eid]["complete"],
                 "start": max(start, by_id[eid].join_date).isoformat(), "last_tap": None, "missing_after": 0}
                for eid in chronic if str(eid) not in skip_people]
    no_track += [{"employee": _emp(by_id[eid]), "kind": "left", "expected": person[eid]["expected"],
                  "tapped": person[eid]["tapped"], "complete": person[eid]["complete"],
                  "start": max(start, by_id[eid].join_date).isoformat(), "last_tap": lt.isoformat(), "missing_after": n}
                 for eid, (lt, n) in left.items() if str(eid) not in skip_people]
    no_track.sort(key=lambda x: (x["kind"] != "left", x["complete"], x["employee"]["full_name"]))
    chronic |= set(left)                                   # neither counts in the power-cut pattern

    # the power-cut pattern
    dismissed = _dismissed(org, start, end)
    counted = {d: [(e, w) for e, w in rows if e.id not in chronic] for d, rows in per_date.items()}
    flagged = [d for d, rows in counted.items()
               if d not in covered_dates and R.is_cluster(sum(1 for _, w in rows if w != "ok"), len(rows))]
    everyone_off = lambda d: off_for_all[d][0] > 0 and off_for_all[d][1] == off_for_all[d][0]
    suggestions = []
    for s, e in R.group_dates(flagged, gap_ok=everyone_off):
        if any(ds <= s and e <= de for ds, de in dismissed):
            continue
        names, peak, absent, one = set(), 0, 0, 0
        d = s
        while d <= e:
            probs = [(emp, w) for emp, w in counted.get(d, []) if w != "ok"]
            names.update(emp.full_name for emp, _ in probs)
            peak = max(peak, len(probs))
            absent += sum(1 for _, w in probs if w == "absent")
            one += sum(1 for _, w in probs if w == "one")
            d += timedelta(days=1)
        suggestions.append({"start": s.isoformat(), "end": e.isoformat(), "people": len(names), "peak": peak,
                            "names": sorted(names)[:8], "absent": absent, "one_tap": one})
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
    from .attendance_log import period_traces                                               # G21-3a: traced once
    _, traced = period_traces(org, start, end, now)
    return {
        "success": True, **info,
        "no_track": no_track,                                                                         # G17-7.1
        "rules": {"late_fine_per_minute": str(fine), "late_tolerance_minutes": tol, "fine_set": fine > 0,
                  "single_tap_half_day": cfg.single_tap_half_day, "overtime_cap_minutes": cap,
                  "long_late_half_day_minutes": long_limit},                                                   # G13-4
        "import": {"days": tapped_days, "people": len(tapped_people), "employees": len(emps),
                   "until": until.isoformat(), "short": bool(last_data) and bool(not_imported),             # G17-7.2.1
                   "last_import": timezone.localtime(last_import).isoformat() if last_import else None},
        "events": {"existing": events, "suggestions": suggestions},
        "notes": note_step,
        "overtime": {"open_days": sum(len(p["days"]) for p in ot_rows), "people": ot_rows,
                     "proposed": sum(p["proposed"] for p in ot_rows), "decided_days": ot_decided},
        "missing": {"days": sum(len(p["days"]) for p in miss_rows), "cut_days": sum(p["cut_days"] for p in miss_rows),
                    "rupiah": sum(p["rupiah"] for p in miss_rows), "people": miss_rows},
        "late": {"count": sum(p["count"] for p in late_rows), "minutes": sum(p["minutes"] for p in late_rows),
                 "half_days": sum(p["half_days"] for p in late_rows),                                         # G13-4
                 "rupiah": sum(p["rupiah"] for p in late_rows), "people": late_rows},
        "conflicts": conflicts_for(org, start, end, now, long_limit, traced),                           # G20-2
        "saran": saran_for(org, start, end, cfg, traced),                                               # G21-3a
        "run": ({"id": str(run.id), "name": run.name, "locked": run.is_locked} if run else None),
    }


def saran_for(org, start, end, cfg, traced):                                               # G21-3a
    """Saran SeeGaji (s1-s3) for everyone in the period: a soft step, never blocking."""
    from .attendance_log import rates_for
    from .suggestions import for_period
    return for_period(org, start, end, traced, lambda emp: rates_for(emp, cfg))


class ChecklistView(APIView):
    permission_classes = [IsCompanyHR]

    def get(self, request):
        return Response(build(request.hr_org, request.query_params.get("month")))


class ChecklistDismissView(APIView):
    permission_classes = [IsCompanyHR]

    def post(self, request):
        conflict = request.data.get("conflict")                                           # G20-2
        if isinstance(conflict, dict):
            from apps.employees.models import Employee
            from .attendance_log import CONFLICT_KINDS
            emp = Employee.objects.filter(organization=request.hr_org, pk=conflict.get("employee")).first()
            kind = str(conflict.get("kind") or "")
            try:
                d = Date.fromisoformat(str(conflict.get("date")))
            except ValueError:
                d = None
            if emp is None or d is None or kind not in CONFLICT_KINDS:
                return Response({"success": False, "message": "Data tidak valid."}, status=status.HTTP_400_BAD_REQUEST)
            record_audit(organization=request.hr_org, actor=request.user, action=CONFLICT_DISMISS, target=emp,
                         summary=f"{emp.full_name} {d:%d-%m-%Y}: sudah benar ({CONFLICT_KINDS[kind]})",
                         after={"employee": str(emp.pk), "date": d.isoformat(), "kind": kind})
            return Response({"success": True})
        if request.data.get("employee"):                                                  # G17-7.1
            from apps.employees.models import Employee
            emp = Employee.objects.filter(organization=request.hr_org, pk=request.data.get("employee")).first()
            if emp is None:
                return Response({"success": False, "message": "Karyawan tidak ditemukan."}, status=status.HTTP_400_BAD_REQUEST)
            record_audit(organization=request.hr_org, actor=request.user, action=NOTRACK_DISMISS, target=emp,
                         summary=f"{emp.full_name}: tetap wajib absen (bukan tidak wajib absen)", after={"employee": str(emp.pk)})
            return Response({"success": True})
        try:
            s, e = Date.fromisoformat(str(request.data.get("start"))), Date.fromisoformat(str(request.data.get("end")))
        except ValueError:
            return Response({"success": False, "message": "Tanggal tidak valid."}, status=status.HTTP_400_BAD_REQUEST)
        if e < s or (e - s).days > 62:
            return Response({"success": False, "message": "Tanggal tidak valid."}, status=status.HTTP_400_BAD_REQUEST)
        record_audit(organization=request.hr_org, actor=request.user, action=DISMISS, target=request.hr_org,
                     summary=f"Bukan kejadian: {s:%d-%m-%Y} s/d {e:%d-%m-%Y}", after={"start": s.isoformat(), "end": e.isoformat()})
        return Response({"success": True})
