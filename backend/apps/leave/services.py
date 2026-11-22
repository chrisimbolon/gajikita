# =============================================================================
# === backend/apps/leave/services.py ===
# =============================================================================
"""
Making and deciding leave (G7). Used by the phone views, HR's views and tests,
so the rules live in one place. Every change writes an audit entry.
"""
import os
from datetime import date as Date, timedelta

from django.db import transaction
from django.db.models import Sum
from django.utils import timezone

from apps.attendance.models import AttendanceDay, CompanyEvent
from apps.core.audit import record_audit
from apps.employees.models import Employee

from . import rules
from .models import LeaveRequest, LeaveSettings

ACTIVE = (LeaveRequest.Status.PENDING, LeaveRequest.Status.APPROVED)
ATTACHMENT_TYPES = {".jpg", ".jpeg", ".png", ".webp", ".pdf"}
ATTACHMENT_MAX_BYTES = 5 * 1024 * 1024
LOCKED = "Ada tanggal yang sudah masuk pay run (terkunci), jadi cuti ini tidak bisa diubah."


class LeaveError(Exception):
    def __init__(self, errors):
        self.errors = errors if isinstance(errors, dict) else {"message": str(errors)}
        super().__init__(next(iter(self.errors.values())))

    @property
    def message(self):
        return next(iter(self.errors.values()))


def working_days_of(employee):
    shift = employee.default_shift
    return shift.working_days if shift else None


def _holiday_events(employee, start, end, collective_only=False):
    qs = CompanyEvent.objects.filter(organization_id=employee.organization_id, kind=CompanyEvent.Kind.HOLIDAY,
                                     start__lte=end, end__gte=start)
    if collective_only:
        qs = qs.filter(collective_leave=True)
    return [e.as_rule() for e in qs.prefetch_related("sites", "employees")]


def holiday_dates(employee, start, end):
    """G14-1: the dates in start..end that a "Libur" Kejadian gives this employee off (cuti bersama included)."""
    events = _holiday_events(employee, start, end)
    out, d = set(), start
    while events and d <= end:
        if any(e.applies(employee.pk, employee.default_site_id, d) for e in events):
            out.add(d)
        d += timedelta(days=1)
    return out


def count_days(employee, start, end, kind=None):
    """The worker's shift working days, minus Libur days (G14-1: a Libur / cuti bersama day is not a leave day).
    G14-2: cuti melahirkan, istirahat keguguran and istirahat panjang are counted in calendar days."""
    if kind in rules.CALENDAR_KINDS:
        return rules.calendar_days(start, end)
    off = holiday_dates(employee, start, end) if end >= start else set()
    return len([d for d in rules.working_dates(start, end, working_days_of(employee)) if d not in off])


def collective_dates(employee, year, cfg=None):
    """
    G14-1: cuti bersama days that come out of annual leave. None unless the company chose so in Pengaturan cuti
    (UU 27/2026 Pasal 118 ayat 6: by law they don't). Only the employee's working days, from the day they are
    entitled to annual leave.
    """
    cfg = cfg or LeaveSettings.for_org(employee.organization)
    if not cfg.collective_leave_reduces_annual:
        return []
    first, last = Date(year, 1, 1), Date(year, 12, 31)
    entitled_from = rules.one_year_after(employee.join_date)
    working = working_days_of(employee)
    out = set()
    for e in _holiday_events(employee, first, last, collective_only=True):
        for d in rules.working_dates(max(e.start, first), min(e.end, last), working):
            if d >= entitled_from and e.applies(employee.pk, employee.default_site_id, d):
                out.add(d)
    return sorted(out)


def annual_used(employee, year, exclude=None):
    qs = LeaveRequest.objects.filter(employee=employee, kind=rules.ANNUAL, status__in=ACTIVE, start_date__year=year)
    if exclude is not None:
        qs = qs.exclude(pk=exclude.pk)
    return (qs.aggregate(n=Sum("days"))["n"] or 0) + len(collective_dates(employee, year))     # G14-1


