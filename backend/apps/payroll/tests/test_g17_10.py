"""
G17-10 (18 Nov 2026) — the Lembur page counts the pay period, like the payroll, and says whether the payroll
pays the same overtime. Made-up people.
"""
from datetime import date, datetime, time
from decimal import Decimal
from unittest import mock
from zoneinfo import ZoneInfo

from django.test import SimpleTestCase
from rest_framework.test import APITestCase

from apps.attendance.models import AttendanceDay
from apps.authentication.models import CustomUser
from apps.employees.models import Employee
from apps.organizations.models import Organization, OrganizationMembership
from apps.payroll.views import current_pay_month
from apps.sites.models import Shift

WIB = ZoneInfo("Asia/Jakarta")
URL, RUNS = "/api/hr/overtime/", "/api/hr/payroll/runs/"


class PayMonthTests(SimpleTestCase):
    def test_current_pay_month(self):
        self.assertEqual(current_pay_month(date(2026, 11, 18), 26), date(2026, 11, 1))
        self.assertEqual(current_pay_month(date(2026, 10, 28), 26), date(2026, 11, 1))
        self.assertEqual(current_pay_month(date(2026, 12, 27), 26), date(2027, 1, 1))
        self.assertEqual(current_pay_month(date(2026, 10, 28), 1), date(2026, 10, 1))


class LemburPeriodTests(APITestCase):
    def setUp(self):
        p = mock.patch("django.utils.timezone.now", return_value=datetime(2026, 10, 28, 10, tzinfo=WIB))
        p.start()
        self.addCleanup(p.stop)
        self.org = Organization.objects.create(name="PT Contoh Periode")
        hr = CustomUser.objects.create_user(email="hr@periode.id", password="pass12345!", full_name="HR")
        OrganizationMembership.objects.create(organization=self.org, user=hr, role="hr")
        self.client.force_authenticate(hr)
        self.shift = Shift.objects.create(organization=self.org, name="Pagi", start_time=time(8), end_time=time(17),
                                          working_days="123456")
        self.emp = Employee.objects.create(organization=self.org, employee_no="P-1", full_name="Arif Contoh",
                                           join_date=date(2025, 1, 6), default_shift=self.shift,
                                           base_rate=Decimal("3460000"))
        self.days = {d: AttendanceDay.objects.create(organization=self.org, employee=self.emp, date=d, shift=self.shift,
                                                     decision="approved", overtime_approved_minutes=120)
                     for d in (date(2026, 9, 25), date(2026, 9, 28), date(2026, 10, 23), date(2026, 10, 27))}

    def dates(self, **params):
        d = self.client.get(URL, params).data
        return d, [x["date"] for x in d["employees"][0]["days"]] if d["employees"] else []

    def test_the_pay_period_is_counted(self):
        d, dates = self.dates(month="2026-10", basis="period")
        self.assertEqual((d["basis"], d["start"], d["end"]), ("period", "2026-09-26", "2026-10-25"))
        self.assertEqual(dates, ["2026-09-28", "2026-10-23"])

    def test_without_basis_it_is_the_calendar_month_as_before(self):
        d, dates = self.dates(month="2026-10")
        self.assertEqual((d["basis"], d["start"], d["end"], d["payroll"]), ("calendar", "2026-10-01", "2026-10-31", None))
        self.assertEqual(dates, ["2026-10-23", "2026-10-27"])

    def test_it_opens_on_the_current_pay_period(self):
        d, dates = self.dates(basis="period")                           # 28 Okt -> November (26 Okt - 25 Nov)
        self.assertEqual((d["month"], dates), ("2026-11", ["2026-10-27"]))

    def test_it_says_whether_the_payroll_pays_the_same(self):
        self.assertIsNone(self.dates(month="2026-10", basis="period")[0]["payroll"])      # no run yet
        run = self.client.post(RUNS, {"month": "2026-10"}, format="json").data["run"]
        d = self.dates(month="2026-10", basis="period")[0]
        p = d["payroll"]
        self.assertEqual((p["run"], p["amount"], p["same"]), (run["id"], d["totals"]["amount"], True))
        self.assertGreater(Decimal(p["amount"]), 0)
        AttendanceDay.objects.filter(pk=self.days[date(2026, 10, 23)].pk).update(overtime_approved_minutes=240)
        p = self.dates(month="2026-10", basis="period")[0]["payroll"]                     # not recalculated yet
        self.assertFalse(p["same"])
        self.assertLess(Decimal(p["difference"]), 0)
