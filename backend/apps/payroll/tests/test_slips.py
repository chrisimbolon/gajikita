"""
G8b part 2 (1 Nov 2026) — pay slips, Sisa Pinjaman / Sisa Cuti, the bank transfer list,
and the "absent most of the period" warning.
"""
from datetime import date, datetime, time
from decimal import Decimal
from unittest import mock
from zoneinfo import ZoneInfo

from rest_framework.test import APITestCase

from apps.authentication.models import CustomUser
from apps.employees.models import Employee
from apps.organizations.models import Organization, OrganizationMembership
from apps.payroll.models import PayrollSettings
from apps.sites.models import Shift

WIB = ZoneInfo("Asia/Jakarta")
RUNS = "/api/hr/payroll/runs/"


class SlipTests(APITestCase):
    def setUp(self):
        patcher = mock.patch("django.utils.timezone.now", return_value=datetime(2026, 10, 26, 7, tzinfo=WIB))   # before the 26th shift starts
        patcher.start()
        self.addCleanup(patcher.stop)
        self.org = Organization.objects.create(name="PT Beton Bintan", address="Jl. Panca Marga, Bintan")
        hr = CustomUser.objects.create_user(email="hr@beton.id", password="pass12345!", full_name="Anthony")
        OrganizationMembership.objects.create(organization=self.org, user=hr, role="hr")
        self.client.force_authenticate(hr)
        shift = Shift.objects.create(organization=self.org, name="Pagi", start_time=time(8), end_time=time(17),
                                     working_days="123456")
        PayrollSettings.objects.create(organization=self.org, slip_place="Bintan")
        self.loader = Employee.objects.create(
            organization=self.org, employee_no="B-1", full_name="Sudar", position="Operator Loader",
            join_date=date(2025, 1, 6), default_shift=shift, base_rate=Decimal("4000000"),
            bank_name="BCA", bank_account_no="1234567890", bank_account_name="SUDAR")
        Employee.objects.create(organization=self.org, employee_no="B-2", full_name="Toni", join_date=date(2026, 6, 1),
                                default_shift=shift, base_rate=Decimal("3000000"))

    def make_run(self, month):
        resp = self.client.post(RUNS, {"month": month}, format="json")
        self.assertEqual(resp.status_code, 201, resp.data)
        return resp.data["run"]["id"]

    def test_slips_for_the_whole_run_and_for_one_person(self):
        run_id = self.make_run("2026-11")              # 26 Oct - 25 Nov: nothing has happened yet, so full pay
        data = self.client.get(f"{RUNS}{run_id}/slips/").data
        self.assertEqual((data["company"]["name"], data["company"]["address"], data["place"], data["signer"]),
                         ("PT Beton Bintan", "Jl. Panca Marga, Bintan", "Bintan", "HRD"))
        self.assertEqual((data["run"]["period"], data["run"]["pay_date"], data["run"]["draft"]),
                         ("26 Oktober 2026 - 25 November 2026", "05 Desember 2026", True))
        sudar = next(s for s in data["slips"] if s["employee"]["full_name"] == "Sudar")
        self.assertEqual((sudar["employee"]["position"], sudar["gross"], sudar["net"], sudar["leave_left"]),
                         ("Operator Loader", "4000000.00", "3920000.00", 12))
        self.assertEqual([d["label"] for d in sudar["deductions"]], ["Iuran BPJS Ketenagakerjaan (JHT 2%)"])
        toni = next(s for s in data["slips"] if s["employee"]["full_name"] == "Toni")
        self.assertIsNone(toni["leave_left"])          # under 12 months: no annual leave yet

        self.client.patch(f"{RUNS}{run_id}/lines/{sudar['line_id']}/", {"loan_balance": "1500000"}, format="json")
        one = self.client.get(f"{RUNS}{run_id}/slips/", {"line": sudar["line_id"]}).data["slips"]
        self.assertEqual((len(one), one[0]["loan_balance"]), (1, "1500000.00"))

    def test_bank_transfer_list_only_for_a_locked_run(self):
        run_id = self.make_run("2026-11")
        resp = self.client.get(f"{RUNS}{run_id}/transfers/")
        self.assertEqual(resp.status_code, 400)
        self.client.post(f"{RUNS}{run_id}/lock/", {"action": "lock"}, format="json")
        data = self.client.get(f"{RUNS}{run_id}/transfers/").data
        self.assertEqual((data["ready"], data["problems"], data["total"]), (1, 1, "3920000.00"))
        rows = {r["full_name"]: r for r in data["rows"]}
        self.assertEqual((rows["Sudar"]["bank_name"], rows["Sudar"]["account_no"], rows["Sudar"]["problem"]),
                         ("BCA", "1234567890", ""))
        self.assertEqual(rows["Toni"]["problem"], "No. rekening kosong")

    def test_warning_when_absent_most_of_the_period(self):
        run_id = self.make_run("2026-10")              # 26 Sep - 25 Oct, no attendance at all
        rows = {r["employee"]["full_name"]: r for r in self.client.get(f"{RUNS}{run_id}/").data["rows"]}
        line = self.client.get(f"{RUNS}{run_id}/lines/{rows['Sudar']['id']}/").data["line"]
        self.assertEqual(line["result"]["warnings"][0], "Tidak hadir 25 dari 25 hari kerja di periode ini.")
