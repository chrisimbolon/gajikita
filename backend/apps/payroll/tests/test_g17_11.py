"""G17-11 (19 Nov 2026): "Ubah" on a running loan, with its guards. Made-up people."""
from datetime import date, datetime
from decimal import Decimal
from unittest import mock
from zoneinfo import ZoneInfo

from rest_framework.test import APITestCase

from apps.authentication.models import CustomUser
from apps.core.models import AuditEntry
from apps.employees.models import Employee
from apps.organizations.models import Organization, OrganizationMembership
from apps.payroll.models import EmployeeLoan, PayRun, PayRunItem

WIB = ZoneInfo("Asia/Jakarta")
RUNS, LOANS = "/api/hr/payroll/runs/", "/api/hr/payroll/loans/"


class LoanEditTests(APITestCase):
    def setUp(self):
        p = mock.patch("django.utils.timezone.now", return_value=datetime(2026, 10, 26, 10, tzinfo=WIB))
        p.start()
        self.addCleanup(p.stop)
        self.org = Organization.objects.create(name="PT Contoh Ubah Pinjaman")
        hr = CustomUser.objects.create_user(email="hr@ubah.id", password="pass12345!", full_name="HR Ubah")
        OrganizationMembership.objects.create(organization=self.org, user=hr, role="hr")
        self.client.force_authenticate(hr)
        self.emp = Employee.objects.create(organization=self.org, employee_no="U-1", full_name="Iqbal Contoh",
                                           join_date=date(2025, 1, 6), base_rate=Decimal("2800000"),
                                           bpjs_tk_enrolled=False)
        self.oct = self.client.post(RUNS, {"month": "2026-10"}, format="json").data["run"]["id"]

    def add(self, **kw):
        body = {"employee": str(self.emp.pk), "amount": "2200000", "installment": "300000", "start_month": "2026-10"}
        body.update(kw)
        r = self.client.post(LOANS, body, format="json")
        self.assertEqual(r.status_code, 201, r.data)
        return r.data["loan"]["id"]

    def patch(self, loan_id, expect=200, **body):
        r = self.client.patch(f"{LOANS}{loan_id}/", body, format="json")
        self.assertEqual(r.status_code, expect, r.data)
        return r.data

    def oct_items(self):
        return list(PayRunItem.objects.filter(line__run_id=self.oct, code="pinjaman").values_list("amount", flat=True))

    def test_a_wrong_first_month_is_moved(self):                          # the Iqbal case
        loan = self.add(start_month="2026-11")
        self.assertEqual(self.oct_items(), [])
        d = self.patch(loan, start_month="2026-10")["loan"]
        self.assertEqual((self.oct_items(), d["start_month"], d["remaining"]), ([Decimal("300000.00")], "2026-10", "1900000.00"))
        self.assertIn("mulai November 2026 -> Oktober 2026",
                      AuditEntry.objects.filter(action="payroll.loan_update").latest("created_at").summary)

    def test_the_monthly_amount_follows_unless_this_month_was_typed(self):
        loan = self.add()
        self.patch(loan, installment="250000")
        self.assertEqual(self.oct_items(), [Decimal("250000.00")])
        self.patch(loan, run=self.oct, this_month="0")                     # HR: tunda this month
        self.patch(loan, installment="200000")
        self.assertEqual(self.oct_items(), [Decimal("0.00")])              # the typed 0 is kept

    def test_sisa_and_starting_figure(self):
        loan = self.add(original_amount="2500000")
        d = self.patch(loan, amount="2000000")["loan"]
        self.assertEqual((d["amount"], d["remaining"]), ("2000000.00", "1700000.00"))
        r = self.patch(loan, expect=400, amount="2600000")                  # above the starting figure
        self.assertIn("tidak boleh lebih kecil", r["message"])
        d = self.patch(loan, amount="2600000", original_amount="")["loan"]   # both at once: fine
        self.assertEqual((d["amount"], d["original_amount"]), ("2600000.00", None))

    def test_a_kasbon_stays_whole(self):
        loan = self.add(amount="500000", installment="500000")
        d = self.patch(loan, amount="600000", installment="100000")["loan"]  # installment ignored for a kasbon
        self.assertEqual((d["kasbon"], d["installment"], self.oct_items()), (True, "600000.00", [Decimal("600000.00")]))

    def test_locked_payrolls_are_guarded(self):
        loan = self.add()
        PayRun.objects.filter(pk=self.oct).update(status=PayRun.Status.LOCKED)
        r = self.patch(loan, expect=400, amount="200000")
        self.assertIn("Rp 300.000", r["message"])
        r = self.patch(loan, expect=400, start_month="2026-11")
        self.assertIn("tidak bisa diubah", r["message"])
        self.patch(loan, amount="1500000")                                   # above what was taken: fine
        self.assertEqual(self.oct_items(), [Decimal("300000.00")])          # the locked run never changes

    def test_a_stopped_loan_cannot_be_changed(self):
        loan = self.add()
        self.patch(loan, action="cancel")
        self.assertIn("sudah dihentikan", self.patch(loan, expect=400, note="x")["message"])
        self.assertEqual(EmployeeLoan.objects.get().note, "")

    def test_nothing_is_saved_when_one_field_is_wrong(self):
        loan = self.add()
        self.patch(loan, expect=400, installment="200000", amount="abc")
        l = EmployeeLoan.objects.get()
        self.assertEqual((l.installment, l.amount), (Decimal("300000.00"), Decimal("2200000.00")))