def took_long_rest(employee, year):
    """G14-2: an istirahat panjang (waiting or approved) starts in that year."""
    return LeaveRequest.objects.filter(employee=employee, kind=rules.LONG_REST, status__in=ACTIVE,
                                       start_date__year=year).exists()


def annual_entitled(employee, on_date):
    """12 days after 12 months; none in a year with istirahat panjang (G14-2, Pasal 118 ayat 4)."""
    if took_long_rest(employee, on_date.year):
        return 0
    return rules.annual_entitlement(employee.join_date, on_date)


def long_rest_balance(employee, on_date, cfg=None):
    """G14-2: the istirahat panjang earned at the latest 5-year mark, taken and left (calendar days). It stays
    until the next 5-year mark."""
    cfg = cfg or LeaveSettings.for_org(employee.organization)
    since = rules.long_rest_since(employee.join_date, on_date)
    nxt = rules.next_long_rest(employee.join_date, on_date) if employee.join_date else None
    taken = 0
    if since:
        taken = (LeaveRequest.objects.filter(employee=employee, kind=rules.LONG_REST, status__in=ACTIVE,
                                             start_date__gte=since, start_date__lt=nxt)
                 .aggregate(n=Sum("days"))["n"] or 0)
    days = rules.LONG_REST_DAYS if since else 0
    return {"on": cfg.long_rest, "from_date": since.isoformat() if since else None,
            "next_date": nxt.isoformat() if nxt else None, "days": days, "taken": taken,
            "left": max(0, days - taken)}


def long_sick_note(employee, period_start, period_end):
    """G14-2: the Pasal 149 ayat 3 note when approved sick leave has run unbroken past 4 months (gaps of up to
    4 days, e.g. a weekend between two letters, don't break it). "" otherwise."""
    rows = list(LeaveRequest.objects.filter(employee=employee, kind=rules.SICK, status=LeaveRequest.Status.APPROVED,
                                            start_date__lte=period_end)
                .order_by("-start_date").values_list("start_date", "end_date")[:60])
    if not rows or rows[0][1] < period_start:
        return ""
    first = rows[0][0]
    for s, e in rows[1:]:
        if e < first - timedelta(days=5):
            break
        first = min(first, s)
    return rules.long_sick_text(first, min(rows[0][1], period_end))


def annual_balance(employee, on_date):
    """What the phone and HR show: entitled days, used (pending + approved + cuti bersama if the company chose so)
    and what is left this year."""
    entitled = annual_entitled(employee, on_date)                                       # G14-2
    used = annual_used(employee, on_date.year)
    return {
        "long_rest_year": took_long_rest(employee, on_date.year),                          # G14-2
        "long_rest": long_rest_balance(employee, on_date),
        "year": on_date.year, "entitled": entitled, "used": used, "left": max(0, entitled - used),
        "collective": len(collective_dates(employee, on_date.year)),                            # G14-1
        "from_date": rules.one_year_after(employee.join_date).isoformat(),
    }


def recount_leave(organization, start, end):
    """
    G14-1: after a Libur Kejadian is added, changed or removed, recount the days of active leave touching
    start..end. Leave on a locked payroll day stays as it was. -> how many changed.
    """
    changed = 0
    for leave in (LeaveRequest.objects.filter(organization=organization, status__in=ACTIVE,
                                              start_date__lte=end, end_date__gte=start)
                  .select_related("employee", "employee__default_shift")):
        if _locked_days(leave):
            continue
        days = count_days(leave.employee, leave.start_date, leave.end_date, leave.kind)        # G14-2
        if days != leave.days:
            leave.days = days
            leave.save(update_fields=["days", "updated_at"])
            changed += 1
    return changed


