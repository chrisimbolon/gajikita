# =============================================================================
# === backend/apps/attendance/suggestion_actions.py ===
# =============================================================================
"""
G21-3b (25 Nov 2026) — Saran SeeGaji: HR's buttons (design G21-3 v0.2, D67, D70, D73-D75).

  preview   what a suggestion would change, day by day and on the slip, BEFORE anything is saved: the real apply
            runs inside a transaction that is always rolled back, so the preview is the payroll's own answer.
  apply     s1/s3: the night tap MOVES to the day before as its pulang (D73), exactly what the import does since
            G20-2.2: no invented time, approved overtime and decisions untouched. s2: HR's pulang (and masuk when
            the day has none) as Ubah jam writes them, but the approved overtime is KEPT (D70; Ubah jam would
            re-derive it from the new times). The suggestion is checked again first: one that no longer fits is
            refused and nothing changes. Then only this person's payroll line is recalculated (G21-2).
  dismiss   "Bukan": never suggested again for that day (D74). Leave-with-taps (s4) keeps G20-2's "Sudah benar".
  undo      "Kembalikan": a moved tap goes back to its own day with its old kind.

Every write is audited (attendance.suggestion_apply / _undo / _dismiss) and tied to the day it changed, so the day
panel's history shows it. A tap gets no flag (a flag would make the day "Belum ditinjau"); the history is the record.
"""
from datetime import date, datetime, timedelta

from django.db import transaction
from django.utils import timezone
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.audit import record_audit
from apps.core.models import AuditEntry
from apps.organizations.permissions import IsCompanyHR

APPLY, UNDO, DISMISS = "attendance.suggestion_apply", "attendance.suggestion_undo", "attendance.suggestion_dismiss"
GONE = "Saran ini sudah tidak berlaku (harinya sudah berubah). Muat ulang halaman."
LOCKED = "Hari ini sudah dikunci (payroll dikunci)."


class Refused(Exception):
    pass


class _Rollback(Exception):
    def __init__(self, result):
        self.result = result


def dismissed_for(org, employee_ids=None):
    """{employee_id (str): {(date_iso, kind)}} from HR's "Bukan"."""
    out = {}
    qs = AuditEntry.objects.filter(organization=org, action=DISMISS)
    for a in qs:
        d = (a.data or {}).get("after") or {}
        if employee_ids is None or d.get("employee") in employee_ids:
            out.setdefault(str(d.get("employee")), set()).add((str(d.get("date")), str(d.get("kind"))))
    return out


def moved_taps(org, emp, start, end):
    """{to_date_iso: [{"event", "time", "from"}]}: taps a suggestion moved INTO a day of the period, still there."""
    from .models import ClockEvent
    applied = [((a.data or {}).get("after") or {}) for a in
               AuditEntry.objects.filter(organization=org, action=APPLY).order_by("created_at")]
    applied = [a for a in applied if a.get("employee") == str(emp.id) and a.get("event")
               and start.isoformat() <= str(a.get("to")) <= end.isoformat()]
    if not applied:
        return {}
    here = {str(e.id): e for e in ClockEvent.objects.filter(pk__in=[a["event"] for a in applied]).select_related("day")}
    out = {}
    for a in applied:
        e = here.get(a["event"])
        if e is not None and e.day.date.isoformat() == a["to"]:
            out.setdefault(a["to"], {})[a["event"]] = {"event": a["event"], "time": a.get("time"), "from": a.get("from")}
    return {k: list(v.values()) for k, v in out.items()}


# ── one person's period, as the payroll sees it ──

def _period(org, month):
    from .review_bulk import _period as period
    return period(org, month)


