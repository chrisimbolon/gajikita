"""
G17-0 (13 Nov 2026): a net pay below zero is shown, warned about first, and blocks locking the run.
Made-up people and amounts. Andi is "tidak wajib absen" for the whole period, so attendance can't
move his pay and the only thing that changes it is a deduction typed into the run.
"""
from datetime import date, datetime, time
from decimal import Decimal
from unittest import mock
from zoneinfo import ZoneInfo

from rest_framework.test import APITestCase

from apps.attendance.models import AttendanceExemption
from apps.authentication.models import CustomUser
from apps.employees.models import Employee
from apps.organizations.models import Organization, OrganizationMembership
from apps.payroll.models import PayRun
from apps.payroll.payrun import NEGATIVE_WARNING, rupiah
from apps.sites.models import Shift

WIB = ZoneInfo("Asia/Jakarta")
RUNS = "/api/hr/payroll/runs/"


class NegativePayGuardTests(APITestCase):
    def setUp(self):
        patcher = mock.patch("django.utils.timezone.now", return_value=datetime(2026, 10, 26, 10, tzinfo=WIB))
        patcher.start()
        self.addCleanup(patcher.stop)
        self.org = Organization.objects.create(name="PT Contoh Minus")
        self.hr = CustomUser.objects.create_user(email="hr@minus.id", password="pass12345!", full_name="HR")
        OrganizationMembership.objects.create(organization=self.org, user=self.hr, role="hr")
        self.client.force_authenticate(self.hr)
        shift = Shift.objects.create(organization=self.org, name="Pagi", start_time=time(8), end_time=time(17),
                                     working_days="123456")
        self.andi = Employee.objects.create(organization=self.org, employee_no="M-1", full_name="Andi Contoh",
                                            join_date=date(2025, 1, 6), default_shift=shift,
                                            base_rate=Decimal("3000000"), bpjs_tk_enrolled=False)
        AttendanceExemption.objects.create(organization=self.org, employee=self.andi, start=date(2026, 1, 1),
                                           reason="Contoh")
        resp = self.client.post(RUNS, {"month": "2026-10"}, format="json")
        self.assertEqual(resp.status_code, 201, resp.data)
        self.run_id = resp.data["run"]["id"]
        self.line_id = self.client.get(f"{RUNS}{self.run_id}/").data["rows"][0]["id"]

    def add_deduction(self, amount):
        resp = self.client.post(f"{RUNS}{self.run_id}/lines/{self.line_id}/items/",
                                {"kind": "deduction", "label": "Kasbon", "amount": amount}, format="json")
        self.assertEqual(resp.status_code, 201, resp.data)
        return resp.data["line"]

    def test_rupiah(self):
        self.assertEqual(rupiah(Decimal("-1108500")), "-1.108.500")
        self.assertEqual(rupiah(Decimal("2479000.00")), "2.479.000")

    def test_negative_net_is_warned_first_and_blocks_locking(self):
        line = self.add_deduction("3500000")                       # 3.000.000 pay - 3.500.000 kasbon
        self.assertEqual(line["net"], "-500000.00")
        self.assertEqual(line["result"]["warnings"][0], NEGATIVE_WARNING.format(net="-500.000"))

        detail = self.client.get(f"{RUNS}{self.run_id}/").data
        self.assertEqual(detail["run"]["negative"], 1)
        self.assertTrue(detail["rows"][0]["negative"])

        resp = self.client.post(f"{RUNS}{self.run_id}/lock/", {"action": "lock"}, format="json")
        self.assertEqual(resp.status_code, 400)
        self.assertIn("gaji bersih minus untuk 1 karyawan (Andi Contoh)", resp.data["message"])
        self.assertEqual(PayRun.objects.get(pk=self.run_id).status, "draft")

    def test_zero_or_more_locks_as_before(self):
        line = self.add_deduction("3000000")                       # exactly zero is allowed to lock
        self.assertEqual(line["net"], "0.00")
        self.assertFalse(any("Gaji bersih minus" in w for w in line["result"]["warnings"]))
        self.assertEqual(self.client.get(f"{RUNS}{self.run_id}/").data["run"]["negative"], 0)
        resp = self.client.post(f"{RUNS}{self.run_id}/lock/", {"action": "lock"}, format="json")
        self.assertEqual(resp.status_code, 200, resp.data)
        self.assertEqual(resp.data["run"]["status"], "locked")
