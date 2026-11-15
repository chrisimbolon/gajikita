"""G13 part 1 (15 Nov 2026): manual pay-run items for everyone in one table. Made-up people."""
from datetime import date, datetime
from decimal import Decimal
from unittest import mock
from zoneinfo import ZoneInfo

from rest_framework.test import APITestCase

from apps.authentication.models import CustomUser
from apps.core.models import AuditEntry
from apps.employees.models import Employee
from apps.organizations.models import Organization, OrganizationMembership
from apps.payroll.models import PayRun, PayRunItem, PayRunLine
from apps.payroll.r1_compare import seegaji_amounts

WIB = ZoneInfo("Asia/Jakarta")
RUNS = "/api/hr/payroll/runs/"


class ItemGridTests(APITestCase):
    def setUp(self):
        patcher = mock.patch("django.utils.timezone.now", return_value=datetime(2026, 10, 26, 10, tzinfo=WIB))
        patcher.start()
        self.addCleanup(patcher.stop)
        self.org = Organization.objects.create(name="PT Contoh Item")
        hr = CustomUser.objects.create_user(email="hr@item.id", password="pass12345!", full_name="HR Item")
        OrganizationMembership.objects.create(organization=self.org, user=hr, role="hr")
        self.client.force_authenticate(hr)
        for no, name in (("I-1", "Andi Contoh"), ("I-2", "Budi Contoh")):
            Employee.objects.create(organization=self.org, employee_no=no, full_name=name, join_date=date(2025, 1, 6),
                                    base_rate=Decimal("3000000"), bpjs_tk_enrolled=False)
        self.run = self.client.post(RUNS, {"month": "2026-10"}, format="json").data["run"]
        self.url = f"{RUNS}{self.run['id']}/items/grid/"
        rows = self.client.get(self.url).data["rows"]
        self.andi, self.budi = rows[0]["line"], rows[1]["line"]

    def save(self, status=200, **body):
        resp = self.client.post(self.url, body, format="json")
        self.assertEqual(resp.status_code, status, resp.data)
        return resp.data

    def net(self, line):
        return PayRunLine.objects.get(pk=line).net

    def test_the_standard_columns(self):
        g = self.client.get(self.url).data
        self.assertEqual([c["code"] for c in g["columns"]],
                         ["insentif_bpjs_kesehatan", "kubikasi", "insentif_lainnya", "pinjaman", "potongan_lainnya"])
        self.assertEqual([r["employee"]["full_name"] for r in g["rows"]], ["Andi Contoh", "Budi Contoh"])

    def test_typing_adds_items_and_recalculates(self):
        before = self.net(self.andi)
        g = self.save(cells=[{"line": self.andi, "code": "insentif_bpjs_kesehatan", "amount": "35000"},
                             {"line": self.andi, "code": "pinjaman", "amount": "500.000"},
                             {"line": self.budi, "code": "kubikasi", "amount": "0"}])            # nothing to remove
        self.assertEqual((g["changed"], g["recalculated"]), (2, 1))
        self.assertEqual(self.net(self.andi), before + Decimal("35000") - Decimal("500000"))
        self.assertEqual(g["rows"][0]["cells"], {"insentif_bpjs_kesehatan": "35000.00", "pinjaman": "500000.00"})
        amounts = seegaji_amounts(PayRunLine.objects.get(pk=self.andi).result)                  # R1 understands them
        self.assertEqual((amounts["bpjs_incentive"], amounts["loan"]), (Decimal("35000"), Decimal("500000")))
        self.assertEqual(AuditEntry.objects.filter(action="payroll.item_grid").count(), 2)

    def test_change_and_empty_removes(self):
        self.save(cells=[{"line": self.andi, "code": "kubikasi", "amount": "462000"}])
        self.save(cells=[{"line": self.andi, "code": "kubikasi", "amount": "500000"}])
        self.assertEqual(PayRunItem.objects.get(line_id=self.andi, code="kubikasi").amount, Decimal("500000"))
        self.save(cells=[{"line": self.andi, "code": "kubikasi", "amount": ""}])
        self.assertFalse(PayRunItem.objects.filter(line_id=self.andi).exists())

    def test_every_month_and_a_new_column(self):
        self.save(cells=[{"line": self.andi, "code": "insentif_bpjs_kesehatan", "amount": "35000"},
                         {"line": self.budi, "code": "sepatu_safety", "amount": "241625"}],
                  columns=[{"code": "insentif_bpjs_kesehatan", "recurring": True},
                           {"code": "sepatu_safety", "label": "Sepatu safety", "kind": "deduction"}])
        self.assertTrue(PayRunItem.objects.get(code="insentif_bpjs_kesehatan").recurring)
        g = self.client.get(self.url).data
        col = next(c for c in g["columns"] if c["code"] == "sepatu_safety")
        self.assertEqual((col["label"], col["kind"], col["recurring"]), ("Sepatu safety", "deduction", False))
        self.assertTrue(next(c for c in g["columns"] if c["code"] == "insentif_bpjs_kesehatan")["recurring"])

    def test_loan_balance_and_refusals(self):
        g = self.save(loan_balance=[{"line": self.andi, "value": "1900000"}])
        self.assertEqual(g["rows"][0]["loan_balance"], "1900000.00")
        self.save(loan_balance=[{"line": self.andi, "value": None}])
        self.assertIsNone(PayRunLine.objects.get(pk=self.andi).loan_balance)
        bad = self.save(status=400, cells=[{"line": self.andi, "code": "kubikasi", "amount": "-5"}])
        self.assertIn("jumlah tidak valid", bad["message"])
        self.save(status=400, cells=[{"line": self.andi, "code": "tidak_ada", "amount": "5"}])
        self.save(status=400, columns=[{"code": "baru", "label": "", "kind": "earning"}])

    def test_two_items_with_one_code_stay_in_the_slip_panel(self):
        line = PayRunLine.objects.get(pk=self.andi)
        for amount in ("100000", "200000"):
            PayRunItem.objects.create(organization=self.org, line=line, kind="earning", code="kubikasi",
                                      label="Kubikasi", amount=Decimal(amount))
        g = self.client.get(self.url).data
        self.assertEqual((g["rows"][0]["cells"]["kubikasi"], g["rows"][0]["multi"]), ("300000.00", ["kubikasi"]))
        bad = self.save(status=400, cells=[{"line": self.andi, "code": "kubikasi", "amount": "5"}])
        self.assertIn("lebih dari satu item", bad["message"])

    def test_a_locked_run_refuses(self):
        PayRun.objects.filter(pk=self.run["id"]).update(status=PayRun.Status.LOCKED)
        self.assertTrue(self.client.get(self.url).data["run"]["locked"])
        self.save(status=400, cells=[{"line": self.andi, "code": "kubikasi", "amount": "5"}])
