"""
G11c (5 Nov 2026) — the day panel and the Lembur page price overtime the way payroll pays it:
with "Tarif tetap perusahaan" that is rounded hours x the hourly rate, or the rest-day rate,
with the PP 35 amount shown beside it.
"""
from datetime import date, datetime, time
from decimal import Decimal
from unittest import mock
from zoneinfo import ZoneInfo

from rest_framework.test import APITestCase

from apps.attendance.models import AttendanceDay, ClockEvent
from apps.authentication.models import CustomUser
from apps.employees.models import Employee
from apps.organizations.models import Organization, OrganizationMembership
from apps.payroll.models import PayrollSettings
from apps.sites.models import Shift

WIB = ZoneInfo("Asia/Jakarta")


class FlatOvertimePriceTests(APITestCase):
    def setUp(self):
        patcher = mock.patch("django.utils.timezone.now", return_value=datetime(2026, 11, 5, 10, tzinfo=WIB))
        patcher.start()
        self.addCleanup(patcher.stop)
        self.org = Organization.objects.create(name="PT Beton Bintan")
        hr = CustomUser.objects.create_user(email="hr@beton.id", password="pass12345!", full_name="Anthony")
        OrganizationMembership.objects.create(organization=self.org, user=hr, role="hr")
        self.client.force_authenticate(hr)
        PayrollSettings.objects.create(organization=self.org, overtime_mode="flat", overtime_rounding="nearest_half",
                                       flat_overtime_hour=Decimal("12500"), flat_rest_day=Decimal("120000"))
        self.shift = Shift.objects.create(organization=self.org, name="Pagi", start_time=time(8), end_time=time(17),
                                          grace_minutes=5, working_days="123456")
        self.emp = Employee.objects.create(organization=self.org, employee_no="B-1", full_name="Bayu", join_date=date(2025, 1, 6),
                                           default_shift=self.shift, base_rate=Decimal("4000000"))

    def day(self, d, inn, out, **kw):
        day = AttendanceDay.objects.create(organization=self.org, employee=self.emp, date=d, shift=self.shift, **kw)
        for kind, (h, m) in (("in", inn), ("out", out)):
            t = datetime(d.year, d.month, d.day, h, m, tzinfo=WIB)
            ClockEvent.objects.create(organization=self.org, day=day, employee=self.emp, kind=kind, source="fingerprint",
                                      occurred_at=t, received_at=t)
        return day

    def pay(self, day):
        return self.client.get(f"/api/hr/attendance/days/{day.id}/").data["day"]["overtime_pay"]

    def test_working_day_is_rounded_hours_times_the_rate(self):
        p = self.pay(self.day(date(2026, 10, 27), (7, 55), (18, 40)))          # 100 minutes -> 1.5 h
        self.assertEqual((p["mode"], p["rounded_minutes"], p["amount"], p["estimate"]), ("flat", 90, "18750", True))
        self.assertGreater(Decimal(p["pp35_amount"]), Decimal(p["amount"]))
        self.assertEqual(Decimal(p["gap"]), Decimal(p["pp35_amount"]) - Decimal("18750"))

    def test_rest_day_is_the_rest_day_rate(self):
        p = self.pay(self.day(date(2026, 8, 30), (7, 56), (14, 0)))             # Sunday, 364 minutes
        self.assertEqual((p["rest_day"], p["amount"], p["rate"]), (True, "120000", "120000"))
        self.assertGreater(Decimal(p["pp35_amount"]), Decimal("120000"))

    def test_lembur_page_uses_the_same_price(self):
        self.day(date(2026, 10, 27), (7, 55), (18, 40), decision="approved", overtime_approved_minutes=100)
        self.day(date(2026, 10, 25), (8, 0), (14, 0), decision="approved", overtime_approved_minutes=360)
        d = self.client.get("/api/hr/overtime/", {"month": "2026-10"}).data
        self.assertEqual(d["totals"]["amount"], "138750")                         # 18.750 + 120.000
        self.assertEqual(sorted(x["mode"] for x in d["employees"][0]["days"]), ["flat", "flat"])

    def test_not_eligible_is_not_paid(self):
        self.emp.overtime_eligible = False
        self.emp.save()
        p = self.pay(self.day(date(2026, 10, 27), (7, 55), (18, 40)))
        self.assertIn("not_paid", p)
