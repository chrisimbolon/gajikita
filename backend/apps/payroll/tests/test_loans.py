"""G13 part 2 (15 Nov 2026): loans that pay themselves off. Made-up people; the shapes copy DKCB's sheets."""
from datetime import date, datetime
from decimal import Decimal
from unittest import mock
from zoneinfo import ZoneInfo

from rest_framework.test import APITestCase

from apps.authentication.models import CustomUser
from apps.employees.models import Employee
from apps.organizations.models import Organization, OrganizationMembership
from apps.payroll.models import EmployeeLoan, PayRun, PayRunItem, PayRunLine

WIB = ZoneInfo("Asia/Jakarta")
RUNS, LOANS = "/api/hr/payroll/runs/", "/api/hr/payroll/loans/"


class LoanTests(APITestCase):
    def setUp(self):
        self.now = mock.patch("django.utils.timezone.now", return_value=datetime(2026, 10, 26, 10, tzinfo=WIB))
        self.now.start()
        self.addCleanup(self.now.stop)
        self.org = Organization.objects.create(name="PT Contoh Pinjaman")
        hr = CustomUser.objects.create_user(email="hr@pinjam.id", password="pass12345!", full_name="HR Pinjam")
        OrganizationMembership.objects.create(organization=self.org, user=hr, role="hr")
        self.client.force_authenticate(hr)
        self.emp = Employee.objects.create(organization=self.org, employee_no="P-1", full_name="Iqbal Contoh",
                                           join_date=date(2025, 1, 6), base_rate=Decimal("2800000"),
                                           bpjs_tk_enrolled=False)
        self.oct = self.client.post(RUNS, {"month": "2026-10"}, format="json").data["run"]["id"]

    def line(self, run_id):
        return PayRunLine.objects.get(run_id=run_id, employee=self.emp)

    def loan_items(self, run_id):
        return list(PayRunItem.objects.filter(line__run_id=run_id, code="pinjaman").values_list("amount", flat=True))

    def add(self, **kw):
        body = {"employee": str(self.emp.pk), "amount": "2200000", "installment": "300000", "start_month": "2026-10",
                "note": "Cicilan Sep"}
        body.update(kw)
        resp = self.client.post(LOANS, body, format="json")
        self.assertEqual(resp.status_code, 201, resp.data)
        return resp.data

    def next_month(self, month="2026-11", when=datetime(2026, 11, 26, 10, tzinfo=WIB)):
        with mock.patch("django.utils.timezone.now", return_value=when):
            return self.client.post(RUNS, {"month": month}, format="json").data["run"]["id"]

    def lock(self, run_id):                                # the state that matters here (no attendance in these tests)
        PayRun.objects.filter(pk=run_id).update(status=PayRun.Status.LOCKED)

    def test_an_instalment_is_deducted_and_the_balance_shown(self):
        before = self.line(self.oct).net
        d = self.add()
        self.assertEqual(self.loan_items(self.oct), [Decimal("300000.00")])
        line = self.line(self.oct)
        self.assertEqual((line.net, line.loan_balance), (before - Decimal("300000"), Decimal("1900000.00")))
        self.assertEqual((d["loan"]["remaining"], d["loan"]["state"]), ("1900000.00", "active"))

    def test_it_carries_on_next_month_and_stops_when_paid(self):
        self.add(amount="400000")                          # 300.000 + 100.000
        self.lock(self.oct)
        nov = self.next_month()
        self.assertEqual(self.loan_items(nov), [Decimal("100000.00")])
        self.assertEqual(self.line(nov).loan_balance, Decimal("0.00"))
        self.lock(nov)
        dec = self.next_month("2026-12", datetime(2026, 12, 26, 10, tzinfo=WIB))
        self.assertEqual(self.loan_items(dec), [])
        loan = self.client.get(LOANS, {"show": "all"}).data["loans"][0]
        self.assertEqual((loan["state_label"], loan["paid"]), ("Lunas", "400000.00"))

    def test_kasbon_and_a_typed_deduction_is_taken_over(self):
        line = self.line(self.oct)
        PayRunItem.objects.create(organization=self.org, line=line, kind="deduction", code="pinjaman",
                                  label="Pinjaman / kasbon", amount=Decimal("500000"))
        d = self.add(amount="500000", installment="500000", note="")
        self.assertTrue(d["adopted"] and d["loan"]["kasbon"])
        self.assertEqual(self.loan_items(self.oct), [Decimal("500000.00")])      # not twice

    def test_skip_this_month_then_cancel(self):
        d = self.add()
        url = f"{LOANS}{d['loan']['id']}/"
        resp = self.client.patch(url, {"run": self.oct, "this_month": "0"}, format="json")
        self.assertEqual((resp.status_code, self.loan_items(self.oct)), (200, [Decimal("0.00")]))
        self.client.post(f"{RUNS}{self.oct}/recalculate/", {}, format="json")
        self.assertEqual(self.loan_items(self.oct), [Decimal("0.00")])              # the skip survives a recalculation
        self.assertEqual(self.client.patch(url, {"run": self.oct, "this_month": "9000000"}, format="json").status_code, 400)
        self.client.patch(url, {"action": "cancel"}, format="json")
        self.assertEqual(self.loan_items(self.oct), [])
        self.assertEqual(EmployeeLoan.objects.get().status, "cancelled")

    def test_refusals(self):
        bad = lambda **kw: self.client.post(LOANS, {"employee": str(self.emp.pk), "amount": "1000000",
                                                    "installment": "500000", "start_month": "2026-10", **kw},
                                            format="json")
        self.assertEqual(bad(amount="0").status_code, 400)
        self.assertEqual(bad(installment="").status_code, 400)
        self.assertEqual(bad(start_month="").status_code, 400)
        self.lock(self.oct)
        resp = bad()
        self.assertEqual(resp.status_code, 400)
        self.assertIn("sudah dikunci", resp.data["message"])


class DeleteGuardTests(APITestCase):
    def setUp(self):
        mock.patch("django.utils.timezone.now", return_value=datetime(2026, 10, 26, 10, tzinfo=WIB)).start()
        self.addCleanup(mock.patch.stopall)
        org = Organization.objects.create(name="PT Contoh Hapus")
        hr = CustomUser.objects.create_user(email="hr@hapus.id", password="pass12345!", full_name="HR Hapus")
        OrganizationMembership.objects.create(organization=org, user=hr, role="hr")
        self.client.force_authenticate(hr)
        emp = Employee.objects.create(organization=org, employee_no="H-1", full_name="Andi Contoh",
                                      join_date=date(2025, 1, 6), base_rate=Decimal("3000000"))
        self.run = self.client.post(RUNS, {"month": "2026-10"}, format="json").data["run"]["id"]
        PayRunItem.objects.create(organization=org, line=PayRunLine.objects.get(employee=emp), kind="earning",
                                  code="kubikasi", label="Kubikasi", amount=Decimal("462000"))

    def test_typed_work_needs_the_word(self):
        summary = self.client.get(f"{RUNS}{self.run}/").data["run"]
        self.assertEqual((summary["typed_items"], summary["corrections"]), (1, 0))
        resp = self.client.delete(f"{RUNS}{self.run}/")
        self.assertEqual(resp.status_code, 400)
        self.assertIn("1 item yang diketik", resp.data["message"])
        self.assertTrue(PayRun.objects.filter(pk=self.run).exists())
        self.assertEqual(self.client.delete(f"{RUNS}{self.run}/?confirm=HAPUS").status_code, 200)
