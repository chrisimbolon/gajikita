# =============================================================================
# === backend/apps/attendance/fingerprint_import.py ===
# =============================================================================
"""
Fingerprint taps into GajiKita (G9, 1 Nov 2026).

  plan(org, punches)    match machine IDs to employees (Karyawan -> "ID Mesin Fingerprint"),
                        build each person's sessions, and count what is new, what was already
                        imported, and what falls on a locked (paid) day. Reads only.
  apply(org, plan, actor)   writes the new taps as ClockEvents (source "fingerprint") on the
                        right AttendanceDay. Safe to repeat: every tap has a fixed id made from
                        the employee and the time, so importing the same file twice adds nothing.

After import the taps behave like phone taps: Absensi, Perlu Tinjau, Lembur and Payroll see them.
They carry no GPS, so no location flags.
"""
import uuid
from collections import defaultdict

from django.db import transaction
from django.utils import timezone

from apps.core.audit import record_audit
from apps.employees.models import Employee

from .fingerprint import clean_id, make_sessions
from .models import AttendanceDay, ClockEvent

NAMESPACE = uuid.UUID("4f0d6c3e-7a1b-4c55-9d3e-2b6f8a9e1c07")      # fixed forever: re-imports find the same ids


def tap_id(employee, at, kind):
    return uuid.uuid5(NAMESPACE, f"fp|{employee.id}|{at.isoformat()}|{kind}")


def plan(org, punches):
    employees = {clean_id(e.fingerprint_id): e
                 for e in Employee.objects.filter(organization=org).exclude(fingerprint_id="")
                 .select_related("default_shift", "default_site")}
    times, names = defaultdict(list), {}
    for p in punches:
        times[p.machine_id].append(p.at)
        if p.name:
            names.setdefault(p.machine_id, p.name)

    people, unknown = [], []
    for machine_id in sorted(times, key=lambda x: (len(x), x)):
        emp = employees.get(machine_id)
        if emp is None:
            t = sorted(times[machine_id])
            unknown.append({"machine_id": machine_id, "name": names.get(machine_id, ""), "taps": len(t),
                            "first": t[0].isoformat(sep=" ", timespec="minutes"),
                            "last": t[-1].isoformat(sep=" ", timespec="minutes")})
            continue
        sessions = make_sessions(times[machine_id])
        events = []
        for s in sessions:
            events.append((s, "in", s.clock_in))
            if s.clock_out is not None:
                events.append((s, "out", s.clock_out))
        ids = [tap_id(emp, at, kind) for _, kind, at in events]
        already = set(ClockEvent.objects.filter(employee=emp, client_id__in=ids).values_list("client_id", flat=True))
        dates = {s.work_date for s in sessions}
        locked = set(AttendanceDay.objects.filter(employee=emp, date__in=dates, is_locked=True)
                     .values_list("date", flat=True))
        new_sessions = [s for s in sessions if s.work_date not in locked
                        and any(tap_id(emp, at, kind) not in already for ss, kind, at in events if ss is s)]
        people.append({
            "employee": emp, "machine_id": machine_id, "name_in_file": names.get(machine_id, ""),
            "sessions": sessions, "events": events, "already": already, "locked": locked,
            "days": len(dates), "new_days": len(new_sessions),
            "already_days": sum(1 for s in sessions if s.work_date not in locked and s not in new_sessions),
            "locked_days": len(locked),
            "no_clock_out": sum(1 for s in sessions if s.clock_out is None),
        })
    all_dates = [s.work_date for p in people for s in p["sessions"]]
    return {
        "people": people, "unknown": unknown,
        "period": {"start": min(all_dates).isoformat(), "end": max(all_dates).isoformat()} if all_dates else None,
        "not_linked": [{"employee_no": e.employee_no, "full_name": e.full_name}
                       for e in Employee.objects.filter(organization=org, status=Employee.Status.ACTIVE, fingerprint_id="")
                       .order_by("full_name")[:50]],
    }


def public(p):
    return {
        "period": p["period"], "unknown": p["unknown"], "not_linked": p["not_linked"],
        "people": [{"employee": {"id": str(x["employee"].id), "employee_no": x["employee"].employee_no,
                                 "full_name": x["employee"].full_name},
                    "machine_id": x["machine_id"], "name_in_file": x["name_in_file"], "days": x["days"],
                    "new_days": x["new_days"], "already_days": x["already_days"], "locked_days": x["locked_days"],
                    "no_clock_out": x["no_clock_out"]} for x in p["people"]],
        "totals": {"people": len(p["people"]), "unknown": len(p["unknown"]),
                   "new_days": sum(x["new_days"] for x in p["people"]),
                   "already_days": sum(x["already_days"] for x in p["people"]),
                   "locked_days": sum(x["locked_days"] for x in p["people"])},
    }


def apply(org, p, actor, filename=""):
    tz = timezone.get_current_timezone()
    now = timezone.now()
    days_touched, events_added = set(), 0
    with transaction.atomic():
        for x in p["people"]:
            emp = x["employee"]
            for s, kind, at in x["events"]:
                if s.work_date in x["locked"]:
                    continue
                cid = tap_id(emp, at, kind)
                if cid in x["already"]:
                    continue
                day, _ = AttendanceDay.objects.get_or_create(
                    employee=emp, date=s.work_date,
                    defaults={"organization": org, "shift": emp.default_shift})
                if day.is_locked:
                    continue
                ClockEvent.objects.create(
                    organization=org, day=day, employee=emp, kind=kind, source=ClockEvent.Source.FINGERPRINT,
                    site=emp.default_site, occurred_at=timezone.make_aware(at, tz), received_at=now,
                    flags=[], client_id=cid)
                days_touched.add((emp.id, s.work_date))
                events_added += 1
        if events_added:
            record_audit(organization=org, actor=actor, action="attendance.fingerprint_import", target=org,
                         summary=f"Import fingerprint{(' ' + filename) if filename else ''}: {events_added} tap, "
                                 f"{len(days_touched)} hari kerja",
                         after={"events": events_added, "days": len(days_touched), "file": filename})
    return {"events": events_added, "days": len(days_touched)}
