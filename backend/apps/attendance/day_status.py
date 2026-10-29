# =============================================================================
# === backend/apps/attendance/day_status.py ===
# =============================================================================
"""
What happened on one employee's working day (G3, 28 Oct 2026).

Pure Python, no Django imports: the day's taps + the shift + "now" go in,
the status and the minutes come out. Nothing is stored, so the answer can
never go stale; HR's screens use this today and payroll uses it next.

Defaults (each becomes a company setting once a customer tells us their rules):
  * Late counts from the shift start, once the clock-in is past the grace minutes
    (08:12 with 10 minutes grace = late 12 minutes; 08:09 = on time).
  * Overtime is only PROPOSED, and only from OVERTIME_MIN_MINUTES past the shift end.
    It is never paid until HR approves it.
  * "No clock-out" is decided NO_CLOCK_OUT_AFTER_HOURS after the shift should have
    ended; before that the worker is "still working".
"""
from dataclasses import dataclass, field
from datetime import date as Date, datetime, time, timedelta

from .geofence import FLAG_LABELS

OVERTIME_MIN_MINUTES = 30
NO_CLOCK_OUT_AFTER_HOURS = 4
NO_SHIFT_DAY_HOURS = 12          # without a shift, a day is assumed to last this long


class Status:
    NOT_YET      = "not_yet"        # Belum masuk (before the shift has started)
    WORKING      = "working"        # Sedang bekerja
    ON_TIME      = "on_time"
    LATE         = "late"
    EARLY_OUT    = "early_out"
    NO_CLOCK_OUT = "no_clock_out"
    ABSENT       = "absent"
    DAY_OFF      = "day_off"
    DAY_OFF_WORK = "day_off_work"   # came in on a day off
    REJECTED     = "rejected"       # HR rejected the day: counts as not worked
    PRESENT      = "present"        # came in, no shift to measure against


STATUS_LABELS = {
    Status.NOT_YET: "Belum masuk", Status.WORKING: "Sedang bekerja", Status.ON_TIME: "Tepat waktu",
    Status.LATE: "Terlambat", Status.EARLY_OUT: "Pulang cepat", Status.NO_CLOCK_OUT: "Tidak absen pulang",
    Status.ABSENT: "Tidak hadir", Status.DAY_OFF: "Libur", Status.DAY_OFF_WORK: "Masuk di hari libur",
    Status.REJECTED: "Ditolak HR", Status.PRESENT: "Hadir",
}

# Which status is shown first when a day has several (late AND early out, say).
_PRECEDENCE = (Status.NO_CLOCK_OUT, Status.LATE, Status.EARLY_OUT, Status.WORKING)


@dataclass(frozen=True)
class Tap:
    kind: str                 # "in" | "switch" | "out"
    at: datetime              # aware
    site: str = ""            # site name, for minutes per site
    flags: tuple = ()


@dataclass(frozen=True)
class ShiftInfo:
    start: time
    end: time
    grace_minutes: int = 10
    working_days: str = "12345"

    @property
    def crosses_midnight(self):
        return self.end <= self.start


@dataclass
class DayResult:
    status: str
    tags: list = field(default_factory=list)          # every status that applies (for the counters)
    first_in: datetime = None
    last_out: datetime = None
    late_minutes: int = 0
    early_minutes: int = 0
    worked_minutes: int = 0
    overtime_proposed_minutes: int = 0
    site_minutes: dict = field(default_factory=dict)
    flags: list = field(default_factory=list)          # flags from the taps (outside site, low accuracy...)
    review_reasons: list = field(default_factory=list)  # plain words for HR
    needs_review: bool = False

    @property
    def label(self):
        return STATUS_LABELS.get(self.status, self.status)


