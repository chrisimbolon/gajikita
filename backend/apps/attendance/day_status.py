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

from .company_events import DISRUPTION, HOLIDAY, label as event_label
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
    NO_CLOCK_IN  = "no_clock_in"    # G17-1: only a clock-out tap that day (a lone afternoon tap)
    ABSENT       = "absent"
    DAY_OFF      = "day_off"
    DAY_OFF_WORK = "day_off_work"   # came in on a day off
    REJECTED     = "rejected"       # HR rejected the day: counts as not worked
    PRESENT      = "present"        # came in, no shift to measure against
    LEAVE        = "leave"          # approved cuti / sakit / izin (G7)
    EXEMPT       = "exempt"         # G12i: tidak wajib absen (off-site, no machine): counts as worked


STATUS_LABELS = {
    Status.NOT_YET: "Belum masuk", Status.WORKING: "Sedang bekerja", Status.ON_TIME: "Tepat waktu",
    Status.LATE: "Terlambat", Status.EARLY_OUT: "Pulang cepat", Status.NO_CLOCK_OUT: "Tidak absen pulang",
    Status.ABSENT: "Tidak hadir", Status.DAY_OFF: "Libur", Status.DAY_OFF_WORK: "Masuk di hari libur",
    Status.REJECTED: "Ditolak HR", Status.PRESENT: "Hadir", Status.LEAVE: "Cuti / izin",
    Status.EXEMPT: "Tidak wajib absen", Status.NO_CLOCK_IN: "Tidak absen masuk",          # G17-1
}

# Which status is shown first when a day has several (late AND early out, say).
_PRECEDENCE = (Status.NO_CLOCK_IN, Status.NO_CLOCK_OUT, Status.LATE, Status.EARLY_OUT, Status.WORKING)


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
    leave: str = ""                                    # the approved leave that day, e.g. "Sakit" (G7)
    note: str = ""                                     # G12e: "Lembur malam sampai 00:30: masuk jam 10:00"
    half_day: bool = False                             # G17-1: one tap only (no clock-in or no clock-out);
                                                       # payroll cuts ½ day when the company's rule is on
    event: str = ""                                    # G17-2: "Gangguan absen: Mati lampu" / "Libur: ..."
    holiday: bool = False                              # G17-2: a working day turned into a holiday
    disrupted: bool = False                            # G17-2: a working day under a disruption

    @property
    def label(self):
        if self.status == Status.LEAVE and self.leave:
            return self.leave
        return STATUS_LABELS.get(self.status, self.status)


