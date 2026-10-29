"""
G4a (28 Oct 2026) — overtime pay under PP 35/2021, the pure rules in apps/payroll/overtime.py.
A monthly wage of Rp 5.190.000 gives a round hourly rate of Rp 30.000 (5.190.000 / 173).
"""
from datetime import date
from decimal import Decimal

from apps.payroll.overtime import (
    hourly_rate, monthly_basis, overtime_pay, week_pattern, week_warnings,
)
from django.test import SimpleTestCase

HOURLY = hourly_rate(Decimal("5190000"))      # Rp 30.000


class BasisTests(SimpleTestCase):
    def test_hourly_rate_is_one_173rd_of_the_month(self):
        self.assertEqual(HOURLY, Decimal("30000"))

    def test_monthly_basis_includes_the_fixed_allowance(self):
        self.assertEqual(monthly_basis("monthly", "4690000", "500000", 6), Decimal("5190000"))

    def test_daily_worker_is_25_or_21_days(self):
        self.assertEqual(monthly_basis("daily", "200000", "0", 6), Decimal("5000000"))
        self.assertEqual(monthly_basis("daily", "200000", "0", 5), Decimal("4200000"))

    def test_piece_rate_is_not_covered_yet(self):
        self.assertIsNone(monthly_basis("piece", "100000", "0", 6))

    def test_week_pattern(self):
        self.assertEqual((week_pattern("123456"), week_pattern("12345"), week_pattern("")), (6, 5, 5))


class WorkingDayTests(SimpleTestCase):
    def test_three_hours(self):
        # 1 h x 1.5 x 30.000 + 2 h x 2 x 30.000 = 45.000 + 120.000
        pay = overtime_pay(180, rest_day=False, pattern=6, hourly=HOURLY)
        self.assertEqual([(l.minutes, l.multiplier, l.amount) for l in pay.lines],
                         [(60, Decimal("1.5"), Decimal("45000")), (120, Decimal("2"), Decimal("120000"))])
        self.assertEqual((pay.amount, pay.warnings), (Decimal("165000"), []))

    def test_half_an_hour_is_pro_rata(self):
        self.assertEqual(overtime_pay(30, False, 6, HOURLY).amount, Decimal("22500"))

    def test_more_than_four_hours_is_warned_not_blocked(self):
        pay = overtime_pay(300, False, 6, HOURLY)
        self.assertEqual(pay.amount, Decimal("45000") + Decimal("240000"))
        self.assertEqual(len(pay.warnings), 1)


class RestDayTests(SimpleTestCase):
    def test_six_day_week_nine_hours(self):
        # 7 h x 2 + 1 h x 3 + 1 h x 4 = 420.000 + 90.000 + 120.000
        pay = overtime_pay(540, rest_day=True, pattern=6, hourly=HOURLY)
        self.assertEqual([l.amount for l in pay.lines], [Decimal("420000"), Decimal("90000"), Decimal("120000")])
        self.assertEqual(pay.amount, Decimal("630000"))

    def test_five_day_week_has_8_hours_at_double(self):
        pay = overtime_pay(540, rest_day=True, pattern=5, hourly=HOURLY)
        self.assertEqual([l.amount for l in pay.lines], [Decimal("480000"), Decimal("90000")])

    def test_rest_day_limit(self):
        self.assertEqual(overtime_pay(660, True, 6, HOURLY).warnings, [])
        self.assertEqual(len(overtime_pay(700, True, 6, HOURLY).warnings), 1)


class WeekLimitTests(SimpleTestCase):
    def test_more_than_18_hours_in_a_week(self):
        week = [(date(2026, 10, 26 + i), 240, False) for i in range(5)]        # Mon-Fri, 4 h each = 20 h
        self.assertEqual(len(week_warnings(week)), 1)
        self.assertEqual(week_warnings(week[:4]), [])                            # 16 h is fine

    def test_rest_days_do_not_count_toward_the_18_hours(self):
        week = [(date(2026, 10, 26 + i), 240, False) for i in range(4)] + [(date(2026, 11, 1), 480, True)]
        self.assertEqual(week_warnings(week), [])
