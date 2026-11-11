"""
G12i (11 Nov 2026) — "Tidak wajib absen": the pure rule and the period arithmetic. No database.

DKCB's case: Marganda (excavator operator) works at Lobam with no machine; Anthony pays every working day.
"""
from datetime import date, datetime, time
from zoneinfo import ZoneInfo

from django.test import SimpleTestCase

from apps.attendance.day_status import ShiftInfo, Status, Tap, evaluate_day
from apps.attendance.exemptions import changed_ranges, covering, locked_hit, overlapping
from apps.attendance.rekap_codes import day_cell

WIB = ZoneInfo("Asia/Jakarta")
SHIFT = ShiftInfo(start=time(8), end=time(17), grace_minutes=5, working_days="123456")
NOW = datetime(2026, 10, 26, 10, tzinfo=WIB)
MON, SUN = date(2026, 10, 12), date(2026, 10, 11)


def at(d, h, m=0):
    return datetime(d.year, d.month, d.day, h, m, tzinfo=WIB)


class RuleTests(SimpleTestCase):
    def test_a_working_day_without_taps_counts_as_worked(self):
        r = evaluate_day(MON, SHIFT, [], NOW, WIB, exempt="Kerja di Lobam")
        self.assertEqual((r.status, r.label, r.needs_review, r.note),
                         (Status.EXEMPT, "Tidak wajib absen", False, "Tidak wajib absen: Kerja di Lobam"))
        self.assertEqual(evaluate_day(MON, SHIFT, [], NOW, WIB).status, Status.ABSENT)        # without: absent

    def test_taps_are_shown_but_decide_nothing(self):
        taps = [Tap("in", at(MON, 9, 40)), Tap("out", at(MON, 22, 0))]       # 95 min late, 5 h past the end
        r = evaluate_day(MON, SHIFT, taps, NOW, WIB, exempt="Kerja di Lobam")
        self.assertEqual((r.status, r.late_minutes, r.overtime_proposed_minutes, r.needs_review), (Status.EXEMPT, 0, 0, False))
        self.assertEqual((r.first_in, r.last_out), (at(MON, 9, 40), at(MON, 22, 0)))

    def test_leave_rejection_and_days_off_still_rule(self):
        self.assertEqual(evaluate_day(MON, SHIFT, [], NOW, WIB, exempt="x", leave="Cuti tahunan").status, Status.LEAVE)
        self.assertEqual(evaluate_day(MON, SHIFT, [], NOW, WIB, exempt="x", decision="rejected").status, Status.REJECTED)
        r = evaluate_day(SUN, SHIFT, [Tap("in", at(SUN, 8)), Tap("out", at(SUN, 17))], NOW, WIB, exempt="x")
        self.assertEqual((r.status, r.first_in), (Status.DAY_OFF, None))     # no "masuk di hari libur" pay from taps

    def test_rekap_code_is_DL(self):
        r = evaluate_day(MON, SHIFT, [], NOW, WIB, exempt="Kerja di Lobam")
        self.assertEqual(day_cell(MON, r, None, None, 0)["c"], "DL")


class PeriodTests(SimpleTestCase):
    def test_covering_with_an_open_end(self):
        periods = [(date(2026, 9, 1), None, "Kerja di Lobam")]
        self.assertEqual(covering(periods, date(2026, 10, 12)), "Kerja di Lobam")
        self.assertEqual(covering(periods, date(2026, 8, 31)), "")
        closed = [(date(2026, 9, 1), date(2026, 9, 30), "Lobam")]
        self.assertEqual((covering(closed, date(2026, 9, 30)), covering(closed, date(2026, 10, 1))), ("Lobam", ""))

    def test_overlapping(self):
        periods = [(date(2026, 9, 1), date(2026, 9, 30), "a", 1), (date(2026, 11, 1), None, "b", 2)]
        self.assertIsNone(overlapping(periods, date(2026, 10, 1), date(2026, 10, 31)))
        self.assertEqual(overlapping(periods, date(2026, 9, 30), date(2026, 10, 5))[3], 1)
        self.assertEqual(overlapping(periods, date(2026, 10, 1), None)[3], 2)          # open end runs into November
        self.assertIsNone(overlapping(periods, date(2026, 9, 10), date(2026, 9, 20), skip=1))

    def test_changed_ranges(self):
        far = date.max
        self.assertEqual(changed_ranges(None, (date(2026, 9, 1), None)), [(date(2026, 9, 1), far)])
        self.assertEqual(changed_ranges((date(2026, 9, 1), None), (date(2026, 9, 1), date(2026, 11, 30))),
                         [(date(2026, 12, 1), far)])                                  # ending it changes only after
        self.assertEqual(changed_ranges((date(2026, 9, 1), date(2026, 9, 30)), None),
                         [(date(2026, 9, 1), date(2026, 9, 30))])
        self.assertEqual(changed_ranges((date(2026, 9, 1), None), (date(2026, 9, 1), None)), [])

    def test_locked_hit(self):
        locked = [(date(2026, 9, 26), date(2026, 10, 25), "Payroll Oktober 2026")]
        self.assertIsNone(locked_hit([(date(2026, 12, 1), date.max)], locked))
        self.assertEqual(locked_hit([(date(2026, 10, 11), date.max)], locked)[2], "Payroll Oktober 2026")
