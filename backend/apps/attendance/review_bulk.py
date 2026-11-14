# =============================================================================
# === backend/apps/attendance/review_bulk.py ===
# =============================================================================
"""
Tinjau massal per periode (G11, 4 Nov 2026).

With 500 workers a month holds thousands of days to review (overtime, late, no clock-out).
One by one, and only for the last 31 days, that is impossible. Here HR reviews a whole pay
period (26 - 25), filtered by kind, and decides many days at once.

  GET  /api/hr/attendance/review/period/?month=YYYY-MM&kind=overtime&q=&page=1
        the days still waiting for HR in that pay period, 100 per page, with a count per kind
  POST /api/hr/attendance/review/bulk/
        {"action": "approve" | "reject", "note": "...",
         "ids": [day ids]                                   <- the ticked rows, or
         "month": "2026-10", "kind": "overtime", "q": ""    <- everything matching the filter,
         "overtime_max_minutes": null, "waive_late": false}
        approve: like "Setujui" on one day; overtime approved = what the taps propose.
                 G12g (8 Nov 2026): no cap unless HR asks for one. "overtime_max_minutes" left out =
                 the company setting (Pengaturan payroll, empty = no cap); null = no cap; a number =
                 that cap on working days. Every day the cap cuts is listed in the answer ("trimmed"),
                 and days over PP 35's 4 hours are counted ("over_legal_days") as a warning.
        reject:  like "Tolak" (a note is required)
        away:    G17-3 "Tandai tugas luar": each day becomes a one-day "tidak wajib absen" period with the note as
                 the errand ("Tugas luar: Belanja alat"): counted as worked, no late / ½ day / automatic overtime
                 or meals. A note is required; days already covered by such a period are skipped. Undo it on the
                 employee's page (Tidak wajib absen).
        Locked days (in a locked payroll) and days already decided are skipped.
        Every day gets its own audit line, so the day panel still shows who decided and when.

G12f.3.1: rows carry "hr_note"; has_note=1 / 0 keeps only the days with / without HR's note (GET and the
bulk filter alike, so "everything matching the filter" is exactly what the screen lists).
"""
from django.db import transaction
from django.db.models import Q
from django.utils import timezone
from rest_framework import serializers, status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.models import AuditEntry
from apps.organizations.permissions import IsCompanyHR
from apps.core.audit import record_audit
from apps.payroll.models import PayrollSettings
from apps.payroll.overtime import WEEKDAY_MAX_MINUTES
from apps.payroll.payrun import MONTHS

from .hr_views import _days_qs, _snapshot
from .rekap import _shift_month, period_of
from .review import evaluate, leaves_between, night_context, row
from .day_status import Status
from .day_notes_import import notes_for
from .models import AttendanceDay
from .review_kinds import KINDS, LABELS, capped_overtime, kinds_of, over_legal

PAGE_SIZE = 100
MAX_BULK = 10000


def pending_days(org, start, end, now, kind="", q=""):
    """[(day, result, kinds)] waiting for HR in [start, end], oldest first, optionally one kind / a search."""
    leaves = leaves_between(org.id, start, end)
    ctx = night_context(org.id, None, start, end)                                   # G12e
    qs = _days_qs(org).filter(date__gte=start, date__lte=end, decision="", is_locked=False)
    q = (q or "").strip().lower()
    out = []
    for d in qs.order_by("date", "employee__full_name"):
        if q and q not in d.employee.full_name.lower() and q not in d.employee.employee_no.lower():
            continue
        r = evaluate(d, now, leave=leaves.get((d.employee_id, d.date), ""), ctx=ctx)
        if not r.needs_review:
            continue
        kinds = kinds_of(r.review_reasons)
        if kind and kind not in kinds:
            continue
        out.append((d, r, kinds))
    return out


def with_note_filter(org, items, start, end, has_note, notes=None):
    """G12f.3.1: (items, notes). has_note "1" keeps the days with HR's note, "0" those without, "" all."""
    notes = notes_for(org, None, start, end) if notes is None else notes
    if has_note in ("1", "0"):
        want = has_note == "1"
        items = [x for x in items if ((x[0].employee_id, x[0].date) in notes) == want]
    return items, notes


