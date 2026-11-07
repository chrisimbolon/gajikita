"""
G12e (7 Nov 2026) — a second meal past midnight, breakfast before 07:00, overtime in 15/45-minute blocks.
"""
from datetime import date, datetime, time
from zoneinfo import ZoneInfo

from django.test import SimpleTestCase

from apps.payroll.engine import (HALF_DOWN, NEAREST_HALF, EmployeeTerms, PayrollRules, PeriodInput, calculate,
                                 round_overtime)
from apps.payroll.meals import LATE_OUT, NONE, OVERTIME_DAY, PRESENT_DAY, earns_breakfast, meal_count

WIB = ZoneInfo("Asia/Jakarta")
DAY = date(2026, 10, 15)


def at(h, m, d=DAY):
    return datetime(d.year, d.month, d.day, h, m, tzinfo=WIB)


def meals(rule, last_out, ot=0, extra=True, rejected=False):
    return meal_count(rule, DAY, at(8, 11), last_out, rejected, ot, time(19), WIB, midnight_extra=extra)


NEXT = date(2026, 10, 16)


class MidnightMealTests(SimpleTestCase):
    def test_late_out(self):
        self.assertEqual(meals(LATE_OUT, at(18, 59)), 0)
        self.assertEqual(meals(LATE_OUT, at(22, 19)), 1)
        self.assertEqual(meals(LATE_OUT, at(0, 0, NEXT)), 1)        # "melebihi 00:00": exactly 00:00 is not past it
        self.assertEqual(meals(LATE_OUT, at(0, 1, NEXT)), 2)
        self.assertEqual(meals(LATE_OUT, at(2, 1, NEXT)), 2)
        self.assertEqual(meals(LATE_OUT, at(2, 1, NEXT), extra=False), 1)   # setting off: as G12d
        self.assertEqual(meals(LATE_OUT, at(2, 1, NEXT), rejected=True), 0)

    def test_overtime_day(self):
        self.assertEqual(meals(OVERTIME_DAY, at(2, 1, NEXT)), 0)              # not approved yet
        self.assertEqual(meals(OVERTIME_DAY, at(2, 1, NEXT), ot=540), 2)

    def test_present_day_and_none_never_get_a_second_meal(self):
        self.assertEqual(meals(PRESENT_DAY, at(2, 1, NEXT)), 1)
        self.assertEqual(meals(NONE, at(2, 1, NEXT)), 0)


class BreakfastTests(SimpleTestCase):
    def test_before_seven(self):
        self.assertTrue(earns_breakfast(DAY, at(6, 43), False, time(7), WIB))
        self.assertFalse(earns_breakfast(DAY, at(7, 0), False, time(7), WIB))
        self.assertFalse(earns_breakfast(DAY, None, False, time(7), WIB))
        self.assertFalse(earns_breakfast(DAY, at(6, 43), True, time(7), WIB))

    def test_on_the_slip(self):
        rules = PayrollRules(meal_allowance=15000, breakfast_allowance=12000)
        slip = calculate(EmployeeTerms(base_salary=4000000), PeriodInput(meal_days=1, breakfast_days=1), rules)
        self.assertEqual(slip.amount("meal"), 15000)
        self.assertEqual(slip.amount("breakfast"), 12000)        # Sudarmono, September: 27.000


class BlockRoundingTests(SimpleTestCase):
    def test_dkcb_blocks(self):
        # DKCB 'Note': 1-15 minutes -> 0, 16-30 -> 0,5, 31-45 -> 0,5, 46-60 -> 1
        cases = {60: 60, 75: 60, 76: 90, 90: 90, 105: 90, 106: 120, 216: 210, 541: 540}
        for minutes, expected in cases.items():
            self.assertEqual(round_overtime(minutes, HALF_DOWN), expected, minutes)

    def test_only_the_edges_differ_from_nearest_half(self):
        self.assertEqual((round_overtime(75, NEAREST_HALF), round_overtime(75, HALF_DOWN)), (90, 60))
        self.assertEqual((round_overtime(105, NEAREST_HALF), round_overtime(105, HALF_DOWN)), (120, 90))
        self.assertEqual(round_overtime(80, NEAREST_HALF), round_overtime(80, HALF_DOWN))
