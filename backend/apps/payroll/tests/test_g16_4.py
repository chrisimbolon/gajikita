"""
G16-4 (23 Nov 2026) — hak akhir under UU No. 27/2026 (pesangon, UPMK, UPH, uang pisah, kompensasi PKWT), the PPh 21
final (PP 68/2009), overrides with a reason, the last payslip, the settings and the law row. Made-up people/amounts.
"""
from datetime import date
from decimal import Decimal as D

from django.test import SimpleTestCase

from apps.core.models import AuditEntry
from apps.employees.models import Employee
from apps.payroll import final_pay as F
from apps.payroll import pph21
from apps.payroll import pph21_slip
from apps.payroll import pph21_year
from apps.payroll.engine import SlipLine
from apps.payroll.models import FinalPay, PayRunItem, PayRunLine, PayrollSettings
from apps.payroll.tests import test_payrun as base

URL = "/api/hr/payroll/final-pay/"


def inputs(**kw):
    d = dict(reason="retire", join_date=date(2020, 3, 1), end_date=date(2026, 7, 15), upah=D("5000000"),
             leave_days=D("5"))
    d.update(kw)
    return F.Inputs(**d)


class FinalPayRuleTests(SimpleTestCase):
    def test_masa_kerja_counts_the_last_day(self):
        self.assertEqual(F.service(date(2020, 3, 1), date(2026, 2, 28)), (6, 0, 0))
        self.assertEqual(F.service(date(2020, 3, 1), date(2026, 7, 15)), (6, 4, 15))
        self.assertEqual(F.service_text(6, 4, 15), "6 tahun 4 bulan")

    def test_the_two_tables(self):
        self.assertEqual([F.pesangon_months(y) for y in (0, 1, 7, 8, 20)], [1, 2, 8, 9, 9])
        self.assertEqual([F.upmk_months(y) for y in (2, 3, 5, 6, 23, 24)], [0, 2, 2, 3, 8, 10])

    def test_pp68_bands(self):
        self.assertEqual(F.final_tax(D("50000000"))[0], 0)
        self.assertEqual(F.final_tax(D("85833335"))[0], D("1791667"))
        self.assertEqual(F.final_tax(D("600000000"))[0], D("87500000"))   # 0 + 2,5 jt + 60 jt + 25 jt

    def test_retirement_example(self):
        r = F.compute(inputs())
        amounts = {l["key"]: D(l["amount"]) for l in r["lines"]}
        self.assertEqual(amounts, {"pesangon": D("70000000"), "upmk": D("15000000"), "uph_leave": D("833333")})
        self.assertEqual((r["total"], r["tax"]["amount"], r["net"]), ("85833333", "1791667", "84041666"))   # G16-4.1
        r = F.compute(inputs(reason="resign", upah=D("2800000"), leave_days=D("12")))
        self.assertEqual([l["amount"] for l in r["lines"] if l["key"] == "uph_leave"], ["1120000"])
        self.assertEqual(r["service"]["text"], "6 tahun 4 bulan")

    def test_resignation_gets_uang_pisah_and_an_override_needs_no_law(self):
        r = F.compute(inputs(reason="resign", upah=D("4000000"), leave_days=D("0")))
        self.assertEqual([(l["key"], l["amount"]) for l in r["lines"]], [("separation", "4000000")])
        r = F.compute(inputs(reason="resign", upah=D("4000000"), leave_days=D("0"),
                             overrides={"separation": {"amount": "2000000", "reason": "Aturan perusahaan"}}))
        line = r["lines"][0]
        self.assertEqual((line["amount"], line["law_amount"], line["changed"]), ("2000000", "4000000", True))
        self.assertTrue(any("berbeda dari UU" in n for n in r["notes"]))

    def test_contract_end_and_closure(self):
        r = F.compute(inputs(reason="contract_end", join_date=date(2026, 1, 1), end_date=date(2026, 6, 30),
                             upah=D("3000000"), leave_days=D("0")))
        self.assertEqual([(l["key"], l["amount"]) for l in r["lines"]], [("compensation", "1500000")])
        r = F.compute(inputs(reason="closure", join_date=date(2022, 1, 1), end_date=date(2026, 6, 30),
                             upah=D("3000000"), leave_days=D("0")))
        upmk = [l for l in r["lines"] if l["key"] == "upmk"][0]
        self.assertEqual((upmk["basis"], upmk["amount"]), ("1,5 × 2 bulan upah", "9000000"))

    def test_bad_input(self):
        with self.assertRaises(ValueError):
            F.compute(inputs(reason="efisiensi"))
        with self.assertRaises(ValueError):
            F.compute(inputs(end_date=date(2019, 1, 1)))

    def test_hak_akhir_never_counts_as_monthly_pay_or_tax(self):
        result = {"earnings": [{"code": "base", "amount": "4000000"}, {"code": "pesangon_uang", "amount": "70000000"}],
                  "deductions": [{"code": "pph21_final", "label": F.TAX_LABEL, "amount": "1791667"}], "employer": []}
        self.assertEqual(pph21.bruto_from_slip(result).total, D("4000000"))
        self.assertIsNone(pph21_year.withheld_from_slip(result))

        class Slip:
            deductions = [SlipLine("pph21_final", F.TAX_LABEL, D("1791667"))]
        self.assertEqual(pph21_slip.manual_pph(Slip), [])


