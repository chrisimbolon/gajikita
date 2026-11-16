# =============================================================================
# === backend/apps/attendance/review_overtime.py ===
# =============================================================================
"""
G17-6 (15 Nov 2026) — overtime decided in one place, with undo.

Why: on 15 Nov "Hadir, tanpa lembur" for 5 days meant "Setujui" + typing 0 into a box called "Batasi lembur per
hari kerja". The 0 was missed and two wrong rows were ticked: 23 h 28 min of overtime approved that the book
never paid, and undoing it took the Rekap, one cell at a time, "Batalkan keputusan". HR thinks in SPL terms:
this person, this day, X hours, or none.

POST /api/hr/attendance/review/bulk/ gets three more actions (ids, or the same filter as the list):
  pay_overtime   the day counts and its overtime is paid: "overtime": {day_id: minutes} as HR typed it per row;
                 a day not in the map gets what the taps propose (the company limit in Pengaturan still applies
                 on working days; on a rest day every hour worked counts)
  no_overtime    the day counts, no overtime
  reset          back to "Belum diputuskan" (waiting for the SPL): nothing paid, the day is on the list again
pay_overtime / no_overtime also CHANGE days already decided (state "decided" on the list): the late decision
and HR's ½-day decision stay as they were. Rejected days are skipped (Kembalikan ke belum first). Locked days
are never touched. Every change is one audit line carrying the batch id.

  forgive        G17-7: late, early leave and the one-tap ½ day of those days are not fined (waive_late); a day
                 with nothing else open becomes "approved", one with open overtime keeps waiting for it
POST /api/hr/attendance/review/undo/  {"batch": "..."}
  puts every day of that batch back as it was (also bulk Setujui / Tolak / Tugas luar). A day changed again
  since, or locked, is left alone and listed.
"""
import copy
import re
import uuid

from django.db import transaction
from django.utils import timezone
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.models import AuditEntry
from apps.organizations.permissions import IsCompanyHR
from apps.payroll.models import PayrollSettings

from .day_status import Status
from .models import AttendanceDay, AttendanceExemption
from .review_kinds import capped_overtime, over_legal

OVERTIME_ACTIONS = ("pay_overtime", "no_overtime", "reset", "forgive")          # G17-7: forgive
AUDIT_ACTION = {"pay_overtime": "attendance.overtime_pay", "no_overtime": "attendance.overtime_none",
                "reset": "attendance.reset", "forgive": "attendance.forgive"}
BATCH = re.compile(r"^[0-9a-f]{32}$")


def new_batch():
    return uuid.uuid4().hex


def as_pending(day):
    """The day as if HR had not decided yet: what the taps propose, which kinds it has."""
    c = copy.copy(day)
    c.decision, c.waive_late, c.overtime_approved_minutes = "", False, None
    return c


def snapshot(day):
    from .hr_views import _snapshot
    return _snapshot(day)


def decide_overtime(request, org, action, todo, minutes_by_id, waive_late, note):
    """todo = [(day, pending_result)]. -> the answer for the screen."""
    cap = PayrollSettings.for_org(org).overtime_daily_cap_minutes
    batch, now, audits, skipped, total, over, done = new_batch(), timezone.now(), [], [], 0, 0, 0

    def skip(day, message):
        skipped.append({"name": day.employee.full_name, "date": day.date.isoformat(), "message": message})

    with transaction.atomic():
        for day, r in todo:
            if day.is_locked:
                skip(day, "payroll sudah dikunci")
                continue
            before = snapshot(day)
            if action == "forgive":                       # G17-7: late, early leave and the one-tap ½ day
                if day.decision == "rejected":
                    skip(day, "ditolak: kembalikan ke belum dulu")
                    continue
                if day.waive_late:
                    skip(day, "sudah dimaafkan")
                    continue
                day.waive_late = True
                if note:
                    day.decision_note = note[:1000]
                open_ot = (r.overtime_proposed_minutes or 0) and day.overtime_approved_minutes is None
                if not day.decision and not open_ot:      # nothing else to decide: the day is settled
                    day.decision = "approved"
                    day.decided_by, day.decided_at = request.user, now
                summary = "Dimaafkan (terlambat / pulang cepat / tap sekali)" + (f": {note}" if note else "") + \
                          (" · lembur tetap menunggu" if open_ot and not day.decision else "")
            elif action == "reset":
                if not day.decision:
                    skip(day, "belum diputuskan")
                    continue
                day.decision, day.decision_note, day.waive_late = "", "", False
                day.overtime_approved_minutes, day.half_day_leave = None, ""
                day.decided_by = day.decided_at = None
                summary = "Dikembalikan ke belum diputuskan (tunggu SPL)"
            else:
                if day.decision == "rejected":
                    skip(day, "ditolak: kembalikan ke belum dulu")
                    continue
                rest_day = Status.DAY_OFF_WORK in r.tags
                proposed = r.overtime_proposed_minutes or 0
                if action == "no_overtime":
                    minutes = 0
                elif str(day.pk) in minutes_by_id:
                    minutes = minutes_by_id[str(day.pk)]
                else:
                    minutes = capped_overtime(proposed, None if rest_day else cap) or 0
                if minutes and not day.employee.overtime_eligible:                        # G12h
                    skip(day, "tidak berhak upah lembur (Karyawan → Berhak Upah Lembur)")
                    continue
                if not day.decision:                       # a new decision: late as HR chose on the bar
                    day.waive_late = waive_late
                day.decision = "approved"
                if note:
                    day.decision_note = note
                day.overtime_approved_minutes = minutes or None
                day.decided_by, day.decided_at = request.user, now
                total += minutes
                over += 1 if over_legal(minutes, rest_day) else 0
                summary = (f"Lembur dibayar {minutes} menit" + (f" (usulan absen {proposed})" if minutes != proposed else "")
                           if minutes else "Hadir, tanpa lembur")
            day.save(update_fields=["decision", "decision_note", "decided_by", "decided_at", "waive_late",
                                    "overtime_approved_minutes", "half_day_leave", "updated_at"])
            audits.append(AuditEntry(
                organization=org, actor=request.user, action=AUDIT_ACTION[action],
                target_type=day._meta.label_lower, target_id=str(day.pk),
                summary=f"{day.employee.full_name} {day.date:%d-%m-%Y}: {summary}"[:255],
                data={"before": before, "after": snapshot(day), "note": note, "bulk": True, "batch": batch,
                      "proposed": r.overtime_proposed_minutes}))
            done += 1
        AuditEntry.objects.bulk_create(audits, batch_size=500)
    return Response({"success": True, "action": action, "decided": done, "skipped": len(skipped),
                     "skipped_list": skipped[:30], "overtime_minutes": total, "over_legal_days": over,
                     "batch": batch if done else None,
                     "cap_minutes": None, "trimmed_count": 0, "trimmed": []})


