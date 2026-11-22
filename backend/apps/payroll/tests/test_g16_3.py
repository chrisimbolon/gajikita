"""
G16-3 (22 Nov 2026) — PPh 21 on the slip (switch, default off): monthly TER, gross-up, the December settlement,
the refund line, the manual-item guard and the readiness numbers. Made-up people and amounts.
"""
from datetime import date
from decimal import Decimal as D

from apps.employees.models import Employee
from apps.payroll import payrun
from apps.payroll import pph21 as P
from apps.payroll.models import PayRun, PayRunItem, PayRunLine, PayrollSettings, Pph21Opening
from apps.payroll.tests import test_payrun as base


def lines(res, kind):
    return {x["code"]: D(x["amount"]) for x in res[kind]}


class Pph21SlipTests(base.PayRunTests):
    def setUp(self):
        super().setUp()
        Employee.objects.filter(pk=self.andi.pk).update(base_rate=D("10000000"))

    def on(self, **extra):
        PayrollSettings.objects.filter(organization=self.org).update(pph21_enabled=True, **extra)

    def recalc(self, run_id, name="Andi"):
        line = PayRunLine.objects.select_related("employee", "run").get(run_id=run_id, employee__full_name=name)
        return payrun.calculate_line(line, PayrollSettings.for_org(self.org)).result

    def test_off_by_default(self):
        res = self.line(self.make_run()["id"], "Andi")["result"]
        self.assertNotIn("pph21", lines(res, "deductions"))

    def test_monthly_ter(self):
        self.on()
        res = self.line(self.make_run()["id"], "Andi")["result"]        # Oct, paid 5 Nov: masa Nov
        tax = lines(res, "deductions")["pph21"]
        self.assertGreater(tax, 0)
        self.assertEqual(tax, P.monthly_for_slip(res, "TK/0").tax)       # the PPh lines are not bruto

    def test_tax_paid_by_the_company_leaves_take_home_pay_alone(self):
        run = self.make_run()
        before = self.line(run["id"], "Andi")["net"]
        Employee.objects.filter(pk=self.andi.pk).update(pph21_by_company=True)
        self.on()
        res = self.recalc(run["id"])
        self.assertEqual(lines(res, "earnings")["pph21_allowance"], lines(res, "deductions")["pph21"])
        line = PayRunLine.objects.get(run_id=run["id"], employee=self.andi)
        self.assertEqual(payrun.calculate_line(line, PayrollSettings.for_org(self.org)).net, D(before))

    def test_a_manual_pph_item_wins(self):
        run = self.make_run()
        line = PayRunLine.objects.get(run_id=run["id"], employee=self.andi)
        PayRunItem.objects.create(line=line, kind=PayRunItem.Kind.DEDUCTION, code="potongan", label="PPh 21 bulan ini",
                                  amount=D("150000"))
        self.on()
        res = self.recalc(run["id"])
        self.assertEqual(lines(res, "deductions").get("pph21"), None)
        self.assertTrue(any("otomatis tidak dihitung" in w for w in res["warnings"]))

    def test_december_settles_the_year(self):
        run = self.make_run()
        PayRun.objects.filter(pk=run["id"]).update(pay_date=date(2026, 12, 5))      # masa Desember
        Pph21Opening.objects.create(organization=self.org, employee=self.andi, year=2026, months=10,
                                    bruto=D("101000000"), pph=D("1515000"), iuran=D("0"))
        self.on()
        res = self.recalc(run["id"])
        self.assertTrue(any(n.startswith("PPh 21 setahun 2026: 11 bulan") for n in res["notes"]))
        plain = P.monthly_for_slip(res, "TK/0", by_company=False)
        expected = P.annual_pph(D("101000000") + plain.bruto, 11, D("0") + lines(res, "deductions").get("jht_employee", D("0")),
                                "TK/0", D("1515000")).due
        got = lines(res, "deductions").get("pph21", D("0")) - lines(res, "earnings").get("pph21_refund", D("0"))
        self.assertEqual(got, expected)

    def test_december_refund_is_an_earning(self):
        run = self.make_run()
        PayRun.objects.filter(pk=run["id"]).update(pay_date=date(2026, 12, 5))
        Pph21Opening.objects.create(organization=self.org, employee=self.andi, year=2026, months=10,
                                    bruto=D("40000000"), pph=D("3000000"), iuran=D("0"))
        self.on()
        res = self.recalc(run["id"])
        self.assertGreater(lines(res, "earnings")["pph21_refund"], 0)
        self.assertNotIn("pph21", lines(res, "deductions"))

    def test_december_without_saldo_awal_falls_back_to_ter(self):
        run = self.make_run()
        PayRun.objects.filter(pk=run["id"]).update(pay_date=date(2026, 12, 5))
        self.on()
        res = self.recalc(run["id"])
        self.assertTrue(any("belum dihitung" in w for w in res["warnings"]))
        self.assertEqual(lines(res, "deductions")["pph21"], P.monthly_for_slip(res, "TK/0").tax)

    def test_readiness_next_to_the_switch(self):
        self.make_run()
        r = self.client.get("/api/hr/payroll/settings/").data
        self.assertFalse(r["settings"]["pph21_enabled"])
        self.assertEqual(r["pph21_readiness"]["year"], 2026)
        self.assertEqual(r["pph21_readiness"]["missing_opening"], 2)              # Andi, Budi joined 2025
        self.assertGreaterEqual(r["pph21_readiness"]["ptkp_unchecked"], 3)


for _name in [n for n in dir(base.PayRunTests) if n.startswith("test_")]:
    setattr(Pph21SlipTests, _name, None)
