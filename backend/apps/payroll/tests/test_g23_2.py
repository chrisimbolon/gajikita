"""
G23-2 (28 Nov 2026) — PPh 21 "ditanggung perusahaan tanpa gross-up" per employee (Anthony, 27 Nov visit, A6):
the company pays the TER tax on the bruto as it is; nothing is added to bruto, nothing is taken from the pay.
The tax is an employer line (pph21_company), counted as paid for the year. Gross-up stays the default for
everyone already ticked "PPh 21 ditanggung perusahaan". Made-up people and amounts.
"""
from datetime import date
from decimal import Decimal as D
from types import SimpleNamespace as NS

from django.test import SimpleTestCase

from apps.employees.models import Employee
from apps.payroll import payrun
from apps.payroll import pph21 as P
from apps.payroll import pph21_year as Y
from apps.payroll.models import PayRun, PayRunLine, PayrollSettings, Pph21Opening
from apps.payroll.tests import test_payrun as base


def lines(res, kind):
    return {x["code"]: D(x["amount"]) for x in res[kind]}


class PureTests(SimpleTestCase):
    def test_the_three_ways(self):
        mode = lambda **kw: P.tax_mode(NS(**kw))
        self.assertEqual(mode(pph21_by_company=False, pph21_gross_up=False), P.WITHHELD)
        self.assertEqual(mode(pph21_by_company=True, pph21_gross_up=True), P.GROSS_UP)
        self.assertEqual(mode(pph21_by_company=True, pph21_gross_up=False), P.BORNE)
        self.assertEqual(mode(pph21_by_company=True), P.GROSS_UP)                    # older objects: as before

    def test_a_book_like_month(self):
        # 10.000.000 + JKK 0,89% + JKM 0,30% = 10.119.000, TER B (K/1): 1,5%
        self.assertEqual(P.monthly_pph(D("10119000"), "K/1"), (D("0.015"), D("151785")))       # without gross-up
        self.assertEqual(P.gross_up(D("10119000"), "K/1"), (D("0.015"), D("154096")))          # with gross-up

    def test_paid_by_the_company_counts_as_paid(self):
        res = {"deductions": [], "employer": [{"code": "jkk", "amount": "89000"},
                                              {"code": "pph21_company", "amount": "151785"}]}
        self.assertEqual(Y.withheld_from_slip(res), D("151785"))
        self.assertIsNone(Y.withheld_from_slip({"deductions": [], "employer": [{"code": "jkk", "amount": "1"}]}))
        self.assertEqual(P.bruto_from_slip({"earnings": [{"code": "base", "amount": "100"}], "deductions": [],
                                            "employer": [{"code": "pph21_company", "amount": "5"}]}).total, D("100"))


class BorneTests(base.PayRunTests):
    def setUp(self):
        super().setUp()
        Employee.objects.filter(pk=self.andi.pk).update(base_rate=D("10000000"))
        PayrollSettings.objects.filter(organization=self.org).update(pph21_tax_month="paid")

    def on(self):
        PayrollSettings.objects.filter(organization=self.org).update(pph21_enabled=True)

    def recalc(self, run_id):
        line = PayRunLine.objects.select_related("employee", "run").get(run_id=run_id, employee=self.andi)
        line = payrun.calculate_line(line, PayrollSettings.for_org(self.org))
        line.save()                                                                  # as "Hitung ulang" does
        return line

    def test_borne_is_not_on_the_pay(self):
        run = self.make_run()
        before = self.line(run["id"], "Andi")
        Employee.objects.filter(pk=self.andi.pk).update(pph21_by_company=True, pph21_gross_up=False)
        self.on()
        slip = self.recalc(run["id"])
        res = slip.result
        self.assertNotIn("pph21_allowance", lines(res, "earnings"))
        self.assertNotIn("pph21", lines(res, "deductions"))
        paid = lines(res, "employer")["pph21_company"]
        self.assertEqual(paid, P.monthly_for_slip(res, "TK/0").tax)                  # TER on bruto as it is
        self.assertGreater(paid, 0)
        self.assertEqual((slip.gross, slip.net), (D(before["gross"]), D(before["net"])))
        self.assertTrue(any("ditanggung perusahaan (tanpa gross-up)" in n for n in res["notes"]), res["notes"])
        self.assertGreaterEqual(slip.employer_cost, paid)                            # in "Ditanggung perusahaan"

    def test_gross_up_unchanged_for_everyone_already_ticked(self):
        run = self.make_run()
        Employee.objects.filter(pk=self.andi.pk).update(pph21_by_company=True)       # pph21_gross_up default True
        self.on()
        res = self.recalc(run["id"]).result
        self.assertEqual(lines(res, "earnings")["pph21_allowance"], lines(res, "deductions")["pph21"])
        self.assertNotIn("pph21_company", lines(res, "employer"))

    def test_december_borne_settles_without_a_refund_to_the_employee(self):
        run = self.make_run()
        PayRun.objects.filter(pk=run["id"]).update(pay_date=date(2026, 12, 5))      # masa Desember
        Pph21Opening.objects.create(organization=self.org, employee=self.andi, year=2026, months=10,
                                    bruto=D("101000000"), pph=D("1515000"), iuran=D("0"))
        Employee.objects.filter(pk=self.andi.pk).update(pph21_by_company=True, pph21_gross_up=False)
        self.on()
        res = self.recalc(run["id"]).result
        self.assertTrue(any(n.startswith("PPh 21 setahun 2026: 11 bulan") for n in res["notes"]), res["notes"])
        self.assertNotIn("pph21_refund", lines(res, "earnings"))
        self.assertNotIn("pph21", lines(res, "deductions"))
        plain = P.monthly_for_slip(res, "TK/0")
        due = P.annual_pph(D("101000000") + plain.bruto, 11, Y.iuran_from_slip(res), "TK/0", D("1515000")).due
        self.assertEqual(lines(res, "employer").get("pph21_company", D("0")), max(due, D("0")))

    def test_employee_api_keeps_the_choice(self):
        r = self.client.patch(f"/api/hr/employees/{self.andi.pk}/", {"pph21_by_company": True, "pph21_gross_up": False},
                              format="json")
        self.assertEqual(r.status_code, 200, r.data)
        self.andi.refresh_from_db()
        self.assertEqual((self.andi.pph21_by_company, self.andi.pph21_gross_up), (True, False))

    def test_slip_book_prints_it(self):
        run = self.make_run()
        Employee.objects.filter(pk=self.andi.pk).update(pph21_by_company=True, pph21_gross_up=False)
        self.on()
        paid = lines(self.recalc(run["id"]).result, "employer")["pph21_company"]
        r = self.client.get(f"/api/hr/payroll/runs/{run['id']}/slips/")
        self.assertEqual(r.status_code, 200, getattr(r, "data", None))
        andi = next(s for s in r.data["slips"] if s["employee"]["full_name"] == "Andi")
        self.assertEqual(D(andi["company_tax"]), paid)


for _name in [n for n in dir(base.PayRunTests) if n.startswith("test_")]:
    setattr(BorneTests, _name, None)