def undo_batch(request, org, batch):
    entries = list(AuditEntry.objects.filter(organization=org, data__batch=batch).order_by("created_at"))
    if not entries:
        return Response({"success": False, "message": "Tidak ada yang bisa diurungkan."}, status=status.HTTP_404_NOT_FOUND)
    if AuditEntry.objects.filter(organization=org, action="attendance.undo", data__undo_of=batch).exists():
        return Response({"success": False, "message": "Sudah diurungkan."}, status=status.HTTP_400_BAD_REQUEST)
    day_label = AttendanceDay._meta.label_lower
    undone, skipped, audits = 0, [], []
    with transaction.atomic():
        for e in entries:
            data = e.data or {}
            if e.action == "attendance.exemption_create":                                # G17-3 tugas luar
                x = AttendanceExemption.objects.filter(pk=data.get("exemption"), organization=org).select_related("employee").first()
                if x is None:
                    continue
                locked = AttendanceDay.objects.filter(employee=x.employee, date=x.start, is_locked=True).exists()
                if locked:
                    skipped.append({"name": x.employee.full_name, "date": x.start.isoformat(), "message": "payroll sudah dikunci"})
                    continue
                name, start = x.employee.full_name, x.start
                x.delete()
                audits.append(AuditEntry(organization=org, actor=request.user, action="attendance.undo",
                                         target_type=e.target_type, target_id=e.target_id,
                                         summary=f"{name} {start:%d-%m-%Y}: tugas luar diurungkan"[:255],
                                         data={"undo_of": batch, "exemption": data.get("exemption")}))
                undone += 1
                continue
            if e.target_type != day_label:
                continue
            day = AttendanceDay.objects.select_related("employee").filter(pk=e.target_id, organization=org).first()
            if day is None:
                continue
            if day.is_locked:
                skipped.append({"name": day.employee.full_name, "date": day.date.isoformat(), "message": "payroll sudah dikunci"})
                continue
            if snapshot(day) != data.get("after"):
                skipped.append({"name": day.employee.full_name, "date": day.date.isoformat(),
                                "message": "sudah diubah lagi setelahnya"})
                continue
            b, current = data.get("before") or {}, snapshot(day)
            day.decision = b.get("decision", "")
            day.decision_note = b.get("note", "")
            day.waive_late = bool(b.get("waive_late"))
            day.overtime_approved_minutes = b.get("overtime_approved_minutes")
            day.half_day_leave = b.get("half_day_leave", "") or ""
            if not day.decision:
                day.decided_by = day.decided_at = None
            day.save(update_fields=["decision", "decision_note", "waive_late", "overtime_approved_minutes",
                                    "half_day_leave", "decided_by", "decided_at", "updated_at"])
            audits.append(AuditEntry(organization=org, actor=request.user, action="attendance.undo",
                                     target_type=day_label, target_id=str(day.pk),
                                     summary=f"{day.employee.full_name} {day.date:%d-%m-%Y}: keputusan massal diurungkan"[:255],
                                     data={"undo_of": batch, "before": current, "after": snapshot(day)}))
            undone += 1
        AuditEntry.objects.bulk_create(audits, batch_size=500)
    return Response({"success": True, "undone": undone, "skipped": len(skipped), "skipped_list": skipped[:30]})


class BulkUndoView(APIView):
    permission_classes = [IsCompanyHR]

    def post(self, request):
        batch = str(request.data.get("batch") or "")
        if not BATCH.match(batch):
            return Response({"success": False, "message": "Tidak ada yang bisa diurungkan."}, status=status.HTTP_400_BAD_REQUEST)
        return undo_batch(request, request.hr_org, batch)
