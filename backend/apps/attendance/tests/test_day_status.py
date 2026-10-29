"""
G3 (28 Oct 2026) — the pure day-status rules in apps/attendance/day_status.py.
"""
from datetime import date, datetime, time
from zoneinfo import ZoneInfo

from apps.attendance.day_status import ShiftInfo, Status, Tap, evaluate_day
from django.test import SimpleTestCase

WIB = ZoneInfo("Asia/Jakarta")
TUE = date(2026, 10, 27)            # a Tuesday
SUN = date(2026, 11, 1)             # a Sunday
DAY = ShiftInfo(start=time(8), end=time(17), grace_minutes=10, working_days="123456")
NIGHT = ShiftInfo(start=time(22), end=time(6), grace_minutes=10, working_days="123456")


def at(d, h, m=0):
    return datetime(d.year, d.month, d.day, h, m, tzinfo=WIB)


NEXT_DAY = at(date(2026, 10, 28), 12)   # "now" well after Tuesday


def ev(*taps, shift=DAY, day=TUE, now=NEXT_DAY, **kw):
    return evaluate_day(day, shift, list(taps), now, WIB, **kw)


class DayStatusTests(SimpleTestCase):
    def test_on_time(self):
        r = ev(Tap("in", at(TUE, 7, 55)), Tap("out", at(TUE, 17, 5)))
        self.assertEqual((r.status, r.late_minutes, r.worked_minutes, r.needs_review), (Status.ON_TIME, 0, 550, False))

    def test_inside_the_grace_minutes_is_on_time(self):
        self.assertEqual(ev(Tap("in", at(TUE, 8, 9)), Tap("out", at(TUE, 17))).status, Status.ON_TIME)

    def test_late_counts_from_the_shift_start(self):
        r = ev(Tap("in", at(TUE, 8, 12)), Tap("out", at(TUE, 17)))
        self.assertEqual((r.status, r.late_minutes, r.needs_review), (Status.LATE, 12, True))
        self.assertIn("Terlambat 12 menit", r.review_reasons)

    def test_early_out(self):
        r = ev(Tap("in", at(TUE, 7, 58)), Tap("out", at(TUE, 15, 30)))
        self.assertEqual((r.status, r.early_minutes), (Status.EARLY_OUT, 90))

    def test_late_and_early_both_count(self):
        r = ev(Tap("in", at(TUE, 9)), Tap("out", at(TUE, 16)))
        self.assertEqual(r.status, Status.LATE)
        self.assertTrue({Status.LATE, Status.EARLY_OUT} <= set(r.tags))

    def test_still_working_then_no_clock_out(self):
        tap = Tap("in", at(TUE, 7, 55))
        self.assertEqual(ev(tap, now=at(TUE, 18)).status, Status.WORKING)
        self.assertEqual(ev(tap, now=at(TUE, 22)).status, Status.NO_CLOCK_OUT)

    def test_not_yet_then_absent(self):
        self.assertEqual(ev(now=at(TUE, 7, 30)).status, Status.NOT_YET)
        self.assertEqual(ev(now=at(TUE, 9)).status, Status.ABSENT)

    def test_day_off_and_coming_in_on_a_day_off(self):
        self.assertEqual(ev(day=SUN).status, Status.DAY_OFF)
        r = ev(Tap("in", at(SUN, 8)), Tap("out", at(SUN, 12)), day=SUN, now=at(SUN, 20))
        self.assertEqual((r.status, r.overtime_proposed_minutes), (Status.DAY_OFF_WORK, 240))
        self.assertTrue(r.needs_review)

    def test_overtime_is_proposed_only_from_30_minutes(self):
        self.assertEqual(ev(Tap("in", at(TUE, 8)), Tap("out", at(TUE, 17, 20))).overtime_proposed_minutes, 0)
        r = ev(Tap("in", at(TUE, 8)), Tap("out", at(TUE, 19)))
        self.assertEqual(r.overtime_proposed_minutes, 120)
        self.assertIn("Lembur 120 menit menunggu persetujuan", r.review_reasons)

    def test_night_shift_measured_across_midnight(self):
        wed = date(2026, 10, 28)
        r = ev(Tap("in", at(TUE, 22, 20)), Tap("out", at(wed, 6, 5)), shift=NIGHT, now=at(wed, 12))
        self.assertEqual((r.status, r.late_minutes, r.worked_minutes), (Status.LATE, 20, 465))
        self.assertEqual(r.early_minutes, 0)

    def test_hr_times_override_the_taps(self):
        r = ev(Tap("in", at(TUE, 7, 55)), hr_out=at(TUE, 17))
        self.assertEqual((r.status, r.last_out, r.worked_minutes), (Status.ON_TIME, at(TUE, 17), 545))

    def test_hr_can_excuse_lateness_and_approve(self):
        r = ev(Tap("in", at(TUE, 9)), Tap("out", at(TUE, 17)), waive_late=True, decision="approved")
        self.assertEqual((r.status, r.late_minutes, r.needs_review), (Status.ON_TIME, 60, False))

    def test_rejected_day(self):
        r = ev(Tap("in", at(TUE, 8), flags=("outside_site",)), decision="rejected")
        self.assertEqual((r.status, r.needs_review), (Status.REJECTED, False))

    def test_tap_flags_need_review(self):
        r = ev(Tap("in", at(TUE, 7, 55), flags=("outside_site",)), Tap("out", at(TUE, 17)))
        self.assertEqual((r.status, r.needs_review, r.review_reasons), (Status.ON_TIME, True, ["Di luar lokasi"]))

    def test_minutes_per_site_follow_the_switches(self):
        r = ev(Tap("in", at(TUE, 8), site="Workshop"), Tap("switch", at(TUE, 11), site="Jalan Lintas"),
               Tap("out", at(TUE, 17), site="Jalan Lintas"))
        self.assertEqual(r.site_minutes, {"Workshop": 180, "Jalan Lintas": 360})

    def test_no_shift_means_present(self):
        r = ev(Tap("in", at(TUE, 10)), Tap("out", at(TUE, 15)), shift=None)
        self.assertEqual((r.status, r.worked_minutes), (Status.PRESENT, 300))