def _minutes(delta):
    return max(0, int(delta.total_seconds() // 60))


def evaluate_day(day, shift, taps, now, tz, *, event=None, **kw):
    """
    The day's status (see _evaluate_day for every other argument).
    event   G17-2: the company event covering this person that day, (kind, reason) from company_events, or None.
            A holiday turns a working day into a day off; a disruption counts a working day as worked.
    """
    r = _evaluate_day(day, shift, taps, now, tz, event=event, **kw)
    if event and (shift is None or str(day.isoweekday()) in shift.working_days):
        r.event = event_label(*event)
        r.holiday = event[0] == HOLIDAY
        r.disrupted = event[0] == DISRUPTION and r.status not in (Status.LEAVE, Status.EXEMPT, Status.REJECTED,
                                                                Status.DAY_OFF)
        if r.holiday or r.disrupted:
            r.note = r.note or r.event
    return r


def _evaluate_day(day, shift, taps, now, tz, *, hr_in=None, hr_out=None, decision="", waive_late=False,
                  overtime_approved=None, leave="", overtime_eligible=True, night=None,
                  overtime_min=OVERTIME_MIN_MINUTES, exempt="", event=None):
    """
    day      the working date (a night shift belongs to the date it started)
    shift    ShiftInfo or None
    taps     list of Tap, any order
    now      aware datetime
    tz       the company's timezone (tzinfo), e.g. ZoneInfo("Asia/Jakarta")
    hr_in / hr_out   HR's corrected clock-in / clock-out (aware), override the taps
    decision         "" (not reviewed) | "approved" | "rejected"
    leave            the approved leave that day ("Sakit", "Cuti tahunan"...), "" if none (G7)
    night            night_rules.NightStart: the previous day's overtime ran past midnight, so today
                     starts later (or is a day off). None = the normal start (G12e)
    overtime_min     overtime is proposed from this many minutes past the shift end (G12e setting)
    exempt           G12i: the reason this person needn't tap today ("Kerja di Lobam"), "" if they must. A working
                     day is then EXEMPT (counted as worked, nothing to review, no late / overtime / meal from taps);
                     leave still wins, HR can still reject the day, and a day off stays a day off
    """
    taps = sorted(taps, key=lambda t: t.at)
    flags = list(dict.fromkeys(f for t in taps for f in t.flags))
    working_day = shift is None or str(day.isoweekday()) in shift.working_days
    # G17-2: a holiday makes the working day a day off; a disruption means nothing about the taps counts against
    # anyone (no late, early-out, missing clock-in/out, ½ day; no taps = present). Overtime still counts.
    if event and event[0] == HOLIDAY:
        working_day = False
    disrupted = bool(event) and event[0] == DISRUPTION and working_day

    start_dt = end_dt = None
    if shift is not None:
        start_dt = datetime.combine(day, shift.start, tzinfo=tz)
        end_day = day + timedelta(days=1) if shift.crosses_midnight else day
        end_dt = datetime.combine(end_day, shift.end, tzinfo=tz)

    # G12e: after overtime past midnight the day starts later, or is a day off
    night = night if (night is not None and working_day and shift is not None) else None
    night_off = night is not None and night.day_off
    if night is not None and not night_off:
        start_dt = datetime.combine(day, night.start, tzinfo=tz)

    ins = [t.at for t in taps if t.kind == "in"]
    outs = [t.at for t in taps if t.kind == "out"]
    first_in = hr_in or (min(ins) if ins else (taps[0].at if taps else None))
    last_out = hr_out or (max(outs) if outs else None)
    if first_in and last_out and last_out < first_in:
        last_out = None

    # G17-1 (13 Nov 2026): ONE tap on a working day with a shift. Before the middle of the shift it is the
    # clock-in (so "no clock-out", as before); from the middle on it is the CLOCK-OUT, so "no clock-in". In R1
    # Hadi's only tap on 14 Okt, 17:12, was read as a clock-in: 552 minutes late. HR's own times (Ubah jam) win.
    out_only = False
    if (hr_in is None and hr_out is None and shift is not None and working_day and len(taps) == 1
            and taps[0].kind in ("in", "out") and start_dt is not None):
        middle = start_dt + (end_dt - start_dt) / 2
        if taps[0].at >= middle:
            out_only, first_in, last_out = True, None, taps[0].at

    if decision == "rejected" and leave and working_day:
        # G9b: HR rejected the taps on a leave day ("salah tap"): the day goes back to the leave
        return DayResult(status=Status.LEAVE, tags=[Status.LEAVE], leave=leave)
    if decision == "rejected":
        return DayResult(status=Status.REJECTED, tags=[Status.REJECTED], first_in=first_in, last_out=last_out,
                         flags=flags)

    # G12i: not required to tap. Taps, if any, are shown but decide nothing.
    if exempt:
        if not working_day:
            return DayResult(status=Status.DAY_OFF, tags=[Status.DAY_OFF], flags=flags)
        if leave:
            return DayResult(status=Status.LEAVE, tags=[Status.LEAVE], leave=leave)
        return DayResult(status=Status.EXEMPT, tags=[Status.EXEMPT], first_in=first_in, last_out=last_out,
                         flags=flags, note=f"Tidak wajib absen: {exempt}")

    # ── nobody came ──
    if first_in is None and not out_only:
        if not working_day:
            return DayResult(status=Status.DAY_OFF, tags=[Status.DAY_OFF])
        if leave:                    # approved leave: not absent, and nothing for HR to look at
            return DayResult(status=Status.LEAVE, tags=[Status.LEAVE], leave=leave)
        if night_off:                # G12e: worked late into the night, so no one expects them today
            return DayResult(status=Status.DAY_OFF, tags=[Status.DAY_OFF], note=night.note)
        if disrupted:                # G17-2: power cut / broken machine: counted as worked, nothing to review
            return DayResult(status=Status.ON_TIME, tags=[Status.ON_TIME])
        if start_dt is not None:
            not_started = now < start_dt + timedelta(minutes=shift.grace_minutes)
        else:
            not_started = now.astimezone(tz).date() <= day
        status = Status.NOT_YET if not_started else Status.ABSENT
        return DayResult(status=status, tags=[status])

    # ── somebody came ──
    result = DayResult(status=Status.ON_TIME, first_in=first_in, last_out=last_out, flags=flags,
                       note=night.note if night is not None else "")
    tags = []
    if not working_day:
        tags.append(Status.DAY_OFF_WORK)
    # G9b: on an approved leave day there is nothing to fine (late, early, no clock-out);
    # HR is asked about the day instead ("Masuk padahal cuti").
    on_leave = bool(leave) and working_day

    if start_dt is not None and working_day and not night_off and first_in is not None and not disrupted:
        late = _minutes(first_in - start_dt)
        if late > shift.grace_minutes:
            result.late_minutes = late
            if not waive_late and not on_leave:
                tags.append(Status.LATE)

    if last_out is None:
        expected_end = end_dt if (end_dt is not None and working_day) else first_in + timedelta(hours=NO_SHIFT_DAY_HOURS)
        if now > expected_end + timedelta(hours=NO_CLOCK_OUT_AFTER_HOURS):
            if not on_leave and not disrupted:                                    # G17-2
                tags.append(Status.NO_CLOCK_OUT)
        else:
            tags.append(Status.WORKING)
    else:
        result.worked_minutes = _minutes(last_out - first_in) if first_in is not None else 0   # G17-1
        if end_dt is not None and working_day:
            early = _minutes(end_dt - last_out)
            if early > 0 and not night_off and not out_only and not disrupted:   # G17-1, G17-2
                result.early_minutes = early
                if not on_leave:
                    tags.append(Status.EARLY_OUT)
            overtime = _minutes(last_out - end_dt)
        else:
            overtime = result.worked_minutes if not working_day else 0
        if overtime >= overtime_min and overtime_eligible:      # G12d: nothing to propose otherwise
            result.overtime_proposed_minutes = overtime

    if out_only and not on_leave and not disrupted:                                   # G17-1, G17-2
        tags.append(Status.NO_CLOCK_IN)

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
    if Status.NO_CLOCK_IN in tags:                                                    # G17-1
        reasons.append("Tidak absen masuk (hanya tap pulang)")
    result.half_day = working_day and (Status.NO_CLOCK_OUT in tags or Status.NO_CLOCK_IN in tags)
    if result.overtime_proposed_minutes and overtime_approved is None:
        reasons.append(f"Lembur {result.overtime_proposed_minutes} menit menunggu persetujuan")
    if Status.DAY_OFF_WORK in tags:
        reasons.append("Masuk di hari libur")
    if leave and working_day:
        result.leave = leave
        reasons.append(f"Masuk padahal {leave.lower()}")
    result.review_reasons = reasons
    result.needs_review = bool(reasons) and decision != "approved"
    return result