def state(org, emp, start, end, now=None):
    """-> (cfg, trace, cells, suggestions): the payroll's own trace and the suggestions on it."""
    from apps.payroll.models import PayrollSettings
    from apps.payroll.payrun import _days_by_employee, _leaves_by_employee, collect_numbers
    from . import suggestions as saran
    from .attendance_log import rates_for
    from .review import night_context
    now = now or timezone.now()
    cfg = PayrollSettings.for_org(org)
    trace, cells = [], []
    collect_numbers(emp, start, end, cfg, _days_by_employee(org, start, end, [emp.id]).get(emp.id, {}),
                    _leaves_by_employee(org, start, end, [emp.id]).get(emp.id, {}), now, cells=cells,
                    ctx=night_context(org.id, [emp.id], start, end), trace=trace)
    found = saran.find(emp, trace, saran.taps_by_day(org, [emp.id], start, end).get(emp.id, {}),
                       saran.notes_by_day(org, [emp.id], start, end).get(emp.id, {}), rates_for(emp, cfg),
                       dismissed_for(org, [str(emp.id)]).get(str(emp.id), set()))
    return cfg, trace, cells, [s for s in found if s["kind"] != "s4"]


def _hm(minutes):
    h, m = divmod(int(minutes or 0), 60)
    return "–" if not minutes else (f"{h} j {m} mnt" if h and m else (f"{h} j" if h else f"{m} mnt"))


def snapshot(trace, cells, dates):
    """{date_iso: {label: value}} of what HR reads on the day, for the dates a suggestion touches."""
    from .attendance_log import hhmm
    by_t = {t["date"].isoformat(): t for t in trace}
    by_c = {c["d"]: c for c in cells}
    out = {}
    for iso in dates:
        t, c = by_t.get(iso), by_c.get(iso)
        if t is None or c is None:
            continue
        lo = t["last_out"]
        nxt = lo is not None and timezone.localtime(lo).date() > t["date"]
        out[iso] = {
            "Status": c.get("l") or "",
            "Masuk": hhmm(t["first_in"]) or "–",
            "Pulang": (hhmm(lo) + (" (+1)" if nxt else "")) if lo else "–",
            "Lembur": _hm(t["overtime"]),
            "Uang makan": f"{t['meal']}×" if t["meal"] else "–",
            "Telat": f"{t['late_raw']} mnt" if (t["late_tag"] and t["late_raw"]) else "–",
            "Aturan pulang malam": t.get("night_rule") or "–",
        }
    return out


def diff(before, after):
    """-> [{"date", "label", "before", "after"}] only what changed, in date order."""
    rows = []
    for iso in sorted(set(before) | set(after)):
        b, a = before.get(iso, {}), after.get(iso, {})
        for label in a:
            if b.get(label) != a.get(label):
                rows.append({"date": iso, "label": label, "before": b.get(label, "–"), "after": a[label]})
    return rows


# ── the writes ──

def _parse_time(value):
    try:
        return datetime.strptime(str(value).strip().replace(".", ":"), "%H:%M").time()
    except (TypeError, ValueError):
        raise Refused("Jam tidak valid (contoh 19:30).")