def _period(org, month):
    y, m, start, end = period_of(org, month)
    py, pm = _shift_month(y, m, -1)
    ny, nm = _shift_month(y, m, 1)
    return {"month": f"{y}-{m:02d}", "label": f"{MONTHS[m - 1]} {y}", "start": start.isoformat(),
            "end": end.isoformat(), "prev": f"{py}-{pm:02d}", "next": f"{ny}-{nm:02d}"}, start, end


class ReviewPeriodView(APIView):
    permission_classes = [IsCompanyHR]

    def get(self, request):
        p = request.query_params
        info, start, end = _period(request.hr_org, p.get("month"))
        everything = pending_days(request.hr_org, start, end, timezone.now(), q=p.get("q", ""))
        has_note = p.get("has_note", "")                                            # G12f.3.1
        _, notes = with_note_filter(request.hr_org, [], start, end, "")
        noted = sum(1 for d, _, _ in everything if (d.employee_id, d.date) in notes)
        everything, _ = with_note_filter(request.hr_org, everything, start, end, has_note, notes)
        counts = {k: 0 for k, _ in KINDS}
        for _, _, kinds in everything:
            for k in kinds:
                counts[k] += 1
        kind = p.get("kind", "")
        chosen = [x for x in everything if not kind or kind in x[2]]
        try:
            page = max(1, int(p.get("page", 1)))
        except ValueError:
            page = 1
        pages = max(1, (len(chosen) + PAGE_SIZE - 1) // PAGE_SIZE)
        page = min(page, pages)
        rows = []
        for d, r, kinds in chosen[(page - 1) * PAGE_SIZE: page * PAGE_SIZE]:
            item = row(d.employee, d.date, d, r)
            item["kinds"] = kinds
            item["over_legal"] = _over_legal(r)                                     # G12g
            item["hr_note"] = notes.get((d.employee_id, d.date))                    # G12f.3.1
            rows.append(item)
        over = sum(1 for _, r, _ in chosen if _over_legal(r))                       # all pages
        return Response({"success": True, **info, "kind": kind, "all": len(everything), "total": len(chosen),
                         "page": page, "pages": pages,
                         "kinds": [{"key": k, "label": l, "count": counts[k]} for k, l in KINDS if counts[k]],
                         "over_legal": over, "legal_day_minutes": WEEKDAY_MAX_MINUTES,      # G12g
                         "cap_minutes": PayrollSettings.for_org(request.hr_org).overtime_daily_cap_minutes,
                         "has_note": has_note if has_note in ("1", "0") else "", "with_note": noted,   # G12f.3.1
                         "rows": rows})


def _over_legal(r):
    return over_legal(r.overtime_proposed_minutes, Status.DAY_OFF_WORK in r.tags)


class BulkSerializer(serializers.Serializer):
    action = serializers.ChoiceField(choices=["approve", "reject", "away"])                 # G17-3: away
    note = serializers.CharField(required=False, allow_blank=True, default="", max_length=500)
    ids = serializers.ListField(child=serializers.UUIDField(), required=False, allow_empty=True)
    month = serializers.CharField(required=False, allow_blank=True, default="")
    kind = serializers.ChoiceField(choices=[""] + [k for k, _ in KINDS], required=False, default="")
    q = serializers.CharField(required=False, allow_blank=True, default="")
    # G12g: left out = the company setting (empty there = no cap); null = no cap. There is no 240 default any more.
    overtime_max_minutes = serializers.IntegerField(required=False, allow_null=True, min_value=0, max_value=24 * 60)
    waive_late = serializers.BooleanField(required=False, default=False)
    has_note = serializers.ChoiceField(choices=["", "1", "0"], required=False, default="")      # G12f.3.1

    def validate(self, attrs):
        if attrs["action"] == "reject" and not attrs["note"].strip():
            raise serializers.ValidationError({"note": "Tulis alasan penolakan."})
        if attrs["action"] == "away" and not attrs["note"].strip():
            raise serializers.ValidationError({"note": "Tulis tugasnya, mis. \"Belanja alat lori fuso\"."})
        if not attrs.get("ids") and not attrs["month"]:
            raise serializers.ValidationError({"ids": "Pilih hari yang akan diputuskan."})
        return attrs


class BulkDecideView(APIView):
    permission_classes = [IsCompanyHR]

    def post(self, request):
        ser = BulkSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        d = ser.validated_data
        org, now = request.hr_org, timezone.now()
        if d.get("ids"):
            days = list(_days_qs(org).filter(id__in=d["ids"]))
            dates = [x.date for x in days] or [now.date()]
            leaves = leaves_between(org.id, min(dates), max(dates))
            ctx = night_context(org.id, None, min(dates), max(dates))               # G12e
            todo = []
            for day in days:
                if day.is_locked or day.decision:
                    continue
                r = evaluate(day, now, leave=leaves.get((day.employee_id, day.date), ""), ctx=ctx)
                todo.append((day, r))
            skipped = len(d["ids"]) - len(todo)
        else:
            _, start, end = _period(org, d["month"])
            found, _ = with_note_filter(org, pending_days(org, start, end, now, d["kind"], d["q"]), start, end,
                                        d["has_note"])                              # G12f.3.1
            todo = [(day, r) for day, r, _ in found]
            skipped = 0
        if len(todo) > MAX_BULK:
            return Response({"success": False, "message": f"Maksimal {MAX_BULK} hari sekali proses. Saring dulu per jenis."},
                            status=status.HTTP_400_BAD_REQUEST)

        if d["action"] == "away":                                                       # G17-3
            return _mark_away(request, org, todo, skipped, d["note"].strip())

        cap = (d["overtime_max_minutes"] if "overtime_max_minutes" in d                  # G12g
               else PayrollSettings.for_org(org).overtime_daily_cap_minutes)
        note = d["note"].strip()
        audits, trimmed, over = [], [], 0
        with transaction.atomic():
            for day, r in todo:
                before = _snapshot(day)
                day.decision = "approved" if d["action"] == "approve" else "rejected"
                day.decision_note = note
                day.decided_by, day.decided_at = request.user, now
                if d["action"] == "approve":
                    day.waive_late = d["waive_late"]
                    # G11b: the cap is for normal working days; on a rest day every hour worked is overtime
                    rest_day = Status.DAY_OFF_WORK in r.tags
                    proposed = r.overtime_proposed_minutes or 0
                    day.overtime_approved_minutes = capped_overtime(proposed, None if rest_day else cap)
                    approved = day.overtime_approved_minutes or 0
                    if approved < proposed:                       # G12g: a cut is always reported, never silent
                        trimmed.append({"name": day.employee.full_name, "date": day.date.isoformat(),
                                        "proposed": proposed, "approved": approved})
                    if over_legal(approved, rest_day):
                        over += 1
                    summary = "Disetujui massal" + (" (terlambat dimaafkan)" if day.waive_late else "") + (
                        f", lembur {approved} menit" if approved else "") + (
                        f" (usulan {proposed}, dibatasi {cap} menit/hari)" if approved < proposed else "")
                else:
                    day.waive_late, day.overtime_approved_minutes = False, None
                    summary = (f"Ditolak massal: kembali ke {r.leave.lower()}" if r.leave
                               else "Ditolak massal: dihitung tidak hadir")
                day.save(update_fields=["decision", "decision_note", "decided_by", "decided_at", "waive_late",
                                        "overtime_approved_minutes"])
                audits.append(AuditEntry(
                    organization=org, actor=request.user, action=f"attendance.{d['action']}",
                    target_type=day._meta.label_lower, target_id=str(day.pk),
                    summary=f"{day.employee.full_name} {day.date:%d-%m-%Y}: {summary}"[:255],
                    data={"before": before, "after": _snapshot(day), "note": note, "bulk": True,
                          "proposed": r.overtime_proposed_minutes, "cap": cap}))
            AuditEntry.objects.bulk_create(audits, batch_size=500)
        overtime = sum(day.overtime_approved_minutes or 0 for day, _ in todo) if d["action"] == "approve" else 0
        return Response({"success": True, "decided": len(todo), "skipped": skipped, "overtime_minutes": overtime,
                         "cap_minutes": cap, "trimmed_count": len(trimmed), "trimmed": trimmed[:50],
                         "over_legal_days": over})


def _mark_away(request, org, todo, skipped, note):
    """G17-3: one-day "tidak wajib absen" periods for the chosen days (Feny's shopping trips for parts)."""
    from .models import AttendanceExemption
    reason = f"Tugas luar: {note}"[:200]
    done, audits = 0, []
    with transaction.atomic():
        for day, _ in todo:
            emp = day.employee
            covered = AttendanceExemption.objects.filter(employee=emp, start__lte=day.date).filter(
                Q(end__isnull=True) | Q(end__gte=day.date)).exists()
            if covered:
                skipped += 1
                continue
            x = AttendanceExemption.objects.create(organization=org, employee=emp, start=day.date, end=day.date,
                                                   reason=reason, created_by=request.user)
            audits.append(AuditEntry(
                organization=org, actor=request.user, action="attendance.exemption_create",
                target_type=emp._meta.label_lower, target_id=str(emp.pk),
                summary=f"{emp.full_name}: tugas luar {day.date:%d-%m-%Y} ({note})"[:255],
                data={"bulk": True, "day": str(day.pk), "exemption": str(x.pk), "reason": reason}))
            done += 1
        AuditEntry.objects.bulk_create(audits, batch_size=500)
    return Response({"success": True, "decided": done, "skipped": skipped, "overtime_minutes": 0, "cap_minutes": None,
                     "trimmed_count": 0, "trimmed": [], "over_legal_days": 0})


# ── G12g: repairing days the old 240-minute default cut ─────────────────────────────────────────
DECISION_ACTIONS = ("attendance.approve", "attendance.reject", "attendance.reset", "attendance.overtime_uncap")


def capped_bulk_days(org, start, end, now, employee_no=""):
    """
    Working days whose overtime a bulk approval cut: still approved, approved minutes below what the
    taps propose, and the LAST decision on the day was a bulk approval. A day HR decided by hand
    (Setujui with typed minutes, Batalkan keputusan, Tolak) is never returned. [(day, proposed)], oldest first.
    """
    leaves = leaves_between(org.id, start, end)
    ctx = night_context(org.id, None, start, end)
    qs = _days_qs(org).filter(date__gte=start, date__lte=end, decision="approved")
    if employee_no:
        qs = qs.filter(employee__employee_no=employee_no)
    candidates = []
    for day in qs.order_by("date", "employee__full_name"):
        r = evaluate(day, now, leave=leaves.get((day.employee_id, day.date), ""), ctx=ctx)
        proposed = r.overtime_proposed_minutes or 0
        if Status.DAY_OFF_WORK not in r.tags and proposed > (day.overtime_approved_minutes or 0):
            candidates.append((day, proposed))
    if not candidates:
        return []
    last = {}
    for a in (AuditEntry.objects.filter(organization=org, target_type=AttendanceDay._meta.label_lower,
                                        target_id__in=[str(d.pk) for d, _ in candidates],
                                        action__in=DECISION_ACTIONS).order_by("created_at")):
        last[a.target_id] = a                                                   # the newest wins
    out = []
    for day, proposed in candidates:
        a = last.get(str(day.pk))
        if a is not None and a.action == "attendance.approve" and (a.data or {}).get("bulk"):
            out.append((day, proposed))
    return out


def uncap(org, rows):
    """Give each day its full proposed overtime, one audit line each (actor "Sistem"). Locked days stay."""
    done, locked = [], []
    with transaction.atomic():
        for day, proposed in rows:
            if day.is_locked:
                locked.append(day)
                continue
            before, old = _snapshot(day), day.overtime_approved_minutes or 0
            day.overtime_approved_minutes = proposed
            day.save(update_fields=["overtime_approved_minutes"])
            record_audit(organization=org, actor=None, action="attendance.overtime_uncap", target=day,
                         summary=f"{day.employee.full_name} {day.date:%d-%m-%Y}: lembur {old} -> {proposed} menit "
                                 "(batas setujui massal dihapus)",
                         before=before, after=_snapshot(day), note="G12g: lembur dikembalikan sesuai jam absen")
            done.append(day)
    return done, locked
