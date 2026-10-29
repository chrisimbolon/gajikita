"""
G6 (28 Oct 2026) — GET /api/hr/summary/, the Ringkasan dashboard in one call.
Its numbers must match the Absensi, Perlu Tinjau and Lembur pages.
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
TODAY = date(2026, 10, 28)          # a Wednesday
URL = "/api/hr/summary/"


def at(h, m=0, d=TODAY):
    return datetime(d.year, d.month, d.day, h, m, tzinfo=WIB)


class SummaryTests(APITestCase):
    def setUp(self):
        patcher = mock.patch("django.utils.timezone.now", return_value=at(10, 0))
        patcher.start()
        self.addCleanup(patcher.stop)
        self.org = Organization.objects.create(name="PT Tol Bersih")
        self.hr = CustomUser.objects.create_user(email="hr@tol.id", password="pass12345!", full_name="Anthony")
        OrganizationMembership.objects.create(organization=self.org, user=self.hr, role="hr")
        self.client.force_authenticate(self.hr)
        self.gate = Site.objects.create(organization=self.org, name="Gerbang Tol KM 21")
        Site.objects.create(organization=self.org, name="Proyek Lama", is_active=False)
        self.shift = Shift.objects.create(organization=self.org, name="Pagi", start_time=time(8), end_time=time(17),
                                          working_days="123456")
        self.emps = [Employee.objects.create(organization=self.org, employee_no=f"T-{i}", full_name=name,
                                             join_date=date(2026, 1, 5), default_shift=self.shift,
                                             base_rate=Decimal("4690000"), fixed_allowance=Decimal("500000"))
                     for i, name in enumerate(["Andi", "Budi", "Citra"])]
        self._tap(self.emps[0], TODAY, ("in", at(7, 52)))                    # working, on time
        self._tap(self.emps[1], TODAY, ("in", at(8, 30)))                    # late: needs review
        # Citra: nothing yet -> absent at 10:00
        yesterday = date(2026, 10, 27)
        day = self._tap(self.emps[0], yesterday, ("in", at(8, d=yesterday)), ("out", at(20, d=yesterday)))
        AttendanceDay.objects.filter(pk=day.pk).update(decision="approved", overtime_approved_minutes=180)

    def _tap(self, emp, d, *taps):
        day = AttendanceDay.objects.create(organization=self.org, employee=emp, date=d, shift=self.shift)
        for kind, when in taps:
            ClockEvent.objects.create(organization=self.org, day=day, employee=emp, kind=kind, site=self.gate,
                                      occurred_at=when, received_at=when)
        return day

    def test_the_whole_dashboard_in_one_call(self):
        resp = self.client.get(URL)
        self.assertEqual(resp.status_code, 200, resp.data)
        d = resp.data
        self.assertEqual((d["user_name"], d["date"], d["employees_active"], d["sites_active"]),
                         ("Anthony", "2026-10-28", 3, 1))
        self.assertEqual((d["counters"]["late"], d["counters"]["absent"], d["counters"]["working"]), (1, 1, 2))
        self.assertEqual(d["present"], 2)
        self.assertEqual(d["review"]["count"], 1)
        self.assertEqual(d["review"]["summary"], [{"label": "Terlambat", "count": 1}])

    def test_problems_come_first_in_todays_list(self):
        names = [r["employee"]["full_name"] for r in self.client.get(URL).data["today"]]
        self.assertEqual(names, ["Budi", "Citra", "Andi"])

    def test_overtime_matches_the_lembur_page(self):
        ot = self.client.get(URL).data["overtime"]
        lembur = self.client.get("/api/hr/overtime/", {"month": "2026-10"}).data
        self.assertEqual((ot["month"], ot["amount"], ot["minutes"], ot["people"]), ("2026-10", "165000", 180, 1))
        self.assertEqual(ot["amount"], lembur["totals"]["amount"])
        self.assertEqual(ot["sites"], [{"site": "Gerbang Tol KM 21", "minutes": 180, "amount": "165000", "share": 100}])

    def test_workers_cannot_see_it(self):
        self.client.force_authenticate(CustomUser.objects.create_user(email="w@tol.id", password="pass12345!",
                                                                      full_name="Worker", role="employee"))
        self.assertEqual(self.client.get(URL).status_code, 403)
