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
         "overtime_max_minutes": 240, "waive_late": false}
        approve: like "Setujui" on one day; overtime approved = what the taps propose, capped
        reject:  like "Tolak" (a note is required)
        Locked days (in a locked payroll) and days already decided are skipped.
        Every day gets its own audit line, so the day panel still shows who decided and when.
"""
from django.db import transaction
from django.utils import timezone
from rest_framework import serializers, status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.models import AuditEntry
from apps.organizations.permissions import IsCompanyHR
from apps.payroll.payrun import MONTHS

from .hr_views import _days_qs, _snapshot
from .rekap import _shift_month, period_of
from .review import evaluate, leaves_between, row
from .review_kinds import KINDS, LABELS, capped_overtime, kinds_of

PAGE_SIZE = 100
MAX_BULK = 10000


def pending_days(org, start, end, now, kind="", q=""):
    """[(day, result, kinds)] waiting for HR in [start, end], oldest first, optionally one kind / a search."""
    leaves = leaves_between(org.id, start, end)
    qs = _days_qs(org).filter(date__gte=start, date__lte=end, decision="", is_locked=False)
    q = (q or "").strip().lower()
    out = []
    for d in qs.order_by("date", "employee__full_name"):
        if q and q not in d.employee.full_name.lower() and q not in d.employee.employee_no.lower():
            continue
        r = evaluate(d, now, leave=leaves.get((d.employee_id, d.date), ""))
        if not r.needs_review:
            continue
        kinds = kinds_of(r.review_reasons)
        if kind and kind not in kinds:
            continue
        out.append((d, r, kinds))
    return out


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
            rows.append(item)
        return Response({"success": True, **info, "kind": kind, "all": len(everything), "total": len(chosen),
                         "page": page, "pages": pages,
                         "kinds": [{"key": k, "label": l, "count": counts[k]} for k, l in KINDS if counts[k]],
                         "rows": rows})


class BulkSerializer(serializers.Serializer):
    action = serializers.ChoiceField(choices=["approve", "reject"])
    note = serializers.CharField(required=False, allow_blank=True, default="", max_length=500)
    ids = serializers.ListField(child=serializers.UUIDField(), required=False, allow_empty=True)
    month = serializers.CharField(required=False, allow_blank=True, default="")
    kind = serializers.ChoiceField(choices=[""] + [k for k, _ in KINDS], required=False, default="")
    q = serializers.CharField(required=False, allow_blank=True, default="")
    overtime_max_minutes = serializers.IntegerField(required=False, allow_null=True, min_value=0, max_value=24 * 60,
                                                    default=240)
    waive_late = serializers.BooleanField(required=False, default=False)

    def validate(self, attrs):
        if attrs["action"] == "reject" and not attrs["note"].strip():
            raise serializers.ValidationError({"note": "Tulis alasan penolakan."})
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
            todo = []
            for day in days:
                if day.is_locked or day.decision:
                    continue
                r = evaluate(day, now, leave=leaves.get((day.employee_id, day.date), ""))
                todo.append((day, r))
            skipped = len(d["ids"]) - len(todo)
        else:
            _, start, end = _period(org, d["month"])
            todo = [(day, r) for day, r, _ in pending_days(org, start, end, now, d["kind"], d["q"])]
            skipped = 0
        if len(todo) > MAX_BULK:
            return Response({"success": False, "message": f"Maksimal {MAX_BULK} hari sekali proses. Saring dulu per jenis."},
                            status=status.HTTP_400_BAD_REQUEST)

        note = d["note"].strip()
        audits = []
        with transaction.atomic():
            for day, r in todo:
                before = _snapshot(day)
                day.decision = "approved" if d["action"] == "approve" else "rejected"
                day.decision_note = note
                day.decided_by, day.decided_at = request.user, now
                if d["action"] == "approve":
                    day.waive_late = d["waive_late"]
                    day.overtime_approved_minutes = capped_overtime(r.overtime_proposed_minutes, d["overtime_max_minutes"])
                    summary = "Disetujui massal" + (" (terlambat dimaafkan)" if day.waive_late else "") + (
                        f", lembur {day.overtime_approved_minutes} menit" if day.overtime_approved_minutes else "")
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
                    data={"before": before, "after": _snapshot(day), "note": note, "bulk": True}))
            AuditEntry.objects.bulk_create(audits, batch_size=500)
        overtime = sum(day.overtime_approved_minutes or 0 for day, _ in todo) if d["action"] == "approve" else 0
        return Response({"success": True, "decided": len(todo), "skipped": skipped, "overtime_minutes": overtime})
