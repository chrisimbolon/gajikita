"""
G16-1 (20 Nov 2026) — BPJS from the reported wage, Jaminan Pensiun, PPh 21 bruto per Pak Holan. Made-up people.
"""
from decimal import Decimal as D
from io import StringIO

from django.core.management import call_command
from django.test import SimpleTestCase

from apps.employees.models import Employee
from apps.payroll import pph21 as P
from apps.payroll.engine import EmployeeTerms, PayrollRules, PeriodInput, calculate
from apps.payroll.models import PayrollSettings
from apps.payroll.tests import test_payrun as base

RULES = PayrollRules(jkk=D("0.0089"))


def lines(slip):
    return ({l.code: l.amount for l in slip.deductions}, {l.code: l.amount for l in slip.employer})


class BpjsEngineTests(SimpleTestCase):
    def test_reported_wage_drives_every_bpjs_line(self):
        ded, emp = lines(calculate(EmployeeTerms(base_salary=D("4500000"), bpjs_wage=D("4000000")), PeriodInput(), RULES))
        self.assertEqual((ded["jht_employee"], emp["jht_company"], emp["jkk"], emp["jkm"]),
                         (D("80000"), D("148000"), D("35600"), D("12000")))        # the BPJSTK sheet, Arief
        ded, _ = lines(calculate(EmployeeTerms(base_salary=D("4500000")), PeriodInput(), RULES))
        self.assertEqual(ded["jht_employee"], D("90000"))                          # empty = gaji pokok, as before

    def test_jp_is_off_unless_the_person_is_in_it(self):
        ded, emp = lines(calculate(EmployeeTerms(base_salary=D("4000000")), PeriodInput(), RULES))
        self.assertNotIn("jp_employee", ded)
        self.assertNotIn("jp_company", emp)

    def test_jp_taken_from_pay_by_default(self):
        slip = calculate(EmployeeTerms(base_salary=D("4000000"), jp=True), PeriodInput(), RULES)
        ded, emp = lines(slip)
        self.assertEqual((ded["jp_employee"], emp["jp_company"]), (D("40000"), D("80000")))

    def test_jp_paid_by_the_company_leaves_take_home_pay_alone(self):
        plain = calculate(EmployeeTerms(base_salary=D("4000000")), PeriodInput(), RULES)
        rules = PayrollRules(jkk=D("0.0089"), jp_by_company=True)
        slip = calculate(EmployeeTerms(base_salary=D("4000000"), jp=True), PeriodInput(), rules)
        ded, emp = lines(slip)
        self.assertNotIn("jp_employee", ded)
        self.assertEqual((emp["jp_employee_company"], emp["jp_company"]), (D("40000"), D("80000")))
        self.assertEqual(slip.net, plain.net)

    def test_jp_wage_cap(self):
        rules = PayrollRules(jkk=D("0.0089"), jp_wage_cap=D("10547400"))
        ded, _ = lines(calculate(EmployeeTerms(base_salary=D("12000000"), jp=True), PeriodInput(), rules))
        self.assertEqual(ded["jp_employee"], D("105474"))

    def test_no_bpjs_tk_means_no_jp(self):
        ded, emp = lines(calculate(EmployeeTerms(base_salary=D("4000000"), jp=True, bpjs_tk=False), PeriodInput(), RULES))
        self.assertEqual((ded.get("jp_employee"), emp.get("jp_company")), (None, None))