def _do(org, emp, s, data, actor):
    """Apply suggestion s (already checked current). -> (summary, day the audit belongs to, after-data)."""
    from .models import AttendanceDay, ClockEvent
    tz = timezone.get_current_timezone()
    d = date.fromisoformat(s["date"])
    if s["kind"] in ("s1", "s3"):
        to = date.fromisoformat(s["to_date"])
        ev = (ClockEvent.objects.select_for_update().select_related("day")
              .filter(employee=emp, day__date=d).order_by("occurred_at").first())
        if ev is None or timezone.localtime(ev.occurred_at).strftime("%H:%M") != s["tap"]:
            raise Refused(GONE)
        target, _ = AttendanceDay.objects.get_or_create(employee=emp, date=to, defaults={
            "organization": emp.organization, "shift": emp.default_shift})
        if target.is_locked or ev.day.is_locked:
            raise Refused(LOCKED)
        kind_was = ev.kind
        ev.day, ev.kind = target, ClockEvent.Kind.OUT
        ev.save(update_fields=["day", "kind"])
        summary = (f"{emp.full_name}: tap {s['tap']} tanggal {d:%d-%m-%Y} dipindah ke {to:%d-%m-%Y} sebagai jam pulang "
                   f"(saran SeeGaji)")
        return summary, target, {"employee": str(emp.id), "kind": s["kind"], "event": str(ev.id), "time": s["tap"],
                                 "from": d.isoformat(), "to": to.isoformat(), "kind_was": kind_was}
    if s["kind"] == "s2":
        from .hr_views import _snapshot
        day, _ = AttendanceDay.objects.select_for_update().get_or_create(employee=emp, date=d, defaults={
            "organization": emp.organization, "shift": emp.default_shift})
        if day.is_locked:
            raise Refused(LOCKED)
        before = _snapshot(day)
        clock_out = _parse_time(data.get("clock_out") or s["prefill"]["clock_out"])
        first_tap = min((e.occurred_at for e in day.events.all()), default=None)
        if data.get("clock_in") and first_tap is None and day.hr_in is None:
            day.hr_in = datetime.combine(d, _parse_time(data["clock_in"]), tzinfo=tz)
        out = datetime.combine(d, clock_out, tzinfo=tz)
        start = day.hr_in or first_tap
        if start is not None and out <= start:
            out += timedelta(days=1)                         # past midnight: the next morning
        day.hr_out = out
        day.save(update_fields=["hr_in", "hr_out", "updated_at"])  # decision and approved overtime stay (D70)
        summary = (f"{emp.full_name} {d:%d-%m-%Y}: jam pulang {clock_out:%H:%M} diisi dari saran SeeGaji "
                   f"(lembur yang disetujui tetap)")
        return summary, day, {"employee": str(emp.id), "kind": "s2", "date": d.isoformat(), "before": before,
                              "after": _snapshot(day)}
    raise Refused("Saran ini diselesaikan di Cuti & Izin atau dengan Sudah benar.")


def _current(org, emp, month, sid):
    info, start, end = _period(org, month)
    cfg, trace, cells, found = state(org, emp, start, end)
    s = next((x for x in found if x["id"] == sid), None)
    if s is None:
        raise Refused(GONE)
    return info, start, end, trace, cells, s


def _dates(s):
    d = date.fromisoformat(s["date"])
    out = {d - timedelta(days=1), d, d + timedelta(days=1)}
    return sorted(x.isoformat() for x in out)


def _line(org, emp, start):
    from apps.payroll.models import PayRun, PayRunLine
    run = PayRun.objects.filter(organization=org, period_start=start).first()
    if run is None or run.is_locked:
        return run, None
    return run, PayRunLine.objects.filter(run=run, employee=emp).first()


def _money(v):
    return str(v.quantize(1)) if v is not None else None


def preview(org, emp, month, sid, data):
    from apps.payroll.payrun import recalculate_line
    info, start, end, trace, cells, s = _current(org, emp, month, sid)
    dates = _dates(s)
    before = snapshot(trace, cells, dates)
    try:
        with transaction.atomic():
            run, line = _line(org, emp, start)
            net_before = net_after = None
            if line is not None:
                net_before = _money(recalculate_line(line).net)        # the slip from today's attendance
            _do(org, emp, s, data, None)
            _, trace2, cells2, _ = state(org, emp, start, end)
            if line is not None:
                net_after = _money(recalculate_line(line).net)
            raise _Rollback({"changes": diff(before, snapshot(trace2, cells2, dates)),
                             "net_before": net_before, "net_after": net_after, "run": run.name if run else None})
    except _Rollback as r:
        return {"success": True, "suggestion": s, **r.result}


def apply(org, emp, month, sid, data, actor):
    from apps.payroll.payrun import recalculate_line
    info, start, end, trace, cells, s = _current(org, emp, month, sid)
    with transaction.atomic():
        summary, day, after = _do(org, emp, s, data, actor)
        record_audit(organization=org, actor=actor, action=APPLY, target=day, summary=summary, after=after,
                     note=(data.get("reason") or "").strip() or "; ".join(s["evidence"]) or "dikonfirmasi HR")
    return {"success": True, "message": summary, "payroll": _recalc(org, emp, start)}


def _recalc(org, emp, start):
    from apps.payroll.payrun import recalculate_line
    run, line = _line(org, emp, start)
    if line is None:
        return {"run": run.name, "locked": True} if (run and run.is_locked) else None
    before = _money(line.net)
    after = _money(recalculate_line(line).net)
    return {"run": run.name, "locked": False, "net_before": before, "net_after": after}