def _minutes(delta):
    return max(0, int(delta.total_seconds() // 60))


def evaluate_day(day, shift, taps, now, tz, *, hr_in=None, hr_out=None, decision="", waive_late=False,
                 overtime_approved=None):
    """
    day      the working date (a night shift belongs to the date it started)
    shift    ShiftInfo or None
    taps     list of Tap, any order
    now      aware datetime
    tz       the company's timezone (tzinfo), e.g. ZoneInfo("Asia/Jakarta")
    hr_in / hr_out   HR's corrected clock-in / clock-out (aware), override the taps
    decision         "" (not reviewed) | "approved" | "rejected"
    """
    taps = sorted(taps, key=lambda t: t.at)
    flags = list(dict.fromkeys(f for t in taps for f in t.flags))
    working_day = shift is None or str(day.isoweekday()) in shift.working_days

    start_dt = end_dt = None
    if shift is not None:
        start_dt = datetime.combine(day, shift.start, tzinfo=tz)
        end_day = day + timedelta(days=1) if shift.crosses_midnight else day
        end_dt = datetime.combine(end_day, shift.end, tzinfo=tz)

    ins = [t.at for t in taps if t.kind == "in"]
    outs = [t.at for t in taps if t.kind == "out"]
    first_in = hr_in or (min(ins) if ins else (taps[0].at if taps else None))
    last_out = hr_out or (max(outs) if outs else None)
    if first_in and last_out and last_out < first_in:
        last_out = None

    if decision == "rejected":
        return DayResult(status=Status.REJECTED, tags=[Status.REJECTED], first_in=first_in, last_out=last_out,
                         flags=flags)

    # ── nobody came ──
    if first_in is None:
        if not working_day:
            return DayResult(status=Status.DAY_OFF, tags=[Status.DAY_OFF])
        if start_dt is not None:
            not_started = now < start_dt + timedelta(minutes=shift.grace_minutes)
        else:
            not_started = now.astimezone(tz).date() <= day
        status = Status.NOT_YET if not_started else Status.ABSENT
        return DayResult(status=status, tags=[status])

    # ── somebody came ──
    result = DayResult(status=Status.ON_TIME, first_in=first_in, last_out=last_out, flags=flags)
    tags = []
    if not working_day:
        tags.append(Status.DAY_OFF_WORK)

    if start_dt is not None and working_day:
        late = _minutes(first_in - start_dt)
        if late > shift.grace_minutes:
            result.late_minutes = late
            if not waive_late:
                tags.append(Status.LATE)

    if last_out is None:
        expected_end = end_dt if (end_dt is not None and working_day) else first_in + timedelta(hours=NO_SHIFT_DAY_HOURS)
        if now > expected_end + timedelta(hours=NO_CLOCK_OUT_AFTER_HOURS):
            tags.append(Status.NO_CLOCK_OUT)
        else:
            tags.append(Status.WORKING)
    else:
        result.worked_minutes = _minutes(last_out - first_in)
        if end_dt is not None and working_day:
            early = _minutes(end_dt - last_out)
            if early > 0:
                result.early_minutes = early
                tags.append(Status.EARLY_OUT)
            overtime = _minutes(last_out - end_dt)
        else:
            overtime = result.worked_minutes if not working_day else 0
        if overtime >= OVERTIME_MIN_MINUTES:
            result.overtime_proposed_minutes = overtime

    # minutes per site: from each in / switch to the next tap
    for a, b in zip(taps, taps[1:]):
        if a.kind in ("in", "switch") and a.site:
            result.site_minutes[a.site] = result.site_minutes.get(a.site, 0) + _minutes(b.at - a.at)

    result.tags = tags
    primary = next((s for s in _PRECEDENCE if s in tags), None)
    if primary is None:
        primary = Status.DAY_OFF_WORK if Status.DAY_OFF_WORK in tags else (
            Status.PRESENT if shift is None else Status.ON_TIME)
    result.status = primary
    if Status.ON_TIME == primary and Status.ON_TIME not in tags:
        tags.append(Status.ON_TIME)

    # what HR should look at
    reasons = [FLAG_LABELS.get(f, f) for f in flags]
    if Status.LATE in tags:
        reasons.append(f"Terlambat {result.late_minutes} menit")
    if Status.EARLY_OUT in tags:
        reasons.append(f"Pulang cepat {result.early_minutes} menit")
    if Status.NO_CLOCK_OUT in tags:
        reasons.append("Tidak absen pulang")
    if result.overtime_proposed_minutes and overtime_approved is None:
        reasons.append(f"Lembur {result.overtime_proposed_minutes} menit menunggu persetujuan")
    if Status.DAY_OFF_WORK in tags:
        reasons.append("Masuk di hari libur")
    result.review_reasons = reasons
    result.needs_review = bool(reasons) and decision != "approved"
    return result