class Pph21BrutoTests(SimpleTestCase):
    RESULT = {"earnings": [{"code": "base", "amount": "4500000"}, {"code": "overtime", "amount": "1100000"},
                           {"code": "meal", "amount": "315000"}, {"code": "bpjs", "amount": "35000"}],
              "deductions": [{"code": "late", "amount": "10000"}, {"code": "jht_employee", "amount": "80000"}],
              "employer": [{"code": "jkk", "amount": "35600"}, {"code": "jkm", "amount": "12000"},
                           {"code": "jp_employee_company", "amount": "40000"}]}

    def test_holans_answers(self):
        b = P.bruto_from_slip(self.RESULT, late_reduces=True)
        self.assertEqual(b.total, D("6027600"))                  # 5.997.600 - late 10.000 + JP 40.000
        self.assertEqual(P.bruto_from_slip(self.RESULT, late_reduces=False, company_jp_in_bruto=False).total,
                         D("5997600"))                           # the October book

    def test_arief_with_jp_pays_300_more(self):
        self.assertEqual(P.monthly_pph(D("5997600"), "TK/0")[1], D("44982"))
        self.assertEqual(P.monthly_pph(D("6037600"), "TK/0")[1], D("45282"))

    def test_gross_up_for_tax_paid_by_the_company(self):
        m = P.monthly_for_slip({"earnings": [{"code": "base", "amount": "10000000"}],
                                "employer": [{"code": "jkk", "amount": "89000"}, {"code": "jkm", "amount": "30000"}]},
                               "K/2", by_company=True)
        self.assertEqual((m.tax, m.bruto), (D("154096"), D("10273096")))
        m = P.monthly_for_slip({"earnings": [{"code": "base", "amount": "10000000"}],
                                "employer": [{"code": "jkk", "amount": "89000"}, {"code": "jkm", "amount": "30000"}]},
                               "K/2", by_company=False)
        self.assertEqual(m.tax, D("151785"))


class BpjsRunTests(base.PayRunTests):
    def test_reported_wage_and_jp_on_the_run(self):
        Employee.objects.filter(pk=self.andi.pk).update(bpjs_wage=D("3000000"), jp_enrolled=True)
        PayrollSettings.objects.filter(organization=self.org).update(jp_employee_by_company=True)
        run = self.make_run()
        res = self.line(run["id"], "Andi")["result"]
        ded = {d["code"]: D(d["amount"]) for d in res["deductions"]}
        emp = {e["code"]: D(e["amount"]) for e in res["employer"]}
        self.assertEqual(ded["jht_employee"], D("60000"))
        self.assertNotIn("jp_employee", ded)
        self.assertEqual((emp["jp_employee_company"], emp["jp_company"]), (D("30000"), D("60000")))
        budi = self.line(run["id"], "Budi")["result"]                   # untouched: as before
        self.assertNotIn("jp_company", {e["code"] for e in budi["employer"]})

    def test_settings_and_employee_fields(self):
        s = self.client.get("/api/hr/payroll/settings/").data["settings"]
        self.assertEqual((s["jp_employee_by_company"], s["pph21_late_reduces_bruto"], s["pph21_company_jht_in_bruto"]),
                         (False, True, True))
        self.assertEqual(self.client.patch("/api/hr/payroll/settings/", {"jp_wage_cap": "-1"}, format="json").status_code, 400)
        r = self.client.patch(f"/api/hr/employees/{self.andi.pk}/", {"bpjs_wage": "0", "jp_enrolled": True}, format="json")
        self.assertEqual(r.status_code, 200, r.data)
        self.andi.refresh_from_db()
        self.assertEqual((self.andi.bpjs_wage, self.andi.jp_enrolled), (None, True))   # 0 = empty = gaji pokok

    def test_law_check_rows(self):
        Employee.objects.filter(pk=self.andi.pk).update(bpjs_wage=D("3000000"), jp_enrolled=True)
        rows = {r["key"]: r for r in self.client.get("/api/hr/payroll/law-check/").data["rows"]}
        self.assertEqual((rows["bpjs_wage"]["status"], rows["bpjs_wage"]["people"]), ("found", ["Andi"]))
        self.assertEqual(rows["jp"]["status"], "missing")                          # no wage cap yet
        PayrollSettings.objects.filter(organization=self.org).update(jp_wage_cap=D("10547400"))
        rows = {r["key"]: r for r in self.client.get("/api/hr/payroll/law-check/").data["rows"]}
        self.assertEqual(rows["jp"]["status"], "ok")

    def test_preview_uses_the_settings_and_grosses_up(self):
        Employee.objects.filter(pk=self.andi.pk).update(pph21_by_company=True)
        self.make_run()
        out = StringIO()
        call_command("pph21_preview", period="2026-10", org="Beton", stdout=out)
        text = out.getvalue()
        self.assertIn("potong telat: ya", text)
        self.assertIn("gross-up", text)


for _name in [n for n in dir(base.PayRunTests) if n.startswith("test_")]:
    setattr(BpjsRunTests, _name, None)
