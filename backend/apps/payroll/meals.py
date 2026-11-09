# =============================================================================
# === backend/apps/payroll/meals.py ===
# =============================================================================
"""
G12d (6 Nov 2026) — who gets uang makan on a day. Pure, so the rules are easy to test.

Each employee can have their own rule (Karyawan → Uang makan); empty = the company's rule
(Payroll → Pengaturan). DKCB, for example: a pump helper gets it every present day, drivers
only on days they come home after 19:00, office staff never.
"""
from datetime import datetime, time, timedelta

NONE, OVERTIME_DAY, PRESENT_DAY, LATE_OUT = "none", "overtime_day", "present_day", "late_out"


def rule_for(employee_rule, company_rule):
    """The employee's own rule wins; empty means 'follow the company'."""
    return employee_rule or company_rule or NONE


def earns_meal(rule, day, first_in, last_out, rejected, overtime_minutes, late_after, tz):
    """
    rule              one of NONE / OVERTIME_DAY / PRESENT_DAY / LATE_OUT
    day               the working date
    first_in/last_out aware datetimes of the day (None when missing)
    rejected          HR rejected the day
    overtime_minutes  overtime HR APPROVED that day
    late_after        a time, e.g. 19:00: 'pulang malam' means the clock-out is AFTER it, to the minute
                      (G12h, DKCB 'OT melebihi pukul 19.00': 19:00 and 19:00:45 are not, 19:01 is;
                      a clock-out after midnight counts too, it belongs to the same working day)
    """
    if rule == OVERTIME_DAY:
        return bool(overtime_minutes)
    if rejected or first_in is None:
        return False
    if rule == PRESENT_DAY:
        return True
    if rule == LATE_OUT:
        return last_out is not None and _minute(last_out, tz) > datetime.combine(day, late_after, tzinfo=tz)
    return False


def _minute(when, tz):
    """A clock time to the minute: seconds never decide a rupiah (19:00:45 is still 19:00)."""
    return when.astimezone(tz).replace(second=0, microsecond=0)


def meal_count(rule, day, first_in, last_out, rejected, overtime_minutes, late_after, tz, midnight_extra=False):
    """
    G12e: how many meals that day (0, 1 or 2). With midnight_extra, overtime that runs PAST 00:00
    (00:01 or later; exactly 00:00 is not past it) earns a second meal. Only for the evening rules
    (per overtime day / per day home late): a per-present-day meal is one meal a day.
    """
    if not earns_meal(rule, day, first_in, last_out, rejected, overtime_minutes, late_after, tz):
        return 0
    if midnight_extra and rule in (OVERTIME_DAY, LATE_OUT) and last_out is not None:
        midnight = datetime.combine(day + timedelta(days=1), time(0), tzinfo=tz)
        if _minute(last_out, tz) > midnight:
            return 2
    return 1


def earns_breakfast(day, first_in, rejected, before, tz):
    """G12e: came in before `before` (DKCB: 07:00)."""
    return not rejected and first_in is not None and first_in < datetime.combine(day, before, tzinfo=tz)
