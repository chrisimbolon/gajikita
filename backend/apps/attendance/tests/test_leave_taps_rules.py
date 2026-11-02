"""
G9b (2 Nov 2026) — taps on an approved leave day: no late / early / no-clock-out fines, HR is
asked ("Masuk padahal ..."), and rejecting the day puts it back to the leave.
"""
from datetime import date, datetime, time
from zoneinfo import ZoneInfo

from django.test import SimpleTestCase

from apps.attendance.day_status import ShiftInfo, Status, Tap, evaluate_day

WIB = ZoneInfo("Asia/Jakarta")
MON = date(2026, 11, 2)
SHIFT = ShiftInfo(start=time(8), end=time(17), grace_minutes=5, working_days="123456")
LATER = datetime(2026, 11, 4, 12, tzinfo=WIB)


def at(h, m):
    return datetime(2026, 11, 2, h, m, tzinfo=WIB)


def ev(taps, leave="", **kw):
    return evaluate_day(MON, SHIFT, list(taps), LATER, WIB, leave=leave, **kw)


class LeaveWithTapsTests(SimpleTestCase):
    def test_no_late_or_early_on_a_leave_day(self):
        taps = [Tap("in", at(8, 24)), Tap("out", at(15, 30))]
        plain = ev(taps)
        self.assertIn(Status.LATE, plain.tags)
        self.assertIn(Status.EARLY_OUT, plain.tags)
        r = ev(taps, leave="Cuti tahunan")
        self.assertNotIn(Status.LATE, r.tags)
        self.assertNotIn(Status.EARLY_OUT, r.tags)
        self.assertEqual((r.status, r.review_reasons, r.needs_review), (Status.ON_TIME, ["Masuk padahal cuti tahunan"], True))

    def test_no_missing_clock_out_on_a_leave_day(self):
        self.assertEqual(ev([Tap("in", at(7, 55))]).status, Status.NO_CLOCK_OUT)
        r = ev([Tap("in", at(7, 55))], leave="Sakit")
        self.assertNotIn(Status.NO_CLOCK_OUT, r.tags)
        self.assertEqual(r.review_reasons, ["Masuk padahal sakit"])

    def test_rejecting_puts_the_day_back_to_leave(self):
        taps = [Tap("in", at(8, 24)), Tap("out", at(17, 0))]
        self.assertEqual(ev(taps, decision="rejected").status, Status.REJECTED)
        r = ev(taps, leave="Sakit", decision="rejected")
        self.assertEqual((r.status, r.label, r.needs_review), (Status.LEAVE, "Sakit", False))

    def test_approving_clears_the_question(self):
        r = ev([Tap("in", at(7, 55)), Tap("out", at(17, 0))], leave="Cuti tahunan", decision="approved")
        self.assertEqual((r.status, r.needs_review), (Status.ON_TIME, False))
