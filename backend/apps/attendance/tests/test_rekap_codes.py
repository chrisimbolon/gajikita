"""G10 (1 Nov 2026) — Rekap Absensi cell codes and summary (pure)."""
from datetime import date, datetime, time
from types import SimpleNamespace
from zoneinfo import ZoneInfo

from django.test import SimpleTestCase

from apps.attendance.day_status import ShiftInfo, Tap, evaluate_day
from apps.attendance.rekap_codes import day_cell, outside_cell, summarize

WIB = ZoneInfo("Asia/Jakarta")
SHIFT = ShiftInfo(start=time(8), end=time(17), grace_minutes=5, working_days="123456")
NOW = datetime(2026, 10, 26, 10, tzinfo=WIB)
MON = date(2026, 10, 5)


def ev(taps=(), day=MON, leave=""):
    return evaluate_day(day, SHIFT, list(taps), NOW, WIB, leave=leave)


def at(h, m, d=MON):
    return datetime(d.year, d.month, d.day, h, m, tzinfo=WIB)


class CellTests(SimpleTestCase):
    def test_codes(self):
        day = SimpleNamespace(id="d1", decision="")
        self.assertEqual(day_cell(MON, ev([Tap("in", at(7, 55)), Tap("out", at(17, 0))]), day, None, 0)["c"], "H")
        late = day_cell(MON, ev([Tap("in", at(8, 24)), Tap("out", at(17, 1))]), day, None, 0)
        self.assertEqual((late["c"], late["late"], late["rv"]), ("T", 24, True))
        self.assertEqual(day_cell(MON, ev(), None, None, 0)["c"], "A")
        self.assertEqual(day_cell(date(2026, 10, 4), ev(day=date(2026, 10, 4)), None, None, 0)["c"], "L")
        sick = day_cell(MON, ev(leave="Sakit"), None, ("sick", "Sakit"), 0)
        self.assertEqual((sick["c"], sick["l"]), ("S", "Sakit"))
        self.assertEqual(day_cell(MON, ev(leave="Izin tanpa upah"), None, ("unpaid", "Izin tanpa upah"), 0)["c"], "I")
        self.assertEqual(outside_cell(MON)["c"], "-")

    def test_overtime_marks(self):
        r = ev([Tap("in", at(7, 52)), Tap("out", at(20, 34))])
        pending = day_cell(MON, r, SimpleNamespace(id="d", decision=""), None, 0)
        approved = day_cell(MON, r, SimpleNamespace(id="d", decision="approved"), None, 210)
        self.assertEqual((pending["otp"], pending["ot"]), (214, 0))
        self.assertEqual((approved["otp"], approved["ot"], approved["rv"]), (0, 210, False))

    def test_summary(self):
        day = SimpleNamespace(id="d", decision="")
        cells = [day_cell(MON, ev([Tap("in", at(8, 24)), Tap("out", at(17, 1))]), day, None, 0), day_cell(MON, ev(), None, None, 0)]
        nums = {"present_days": 1, "absent_days": 1, "leave": {}, "unpaid_leave_days": 0, "paid_leave_days": 0,
                "overtime": [{"minutes": 180}], "meal_days": 1, "review_days": 1}
        s = summarize(nums, cells)
        self.assertEqual((s["late_times"], s["late_minutes"], s["overtime_minutes"], s["problem"]), (1, 24, 180, True))
