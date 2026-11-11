# =============================================================================
# === backend/apps/attendance/exemptions.py ===
# =============================================================================
"""
"Tidak wajib absen": people who are paid for every scheduled working day without tapping (G12i, 11 Nov 2026).
Pure Python, no Django.

DKCB: Marganda (excavator operator) works at Lobam, where there is no machine ("Kerja di Lobam" every day since
September); Kamarol (sales) is out of the office. Anthony pays both their full base, with no meals or
overtime, and still counts their leave. SeeGaji showed them "Tidak hadir" every day and would have cut their pay.

An exemption is a dated PERIOD (start, end or open), never a yes/no on the employee: switching it off later must
not turn last month's paid days into absences, and a person can be off-site more than once.

  covering(periods, day)            the reason the day is exempt, or ""
  overlapping(periods, start, end)  the first other period that shares a day with start..end, or None
  changed_ranges(old, new)          the dates whose exemption an edit changes (old/new = (start, end) or None)
  locked_hit(ranges, locked)        the first locked pay period those dates touch, or None
A period is (start, end, reason[, id]) with end None = until further notice.
"""
from datetime import date as Date

FAR = Date.max


def _end(end):
    return FAR if end is None else end


def covering(periods, day):
    for p in periods:
        if p[0] <= day <= _end(p[1]):
            return p[2]
    return ""


def overlapping(periods, start, end, skip=None):
    """periods: [(start, end, reason, id)]. skip: the id being edited."""
    for p in periods:
        if skip is not None and len(p) > 3 and p[3] == skip:
            continue
        if p[0] <= _end(end) and start <= _end(p[1]):
            return p
    return None


def _subtract(a, b):
    """Interval a minus interval b, as a list of intervals. Intervals are (start, end) with FAR = open."""
    (s1, e1), (s2, e2) = a, b
    if e2 < s1 or s2 > e1:
        return [a]
    out = []
    if s2 > s1:
        out.append((s1, Date.fromordinal(s2.toordinal() - 1)))
    if e2 < e1:
        out.append((Date.fromordinal(e2.toordinal() + 1), e1))
    return out


def changed_ranges(old, new):
    """Dates covered by exactly one of old and new (each (start, end) with end None = open, or None)."""
    a = (old[0], _end(old[1])) if old else None
    b = (new[0], _end(new[1])) if new else None
    if a is None and b is None:
        return []
    if a is None:
        return [b]
    if b is None:
        return [a]
    return _subtract(a, b) + _subtract(b, a)


def locked_hit(ranges, locked):
    """locked: [(period_start, period_end, name)] of locked pay runs. -> the first one touched, or None."""
    for start, end in ranges:
        for ls, le, name in locked:
            if ls <= end and start <= le:
                return (ls, le, name)
    return None