def undo(org, emp, event_id, actor):
    from .models import AttendanceDay, ClockEvent
    ev = ClockEvent.objects.select_related("day").filter(organization=org, employee=emp, pk=event_id).first()
    applied = None
    for a in AuditEntry.objects.filter(organization=org, action=APPLY).order_by("-created_at"):
        d = (a.data or {}).get("after") or {}
        if d.get("event") == str(event_id):
            applied = d
            break
    if ev is None or applied is None or ev.day.date.isoformat() != applied.get("to"):
        raise Refused("Tap ini tidak bisa dikembalikan (sudah dikembalikan atau diubah).")
    back = date.fromisoformat(applied["from"])
    with transaction.atomic():
        home, _ = AttendanceDay.objects.get_or_create(employee=emp, date=back, defaults={
            "organization": emp.organization, "shift": emp.default_shift})
        if home.is_locked or ev.day.is_locked:
            raise Refused(LOCKED)
        moved_to = ev.day
        ev.day, ev.kind = home, applied.get("kind_was") or ClockEvent.Kind.IN
        ev.save(update_fields=["day", "kind"])
        summary = (f"{emp.full_name}: tap {applied.get('time')} dikembalikan dari {moved_to.date:%d-%m-%Y} ke "
                   f"{back:%d-%m-%Y}")
        record_audit(organization=org, actor=actor, action=UNDO, target=moved_to, summary=summary,
                     after={**applied, "undone": True})
    period_start = _period_start_for(org, back)
    return {"success": True, "message": summary, "payroll": _recalc(org, emp, period_start) if period_start else None}


def _period_start_for(org, d):
    from apps.payroll.models import PayRun
    run = PayRun.objects.filter(organization=org, period_start__lte=d, period_end__gte=d).first()
    return run.period_start if run else None


def dismiss(org, emp, month, sid, actor):
    info, start, end, trace, cells, s = _current(org, emp, month, sid)
    d = date.fromisoformat(s["date"])
    record_audit(organization=org, actor=actor, action=DISMISS, target=emp,
                 summary=f"{emp.full_name} {d:%d-%m-%Y}: saran SeeGaji ditolak HR (“{s['text']}”)",
                 after={"employee": str(emp.id), "date": s["date"], "kind": s["kind"]})
    return {"success": True, "message": "Saran ditutup: tidak akan muncul lagi untuk hari ini."}


# ── views ──

def _employee(request):
    from apps.employees.models import Employee
    emp = (Employee.objects.select_related("default_shift")
           .filter(organization=request.hr_org, pk=request.data.get("employee")).first()
           if request.data.get("employee") else None)
    if emp is None:
        raise Refused("Karyawan tidak ditemukan.")
    return emp


def _run(fn):
    try:
        return Response(fn())
    except Refused as err:
        code = status.HTTP_409_CONFLICT if str(err) == GONE else status.HTTP_400_BAD_REQUEST
        return Response({"success": False, "message": str(err)}, status=code)


class SuggestionPreviewView(APIView):
    permission_classes = [IsCompanyHR]

    def post(self, request):
        return _run(lambda: preview(request.hr_org, _employee(request), request.data.get("month"),
                                    request.data.get("id"), request.data))


class SuggestionApplyView(APIView):
    permission_classes = [IsCompanyHR]

    def post(self, request):
        return _run(lambda: apply(request.hr_org, _employee(request), request.data.get("month"),
                                  request.data.get("id"), request.data, request.user))


class SuggestionDismissView(APIView):
    permission_classes = [IsCompanyHR]

    def post(self, request):
        return _run(lambda: dismiss(request.hr_org, _employee(request), request.data.get("month"),
                                    request.data.get("id"), request.user))


class SuggestionUndoView(APIView):
    permission_classes = [IsCompanyHR]

    def post(self, request):
        return _run(lambda: undo(request.hr_org, _employee(request), request.data.get("event"), request.user))
