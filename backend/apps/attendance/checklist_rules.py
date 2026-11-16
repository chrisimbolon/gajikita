# =============================================================================
# === backend/apps/attendance/checklist_rules.py ===
# =============================================================================
"""
G17-7 (16 Nov 2026) — the pure rules behind "Siap gajian?" (Perlu Tinjau as a checklist). No ORM, no clock.

  late_charge(late, early, tolerance)        the minutes a day is fined for (same rule as payroll:
                                             tolerance off the late minutes, early leave in full)
  is_cluster(problems, tracked)              many people missing taps on one date -> maybe a power cut
  group_dates(dates, gap_ok)                 consecutive flagged dates -> ranges (a Sunday in between is fine)
  rupiah_int(x)                              whole rupiah for the screen
"""
from datetime import timedelta
from decimal import ROUND_HALF_UP, Decimal

MIN_PEOPLE = 5          # fewer than 5 people missing taps on one date is just a normal day
MIN_SHARE = Decimal("0.4")
LEFT_AFTER_DAYS = 5     # G17-7.2: 5+ working days in a row with no tap after the last one = maybe left


def late_charge(late, early, tolerance):
    return max(0, int(late or 0) - int(tolerance or 0)) + max(0, int(early or 0))


def is_cluster(problems, tracked):
    """problems: people with a missing tap or no tap that day; tracked: people expected to tap that day."""
    if tracked <= 0 or problems < MIN_PEOPLE:
        return False
    return Decimal(problems) / Decimal(tracked) >= MIN_SHARE


def group_dates(dates, gap_ok=lambda d: False):
    """Sorted ranges [(start, end)] from a set of dates. gap_ok(d) = a date between two flagged dates that may be
    skipped without breaking the range (a day off for everyone)."""
    out = []
    for d in sorted(set(dates)):
        if out:
            start, end = out[-1]
            gap = end + timedelta(days=1)
            while gap < d and gap_ok(gap):
                gap += timedelta(days=1)
            if gap == d:
                out[-1] = (start, d)
                continue
        out.append((d, d))
    return out


def rupiah_int(x):
    return int(Decimal(x).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