def _check_attachment(f):
    if not f:
        return
    if os.path.splitext(f.name)[1].lower() not in ATTACHMENT_TYPES:
        raise LeaveError({"attachment": "Lampiran harus foto (JPG/PNG) atau PDF."})
    if f.size > ATTACHMENT_MAX_BYTES:
        raise LeaveError({"attachment": "Lampiran paling besar 5 MB."})


def _locked_days(leave):
    return AttendanceDay.objects.filter(employee=leave.employee, date__gte=leave.start_date, date__lte=leave.end_date,
                                        is_locked=True).exists()


def _snapshot(leave):
    return {"status": leave.status, "kind": leave.kind, "special_reason": leave.special_reason,
            "start_date": leave.start_date.isoformat(), "end_date": leave.end_date.isoformat(), "days": leave.days,
            "note": leave.decision_note}


def _period(leave):
    if leave.start_date == leave.end_date:
        return f"{leave.start_date:%d-%m-%Y}"
    return f"{leave.start_date:%d-%m-%Y} s/d {leave.end_date:%d-%m-%Y}"


def create_leave(*, employee, kind, start, end, actor, special_reason="", reason="", attachment=None,
                 by_worker=True, approve=False, note=""):
    """
    by_worker  True from the phone (waits for approval, can't go far back);
               False when HR records the paper form.
    approve    HR's paper form: approved straight away.
    """
    _check_attachment(attachment)
    today = timezone.localdate()
    with transaction.atomic():
        # one request at a time per worker, so two quick taps can't both spend the same annual days
        Employee.objects.select_for_update().filter(pk=employee.pk).first()
        days = count_days(employee, start, end, kind) if end >= start else 0                  # G14-2: kind
        annual_left = 0
        if kind == rules.ANNUAL and end >= start:
            annual_left = max(0, annual_entitled(employee, start) - annual_used(employee, start.year))
        cfg = LeaveSettings.for_org(employee.organization)                               # G14-1
        errors = rules.check_request(kind=kind, special_reason=special_reason, start=start, end=end, days=days,
                                     annual_left=annual_left, today=today, by_worker=by_worker,
                                     reasons=rules.special_reasons(cfg.paternity_extra_days, cfg.menstrual_leave))
        if errors:
            raise LeaveError(errors)
        if kind == rules.SPECIAL and special_reason == rules.MENSTRUAL:                    # G14-1
            if employee.gender != "P":
                raise LeaveError({"special_reason": "Cuti haid hanya untuk karyawan perempuan. "
                                                    "Isi Jenis kelamin di data Karyawan."})
            month = (LeaveRequest.objects.filter(employee=employee, kind=rules.SPECIAL, special_reason=rules.MENSTRUAL,
                                                 status__in=ACTIVE, start_date__year=start.year,
                                                 start_date__month=start.month)
                     .aggregate(n=Sum("days"))["n"] or 0)
            most = rules.SPECIAL_REASONS[rules.MENSTRUAL][1]
            if month + days > most:
                raise LeaveError({"end_date": f"Cuti haid paling banyak {most} hari sebulan "
                                              f"(sudah {month} hari di bulan ini)."})
        if kind in rules.WOMEN_ONLY and employee.gender != "P":                            # G14-2
            raise LeaveError({"kind": f"{rules.KIND_LABELS[kind]} hanya untuk karyawan perempuan. "
                                      f"Isi Jenis kelamin di data Karyawan."})
        if kind == rules.LONG_REST:                                                        # G14-2
            if not cfg.long_rest:
                raise LeaveError({"kind": "Istirahat panjang dimatikan di Pengaturan cuti."})
            bal = long_rest_balance(employee, start, cfg)
            if not bal["from_date"]:
                raise LeaveError({"kind": f"Belum berhak istirahat panjang: setelah {rules.LONG_REST_YEARS} tahun "
                                          f"bekerja berturut-turut (mulai {Date.fromisoformat(bal['next_date']):%d-%m-%Y})."})
            if days > bal["left"]:
                raise LeaveError({"end_date": f"Sisa istirahat panjang {bal['left']} hari kalender, "
                                              f"pengajuan ini {days} hari."})
        overlap = (LeaveRequest.objects.filter(employee=employee, status__in=ACTIVE, start_date__lte=end, end_date__gte=start)
                   .order_by("start_date").first())
        if overlap:
            raise LeaveError({"start_date": f"Sudah ada {overlap.label.lower()} {_period(overlap)} "
                                            f"({overlap.get_status_display().lower()})."})
        leave = LeaveRequest(
            organization=employee.organization, employee=employee, kind=kind,
            special_reason=special_reason if kind == rules.SPECIAL else "",
            start_date=start, end_date=end, days=days, reason=(reason or "").strip()[:500],
            source=LeaveRequest.Source.PHONE if by_worker else LeaveRequest.Source.FORM,
            requested_by=actor if getattr(actor, "is_authenticated", False) else None,
        )
        if attachment:
            leave.attachment = attachment
        if approve:
            if _locked_days(leave):
                raise LeaveError({"start_date": LOCKED})
            leave.status = LeaveRequest.Status.APPROVED
            leave.decided_by, leave.decided_at = leave.requested_by, timezone.now()
            leave.decision_note = (note or "").strip()[:255]
        leave.save()
        how = "dicatat HR dari formulir dan disetujui" if approve else "diajukan"
        record_audit(organization=leave.organization, actor=actor, action="leave.create", target=leave,
                     summary=f"{employee.full_name}: {leave.label} {_period(leave)} ({days} hari) {how}",
                     after=_snapshot(leave), note=leave.reason)
    return leave


