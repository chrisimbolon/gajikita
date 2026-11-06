"""
G12d (6 Nov 2026) — no overtime is proposed for people who are not paid overtime
(Karyawan → "Berhak upah lembur" off), so their late evenings don't fill Perlu Tinjau.
"""
from datetime import date, datetime, time
from zoneinfo import ZoneInfo

from django.test import SimpleTestCase

from apps.attendance.day_status import ShiftInfo, Status, Tap, evaluate_day

WIB = ZoneInfo("Asia/Jakarta")
MON = date(2026, 10, 5)
SUN = date(2026, 10, 4)
PAGI = ShiftInfo(start=time(8), end=time(17), grace_minutes=5, working_days="123456")
LATER = datetime(2026, 10, 10, 12, tzinfo=WIB)


def at(d, h, m):
    return datetime(d.year, d.month, d.day, h, m, tzinfo=WIB)


def ev(d, t_in, t_out, **kw):
    return evaluate_day(d, PAGI, [Tap("in", at(d, *t_in)), Tap("out", at(d, *t_out))], LATER, WIB, **kw)


class OvertimeEligibleTests(SimpleTestCase):
    def test_eligible_people_still_get_overtime_proposed(self):
        r = ev(MON, (7, 50), (20, 32))
        self.assertEqual(r.overtime_proposed_minutes, 212)
        self.assertTrue(r.needs_review)

    def test_a_driver_home_late_is_simply_on_time(self):
        r = ev(MON, (7, 50), (20, 32), overtime_eligible=False)
        self.assertEqual(r.overtime_proposed_minutes, 0)
        self.assertEqual(r.status, Status.ON_TIME)
        self.assertFalse(r.needs_review)
        self.assertEqual(r.worked_minutes, 762)

    def test_late_and_day_off_work_are_still_shown(self):
        self.assertIn(Status.LATE, ev(MON, (8, 20), (20, 0), overtime_eligible=False).tags)
        sunday = ev(SUN, (8, 0), (12, 0), overtime_eligible=False)
        self.assertEqual((sunday.overtime_proposed_minutes, sunday.needs_review), (0, True))
