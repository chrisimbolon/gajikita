"""G17-9 (18 Nov 2026): the loan form follows HR's book. Made-up people."""
from datetime import date, datetime
from decimal import Decimal
from unittest import mock
from zoneinfo import ZoneInfo

from django.test import SimpleTestCase
from rest_framework.test import APITestCase

from apps.authentication.models import CustomUser
from apps.employees.models import Employee
from apps.organizations.models import Organization, OrganizationMembership
from apps.payroll import loans as L
from apps.payroll.models import EmployeeLoan, PayRunItem

WIB = ZoneInfo("Asia/Jakarta")
RUNS, LOANS = "/api/hr/payroll/runs/", "/api/hr/payroll/loans/"


class PlanTests(SimpleTestCase):
    def test_schedule(self):
        self.assertEqual(L.schedule(Decimal("2500000"), Decimal("300000"), date(2026, 9, 1)),
                         (8, Decimal("100000"), date(2027, 5, 1)))
        self.assertEqual(L.schedule(3000000, 1000000, date(2026, 8, 1)), (3, 0, date(2026, 10, 1)))
        self.assertEqual(L.schedule(500000, 900000, date(2026, 12, 1)), (1, 0, date(2026, 12, 1)))
        self.assertEqual(L.schedule(0, 300000, date(2026, 9, 1)), (0, 0, None))
        self.assertEqual(L.add_months(date(2026, 11, 1), 14), date(2028, 1, 1))

    def test_words(self):
        self.assertEqual(L.plan_text(2500000, 300000, date(2026, 9, 1)),
                         "8× Rp 300.000 + 1× Rp 100.000, lunas Mei 2027")
        self.assertEqual(L.plan_text(3000000, 1000000, date(2026, 8, 1)), "3× Rp 1.000.000, lunas Oktober 2026")
        self.assertEqual(L.plan_text(0, 1, date(2026, 8, 1)), "")


class FormTests(APITestCase):
    def setUp(self):
        p = mock.patch("django.utils.timezone.now", return_value=datetime(2026, 10, 26, 10, tzinfo=WIB))
        p.start()
        self.addCleanup(p.stop)
        self.org = Organization.objects.create(name="PT Contoh Angsuran")
        hr = CustomUser.objects.create_user(email="hr@angsuran.id", password="pass12345!", full_name="HR Angsuran")
        OrganizationMembership.objects.create(organization=self.org, user=hr, role="hr")
        self.client.force_authenticate(hr)
        self.emp = Employee.objects.create(organization=self.org, employee_no="A-1", full_name="Iqbal Contoh",
                                           join_date=date(2025, 1, 6), base_rate=Decimal("2800000"),
                                           bpjs_tk_enrolled=False)
        self.oct = self.client.post(RUNS, {"month": "2026-10"}, format="json").data["run"]["id"]

    def add(self, expect=201, **kw):
        body = {"employee": str(self.emp.pk), "amount": "2200000", "installment": "300000", "start_month": "2026-10",
                "note": ""}
        body.update(kw)
        resp = self.client.post(LOANS, body, format="json")
        self.assertEqual(resp.status_code, expect, resp.data)
        return resp.data

    def test_a_running_loan_keeps_the_book_figure_and_says_when_it_ends(self):
        d = self.add(original_amount="2500000")["loan"]
        self.assertEqual((d["original_amount"], d["amount"], d["remaining"]), ("2500000.00", "2200000.00", "1900000.00"))
        self.assertEqual(d["plan"], "Berikutnya 6× Rp 300.000 + 1× Rp 100.000, lunas Mei 2027")
        self.assertEqual(EmployeeLoan.objects.get().original_amount, Decimal("2500000"))

    def test_the_starting_figure_is_optional_and_checked(self):
        self.assertIsNone(self.add()["loan"]["original_amount"])
        r = self.add(expect=400, original_amount="1000000")
        self.assertIn("tidak boleh lebih kecil", r["message"])
        self.assertEqual(self.add(expect=400, original_amount="abc")["message"], "Jumlah awal / pengajuan tidak valid.")

    def test_a_kasbon_with_what_was_asked(self):
        d = self.add(amount="500000", installment="500000", original_amount="750000")["loan"]
        self.assertTrue(d["kasbon"])
        self.assertEqual((d["original_amount"], d["plan"]), ("750000.00", "Lunas Oktober 2026"))
        self.assertEqual(list(PayRunItem.objects.filter(line__run_id=self.oct, code="pinjaman")
                              .values_list("amount", flat=True)), [Decimal("500000.00")])

    def test_a_loan_starting_later_shows_its_whole_plan(self):
        d = self.add(start_month="2026-12")["loan"]
        self.assertEqual((d["this_month"], d["plan"]), (None, "7× Rp 300.000 + 1× Rp 100.000, lunas Juli 2027"))

    def test_the_list_names_the_open_payroll(self):
        r = self.client.get(LOANS).data
        self.assertEqual((r["open_run"]["month"], r["open_run"]["run"]), ("2026-10", str(self.oct)))
        self.assertEqual([(x["month"], x["locked"]) for x in r["runs"]], [("2026-10", False)])

    def test_the_starting_figure_can_be_corrected(self):
        loan = self.add()["loan"]
        url = f"{LOANS}{loan['id']}/"
        self.assertEqual(self.client.patch(url, {"original_amount": "2500000"}, format="json").data["loan"]["original_amount"],
                         "2500000.00")
        self.assertEqual(self.client.patch(url, {"original_amount": "100"}, format="json").status_code, 400)
        self.assertIsNone(self.client.patch(url, {"original_amount": ""}, format="json").data["loan"]["original_amount"])
