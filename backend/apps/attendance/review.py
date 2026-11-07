# =============================================================================
# === backend/apps/attendance/review.py ===
# =============================================================================
"""
Glue between the database and the pure rules in day_status.py (G3):
evaluate(day) / evaluate_missing(employee, date) and the JSON rows HR sees.
"""
from datetime import timedelta

from django.db.models import Max, Q
from django.utils import timezone

from . import night_rules
from .day_status import OVERTIME_MIN_MINUTES, STATUS_LABELS, ShiftInfo, Tap, evaluate_day


def shift_info(shift):
    if shift is None:
        return None
    return ShiftInfo(start=shift.start_time, end=shift.end_time, grace_minutes=shift.grace_minutes,
                     working_days=shift.working_days)


def taps_of(day):
    return [Tap(kind=e.kind, at=e.occurred_at, site=e.site.name if e.site else "", flags=tuple(e.flags or ()))
            for e in day.events.all()]


def leaves_between(organization_id, start, end):
    """{(employee_id, date): label} for approved leave between two dates (G9b)."""
    from apps.leave.models import LeaveRequest
    out = {}
    qs = LeaveRequest.objects.filter(organization_id=organization_id, status=LeaveRequest.Status.APPROVED,
                                     start_date__lte=end, end_date__gte=start)
    for leave in qs:
        d = max(leave.start_date, start)
        while d <= min(leave.end_date, end):
            out[(leave.employee_id, d)] = leave.label
            d += timedelta(days=1)
    return out


class NightContext:
    """
    G12e: what evaluate() needs from the company and from the day before, loaded once per screen:
    the night-overtime rows, the overtime minimum, and every previous day's last clock-out.
    """
    def __init__(self, rules=(), overtime_min=OVERTIME_MIN_MINUTES, prev=None):
        self.rules, self.overtime_min, self._prev = rules, overtime_min, prev or {}

    def night_for(self, employee_id, date):
        info = self._prev.get((employee_id, date - timedelta(days=1)))
        if not info:
            return None
        prev_out, crosses_midnight = info
        return night_rules.night_start(date, timezone.localtime(prev_out), crosses_midnight, self.rules)


def night_context(organization_id, employee_ids, start, end):
    """For the days start..end. employee_ids=None = everyone in the company. At most two queries."""
    from apps.payroll.models import PayrollSettings
    from .models import AttendanceDay
    cfg = PayrollSettings.objects.filter(organization_id=organization_id).first()
    if cfg is None:
        return NightContext()
    try:
        rules = night_rules.parse_rules(cfg.night_ot_rules)
    except night_rules.RuleError:
        rules = ()          # the settings page never saves bad rows; never break a screen over them
    prev = {}
    if rules:
        qs = (AttendanceDay.objects
              .filter(organization_id=organization_id, date__gte=start - timedelta(days=1),
                      date__lte=end - timedelta(days=1))
              .exclude(decision="rejected"))
        if employee_ids is not None:
            qs = qs.filter(employee_id__in=list(employee_ids))
        rows = qs.annotate(max_out=Max("events__occurred_at", filter=Q(events__kind="out"))).values(
            "employee_id", "date", "hr_out", "max_out", "shift__start_time", "shift__end_time",
            "employee__default_shift__start_time", "employee__default_shift__end_time")
        for v in rows:
            last_out = v["hr_out"] or v["max_out"]
            if last_out is None:
                continue
            if v["shift__start_time"] is not None:
                st, et = v["shift__start_time"], v["shift__end_time"]
            else:
                st, et = v["employee__default_shift__start_time"], v["employee__default_shift__end_time"]
            crosses = st is not None and et is not None and et <= st
            prev[(v["employee_id"], v["date"])] = (last_out, crosses)
    return NightContext(rules, cfg.overtime_min_minutes, prev)


def evaluate(day, now=None, shift=None, leave=None, ctx=None):
    """
    leave: the approved leave that day ("" = none). None = look it up, so no screen forgets it (G9b).
    ctx:   night_context() for a whole screen; None = look it up for this one day (G12e).
    """
    if leave is None:
        leave = leaves_between(day.organization_id, day.date, day.date).get((day.employee_id, day.date), "")
    if ctx is None:
        ctx = night_context(day.organization_id, [day.employee_id], day.date, day.date)
    shift = shift or day.shift or day.employee.default_shift
    return evaluate_day(
        day.date, shift_info(shift), taps_of(day), now or timezone.now(), timezone.get_current_timezone(),
        hr_in=day.hr_in, hr_out=day.hr_out, decision=day.decision, waive_late=day.waive_late,
        overtime_approved=day.overtime_approved_minutes, leave=leave,
        overtime_eligible=day.employee.overtime_eligible,                # G12d
        night=ctx.night_for(day.employee_id, day.date), overtime_min=ctx.overtime_min,   # G12e
    )


def evaluate_missing(employee, date, now=None, leave="", ctx=None):
    """A day with no taps at all (absent, not yet, a day off, or a day off after a late night)."""
    if ctx is None:
        ctx = night_context(employee.organization_id, [employee.id], date, date)
    return evaluate_day(date, shift_info(employee.default_shift), [], now or timezone.now(),
                        timezone.get_current_timezone(), leave=leave,
                        night=ctx.night_for(employee.id, date))


def _t(dt):
    return timezone.localtime(dt).strftime("%H:%M") if dt else None


def row(employee, date, day, result):
    return {
        "employee": {"id": str(employee.id), "employee_no": employee.employee_no, "full_name": employee.full_name},
        "date": date.isoformat(),
        "day_id": str(day.id) if day else None,
        "status": result.status,
        "status_label": result.label,          # "Sakit", "Cuti tahunan"... for approved leave (G7)
        "leave": result.leave,
        "tags": result.tags,
        "first_in": _t(result.first_in),
        "last_out": _t(result.last_out),
        "late_minutes": result.late_minutes,
        "early_minutes": result.early_minutes,
        "worked_minutes": result.worked_minutes,
        "overtime_proposed_minutes": result.overtime_proposed_minutes,
        "overtime_approved_minutes": day.overtime_approved_minutes if day else None,
        "site_minutes": result.site_minutes,
        "review_reasons": result.review_reasons,
        "note": result.note,                    # G12e
        "needs_review": result.needs_review,
        "decision": day.decision if day else "",
        "is_locked": day.is_locked if day else False,
        "hr_fixed": bool(day and (day.hr_in or day.hr_out)),
    }

