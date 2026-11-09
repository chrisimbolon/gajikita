"""
G12d (6 Nov 2026) — uang makan per employee (apps/payroll/meals.py).
"""
from datetime import date, datetime, time
from zoneinfo import ZoneInfo

from django.test import SimpleTestCase

from apps.payroll.meals import LATE_OUT, NONE, OVERTIME_DAY, PRESENT_DAY, earns_meal, rule_for

WIB = ZoneInfo("Asia/Jakarta")
DAY = date(2026, 10, 10)
AFTER = time(19)


def at(h, m, d=DAY):
    return datetime(d.year, d.month, d.day, h, m, tzinfo=WIB)


def meal(rule, first_in=at(7, 55), last_out=at(17, 5), rejected=False, ot=0):
    return earns_meal(rule, DAY, first_in, last_out, rejected, ot, AFTER, WIB)


class MealRuleTests(SimpleTestCase):
    def test_the_employee_rule_wins_and_empty_follows_the_company(self):
        self.assertEqual(rule_for("present_day", "late_out"), PRESENT_DAY)
        self.assertEqual(rule_for("", "late_out"), LATE_OUT)
        self.assertEqual(rule_for("", ""), NONE)

    def test_present_day(self):
        self.assertTrue(meal(PRESENT_DAY))
        self.assertTrue(meal(PRESENT_DAY, last_out=None))              # forgot to tap out: still came
        self.assertFalse(meal(PRESENT_DAY, first_in=None, last_out=None))
        self.assertFalse(meal(PRESENT_DAY, rejected=True))

    def test_overtime_day_needs_approved_overtime(self):
        self.assertFalse(meal(OVERTIME_DAY, last_out=at(21, 36)))       # proposed only
        self.assertTrue(meal(OVERTIME_DAY, last_out=at(21, 36), ot=270))

    def test_late_out_after_seven_in_the_evening_also_after_midnight(self):
        self.assertFalse(meal(LATE_OUT, last_out=at(18, 59)))
        self.assertFalse(meal(LATE_OUT, last_out=at(19, 0)))          # G12h: 'melebihi 19.00', 19:00 is not past it
        self.assertFalse(meal(LATE_OUT, last_out=datetime(DAY.year, DAY.month, DAY.day, 19, 0, 45, tzinfo=WIB)))   # seconds don't count
        self.assertTrue(meal(LATE_OUT, last_out=at(19, 1)))
        self.assertTrue(meal(LATE_OUT, last_out=at(2, 1, date(2026, 10, 11))))   # pump day 08:11 -> 02:01
        self.assertFalse(meal(LATE_OUT, last_out=None))
        self.assertFalse(meal(LATE_OUT, last_out=at(20, 32), rejected=True))

    def test_none(self):
        self.assertFalse(meal(NONE, last_out=at(22, 0), ot=300))
