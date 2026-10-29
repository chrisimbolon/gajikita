# =============================================================================
# === backend/apps/attendance/review.py ===
# =============================================================================
"""
Glue between the database and the pure rules in day_status.py (G3):
evaluate(day) / evaluate_missing(employee, date) and the JSON rows HR sees.
"""
from django.utils import timezone

from .day_status import STATUS_LABELS, ShiftInfo, Tap, evaluate_day


def shift_info(shift):
    if shift is None:
        return None
    return ShiftInfo(start=shift.start_time, end=shift.end_time, grace_minutes=shift.grace_minutes,
                     working_days=shift.working_days)


def taps_of(day):
    return [Tap(kind=e.kind, at=e.occurred_at, site=e.site.name if e.site else "", flags=tuple(e.flags or ()))
            for e in day.events.all()]


def evaluate(day, now=None, shift=None):
    shift = shift or day.shift or day.employee.default_shift
    return evaluate_day(
        day.date, shift_info(shift), taps_of(day), now or timezone.now(), timezone.get_current_timezone(),
        hr_in=day.hr_in, hr_out=day.hr_out, decision=day.decision, waive_late=day.waive_late,
        overtime_approved=day.overtime_approved_minutes,
    )


def evaluate_missing(employee, date, now=None):
    """A day with no taps at all (absent, not yet, or a day off)."""
    return evaluate_day(date, shift_info(employee.default_shift), [], now or timezone.now(),
                        timezone.get_current_timezone())


def _t(dt):
    return timezone.localtime(dt).strftime("%H:%M") if dt else None


def row(employee, date, day, result):
    return {
        "employee": {"id": str(employee.id), "employee_no": employee.employee_no, "full_name": employee.full_name},
        "date": date.isoformat(),
        "day_id": str(day.id) if day else None,
        "status": result.status,
        "status_label": STATUS_LABELS.get(result.status, result.status),
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
        "needs_review": result.needs_review,
        "decision": day.decision if day else "",
        "is_locked": day.is_locked if day else False,
        "hr_fixed": bool(day and (day.hr_in or day.hr_out)),
    }

