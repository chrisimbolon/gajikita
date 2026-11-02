"""G8b part 1 (1 Nov 2026) — pay periods and pay dates (pure)."""
from datetime import date

from django.test import SimpleTestCase

from apps.payroll.engine import period_for, pay_date_for


class PeriodTests(SimpleTestCase):
    def test_period_ending_in_the_month(self):
        self.assertEqual(period_for(2026, 10, 26), (date(2026, 9, 26), date(2026, 10, 25)))
        self.assertEqual(period_for(2026, 1, 26), (date(2025, 12, 26), date(2026, 1, 25)))
        self.assertEqual(period_for(2026, 3, 26), (date(2026, 2, 26), date(2026, 3, 25)))
        self.assertEqual(period_for(2026, 2, 1), (date(2026, 2, 1), date(2026, 2, 28)))
        self.assertEqual(period_for(2024, 2, 1), (date(2024, 2, 1), date(2024, 2, 29)))

    def test_pay_date_is_the_next_pay_day_after_the_period(self):
        self.assertEqual(pay_date_for(date(2026, 10, 25), 5), date(2026, 11, 5))
        self.assertEqual(pay_date_for(date(2026, 10, 25), 28), date(2026, 10, 28))
        self.assertEqual(pay_date_for(date(2026, 12, 25), 5), date(2027, 1, 5))
        self.assertEqual(pay_date_for(date(2026, 10, 31), 25), date(2026, 11, 25))
