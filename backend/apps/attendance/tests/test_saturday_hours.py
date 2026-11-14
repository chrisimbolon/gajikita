"""G17-5 (14 Nov 2026): a shift can end earlier on Saturdays (DKCB office: 08:00-12:00). Made-up data."""
from datetime import date, datetime, time
from zoneinfo import ZoneInfo

from django.test import SimpleTestCase

from apps.attendance.day_status import ShiftInfo, Status, Tap, evaluate_day

WIB = ZoneInfo("Asia/Jakarta")
SAT, MON = date(2026, 10, 10), date(2026, 10, 12)
OFFICE = ShiftInfo(start=time(8), end=time(17), grace_minutes=5, working_days="123456", saturday_end=time(12))
PLANT = ShiftInfo(start=time(8), end=time(17), grace_minutes=5, working_days="123456")
NOW = datetime(2026, 10, 20, 12, tzinfo=WIB)


def at(d, h, m=0):
    return datetime(d.year, d.month, d.day, h, m, tzinfo=WIB)


def ev(shift, day, *hm):
    taps = [Tap(k, at(day, h, m)) for k, (h, m) in zip(("in", "out"), hm)]
    return evaluate_day(day, shift, taps, NOW, WIB)


class SaturdayHoursTests(SimpleTestCase):
    def test_leaving_at_noon_on_saturday_is_on_time(self):
        r = ev(OFFICE, SAT, (7, 53), (12, 1))                      # Tari, 10 Okt
        self.assertEqual((r.status, r.early_minutes), (Status.ON_TIME, 0))
        self.assertEqual(ev(PLANT, SAT, (7, 53), (12, 1)).early_minutes, 299)   # without the Saturday hours

    def test_other_days_keep_the_normal_end(self):
        self.assertEqual(ev(OFFICE, MON, (7, 53), (12, 1)).early_minutes, 299)

    def test_saturday_overtime_counts_from_noon(self):
        r = ev(OFFICE, SAT, (7, 53), (14, 0))
        self.assertEqual(r.overtime_proposed_minutes, 120)

    def test_a_lone_saturday_tap_uses_the_short_day(self):
        r = evaluate_day(SAT, OFFICE, [Tap("in", at(SAT, 11, 30))], NOW, WIB)   # middle of 08-12 is 10:00
        self.assertEqual(r.status, Status.NO_CLOCK_IN)
