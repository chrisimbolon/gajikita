"""
G12e (7 Nov 2026) — a real month, end to end in pure Python: DKCB's pump helper K22 (Ganda),
26 Sep - 25 Okt 2026, taps from Anthony's ASR Edit sheet, paired by G12c, judged with
DKCB's rules from the 'Note' sheet:

  * late start after overtime past midnight (10:00 / 13:00 / day off)
  * late fine minutes = (late - 5) per day
  * overtime from 18:00, rounded in 15/45-minute blocks
  * uang makan when home after 19:00, plus one more when past 00:00

Anthony charged 301 late minutes and paid 25 meals. SeeGaji gives 25 meals and 265 minutes:
the 36-minute difference is 22 and 24 Okt, when Ganda had worked past midnight and was
allowed in at 10:00 under DKCB's own rule, but was still charged from 08:00.
"""
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from django.test import SimpleTestCase

from apps.attendance.day_status import ShiftInfo, Status, evaluate_day, Tap
from apps.attendance.fingerprint import make_sessions
from apps.attendance.night_rules import DKCB_EXAMPLE, night_start, parse_rules
from apps.attendance.tests.test_shift_pairing import DECIDED_BY_HAND, HR_OVERTIME, k22_taps
from apps.payroll.engine import HALF_DOWN, chargeable_late_minutes, round_overtime
from apps.payroll.meals import LATE_OUT, meal_count

WIB = ZoneInfo("Asia/Jakarta")
PAGI = ShiftInfo(start=time(8), end=time(17), grace_minutes=5, working_days="123456")
LATER = datetime(2026, 10, 26, 12, tzinfo=WIB)
RULES = parse_rules(DKCB_EXAMPLE)


def as_wib(t):
    return t.replace(tzinfo=WIB)


def month():
    sessions = make_sessions(k22_taps(), shift_start=time(8))
    by_day = {s.work_date: s for s in sessions}
    out = {}
    for s in sessions:
        prev = by_day.get(s.work_date - timedelta(days=1))
        prev_out = as_wib(prev.clock_out) if prev and prev.clock_out else None
        night = night_start(s.work_date, prev_out, False, RULES)
        taps = [Tap("in", as_wib(s.clock_in))] + ([Tap("out", as_wib(s.clock_out))] if s.clock_out else [])
        out[s.work_date] = evaluate_day(s.work_date, PAGI, taps, LATER, WIB, night=night, overtime_min=60)
    return out


class GandaOctoberTests(SimpleTestCase):
    def test_late_minutes(self):
        days = month()
        raw = [(r.late_minutes if Status.LATE in r.tags else 0, r.early_minutes if Status.EARLY_OUT in r.tags else 0)
               for r in days.values()]
        self.assertEqual(chargeable_late_minutes(raw, 5), 265)
        self.assertEqual(days[date(2026, 10, 20)].late_minutes, 19)          # in at 10:00, came 10:19
        self.assertNotIn(Status.LATE, days[date(2026, 10, 16)].tags)          # in at 13:00, came 12:27
        self.assertNotIn(Status.LATE, days[date(2026, 10, 22)].tags)          # in at 10:00, came 08:27
        self.assertNotIn(Status.LATE, days[date(2026, 10, 24)].tags)          # in at 10:00, came 08:19
        anthony_extra = 22 + 14                                               # what Anthony charged on 22 and 24 Okt
        self.assertEqual(265 + anthony_extra, 301)

    def test_meals(self):
        n = sum(meal_count(LATE_OUT, d, r.first_in, r.last_out, False, 0, time(19), WIB, midnight_extra=True)
                for d, r in month().items())
        self.assertEqual(n, 25)                                               # 20 evenings + 5 nights past 00:00

    def test_overtime_per_day(self):
        for d, r in month().items():
            key = d.isoformat()
            if key in DECIDED_BY_HAND:
                continue
            hours = round_overtime(r.overtime_proposed_minutes, HALF_DOWN) / 60
            self.assertEqual(hours, HR_OVERTIME.get(key, 0), key)
