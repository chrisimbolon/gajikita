# =============================================================================
# === backend/apps/payroll/meals.py ===
# =============================================================================
"""
G12d (6 Nov 2026) — who gets uang makan on a day. Pure, so the rules are easy to test.

Each employee can have their own rule (Karyawan → Uang makan); empty = the company's rule
(Payroll → Pengaturan). DKCB, for example: a pump helper gets it every present day, drivers
only on days they come home at 19:00 or later, office staff never.
"""
from datetime import datetime, time, timedelta

NONE, OVERTIME_DAY, PRESENT_DAY, LATE_OUT = "none", "overtime_day", "present_day", "late_out"


def rule_for(employee_rule, company_rule):
    """The employee's own rule wins; empty means 'follow the company'."""
    return employee_rule or company_rule or NONE


def earns_meal(rule, day, first_in, last_out, rejected, overtime_minutes, late_after, tz, needs_overtime=False):
    """
    rule              one of NONE / OVERTIME_DAY / PRESENT_DAY / LATE_OUT
    day               the working date
    first_in/last_out aware datetimes of the day (None when missing)
    rejected          HR rejected the day
    overtime_minutes  overtime HR APPROVED that day
    late_after        a time, e.g. 19:00: 'pulang malam' means the clock-out is AT or after it, to the minute
                      (G12h.1, 26 Nov 2026: Anthony confirmed Prayuda's October, 20x, where pulang exactly 19:00
                      counts; 18:59 and 18:59:50 do not, 19:00 and 19:00:45 do. G12h had read DKCB's 'OT melebihi
                      pukul 19.00' as strictly after. A clock-out after midnight counts too: same working day)

    G20-2.1 (24 Nov 2026): for 'pulang malam' the CLOCK-OUT is the evidence, so a day with only a late clock-out
    (the clock-in tap missing, G17-1) earns it too: Syaiful 26 Sep, out 21:50, and Amsar 14 Okt, out 23:26, were
    paid in DKCB's book and not in SeeGaji. The missing clock-in is still the ½-day rule, as before. A per-present-
    day meal keeps needing the clock-in (unchanged).

    G23-1 (28 Nov 2026, Anthony at the 27 Nov visit, A3: "lembur harus disetujui"): with needs_overtime, 'pulang
    malam' also needs overtime APPROVED that day (HR's decision or an SPL). The clock-out alone is not enough.
    The caller passes it only for people paid overtime: a TM driver (no lembur, paid per kubikasi) still earns the
    meal from the clock-out (A5: Edi 14 Okt, 2x).
    """
    if rule == OVERTIME_DAY:
        return bool(overtime_minutes)
    if rejected:
        return False
    if rule == PRESENT_DAY:
        return first_in is not None
    if rule == LATE_OUT:
        if needs_overtime and not overtime_minutes:
            return False
        return last_out is not None and _minute(last_out, tz) >= datetime.combine(day, late_after, tzinfo=tz)
    return False


def _minute(when, tz):
    """A clock time to the minute: seconds never decide a rupiah (19:00:45 is still 19:00)."""
    return when.astimezone(tz).replace(second=0, microsecond=0)


def meal_count(rule, day, first_in, last_out, rejected, overtime_minutes, late_after, tz, midnight_extra=False,
               needs_overtime=False):
    """
    G12e: how many meals that day (0, 1 or 2). With midnight_extra, a clock-out at 00:00 or later earns a second
    meal (G12h.1: exactly 00:00 counts, Prayuda 3 Okt in Anthony's book; it was 00:01 or later). Only for the evening rules
    (per overtime day / per day home late): a per-present-day meal is one meal a day.
    """
    if not earns_meal(rule, day, first_in, last_out, rejected, overtime_minutes, late_after, tz, needs_overtime):
        return 0
    if midnight_extra and rule in (OVERTIME_DAY, LATE_OUT) and last_out is not None:
        midnight = datetime.combine(day + timedelta(days=1), time(0), tzinfo=tz)
        if _minute(last_out, tz) >= midnight:
            return 2
    return 1


def waits_for_overtime(rule, day, first_in, last_out, rejected, overtime_minutes, late_after, tz, needs_overtime):
    """G23-1: True when the clock-out earns 'pulang malam' but the day's overtime is not approved (so no meal yet)."""
    return bool(needs_overtime and rule == LATE_OUT and not overtime_minutes
                and earns_meal(rule, day, first_in, last_out, rejected, 0, late_after, tz, needs_overtime=False))


def earns_breakfast(day, first_in, rejected, before, tz):
    """G12e: came in before `before` (DKCB: 07:00)."""
    return not rejected and first_in is not None and first_in < datetime.combine(day, before, tzinfo=tz)
