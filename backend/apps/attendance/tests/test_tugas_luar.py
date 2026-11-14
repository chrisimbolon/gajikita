"""
G17-3 (14 Nov 2026) — "Tandai tugas luar": HR marks ticked days in Perlu Tinjau as company errands.
Made-up people; the days copy Feny (DKCB, October 2026): late because she went shopping for parts first.
"""
from datetime import date, datetime, time
from decimal import Decimal
from unittest import mock
from zoneinfo import ZoneInfo

from rest_framework.test import APITestCase

from apps.attendance.day_status import Status
from apps.attendance.models import AttendanceDay, AttendanceExemption, ClockEvent
from apps.attendance.review import evaluate
from apps.authentication.models import CustomUser
from apps.employees.models import Employee
from apps.organizations.models import Organization, OrganizationMembership
from apps.sites.models import Shift

WIB = ZoneInfo("Asia/Jakarta")
BULK = "/api/hr/attendance/review/bulk/"
PERIOD = "/api/hr/attendance/review/period/"


class TugasLuarTests(APITestCase):
    def setUp(self):
        patcher = mock.patch("django.utils.timezone.now", return_value=datetime(2026, 10, 26, 10, tzinfo=WIB))
        patcher.start()
        self.addCleanup(patcher.stop)
        self.org = Organization.objects.create(name="PT Contoh Logistik")
        hr = CustomUser.objects.create_user(email="hr@logistik.id", password="pass12345!", full_name="HR")
        OrganizationMembership.objects.create(organization=self.org, user=hr, role="hr")
        self.client.force_authenticate(hr)
        shift = Shift.objects.create(organization=self.org, name="Pagi", start_time=time(8), end_time=time(17),
                                     grace_minutes=5, working_days="123456")
        self.emp = Employee.objects.create(organization=self.org, employee_no="F-1", full_name="Feny Contoh",
                                           join_date=date(2025, 1, 6), default_shift=shift, base_rate=Decimal("3500000"))
        self.days = [self.day(date(2026, 9, 28), 10, 15), self.day(date(2026, 9, 29), 11, 0)]

    def day(self, d, h, m):
        day = AttendanceDay.objects.create(organization=self.org, employee=self.emp, date=d)
        for kind, hh, mm in (("in", h, m), ("out", 17, 5)):
            t = datetime(d.year, d.month, d.day, hh, mm, tzinfo=WIB)
            ClockEvent.objects.create(organization=self.org, day=day, employee=self.emp, kind=kind,
                                      source="fingerprint", occurred_at=t, received_at=t)
        return day

    def test_marked_days_count_as_worked_and_leave_the_queue(self):
        self.assertEqual(evaluate(self.days[0]).late_minutes, 135)
        resp = self.client.post(BULK, {"action": "away", "note": "Belanja alat lori fuso",
                                       "ids": [str(d.pk) for d in self.days]}, format="json")
        self.assertEqual(resp.status_code, 200, resp.data)
        self.assertEqual((resp.data["decided"], resp.data["skipped"]), (2, 0))
        x = AttendanceExemption.objects.get(employee=self.emp, start=date(2026, 9, 28))
        self.assertEqual((x.end, x.reason), (date(2026, 9, 28), "Tugas luar: Belanja alat lori fuso"))
        for d in self.days:
            r = evaluate(AttendanceDay.objects.get(pk=d.pk))
            self.assertEqual((r.status, r.needs_review), (Status.EXEMPT, False))
        self.assertEqual(self.client.get(PERIOD, {"month": "2026-10"}).data["total"], 0)

    def test_the_errand_is_required_and_a_second_mark_is_skipped(self):
        resp = self.client.post(BULK, {"action": "away", "note": " ", "ids": [str(self.days[0].pk)]}, format="json")
        self.assertEqual(resp.status_code, 400)
        AttendanceExemption.objects.create(organization=self.org, employee=self.emp, start=date(2026, 9, 29),
                                           end=date(2026, 9, 29), reason="Sudah ada")
        resp = self.client.post(BULK, {"action": "away", "note": "Belanja", "ids": [str(d.pk) for d in self.days]},
                                format="json")
        self.assertEqual((resp.data["decided"], resp.data["skipped"]), (1, 1))
        self.assertEqual(AttendanceExemption.objects.filter(employee=self.emp).count(), 2)
