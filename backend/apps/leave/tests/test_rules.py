"""
G7 (28 Oct 2026) — the pure leave rules, and how approved leave shows up in day_status.
"""
from datetime import date, datetime, time
from zoneinfo import ZoneInfo

from django.test import SimpleTestCase

from apps.attendance.day_status import ShiftInfo, Status, Tap, evaluate_day
from apps.leave import rules

WIB = ZoneInfo("Asia/Jakarta")
MON = date(2026, 11, 2)                       # a Monday
SHIFT_6 = ShiftInfo(start=time(8), end=time(17), grace_minutes=10, working_days="123456")


def check(**kw):
    base = dict(kind=rules.ANNUAL, special_reason="", start=MON, end=MON, days=1, annual_left=12,
                today=date(2026, 10, 28), by_worker=True)
    base.update(kw)
    return rules.check_request(**base)


class CountingTests(SimpleTestCase):
    def test_a_week_on_a_six_day_shift_is_six_days(self):
        self.assertEqual(len(rules.working_dates(MON, date(2026, 11, 8), "123456")), 6)
        self.assertEqual(len(rules.working_dates(MON, date(2026, 11, 8), "12345")), 5)
        self.assertEqual(len(rules.working_dates(MON, date(2026, 11, 8), None)), 7)

    def test_annual_leave_starts_after_twelve_months(self):
        joined = date(2025, 11, 10)
        self.assertEqual(rules.annual_entitlement(joined, date(2026, 11, 9)), 0)
        self.assertEqual(rules.annual_entitlement(joined, date(2026, 11, 10)), 12)
        self.assertEqual(rules.one_year_after(date(2024, 2, 29)), date(2025, 2, 28))


class CheckRequestTests(SimpleTestCase):
    def test_a_normal_request_is_fine(self):
        self.assertEqual(check(), {})

    def test_more_annual_days_than_left(self):
        self.assertIn("Sisa cuti tahunan 2 hari", check(days=3, annual_left=2)["end_date"])
        self.assertIn("Belum ada sisa", check(annual_left=0)["end_date"])

    def test_special_leave_has_a_reason_and_a_limit(self):
        self.assertIn("special_reason", check(kind=rules.SPECIAL))
        self.assertEqual(check(kind=rules.SPECIAL, special_reason="marriage", days=3), {})
        self.assertIn("paling banyak 3 hari", check(kind=rules.SPECIAL, special_reason="marriage", days=4)["end_date"])
        self.assertIn("paling banyak 1 hari", check(kind=rules.SPECIAL, special_reason="household_death", days=2)["end_date"])

    def test_sick_and_unpaid_have_no_balance(self):
        self.assertEqual(check(kind=rules.SICK, days=20, annual_left=0), {})
        self.assertEqual(check(kind=rules.UNPAID, days=5, annual_left=0), {})

    def test_dates_must_make_sense(self):
        self.assertIn("end_date", check(end=date(2026, 11, 1)))
        self.assertIn("90 hari", check(kind=rules.SICK, end=date(2027, 3, 1), days=70)["end_date"])
        self.assertIn("hari libur", check(days=0)["end_date"])

    def test_workers_cannot_go_far_back_but_hr_can(self):
        old = dict(kind=rules.SICK, start=date(2026, 9, 1), end=date(2026, 9, 2), days=2)
        self.assertIn("start_date", check(**old))
        self.assertEqual(check(by_worker=False, **old), {})

    def test_sick_note_hint(self):
        self.assertTrue(rules.sick_note_missing(rules.SICK, 3, False))
        self.assertFalse(rules.sick_note_missing(rules.SICK, 2, False))
        self.assertFalse(rules.sick_note_missing(rules.SICK, 3, True))

    def test_labels(self):
        self.assertEqual(rules.label_of(rules.SPECIAL, "marriage"), "Cuti khusus: menikah")
        self.assertEqual(rules.label_of(rules.UNPAID), "Izin tanpa upah")


class DayStatusWithLeaveTests(SimpleTestCase):
    def _eval(self, taps=(), leave="", day=MON, now=datetime(2026, 11, 2, 12, tzinfo=WIB)):
        return evaluate_day(day, SHIFT_6, list(taps), now, WIB, leave=leave)

    def test_approved_leave_replaces_absent(self):
        self.assertEqual(self._eval().status, Status.ABSENT)
        r = self._eval(leave="Sakit")
        self.assertEqual((r.status, r.tags, r.label, r.needs_review), (Status.LEAVE, [Status.LEAVE], "Sakit", False))

    def test_leave_also_replaces_not_yet(self):
        r = self._eval(leave="Cuti tahunan", now=datetime(2026, 11, 2, 6, tzinfo=WIB))
        self.assertEqual(r.status, Status.LEAVE)

    def test_a_day_off_inside_leave_stays_a_day_off(self):
        self.assertEqual(self._eval(leave="Cuti tahunan", day=date(2026, 11, 8)).status, Status.DAY_OFF)

    def test_coming_in_on_leave_asks_hr(self):
        r = self._eval(taps=[Tap("in", datetime(2026, 11, 2, 7, 55, tzinfo=WIB))], leave="Cuti tahunan")
        self.assertEqual(r.status, Status.WORKING)
        self.assertIn("Masuk padahal cuti tahunan", r.review_reasons)
        self.assertTrue(r.needs_review)
