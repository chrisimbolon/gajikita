"""
G4a (28 Oct 2026) — overtime in rupiah through the API: the monthly summary
(per person, per site, PP 35 warnings) and the estimate on HR's day panel.
"""
from datetime import date, datetime, time
from decimal import Decimal
from unittest import mock
from zoneinfo import ZoneInfo

from apps.attendance.models import AttendanceDay, ClockEvent
from apps.authentication.models import CustomUser
from apps.employees.models import Employee
from apps.organizations.models import Organization, OrganizationMembership
from apps.sites.models import Shift, Site
from rest_framework.test import APITestCase

WIB = ZoneInfo("Asia/Jakarta")
URL = "/api/hr/overtime/"


def at(d, h, m=0):
    return datetime(d.year, d.month, d.day, h, m, tzinfo=WIB)


class OvertimeApiTests(APITestCase):
    def setUp(self):
        patcher = mock.patch("django.utils.timezone.now", return_value=at(date(2026, 10, 31), 12))
        patcher.start()
        self.addCleanup(patcher.stop)
        self.org = Organization.objects.create(name="PT Tol Bersih")
        hr = CustomUser.objects.create_user(email="hr@tol.id", password="pass12345!", full_name="HR")
        OrganizationMembership.objects.create(organization=self.org, user=hr, role="hr")
        self.client.force_authenticate(hr)
        self.gate = Site.objects.create(organization=self.org, name="Gerbang Tol Cikarang")
        self.road = Site.objects.create(organization=self.org, name="Ruas KM 30-45", kind=Site.Kind.MOVING)
        self.shift = Shift.objects.create(organization=self.org, name="Pagi", start_time=time(8), end_time=time(17),
                                          working_days="123456")
        # Rp 4.690.000 + Rp 500.000 fixed allowance = Rp 5.190.000 -> Rp 30.000 an hour
        self.andi = Employee.objects.create(organization=self.org, employee_no="T-1", full_name="Andi",
                                            join_date=date(2026, 1, 5), default_shift=self.shift,
                                            base_rate=Decimal("4690000"), fixed_allowance=Decimal("500000"))

    def _day(self, emp, d, out_h, approved, site=None, decision="approved"):
        day = AttendanceDay.objects.create(organization=self.org, employee=emp, date=d, shift=self.shift,
                                           decision=decision, overtime_approved_minutes=approved)
        for kind, when in (("in", at(d, 8)), ("out", at(d, out_h))):
            ClockEvent.objects.create(organization=self.org, day=day, employee=emp, kind=kind, site=site or self.gate,
                                      occurred_at=when, received_at=when)
        return day

    def test_month_summary_in_rupiah(self):
        self._day(self.andi, date(2026, 10, 27), 20, 180)                         # Tue, 3 h: 165.000
        self._day(self.andi, date(2026, 11, 1), 17, 540, site=self.road)          # Sun (rest day), 9 h: 630.000 (November)
        self._day(self.andi, date(2026, 10, 25), 17, 540, site=self.road)         # Sun, 9 h: 630.000
        resp = self.client.get(URL, {"month": "2026-10"})
        self.assertEqual(resp.status_code, 200, resp.data)
        andi = resp.data["employees"][0]
        self.assertEqual((andi["minutes"], andi["amount"], andi["hourly_rate"]), (720, "795000", "30000"))
        self.assertEqual(resp.data["totals"]["amount"], "795000")
        self.assertEqual({s["site"]: s["amount"] for s in resp.data["sites"]},
                         {"Gerbang Tol Cikarang": "165000", "Ruas KM 30-45": "630000"})
        sunday = next(d for d in andi["days"] if d["date"] == "2026-10-25")
        self.assertTrue(sunday["rest_day"])
        self.assertEqual([l["multiplier"] for l in sunday["lines"]], ["2", "3", "4"])

    def test_only_approved_overtime_counts(self):
        self._day(self.andi, date(2026, 10, 27), 20, 180, decision="")
        self.assertEqual(self.client.get(URL, {"month": "2026-10"}).data["employees"], [])

    def test_daily_worker_and_week_warning(self):
        budi = Employee.objects.create(organization=self.org, employee_no="T-2", full_name="Budi",
                                       join_date=date(2026, 1, 5), default_shift=self.shift, pay_type="daily",
                                       base_rate=Decimal("207600"))                # x25 = 5.190.000 -> 30.000/h
        for i in range(5):                                                          # Mon 26 - Fri 30, 4 h each
            self._day(budi, date(2026, 10, 26 + i), 21, 240)
        row = self.client.get(URL, {"month": "2026-10"}).data["employees"][0]
        self.assertEqual(row["hourly_rate"], "30000")
        self.assertEqual(row["amount"], str(5 * (45000 + 180000)))
        self.assertTrue(any("18 jam per minggu" in w for w in row["warnings"]))

    def test_not_eligible_is_listed_but_not_paid(self):
        Employee.objects.filter(pk=self.andi.pk).update(overtime_eligible=False)
        self._day(self.andi, date(2026, 10, 27), 20, 180)
        row = self.client.get(URL, {"month": "2026-10"}).data["employees"][0]
        self.assertEqual(row["amount"], "0")
        self.assertIn("Tidak berhak", row["not_paid"])

    def test_day_panel_shows_the_estimate_then_the_approved_pay(self):
        day = self._day(self.andi, date(2026, 10, 27), 20, None, decision="")
        detail = self.client.get(f"/api/hr/attendance/days/{day.id}/").data["day"]
        self.assertEqual((detail["overtime_pay"]["amount"], detail["overtime_pay"]["estimate"]), ("165000", True))
        resp = self.client.post(f"/api/hr/attendance/days/{day.id}/decide/", {"action": "approve", "overtime_minutes": 60},
                                format="json")
        self.assertEqual((resp.data["day"]["overtime_pay"]["amount"], resp.data["day"]["overtime_pay"]["estimate"]),
                         ("45000", False))

    def test_other_companies_are_not_counted(self):
        other = Organization.objects.create(name="PT Lain")
        stranger = Employee.objects.create(organization=other, employee_no="X", full_name="X", join_date=date(2026, 1, 5),
                                           base_rate=Decimal("5190000"))
        AttendanceDay.objects.create(organization=other, employee=stranger, date=date(2026, 10, 27),
                                     decision="approved", overtime_approved_minutes=60)
        self.assertEqual(self.client.get(URL, {"month": "2026-10"}).data["employees"], [])