def decide_leave(leave, *, action, actor, note=""):
    """action: approve | reject | cancel. Reject needs a note. Cancel works on pending and approved leave."""
    note = (note or "").strip()[:255]
    S = LeaveRequest.Status
    with transaction.atomic():
        leave = LeaveRequest.objects.select_for_update().select_related("employee").get(pk=leave.pk)
        before = _snapshot(leave)
        if action in ("approve", "reject"):
            if leave.status != S.PENDING:
                raise LeaveError({"message": f"Pengajuan ini sudah {leave.get_status_display().lower()}."})
            if action == "reject" and not note:
                raise LeaveError({"note": "Tulis alasan penolakan."})
            if action == "approve" and _locked_days(leave):
                raise LeaveError({"message": LOCKED})
            leave.status = S.APPROVED if action == "approve" else S.REJECTED
            word = "disetujui" if action == "approve" else "ditolak"
        elif action == "cancel":
            if leave.status not in ACTIVE:
                raise LeaveError({"message": f"Pengajuan ini sudah {leave.get_status_display().lower()}."})
            if leave.status == S.APPROVED and _locked_days(leave):
                raise LeaveError({"message": LOCKED})
            leave.status = S.CANCELLED
            word = "dibatalkan"
        else:
            raise LeaveError({"action": "Aksi tidak dikenal."})
        leave.decided_by = actor if getattr(actor, "is_authenticated", False) else None
        leave.decided_at = timezone.now()
        leave.decision_note = note
        leave.save()
        record_audit(organization=leave.organization, actor=actor, action=f"leave.{action}", target=leave,
                     summary=f"{leave.employee.full_name}: {leave.label} {_period(leave)} {word}",
                     before=before, after=_snapshot(leave), note=note)
    return leave


def approved_leave_on(organization, day):
    """{employee_id: label} for everyone on approved leave that date (the attendance pages use it)."""
    qs = LeaveRequest.objects.filter(organization=organization, status=LeaveRequest.Status.APPROVED,
                                     start_date__lte=day, end_date__gte=day)
    return {l.employee_id: l.label for l in qs}


def can_approve_on_phone(approver, leave):
    """The site manager: the worker's "Mandor / atasan" on the Karyawan form."""
    return approver is not None and leave.employee.mandor_id == approver.id
