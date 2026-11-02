# =============================================================================
# === backend/apps/attendance/fingerprint_delete.py ===
# =============================================================================
"""
Undo a fingerprint import: "Hapus data import" (G9b, 2 Nov 2026).

  plan(org, start, end, keep_decided)   what would be removed between two dates. Reads only.
  apply(org, plan, actor, reason)       removes it in one transaction and writes one audit entry.

Rules
  - Only taps from the machine (source "fingerprint") are removed. Phone taps, kiosk taps,
    leave and everything else stay.
  - Days in a locked payroll are never touched: reopen the payroll first (with a note).
  - Days HR already worked on (approved / rejected, "Ubah jam", approved overtime) are kept by
    default. With keep_decided=False they are removed too, and HR's decision on them is reset.
  - A day left with no taps and no HR decision is removed, so it reads exactly as before the import.
  - Afterwards the same file can be imported again (the taps' fixed ids are gone with them).
"""
from collections import defaultdict

from django.db import transaction

from apps.core.audit import record_audit

from .models import AttendanceDay, ClockEvent

MAX_LISTED = 50


def hr_touched(day):
    """What HR did on this day, in plain words ([] = nothing)."""
    out = []
    if day.decision == "approved":
        out.append("Disetujui HR")
    elif day.decision == "rejected":
        out.append("Ditolak HR")
    if day.hr_in or day.hr_out:
        out.append("Jam dikoreksi HR")
    if day.overtime_approved_minutes:
        out.append(f"Lembur disetujui {day.overtime_approved_minutes} menit")
    return out


def plan(org, start, end, keep_decided=True):
    taps = (ClockEvent.objects.filter(organization=org, source=ClockEvent.Source.FINGERPRINT,
                                      day__date__gte=start, day__date__lte=end)
            .select_related("day", "employee"))
    by_day = defaultdict(list)
    for t in taps:
        by_day[t.day_id].append(t)
    days = {d.id: d for d in AttendanceDay.objects.filter(id__in=by_day).select_related("employee")}

    remove, locked, decided_kept, decided_removed = [], [], [], []
    for day_id, day_taps in by_day.items():
        day = days[day_id]
        if day.is_locked:
            locked.append(day)
            continue
        touched = hr_touched(day)
        if touched and keep_decided:
            decided_kept.append((day, touched))
            continue
        if touched:
            decided_removed.append((day, touched))
        remove.append(day)

    people = defaultdict(lambda: {"taps": 0, "days": 0})
    for day in remove:
        p = people[day.employee]
        p["taps"] += len(by_day[day.id])
        p["days"] += 1

    from apps.payroll.models import PayRun
    runs = PayRun.objects.filter(organization=org, period_start__lte=end, period_end__gte=start)
    return {
        "start": start, "end": end, "keep_decided": keep_decided,
        "remove": remove, "by_day": by_day, "locked": locked,
        "decided_kept": decided_kept, "decided_removed": decided_removed, "people": people,
        "draft_runs": [r.name for r in runs if r.status == PayRun.Status.DRAFT],
        "locked_runs": [r.name for r in runs if r.status == PayRun.Status.LOCKED],
    }


def _day_line(day, touched):
    return {"employee_no": day.employee.employee_no, "full_name": day.employee.full_name,
            "date": day.date.isoformat(), "what": touched}


def public(p):
    ordered = sorted(p["people"].items(), key=lambda kv: kv[0].full_name)
    return {
        "start": p["start"].isoformat(), "end": p["end"].isoformat(), "keep_decided": p["keep_decided"],
        "totals": {"taps": sum(len(p["by_day"][d.id]) for d in p["remove"]), "days": len(p["remove"]),
                   "people": len(p["people"]), "locked_days": len(p["locked"]),
                   "decided_kept": len(p["decided_kept"]), "decided_removed": len(p["decided_removed"])},
        "people": [{"employee": {"id": str(e.id), "employee_no": e.employee_no, "full_name": e.full_name},
                    "taps": v["taps"], "days": v["days"]} for e, v in ordered],
        "decided": [_day_line(d, t) for d, t in sorted(p["decided_kept"] + p["decided_removed"],
                                                      key=lambda x: (x[0].date, x[0].employee.full_name))][:MAX_LISTED],
        "draft_runs": p["draft_runs"], "locked_runs": p["locked_runs"],
    }


def apply(org, p, actor, reason):
    taps_removed = days_removed = 0
    with transaction.atomic():
        for day in p["remove"]:
            day = AttendanceDay.objects.select_for_update().get(pk=day.pk)
            if day.is_locked:                       # locked in the meantime: leave it
                continue
            n, _ = ClockEvent.objects.filter(day=day, source=ClockEvent.Source.FINGERPRINT).delete()
            taps_removed += n
            if hr_touched(day) or day.decision_note:
                day.decision, day.decision_note, day.waive_late = "", "", False
                day.overtime_approved_minutes = None
                day.hr_in = day.hr_out = None
                day.decided_by = day.decided_at = None
                day.save()
            if not day.events.exists():
                day.delete()
                days_removed += 1
        if taps_removed:
            record_audit(
                organization=org, actor=actor, action="attendance.fingerprint_delete", target=org,
                summary=f"Hapus import fingerprint {p['start']:%d-%m-%Y} s/d {p['end']:%d-%m-%Y}: "
                        f"{taps_removed} tap, {len(p['remove'])} hari kerja",
                after={"taps": taps_removed, "days": len(p["remove"]), "days_removed": days_removed,
                       "keep_decided": p["keep_decided"], "decided_reset": len(p["decided_removed"])},
                note=reason)
    return {"taps": taps_removed, "days": len(p["remove"]), "days_removed": days_removed}
