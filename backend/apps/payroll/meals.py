# =============================================================================
# === backend/apps/payroll/meals.py ===
# =============================================================================
"""
G12d (6 Nov 2026) — who gets uang makan on a day. Pure, so the rules are easy to test.

Each employee can have their own rule (Karyawan → Uang makan); empty = the company's rule
(Payroll → Pengaturan). DKCB, for example: a pump helper gets it every present day, drivers
only on days they come home after 19:00, office staff never.
"""
from datetime import datetime

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
    late_after        a time, e.g. 19:00: 'pulang malam' means the clock-out is at or after it
                      (a clock-out after midnight counts too, it belongs to the same working day)
    """
    if rule == OVERTIME_DAY:
        return bool(overtime_minutes)
    if rejected or first_in is None:
        return False
    if rule == PRESENT_DAY:
        return True
    if rule == LATE_OUT:
        return last_out is not None and last_out >= datetime.combine(day, late_after, tzinfo=tz)
    return False