class FinalPayApiTests(base.PayRunTests):
    def body(self, who, **kw):
        d = {"employee": str(who.id), "end_date": "2026-10-20", "reason": "resign", "leave_days": "0"}
        d.update(kw)
        return d

    def test_preview_save_and_list(self):
        Employee.objects.filter(pk=self.andi.pk).update(join_date=date(2020, 3, 1))
        r = self.client.post(URL + "preview/", self.body(self.andi, reason="retire"), format="json")
        self.assertEqual(r.status_code, 200, r.data)
        expected = F.compute(inputs(end_date=date(2026, 10, 20), upah=D("4000000"), leave_days=D("0")))
        self.assertEqual(r.data["result"]["total"], expected["total"])
        r = self.client.post(URL, self.body(self.andi, reason="retire"), format="json")
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(FinalPay.objects.filter(employee=self.andi).count(), 1)
        self.assertTrue(AuditEntry.objects.filter(organization=self.org, action="payroll.final_pay").exists())
        page = self.client.get(URL, {"employee": str(self.andi.id)}).data
        self.assertEqual((len(page["records"]), page["defaults"]["upah"]), (1, "4000000"))

    def test_a_changed_amount_needs_a_reason(self):
        r = self.client.post(URL, self.body(self.andi, overrides={"separation": {"amount": "1000", "reason": ""}}),
                             format="json")
        self.assertEqual(r.status_code, 400)

    def test_attach_to_the_last_payslip_and_take_it_off(self):
        run = self.make_run()                                                # 26 Sep - 25 Okt
        rec = self.client.post(URL, self.body(self.andi), format="json").data["record"]
        r = self.client.post(f"{URL}{rec['id']}/attach/", format="json")
        self.assertEqual(r.status_code, 200, r.data)
        line = PayRunLine.objects.get(run_id=run["id"], employee=self.andi)
        earnings = {e["code"]: D(e["amount"]) for e in line.result["earnings"]}
        self.assertEqual(earnings["pesangon_pisah"], D("4000000"))           # 1 month of upah
        self.assertEqual(pph21.bruto_from_slip(line.result).total < D("8000000"), True)
        self.andi.refresh_from_db()
        self.assertEqual(self.andi.end_date, date(2026, 10, 20))
        self.assertEqual(self.client.delete(f"{URL}{rec['id']}/").status_code, 200)
        self.assertFalse(PayRunItem.objects.filter(line=line, code__startswith="pesangon_").exists())

    def test_the_final_tax_is_a_deduction_on_the_slip(self):
        run = self.make_run()
        Employee.objects.filter(pk=self.budi.pk).update(join_date=date(2010, 1, 1), base_rate=D("10000000"))
        rec = self.client.post(URL, self.body(self.budi, reason="retire"), format="json").data["record"]
        self.assertEqual(self.client.post(f"{URL}{rec['id']}/attach/", format="json").status_code, 200)
        line = PayRunLine.objects.get(run_id=run["id"], employee=self.budi)
        deds = {d["code"]: D(d["amount"]) for d in line.result["deductions"]}
        self.assertEqual(deds["pph21_final"], D(rec["result"]["tax"]["amount"]))
        self.assertGreater(deds["pph21_final"], 0)

    def test_a_locked_payroll_is_never_changed(self):
        run = self.make_run()
        rec = self.client.post(URL, self.body(self.andi), format="json").data["record"]
        self.client.post(f"{base.RUNS}{run['id']}/lock/", {"action": "lock"}, format="json")
        r = self.client.post(f"{URL}{rec['id']}/attach/", format="json")
        self.assertEqual(r.status_code, 400)
        self.assertIn("dikunci", r.data["message"])

    def test_settings_and_law_row(self):
        rows = {x["key"]: x for x in self.client.get("/api/hr/payroll/law-check/").data["rows"]}
        self.assertEqual(rows["separation"]["status"], "ok")
        r = self.client.patch("/api/hr/payroll/settings/", {"separation_pay_months": "0.5"}, format="json")
        self.assertEqual(r.status_code, 200, r.data)
        rows = {x["key"]: x for x in self.client.get("/api/hr/payroll/law-check/").data["rows"]}
        self.assertEqual(rows["separation"]["status"], "differs")
        rec = self.client.post(URL + "preview/", self.body(self.andi), format="json").data["result"]
        self.assertEqual(rec["lines"][0]["amount"], "2000000")


for _name in [n for n in dir(base.PayRunTests) if n.startswith("test_")]:
    setattr(FinalPayApiTests, _name, None)
